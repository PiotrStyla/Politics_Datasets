#!/usr/bin/env python3
"""Snapshot and replay four Polish Open AGH chemistry textbooks."""
from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path
import platform
import pprint
import re
import shutil
import threading
import time
import unicodedata
import xml.etree.ElementTree as ET
import zipfile

from bs4 import BeautifulSoup, Comment, NavigableString
import requests

BASE = "https://epodreczniki.open.agh.edu.pl"
BOOK_IDS = (29, 1394, 37, 1893)
SOURCE = "open_agh_chemistry_pl"
OWN_REPO = "PiotrSty/open-agh-chemistry-pl"
TARGET = "SlayerLab/polish-dynaword"
LICENSE = "CC-BY-SA-4.0"
FIELDS = ["id", "text", "source", "added", "created", "token_count", "license", "author"]
LOCK = threading.Lock()
NEXT = 0.0


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(value).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def lines(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), encoding="utf-8")


def read_lines(path):
    return [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines() if s]


def get(url):
    global NEXT
    for attempt in range(5):
        with LOCK:
            wait = max(0, NEXT - time.monotonic())
            NEXT = max(time.monotonic(), NEXT) + 0.4
        time.sleep(wait)
        response = requests.get(url, timeout=(20, 100), headers={
            "User-Agent": "OpenAGHTextResearch/1.0 (PiotrSty; four-book text corpus)", "Accept-Language": "pl"})
        if response.status_code not in (429, 500, 502, 503, 504):
            response.raise_for_status()
            return response
        time.sleep(2 ** attempt)
    response.raise_for_status()


def walk(items, chapter=""):
    for item in items:
        module = item.get("_embedded", {}).get("module")
        if module:
            yield module, chapter
        else:
            yield from walk(item.get("children", []), item.get("title", chapter))


def license_from_epub(payload, book_id):
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        rights = archive.read("OEBPS/main.xhtml")
    document = ET.fromstring(rights)
    text = " ".join(" ".join(document.itertext()).split())
    links = [n.attrib["href"] for n in document.iter() if "href" in n.attrib]
    if not any("creativecommons.org/licenses/by-sa/4.0" in link for link in links):
        raise ValueError("Missing book-specific CC BY-SA 4.0 link")
    if "Na tych samych warunkach" not in text or f"/handbook/{book_id}" not in text:
        raise ValueError("Book-specific rights/identity evidence missing")
    if re.search(r"(?i)licenses/by-nc|CC\s*BY[- ]NC", text + " ".join(links)):
        raise ValueError("Noncommercial marker in rights page")
    return {"license": LICENSE, "epub_url": f"{BASE}/rpc/preview/handbooks/{book_id}/epub/light",
        "epub_sha256": sha(payload), "rights_xhtml": rights.decode("utf-8"),
        "rights_sha256": sha(rights), "rights_text": text, "links": links,
        "observed_at": now()}


def discover(out):
    from huggingface_hub import HfApi
    if (out / "inventory.json").exists():
        raise ValueError("Inventory already exists; use a fresh output for a new snapshot")
    out.mkdir(parents=True, exist_ok=True)
    api = HfApi(token=False)
    target = api.dataset_info(TARGET)
    registry = get(f"https://huggingface.co/datasets/{TARGET}/resolve/{target.sha}/src/sources.py").content.decode("utf-8")
    discussions = [{"num": d.num, "title": d.title, "status": d.status} for d in api.get_repo_discussions(TARGET, repo_type="dataset")]
    if SOURCE in registry or any(re.search(r"(?i)\bAGH\b", d["title"]) for d in discussions):
        raise ValueError("AGH registration/proposal found; inspect before creating another")
    (out / "target_sources.py").write_text(registry, encoding="utf-8")
    save(out / "target_audit.json", {"repository": TARGET, "revision": target.sha, "observed_at": now(),
        "registry_sha256": sha(registry.encode()), "files": [s.rfilename for s in target.siblings], "discussions": discussions,
        "cross_source_dedup": "pending; registry and title checks do not establish text novelty"})
    books = []
    for book_id in BOOK_IDS:
        response = get(f"{BASE}/rest/handbooks/{book_id}?lang=auto")
        book = response.json()
        meta = book["_embedded"]["metadata"]
        if book["id"] != book_id or meta["in_language"] != "pl" or meta.get("private_token") or meta.get("ai_based"):
            raise ValueError("Unexpected/private/non-Polish/AI-marked edition")
        item_response = get(book["_links"]["items"]["href"])
        occurrences = []
        for module, chapter in walk(item_response.json()):
            embedded = module["_embedded"]
            occurrences.append({"module_id": module["id"], "title": module["title"], "chapter": chapter,
                "revision": embedded["revision"]["version"],
                "authors": [" ".join([a["firstname"], a["lastname"]]) for a in embedded["authors"]],
                "preview_url": next(f["_links"]["preview"]["href"] for f in embedded["formats"] if f["type"] == "html"),
                "module_url": module["_links"]["self"]["href"],
                "reader_url": f"{BASE}/handbook/{book_id}/module/{module['id']}/reader"})
        rights_url = next(f["_links"]["preview"]["href"] for f in book["_embedded"]["formats"] if f["type"] == "epub/light")
        rights = license_from_epub(get(rights_url).content, book_id)
        books.append({"id": book_id, "title": book["title"], "url": f"{BASE}/handbook/{book_id}",
            "observed_at": now(), "metadata_sha256": sha(response.content), "items_sha256": sha(item_response.content),
            "metadata": {k: meta.get(k) for k in ("publisher", "publish_time", "update_time", "isbn", "reviewers", "in_language", "ai_based")},
            "license_evidence": rights, "occurrences": occurrences})
        save(out / "inventory_progress.json", books)
        print(f"Verified book {book_id}: {len(occurrences)} modules; {LICENSE}", flush=True)
    save(out / "inventory.json", books)


def module_map(books):
    modules = {}
    for book in books:
        for item in book["occurrences"]:
            mid = item["module_id"]
            if mid in modules and any(modules[mid][key] != item[key] for key in ("title", "revision", "authors")):
                raise ValueError("Shared module has inconsistent identity/version/authors")
            modules[mid] = item
    return modules


def fetch_one(out, module):
    path = out / "cache" / f"{module['module_id']}.json.gz"
    if path.exists():
        row = json.loads(gzip.decompress(path.read_bytes()))
        if row["revision"] != module["revision"] or row["html_sha256"] != sha(row["html"].encode()):
            raise ValueError("Stale or corrupt module cache")
        return row
    response = get(module["preview_url"])
    html = response.content.decode("utf-8")
    current = get(module["module_url"]).json()
    if current["_embedded"]["revision"]["version"] != module["revision"] or current["title"] != module["title"]:
        raise ValueError("Module changed since inventory; acquire a new snapshot")
    row = {"module_id": module["module_id"], "revision": module["revision"], "preview_url": module["preview_url"],
        "observed_at": now(), "html": html, "html_sha256": sha(html.encode()), "response_sha256": sha(response.content)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(json.dumps(row, ensure_ascii=False, sort_keys=True).encode(), mtime=0))
    return row


def fetch(out):
    modules = module_map(read(out / "inventory.json"))
    rows, failures = [], []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(fetch_one, out, module): mid for mid, module in sorted(modules.items())}
        for count, future in enumerate(as_completed(futures), 1):
            try:
                rows.append(future.result())
            except Exception as error:
                failures.append({"module_id": futures[future], "error": str(error)})
            if count % 25 == 0 or count == len(futures):
                print(f"Fetched {count}/{len(futures)}; failures={len(failures)}", flush=True)
    save(out / "fetch_failures.json", failures)
    if failures:
        raise ValueError("Fetch incomplete; inspect failures then rerun to resume")
    lines(out / "modules.jsonl", sorted(rows, key=lambda r: r["module_id"]))


def normalize(text):
    text = unicodedata.normalize("NFKC", text).replace("\u00ad", "").replace("\u200b", "")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(re.sub(r"[ \t\xa0]+", " ", s).strip() for s in text.splitlines())).strip()


def text_key(text):
    return " ".join(normalize(text).casefold().split())


def extract(html):
    soup = BeautifulSoup(html, "html.parser")
    if soup.find(["html", "body"]) or soup.select_one('#root, form[action*="login"]'):
        raise ValueError("Expected module fragment, received a shell/login document")
    changes = Counter()
    for node in list(soup.select("script, style, nav, figure, img, video, audio, iframe, svg")):
        if node.parent is not None:
            node.decompose()
            changes["media_or_ui_removed"] += 1
    for comment in soup.find_all(string=lambda n: isinstance(n, Comment)):
        comment.extract()
    # Collapse physical source wrapping before inserting semantic paragraph breaks.
    for node in list(soup.find_all(string=True)):
        node.replace_with(NavigableString(re.sub(r"\s+", " ", str(node))))
    for node in list(soup.find_all(["sub", "sup"])):
        node.replace_with(NavigableString(("_" if node.name == "sub" else "^") + "{" + node.get_text() + "}"))
    for node in soup.find_all(["br", "hr"]):
        node.replace_with(NavigableString("\n"))
    for node in soup.find_all(["td", "th"]):
        node.append(NavigableString(" | "))
    for node in soup.find_all(["p", "div", "section", "h1", "h2", "h3", "h4", "h5", "li", "table", "tr", "blockquote"]):
        node.insert_before(NavigableString("\n\n"))
        node.insert_after(NavigableString("\n\n"))
    text = normalize(soup.get_text())
    for name, pattern in (
        ("email", r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
        ("labelled_phone", r"(?i)(?:\btelefon|\btel\.)\s*:?\s*(?:\+48\s*)?\d(?:[ .-]?\d){8}\b"),
    ):
        text, count = re.subn(pattern, "[REDACTED:" + name.upper() + "]", text)
        changes[name] += count
    changes["unbalanced_math_delimiters"] = int(text.count(r"\(") != text.count(r"\)") or text.count(r"\[") != text.count(r"\]"))
    return text, dict(changes)


def near_dedup(rows):
    from datasketch import MinHash, MinHashLSH
    index, features, kept, dropped = MinHashLSH(threshold=0.8, num_perm=128), {}, [], []
    for row in rows:
        words = re.findall(r"\w+", text_key(row["text"]))
        shingles = {" ".join(words[i:i + 5]).encode() for i in range(max(0, len(words) - 4))}
        signature = MinHash(num_perm=128, seed=1)
        if not shingles:
            kept.append(row)
            continue
        signature.update_batch(sorted(shingles))
        for other in sorted(index.query(signature)):
            score = len(shingles & features[other]) / len(shingles | features[other])
            if score >= 0.9:
                dropped.append({"id": row["id"], "duplicate_of": other, "jaccard": score})
                break
        else:
            kept.append(row)
            features[row["id"]] = shingles
            index.insert(row["id"], signature)
    return kept, dropped


def registry(base):
    tree = ast.parse(base)
    node = next(n.value for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SOURCES" for t in n.targets))
    if SOURCE in ast.literal_eval(node):
        raise ValueError("Source already registered")
    entry = {"file_key": SOURCE, "pretty": "Open AGH - four Polish chemistry textbooks", "license": LICENSE, "license_spdx": LICENSE,
        "traceable": "Each contributed Polish edition includes explicit CC BY-SA 4.0 terms in its preserved official EPUB rights page. Authors, AGH attribution, original URLs and changes are preserved.",
        "upstream": BASE, "provenance": "Pinned PiotrSty/open-agh-chemistry-pl source snapshot; public AGH module previews with observed revision identifiers and per-module author attribution.",
        "domain": "educational/chemistry/materials", "created": "2018-2024 (book publication metadata proxy)", "is_ocr": False, "custom_datasheet": True}
    offset = sum(len(s) for s in base.splitlines(keepends=True)[:node.lineno - 1]) + node.col_offset + 1
    return base[:offset] + "\n    " + repr(SOURCE) + ": " + pprint.pformat(entry, width=96, sort_dicts=False).replace("\n", "\n    ") + "," + base[offset:]


def build(out):
    import pyarrow as pa
    import pyarrow.parquet as pq
    import tiktoken
    from langid.langid import LanguageIdentifier, model
    started = now()
    code_digest = sha(Path(__file__).read_bytes())
    books = read(out / "inventory.json")
    if {b["id"] for b in books} != set(BOOK_IDS):
        raise ValueError("Four-book allowlist mismatch")
    modules = module_map(books)
    snapshot = read_lines(out / "modules.jsonl")
    if {r["module_id"] for r in snapshot} != set(modules) or len(snapshot) != len(modules):
        raise ValueError("Incomplete/duplicated module snapshot")
    memberships = defaultdict(list)
    for book in books:
        for occurrence in book["occurrences"]:
            memberships[occurrence["module_id"]].append({"book_id": book["id"], "book_title": book["title"], "book_url": book["url"],
                "publish_time": book["metadata"]["publish_time"], "isbn": book["metadata"]["isbn"], "reader_url": occurrence["reader_url"], "chapter": occurrence["chapter"]})
    encoder = tiktoken.get_encoding("cl100k_base")
    lang = LanguageIdentifier.from_modelstring(model, norm_probs=True)
    lang.set_languages(["pl", "en", "de", "cs", "sk", "uk", "ru", "fr"])
    rows, sidecars, decisions, seen = [], [], {}, {}
    totals = Counter()
    added = min(r["observed_at"][:10] for r in snapshot)
    for raw in snapshot:
        mid = raw["module_id"]
        module = modules[mid]
        if raw["html_sha256"] != sha(raw["html"].encode()) or raw["revision"] != module["revision"]:
            raise ValueError("Module checksum/revision mismatch")
        body, operations = extract(raw["html"])
        totals.update(operations)
        reason = ""
        if re.match(r"(?i)^(informacj[ae]\s+o\s+e-podr|bibliografia|spis\s)", module["title"]):
            reason = "frontmatter_or_bibliography"
        elif len(body) < 200:
            reason = "too_short"
        elif operations["unbalanced_math_delimiters"]:
            reason = "unbalanced_math"
        elif len(re.findall(r"[a-zA-Z\u00c0-\u024f]", body)) / len(body) < 0.35:
            reason = "low_letter_ratio"
        language, confidence = lang.classify(body[:12000]) if body else ("unknown", 0.0)
        if not reason and language != "pl" and confidence >= 0.99:
            reason = "non_polish"
        if not module["authors"]:
            reason = "missing_authorship"
        key = text_key(body)
        duplicate = seen.get(key)
        if not reason and duplicate:
            reason = "normalized_duplicate"
        row_id = SOURCE + "_" + str(mid)
        decisions[mid] = {"module_id": mid, "book_ids": [b["book_id"] for b in memberships[mid]], "selected": not bool(reason),
            "reason": reason or "include", "duplicate_of": duplicate, "html_sha256": raw["html_sha256"]}
        if reason:
            continue
        seen[key] = row_id
        text = normalize(module["title"]) + "\n\n" + body
        rows.append({"id": row_id, "text": text, "source": SOURCE, "added": added,
            "created": min(b["publish_time"][:10] for b in memberships[mid]), "token_count": len(encoder.encode_ordinary(text)),
            "license": LICENSE, "author": "; ".join(module["authors"])})
        sidecars.append({"id": row_id, "module_id": mid, "title": module["title"], "observed_revision": raw["revision"],
            "observed_at": raw["observed_at"], "url": memberships[mid][0]["reader_url"], "preview_url": raw["preview_url"],
            "memberships": memberships[mid], "authors": module["authors"], "publisher": "AGH University of Krakow",
            "original_notice": "Wersja oryginalna e-podr\u0119cznika dost\u0119pna na stronie: " + memberships[mid][0]["book_url"],
            "license": LICENSE, "license_url": "https://creativecommons.org/licenses/by-sa/4.0/deed.pl",
            "created_semantics": "book publication metadata proxy, not module authorship date",
            "text_sha256": sha(text.encode()), "html_sha256": raw["html_sha256"], "transformations": operations,
            "language": language, "language_confidence": float(confidence)})
    rows, removed = near_dedup(rows)
    for duplicate in removed:
        mid = int(duplicate["id"].rsplit("_", 1)[1])
        decisions[mid].update(selected=False, reason="near_duplicate", duplicate_of=duplicate["duplicate_of"], jaccard=duplicate["jaccard"])
    ids = {r["id"] for r in rows}
    sidecars = [s for s in sidecars if s["id"] in ids]
    counts = Counter(b["book_id"] for s in sidecars for b in s["memberships"])
    if set(counts) != set(BOOK_IDS):
        raise ValueError("An approved book has no retained text")
    root = out / "hf_repo"
    (root / "data").mkdir(parents=True, exist_ok=True)
    artifacts = root / "artifacts"
    schema = pa.schema([(name, pa.int64() if name == "token_count" else pa.string()) for name in FIELDS])
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), root / "data/train-00000-of-00001.parquet", compression="zstd", row_group_size=128)
    lines(artifacts / "attribution.jsonl", sidecars)
    lines(artifacts / "decisions.jsonl", sorted(decisions.values(), key=lambda r: r["module_id"]))
    samples = {}
    for book_id in BOOK_IDS:
        book_ids = {s["id"] for s in sidecars if any(b["book_id"] == book_id for b in s["memberships"])}
        for row in sorted((r for r in rows if r["id"] in book_ids), key=lambda r: sha(("sample:" + r["id"]).encode()))[:3]:
            samples[row["id"]] = row
    lines(artifacts / "sample.jsonl", list(samples.values()))
    save(artifacts / "books.json", books)
    shutil.copy2(out / "target_audit.json", artifacts / "target_audit.json")
    (artifacts / "modules.jsonl.gz").write_bytes(gzip.compress((out / "modules.jsonl").read_bytes(), mtime=0))
    qa = {"extraction_operations": dict(totals), "normalized_exact_dedup": True, "module_identity_dedup": True,
        "near_dedup": {"algorithm": "seeded MinHashLSH .8 candidates and exact 5-word-shingle Jaccard >=.9", "seed": 1, "num_perm": 128, "removed": len(removed), "limitation": "probabilistic retrieval can miss pairs"},
        "cross_source_exact_dedup_completed": False, "cross_source_near_dedup_completed": False, "benchmark_overlap_check": "pending",
        "limitations": ["figures/media omitted; prose can reference missing figures", "LaTeX preserved, not equation correctness verification", "tables flattened into rows", "email/labelled-phone patterns are not complete PII scrubbing; author attribution retained", "published source snapshots are not de-identified", "API revision is an observed label; source content identity is its snapshot hash"]}
    save(artifacts / "qa.json", qa)
    stats = {"book_count": len(books), "module_occurrences": sum(len(b["occurrences"]) for b in books), "unique_modules": len(snapshot),
        "kept": len(rows), "tokens": sum(r["token_count"] for r in rows), "chars": sum(len(r["text"]) for r in rows),
        "by_book": dict(counts), "drop_by_reason": dict(Counter(d["reason"] for d in decisions.values() if not d["selected"])),
        "tokenizer": "cl100k_base", "sample_count": len(samples), "license": LICENSE, "added": added}
    save(artifacts / "stats.json", stats)
    (root / "src").mkdir(exist_ok=True)
    for name in ("build_open_agh_pl.py", "publish_open_agh_pl.py", "test_build_open_agh_pl.py", "test_open_agh_contribution.py", "open_agh_requirements.txt"):
        shutil.copy2(Path(__file__).with_name(name), root / "src" / name)
    save(artifacts / "run.json", {"started_at": started, "finished_at": now(), "actor_id": "agent:codex", "requested_by": "hf:PiotrSty",
        "code_sha256": code_digest, "input_sha256": sha((out / "modules.jsonl").read_bytes()), "python": platform.python_version(),
        "packages": {n: importlib.metadata.version(n) for n in ("beautifulsoup4", "requests", "pyarrow", "tiktoken", "langid", "datasketch")}})
    save(artifacts / "checksums.json", {p.relative_to(root).as_posix(): sha(p.read_bytes()) for p in sorted(root.rglob("*"))
        if p.is_file() and p.name not in ("README.md", "NOTICE.md", "ontology.json", "checksums.json") and "__pycache__" not in p.parts})
    print(json.dumps(stats, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("command", choices=["discover", "fetch", "build"])
    args = parser.parse_args()
    globals()[args.command](args.output)
