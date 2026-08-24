#!/usr/bin/env python3
"""Prepare a metadata-only Polish DynaWord handoff package for RCL data."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


SOURCE_ID = "rcl_legislacja_consultations"
OUTPUT_FIELDS = [
    "dynaword_candidate_id",
    "dynaword_schema_status",
    "source_batch",
    "queue_id",
    "document_url",
    "created",
    "author",
    "source",
    "license",
    "token_count_proxy",
    "char_count",
    "word_count",
    "text_sha256",
    "text_path_local_only",
    "raw_sha256",
    "artifact_sha256",
    "media_type",
    "extract_status",
    "extraction_quality",
    "manual_doc_type",
    "manual_source_type",
    "contains_pii",
    "pii_types",
    "legal_status",
    "train_recommendation",
    "reviewer",
    "reviewed_at",
    "handoff_decision",
    "handoff_blockers",
    "notes",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def token_proxy(char_count: int, word_count: int) -> int:
    # Conservative planning proxy for Polish subword tokenizers without binding to a model.
    return round(max(char_count / 3.5, word_count * 1.5))


def handoff_decision(annotation: dict[str, str], observation: dict[str, str], reviewed: bool) -> tuple[str, str]:
    blockers: list[str] = []
    if annotation.get("legal_status") != "eligible":
        blockers.append("legal_review_needed")
    if annotation.get("contains_pii") == "yes" or observation.get("machine_pii_hint") == "yes":
        blockers.append("pii_scrub_needed")
    if observation.get("machine_extraction_quality_hint") in {"poor", "not_extractable"}:
        blockers.append("extraction_quality_review_needed")
    if not reviewed:
        blockers.append("human_review_needed")
    if annotation.get("train_recommendation") == "exclude":
        return "exclude_from_training_candidate", ";".join(blockers or ["excluded_by_review"])
    if not reviewed:
        return "draft_candidate_do_not_train", ";".join(blockers)
    return "reviewed_candidate_blocked_until_clearance", ";".join(blockers)


def load_batch(root: Path, name: str) -> list[dict[str, str]]:
    annotations = {row["queue_id"]: row for row in read_csv(root / "annotations.csv")}
    observations = {row["queue_id"]: row for row in read_csv(root / "machine_observations.csv")}
    rows: list[dict[str, str]] = []
    for queue_id, annotation in sorted(annotations.items()):
        observation = observations.get(queue_id, {})
        reviewed = bool(annotation.get("reviewer", "").strip())
        char_count = int(observation.get("char_count") or 0)
        word_count = int(observation.get("word_count") or 0)
        decision, blockers = handoff_decision(annotation, observation, reviewed)
        local_text_path = observation.get("text_path", "")
        schema_status = "adapter_metadata_only"
        rows.append(
            {
                "dynaword_candidate_id": f"{SOURCE_ID}:{name}:{queue_id}",
                "dynaword_schema_status": schema_status,
                "source_batch": name,
                "queue_id": queue_id,
                "document_url": annotation.get("document_url", ""),
                "created": annotation.get("document_created", ""),
                "author": annotation.get("listed_author", "") or annotation.get("applicant", ""),
                "source": SOURCE_ID,
                "license": "source-specific-rights-under-review",
                "token_count_proxy": str(token_proxy(char_count, word_count)),
                "char_count": str(char_count),
                "word_count": str(word_count),
                "text_sha256": observation.get("text_sha256", ""),
                "text_path_local_only": local_text_path,
                "raw_sha256": observation.get("raw_sha256", ""),
                "artifact_sha256": annotation.get("artifact_sha256", ""),
                "media_type": annotation.get("media_type", observation.get("source_media_type", "")),
                "extract_status": observation.get("extract_status", ""),
                "extraction_quality": annotation.get("extraction_quality")
                if reviewed
                else observation.get("machine_extraction_quality_hint", ""),
                "manual_doc_type": annotation.get("manual_doc_type", ""),
                "manual_source_type": annotation.get("manual_source_type", ""),
                "contains_pii": annotation.get("contains_pii")
                if reviewed
                else observation.get("machine_pii_hint", ""),
                "pii_types": annotation.get("pii_types", "") or observation.get("machine_pii_types", ""),
                "legal_status": annotation.get("legal_status", "unreviewed"),
                "train_recommendation": annotation.get("train_recommendation", "undecided"),
                "reviewer": annotation.get("reviewer", ""),
                "reviewed_at": annotation.get("reviewed_at", ""),
                "handoff_decision": decision,
                "handoff_blockers": blockers,
                "notes": "Metadata-only handoff. Text payload remains local until legal/PII clearance.",
            }
        )
    return rows


def write_readme(path: Path, rows: list[dict[str, str]], generated_at: str) -> None:
    decisions = Counter(row["handoff_decision"] for row in rows)
    batches = Counter(row["source_batch"] for row in rows)
    legal = Counter(row["legal_status"] for row in rows)
    pii = Counter(row["contains_pii"] for row in rows)
    total_tokens = sum(int(row["token_count_proxy"] or 0) for row in rows)
    reviewed = sum(1 for row in rows if row["reviewer"])
    text = f"""# RCL Polish DynaWord Handoff v0.1

Generated at: `{generated_at}`

This is a metadata-only handoff package for evaluating RCL/RPL public
consultation documents as a possible Polish DynaWord source. It is not a
training split and it does not publish extracted text payloads.

## Scope

- rows: {len(rows)}
- reviewed rows: {reviewed}
- token proxy: {total_tokens:,}
- source batches: `{json.dumps(dict(sorted(batches.items())), ensure_ascii=False, sort_keys=True)}`
- handoff decisions: `{json.dumps(dict(sorted(decisions.items())), ensure_ascii=False, sort_keys=True)}`
- legal statuses: `{json.dumps(dict(sorted(legal.items())), ensure_ascii=False, sort_keys=True)}`
- PII flags: `{json.dumps(dict(sorted(pii.items())), ensure_ascii=False, sort_keys=True)}`

## DynaWord Schema Mapping

Polish DynaWord stable releases use the canonical columns:
`id, text, source, added, created, token_count, license, author`.

This package maps the auditable fields that are ready:

- `id` -> `dynaword_candidate_id`
- `source` -> `rcl_legislacja_consultations`
- `created` -> RCL document creation date where available
- `author` -> RCL listed author/applicant where available
- `token_count` -> `token_count_proxy`
- `license` -> `source-specific-rights-under-review`

The `text` field is intentionally absent. Use `text_path_local_only` only inside
the local workspace after legal and PII review authorizes text handling.

## Release Boundary

No row is training-ready in this handoff. Rows are blocked by at least one of:
legal review, PII scrubbing, extraction quality review, or human-review status.
The correct next step is review and filtering, not direct inclusion in
Polish DynaWord stable parquets.

## Files

- `dynaword_candidate_manifest.csv`
- `dynaword_candidate_manifest.jsonl`
- `dynaword_handoff_run.json`
- `source_datasheet.md`
"""
    path.write_text(text, encoding="utf-8", newline="\n")


def write_datasheet(path: Path, rows: list[dict[str, str]], generated_at: str) -> None:
    text = f"""# Datasheet: RCL/RPL Public Consultation Documents

Generated at: `{generated_at}`

## Source

Official Rządowy Proces Legislacyjny / RCL public consultation document URLs
discovered from `legislacja.gov.pl`.

## Intended DynaWord Role

Candidate source for legal/provenance review and possible later controlled
inclusion. This source should be capped or separately ablated if included,
because legislative consultation language can over-weight legal/administrative
style.

## Current Status

- metadata and local raw snapshots: prepared
- local text extraction: prepared
- human review: partial
- PII review: not cleared
- legal review: not cleared
- training release: not cleared

## Legal Basis

Working premise only: public official RCL/RPL source documents with plausible
public-sector information reuse path. No blanket open-content license has been
assigned. Per-document legal review must verify attribution, reuse,
copyright/database-right and PII constraints.

## Personal Data

The source contains organizational submissions and some individual/private
person rows. PII hints are present and must be scrubbed or excluded before any
training-text release.

## Provenance Artifacts

See `source_manifest.jsonl`, `checksums.sha256`, extraction manifests, validation
reports and legal review packs in the RCL dataset-source repository.
"""
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare RCL metadata-only DynaWord handoff.")
    parser.add_argument("--output-dir", default="data/rcl_dynaword_handoff_v0_1")
    parser.add_argument("--actor", default="Codex-assisted")
    args = parser.parse_args()

    batches = [
        ("accepted_40", Path("data/rcl_gold_pilot_v0_1")),
        ("accepted_42", Path("data/rcl_remaining_consultations_v0_1")),
        ("draft_918", Path("data/rcl_2026_selected_remaining_918_v0_1")),
    ]
    rows: list[dict[str, str]] = []
    for name, root in batches:
        rows.extend(load_batch(root, name))

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = utc_now()
    write_csv(output_dir / "dynaword_candidate_manifest.csv", rows)
    write_jsonl(output_dir / "dynaword_candidate_manifest.jsonl", rows)
    write_readme(output_dir / "README.md", rows, generated_at)
    write_datasheet(output_dir / "source_datasheet.md", rows, generated_at)

    run = {
        "tool": "scripts/rcl_prepare_dynaword_handoff.py",
        "version": "0.1.0",
        "actor": args.actor,
        "generated_at": generated_at,
        "output_dir": str(output_dir),
        "summary": {
            "rows": len(rows),
            "reviewed_rows": sum(1 for row in rows if row["reviewer"]),
            "token_count_proxy": sum(int(row["token_count_proxy"] or 0) for row in rows),
            "handoff_decisions": dict(Counter(row["handoff_decision"] for row in rows)),
            "source_batches": dict(Counter(row["source_batch"] for row in rows)),
            "legal_statuses": dict(Counter(row["legal_status"] for row in rows)),
        },
        "claims": [],
        "publication_boundary": {
            "metadata_only": True,
            "text_payload_included": False,
            "training_ready": False,
        },
    }
    (output_dir / "dynaword_handoff_run.json").write_text(
        json.dumps(run, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(run, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
