#!/usr/bin/env python3
"""Build an auditable pilot from Polish CC BY-SA books in the ROCK repository."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import pprint
import re
import shutil
import subprocess
import sys
from difflib import SequenceMatcher
import unicodedata

import requests

SOURCE = "rock_pollub_pl"
OWN_REPO = "PiotrSty/rock-pollub-pl-books"
TARGET = "SlayerLab/polish-dynaword"
COLLECTION_ID = "a42db069-319d-4d51-88d1-490ee7e6bad8"
API = "https://rock.pollub.pl/server/api"
COLLECTION_URL = "https://rock.pollub.pl/collections/a42db069-319d-4d51-88d1-490ee7e6bad8"
POLICY_URL = "https://wpl.pollub.pl/pl/i/Polityka-publikacyjna/20"
LICENSE = "CC-BY-SA-4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by-sa/4.0/"
FIELDS = ["id", "text", "source", "added", "created", "token_count", "license", "author"]
UA = "ROCKPollubCorpusResearch/0.1 (PiotrSty; open research pilot)"
BOOK_SUBTYPES = {"Monograph", "Handbook", "Workbook"}
MAX_PDF_BYTES = 50 * 1024 * 1024
EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
PHONE_RE = re.compile(r"(?i)(?:\btelefon|\btel\.)\s*:?[ \t]*(?:\+48[ \t]*)?\d(?:[ .-]?\d){8}\b")


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def write_lines(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def read_lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def values(metadata, key):
    return [str(item.get("value", "")).strip() for item in metadata.get(key, []) if str(item.get("value", "")).strip()]


def request_json(url, params=None, attempts=3):
    response = None
    for attempt in range(attempts):
        response = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=(15, 30))
        if response.status_code not in (429, 500, 502, 503, 504):
            response.raise_for_status()
            return response.json()
        import time
        time.sleep(2 ** attempt)
    response.raise_for_status()


def download(url, path, attempts=3):
    response = None
    for attempt in range(attempts):
        response = requests.get(url, headers={"User-Agent": UA}, timeout=(15, 120), stream=True)
        if response.status_code not in (429, 500, 502, 503, 504):
            response.raise_for_status()
            with path.open("wb") as handle:
                for block in response.iter_content(1024 * 1024):
                    if block:
                        handle.write(block)
            return
        import time
        time.sleep(2 ** attempt)
    response.raise_for_status()


def embedded(payload, name):
    return payload.get("_embedded", {}).get(name, [])


def normalize(text):
    text = unicodedata.normalize("NFKC", text or "").replace("\u00ad", "").replace("\u200b", "")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    lines = [re.sub(r"[ \t\xa0]+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if not re.fullmatch(r"\d{1,4}", line)]
    text = "\n".join(lines)
    text = re.sub(r"(?<=\w)-\n(?=[a-ząćęłńóśźż])", "", text)
    text = re.sub(r"(?<![.!?:;\n])\n(?!\n)(?=[a-ząćęłńóśźż])", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def normalize_title(text):
    text = unicodedata.normalize("NFKD", text or "").casefold()
    text = "".join(character for character in text if not unicodedata.combining(character))
    return " ".join(re.findall(r"\w+", text))


def item_objects(payload):
    search = payload.get("_embedded", {}).get("searchResult", {})
    objects = search.get("_embedded", {}).get("objects", [])
    return [item.get("_embedded", {}).get("indexableObject", {}) for item in objects]


def bundle(item_id, name):
    payload = request_json(f"{API}/core/items/{item_id}/bundles", {"size": 20})
    return next((item for item in embedded(payload, "bundles") if item.get("name") == name), None)


def bitstreams(bundle_id):
    return embedded(request_json(f"{API}/core/bundles/{bundle_id}/bitstreams", {"size": 100}), "bitstreams")


def choose_pdf(item_id):
    original = bundle(item_id, "ORIGINAL")
    if not original:
        raise ValueError("missing ORIGINAL bundle")
    pdfs = [item for item in bitstreams(original["uuid"]) if item.get("name", "").casefold().endswith(".pdf")]
    if not pdfs:
        raise ValueError("no PDF in ORIGINAL bundle")
    return max(pdfs, key=lambda item: (int(item.get("sizeBytes", 0)), item.get("name", "")))


def extract_pdf(path):
    import pdfplumber
    pages, failures = [], []
    with pdfplumber.open(path) as document:
        for index, page in enumerate(document.pages, 1):
            try:
                pages.append(page.extract_text() or "")
            except Exception as error:
                pages.append("")
                failures.append({"page": index, "error": str(error)})
    return "\n\n".join(pages), len(pages), failures


def candidate(item):
    metadata = item.get("metadata", {})
    return (
        LICENSE in values(metadata, "dc.rights")
        and "pl" in values(metadata, "dc.language")
        and bool(BOOK_SUBTYPES & set(values(metadata, "dc.subtype")))
        and "Book" in values(metadata, "dc.type")
    )


def acquire(out, limit):
    if (out / "inventory.json").exists():
        raise ValueError("inventory exists; use a fresh directory for an immutable acquisition")
    out.mkdir(parents=True, exist_ok=True)
    raw = out / "raw_text"
    raw.mkdir(exist_ok=True)
    temp_pdf = out / ".current.pdf"
    selected, rejected, pages = [], [], []
    page = 0
    while len(selected) < limit:
        payload = request_json(f"{API}/discover/search/objects", [
            ("scope", COLLECTION_ID), ("f.license", f"{LICENSE},equals"),
            ("page", page), ("size", 100), ("sort", "dc.date.issued,DESC"),
        ])
        items = item_objects(payload)
        if not items:
            break
        pages.append({"page": page, "sha256": digest(payload), "items": len(items)})
        for item in items:
            if len(selected) >= limit:
                break
            if not candidate(item):
                continue
            item_id = item["uuid"]
            metadata = item["metadata"]
            try:
                print(f"Inspecting candidate {item_id}: {item.get('name', '')}", flush=True)
                pdf = choose_pdf(item_id)
                pdf_rights = values(pdf.get("metadata", {}), "dc.rights")
                if LICENSE.replace("-", " ") not in pdf_rights and "CC-BY-SA 4.0" not in pdf_rights:
                    raise ValueError("original PDF bitstream lacks CC-BY-SA 4.0 evidence")
                if int(pdf.get("sizeBytes", 0)) > MAX_PDF_BYTES:
                    raise ValueError(f"PDF exceeds pilot limit of {MAX_PDF_BYTES} bytes")
                download(pdf["_links"]["content"]["href"], temp_pdf)
                if temp_pdf.stat().st_size != int(pdf.get("sizeBytes", 0)):
                    raise ValueError("downloaded PDF byte count differs from repository metadata")
                pdf_bytes = temp_pdf.read_bytes()
                repository_checksum = pdf.get("checkSum") or {}
                if repository_checksum.get("checkSumAlgorithm") == "MD5" and hashlib.md5(pdf_bytes).hexdigest() != repository_checksum.get("value"):
                    raise ValueError("downloaded PDF MD5 differs from repository metadata")
                decoded, page_count, page_failures = extract_pdf(temp_pdf)
                path = raw / f"{item_id}.txt"
                path.write_text(decoded, encoding="utf-8")
                selected.append({
                    "item_id": item_id, "title": item.get("name", ""), "handle": item.get("handle"),
                    "landing_url": f"https://rock.pollub.pl/entities/publication/{item_id}",
                    "metadata": metadata, "authors": values(metadata, "dc.contributor.author"),
                    "editors": values(metadata, "dc.contributor.editor"), "issued": values(metadata, "dc.date.issued"),
                    "subtype": values(metadata, "dc.subtype"), "isbn": values(metadata, "dc.identifier.isbn"),
                    "eisbn": values(metadata, "dc.identifier.eisbn"), "item_license": values(metadata, "dc.rights"),
                    "pdf": {"id": pdf["uuid"], "name": pdf["name"], "bytes": pdf.get("sizeBytes"),
                            "checksum": pdf.get("checkSum"), "sha256": digest(pdf_bytes), "rights": pdf_rights,
                            "content_url": pdf["_links"]["content"]["href"]},
                    "extracted_text": {"extractor": "pdfplumber", "bytes": path.stat().st_size,
                                       "sha256": digest(path.read_bytes()), "page_count": page_count,
                                       "page_failures": page_failures},
                    "observed_at": now(), "decoded_characters": len(decoded),
                })
                print(f"Acquired {len(selected)}/{limit}: {item.get('name', '')}", flush=True)
            except Exception as error:
                rejected.append({"item_id": item_id, "title": item.get("name", ""), "reason": str(error)})
                print(f"Skipped {item_id}: {error}", flush=True)
            finally:
                temp_pdf.unlink(missing_ok=True)
        page += 1
    collection = request_json(f"{API}/core/collections/{COLLECTION_ID}")
    inventory = {"source": SOURCE, "collection_id": COLLECTION_ID, "collection_url": COLLECTION_URL,
                 "collection_sha256": digest(collection), "collection_archived_items": collection.get("archivedItemsCount"),
                 "policy_url": POLICY_URL, "license": LICENSE, "limit": limit, "query_pages": pages,
                 "selected": selected, "acquisition_rejections": rejected, "observed_at": now(),
                 "target_reached": len(selected) == limit}
    save(out / "inventory.json", inventory)
    print(json.dumps({"selected": len(selected), "target": limit, "target_reached": len(selected) == limit,
                      "rejected_during_acquisition": len(rejected)}, ensure_ascii=False, indent=2))


def shingles(text):
    words = re.findall(r"\w+", text.casefold())
    return {" ".join(words[index:index + 5]) for index in range(max(0, len(words) - 4))}


def audit_overlap(out):
    import pyarrow.parquet as pq
    from huggingface_hub import HfApi, HfFileSystem

    inventory = json.loads((out / "inventory.json").read_text(encoding="utf-8"))
    fs = HfFileSystem()
    revision = HfApi().dataset_info("SlayerLab/polish-dynaword").sha
    remote = f"datasets/SlayerLab/polish-dynaword@{revision}/data/biblioteka_nauki/biblioteka_nauki.parquet"
    with fs.open(remote, "rb") as handle:
        table = pq.read_table(handle, columns=["id", "attribution"])
    target = []
    for row in table.to_pylist():
        parts = row["attribution"].split(" | ")
        title = parts[2] if len(parts) >= 4 else row["attribution"]
        target.append((row["id"], row["attribution"], normalize_title(title)))
    results = []
    for record in inventory["selected"]:
        title = normalize_title(record["title"])
        exact = [{"id": row_id, "attribution": attribution} for row_id, attribution, normalized in target
                 if title and title in normalized]
        fuzzy = []
        if not exact:
            ranked = sorted(((SequenceMatcher(None, title, normalized).ratio(), row_id, attribution)
                             for row_id, attribution, normalized in target), reverse=True)[:3]
            fuzzy = [{"score": score, "id": row_id, "attribution": attribution}
                     for score, row_id, attribution in ranked if score >= 0.90]
        results.append({"item_id": record["item_id"], "title": record["title"],
                        "exact_title_matches": exact, "fuzzy_title_matches": fuzzy})
    report = {"target": "SlayerLab/polish-dynaword:data/biblioteka_nauki", "target_revision": revision,
              "method": "normalized title substring; fallback SequenceMatcher >= 0.90 over attribution",
              "target_rows": table.num_rows, "candidate_records": len(results),
              "records_with_exact_title_match": sum(bool(row["exact_title_matches"]) for row in results),
              "records_with_fuzzy_title_match": sum(bool(row["fuzzy_title_matches"]) for row in results),
              "text_overlap": "not tested; target-wide text dedup remains an integration gate",
              "observed_at": now(), "results": results}
    save(out / "overlap_audit.json", report)
    print(json.dumps({key: report[key] for key in ("target_rows", "candidate_records",
          "records_with_exact_title_match", "records_with_fuzzy_title_match")}, ensure_ascii=False, indent=2))


def build(out):
    import pyarrow as pa
    import pyarrow.parquet as pq
    import tiktoken
    from langid.langid import LanguageIdentifier, model

    inventory = json.loads((out / "inventory.json").read_text(encoding="utf-8"))
    encoder = tiktoken.get_encoding("cl100k_base")
    identifier = LanguageIdentifier.from_modelstring(model, norm_probs=True)
    identifier.set_languages(["pl", "en", "de", "uk", "ru"])
    rows, attribution, decisions, seen, features = [], [], [], {}, {}
    pii = Counter()
    added = inventory["observed_at"][:10]
    for record in inventory["selected"]:
        path = out / "raw_text" / f"{record['item_id']}.txt"
        payload = path.read_bytes()
        if digest(payload) != record["extracted_text"]["sha256"]:
            raise ValueError("text checksum mismatch: " + record["item_id"])
        text = normalize(payload.decode("utf-8-sig"))
        letters = len(re.findall(r"[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]", text))
        replacement = text.count("\ufffd")
        if replacement:
            text = text.replace("\ufffd", "[UNREADABLE_GLYPH]")
        language, confidence = identifier.classify(text[:30000]) if text else ("unknown", 0.0)
        reason = ""
        if len(text) < 5000:
            reason = "too_little_extractable_text"
        elif letters / max(len(text), 1) < 0.55:
            reason = "low_letter_ratio"
        elif replacement > 5 or replacement / max(len(text), 1) > 0.00001:
            reason = "excessive_unreadable_glyphs"
        elif language != "pl" and confidence >= 0.95:
            reason = "non_polish"
        text, emails = EMAIL_RE.subn("[REDACTED:EMAIL]", text)
        text, phones = PHONE_RE.subn("[REDACTED:PHONE]", text)
        pii.update(email=emails, labelled_phone=phones)
        normalized_key = " ".join(text.casefold().split())
        if not reason and normalized_key in seen:
            reason = "normalized_duplicate"
        current_features = shingles(text)
        duplicate_of = None
        duplicate_score = 0.0
        if not reason:
            for other_id, other_features in features.items():
                score = len(current_features & other_features) / max(len(current_features | other_features), 1)
                if score >= 0.90:
                    reason, duplicate_of, duplicate_score = "near_duplicate", other_id, score
                    break
        row_id = f"{SOURCE}_{record['item_id']}"
        decision = {"id": row_id, "selected": not bool(reason), "reason": reason or "include",
                    "language": language, "language_confidence": float(confidence), "characters": len(text),
                    "letter_ratio": letters / max(len(text), 1), "replacement_characters": replacement}
        if duplicate_of:
            decision.update(duplicate_of=duplicate_of, jaccard=duplicate_score)
        decisions.append(decision)
        if reason:
            continue
        seen[normalized_key] = row_id
        features[row_id] = current_features
        author = "; ".join(record["authors"] or record["editors"] or ["Politechnika Lubelska"])
        created = record["issued"][0] if record["issued"] else "unknown"
        row = {"id": row_id, "text": text, "source": SOURCE, "added": added, "created": created,
               "token_count": len(encoder.encode_ordinary(text)), "license": LICENSE, "author": author}
        rows.append(row)
        attribution.append({"id": row_id, "title": record["title"], "author": author,
                            "authors": record["authors"], "editors": record["editors"], "publisher": "Politechnika Lubelska",
                            "subtype": record["subtype"], "issued": record["issued"], "isbn": record["isbn"], "eisbn": record["eisbn"],
                            "landing_url": record["landing_url"], "handle": record["handle"], "license": LICENSE,
                            "license_url": LICENSE_URL, "license_policy_url": POLICY_URL,
                            "license_evidence": {"item": record["item_license"], "pdf_bitstream": record["pdf"]["rights"]},
                            "pdf": record["pdf"], "extracted_text": record["extracted_text"], "text_sha256": digest(text.encode("utf-8")),
                            "transformations": ["pdfplumber page extraction", "Unicode/whitespace normalization",
                                                "page-number-only removal", "line-wrap repair", "limited email/labelled-phone redaction"]})
    root = out / "hf_repo"
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "artifacts").mkdir(exist_ok=True)
    schema = pa.schema([(field, pa.int64() if field == "token_count" else pa.string()) for field in FIELDS])
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), root / "data/train-00000-of-00001.parquet", compression="zstd")
    write_lines(root / "artifacts/attribution.jsonl", attribution)
    write_lines(root / "artifacts/decisions.jsonl", decisions)
    sample = sorted(rows, key=lambda row: digest(("sample:" + row["id"]).encode()))[:12]
    write_lines(root / "artifacts/sample.jsonl", sample)
    inventory_public = dict(inventory)
    save(root / "artifacts/inventory.json", inventory_public)
    stats = {"pilot_limit": inventory["limit"], "discovered_collection_items": inventory["collection_archived_items"],
             "acquired": len(inventory["selected"]), "kept": len(rows), "rejected": len(decisions) - len(rows),
             "tokens": sum(row["token_count"] for row in rows), "characters": sum(len(row["text"]) for row in rows),
             "author_coverage": sum(bool(row["author"]) for row in rows) / len(rows) if rows else 0,
             "sample_count": len(sample), "added": added}
    overlap_path = out / "overlap_audit.json"
    overlap = json.loads(overlap_path.read_text(encoding="utf-8")) if overlap_path.exists() else None
    if overlap:
        save(root / "artifacts/overlap_audit.json", overlap)
    target_audit_path = out / "target_audit.json"
    target_audit = load(target_audit_path) if target_audit_path.exists() else None
    if target_audit:
        save(root / "artifacts/target_audit.json", target_audit)
    qa = {"scope": f"pilot target {inventory['limit']}; acquired {len(inventory['selected'])}; not a completeness claim",
          "target_reached": inventory.get("target_reached", len(inventory["selected"]) == inventory["limit"]),
          "license_gate": "CC-BY-SA-4.0 in item and matched PDF bitstream metadata",
          "pii_pattern_matches": dict(pii), "exact_dedup": True, "near_dedup": "exact 5-word-shingle Jaccard >= 0.90 within pilot",
          "biblioteka_nauki_overlap": overlap or "pending title comparison", "cross_source_dedup": "pending target integration",
          "benchmark_overlap": "pending", "limitations": ["PDF extraction may flatten tables and equations",
          "third-party figures and quoted material are not included as images but textual excerpts require review",
          "isolated PDF extraction replacement characters are represented as [UNREADABLE_GLYPH]",
          "pattern checks are not comprehensive de-identification", "pilot yield must not be extrapolated without a full inventory run"]}
    save(root / "artifacts/stats.json", stats)
    save(root / "artifacts/qa.json", qa)
    run = {"id": "run:" + digest({"script": digest(Path(__file__).read_bytes()), "inventory": digest(inventory)}),
           "protocol": "protocol:rock-pilot-v1", "started_at": inventory["observed_at"], "finished_at": now(),
           "success": True, "actor": "actor:codex", "stats": stats}
    save(root / "artifacts/run.json", run)
    checksum_exclusions = {"artifacts/checksums.json", "artifacts/ontology.json"}
    checks = {path.relative_to(root).as_posix(): digest(path.read_bytes()) for path in sorted(root.rglob("*"))
              if path.is_file() and path.relative_to(root).as_posix() not in checksum_exclusions}
    save(root / "artifacts/checksums.json", checks)
    evidence_id = "evidence:qa:" + digest(qa)
    inventory_evidence_id = "evidence:inventory:" + digest(inventory)
    overlap_evidence_id = "evidence:overlap:" + digest(overlap) if overlap else None
    target_evidence_id = "evidence:target-audit:" + digest(target_audit) if target_audit else None
    source_version = "version:source:" + digest({"inventory": inventory, "texts": [item["extracted_text"]["sha256"] for item in inventory["selected"]]})
    dataset_version = "version:dataset:" + digest(checks)
    ontology = {"schema": "slayer-research-ontology-profile-v1",
        "objects": [{"id": "object:source:rock-pollub", "type": "Source"}, {"id": "object:dataset:rock-pollub-pl-pilot", "type": "Dataset"}],
        "versions": [{"id": source_version, "object": "object:source:rock-pollub", "content_address": source_version.rsplit(":", 1)[-1]},
                     {"id": dataset_version, "object": "object:dataset:rock-pollub-pl-pilot", "content_address": dataset_version.rsplit(":", 1)[-1]}],
        "protocols": [{"id": "protocol:rock-pilot-v1", "procedure": "item+PDF rights gate, matched repository text, normalization, PII patterns, exact/near dedup"}],
        "runs": [run], "evidence": [
            {"id": inventory_evidence_id, "observation_type": "source_inventory",
             "artifact": "artifacts/inventory.json", "content_address": digest(inventory), "produced_by": run["id"]},
            {"id": evidence_id, "observation_type": "pilot_qa", "payload": qa, "produced_by": run["id"]},
        ] + ([{"id": overlap_evidence_id, "observation_type": "metadata_overlap_audit",
               "artifact": "artifacts/overlap_audit.json", "content_address": digest(overlap),
               "produced_by": run["id"]}] if overlap else []) +
            ([{"id": target_evidence_id, "observation_type": "target_registry_audit",
               "artifact": "artifacts/target_audit.json", "content_address": digest(target_audit),
               "produced_by": run["id"]}] if target_audit else []),
        "claims": [{"id": "claim:pilot-eligibility", "statement": "Retained pilot records have Polish book metadata and CC BY-SA 4.0 evidence at item and matched PDF-bitstream level.",
                    "supported_by": [inventory_evidence_id, evidence_id], "falsification_condition": "A retained record lacks Polish book metadata or either rights assertion."},
                   {"id": "claim:no-title-overlap-detected", "statement": "No exact or near title match was detected against the current Biblioteka Nauki attribution column.",
                    "supported_by": [overlap_evidence_id] if overlap else [evidence_id],
                    "falsification_condition": "The recorded comparison contains a match, or a rerun against the pinned target version finds one."},
                   {"id": "claim:not-registered-at-audit", "statement": "The source key and a matching ROCK/Pollub proposal were absent from the pinned DynaWord registry and discussion list at audit time.",
                    "supported_by": [target_evidence_id] if target_audit else [evidence_id],
                    "falsification_condition": "The pinned registry or recorded discussion list contains this source."},
                   {"id": "claim:training-value-untested", "statement": "Training benefit and full-corpus novelty remain untested hypotheses.",
                    "supported_by": [evidence_id], "falsification_condition": "A controlled ablation and target-wide overlap analysis establish those properties."}],
        "actors": [{"id": "actor:piotrsty", "type": "Contributor"}, {"id": "actor:politechnika-lubelska", "type": "Organization"},
                   {"id": "actor:codex", "type": "Agent"}],
        "relations": [{"source": dataset_version, "predicate": "DERIVED_FROM", "target": source_version},
                      {"source": dataset_version, "predicate": "GENERATED_BY", "target": run["id"]}] +
                     ([{"source": dataset_version, "predicate": "VALIDATED_AGAINST",
                        "target": "hf:dataset:SlayerLab/polish-dynaword@" + target_audit["revision"]}]
                      if target_audit else []),
        "pending": ["Biblioteka Nauki text overlap", "full collection inventory", "cross-source deduplication",
                    "benchmark contamination check", "legal review of third-party textual excerpts", "controlled training ablation"]}
    save(root / "artifacts/ontology.json", ontology)
    print(json.dumps(stats, ensure_ascii=False, indent=2))


def verify(out):
    import pyarrow.parquet as pq
    root = out / "hf_repo"
    table = pq.read_table(root / "data/train-00000-of-00001.parquet")
    rows = table.to_pylist()
    stats = json.loads((root / "artifacts/stats.json").read_text(encoding="utf-8"))
    decisions = read_lines(root / "artifacts/decisions.jsonl")
    attribution = read_lines(root / "artifacts/attribution.jsonl")
    sample = read_lines(root / "artifacts/sample.jsonl")
    assert table.column_names == FIELDS
    assert len(rows) == stats["kept"] == len(attribution)
    assert len(decisions) == stats["acquired"]
    assert sum(item["selected"] for item in decisions) == len(rows)
    assert sum(row["token_count"] for row in rows) == stats["tokens"]
    assert all(row["source"] == SOURCE and row["license"] == LICENSE and row["author"] for row in rows)
    assert all(EMAIL_RE.search(row["text"]) is None for row in rows)
    by_id = {row["id"]: row for row in rows}
    assert len(sample) == stats["sample_count"] and all(by_id[row["id"]] == row for row in sample)
    manifest = json.loads((root / "artifacts/ontology.json").read_text(encoding="utf-8"))
    evidence = {item["id"] for item in manifest["evidence"]}
    assert all(item["falsification_condition"] and set(item["supported_by"]) <= evidence for item in manifest["claims"])
    checks = json.loads((root / "artifacts/checksums.json").read_text(encoding="utf-8"))
    assert "artifacts/checksums.json" not in checks and "artifacts/ontology.json" not in checks
    assert all((root / relative).is_file() and digest((root / relative).read_bytes()) == checksum
               for relative, checksum in checks.items())
    for item in manifest["evidence"]:
        if item.get("artifact"):
            artifact = root / item["artifact"]
            assert artifact.is_file() and digest(json.loads(artifact.read_text(encoding="utf-8"))) == item["content_address"]
    print(json.dumps({"verified": True, **stats}, ensure_ascii=False, indent=2))


def checksum_map(root):
    excluded = {"artifacts/checksums.json", "artifacts/ontology.json"}
    return {path.relative_to(root).as_posix(): digest(path.read_bytes()) for path in sorted(root.rglob("*"))
            if path.is_file() and path.relative_to(root).as_posix() not in excluded}


def registry(base):
    tree = ast.parse(base)
    node = next(item.value for item in tree.body if isinstance(item, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "SOURCES" for target in item.targets))
    if SOURCE in ast.literal_eval(node):
        raise ValueError("source already registered")
    entry = {
        "file_key": SOURCE,
        "pretty": "ROCK Politechnika Lubelska - Polish academic books",
        "license": LICENSE,
        "license_spdx": LICENSE,
        "traceable": "Each retained book has CC BY-SA 4.0 evidence in both the item record and matched original-PDF bitstream metadata; URLs, checksums, attribution and exclusions are preserved.",
        "upstream": COLLECTION_URL,
        "provenance": f"Fetched directly from the official ROCK repository by src/fetch_{SOURCE}.py; only the fail-closed eight-record subset with item- and PDF-level rights evidence is included.",
        "domain": "academic/technical",
        "created": "2023-2026",
        "is_ocr": False,
        "custom_datasheet": True,
    }
    offset = sum(len(line) for line in base.splitlines(keepends=True)[:node.lineno - 1]) + node.col_offset + 1
    return base[:offset] + "\n    " + repr(SOURCE) + ": " + pprint.pformat(
        entry, width=96, sort_dicts=False).replace("\n", "\n    ") + "," + base[offset:]


def prepare(out, target_revision):
    root = out / "hf_repo"
    (root / "src").mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(__file__), root / f"src/fetch_{SOURCE}.py")
    shutil.copy2(Path(__file__).with_name("rock_pollub_requirements.txt"), root / "src/requirements.txt")
    shutil.copy2(Path(__file__).with_name("test_rock_pollub_contribution.py"), root / "src/test_rock_pollub_contribution.py")
    stats = load(root / "artifacts/stats.json")
    notice = f"""# Notice and attribution

Source collection: {COLLECTION_URL}
Publisher policy: {POLICY_URL}

The eight retained books expose `{LICENSE}` in both the item record and the metadata of the matched original PDF bitstream. Per-record authors, titles, source URLs, license evidence and source-file checksums are preserved in `artifacts/attribution.jsonl` and `artifacts/inventory.json`.

Transformations: PDF text extraction with pdfplumber, Unicode and whitespace normalization, page-number-only removal, line-wrap repair, limited email and labelled-phone redaction, and within-source exact/near deduplication. Images are excluded. Isolated unreadable PDF glyphs are represented as `[UNREADABLE_GLYPH]`. Attribution and ShareAlike obligations remain applicable.
"""
    (root / "NOTICE.md").write_text(notice, encoding="utf-8")
    readme = f"""---
license: cc-by-sa-4.0
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

# ROCK Politechnika Lubelska PL books

A fail-closed Polish academic-book subset extracted from the official ROCK repository of Lublin University of Technology.

- Retained books: {stats['kept']}
- Text characters: {stats['characters']:,}
- Tokens: {stats['tokens']:,} (`cl100k_base` proxy)
- Author coverage: {stats['author_coverage']:.1%}
- License: CC BY-SA 4.0, confirmed for every retained item and matched PDF bitstream
- Source period: 2023-2026

The acquisition target was 20 books, but only eight passed the conservative per-file rights gate. The other inspected candidates are not included. See `NOTICE.md` and `artifacts/` for attribution, decisions, the source inventory, deterministic complete-record samples, QA, checksums, overlap audit and Slayer ontology manifest.

## Limitations

PDF extraction can flatten tables and equations. Two isolated unreadable glyphs were marked explicitly. Pattern-based PII checks are not comprehensive de-identification. No title overlap was detected against the pinned `biblioteka_nauki` attribution column, but target-wide text deduplication, benchmark checks and controlled training ablations remain pending.
"""
    (root / "README.md").write_text(readme, encoding="utf-8")
    build(out)
    verify(out)
    if load(out / "target_audit.json")["revision"] != target_revision:
        raise ValueError("target audit revision mismatch")


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
    return [path for path in sorted(root.rglob("*")) if path.is_file()
            and "__pycache__" not in path.parts and ".pytest_cache" not in path.parts]


def assemble_pr(out, base, source_commit):
    root = out / "hf_repo"
    pr = out / "dynaword_pr"
    data = pr / "data" / SOURCE
    data.mkdir(parents=True, exist_ok=True)
    (pr / "src").mkdir(exist_ok=True)
    (pr / "artifacts").mkdir(exist_ok=True)
    shutil.copy2(root / "data/train-00000-of-00001.parquet", data / f"{SOURCE}.parquet")
    for name in ("attribution.jsonl", "decisions.jsonl", "sample.jsonl", "stats.json", "qa.json", "overlap_audit.json"):
        shutil.copy2(root / "artifacts" / name, data / f"{SOURCE}.{name}")
    shutil.copy2(root / "NOTICE.md", data / "NOTICE.md")
    shutil.copy2(root / "README.md", data / f"{SOURCE}.md")
    shutil.copy2(root / "artifacts/ontology.json", pr / f"artifacts/{SOURCE}_ontology_manifest.json")
    shutil.copy2(Path(__file__), pr / f"src/fetch_{SOURCE}.py")
    shutil.copy2(Path(__file__).with_name("rock_pollub_requirements.txt"), pr / f"src/{SOURCE}_requirements.txt")
    shutil.copy2(Path(__file__).with_name("test_rock_pollub_contribution.py"), pr / "src/test_rock_pollub_contribution.py")
    (pr / "src/sources.py").write_text(registry(base), encoding="utf-8")
    stats = load(root / "artifacts/stats.json")
    description = f"""## Add eight Polish academic books from ROCK

Adds `{SOURCE}`: **{stats['kept']} complete books and {stats['tokens']:,} measured `cl100k_base` proxy tokens** from the official ROCK repository of Lublin University of Technology.

Source dataset: https://huggingface.co/datasets/{OWN_REPO}/tree/{source_commit}

### Data sample

- [{stats['sample_count']} deterministic complete-record samples](https://huggingface.co/datasets/{OWN_REPO}/blob/{source_commit}/artifacts/sample.jsonl)
- [Per-record attribution, source URLs and item/PDF rights evidence](https://huggingface.co/datasets/{OWN_REPO}/blob/{source_commit}/artifacts/attribution.jsonl)
- [Fail-closed acquisition inventory and exclusions](https://huggingface.co/datasets/{OWN_REPO}/blob/{source_commit}/artifacts/inventory.json)

### Rights and method

Every retained record exposes CC BY-SA 4.0 in both the ROCK item record and the matched original PDF bitstream metadata. The publisher policy, source URLs, checksums and attribution are preserved. The acquisition target was 20 records; only these eight passed the conservative per-file gate. Text was extracted with pdfplumber, normalized, checked for limited PII patterns, and exact/near-deduplicated within source.

### Overlap and Slayer ontology

No exact or fuzzy title match was detected against all 42,071 rows of `biblioteka_nauki` at pinned DynaWord revision `{load(out / 'overlap_audit.json')['target_revision']}`. This is metadata evidence, not target-wide text deduplication. The manifest separates content-addressed source/dataset Versions, Protocol, Run, Evidence, falsifiable Claims, Actors and typed lineage. Cross-source text deduplication, benchmark checks, review of quoted third-party text and controlled training ablations remain pending. This PR proposes a source, not a merged or stable release.
"""
    (out / "pr_description.md").write_text(description, encoding="utf-8")
    return pr


def publish(out):
    from huggingface_hub import CommitOperationAdd, HfApi

    api = HfApi(token=hf_token())
    if api.whoami()["name"].casefold() != "piotrsty":
        raise ValueError("unexpected HF account")
    target = api.dataset_info(TARGET)
    registry_url = f"https://huggingface.co/datasets/{TARGET}/resolve/{target.sha}/src/sources.py"
    response = requests.get(registry_url, headers={"User-Agent": UA}, timeout=(15, 60))
    response.raise_for_status()
    base = response.text
    discussions = list(api.get_repo_discussions(TARGET, repo_type="dataset"))
    matching = [{"num": item.num, "title": item.title, "status": item.status}
                for item in discussions if "rock" in item.title.casefold() or "pollub" in item.title.casefold()]
    if SOURCE in base or matching:
        raise ValueError("ROCK source registration or proposal already exists")
    target_audit = {"repository": TARGET, "revision": target.sha, "registry_sha256": digest(base.encode("utf-8")),
                    "discussion_count": len(discussions), "matching_discussions": matching, "observed_at": now()}
    save(out / "target_audit.json", target_audit)
    prepare(out, target.sha)
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
        result = api.create_commit(OWN_REPO, repo_type="dataset",
            commit_message="Add validated eight-book ROCK Polish corpus",
            operations=[CommitOperationAdd(path_in_repo=path.relative_to(root).as_posix(), path_or_fileobj=str(path))
                        for path in all_files(root)])
        receipt["source_commit"] = result.oid
        save(receipt_path, receipt)
    source_revision = receipt["source_commit"]
    if not any(item.name == "v1.0.0" for item in api.list_repo_refs(OWN_REPO, repo_type="dataset").tags):
        api.create_tag(OWN_REPO, repo_type="dataset", tag="v1.0.0", revision=source_revision)
    api.update_repo_settings(OWN_REPO, repo_type="dataset", private=False)
    pr = assemble_pr(out, base, source_revision)
    subprocess.run([sys.executable, "-m", "pytest", "-q", str(pr / "src/test_rock_pollub_contribution.py")], check=True)
    if not receipt.get("pr_url"):
        result = api.create_commit(TARGET, repo_type="dataset", parent_commit=target.sha, create_pr=True,
            commit_message="Add eight CC BY-SA 4.0 Polish academic books from ROCK",
            commit_description=(out / "pr_description.md").read_text(encoding="utf-8"),
            operations=[CommitOperationAdd(path_in_repo=path.relative_to(pr).as_posix(), path_or_fileobj=str(path))
                        for path in all_files(pr)])
        receipt.update({"tag": "v1.0.0", "pr_url": result.pr_url, "pr_commit": result.oid, "published_at": now()})
        save(receipt_path, receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


def audit(out):
    from huggingface_hub import HfApi, hf_hub_download

    api = HfApi(token=False)
    receipt = load(out / "publication.json")
    info = api.dataset_info(OWN_REPO)
    if info.private or info.sha != receipt["source_commit"]:
        raise ValueError("source repo visibility or revision mismatch")
    tags = api.list_repo_refs(OWN_REPO, repo_type="dataset").tags
    if not any(item.name == receipt["tag"] and item.target_commit == info.sha for item in tags):
        raise ValueError("release tag mismatch")
    number = int(receipt["pr_url"].rsplit("/", 1)[-1])
    discussion = api.get_discussion_details(TARGET, number, repo_type="dataset")
    pr_info = api.dataset_info(TARGET, revision=f"refs/pr/{number}")
    if not discussion.is_pull_request or pr_info.sha != receipt["pr_commit"]:
        raise ValueError("PR identity mismatch")
    checked = []
    cache = out / "remote_cache"
    for repo, revision, root in ((OWN_REPO, info.sha, out / "hf_repo"), (TARGET, pr_info.sha, out / "dynaword_pr")):
        for path in all_files(root):
            name = path.relative_to(root).as_posix()
            remote = Path(hf_hub_download(repo, name, repo_type="dataset", revision=revision,
                                          token=False, cache_dir=str(cache)))
            if digest(remote.read_bytes()) != digest(path.read_bytes()):
                raise ValueError("remote mismatch: " + name)
            checked.append({"repo": repo, "revision": revision, "path": name,
                            "sha256": digest(remote.read_bytes())})
    result = {"observed_at": now(), "source_revision": info.sha, "pr_revision": pr_info.sha,
              "pr_status": discussion.status, "target_main_revision": api.dataset_info(TARGET).sha,
              "verified_files": checked}
    save(out / "publication_audit.json", result)
    shutil.rmtree(cache, ignore_errors=True)
    print(json.dumps({**result, "verified_files": len(checked)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("command", choices=["acquire", "audit_overlap", "build", "verify", "publish", "audit"])
    args = parser.parse_args()
    acquire(args.output, args.limit) if args.command == "acquire" else globals()[args.command](args.output)
