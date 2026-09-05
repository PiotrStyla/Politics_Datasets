#!/usr/bin/env python3
"""Snapshot and prepare eight Polish OpenStax editions for DynaWord.

Run with uv run --with-requirements scripts/openstax_requirements.txt python
scripts/build_openstax_pl.py --output data/openstax_pl_v1 <discover|fetch|build>.
Only discover/fetch access upstream. Build replays the recorded content snapshot.
"""

from __future__ import annotations

import argparse
import ast
import collections
import concurrent.futures
import datetime as dt
import gzip
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import pprint
import re
import shutil
import threading
import time
import unicodedata
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup, NavigableString
import requests

SOURCE = "openstax_pl"
OWN_REPO = "PiotrSty/openstax-pl-textbooks"
TARGET = "SlayerLab/polish-dynaword"
CATALOG = "https://openstax.pl/podreczniki"
BOOKS = (
    "fizyka-dla-szkół-wyższych-tom-1", "fizyka-dla-szkół-wyższych-tom-2",
    "fizyka-dla-szkół-wyższych-tom-3", "psychologia-polska",
    "mikroekonomia-podstawy", "makroekonomia-podstawy", "marketing-podstawy", "zywienie",
)
FIELDS = ["id", "text", "source", "added", "created", "token_count", "license", "author"]
BLOCKS = {"p", "div", "section", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "table", "tr", "blockquote", "dl", "dt", "dd"}
EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
PHONE = re.compile(r"(?i)(?:\btelefon|\btel\.)\s*:?\s*(?:\+48\s*)?\d(?:[ .-]?\d){8}\b")
_LOCK = threading.Lock()
_NEXT_REQUEST = 0.0


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(value).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in records), encoding="utf-8")


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def request(url):
    global _NEXT_REQUEST
    for attempt in range(5):
        with _LOCK:
            delay = max(0, _NEXT_REQUEST - time.monotonic())
            _NEXT_REQUEST = max(time.monotonic(), _NEXT_REQUEST) + 0.5
        time.sleep(delay)
        response = requests.get(url, timeout=(20, 90), headers={"User-Agent": "OpenStaxPLResearch/1.0 (PiotrSty; text-only open dataset curation)"})
        if response.status_code not in (429, 500, 502, 503, 504):
            response.raise_for_status()
            return response
        time.sleep(min(2 ** attempt, 16))
    response.raise_for_status()


def soup_html(raw):
    return BeautifulSoup(raw, "html.parser")


def page_content(raw):
    soup = soup_html(raw)
    content = soup.select_one('#main-content [data-type="page"]')
    if content is None:
        content = soup.select_one('[data-book-content="true"]')
    if content is None:
        raise ValueError("Missing OpenStax book content container")
    return soup, content


def normalize(text):
    text = unicodedata.normalize("NFKC", text).replace("\u200b", "").replace("\u00ad", "")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    lines = [re.sub(r"[ \t\xa0]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def normalized_key(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def shingles(text):
    words = re.findall(r"\w+", normalized_key(text))
    return {" ".join(words[i:i + 5]).encode() for i in range(max(0, len(words) - 4))}


def near_dedup(rows):
    from datasketch import MinHash, MinHashLSH
    index = MinHashLSH(threshold=0.8, num_perm=128)
    accepted, removed, features = [], [], {}
    for row in rows:
        tokens = shingles(row["text"])
        if not tokens:
            accepted.append(row)
            continue
        signature = MinHash(num_perm=128, seed=1)
        signature.update_batch(sorted(tokens))
        duplicate = None
        for other in sorted(index.query(signature)):
            score = len(tokens & features[other]) / len(tokens | features[other])
            if score >= 0.9:
                duplicate = {"id": row["id"], "duplicate_of": other, "jaccard": score, "reason": "within_source_near_duplicate"}
                break
        if duplicate:
            removed.append(duplicate)
        else:
            accepted.append(row)
            features[row["id"]] = tokens
            index.insert(row["id"], signature)
    return accepted, removed


def extract(content_html):
    from mathml_to_latex.converter import MathMLToLaTeX
    soup = soup_html(content_html)
    root = soup.select_one('[data-type="page"]') or soup
    removed = collections.Counter()
    for node in list(root.select('script, style, nav, button, iframe, video, audio, svg, figure, [data-type="figure"], .os-figure, [data-type="media"]')):
        if node.parent is not None:
            removed["media_or_ui_blocks"] += 1
            node.decompose()
    # MathML can otherwise concatenate numerator/denominator or duplicate MathJax output.
    for node in list(root.find_all("math")):
        annotation = node.find("annotation", attrs={"encoding": "application/x-tex"})
        value = annotation.get_text() if annotation else node.get("alttext")
        if not value:
            for redundant in node.find_all(["annotation", "annotation-xml"]):
                redundant.decompose()
            for spacing in node.find_all("mspace"):
                spacing.decompose()
                removed["math_spacing_removed"] += 1
            if not node.get_text(strip=True) and all(
                child.name in {"semantics", "mrow"} for child in node.find_all()
            ):
                node.decompose()
                removed["empty_math_placeholder_removed"] += 1
                continue
            try:
                value = MathMLToLaTeX().convert(str(node))
                if not value.strip():
                    raise ValueError("Empty math conversion")
                removed["mathml_converted_to_latex"] += 1
            except Exception:
                value = "[UNCONVERTED_MATHML]"
                removed["math_conversion_failed"] += 1
        value = value.replace("\u2062", " \\cdot ").replace("\u2061", " ").replace("\u2063", ", ")
        node.replace_with(NavigableString(" " + ("$" + value + "$" if value else "[formula]") + " "))
    for node in root.select(".MathJax, mjx-container"):
        node.decompose()
    for node in root.find_all(["sub", "sup"]):
        node.replace_with(NavigableString(("_" if node.name == "sub" else "^") + "(" + node.get_text() + ")"))
    for node in root.find_all(["br", "hr"]):
        node.replace_with(NavigableString("\n"))
    for node in root.find_all(["td", "th"]):
        node.append(NavigableString(" | "))
    for node in root.find_all(list(BLOCKS)):
        node.insert_before(NavigableString("\n\n"))
        node.insert_after(NavigableString("\n\n"))
    text = normalize(root.get_text())
    for name, pattern in (("email", EMAIL), ("labelled_phone", PHONE)):
        text, count = pattern.subn("[REDACTED:" + name.upper() + "]", text)
        removed[name] += count
    return text, dict(removed)


def license_evidence(content):
    text = normalize(content.get_text(" ", strip=True))
    match = re.search(r"(?:Podręcznik|Fizyka|Psychologia|Creative Commons).{0,260}(?:CC BY.{0,15}4\.0|Uznanie autorstwa.{0,30}4\.0)", text)
    links = sorted({a.get("href", "") for a in content.find_all("a") if "creativecommons.org/licenses/" in a.get("href", "")})
    if re.search(r"(?i)CC\s*BY[-\s]*NC|licenses/by-nc", text + " ".join(links)):
        raise ValueError("Noncommercial license marker in book foreword")
    if not match and not any("licenses/by/4.0" in link for link in links):
        raise ValueError("No book-specific CC BY 4.0 evidence")
    return {"license": "CC-BY-4.0", "license_links": links, "evidence_excerpt": match.group(0) if match else "Book foreword links CC BY 4.0", "full_foreword_text_sha256": digest(text.encode())}


def discover(out):
    from huggingface_hub import HfApi
    out.mkdir(parents=True, exist_ok=True)
    response = request(CATALOG)
    soup = soup_html(response.content)
    details = sorted({a["href"] for a in soup.select('a[href*="szczegoly-ksiazki?book="]')})
    inventory = []
    for detail in details:
        page = request(detail)
        doc = soup_html(page.content)
        urls = sorted({unquote(a["href"]).split("#")[0] for a in doc.select('a[href*="openstax.org/books/"]') if "/pages/" in a["href"]})
        slugs = {urlsplit(u).path.split("/")[2] for u in urls}
        if len(slugs) != 1 or not slugs <= set(BOOKS):
            continue
        slug = next(iter(slugs))
        foreword = f"https://openstax.org/books/{slug}/pages/przedmowa"
        fw = request(foreword)
        fw_soup, content = page_content(fw.content)
        evidence = license_evidence(content)
        meta = collections.defaultdict(list)
        for tag in fw_soup.select('meta[name^="citation_"]'):
            meta[tag["name"]].append(tag.get("content", ""))
        item = {"slug": slug, "detail_url": detail, "title": meta.get("citation_book_title", [slug])[0], "pages": urls,
                "foreword_url": foreword, "foreword_content_html": str(content), "metadata": dict(meta),
                "license_evidence": evidence, "observed_at": now(), "detail_response_sha256": digest(page.content),
                "foreword_response_sha256": digest(fw.content)}
        inventory.append(item)
        print(f"Discovered {slug}: {len(urls)} pages; CC-BY-4.0", flush=True)
    if {i["slug"] for i in inventory} != set(BOOKS) or len(inventory) != 8:
        raise ValueError("The eight-book catalog contract was not satisfied")
    api = HfApi()
    target = api.dataset_info(TARGET)
    discussions = [{"num": d.num, "title": d.title, "status": d.status, "is_pull_request": d.is_pull_request} for d in api.get_repo_discussions(TARGET, repo_type="dataset")]
    registry_response = request(f"https://huggingface.co/datasets/{TARGET}/resolve/{target.sha}/src/sources.py")
    registry = registry_response.content.decode("utf-8")
    if SOURCE in registry or any("openstax" in d["title"].lower() for d in discussions):
        raise ValueError("OpenStax already appears in registry/discussions; review before continuing")
    (out / "target_sources.py").write_text(registry, encoding="utf-8")
    write_json(out / "target_audit.json", {"repository": TARGET, "revision": target.sha, "observed_at": now(), "discussions": discussions,
        "files": [s.rfilename for s in target.siblings], "registry_sha256": digest(registry.encode()),
        "source_key_absent": True, "cross_source_text_dedup": "pending; source registration is not evidence of text novelty"})
    write_json(out / "inventory.json", sorted(inventory, key=lambda x: x["slug"]))


def fetch_page(task):
    out, book, url = task
    path = out / "cache" / (digest(url.encode()) + ".json.gz")
    if path.exists():
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            record = json.load(stream)
        if record["url"] != url or digest(record["content_html"].encode()) != record["content_sha256"]:
            raise ValueError("Invalid cached content")
        return record
    response = request(url)
    soup, content = page_content(response.content)
    canonical = soup.select_one('meta[property="og:url"]')
    record = {"url": url, "resolved_url": response.url, "book": book,
        "canonical_url": unquote(canonical.get("content")) if canonical else url,
        "content_html": str(content), "content_sha256": digest(str(content).encode()),
        "response_sha256": digest(response.content), "observed_at": now(),
        "title": content.select_one('[data-type="document-title"]').get_text(" ", strip=True) if content.select_one('[data-type="document-title"]') else "",
        "page_id": content.get("id", "")}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(json.dumps(record, ensure_ascii=False, sort_keys=True).encode(), mtime=0))
    return record


def fetch(out, workers, limit):
    inventory = json.loads((out / "inventory.json").read_text(encoding="utf-8"))
    tasks = [(out, b["slug"], url) for b in inventory for url in (b["pages"][:limit] if limit else b["pages"])]
    records, failures = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_page, task): task for task in tasks}
        for count, future in enumerate(concurrent.futures.as_completed(futures), 1):
            try:
                records.append(future.result())
            except Exception as exc:
                failures.append({"book": futures[future][1], "url": futures[future][2], "error": str(exc)})
            if count % 50 == 0 or count == len(tasks):
                print(f"Fetched {count}/{len(tasks)}; failures={len(failures)}", flush=True)
    write_json(out / "fetch_failures.json", failures)
    if failures:
        raise ValueError(f"{len(failures)} pages failed; rerun fetch to resume")
    jsonl(out / "source_pages.jsonl", sorted(records, key=lambda x: (x["book"], x["url"])))


def source_entry():
    return {"file_key": SOURCE, "pretty": "OpenStax Poland - eight academic textbook volumes",
        "license": "CC-BY-4.0", "license_spdx": "CC-BY-4.0",
        "traceable": "Each Polish edition explicitly grants CC BY 4.0 in its recorded foreword. Media are excluded; attribution is retained per page.",
        "upstream": CATALOG, "provenance": "Pinned PiotrSty/openstax-pl-textbooks snapshot; book/page URLs, content hashes, contributors and transformations in attribution sidecar.",
        "domain": "educational/academic", "created": "2017-12-05, 2025-10-01", "is_ocr": False, "custom_datasheet": True}


def update_registry(registry):
    tree = ast.parse(registry)
    node = next(n.value for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SOURCES" for t in n.targets))
    if not isinstance(node, ast.Dict) or SOURCE in [ast.literal_eval(k) for k in node.keys]:
        raise ValueError("Unexpected source registry")
    lines = registry.splitlines(keepends=True)
    offset = sum(len(line) for line in lines[:node.lineno - 1]) + node.col_offset + 1
    formatted = pprint.pformat(source_entry(), width=96, sort_dicts=False)
    entry = "\n    " + json.dumps(SOURCE) + ": " + formatted.replace("\n", "\n    ") + ","
    return registry[:offset] + entry + registry[offset:]


def build(out):
    import pyarrow as pa
    import pyarrow.parquet as pq
    import tiktoken
    from langid.langid import LanguageIdentifier, model
    started = now()
    code_sha256 = digest(Path(__file__).read_bytes())
    books = json.loads((out / "inventory.json").read_text(encoding="utf-8"))
    book_map = {b["slug"]: b for b in books}
    snapshot = read_jsonl(out / "source_pages.jsonl")
    expected = {url for b in books for url in b["pages"]}
    if {r["url"] for r in snapshot} != expected or len(snapshot) != len(expected):
        raise ValueError("Build requires the complete discovered snapshot")
    encoder = tiktoken.get_encoding("cl100k_base")
    identifier = LanguageIdentifier.from_modelstring(model, norm_probs=True)
    identifier.set_languages(["pl", "en", "de", "cs", "sk", "uk", "ru", "fr"])
    rows, sidecars, rejected, language_flags = [], [], [], []
    seen = {}
    counts, changes = collections.Counter(), collections.Counter()
    added = min(r["observed_at"][:10] for r in snapshot)
    for page_number, record in enumerate(snapshot, 1):
        if page_number % 100 == 0:
            print(f"Processing {page_number}/{len(snapshot)} pages", flush=True)
        if digest(record["content_html"].encode()) != record["content_sha256"]:
            raise ValueError("Source snapshot checksum mismatch")
        text, operations = extract(record["content_html"])
        changes.update(operations)
        slug = record["url"].rsplit("/", 1)[-1]
        reason = ""
        if re.match(r"^(?:przedmowa|skorowidz|bibliografia|rozdzial-\d+$)", slug) or "bibliografia" in slug:
            reason = "frontmatter_index_bibliography_or_answer_key"
        elif operations.get("math_conversion_failed"):
            reason = "unconverted_math"
        elif len(text) < 200:
            reason = "too_short"
        elif len(re.findall(r"[a-zA-Z\u00c0-\u024f]", text)) / max(1, len(text)) < 0.35:
            reason = "low_letter_ratio"
        key = normalized_key(text)
        if not reason and key in seen:
            reason = "normalized_duplicate"
        if reason:
            rejected.append({"url": record["url"], "book": record["book"], "reason": reason, "duplicate_of": seen.get(key), "content_sha256": record["content_sha256"]})
            continue
        language, confidence = identifier.classify(text[:12000])
        if language != "pl":
            language_flags.append({"url": record["url"], "language": language, "confidence": float(confidence), "text_preview": text[:400]})
        if language != "pl" and confidence >= 0.99:
            rejected.append({"url": record["url"], "book": record["book"], "reason": "high_confidence_non_polish", "content_sha256": record["content_sha256"]})
            continue
        seen[key] = record["url"]
        book = book_map[record["book"]]
        authors = book["metadata"].get("citation_author", [])
        author = "; ".join(authors + ["OpenStax Poland and the Polish edition contributors (see foreword)"])
        date_raw = book["metadata"].get("citation_date", [""])[0]
        try:
            created = dt.datetime.strptime(date_raw, "%b %d, %Y").date().isoformat()
        except ValueError:
            created = ""
        row_id = SOURCE + "_" + digest(record["url"].encode())
        row = {"id": row_id, "text": text, "source": SOURCE, "added": added, "created": created,
            "token_count": len(encoder.encode_ordinary(text)), "license": "CC-BY-4.0", "author": author}
        rows.append(row)
        counts[record["book"]] += 1
        sidecars.append({"id": row_id, **{k: v for k, v in record.items() if k != "content_html"}, "text_sha256": digest(text.encode()),
            "book_title": book["title"], "foreword_url": book["foreword_url"], "license": "CC-BY-4.0", "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "citation_authors": authors, "edition_contributors": "Named in the preserved foreword", "citation_date_raw": date_raw,
            "language_result": language, "language_confidence": float(confidence), "transformations": operations})
    if not rows or set(counts) != set(BOOKS):
        raise ValueError("No retained data for one or more books")
    rows, near_removed = near_dedup(rows)
    by_id = {s["id"]: s for s in sidecars}
    for item in near_removed:
        rejected.append({**item, "url": by_id[item["id"]]["url"], "book": by_id[item["id"]]["book"],
            "content_sha256": by_id[item["id"]]["content_sha256"]})
    retained_ids = {r["id"] for r in rows}
    sidecars = [s for s in sidecars if s["id"] in retained_ids]
    counts = collections.Counter(s["book"] for s in sidecars)
    root = out / "hf_repo"
    data = root / "data"
    artifacts = root / "artifacts"
    data.mkdir(parents=True, exist_ok=True)
    artifacts.mkdir(parents=True, exist_ok=True)
    schema = pa.schema([(name, pa.int64() if name == "token_count" else pa.string()) for name in FIELDS])
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), data / "train-00000-of-00001.parquet", compression="zstd", row_group_size=128)
    jsonl(artifacts / "attribution.jsonl", sidecars)
    jsonl(artifacts / "rejections.jsonl", rejected)
    samples = []
    for book in BOOKS:
        ids = {s["id"] for s in sidecars if s["book"] == book}
        samples.extend(sorted((r for r in rows if r["id"] in ids), key=lambda r: digest(("sample:" + r["id"]).encode()))[:3])
    jsonl(artifacts / "sample.jsonl", samples)
    write_json(artifacts / "books.json", books)
    shutil.copy2(out / "target_audit.json", artifacts / "target_audit.json")
    # Preserve the exact extracted source containers; gzip has a fixed timestamp.
    (artifacts / "source_pages.jsonl.gz").write_bytes(gzip.compress((out / "source_pages.jsonl").read_bytes(), mtime=0))
    write_json(artifacts / "qa.json", {"protocol": "All retained-page language classifications and deterministic extraction checks",
        "language_flags": language_flags, "within_source_normalized_dedup": True,
        "within_source_near_dedup": {"algorithm": "MinHashLSH candidates threshold 0.8; exact five-word-shingle Jaccard >=0.9", "num_perm": 128, "seed": 1, "removed": len(near_removed), "limitation": "Probabilistic candidate retrieval can miss similar pairs"},
        "cross_source_exact_dedup_completed": False, "cross_source_near_dedup_completed": False,
        "benchmark_contamination_check": "pending_target_integration", "extraction_operations": dict(changes),
        "pii_patterns": {key: changes[key] for key in ("email", "labelled_phone")},
        "pii_limitations": "Pattern checks are not complete de-identification. Published author names and attributed examples are retained.",
        "math_policy": "MathML TeX annotation/alttext or mathml-to-latex==1.0.0; remove spacing-only nodes and empty mrow/semantics placeholders; drop pages with failed conversion without guessing missing operands", "ocr": False})
    stats = {"source_pages": len(snapshot), "kept": len(rows), "tokens": sum(r["token_count"] for r in rows),
        "chars": sum(len(r["text"]) for r in rows), "words": sum(len(r["text"].split()) for r in rows),
        "by_book": dict(counts), "drop_by_reason": dict(collections.Counter(r["reason"] for r in rejected)),
        "tokenizer": "cl100k_base", "license": "CC-BY-4.0", "added": added,
        "target_revision": json.loads((out / "target_audit.json").read_text())["revision"]}
    write_json(artifacts / "stats.json", stats)
    (root / "src").mkdir(exist_ok=True)
    shutil.copy2(Path(__file__), root / "src" / "build_openstax_pl.py")
    requirements = Path(__file__).with_name("openstax_requirements.txt")
    shutil.copy2(requirements, root / "src" / requirements.name)
    write_json(artifacts / "run.json", {"started_at": started, "finished_at": now(), "actor_id": "agent:codex", "requested_by": "hf:PiotrSty",
        "python": platform.python_version(), "platform": platform.platform(),
        "packages": {n: importlib.metadata.version(n) for n in ("beautifulsoup4", "requests", "pyarrow", "tiktoken", "langid", "datasketch", "mathml-to-latex")},
        "code_sha256": code_sha256, "input_sha256": digest((out / "source_pages.jsonl").read_bytes())})
    write_json(artifacts / "checksums.json", {p.relative_to(root).as_posix(): digest(p.read_bytes()) for p in sorted(root.rglob("*")) if p.is_file() and p.name not in ("checksums.json", "ontology.json", "README.md", "NOTICE.md") and "__pycache__" not in p.parts and ".pytest_cache" not in p.parts})
    print(json.dumps(stats, ensure_ascii=False, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("command", choices=["discover", "fetch", "build"])
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--limit-per-book", type=int, default=0)
    args = parser.parse_args()
    if args.command == "discover":
        discover(args.output)
    elif args.command == "fetch":
        fetch(args.output, args.workers, args.limit_per_book)
    else:
        build(args.output)


if __name__ == "__main__":
    main()
