#!/usr/bin/env python3
"""Create a deterministic manual-review calibration queue for the RCL pilot."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path


PROTOCOL_ID = "rcl-gold-pilot-calibration-queue"
PROTOCOL_VERSION = "0.1.0"
CALIBRATION_FIELDS = [
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


def read_jsonl(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def reason_for(priority: str) -> str:
    if priority == "extraction_first":
        return "ocr_or_scan_review"
    if priority == "standard":
        return "clean_text_baseline"
    if priority == "pii_first":
        return "pii_triage_baseline"
    return "scope_check"


def select_rows(observations: list[dict[str, str]], limit: int) -> list[dict[str, str]]:
    buckets = [
        ("extraction_first", 2),
        ("standard", 4),
        ("pii_first", 4),
        ("scope_check", 2),
    ]
    selected: list[dict[str, str]] = []
    selected_ids: set[str] = set()
    rows_by_priority = {
        priority: sorted(
            [row for row in observations if row["machine_review_priority"] == priority],
            key=lambda row: row["queue_id"],
        )
        for priority, _ in buckets
    }
    for priority, quota in buckets:
        for row in rows_by_priority.get(priority, [])[:quota]:
            if row["queue_id"] not in selected_ids and len(selected) < limit:
                selected.append(row)
                selected_ids.add(row["queue_id"])

    if len(selected) < limit:
        for row in sorted(observations, key=lambda row: row["queue_id"]):
            if row["queue_id"] not in selected_ids:
                selected.append(row)
                selected_ids.add(row["queue_id"])
                if len(selected) == limit:
                    break
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a 10-row RCL calibration review queue.")
    parser.add_argument("--input-dir", default="data/rcl_gold_pilot_v0_1")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--actor", default="unassigned")
    args = parser.parse_args()

    started_at = utc_now()
    run_id = "rcl-calibration-" + started_at.replace(":", "").replace("-", "").replace("+", "z")
    root = Path(args.input_dir)
    observations = read_csv(root / "machine_observations.csv")
    annotations = {row["queue_id"]: row for row in read_csv(root / "annotations.csv")}
    source_manifest = read_jsonl(root / "source_manifest.jsonl")
    raw_path_by_queue_id = {
        str(item["object"]["id"]).rsplit(":", 1)[-1]: str(item["version"]["local_path"])
        for item in source_manifest
    }

    rows: list[dict[str, str]] = []
    for rank, observation in enumerate(select_rows(observations, args.limit), start=1):
        queue_id = observation["queue_id"]
        annotation = annotations[queue_id]
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

    output_path = root / "calibration_queue.csv"
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CALIBRATION_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    run = {
        "object": {"id": "rcl:gold-set-pilot-calibration-queue", "kind": "dataset_review_queue"},
        "protocol": {
            "id": PROTOCOL_ID,
            "version": PROTOCOL_VERSION,
            "tool": "scripts/rcl_make_calibration_queue.py",
            "input": ["annotations.csv", "machine_observations.csv", "source_manifest.jsonl"],
            "selection": {
                "limit": args.limit,
                "buckets": {
                    "extraction_first": 2,
                    "standard": 4,
                    "pii_first": 4,
                    "scope_check": 2,
                },
            },
        },
        "run": {
            "id": run_id,
            "actor": args.actor,
            "started_at": started_at,
            "finished_at": utc_now(),
        },
        "evidence": {
            "rows_selected": len(rows),
            "review_reasons": {
                reason: sum(1 for row in rows if row["review_reason"] == reason)
                for reason in sorted({row["review_reason"] for row in rows})
            },
        },
        "claims": [],
        "outputs": {"calibration_queue": "calibration_queue.csv"},
    }
    runs_dir = root / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_path = runs_dir / f"{run_id}.json"
    run_path.write_text(json.dumps(run, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    print(f"calibration_rows: {len(rows)}")
    print(f"output: {output_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
