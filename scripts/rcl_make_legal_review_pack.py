#!/usr/bin/env python3
"""Build a legal-review pack for the RCL gold pilot."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


LEGAL_REVIEW_STATUSES = {"review_needed", "uncertain"}
DEFAULT_SOURCE_CHECKS = (
    "RPL document URL; RCL BIP reuse page; current open-data/public-sector "
    "information reuse act; document-specific notices and attachments"
)
DEFAULT_REVIEW_QUESTION = (
    "Can this public RCL/RPL document, or cleaned extracted text derived from it, "
    "be redistributed and used in a pretraining dataset under stated attribution, "
    "PII and reuse conditions?"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_jsonl(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def legal_priority(row: dict[str, str]) -> str:
    if row["train_recommendation"] == "exclude":
        return "3_exclusion_confirmation"
    if row["contains_pii"] in {"yes", "uncertain"}:
        return "1_training_candidate_with_pii"
    return "2_training_candidate_low_pii"


def legal_question(row: dict[str, str]) -> str:
    if row["train_recommendation"] == "exclude":
        return (
            "Confirm whether legal review agrees with exclusion, and whether metadata-only "
            "publication remains acceptable."
        )
    if row["contains_pii"] in {"yes", "uncertain"}:
        return (
            DEFAULT_REVIEW_QUESTION
            + " Pay special attention to personal data, signatures and contact details."
        )
    return DEFAULT_REVIEW_QUESTION


def make_rows(root: Path) -> tuple[list[dict[str, str]], dict[str, object]]:
    annotations = read_csv(root / "annotations.csv")
    manifest = read_jsonl(root / "source_manifest.jsonl")
    manifest_by_digest = {
        str(item["version"]["digest"]["value"]): item for item in manifest
    }

    rows: list[dict[str, str]] = []
    for index, row in enumerate(annotations, start=1):
        if row["legal_status"] not in LEGAL_REVIEW_STATUSES:
            continue
        manifest_item = manifest_by_digest.get(row["artifact_sha256"], {})
        source = manifest_item.get("source", {}) if isinstance(manifest_item, dict) else {}
        version = manifest_item.get("version", {}) if isinstance(manifest_item, dict) else {}
        legal_row = {
            "legal_review_id": f"rcl-legal-{len(rows) + 1:04d}",
            "source_queue_id": row["queue_id"],
            "legal_review_priority": legal_priority(row),
            "project_id": row["project_id"],
            "project_number": row["project_number"],
            "project_created": row["project_created"],
            "applicant": row["applicant"],
            "category": row["category"],
            "filename": row["filename"],
            "document_url": row["document_url"],
            "source_page_url": str(source.get("page_url", "")),
            "listed_author": row["listed_author"],
            "document_created": row["document_created"],
            "artifact_sha256": row["artifact_sha256"],
            "artifact_bytes": row["artifact_bytes"],
            "media_type": row["media_type"],
            "manifest_local_path": str(version.get("local_path", "")),
            "manual_doc_type": row["manual_doc_type"],
            "manual_source_type": row["manual_source_type"],
            "contains_pii": row["contains_pii"],
            "pii_types": row["pii_types"],
            "extraction_quality": row["extraction_quality"],
            "train_recommendation": row["train_recommendation"],
            "exclusion_reason": row["exclusion_reason"],
            "current_legal_status": row["legal_status"],
            "working_legal_basis": row["legal_basis"],
            "source_checks": DEFAULT_SOURCE_CHECKS,
            "legal_question": legal_question(row),
            "legal_decision": "",
            "allowed_release_artifacts": "",
            "required_attribution": "",
            "required_pii_handling": "",
            "legal_reviewer": "",
            "legal_reviewed_at": "",
            "legal_notes": "",
        }
        rows.append(legal_row)

    rows.sort(
        key=lambda item: (
            item["legal_review_priority"],
            item["project_id"],
            item["source_queue_id"],
        )
    )
    for index, row in enumerate(rows, start=1):
        row["legal_review_id"] = f"rcl-legal-{index:04d}"

    summary = {
        "annotations": len(annotations),
        "legal_review_rows": len(rows),
        "legal_statuses": dict(Counter(row["legal_status"] for row in annotations)),
        "review_priorities": dict(Counter(row["legal_review_priority"] for row in rows)),
        "doc_types": dict(Counter(row["manual_doc_type"] for row in rows)),
        "source_types": dict(Counter(row["manual_source_type"] for row in rows)),
        "contains_pii": dict(Counter(row["contains_pii"] for row in rows)),
        "train_recommendations": dict(Counter(row["train_recommendation"] for row in rows)),
    }
    return rows, summary


def write_readme(path: Path, root: Path, rows: list[dict[str, str]], summary: dict[str, object]) -> None:
    generated_at = utc_now()
    text = f"""# RCL Legal Review Pack

Generated at: `{generated_at}`

Input artifact: `{root.as_posix()}`

This pack is for legal review of the RCL gold-pilot rows whose current
`legal_status` is `review_needed` or `uncertain`. It does not contain raw PDF,
DOCX or extracted-text payloads. It gives reviewers document-level provenance,
the working legal premise, PII flags and explicit decision fields.

## Working Premise

Rows were collected from public URLs in the official Rzadowy Proces
Legislacyjny service (`legislacja.gov.pl`). The working premise is that these
are public official RCL/RPL legislative-process documents with a plausible
public-sector information reuse path. This is not a blanket license assignment
and does not clear text redistribution or model pretraining.

Legal reviewers should check:

- whether public-sector information reuse applies to the specific document,
- whether any document-specific notices, copyright or database-right limits
  apply,
- what attribution/source/time notice is required,
- whether extracted text may be redistributed,
- whether use in a pretraining corpus is allowed,
- what PII/signature/contact-detail handling is required.

## Source References

- RCL BIP reuse page: https://bip.rcl.gov.pl/rcl/ponowne-wykorzystywanie/3122%2CPonowne-wykorzystywanie.html
- KPRM public-sector information reuse page: https://www.gov.pl/web/premier/ponowne-wykorzystywanie
- Current statutory reference: https://isap.sejm.gov.pl/isap.nsf/DocDetails.xsp?id=WDU20210001641

## Files

- `legal_review_queue.csv` - row-level review queue and empty decision fields.
- `legal_review_run.json` - generation metadata and aggregate counts.

## Counts

- legal review rows: {summary["legal_review_rows"]}
- source annotation rows: {summary["annotations"]}
- priorities: `{json.dumps(summary["review_priorities"], ensure_ascii=False, sort_keys=True)}`
- train recommendations: `{json.dumps(summary["train_recommendations"], ensure_ascii=False, sort_keys=True)}`
- PII flags: `{json.dumps(summary["contains_pii"], ensure_ascii=False, sort_keys=True)}`

## Decision Fields

Reviewers should fill:

- `legal_decision`: `eligible`, `eligible_with_conditions`, `exclude`,
  `metadata_only`, or `uncertain`.
- `allowed_release_artifacts`: for example `metadata`, `checksums`,
  `cleaned_text`, `redacted_text`, `raw_document`, or a narrower condition.
- `required_attribution`: source, author, timestamp and processing notices.
- `required_pii_handling`: redaction, exclusion, signature stripping or other
  constraints.
- `legal_reviewer`, `legal_reviewed_at`, `legal_notes`.

## Boundary

Until these fields are completed, `review_needed` means "not yet cleared", not
"blocked". No row should be treated as training-ready based only on public
availability in RPL.
"""
    path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an RCL legal-review pack.")
    parser.add_argument("--input-dir", default="data/rcl_gold_pilot_v0_1")
    parser.add_argument("--output-dir", default="legal_review_pack")
    parser.add_argument("--actor", default="Codex-assisted")
    args = parser.parse_args()

    root = Path(args.input_dir)
    output_dir = root / args.output_dir
    rows, summary = make_rows(root)

    fieldnames = [
        "legal_review_id",
        "source_queue_id",
        "legal_review_priority",
        "project_id",
        "project_number",
        "project_created",
        "applicant",
        "category",
        "filename",
        "document_url",
        "source_page_url",
        "listed_author",
        "document_created",
        "artifact_sha256",
        "artifact_bytes",
        "media_type",
        "manifest_local_path",
        "manual_doc_type",
        "manual_source_type",
        "contains_pii",
        "pii_types",
        "extraction_quality",
        "train_recommendation",
        "exclusion_reason",
        "current_legal_status",
        "working_legal_basis",
        "source_checks",
        "legal_question",
        "legal_decision",
        "allowed_release_artifacts",
        "required_attribution",
        "required_pii_handling",
        "legal_reviewer",
        "legal_reviewed_at",
        "legal_notes",
    ]

    queue_path = output_dir / "legal_review_queue.csv"
    run_path = output_dir / "legal_review_run.json"
    readme_path = output_dir / "README.md"
    write_csv(queue_path, rows, fieldnames)
    write_readme(readme_path, root, rows, summary)

    run = {
        "tool": "scripts/rcl_make_legal_review_pack.py",
        "version": "0.1.0",
        "actor": args.actor,
        "generated_at": utc_now(),
        "input_dir": str(root),
        "output_dir": str(output_dir),
        "outputs": {
            "queue_csv": str(queue_path),
            "readme": str(readme_path),
            "run_json": str(run_path),
        },
        "summary": summary,
    }
    run_path.write_text(json.dumps(run, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(run, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
