#!/usr/bin/env python3
"""Create a deterministic review queue for unreviewed RCL pilot rows."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


PROTOCOL_ID = "rcl-gold-pilot-remaining-review-queue"
PROTOCOL_VERSION = "0.1.0"
QUEUE_FIELDS = [
    "calibration_rank",
    "queue_id",
    "review_reason",
    "document_url",
    "filename",
    "raw_path",
    "text_path",
    "source_media_type",
    "machine_review_priority",
    "extract_status",
    "machine_extraction_quality_hint",
    "machine_pii_hint",
    "machine_pii_types",
    "char_count",
    "word_count",
    "manual_review_status",
    "reviewer",
    "reviewed_at",
    "review_notes",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def read_jsonl(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def reason_for(priority: str) -> str:
    if priority == "extraction_first":
        return "ocr_or_scan_review"
    if priority == "standard":
        return "clean_text_baseline"
    if priority == "pii_first":
        return "pii_triage"
    return "scope_check"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a queue for unreviewed RCL pilot rows.")
    parser.add_argument("--input-dir", default="data/rcl_gold_pilot_v0_1")
    parser.add_argument("--output", default="remaining_review_queue.csv")
    parser.add_argument("--actor", default="unassigned")
    args = parser.parse_args()

    started_at = utc_now()
    run_id = "rcl-remaining-review-" + started_at.replace(":", "").replace("-", "").replace("+", "z")
    root = Path(args.input_dir)
    annotations = [row for row in read_csv(root / "annotations.csv") if not row["reviewer"].strip()]
    observations = {row["queue_id"]: row for row in read_csv(root / "machine_observations.csv")}
    source_manifest = read_jsonl(root / "source_manifest.jsonl")
    raw_path_by_queue_id = {
        str(item["object"]["id"]).rsplit(":", 1)[-1]: str(item["version"]["local_path"])
        for item in source_manifest
    }

    annotations.sort(key=lambda row: row["queue_id"])
    rows: list[dict[str, str]] = []
    for rank, annotation in enumerate(annotations, start=1):
        queue_id = annotation["queue_id"]
        observation = observations[queue_id]
        rows.append(
            {
                "calibration_rank": str(rank),
                "queue_id": queue_id,
                "review_reason": reason_for(observation["machine_review_priority"]),
                "document_url": annotation["document_url"],
                "filename": annotation["filename"],
                "raw_path": raw_path_by_queue_id[queue_id],
                "text_path": observation["text_path"],
                "source_media_type": observation["source_media_type"],
                "machine_review_priority": observation["machine_review_priority"],
                "extract_status": observation["extract_status"],
                "machine_extraction_quality_hint": observation["machine_extraction_quality_hint"],
                "machine_pii_hint": observation["machine_pii_hint"],
                "machine_pii_types": observation["machine_pii_types"],
                "char_count": observation["char_count"],
                "word_count": observation["word_count"],
                "manual_review_status": "not_started",
                "reviewer": "",
                "reviewed_at": "",
                "review_notes": "",
            }
        )

    output_path = root / args.output
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=QUEUE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    run = {
        "object": {"id": "rcl:gold-set-pilot-remaining-review-queue", "kind": "dataset_review_queue"},
        "protocol": {
            "id": PROTOCOL_ID,
            "version": PROTOCOL_VERSION,
            "tool": "scripts/rcl_make_remaining_review_queue.py",
            "input": ["annotations.csv", "machine_observations.csv", "source_manifest.jsonl"],
        },
        "run": {
            "id": run_id,
            "actor": args.actor,
            "started_at": started_at,
            "finished_at": utc_now(),
        },
        "evidence": {
            "rows_selected": len(rows),
            "review_reasons": dict(sorted(Counter(row["review_reason"] for row in rows).items())),
        },
        "claims": [],
        "outputs": {"remaining_review_queue": args.output},
    }
    runs_dir = root / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_path = runs_dir / f"{run_id}.json"
    run_path.write_text(json.dumps(run, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    print(f"remaining_review_rows: {len(rows)}")
    print(f"output: {output_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
