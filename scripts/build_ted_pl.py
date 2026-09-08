#!/usr/bin/env python3
"""Acquire official Polish TED notices and build an auditable DynaWord contribution."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
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
import threading
import time
import unicodedata
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import requests

SOURCE = "ted_pl"
PRETTY = "TED Polish public-procurement notices"
OWN_REPO = "PiotrSty/ted-polish-procurement-notices"
TARGET = "SlayerLab/polish-dynaword"
MIRROR = "PleIAs/TEDEUTenders"
MIRROR_REVISION = "2752d9d6f7628387583eac2435caa11edb36b9c1"
YEARS = (2023, 2024)
LICENSE = "LicenseRef-TED-Notice-Reuse"
LICENSE_URL = "https://ted.europa.eu/en/legal-notice"
SEARCH_API_URL = "https://api.ted.europa.eu/v3/notices/search"
FIELDS = ["id", "text", "source", "added", "created", "token_count", "license", "author"]
UA = "TEDPolishCorpusResearch/1.0 (PiotrSty; open research dataset)"
TEXT_TAGS = {"Name", "Title", "Description", "Note", "DocumentDescription", "ProcessReason", "ChangeDescription"}
EXCLUDED_ANCESTORS = {"Organization", "Company", "PartyName", "PostalAddress", "Contact", "PartyLegalEntity", "Person"}
EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
PHONE_RE = re.compile(
    r"(?ix)(?<!\w)(?:(?:tel(?:efon)?\.?\s*:?\s*|\+48[ .-]?)\d{3}[ .-]?\d{3}[ .-]?\d{3}|\d{3}[ .-]\d{3}[ .-]\d{3})(?!\d)"
)
NATIONAL_ID_RE = re.compile(r"(?i)\b(?:PESEL|NIP|REGON)\s*:?[ \t]*(?:\d[ -]?){9,14}\b")
THREAD_LOCAL = threading.local()
API_NARRATIVE_FIELDS = (
    "title-proc", "description-proc", "title-lot", "description-lot", "title-part", "description-part",
    "title-glo", "description-glo", "additional-info-glo", "award-criteria-order-justification",
    "award-criterion-description-glo", "award-criterion-description-lot", "accessibility-justification-lot",
    "direct-award-justification-text-proc", "duration-additional-information-lot",
    "electronic-auction-description-lot", "guarantee-required-description-lot",
    "missing-info-submission-description-lot", "non-disclosure-agreement-description-lot",
    "option-description-lot", "place-of-performance-additional-part", "place-of-performance-add-proc",
    "place-of-performance-addtional-lot", "procedure-features", "procedure-justification",
    "public-opening-description-lot", "quality-target-description-lot", "recurrence-description-lot",
    "renewal-description-lot", "review-deadline-description-lot", "selection-criterion-description-lot",
    "strategic-procurement-description-lot", "subcontracting-description",
    "submission-nonelectronic-description-lot", "terms-financial-lot",
    "reserved-execution-justification-lot", "tenderer-legal-form-description-lot",
)
API_FIELDS = (
    "publication-number", "publication-date", "official-language", "buyer-name", "notice-title",
    *API_NARRATIVE_FIELDS,
)


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
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
    text = unicodedata.normalize("NFKC", text or "").replace("\u00ad", "").replace("\u200b", "")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    lines = [re.sub(r"[ \t\xa0]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def redact_pii(text):
    counts = Counter()
    text, counts["email"] = EMAIL_RE.subn("[PII]", text)
    text, counts["national_id"] = NATIONAL_ID_RE.subn("[PII]", text)
    text, counts["phone"] = PHONE_RE.subn("[Telefon]", text)
    return normalize(text), dict(counts)


def local_name(tag):
    return tag.rsplit("}", 1)[-1]


def notice_id(url):
    match = re.search(r"(?<!\d)(\d{1,6}-\d{4})(?:xml)?(?:\b|$)", url)
    if not match:
        raise ValueError("cannot derive TED notice id from " + url)
    return match.group(1)


def request(url, attempts=6, stream=False):
    if not hasattr(THREAD_LOCAL, "session"):
        THREAD_LOCAL.session = requests.Session()
        THREAD_LOCAL.session.headers.update({"User-Agent": UA})
    last = None
    for attempt in range(attempts):
        last = THREAD_LOCAL.session.get(url, timeout=(20, 120), stream=stream)
        if last.status_code not in (429, 500, 502, 503, 504):
            last.raise_for_status()
            return last
        last.close()
        time.sleep(min(30, 2 ** attempt))
    last.raise_for_status()


def search_request(payload, attempts=6):
    if not hasattr(THREAD_LOCAL, "session"):
        THREAD_LOCAL.session = requests.Session()
        THREAD_LOCAL.session.headers.update({"User-Agent": UA})
    last = None
    for attempt in range(attempts):
        last = THREAD_LOCAL.session.post(SEARCH_API_URL, json=payload, timeout=(20, 120))
        if last.status_code not in (429, 500, 502, 503, 504):
            last.raise_for_status()
            return last.json()
        last.close()
        time.sleep(min(30, 2 ** attempt))
    last.raise_for_status()


def download(url, path):
    if path.exists() and path.stat().st_size:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".partial")
    with request(url, stream=True) as response, temp.open("wb") as handle:
        for block in response.iter_content(1024 * 1024):
            if block:
                handle.write(block)
    temp.replace(path)


def build_index(out):
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    source_dir = out / "source"
    records = {}
    source_files = []
    for year in YEARS:
        name = f"{year}_EUTenders.parquet"
        url = f"https://huggingface.co/datasets/{MIRROR}/resolve/{MIRROR_REVISION}/{name}"
        path = source_dir / name
        download(url, path)
        source_files.append({"path": name, "url": url, "bytes": path.stat().st_size, "sha256": sha(path.read_bytes())})
        parquet = pq.ParquetFile(path)
        for batch in parquet.iter_batches(columns=["filename", "identifier", "date", "language", "url"], batch_size=4096):
            selected = batch.filter(pc.equal(batch.column("language"), "POL"))
            for row in selected.to_pylist():
                identifier = notice_id(row["url"])
                item = {"notice_id": identifier, "mirror_filename": row["filename"], "mirror_identifier": row["identifier"],
                        "date": row["date"], "mirror_url": row["url"],
                        "official_xml_url": f"https://ted.europa.eu/en/notice/{identifier}/xml"}
                if identifier in records and records[identifier] != item:
                    raise ValueError("conflicting duplicate notice id: " + identifier)
                records[identifier] = item
        print(f"Indexed {year}: cumulative Polish notices={len(records)}", flush=True)
    index = sorted(records.values(), key=lambda row: row["notice_id"])
    write_lines(out / "source_index.jsonl", index)
    save(out / "source_files.json", {"mirror": MIRROR, "revision": MIRROR_REVISION,
        "files": source_files, "years": list(YEARS), "indexed_polish_notices": len(index), "created_at": now()})
    return index


def fetch_one(out, item):
    year = item["notice_id"].rsplit("-", 1)[-1]
    path = out / "raw_xml" / year / (item["notice_id"] + ".xml")
    if path.exists() and path.stat().st_size > 100 and path.read_bytes().lstrip().startswith(b"<?xml"):
        return {**item, "xml_path": path.relative_to(out).as_posix(), "xml_sha256": sha(path.read_bytes()), "bytes": path.stat().st_size}
    download(item["official_xml_url"], path)
    payload = path.read_bytes()
    if not payload.lstrip().startswith(b"<?xml"):
        path.unlink(missing_ok=True)
        raise ValueError("official response is not XML")
    ET.fromstring(payload)
    return {**item, "xml_path": path.relative_to(out).as_posix(), "xml_sha256": sha(payload), "bytes": len(payload)}


def canonical_notice_key(value):
    number, year = value.rsplit("-", 1)
    return int(number), int(year)


def polish_values(value):
    if isinstance(value, dict):
        return polish_values(value.get("pol")) if "pol" in value else []
    if isinstance(value, list):
        return [text for item in value for text in polish_values(item)]
    return [normalize(value)] if isinstance(value, str) and normalize(value) else []


def parse_search_record(record):
    chunks = []
    counts = Counter()
    seen = set()
    for field in API_NARRATIVE_FIELDS:
        for raw in polish_values(record.get(field)):
            value, redacted = redact_pii(raw)
            counts.update(redacted)
            key = " ".join(value.casefold().split())
            if len(value) >= 20 and key not in seen:
                chunks.append(value)
                seen.add(key)
    return {"authors": sorted(set(polish_values(record.get("buyer-name")))), "chunks": chunks, "pii": dict(counts)}


def fetch_api_batch(out, batch):
    by_key = {canonical_notice_key(item["notice_id"]): item for item in batch}
    query = " OR ".join(f'publication-number = "{item["notice_id"]}"' for item in batch)
    payload = search_request({
        "query": query,
        "fields": list(API_FIELDS),
        "page": 1,
        "limit": len(batch),
        "scope": "ALL",
        "checkQuerySyntax": False,
        "paginationMode": "PAGE_NUMBER",
    })
    results = []
    observed = set()
    for notice in payload.get("notices", []):
        key = canonical_notice_key(notice["publication-number"])
        if key not in by_key or key in observed:
            raise ValueError("unexpected or duplicate Search API publication number")
        observed.add(key)
        item = by_key[key]
        notice = {field: notice[field] for field in API_FIELDS if field in notice}
        year = item["notice_id"].rsplit("-", 1)[-1]
        path = out / "raw_api" / year / (item["notice_id"] + ".json")
        encoded = (json.dumps(notice, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded)
        parsed = parse_search_record(notice)
        results.append({
            **item,
            "api_path": path.relative_to(out).as_posix(),
            "api_sha256": sha(encoded),
            "api_bytes": len(encoded),
            "api_has_narrative": bool(parsed["chunks"]),
        })
    missing = sorted(set(by_key) - observed)
    if missing:
        raise ValueError(f"Search API omitted {len(missing)} requested notices")
    return results


def acquire(out, workers, limit):
    out.mkdir(parents=True, exist_ok=True)
    index = read_lines(out / "source_index.jsonl") if (out / "source_index.jsonl").exists() else build_index(out)
    selected = index[:limit] if limit else index
    api_records, failures = [], []
    batches = [selected[start:start + 100] for start in range(0, len(selected), 100)]
    with ThreadPoolExecutor(max_workers=min(8, workers)) as pool:
        futures = {pool.submit(fetch_api_batch, out, batch): batch for batch in batches}
        for count, future in enumerate(as_completed(futures), 1):
            batch = futures[future]
            try:
                api_records.extend(future.result())
            except Exception as error:
                failures.append({"notice_ids": [item["notice_id"] for item in batch], "url": SEARCH_API_URL, "error": str(error)})
            if count % 10 == 0 or count == len(batches):
                print(f"Search API batches {count}/{len(batches)}; failures={len(failures)}", flush=True)
    if failures:
        save(out / "acquisition_failures.json", failures)
        raise ValueError(f"{len(failures)} Search API batches failed; rerun acquire to retry")
    fallbacks = [record for record in api_records if not record["api_has_narrative"]]
    xml_records, xml_failures = [], []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_one, out, item): item for item in fallbacks}
        for count, future in enumerate(as_completed(futures), 1):
            item = futures[future]
            try:
                xml_records.append({**future.result(), "source_kind": "official_xml"})
            except Exception as error:
                xml_failures.append({"notice_id": item["notice_id"], "url": item["official_xml_url"], "error": str(error)})
            if count % 250 == 0 or count == len(fallbacks):
                print(f"XML fallbacks {count}/{len(fallbacks)}; failures={len(xml_failures)}", flush=True)
    xml_by_id = {record["notice_id"]: record for record in xml_records}
    completed = [
        xml_by_id.get(record["notice_id"], {**record, "source_kind": "official_search_api"})
        for record in api_records
    ]
    completed.sort(key=lambda row: row["notice_id"])
    save(out / "inventory.json", {"created_at": now(), "complete": not limit and len(completed) == len(index) and not xml_failures,
        "indexed": len(index), "attempted": len(selected), "acquired": len(completed), "api_acquired": len(api_records),
        "xml_fallback": len(xml_records), "records": completed, "failures": xml_failures,
        "source_files": load(out / "source_files.json")})
    if xml_failures:
        raise ValueError(f"{len(xml_failures)} XML fallback downloads failed; rerun acquire to retry")
    if limit:
        print("Pilot acquisition complete; rerun without --limit for a complete immutable acquisition", flush=True)


def organization_map(root):
    result = {}
    for organization in root.iter():
        if local_name(organization.tag) != "Organization":
            continue
        company = next((node for node in list(organization) if local_name(node.tag) == "Company"), None)
        if company is None:
            continue
        org_id = ""
        names = []
        for node in company.iter():
            tag = local_name(node.tag)
            if tag == "ID" and not org_id and normalize(node.text):
                org_id = normalize(node.text)
            if tag == "Name" and node.attrib.get("languageID") in ("POL", "PL") and normalize(node.text):
                names.append(normalize(node.text))
        if org_id and names:
            result[org_id] = names[0]
    return result


def contracting_authorities(root):
    mapping = organization_map(root)
    ids = []
    for party in root.iter():
        if local_name(party.tag) != "ContractingParty":
            continue
        for node in party.iter():
            if local_name(node.tag) == "ID" and normalize(node.text) in mapping:
                ids.append(normalize(node.text))
                break
    return sorted({mapping[item] for item in ids})


def parse_official_xml(payload):
    root = ET.fromstring(payload)
    if local_name(root.tag) == "TED_EXPORT":
        return parse_legacy_xml(root)
    parents = {child: parent for parent in root.iter() for child in parent}
    chunks = []
    counts = Counter()
    seen = set()
    for node in root.iter():
        if local_name(node.tag) not in TEXT_TAGS or node.attrib.get("languageID") not in ("POL", "PL"):
            continue
        ancestors = []
        current = parents.get(node)
        while current is not None:
            ancestors.append(local_name(current.tag))
            current = parents.get(current)
        if set(ancestors) & EXCLUDED_ANCESTORS:
            continue
        value, redacted = redact_pii(normalize(" ".join(node.itertext())))
        counts.update(redacted)
        key = " ".join(value.casefold().split())
        if len(value) >= 20 and key not in seen:
            chunks.append(value)
            seen.add(key)
    return {"authors": contracting_authorities(root), "chunks": chunks, "pii": dict(counts)}


def parse_legacy_xml(root):
    forms = [
        node
        for node in root.iter()
        if node.attrib.get("LG") == "PL" and node.attrib.get("CATEGORY") == "ORIGINAL"
    ]
    authors = []
    chunks = []
    counts = Counter()
    seen = set()
    for form in forms:
        parents = {child: parent for parent in form.iter() for child in parent}
        for node in form.iter():
            tag = local_name(node.tag)
            ancestors = []
            current = parents.get(node)
            while current is not None:
                ancestors.append(local_name(current.tag))
                current = parents.get(current)
            if tag == "OFFICIALNAME" and "CONTRACTING_BODY" in ancestors and normalize(node.text):
                authors.append(normalize(node.text))
            if tag != "P" or "CONTRACTING_BODY" in ancestors:
                continue
            value, redacted = redact_pii(normalize(" ".join(node.itertext())))
            counts.update(redacted)
            key = " ".join(value.casefold().split())
            if len(value) >= 20 and key not in seen:
                chunks.append(value)
                seen.add(key)
    return {"authors": sorted(set(authors)), "chunks": chunks, "pii": dict(counts)}


def shingle_set(text):
    words = re.findall(r"\w+", text.casefold())
    return {" ".join(words[index:index + 5]).encode("utf-8") for index in range(max(0, len(words) - 4))}


def near_dedup(rows):
    from datasketch import MinHash, MinHashLSH
    index = MinHashLSH(threshold=0.86, num_perm=128)
    signatures = {}
    texts = {}
    kept, removed = [], []
    for row in rows:
        shingles = shingle_set(row["text"])
        signature = MinHash(num_perm=128, seed=1)
        signature.update_batch(sorted(shingles))
        duplicate = None
        score = 0.0
        for candidate in sorted(index.query(signature)):
            other = shingle_set(texts[candidate])
            value = len(shingles & other) / len(shingles | other) if shingles | other else 1.0
            if value >= 0.9:
                duplicate, score = candidate, value
                break
        if duplicate:
            removed.append({"id": row["id"], "duplicate_of": duplicate, "jaccard": score})
        else:
            kept.append(row)
            signatures[row["id"]] = signature
            texts[row["id"]] = row["text"]
            index.insert(row["id"], signature)
    return kept, removed


def date_iso(value):
    try:
        return datetime.strptime(value, "%d/%m/%Y").date().isoformat()
    except (TypeError, ValueError):
        return "unknown"


def parse_acquired_record(out, record):
    if record["source_kind"] == "official_search_api":
        payload = (out / record["api_path"]).read_bytes()
        if sha(payload) != record["api_sha256"]:
            raise ValueError("Search API checksum mismatch: " + record["notice_id"])
        return parse_search_record(json.loads(payload)), record["api_sha256"]
    payload = (out / record["xml_path"]).read_bytes()
    if sha(payload) != record["xml_sha256"]:
        raise ValueError("XML checksum mismatch: " + record["notice_id"])
    return parse_official_xml(payload), record["xml_sha256"]


def build(out):
    import pyarrow as pa
    import pyarrow.parquet as pq
    import tiktoken
    from langid.langid import LanguageIdentifier, model
    inventory = load(out / "inventory.json")
    if not inventory["complete"] or inventory["failures"] or inventory["acquired"] != inventory["indexed"]:
        raise ValueError("complete official-XML acquisition required before build")
    parsed = []
    chunk_frequency = Counter()
    pii = Counter()
    for count, record in enumerate(inventory["records"], 1):
        item, source_hash = parse_acquired_record(out, record)
        parsed.append((record, item, source_hash))
        pii.update(item["pii"])
        chunk_frequency.update({sha(" ".join(chunk.casefold().split()).encode("utf-8")) for chunk in item["chunks"]})
        if count % 1000 == 0:
            print(f"Parsed {count}/{len(inventory['records'])}", flush=True)
    boilerplate_threshold = max(100, int(len(parsed) * 0.01))
    boilerplate = {key for key, count in chunk_frequency.items() if count >= boilerplate_threshold}
    encoder = tiktoken.get_encoding("cl100k_base")
    identifier = LanguageIdentifier.from_modelstring(model, norm_probs=True)
    identifier.set_languages(["pl", "en", "de", "cs", "sk", "uk", "ru"])
    added = inventory["created_at"][:10]
    rows, attribution, decisions = [], [], []
    seen = {}
    reject_counts = Counter()
    for record, item, source_hash in parsed:
        retained_chunks = [chunk for chunk in item["chunks"] if sha(" ".join(chunk.casefold().split()).encode("utf-8")) not in boilerplate]
        text = normalize("\n\n".join(retained_chunks))
        reason = ""
        if "\ufffd" in text:
            reason = "replacement_character"
        elif not item["authors"]:
            reason = "missing_contracting_authority"
        elif len(text) < 300:
            reason = "too_short_after_cleaning"
        language, confidence = identifier.classify(text[:20000]) if text else ("unknown", 0.0)
        if not reason and language != "pl" and confidence >= 0.98:
            reason = "non_polish"
        normalized_key = " ".join(text.casefold().split())
        if not reason and normalized_key in seen:
            reason = "exact_normalized_duplicate"
        row_id = SOURCE + "_" + record["notice_id"]
        decision = {"id": row_id, "notice_id": record["notice_id"], "selected": not bool(reason), "reason": reason or "include",
                    "source_kind": record["source_kind"], "source_sha256": source_hash,
                    "api_sha256": record["api_sha256"], "official_xml_url": record["official_xml_url"]}
        if record.get("xml_sha256"):
            decision["xml_sha256"] = record["xml_sha256"]
        decisions.append(decision)
        if reason:
            reject_counts[reason] += 1
            continue
        seen[normalized_key] = row_id
        author = "; ".join(item["authors"])
        row = {"id": row_id, "text": text, "source": SOURCE, "added": added, "created": date_iso(record["date"]),
               "token_count": len(encoder.encode_ordinary(text)), "license": LICENSE, "author": author}
        rows.append(row)
        transformations = [
            "official TED Search API extraction of Polish narrative fields"
            if record["source_kind"] == "official_search_api"
            else "official TED XML extraction of Polish-language narrative fields",
            "structured contact and address fields omitted", "Unicode and whitespace normalization",
            "email, phone and labelled national-ID pattern redaction", "within-document exact chunk deduplication",
            "source-frequency boilerplate removal",
        ]
        attribution.append({"id": row_id, "notice_id": record["notice_id"], "official_xml_url": record["official_xml_url"],
            "mirror_record_url": record["mirror_url"], "created": row["created"], "authors": item["authors"],
            "license": LICENSE, "license_url": LICENSE_URL, "source_kind": record["source_kind"],
            "source_sha256": source_hash, "api_sha256": record["api_sha256"],
            "xml_sha256": record.get("xml_sha256"), "text_sha256": sha(text.encode("utf-8")),
            "language": language, "language_confidence": float(confidence), "retained_chunks": len(retained_chunks),
            "transformations": transformations})
    rows, near_removed = near_dedup(rows)
    removed = {item["id"]: item for item in near_removed}
    for decision in decisions:
        if decision["id"] in removed:
            decision.update(selected=False, reason="near_duplicate", **removed[decision["id"]])
            reject_counts["near_duplicate"] += 1
    kept_ids = {row["id"] for row in rows}
    attribution = [item for item in attribution if item["id"] in kept_ids]
    root = out / "hf_repo"
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "artifacts").mkdir(exist_ok=True)
    schema = pa.schema([(field, pa.int64() if field == "token_count" else pa.string()) for field in FIELDS])
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), root / "data/train-00000-of-00001.parquet", compression="zstd")
    write_lines(root / "artifacts/attribution.jsonl", attribution)
    write_lines(root / "artifacts/decisions.jsonl", decisions)
    candidates = sorted(rows, key=lambda row: (abs(row["token_count"] - 1500), sha(("sample:" + row["id"]).encode("utf-8"))))
    samples = candidates[:12]
    write_lines(root / "artifacts/sample.jsonl", samples)
    source_index = [{
        "notice_id": record["notice_id"], "date": record["date"], "mirror_url": record["mirror_url"],
        "official_xml_url": record["official_xml_url"], "source_kind": record["source_kind"],
        "source_sha256": record.get("xml_sha256", record["api_sha256"]), "api_sha256": record["api_sha256"],
        "api_bytes": record["api_bytes"], "xml_sha256": record.get("xml_sha256"), "xml_bytes": record.get("bytes"),
    } for record in inventory["records"]]
    (root / "artifacts/source_index.jsonl.gz").write_bytes(gzip.compress(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in source_index).encode("utf-8"), mtime=0))
    shutil.copy2(out / "source_files.json", root / "artifacts/source_files.json")
    stats = {"indexed": inventory["indexed"], "acquired": inventory["acquired"], "api_acquired": inventory["api_acquired"],
        "xml_fallback": inventory["xml_fallback"], "kept": len(rows),
        "rejected": len(decisions) - len(rows), "rejection_reasons": dict(reject_counts),
        "tokens": sum(row["token_count"] for row in rows), "characters": sum(len(row["text"]) for row in rows),
        "sample_count": len(samples), "author_coverage": sum(bool(row["author"]) for row in rows) / len(rows) if rows else 0,
        "created_min": min((row["created"] for row in rows if row["created"] != "unknown"), default="unknown"),
        "created_max": max((row["created"] for row in rows if row["created"] != "unknown"), default="unknown"), "added": added}
    qa = {"official_sources_only": True, "source_protocol": "official TED Search API narrative fields with official XML fallback",
        "mirror_text_used_for_training": False,
        "mirror_encoding_defect": "U+FFFD observed in pilot; mirror used only to enumerate official notice identifiers",
        "license_gate": "TED legal notice permits commercial and non-commercial reuse unless otherwise noted; document-level exceptions remain reviewable",
        "pii_pattern_matches_replaced": dict(pii), "structured_contacts_omitted": True,
        "boilerplate": {"method": "drop exact normalized narrative chunks present in >=1% and at least 100 documents",
                        "threshold_documents": boilerplate_threshold, "removed_chunk_hashes": len(boilerplate)},
        "exact_normalized_dedup": True,
        "near_dedup": {"method": "seeded MinHash 128 / LSH 0.86 candidates / exact 5-word Jaccard >=0.9", "removed": near_removed},
        "cross_source_dedup": "pending target integration", "benchmark_overlap": "pending",
        "limitations": ["free-text personal names are not comprehensively de-identified", "third-party works and per-notice exceptions require review",
            "source is institutional/legal-administrative and requires a deliberate mix cap", "official records may contain repeated form language below the frequency threshold"]}
    save(root / "artifacts/stats.json", stats)
    save(root / "artifacts/qa.json", qa)
    input_hashes = [{"notice_id": row["notice_id"], "source_kind": row["source_kind"],
                     "sha256": row.get("xml_sha256", row["api_sha256"])} for row in inventory["records"]]
    run = {"id": "run:" + sha({"code": sha(Path(__file__).read_bytes()), "sources": input_hashes}),
        "started_at": inventory["created_at"], "finished_at": now(), "code_sha256": sha(Path(__file__).read_bytes()), "success": True,
        "inputs": {"mirror_revision": MIRROR_REVISION, "source_records": input_hashes}, "stats": stats}
    save(root / "artifacts/run.json", run)
    print(json.dumps(stats, ensure_ascii=False, indent=2), flush=True)


def checksums(root):
    excluded = {"artifacts/checksums.json", "artifacts/ontology.json", "artifacts/validation_run.json"}
    return {path.relative_to(root).as_posix(): sha(path.read_bytes()) for path in sorted(root.rglob("*"))
            if path.is_file() and path.relative_to(root).as_posix() not in excluded}


def registry(base):
    tree = ast.parse(base)
    node = next(item.value for item in tree.body if isinstance(item, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "SOURCES" for target in item.targets))
    if SOURCE in ast.literal_eval(node):
        raise ValueError("source already registered")
    entry = {"file_key": SOURCE, "pretty": PRETTY, "license": "TED notice reuse terms", "license_spdx": LICENSE,
        "traceable": "TED legal notice permits commercial and non-commercial reuse of procurement notices unless otherwise noted; official Search API/XML provenance and SHA-256 are preserved per record. Metadata is CC0, while notice text uses the separate reuse grant.",
        "upstream": "https://ted.europa.eu/", "provenance": "Pinned PiotrSty/ted-polish-procurement-notices snapshot; PleIAs/TEDEUTenders is used only as a pinned identifier index, while text is rebuilt from official TED Search API narrative fields with official XML fallback.",
        "domain": "public procurement / institutional / technical", "created": "2023-2024 per-record publication date", "is_ocr": False, "custom_datasheet": True}
    offset = sum(len(line) for line in base.splitlines(keepends=True)[:node.lineno - 1]) + node.col_offset + 1
    return base[:offset] + "\n    " + repr(SOURCE) + ": " + pprint.pformat(entry, width=96, sort_dicts=False).replace("\n", "\n    ") + "," + base[offset:]


def verify_core(out):
    import pyarrow.parquet as pq
    root = out / "hf_repo"
    table = pq.read_table(root / "data/train-00000-of-00001.parquet")
    rows = table.to_pylist()
    stats = load(root / "artifacts/stats.json")
    attribution = read_lines(root / "artifacts/attribution.jsonl")
    decisions = read_lines(root / "artifacts/decisions.jsonl")
    sample = read_lines(root / "artifacts/sample.jsonl")
    assert table.column_names == FIELDS
    assert len(rows) == stats["kept"] == len(attribution)
    assert len(decisions) == stats["indexed"]
    assert sum(bool(item["selected"]) for item in decisions) == stats["kept"]
    assert sum(row["token_count"] for row in rows) == stats["tokens"]
    assert all(row["author"] and row["license"] == LICENSE and "\ufffd" not in row["text"] for row in rows)
    assert all(not EMAIL_RE.search(row["text"]) for row in rows)
    by_id = {row["id"]: row for row in rows}
    assert len(sample) == min(12, len(rows)) and all(by_id[item["id"]] == item for item in sample)
    if (root / "artifacts/checksums.json").exists():
        for name, digest in load(root / "artifacts/checksums.json").items():
            assert sha((root / name).read_bytes()) == digest
    return stats


def prepare(out, target_revision):
    root = out / "hf_repo"
    (root / "src").mkdir(exist_ok=True)
    shutil.copy2(Path(__file__), root / "src/build_ted_pl.py")
    shutil.copy2(Path(__file__).with_name("ted_pl_requirements.txt"), root / "src/requirements.txt")
    shutil.copy2(Path(__file__).with_name("test_ted_pl_contribution.py"), root / "src/test_ted_pl_contribution.py")
    stats = load(root / "artifacts/stats.json")
    (root / "NOTICE.md").write_text(f"""# Notice and attribution

Source notice text: https://ted.europa.eu/
Official reuse terms: {LICENSE_URL}

Unless otherwise noted, procurement notices in the Supplement to the Official Journal of the European Union may be freely reused for commercial or non-commercial purposes. The same legal notice identifies exceptions for third-party works and identifiable private individuals. TED metadata is CC0; this does not silently relabel the notice text as CC0.

The PleIAs mirror at revision `{MIRROR_REVISION}` is used only to enumerate Polish-labelled notice identifiers. Training text is extracted afresh from official TED Search API narrative fields, with official XML fallback where those fields are absent. Preserve source acknowledgement, record URLs, this notice and the documented modifications.
""", encoding="utf-8")
    (root / "README.md").write_text(f"""---
license: other
license_name: ted-notice-reuse-terms
language:
- pl
task_categories:
- text-generation
configs:
- config_name: default
  data_files:
  - split: train
    path: data/train-00000-of-00001.parquet
---

# TED Polish procurement notices

Polish narrative text rebuilt from official TED procurement-notice records.

- Indexed notices: {stats['indexed']:,}
- Search API records: {stats['api_acquired']:,}
- XML fallbacks: {stats['xml_fallback']:,}
- Retained documents: {stats['kept']:,}
- Tokens: {stats['tokens']:,} (`cl100k_base` proxy)
- Dates: {stats['created_min']} to {stats['created_max']}
- Contracting-authority attribution: {stats['author_coverage']:.1%}

The pinned PleIAs mirror is an identifier index only because its Polish preview contains replacement-character encoding damage. Released text comes from official TED Search API narrative fields or, when absent, official XML; any remaining U+FFFD record is rejected. Structured contact/address fields are omitted; emails, phone numbers and labelled national identifiers in narrative fields are replaced. Recurrent boilerplate and within-source duplicates are filtered.

See `NOTICE.md` and `artifacts/` for the source index, attribution, selection decisions, QA, checksums, full samples and Slayer ontology manifest.

## Limitations

Free-text personal names are not comprehensively de-identified. The official reuse notice has exceptions for third-party works and identifiable private individuals, so per-notice/legal review remains appropriate. Cross-source DynaWord deduplication, benchmark-overlap checks and controlled training ablations remain pending. This administrative/technical register should be capped deliberately in a training mix.
""", encoding="utf-8")
    digest_map = checksums(root)
    save(root / "artifacts/checksums.json", digest_map)
    verified = verify_core(out)
    validation = {"id": "run:" + sha({"checksums": digest_map, "target": target_revision}), "started_at": now(), "finished_at": now(),
        "success": True, "protocol": "dataset-contract-and-checksum-validation-v1", "target_main_revision": target_revision, "stats": verified}
    save(root / "artifacts/validation_run.json", validation)
    build_run = load(root / "artifacts/run.json")
    qa = load(root / "artifacts/qa.json")
    check_id = "evidence:checksums:" + sha(digest_map)
    qa_id = "evidence:qa:" + sha(qa)
    dataset_version = "version:dataset:" + sha(digest_map)
    source_version = "version:source:" + sha({"records": build_run["inputs"]["source_records"], "mirror": MIRROR_REVISION})
    ontology = {"schema": "slayer-research-ontology-profile-v1",
        "objects": [{"id": "object:source:ted", "type": "Source"}, {"id": "object:dataset:ted-pl", "type": "Dataset"}],
        "versions": [{"id": source_version, "object": "object:source:ted", "content_address": source_version.rsplit(":", 1)[-1]},
                     {"id": dataset_version, "object": "object:dataset:ted-pl", "content_address": dataset_version.rsplit(":", 1)[-1]}],
        "protocols": [{"id": "protocol:ted-official-v1", "procedure": "pinned identifier index, official Search API narrative extraction with official XML fallback, structured-contact omission, PII patterns, boilerplate and dedup filters"},
                      {"id": "protocol:contract-v1", "procedure": "schema, checksum, sample, provenance and ontology contract checks"}],
        "runs": [{"id": build_run["id"], "protocol": "protocol:ted-official-v1", "success": True,
                  "started_at": build_run["started_at"], "finished_at": build_run["finished_at"]}, validation],
        "evidence": [{"id": check_id, "observation_type": "checksums", "payload": digest_map, "produced_by": validation["id"]},
                     {"id": qa_id, "observation_type": "qa", "payload": qa, "produced_by": build_run["id"]}],
        "claims": [{"id": "claim:official-source", "statement": "Every retained text is rebuilt from a checksum-addressed official TED Search API record or official XML fallback; mirror text is not training input.",
                    "supported_by": [check_id, qa_id], "falsification_condition": "A retained attribution lacks an official source kind/hash or released text contains mirror encoding damage."},
                   {"id": "claim:rights-qualified", "statement": "TED's official legal notice permits commercial and non-commercial reuse of notices unless otherwise noted; exceptions are not claimed absent.",
                    "supported_by": [qa_id], "falsification_condition": "The pinned legal notice does not contain the reuse grant or a retained notice is explicitly excepted."}],
        "actors": [{"id": "actor:piotrsty", "type": "Contributor"}, {"id": "actor:publications-office-eu", "type": "Organization"},
                   {"id": "actor:codex", "type": "Agent"}],
        "relations": [{"source": dataset_version, "predicate": "DERIVED_FROM", "target": source_version},
                      {"source": dataset_version, "predicate": "GENERATED_BY", "target": build_run["id"]},
                      {"source": dataset_version, "predicate": "VALIDATED_AGAINST", "target": validation["id"]}],
        "pending": ["per-notice exception/legal review", "free-text PERSON de-identification review", "cross-source deduplication",
                    "benchmark contamination check", "training-mix cap and controlled ablation"]}
    save(root / "artifacts/ontology.json", ontology)


def verify(out):
    stats = verify_core(out)
    manifest = load(out / "hf_repo/artifacts/ontology.json")
    evidence = {item["id"] for item in manifest["evidence"]}
    assert all(item["falsification_condition"] and set(item["supported_by"]) <= evidence for item in manifest["claims"])
    assert len(manifest["runs"]) >= 2 and all(item["success"] for item in manifest["runs"])
    print(json.dumps({"verified": True, **stats}, ensure_ascii=False, indent=2), flush=True)


def findings_append(base, stats):
    heading = "## TED Polish procurement notices (2026-09-07)"
    if heading in base:
        raise ValueError("TED finding already present")
    return base.rstrip() + f"""


{heading}

- **Decision:** open PR, qualified; source inclusion and training-mix weight remain separate decisions.
- **Observed scale:** {stats['indexed']:,} Polish-labelled identifiers, {stats['kept']:,} retained documents, {stats['tokens']:,} measured `cl100k_base` proxy tokens.
- **Provenance:** the pinned `PleIAs/TEDEUTenders@{MIRROR_REVISION}` mirror enumerates identifiers only. Its Polish preview contains U+FFFD encoding damage, so training text is rebuilt from checksum-addressed official TED Search API narrative records, with official XML fallback where those fields are absent.
- **Rights:** TED's legal notice permits commercial and non-commercial reuse of procurement notices unless otherwise noted. Metadata is CC0, but notice text is recorded separately as `{LICENSE}`. Third-party-work and identifiable-person exceptions remain reviewable.
- **Quality/privacy:** structured contact/address nodes are excluded; email, phone and labelled national-ID patterns are replaced. Cross-document boilerplate and within-source exact/near duplicates are filtered. Free-text names are not comprehensively de-identified.
- **Remaining gates:** per-notice/legal exception review, cross-source deduplication, benchmark overlap, and a deliberate cap/ablation because this is a large administrative/legal-technical register.
"""


def all_files(root):
    return [path for path in sorted(root.rglob("*")) if path.is_file() and "__pycache__" not in path.parts and ".pytest_cache" not in path.parts]


def assemble_pr(out, base_sources, base_findings, source_commit):
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
    shutil.copy2(Path(__file__), pr / "src/build_ted_pl.py")
    shutil.copy2(Path(__file__).with_name("test_ted_pl_contribution.py"), pr / "src/test_ted_pl_contribution.py")
    (pr / "src/sources.py").write_text(registry(base_sources), encoding="utf-8")
    stats = load(root / "artifacts/stats.json")
    (pr / "artifacts/source_findings.md").write_text(findings_append(base_findings, stats), encoding="utf-8")
    samples = read_lines(root / "artifacts/sample.jsonl")[:3]
    snippets = []
    for row in samples:
        excerpt = row["text"][:700].replace("```", "`` `")
        snippets.append(f"#### `{row['id']}` ({row['token_count']:,} tokens)\n\n```text\n{excerpt}\n```")
    description = f"""## Add Polish TED procurement notices

Adds `{SOURCE}`: **{stats['kept']:,} documents and {stats['tokens']:,} measured `cl100k_base` proxy tokens** from official Polish-language TED procurement-notice records ({stats['created_min']} to {stats['created_max']}). The corpus uses {stats['api_acquired']:,} official Search API records and {stats['xml_fallback']:,} official XML fallbacks.

Source dataset: https://huggingface.co/datasets/{OWN_REPO}/tree/{source_commit}

### Data samples

{"\n\n".join(snippets)}

- [12 complete deterministic sample records](https://huggingface.co/datasets/{OWN_REPO}/blob/{source_commit}/artifacts/sample.jsonl)
- [Per-record official URLs, source/text hashes and attribution](https://huggingface.co/datasets/{OWN_REPO}/blob/{source_commit}/artifacts/attribution.jsonl)
- [All selection decisions](https://huggingface.co/datasets/{OWN_REPO}/blob/{source_commit}/artifacts/decisions.jsonl)

### Rights and method

TED's [official legal notice]({LICENSE_URL}) says that, unless otherwise noted, procurement notices may be freely reused for commercial or non-commercial purposes. It separately assigns CC0 to metadata; this contribution therefore records notice text as `{LICENSE}` rather than silently relabelling it CC0. Third-party-work and identifiable-person exceptions remain explicit review items.

The pinned PleIAs mirror is used only to enumerate Polish-labelled identifiers because its Polish preview contains replacement-character encoding damage. Every released text is rebuilt from a checksum-addressed official TED Search API record or, where narrative fields are absent, an official XML fallback. Structured contact/address fields are omitted; email, phone and labelled national-ID patterns are replaced. Frequent exact boilerplate and exact/near duplicates are removed.

### Slayer ontology and remaining gates

The manifest separates content-addressed source/dataset Versions, Protocols, executed Runs, Evidence, falsifiable Claims, Actors and typed lineage. Per-notice/legal exception review, free-text name review, cross-source DynaWord deduplication, benchmark-overlap testing and a deliberate training-mix cap/ablation remain pending. This PR proposes a source; it does not claim a merged or stable release.
"""
    (out / "pr_description.md").write_text(description, encoding="utf-8")
    return pr


def hf_token():
    value = os.environ.get("HF_TOKEN")
    if not value and os.name == "nt":
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value = winreg.QueryValueEx(key, "HF_TOKEN")[0]
    if not value or not value.startswith("hf_"):
        raise ValueError("HF_TOKEN unavailable")
    return value


def publish(out):
    from huggingface_hub import CommitOperationAdd, HfApi
    api = HfApi(token=hf_token())
    if api.whoami()["name"].casefold() != "piotrsty":
        raise ValueError("unexpected HF account")
    target = api.dataset_info(TARGET)
    sources_url = f"https://huggingface.co/datasets/{TARGET}/resolve/{target.sha}/src/sources.py"
    findings_url = f"https://huggingface.co/datasets/{TARGET}/resolve/{target.sha}/artifacts/source_findings.md"
    base_sources = request(sources_url).content.decode("utf-8")
    base_findings = request(findings_url).content.decode("utf-8")
    discussions = list(api.get_repo_discussions(TARGET, repo_type="dataset"))
    if SOURCE in base_sources or any("ted" in item.title.casefold() and "procurement" in item.title.casefold() for item in discussions):
        raise ValueError("source registration or proposal already exists")
    prepare(out, target.sha)
    verify(out)
    root = out / "hf_repo"
    receipt_path = out / "publication.json"
    receipt = load(receipt_path) if receipt_path.exists() else {}
    if not receipt:
        if api.repo_exists(OWN_REPO, repo_type="dataset"):
            raise ValueError("own HF repository already exists without this run receipt")
        api.create_repo(OWN_REPO, repo_type="dataset", private=True)
        receipt = {"source_repo": OWN_REPO, "target_main_revision": target.sha, "created_at": now()}
        save(receipt_path, receipt)
    if receipt["target_main_revision"] != target.sha:
        raise ValueError("target main changed since publication started; inspect before continuing")
    if not receipt.get("source_commit"):
        result = api.create_commit(OWN_REPO, repo_type="dataset", commit_message="Add validated Polish TED procurement notices",
            operations=[CommitOperationAdd(path_in_repo=path.relative_to(root).as_posix(), path_or_fileobj=str(path)) for path in all_files(root)])
        receipt["source_commit"] = result.oid
        save(receipt_path, receipt)
    source_revision = receipt["source_commit"]
    if not any(item.name == "v1.0.0" for item in api.list_repo_refs(OWN_REPO, repo_type="dataset").tags):
        api.create_tag(OWN_REPO, repo_type="dataset", tag="v1.0.0", revision=source_revision)
    api.update_repo_settings(OWN_REPO, repo_type="dataset", private=False)
    pr = assemble_pr(out, base_sources, base_findings, source_revision)
    subprocess.run([sys.executable, "-m", "pytest", "-q", str(pr / "src/test_ted_pl_contribution.py")], check=True)
    if not receipt.get("pr_url"):
        result = api.create_commit(TARGET, repo_type="dataset", parent_commit=target.sha, create_pr=True,
            commit_message="Add Polish TED public-procurement notices",
            commit_description=(out / "pr_description.md").read_text(encoding="utf-8"),
            operations=[CommitOperationAdd(path_in_repo=path.relative_to(pr).as_posix(), path_or_fileobj=str(path)) for path in all_files(pr)])
        receipt.update(tag="v1.0.0", pr_url=result.pr_url, pr_commit=result.oid, published_at=now())
        save(receipt_path, receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2), flush=True)


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
            remote = Path(hf_hub_download(repo, name, repo_type="dataset", revision=revision, token=False,
                                          cache_dir=str(out / "remote_cache")))
            if sha(remote.read_bytes()) != sha(path.read_bytes()):
                raise ValueError("remote mismatch: " + name)
            checked.append({"repo": repo, "revision": revision, "path": name, "sha256": sha(remote.read_bytes())})
    result = {"observed_at": now(), "source_revision": info.sha, "pr_revision": pr_info.sha,
        "pr_status": discussion.status, "target_main_revision": api.dataset_info(TARGET).sha, "verified_files": checked}
    save(out / "publication_audit.json", result)
    shutil.rmtree(out / "remote_cache", ignore_errors=True)
    print(json.dumps({**result, "verified_files": len(checked)}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("command", choices=["acquire", "build", "prepare", "verify", "publish", "audit"])
    args = parser.parse_args()
    if args.command == "acquire":
        acquire(args.output, args.workers, args.limit)
    elif args.command == "prepare":
        raise SystemExit("prepare is executed by publish against the current target revision")
    else:
        globals()[args.command](args.output)
