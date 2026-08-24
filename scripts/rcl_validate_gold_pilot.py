#!/usr/bin/env python3
"""Validate an RCL gold-pilot manifest, annotations, and local artifacts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


CONTROLLED_VALUES = {
    "manual_doc_type": {
        "",
        "organization_comment",
        "individual_comment",
        "government_response",
        "cover_letter",
        "draft_law",
        "attachment",
        "other",
    },
    "manual_source_type": {
        "",
        "ngo",
        "trade_union",
        "employer_organization",
        "professional_body",
        "company",
        "religious_organization",
        "public_body",
        "individual",
        "unknown",
        "other",
    },
    "contains_pii": {"unreviewed", "yes", "no", "uncertain"},
    "legal_status": {"unreviewed", "review_needed", "eligible", "exclude", "uncertain"},
    "extraction_quality": {"unreviewed", "good", "usable", "poor", "not_extractable"},
    "train_recommendation": {"undecided", "include", "exclude", "conditional"},
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
    parser = argparse.ArgumentParser(description="Validate an RCL gold-pilot artifact.")
    parser.add_argument("--input-dir", default="data/rcl_gold_pilot_v0_1")
    parser.add_argument("--expected-rows", type=int, default=40)
    parser.add_argument(
        "--allow-duplicate-digests",
        action="store_true",
        help="Allow different queue rows to point at identical content versions.",
    )
    args = parser.parse_args()

    root = Path(args.input_dir)
    manifest_path = root / "source_manifest.jsonl"
    annotations_path = root / "annotations.csv"
    manifest = read_jsonl(manifest_path)
    with annotations_path.open(encoding="utf-8", newline="") as handle:
        annotations = list(csv.DictReader(handle))

    errors: list[str] = []
    warnings: list[str] = []
    if len(manifest) != args.expected_rows:
        errors.append(f"manifest rows: expected {args.expected_rows}, found {len(manifest)}")
    if len(annotations) != args.expected_rows:
        errors.append(f"annotation rows: expected {args.expected_rows}, found {len(annotations)}")

    queue_ids = [str(row["queue_id"]) for row in annotations]
    object_ids = [str(row["object"]["id"]) for row in manifest]
    urls = [str(row["source"]["url"]) for row in manifest]
    digests = [str(row["version"]["digest"]["value"]) for row in manifest]
    for label, values in {
        "queue_id": queue_ids,
        "object id": object_ids,
        "source URL": urls,
        "artifact digest": digests,
    }.items():
        duplicates = duplicate_values(values)
        if duplicates:
            if label == "artifact digest" and args.allow_duplicate_digests:
                warnings.append(f"duplicate {label}: {duplicates[:5]}")
            else:
                errors.append(f"duplicate {label}: {duplicates[:5]}")

    annotation_by_queue_id = {row["queue_id"]: row for row in annotations}
    total_bytes = 0
    media_types: Counter[str] = Counter()
    for item in manifest:
        queue_id = str(item["object"]["id"]).rsplit(":", 1)[-1]
        version = item["version"]
        digest = str(version["digest"]["value"])
        path = root / str(version["local_path"])
        if not path.is_file():
            errors.append(f"missing artifact: {path}")
            continue
        actual_digest = sha256_file(path)
        if actual_digest != digest:
            errors.append(f"digest mismatch: {path}")
        actual_bytes = path.stat().st_size
        if actual_bytes != int(version["bytes"]):
            errors.append(f"byte-count mismatch: {path}")
        total_bytes += actual_bytes
        media_types[str(version["media_type"])] += 1
        annotation = annotation_by_queue_id.get(queue_id)
        if annotation is None:
            errors.append(f"manifest queue_id absent from annotations: {queue_id}")
        elif annotation["artifact_sha256"] != digest:
            errors.append(f"annotation digest mismatch for queue_id: {queue_id}")
        elif annotation["document_url"] != item["source"]["url"]:
            errors.append(f"URL mismatch for queue_id: {queue_id}")

    manifest_digest_set = set(digests)
    extra_annotation_digests = sorted({row["artifact_sha256"] for row in annotations} - manifest_digest_set)
    if extra_annotation_digests:
        errors.append(f"annotation digests absent from manifest: {extra_annotation_digests[:5]}")

    for field, allowed in CONTROLLED_VALUES.items():
        invalid = sorted({row[field] for row in annotations if row[field] not in allowed})
        if invalid:
            errors.append(f"invalid {field} values: {invalid}")

    reviewed_rows = sum(1 for row in annotations if row["reviewer"].strip())
    if reviewed_rows == 0:
        warnings.append("no completed manual reviews; artifact is a review pilot, not a gold set release")
    if any(row["fetch_status"] != "downloaded" for row in annotations):
        errors.append("one or more annotation rows do not have fetch_status=downloaded")

    report = {
        "validator": {"tool": "scripts/rcl_validate_gold_pilot.py", "version": "0.1.0"},
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "input": str(root),
        "status": "pass" if not errors else "fail",
        "checks": {
            "expected_rows": args.expected_rows,
            "manifest_rows": len(manifest),
            "annotation_rows": len(annotations),
            "unique_queue_ids": len(set(queue_ids)),
            "unique_source_urls": len(set(urls)),
            "unique_artifact_digests": len(set(digests)),
            "artifact_bytes": total_bytes,
            "media_types": dict(sorted(media_types.items())),
            "reviewed_rows": reviewed_rows,
        },
        "errors": errors,
        "warnings": warnings,
    }
    report_path = root / "validation_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
