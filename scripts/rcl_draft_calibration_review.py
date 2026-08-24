#!/usr/bin/env python3
"""Draft conservative calibration-review suggestions from local RCL review pack data."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


PROTOCOL_ID = "rcl-gold-pilot-draft-calibration-review"
PROTOCOL_VERSION = "0.1.0"

OUTPUT_FIELDS = [
    "calibration_rank",
    "queue_id",
    "review_reason",
    "filename",
    "document_url",
    "raw_path",
    "text_path",
    "manual_doc_type",
    "manual_source_type",
    "contains_pii",
    "pii_types",
    "legal_basis",
    "legal_status",
    "extraction_quality",
    "train_recommendation",
    "exclusion_reason",
    "manual_review_status",
    "reviewer",
    "reviewed_at",
    "review_notes",
    "draft_confidence",
    "draft_basis",
]

ORG_PATTERNS = [
    ("religious_organization", re.compile(r"alians ewangeliczny|ko[śs]ci[oó][łl]", re.IGNORECASE)),
    ("employer_organization", re.compile(r"\bzbp\b|zwi[aą]zek bank[oó]w|pracodawc[oó]w rp", re.IGNORECASE)),
    ("professional_body", re.compile(r"\bizfia\b|izba zarz[aą]dzaj[aą]cych", re.IGNORECASE)),
    ("ngo", re.compile(r"amnesty international|ordo iuris|helsi[nń]sk|watchdog|fundacja|stowarzyszenie", re.IGNORECASE)),
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def text_for(root: Path, row: dict[str, str]) -> str:
    path = root / row["text_path"]
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def infer_doc_type(filename: str, text: str) -> tuple[str, str]:
    basis: list[str] = []
    lower_name = filename.lower()
    head = text[:6000].lower()
    if "zbiór uwag" in lower_name or "zbior uwag" in lower_name:
        return "government_response", "filename indicates collected comments with responses"
    if "tabela uwag" in head and "stanowisko" in head and "podmiot" in head:
        return "government_response", "text has consultation table with government-response column"
    if "załącznik do stanowiska" in head or "zalacznik do stanowiska" in head:
        return "organization_comment", "text identifies an attachment to an organization position"
    if "stanowisko" in lower_name:
        return "organization_comment", "filename identifies a submitted position"
    if "uwagi" in lower_name:
        basis.append("filename contains comments/remarks")
    if "tabela uwag" in lower_name:
        basis.append("filename contains comment table")
    return "organization_comment", "; ".join(basis) or "default for calibration queue"


def infer_source_type(filename: str, text: str, doc_type: str) -> tuple[str, str]:
    combined = f"{filename}\n{text[:4000]}"
    if doc_type == "government_response":
        return "public_body", "document appears to be a compiled response/aggregation table"
    for label, pattern in ORG_PATTERNS:
        if pattern.search(combined):
            return label, f"matched source pattern for {label}"
    return "unknown", "no reliable source-type cue in filename or extracted text head"


def infer_pii(row: dict[str, str], text: str, doc_type: str) -> tuple[str, str, str]:
    machine_hint = row["machine_pii_hint"]
    machine_types = row["machine_pii_types"]
    lower = text.lower()
    if row["machine_extraction_quality_hint"] == "not_extractable":
        return "uncertain", "", "text extraction empty; inspect raw document"
    if machine_hint == "yes":
        return "yes", machine_types, "machine PII hint requires reviewer confirmation"
    if doc_type == "government_response" and ("obywatel" in lower or "osoba fizyczna" in lower):
        return "uncertain", "person_name", "aggregated table may include individual submitters"
    return "uncertain", "", "no machine PII hit, but reviewer must confirm"


def recommendation(extraction_quality: str, contains_pii: str, doc_type: str) -> tuple[str, str]:
    if extraction_quality == "not_extractable":
        return "exclude", "empty extraction; OCR or manual transcription required before use"
    if doc_type == "government_response":
        return "conditional", "aggregation/response table; include only if target mix wants this document type"
    if contains_pii == "yes":
        return "conditional", "PII scrub and legal review required before release or training use"
    return "conditional", "legal review required before release or training use"


def confidence(row: dict[str, str], doc_type: str, source_type: str) -> str:
    if row["machine_extraction_quality_hint"] == "not_extractable":
        return "low"
    if doc_type == "government_response" or source_type == "unknown":
        return "medium"
    return "medium"


def draft_row(root: Path, row: dict[str, str], reviewer: str, reviewed_at: str) -> dict[str, str]:
    text = text_for(root, row)
    doc_type, doc_basis = infer_doc_type(row["filename"], text)
    source_type, source_basis = infer_source_type(row["filename"], text, doc_type)
    contains_pii, pii_types, pii_basis = infer_pii(row, text, doc_type)
    extraction_quality = row["machine_extraction_quality_hint"]
    train_recommendation, exclusion_reason = recommendation(extraction_quality, contains_pii, doc_type)
    if train_recommendation == "conditional":
        exclusion_reason = ""
    legal_basis = (
        "RCL source URL recorded; document-specific copyright/public-information and PII basis "
        "requires legal review before release."
    )
    review_notes = (
        f"Draft suggestion only. Doc type: {doc_basis}. Source type: {source_basis}. "
        f"PII: {pii_basis}."
    )
    return {
        "calibration_rank": row["calibration_rank"],
        "queue_id": row["queue_id"],
        "review_reason": row["review_reason"],
        "filename": row["filename"],
        "document_url": row["document_url"],
        "raw_path": row["raw_path"],
        "text_path": row["text_path"],
        "manual_doc_type": doc_type,
        "manual_source_type": source_type,
        "contains_pii": contains_pii,
        "pii_types": pii_types,
        "legal_basis": legal_basis,
        "legal_status": "review_needed",
        "extraction_quality": extraction_quality,
        "train_recommendation": train_recommendation,
        "exclusion_reason": exclusion_reason,
        "manual_review_status": "needs_human_acceptance",
        "reviewer": reviewer,
        "reviewed_at": reviewed_at,
        "review_notes": review_notes,
        "draft_confidence": confidence(row, doc_type, source_type),
        "draft_basis": "local extracted text, filenames, machine_observations; no external legal conclusion",
    }


def write_summary(path: Path, rows: list[dict[str, str]], created_at: str) -> None:
    counters = {
        "manual_doc_type": Counter(row["manual_doc_type"] for row in rows),
        "manual_source_type": Counter(row["manual_source_type"] for row in rows),
        "contains_pii": Counter(row["contains_pii"] for row in rows),
        "extraction_quality": Counter(row["extraction_quality"] for row in rows),
        "train_recommendation": Counter(row["train_recommendation"] for row in rows),
        "draft_confidence": Counter(row["draft_confidence"] for row in rows),
    }
    lines = [
        "# RCL calibration review suggestions",
        "",
        f"Generated at: `{created_at}`",
        "",
        "These are conservative draft suggestions, not final legal or human-review claims.",
        "All rows keep `legal_status=review_needed`.",
        "",
    ]
    for field, counter in counters.items():
        lines.append(f"## {field}")
        lines.extend(f"- {key}: {value}" for key, value in sorted(counter.items()))
        lines.append("")
    lines.append("## Next step")
    lines.append("")
    lines.append(
        "A reviewer should inspect the raw document and extracted text, edit the suggestions where needed, "
        "and only then copy settled values into `annotations.csv`."
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Draft conservative calibration-review suggestions.")
    parser.add_argument("--input-dir", default="data/rcl_gold_pilot_v0_1")
    parser.add_argument("--review-pack-dir", default="review_pack")
    parser.add_argument("--actor", default="Codex-assisted")
    args = parser.parse_args()

    started_at = utc_now()
    run_id = "rcl-draft-calibration-" + started_at.replace(":", "").replace("-", "").replace("+", "z")
    root = Path(args.input_dir)
    review_pack = root / args.review_pack_dir
    input_path = review_pack / "calibration_review_sheet.csv"
    rows = read_csv(input_path)
    drafted = [draft_row(root, row, args.actor, started_at) for row in rows]

    output_path = review_pack / "calibration_review_suggestions.csv"
    summary_path = review_pack / "calibration_review_suggestions.md"
    write_csv(output_path, OUTPUT_FIELDS, drafted)
    write_summary(summary_path, drafted, started_at)

    run = {
        "object": {"id": "rcl:gold-set-pilot-draft-calibration-review", "kind": "draft_review_evidence"},
        "protocol": {
            "id": PROTOCOL_ID,
            "version": PROTOCOL_VERSION,
            "tool": "scripts/rcl_draft_calibration_review.py",
            "input": "review_pack/calibration_review_sheet.csv",
        },
        "run": {
            "id": run_id,
            "actor": args.actor,
            "started_at": started_at,
            "finished_at": utc_now(),
        },
        "evidence": {
            "rows": len(drafted),
            "doc_type_counts": dict(sorted(Counter(row["manual_doc_type"] for row in drafted).items())),
            "source_type_counts": dict(sorted(Counter(row["manual_source_type"] for row in drafted).items())),
            "pii_counts": dict(sorted(Counter(row["contains_pii"] for row in drafted).items())),
            "legal_status_counts": dict(sorted(Counter(row["legal_status"] for row in drafted).items())),
        },
        "claims": [],
        "outputs": {
            "suggestions_csv": "review_pack/calibration_review_suggestions.csv",
            "suggestions_summary": "review_pack/calibration_review_suggestions.md",
        },
    }
    runs_dir = root / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_path = runs_dir / f"{run_id}.json"
    run_path.write_text(json.dumps(run, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    print(f"draft_rows: {len(drafted)}")
    print(f"suggestions: {output_path.resolve()}")
    print(f"summary: {summary_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
