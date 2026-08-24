#!/usr/bin/env python3
"""Create a source-download queue excluding documents already in a review artifact."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the remaining RCL source queue.")
    parser.add_argument("--queue", default="data/rcl_2026_consultations/review_queue.csv")
    parser.add_argument(
        "--completed",
        action="append",
        default=[],
        help="Completed annotations CSV. May be passed more than once.",
    )
    parser.add_argument(
        "--output",
        default="data/rcl_2026_consultations/review_queue_remaining_after_pilot.csv",
    )
    parser.add_argument("--actor", default="Codex-assisted")
    args = parser.parse_args()

    queue_path = Path(args.queue)
    output_path = Path(args.output)

    queue = read_csv(queue_path)
    completed_paths = args.completed or ["data/rcl_gold_pilot_v0_1/annotations.csv"]
    completed = []
    for completed_path in completed_paths:
        completed.extend(read_csv(Path(completed_path)))
    completed_urls = {row["document_url"] for row in completed if row.get("document_url")}
    completed_digests = {row["artifact_sha256"] for row in completed if row.get("artifact_sha256")}

    remaining = [row for row in queue if row["document_url"] not in completed_urls]
    remaining.sort(key=lambda row: (int(row["priority"]), row["queue_id"]))
    write_csv(output_path, remaining, list(queue[0].keys()) if queue else [])

    run = {
        "tool": "scripts/rcl_make_remaining_source_queue.py",
        "version": "0.1.0",
        "actor": args.actor,
        "generated_at": utc_now(),
        "inputs": {
            "queue": str(queue_path),
            "completed": [str(Path(path)) for path in completed_paths],
        },
        "outputs": {
            "queue": str(output_path),
            "run_json": str(output_path.with_suffix(".run.json")),
        },
        "evidence": {
            "source_queue_rows": len(queue),
            "completed_rows": len(completed),
            "completed_unique_urls": len(completed_urls),
            "completed_unique_digests": len(completed_digests),
            "remaining_rows": len(remaining),
            "remaining_priorities": dict(Counter(row["priority"] for row in remaining)),
        },
    }
    run_path = output_path.with_suffix(".run.json")
    run_path.write_text(json.dumps(run, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(run, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
