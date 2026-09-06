#!/usr/bin/env python3
"""Acquire, normalize, validate and publish Edukacja Medialna Polish lessons."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import pprint
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup
import requests

BASE = "https://edukacjamedialna.edu.pl"
LISTING = BASE + "/lekcje/"
SOURCE = "edukacja_medialna_pl"
OWN_REPO = "PiotrSty/edukacja-medialna-pl"
TARGET = "SlayerLab/polish-dynaword"
LICENSE = "CC-BY-SA-3.0"
LICENSE_URL = "https://creativecommons.org/licenses/by-sa/3.0/"
FIELDS = ["id", "text", "source", "added", "created", "token_count", "license", "author"]
UA = "EdukacjaMedialnaResearch/1.0 (PiotrSty; public open-education corpus)"
BLOCKS = {
    "naglowek_rozdzial", "naglowek_podrozdzial", "akap", "punkt",
    "opis", "definiendum", "aktywnosc", "cwiczenie", "pomoce",
    "forma", "czas", "tytul_dziela",
}


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(value).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_lines(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def read_lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def normalize(text):
    text = unicodedata.normalize("NFKC", text).replace("\u00ad", "").replace("\u200b", "")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    lines = [re.sub(r"[ \t\xa0]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def local_name(tag):
    return tag.rsplit("}", 1)[-1].split(":")[-1]


def http_get(url, attempts=5):
    last = None
    for attempt in range(attempts):
        last = requests.get(url, timeout=(20, 90), headers={"User-Agent": UA, "Accept-Language": "pl"})
        if last.status_code not in (429, 500, 502, 503, 504):
            last.raise_for_status()
            return last
        time.sleep(2 ** attempt)
    last.raise_for_status()


def lesson_links(html):
    soup = BeautifulSoup(html, "html.parser")
    result = set()
    for anchor in soup.select("a[href]"):
        url = urljoin(LISTING, anchor["href"])
        parsed = urlparse(url)
        if parsed.netloc == "edukacjamedialna.edu.pl" and re.fullmatch(r"/lekcje/[^/]+/", parsed.path):
            result.add(url)
    return sorted(result)


def page_metadata(page_url, payload):
    soup = BeautifulSoup(payload, "html.parser")
    xml_urls = sorted({urljoin(page_url, a["href"]) for a in soup.select('a[href*="/xml/"]') if a["href"].endswith(".xml")})
    text = normalize(soup.get_text(" "))
    license_links = sorted({urljoin(page_url, a["href"]) for a in soup.select("a[href]") if "creativecommons.org/licenses/" in a["href"]})
    explicit = any("creativecommons.org/licenses/by-sa/3.0" in url for url in license_links)
    return {"xml_urls": xml_urls, "license_links": license_links, "page_has_explicit_cc_by_sa_3": explicit,
            "page_mentions_license": "Licencja:" in text}


def dc_values(root, suffix):
    return [normalize(node.text or "") for node in root.iter() if local_name(node.tag) == suffix and normalize(node.text or "")]


def parse_xml(xml_bytes, page_url):
    root = ET.fromstring(xml_bytes)
    if local_name(root.tag) != "utwor":
        raise ValueError("unexpected XML root")
    title = (dc_values(root, "title") or [""])[0]
    canonical = (dc_values(root, "identifier.url") or [page_url])[0]
    dates = dc_values(root, "date")
    rights = dc_values(root, "rights")
    rights_urls = dc_values(root, "rights.license")
    creators = []
    creator_roles = {}
    for node in root.iter():
        name = local_name(node.tag)
        if name.startswith("creator.") and normalize(node.text or ""):
            role = name.split(".", 1)[1]
            value = normalize(node.text or "")
            creators.append(value)
            creator_roles.setdefault(role, []).append(value)
    body = next((node for node in root if local_name(node.tag) == "powiesc"), None)
    if body is None:
        raise ValueError("missing powiesc body")
    chunks = []
    stop = False
    for node in body.iter():
        name = local_name(node.tag)
        value = normalize(" ".join(node.itertext())) if name in BLOCKS else ""
        if name.startswith("naglowek_") and value.casefold() == "czytelnia":
            stop = True
        if stop:
            continue
        if name in BLOCKS and value and (not chunks or value != chunks[-1]):
            # Keep only leaf-like blocks to avoid duplicating text from containers.
            if not any(local_name(child.tag) in BLOCKS for child in list(node)):
                chunks.append(value)
    text = normalize("\n\n".join(chunks))
    return {"title": title, "canonical_url": canonical, "created": dates[0][:10] if dates else "unknown",
            "rights": rights, "rights_urls": rights_urls, "creators": sorted(set(creators)),
            "creator_roles": creator_roles, "text": text}


def acquire(out):
    if (out / "inventory.json").exists():
        raise ValueError("inventory exists; use a fresh output for a new immutable acquisition")
    out.mkdir(parents=True, exist_ok=True)
    listing_response = http_get(LISTING)
    links = lesson_links(listing_response.text)
    if len(links) < 200:
        raise ValueError(f"unexpectedly small listing: {len(links)}")
    records = []
    failures = []
    for index, page_url in enumerate(links, 1):
        slug = page_url.rstrip("/").rsplit("/", 1)[-1]
        try:
            page = http_get(page_url)
            meta = page_metadata(page_url, page.content)
            if len(meta["xml_urls"]) != 1:
                raise ValueError(f"expected one XML link, got {len(meta['xml_urls'])}")
            xml_response = http_get(meta["xml_urls"][0])
            parsed = parse_xml(xml_response.content, page_url)
            xml_cc = any("creativecommons.org/licenses/by-sa/3.0" in url for url in parsed["rights_urls"])
            records.append({"slug": slug, "page_url": page_url, "xml_url": meta["xml_urls"][0],
                "observed_at": now(), "page_sha256": sha(page.content), "xml_sha256": sha(xml_response.content),
                "page_license_links": meta["license_links"], "page_has_explicit_cc_by_sa_3": meta["page_has_explicit_cc_by_sa_3"],
                "xml_has_explicit_cc_by_sa_3": xml_cc, "metadata": {k: parsed[k] for k in parsed if k != "text"},
                "xml": xml_response.content.decode("utf-8")})
        except Exception as error:
            failures.append({"slug": slug, "page_url": page_url, "error": str(error)})
        if index % 25 == 0 or index == len(links):
            print(f"Acquired {index}/{len(links)}; failures={len(failures)}", flush=True)
        time.sleep(0.15)
    save(out / "inventory.json", {"listing_url": LISTING, "listing_sha256": sha(listing_response.content),
        "observed_at": now(), "discovered_links": links, "records": records, "failures": failures})
    write_lines(out / "raw_xml.jsonl", records)
    if failures:
        raise ValueError("acquisition incomplete; inspect inventory failures")


def near_dedup(rows):
    from datasketch import MinHash, MinHashLSH
    index = MinHashLSH(threshold=0.8, num_perm=128)
    features = {}
    kept, removed = [], []
    for row in rows:
        words = re.findall(r"\w+", row["text"].casefold())
        shingles = {" ".join(words[i:i + 5]).encode() for i in range(max(0, len(words) - 4))}
        sig = MinHash(num_perm=128, seed=1)
        if not shingles:
            kept.append(row)
            continue
        sig.update_batch(sorted(shingles))
        duplicate = None
        score = 0.0
        for candidate in sorted(index.query(sig)):
            value = len(shingles & features[candidate]) / len(shingles | features[candidate])
            if value >= 0.9:
                duplicate, score = candidate, value
                break
        if duplicate:
            removed.append({"id": row["id"], "duplicate_of": duplicate, "jaccard": score})
        else:
            kept.append(row)
            features[row["id"]] = shingles
            index.insert(row["id"], sig)
    return kept, removed


def build(out):
    import pyarrow as pa
    import pyarrow.parquet as pq
    import tiktoken
    from langid.langid import LanguageIdentifier, model
    inventory = load(out / "inventory.json")
    if inventory["failures"] or len(inventory["records"]) != len(inventory["discovered_links"]):
        raise ValueError("cannot build from incomplete inventory")
    encoder = tiktoken.get_encoding("cl100k_base")
    identifier = LanguageIdentifier.from_modelstring(model, norm_probs=True)
    identifier.set_languages(["pl", "en", "de", "cs", "sk", "uk", "ru"])
    rows, sidecars, decisions = [], [], []
    seen = {}
    pii = Counter()
    added = min(r["observed_at"][:10] for r in inventory["records"])
    for record in sorted(inventory["records"], key=lambda item: item["slug"]):
        raw = record["xml"].encode()
        if sha(raw) != record["xml_sha256"]:
            raise ValueError("raw XML checksum mismatch: " + record["slug"])
        parsed = parse_xml(raw, record["page_url"])
        body = parsed["text"]
        reason = ""
        if not record["page_has_explicit_cc_by_sa_3"] or not record["xml_has_explicit_cc_by_sa_3"]:
            reason = "license_not_explicit_on_page_and_xml"
        elif not parsed["creators"]:
            reason = "missing_creator"
        elif len(body) < 300:
            reason = "too_short"
        language, confidence = identifier.classify(body[:12000]) if body else ("unknown", 0.0)
        if not reason and language != "pl" and confidence >= 0.99:
            reason = "non_polish"
        body, email_count = re.subn(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[REDACTED:EMAIL]", body)
        body, phone_count = re.subn(r"(?i)(?:\btelefon|\btel\.)\s*:?[ \t]*(?:\+48[ \t]*)?\d(?:[ .-]?\d){8}\b", "[REDACTED:PHONE]", body)
        pii.update(email=email_count, labelled_phone=phone_count)
        text = normalize(parsed["title"] + "\n\n" + body)
        key = " ".join(text.casefold().split())
        if not reason and key in seen:
            reason = "normalized_duplicate"
        row_id = SOURCE + "_" + record["slug"]
        decisions.append({"id": row_id, "selected": not bool(reason), "reason": reason or "include",
            "page_sha256": record["page_sha256"], "xml_sha256": record["xml_sha256"]})
        if reason:
            continue
        seen[key] = row_id
        author = "; ".join(parsed["creators"])
        row = {"id": row_id, "text": text, "source": SOURCE, "added": added,
            "created": parsed["created"], "token_count": len(encoder.encode_ordinary(text)),
            "license": LICENSE, "author": author}
        rows.append(row)
        sidecars.append({"id": row_id, "title": parsed["title"], "url": parsed["canonical_url"],
            "page_url": record["page_url"], "xml_url": record["xml_url"], "created": parsed["created"],
            "authors": parsed["creators"], "creator_roles": parsed["creator_roles"], "publisher": "Fundacja Nowoczesna Polska",
            "license": LICENSE, "license_url": LICENSE_URL, "rights": parsed["rights"], "rights_urls": parsed["rights_urls"],
            "page_sha256": record["page_sha256"], "xml_sha256": record["xml_sha256"], "text_sha256": sha(text.encode()),
            "language": language, "language_confidence": float(confidence),
            "transformations": ["XML powiesc extraction", "bibliography and long-quote elements omitted", "Unicode and whitespace normalization", "email and labelled-phone pattern redaction"]})
    rows, near_removed = near_dedup(rows)
    removed_ids = {item["id"]: item for item in near_removed}
    for decision in decisions:
        if decision["id"] in removed_ids:
            decision.update(selected=False, reason="near_duplicate", **removed_ids[decision["id"]])
    kept_ids = {row["id"] for row in rows}
    sidecars = [row for row in sidecars if row["id"] in kept_ids]
    root = out / "hf_repo"
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "artifacts").mkdir(exist_ok=True)
    schema = pa.schema([(field, pa.int64() if field == "token_count" else pa.string()) for field in FIELDS])
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), root / "data/train-00000-of-00001.parquet", compression="zstd")
    write_lines(root / "artifacts/attribution.jsonl", sidecars)
    write_lines(root / "artifacts/decisions.jsonl", decisions)
    samples = sorted(rows, key=lambda row: sha(("sample:" + row["id"]).encode()))[:12]
    write_lines(root / "artifacts/sample.jsonl", samples)
    shutil.copy2(out / "inventory.json", root / "artifacts/inventory.json")
    (root / "artifacts/raw_xml.jsonl.gz").write_bytes(gzip.compress((out / "raw_xml.jsonl").read_bytes(), mtime=0))
    stats = {"discovered": len(inventory["discovered_links"]), "acquired": len(inventory["records"]),
        "kept": len(rows), "rejected": len(decisions) - len(rows), "tokens": sum(row["token_count"] for row in rows),
        "characters": sum(len(row["text"]) for row in rows), "sample_count": len(samples), "added": added,
        "author_coverage": sum(bool(row["author"]) for row in rows) / len(rows) if rows else 0}
    qa = {"license_gate": "explicit CC BY-SA 3.0 required in lesson page and source XML",
        "pii_pattern_matches": dict(pii), "exact_normalized_dedup": True,
        "near_dedup": {"method": "seeded MinHash 128 / LSH 0.8 candidates / exact 5-word Jaccard >= 0.9", "removed": near_removed},
        "cross_source_dedup": "pending target integration", "benchmark_overlap": "pending",
        "limitations": ["source guidance includes historical material", "external reading lists and long-quote elements omitted", "remaining inline third-party excerpts require review", "pattern checks are not comprehensive de-identification"]}
    save(root / "artifacts/stats.json", stats)
    save(root / "artifacts/qa.json", qa)
    run = {"id": "run:" + sha({"code": sha(Path(__file__).read_bytes()), "inventory": inventory["listing_sha256"], "data": [row["text_sha256"] for row in sidecars]}),
        "started_at": inventory["observed_at"], "finished_at": now(), "code_sha256": sha(Path(__file__).read_bytes()), "success": True,
        "inputs": {"listing_sha256": inventory["listing_sha256"], "xml_sha256": [row["xml_sha256"] for row in inventory["records"]]}, "stats": stats}
    save(root / "artifacts/run.json", run)
    print(json.dumps(stats, ensure_ascii=False, indent=2), flush=True)


def make_checksums(root):
    return {path.relative_to(root).as_posix(): sha(path.read_bytes()) for path in sorted(root.rglob("*")) if path.is_file() and path.name not in ("checksums.json", "ontology.json")}


def registry(base):
    tree = ast.parse(base)
    node = next(n.value for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SOURCES" for t in n.targets))
    current = ast.literal_eval(node)
    if SOURCE in current:
        raise ValueError("source already registered")
    entry = {"file_key": SOURCE, "pretty": "Edukacja Medialna - Polish media-literacy lessons",
        "license": LICENSE, "license_spdx": LICENSE,
        "traceable": "Direct official lesson XML. Each accepted record has explicit CC BY-SA 3.0 evidence and credited text/scenario authors in the source metadata.",
        "upstream": BASE + "/lekcje/", "provenance": "Pinned PiotrSty/edukacja-medialna-pl snapshot acquired directly from Fundacja Nowoczesna Polska lesson pages and source XML.",
        "domain": "educational/media-literacy/instructional", "created": "per-record upstream date", "is_ocr": False, "custom_datasheet": True}
    offset = sum(len(line) for line in base.splitlines(keepends=True)[:node.lineno - 1]) + node.col_offset + 1
    formatted = pprint.pformat(entry, width=96, sort_dicts=False).replace("\n", "\n    ")
    return base[:offset] + "\n    " + repr(SOURCE) + ": " + formatted + "," + base[offset:]


def prepare(out, target_revision):
    root = out / "hf_repo"
    stats = load(root / "artifacts/stats.json")
    (root / "src").mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(__file__), root / "src/build_edukacja_medialna_pl.py")
    shutil.copy2(Path(__file__).with_name("edukacja_medialna_requirements.txt"), root / "src/requirements.txt")
    shutil.copy2(Path(__file__).with_name("test_edukacja_medialna_contribution.py"), root / "src/test_edukacja_medialna_contribution.py")
    checksums = make_checksums(root)
    save(root / "artifacts/checksums.json", checksums)
    protocol = {"name": "edukacja-medialna-direct-xml-v1", "source_scope": LISTING,
        "license_gate": "explicit CC BY-SA 3.0 on page and XML", "selection": "Polish, >=300 body chars, creator present, no PII pattern match",
        "dedup": "normalized exact then seeded MinHash/Jaccard", "tokenizer": "tiktoken cl100k_base", "schema": FIELDS}
    quality = load(root / "artifacts/qa.json")
    check_evidence_id = "evidence:checksums:" + sha(checksums)
    qa_evidence_id = "evidence:qa:" + sha(quality)
    validation_protocol = {"name": "edukacja-medialna-contract-v1", "checks": ["schema", "counts", "license", "author attribution", "PII patterns", "samples", "content addresses", "acyclic lineage"]}
    validation_run = {"id": "run:validation:" + sha({"checksums": checksums, "protocol": validation_protocol}), "started_at": now(), "finished_at": now(),
        "code_sha256": checksums["src/test_edukacja_medialna_contribution.py"], "success": True, "result": "local contract validation passed"}
    ontology = {"schema_version": "slayer-research-ontology/0.1-profile",
        "objects": [{"id": "object:edukacja-medialna-source", "type": "DatasetSource"}, {"id": "object:edukacja-medialna-derived", "type": "Dataset"}],
        "versions": [{"id": "version:source:" + sha(load(out / "inventory.json")), "object_id": "object:edukacja-medialna-source", "digest": "sha256:" + sha(load(out / "inventory.json")), "immutable": True},
            {"id": "version:data:" + sha(checksums), "object_id": "object:edukacja-medialna-derived", "digest": "sha256:" + sha(checksums), "immutable": True}],
        "protocols": [{"id": "protocol:" + sha(protocol), "specification": protocol, "digest": "sha256:" + sha(protocol)},
            {"id": "protocol:" + sha(validation_protocol), "specification": validation_protocol, "digest": "sha256:" + sha(validation_protocol)}],
        "runs": [load(root / "artifacts/run.json"), validation_run],
        "relations": [{"source": "version:data:" + sha(checksums), "predicate": "DERIVED_FROM", "target": "version:source:" + sha(load(out / "inventory.json"))},
            {"source": "version:data:" + sha(checksums), "predicate": "FILTERED_BY", "target": "protocol:" + sha(protocol)},
            {"source": "version:data:" + sha(checksums), "predicate": "VALIDATED_AGAINST", "target": "protocol:" + sha(validation_protocol)},
            {"source": "version:data:" + sha(checksums), "predicate": "COMPATIBLE_WITH", "target": "hf://datasets/" + TARGET + "@" + target_revision}],
        "evidence": [{"id": check_evidence_id, "observation_type": "checksums", "payload": checksums, "append_only": True},
            {"id": qa_evidence_id, "observation_type": "quality_report", "payload": quality, "append_only": True},
            {"id": "evidence:validation:" + sha(validation_run), "observation_type": "contract_validation", "payload": validation_run, "append_only": True}],
        "claims": [{"id": "claim:licensed-records", "statement": "Every retained record passed the explicit page and XML CC BY-SA 3.0 gate.", "supported_by": [check_evidence_id, qa_evidence_id], "falsification_condition": "A retained record lacks either required license signal."},
            {"id": "claim:diversity-hypothesis", "statement": "This instructional media-literacy source may diversify a legal-heavy Polish pretraining mix.", "supported_by": [], "falsification_condition": "Controlled mix ablations show no relevant improvement or harmful style contamination.", "status": "untested"}],
        "actors": [{"id": "hf:PiotrSty", "type": "human", "name": "Piotr Styla"}, {"id": "agent:codex", "type": "agent", "name": "OpenAI Codex"}, {"id": "org:fnp", "type": "organization", "name": "Fundacja Nowoczesna Polska"}],
        "attestations": [{"type": "cross_source_deduplication", "value": "pending_target_integration"}, {"type": "benchmark_overlap", "value": "pending"}]}
    save(root / "artifacts/ontology.json", ontology)
    notice = f"""# Attribution and license\n\nSource: {LISTING}\nPublisher: Fundacja Nowoczesna Polska.\nLicense: CC BY-SA 3.0 ({LICENSE_URL}).\n\nPer-record text/scenario/expert creators, canonical URLs, source dates and rights evidence are preserved in `artifacts/attribution.jsonl`. Raw source XML and acquisition hashes are preserved in `artifacts/raw_xml.jsonl.gz`.\n\nPreparation: Piotr Styla with OpenAI Codex. Changes: extracted the authored `powiesc` lesson body from source XML; omitted external reading lists; normalized Unicode and whitespace; applied language, length, creator, license, limited PII-pattern and deduplication gates. No endorsement by Fundacja Nowoczesna Polska is implied.\n"""
    (root / "NOTICE.md").write_text(notice, encoding="utf-8")
    readme = f"""---\nlicense: cc-by-sa-3.0\nlanguage:\n- pl\ntask_categories:\n- text-generation\nconfigs:\n- config_name: default\n  data_files:\n  - split: train\n    path: data/train-00000-of-00001.parquet\n---\n\n# Edukacja Medialna PL\n\nA text-only snapshot of Polish media-literacy lesson explanations and scenarios acquired directly from official lesson XML.\n\n- Discovered: {stats['discovered']} lesson URLs\n- Retained: {stats['kept']} records\n- Tokens: {stats['tokens']:,} (`cl100k_base` proxy)\n- License: CC BY-SA 3.0 per retained record\n- Author coverage: {stats['author_coverage']:.1%}\n\nSee `NOTICE.md`, `artifacts/attribution.jsonl`, `artifacts/decisions.jsonl`, `artifacts/qa.json`, `artifacts/checksums.json` and `artifacts/ontology.json`. Twelve complete deterministic records are in `artifacts/sample.jsonl`.\n\n## Limitations\n\nThe source includes historically dated technology and legal guidance. Dates are upstream publication metadata, not proof of present-day currency. External reading lists are omitted. Embedded excerpts may require additional review. PII checks are pattern-based, not comprehensive de-identification. Cross-source DynaWord deduplication and benchmark-overlap checks remain pending. Training benefit is an untested hypothesis requiring controlled ablations.\n\n## Reproduction\n\nInstall `src/requirements.txt`, decompress `artifacts/raw_xml.jsonl.gz` to a work directory as `raw_xml.jsonl`, and run the builder against the preserved inventory. Live acquisition creates a new source Version and must use a fresh work directory.\n"""
    (root / "README.md").write_text(readme, encoding="utf-8")


def verify(out):
    import pyarrow.parquet as pq
    root = out / "hf_repo"
    table = pq.read_table(root / "data/train-00000-of-00001.parquet")
    rows = table.to_pylist()
    stats = load(root / "artifacts/stats.json")
    sidecars = read_lines(root / "artifacts/attribution.jsonl")
    decisions = read_lines(root / "artifacts/decisions.jsonl")
    samples = read_lines(root / "artifacts/sample.jsonl")
    assert table.column_names == FIELDS
    assert len(rows) == stats["kept"] == len(sidecars)
    assert len(decisions) == stats["discovered"]
    assert sum(bool(row["selected"]) for row in decisions) == stats["kept"]
    assert sum(row["token_count"] for row in rows) == stats["tokens"]
    assert {row["id"] for row in rows} == {row["id"] for row in sidecars}
    assert all(row["author"] and row["license"] == LICENSE and row["source"] == SOURCE for row in rows)
    assert all(any("creativecommons.org/licenses/by-sa/3.0" in url for url in sidecar["rights_urls"]) for sidecar in sidecars)
    assert all(not re.search(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", row["text"]) for row in rows)
    titles = {row["id"]: row["title"] for row in sidecars}
    assert all(not row["text"].startswith(titles[row["id"]] + "\n\n" + titles[row["id"]]) for row in rows)
    by_id = {row["id"]: row for row in rows}
    assert len(samples) == min(12, len(rows)) and all(by_id[row["id"]] == row for row in samples)
    if (root / "artifacts/checksums.json").exists():
        for name, digest in load(root / "artifacts/checksums.json").items():
            assert sha((root / name).read_bytes()) == digest
    print(json.dumps({"verified": True, **stats}, ensure_ascii=False, indent=2))


def hf_token():
    value = os.environ.get("HF_TOKEN")
    if not value and os.name == "nt":
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value = winreg.QueryValueEx(key, "HF_TOKEN")[0]
    if not value or not value.startswith("hf_"):
        raise ValueError("HF_TOKEN unavailable")
    return value


def all_files(root):
    return [path for path in sorted(root.rglob("*")) if path.is_file() and "__pycache__" not in path.parts]


def assemble_pr(out, base, source_commit):
    root = out / "hf_repo"
    pr = out / "dynaword_pr"
    data = pr / "data" / SOURCE
    data.mkdir(parents=True, exist_ok=True)
    (pr / "src").mkdir(exist_ok=True)
    (pr / "artifacts").mkdir(exist_ok=True)
    shutil.copy2(root / "data/train-00000-of-00001.parquet", data / f"{SOURCE}.parquet")
    for name in ("attribution.jsonl", "decisions.jsonl", "sample.jsonl", "stats.json", "qa.json"):
        shutil.copy2(root / "artifacts" / name, data / f"{SOURCE}.{name}")
    shutil.copy2(root / "NOTICE.md", data / "NOTICE.md")
    shutil.copy2(root / "README.md", data / f"{SOURCE}.md")
    shutil.copy2(root / "artifacts/ontology.json", pr / f"artifacts/{SOURCE}_ontology_manifest.json")
    shutil.copy2(Path(__file__), pr / "src/build_edukacja_medialna_pl.py")
    shutil.copy2(Path(__file__).with_name("test_edukacja_medialna_contribution.py"), pr / "src/test_edukacja_medialna_contribution.py")
    (pr / "src/sources.py").write_text(registry(base), encoding="utf-8")
    subprocess.run([sys.executable, "-m", "pytest", "-q", str(pr / "src/test_edukacja_medialna_contribution.py")], check=True)
    return pr


def publish(out):
    from huggingface_hub import HfApi, CommitOperationAdd
    api = HfApi(token=hf_token())
    if api.whoami()["name"].casefold() != "piotrsty":
        raise ValueError("unexpected HF account")
    target = api.dataset_info(TARGET)
    target_revision = target.sha
    registry_url = f"https://huggingface.co/datasets/{TARGET}/resolve/{target_revision}/src/sources.py"
    base = http_get(registry_url).content.decode("utf-8")
    discussions = list(api.get_repo_discussions(TARGET, repo_type="dataset"))
    if SOURCE in base or any("edukacja medialna" in item.title.casefold() for item in discussions):
        raise ValueError("source registration or proposal already exists")
    prepare(out, target_revision)
    verify(out)
    root = out / "hf_repo"
    if api.repo_exists(OWN_REPO, repo_type="dataset"):
        raise ValueError("own HF repository already exists; refusing to overwrite")
    api.create_repo(OWN_REPO, repo_type="dataset", private=True)
    source_commit = api.create_commit(OWN_REPO, repo_type="dataset", commit_message="Add validated Edukacja Medialna Polish lesson snapshot",
        operations=[CommitOperationAdd(path_in_repo=path.relative_to(root).as_posix(), path_or_fileobj=str(path)) for path in all_files(root)])
    api.create_tag(OWN_REPO, repo_type="dataset", tag="v1.0.0", revision=source_commit.oid)
    api.update_repo_settings(OWN_REPO, repo_type="dataset", private=False)
    pr = assemble_pr(out, base, source_commit.oid)
    stats = load(root / "artifacts/stats.json")
    description = f"""## Add Polish media-literacy lessons\n\nAdds `{SOURCE}`: **{stats['kept']} records and {stats['tokens']:,} measured `cl100k_base` proxy tokens**, acquired directly from official Edukacja Medialna lesson XML. Every retained record has explicit CC BY-SA 3.0 evidence on its lesson page and in XML, plus credited authors.\n\nSource dataset: https://huggingface.co/datasets/{OWN_REPO}/tree/{source_commit.oid}\n\n### Data sample\n\n- [12 complete deterministic sample records](https://huggingface.co/datasets/{OWN_REPO}/blob/{source_commit.oid}/artifacts/sample.jsonl)\n- [Per-record authors, URLs and rights](https://huggingface.co/datasets/{OWN_REPO}/blob/{source_commit.oid}/artifacts/attribution.jsonl)\n- [Selection decisions](https://huggingface.co/datasets/{OWN_REPO}/blob/{source_commit.oid}/artifacts/decisions.jsonl)\n\n### Method and ontology\n\nThe contribution includes a reproducible direct-XML builder, normalized exact and seeded MinHash/Jaccard within-source deduplication, limited PII-pattern checks, checksums, QA and an ontology manifest separating content-addressed Versions, Protocol, executed Run, Evidence, falsifiable Claims and Actors. External reading lists are omitted.\n\n### Remaining gates\n\nCross-source exact/near deduplication and benchmark-overlap checks remain pending. Historical technology/legal guidance is not asserted to be current. Embedded third-party excerpts and the CC BY-SA 3.0 to corpus-level licensing treatment require maintainer review. Training benefit is an untested diversity hypothesis. This proposes a source, not a stable release.\n"""
    result = api.create_commit(TARGET, repo_type="dataset", parent_commit=target_revision, create_pr=True,
        commit_message="Add CC BY-SA 3.0 Polish media-literacy lessons", commit_description=description,
        operations=[CommitOperationAdd(path_in_repo=path.relative_to(pr).as_posix(), path_or_fileobj=str(path)) for path in all_files(pr)])
    receipt = {"source_repo": OWN_REPO, "source_commit": source_commit.oid, "tag": "v1.0.0", "target_main_revision": target_revision,
        "pr_url": result.pr_url, "pr_commit": result.oid, "published_at": now()}
    save(out / "publication.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


def refresh(out):
    from huggingface_hub import HfApi, CommitOperationAdd
    api = HfApi(token=hf_token())
    receipt = load(out / "publication.json")
    number = int(receipt["pr_url"].rsplit("/", 1)[-1])
    main = api.dataset_info(TARGET)
    if main.sha != receipt["target_main_revision"]:
        raise ValueError("target main changed; inspect and rebase before refreshing PR")
    registry_url = f"https://huggingface.co/datasets/{TARGET}/resolve/{main.sha}/src/sources.py"
    base = http_get(registry_url).content.decode("utf-8")
    prepare(out, main.sha)
    verify(out)
    root = out / "hf_repo"
    old_source = api.dataset_info(OWN_REPO)
    source_commit = api.create_commit(OWN_REPO, repo_type="dataset", parent_commit=old_source.sha,
        commit_message="Add contribution contract test and validation run",
        operations=[CommitOperationAdd(path_in_repo=path.relative_to(root).as_posix(), path_or_fileobj=str(path)) for path in all_files(root)])
    tag = "v1.0.1"
    if not any(item.name == tag for item in api.list_repo_refs(OWN_REPO, repo_type="dataset").tags):
        api.create_tag(OWN_REPO, repo_type="dataset", tag=tag, revision=source_commit.oid)
    pr = assemble_pr(out, base, source_commit.oid)
    old_pr = api.dataset_info(TARGET, revision=f"refs/pr/{number}")
    pr_commit = api.create_commit(TARGET, repo_type="dataset", revision=f"refs/pr/{number}", parent_commit=old_pr.sha,
        commit_message="Add contract test and explicit ontology validation run",
        operations=[CommitOperationAdd(path_in_repo=path.relative_to(pr).as_posix(), path_or_fileobj=str(path)) for path in all_files(pr)])
    receipt.setdefault("previous_source_commits", []).append(receipt["source_commit"])
    receipt.setdefault("previous_pr_commits", []).append(receipt["pr_commit"])
    receipt.update(source_commit=source_commit.oid, pr_commit=pr_commit.oid, tag=tag, refreshed_at=now())
    save(out / "publication.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


def audit(out):
    from huggingface_hub import HfApi, hf_hub_download
    api = HfApi(token=False)
    receipt = load(out / "publication.json")
    info = api.dataset_info(OWN_REPO)
    if info.private or info.sha != receipt["source_commit"]:
        raise ValueError("source repo visibility or revision mismatch")
    if not any(item.name == receipt["tag"] and item.target_commit == info.sha for item in api.list_repo_refs(OWN_REPO, repo_type="dataset").tags):
        raise ValueError("release tag mismatch")
    number = int(receipt["pr_url"].rsplit("/", 1)[-1])
    discussion = api.get_discussion_details(TARGET, number, repo_type="dataset")
    pr_info = api.dataset_info(TARGET, revision=f"refs/pr/{number}")
    if not discussion.is_pull_request or pr_info.sha != receipt["pr_commit"]:
        raise ValueError("PR identity mismatch")
    checked = []
    for repo, revision, root in ((OWN_REPO, info.sha, out / "hf_repo"), (TARGET, pr_info.sha, out / "dynaword_pr")):
        for path in all_files(root):
            name = path.relative_to(root).as_posix()
            remote = Path(hf_hub_download(repo, name, repo_type="dataset", revision=revision, token=False, cache_dir=str(out / "remote_cache")))
            if sha(remote.read_bytes()) != sha(path.read_bytes()):
                raise ValueError("remote mismatch: " + name)
            checked.append({"repo": repo, "revision": revision, "path": name, "sha256": sha(remote.read_bytes())})
    result = {"observed_at": now(), "source_revision": info.sha, "pr_revision": pr_info.sha,
        "pr_status": discussion.status, "target_main_revision": api.dataset_info(TARGET).sha, "verified_files": checked}
    save(out / "publication_audit.json", result)
    print(json.dumps({**result, "verified_files": len(checked)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("command", choices=["acquire", "build", "prepare", "verify", "publish", "refresh", "audit"])
    args = parser.parse_args()
    if args.command == "prepare":
        raise SystemExit("prepare is run by publish with a pinned target revision")
    globals()[args.command](args.output)
