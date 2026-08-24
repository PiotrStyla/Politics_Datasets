#!/usr/bin/env python3
"""Apply accepted calibration-review rows to the main RCL annotations table."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


PROTOCOL_ID = "rcl-gold-pilot-apply-calibration-review"
PROTOCOL_VERSION = "0.1.0"
ACCEPTED_STATUSES = {"accepted", "reviewed", "approved"}
ASSISTED_REVIEWERS = {"codex-assisted", "machine", "auto", "automated"}

UPDATE_FIELDS = [
    "manual_doc_type",
    "manual_source_type",
    "contains_pii",
    "pii_types",
    "legal_basis",
    "legal_status",
    "extraction_quality",
    "train_recommendation",
    "exclusion_reason",
    "reviewer",
    "reviewed_at",
    "review_notes",
]

REQUIRED_FOR_APPLY = [
    "manual_doc_type",
    "manual_source_type",
    "contains_pii",
    "legal_status",
    "extraction_quality",
    "train_recommendation",
    "reviewer",
    "reviewed_at",
]

CONTROLLED_VALUES = {
    "manual_doc_type": {
        "organization_comment",
        "individual_comment",
        "government_response",
        "cover_letter",
        "draft_law",
        "attachment",
        "other",
    },
    "manual_source_type": {
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
    "contains_pii": {"yes", "no", "uncertain"},
    "legal_status": {"review_needed", "eligible", "exclude", "uncertain"},
    "extraction_quality": {"good", "usable", "poor", "not_extractable"},
    "train_recommendation": {"include", "exclude", "conditional", "undecided"},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def status_for(row: dict[str, str]) -> str:
    return row.get("manual_review_status", "").strip().lower()


def reviewer_is_assisted(row: dict[str, str]) -> bool:
    reviewer = row.get("reviewer", "").strip().lower()
    return reviewer in ASSISTED_REVIEWERS or reviewer.startswith("codex")


def validate_candidate(row: dict[str, str], allow_assisted_reviewer: bool) -> list[str]:
    errors: list[str] = []
    queue_id = row.get("queue_id", "")
    if status_for(row) not in ACCEPTED_STATUSES:
        errors.append(f"{queue_id}: manual_review_status must be one of {sorted(ACCEPTED_STATUSES)}")
    for field in REQUIRED_FOR_APPLY:
        if not row.get(field, "").strip():
            errors.append(f"{queue_id}: missing required field {field}")
    for field, allowed in CONTROLLED_VALUES.items():
        value = row.get(field, "").strip()
        if value not in allowed:
            errors.append(f"{queue_id}: invalid {field}={value!r}")
    if reviewer_is_assisted(row) and not allow_assisted_reviewer:
        errors.append(f"{queue_id}: reviewer appears machine-assisted; require human reviewer or --allow-assisted-reviewer")
    if row.get("legal_status") == "eligible" and "review" in row.get("legal_basis", "").lower():
        errors.append(f"{queue_id}: legal_status=eligible needs a document-specific legal basis, not only review-needed text")
    if row.get("train_recommendation") == "include" and row.get("legal_status") != "eligible":
        errors.append(f"{queue_id}: train_recommendation=include requires legal_status=eligible")
    if row.get("contains_pii") == "yes" and row.get("train_recommendation") == "include":
        errors.append(f"{queue_id}: train_recommendation=include is incompatible with unresolved PII")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply accepted calibration review rows to annotations.csv.")
    parser.add_argument("--input-dir", default="data/rcl_gold_pilot_v0_1")
    parser.add_argument(
        "--source",
        default="review_pack/calibration_review_suggestions.csv",
        help="CSV containing reviewed calibration rows, relative to --input-dir unless absolute.",
    )
    parser.add_argument("--commit", action="store_true", help="Write annotations.csv; default is dry-run.")
    parser.add_argument("--allow-assisted-reviewer", action="store_true")
    parser.add_argument("--actor", default="unassigned")
    args = parser.parse_args()

    started_at = utc_now()
    run_id = "rcl-apply-calibration-" + started_at.replace(":", "").replace("-", "").replace("+", "z")
    root = Path(args.input_dir)
    source_path = Path(args.source)
    if not source_path.is_absolute():
        source_path = root / source_path
    annotations_path = root / "annotations.csv"
    annotation_fields, annotations = read_csv(annotations_path)
    source_fields, source_rows = read_csv(source_path)

    missing_source_fields = sorted({"queue_id", "manual_review_status", *UPDATE_FIELDS} - set(source_fields))
    errors: list[str] = []
    warnings: list[str] = []
    if missing_source_fields:
        errors.append(f"source CSV missing fields: {missing_source_fields}")

    annotation_by_queue_id = {row["queue_id"]: row for row in annotations}
    source_queue_ids = [row.get("queue_id", "") for row in source_rows]
    duplicate_source_ids = sorted(
        queue_id for queue_id, count in Counter(source_queue_ids).items() if queue_id and count > 1
    )
    if duplicate_source_ids:
        errors.append(f"duplicate source queue_id: {duplicate_source_ids[:5]}")

    accepted_rows: list[dict[str, str]] = []
    skipped_rows: list[dict[str, str]] = []
    candidate_errors: list[str] = []
    for row in source_rows:
        queue_id = row.get("queue_id", "")
        if queue_id not in annotation_by_queue_id:
            candidate_errors.append(f"{queue_id}: absent from annotations.csv")
            continue
        status = status_for(row)
        if status not in ACCEPTED_STATUSES:
            skipped_rows.append({"queue_id": queue_id, "reason": f"status={status or 'empty'}"})
            continue
        row_errors = validate_candidate(row, args.allow_assisted_reviewer)
        if row_errors:
            candidate_errors.extend(row_errors)
        else:
            accepted_rows.append(row)

    if candidate_errors:
        errors.extend(candidate_errors)
    if not accepted_rows:
        warnings.append("no accepted calibration rows to apply")

    output_annotations: list[dict[str, str]] = [dict(row) for row in annotations]
    applied_ids: list[str] = []
    if not errors:
        output_by_queue_id = {row["queue_id"]: row for row in output_annotations}
        for row in accepted_rows:
            target = output_by_queue_id[row["queue_id"]]
            for field in UPDATE_FIELDS:
                target[field] = row[field]
            applied_ids.append(row["queue_id"])
        if args.commit and applied_ids:
            backup_path = annotations_path.with_suffix(".csv.bak")
            shutil.copyfile(annotations_path, backup_path)
            write_csv(annotations_path, annotation_fields, output_annotations)
        elif not args.commit:
            warnings.append("dry-run only; annotations.csv was not changed")

    report = {
        "object": {"id": "rcl:gold-set-pilot-apply-calibration-review", "kind": "annotation_update_run"},
        "protocol": {
            "id": PROTOCOL_ID,
            "version": PROTOCOL_VERSION,
            "tool": "scripts/rcl_apply_calibration_review.py",
            "input": str(source_path),
        },
        "run": {
            "id": run_id,
            "actor": args.actor,
            "started_at": started_at,
            "finished_at": utc_now(),
            "mode": "commit" if args.commit else "dry_run",
        },
        "evidence": {
            "source_rows": len(source_rows),
            "accepted_rows": len(accepted_rows),
            "applied_rows": len(applied_ids) if args.commit else 0,
            "would_apply_rows": len(applied_ids) if not args.commit else 0,
            "skipped_rows": len(skipped_rows),
            "applied_queue_ids": applied_ids,
            "skipped": skipped_rows,
        },
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "warnings": warnings,
        "claims": [],
    }
    report_path = root / "review_pack" / "calibration_apply_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    runs_dir = root / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_path = runs_dir / f"{run_id}.json"
    run_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
