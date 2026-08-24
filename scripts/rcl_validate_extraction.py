#!/usr/bin/env python3
"""Validate RCL gold-pilot text extraction outputs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


CONTROLLED_VALUES = {
    "extract_status": {"extracted", "empty_text", "missing_raw", "raw_digest_mismatch"},
    "machine_doc_type_hint": {
        "organization_comment",
        "government_response",
        "cover_letter",
        "draft_law",
        "other",
    },
    "machine_source_type_hint": {
        "ngo",
        "trade_union",
        "employer_organization",
        "professional_body",
        "company",
        "public_body",
        "individual",
        "unknown",
    },
    "machine_pii_hint": {"yes", "uncertain"},
    "machine_extraction_quality_hint": {"good", "usable", "poor", "not_extractable"},
    "machine_review_priority": {"pii_first", "extraction_first", "scope_check", "standard"},
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def duplicate_values(values: list[str]) -> list[str]:
    return sorted(value for value, count in Counter(values).items() if count > 1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate local RCL pilot text extraction.")
    parser.add_argument("--input-dir", default="data/rcl_gold_pilot_v0_1")
    parser.add_argument("--expected-rows", type=int, default=40)
    args = parser.parse_args()

    root = Path(args.input_dir)
    source_manifest = read_jsonl(root / "source_manifest.jsonl")
    extraction_manifest = read_jsonl(root / "extraction_manifest.jsonl")
    with (root / "machine_observations.csv").open(encoding="utf-8", newline="") as handle:
        observations = list(csv.DictReader(handle))

    errors: list[str] = []
    warnings: list[str] = []
    if len(source_manifest) != args.expected_rows:
        errors.append(f"source rows: expected {args.expected_rows}, found {len(source_manifest)}")
    if len(extraction_manifest) != args.expected_rows:
        errors.append(f"extraction rows: expected {args.expected_rows}, found {len(extraction_manifest)}")
    if len(observations) != args.expected_rows:
        errors.append(f"observation rows: expected {args.expected_rows}, found {len(observations)}")

    source_ids = {str(row["object"]["id"]) for row in source_manifest}
    extracted_source_ids = {str(row["source"]["source_object_id"]) for row in extraction_manifest}
    if extracted_source_ids != source_ids:
        errors.append("source/extraction object-id sets differ")

    observation_by_queue_id = {row["queue_id"]: row for row in observations}
    duplicated_queue_ids = duplicate_values([row["queue_id"] for row in observations])
    if duplicated_queue_ids:
        errors.append(f"duplicate observation queue_id: {duplicated_queue_ids[:5]}")

    total_text_bytes = 0
    status_counts: Counter[str] = Counter()
    quality_counts: Counter[str] = Counter()
    pii_counts: Counter[str] = Counter()
    for item in extraction_manifest:
        version = item["version"]
        source = item["source"]
        queue_id = str(item["object"]["id"]).rsplit(":", 1)[-1]
        text_path = root / str(version["local_path"])
        if not text_path.is_file():
            errors.append(f"missing extracted text: {text_path}")
            continue
        actual_digest = sha256_file(text_path)
        if actual_digest != str(version["digest"]["value"]):
            errors.append(f"text digest mismatch: {text_path}")
        actual_bytes = text_path.stat().st_size
        if actual_bytes != int(version["bytes"]):
            errors.append(f"text byte-count mismatch: {text_path}")
        total_text_bytes += actual_bytes
        if str(source["source_object_id"]) not in source_ids:
            errors.append(f"unknown source object for extraction row: {queue_id}")

        observation = observation_by_queue_id.get(queue_id)
        if observation is None:
            errors.append(f"missing observation row: {queue_id}")
            continue
        if observation["text_sha256"] != str(version["digest"]["value"]):
            errors.append(f"observation text digest mismatch: {queue_id}")
        if observation["text_path"] != str(version["local_path"]):
            errors.append(f"observation text path mismatch: {queue_id}")
        status_counts[observation["extract_status"]] += 1
        quality_counts[observation["machine_extraction_quality_hint"]] += 1
        pii_counts[observation["machine_pii_hint"]] += 1

    for field, allowed in CONTROLLED_VALUES.items():
        invalid = sorted({row[field] for row in observations if row[field] not in allowed})
        if invalid:
            errors.append(f"invalid {field} values: {invalid}")

    if status_counts.get("empty_text", 0):
        warnings.append(f"empty text extractions require manual handling: {status_counts['empty_text']}")
    if quality_counts.get("poor", 0) or quality_counts.get("not_extractable", 0):
        warnings.append(
            "low-quality extractions require manual review before annotation or release"
        )
    if pii_counts.get("yes", 0):
        warnings.append("machine PII hints found; treat as triage evidence only")

    report = {
        "validator": {"tool": "scripts/rcl_validate_extraction.py", "version": "0.1.0"},
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "input": str(root),
        "status": "pass" if not errors else "fail",
        "checks": {
            "expected_rows": args.expected_rows,
            "source_rows": len(source_manifest),
            "extraction_rows": len(extraction_manifest),
            "observation_rows": len(observations),
            "text_bytes": total_text_bytes,
            "status_counts": dict(sorted(status_counts.items())),
            "quality_counts": dict(sorted(quality_counts.items())),
            "pii_hint_counts": dict(sorted(pii_counts.items())),
        },
        "errors": errors,
        "warnings": warnings,
    }
    report_path = root / "extraction_validation_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
