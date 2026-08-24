#!/usr/bin/env python3
"""Build a deterministic manual-review queue from RCL document metadata."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path


REVIEW_FIELDS = [
    "queue_id",
    "priority",
    "project_id",
    "project_number",
    "project_created",
    "applicant",
    "category",
    "filename",
    "document_url",
    "author",
    "doc_created",
    "manual_doc_type",
    "manual_source_type",
    "pii_risk",
    "legal_status",
    "train_candidate",
    "exclusion_reason",
    "reviewer",
    "review_notes",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def priority_for(doc: dict[str, str]) -> int:
    category = doc["category"].lower()
    filename = doc["filename"].lower()
    if "stanowisk" in category:
        return 1
    if "odniesienie" in category or "uwag" in category or "uwag" in filename:
        return 2
    if "pisma kierujące" in category:
        return 3
    return 4


def build_queue(args: argparse.Namespace) -> list[dict[str, str]]:
    projects = {row["project_id"]: row for row in read_csv(Path(args.projects_csv))}
    docs = read_csv(Path(args.documents_csv))
    selected_docs = [doc for doc in docs if doc.get("selected") == "True"]
    selected_docs.sort(key=lambda doc: (priority_for(doc), doc["project_id"], doc["category"], doc["filename"]))

    by_priority: dict[int, list[dict[str, str]]] = defaultdict(list)
    for doc in selected_docs:
        by_priority[priority_for(doc)].append(doc)

    rows: list[dict[str, str]] = []
    for priority in sorted(by_priority):
        bucket = by_priority[priority]
        limit = args.per_priority if args.per_priority else len(bucket)
        for doc in bucket[:limit]:
            project = projects.get(doc["project_id"], {})
            rows.append(
                {
                    "queue_id": f"rcl-review-{len(rows) + 1:04d}",
                    "priority": str(priority),
                    "project_id": doc["project_id"],
                    "project_number": doc["project_number"],
                    "project_created": project.get("created", ""),
                    "applicant": project.get("applicant", ""),
                    "category": doc["category"],
                    "filename": doc["filename"],
                    "document_url": doc["document_url"],
                    "author": doc["author"],
                    "doc_created": doc["created"],
                    "manual_doc_type": "",
                    "manual_source_type": "",
                    "pii_risk": "",
                    "legal_status": "",
                    "train_candidate": "",
                    "exclusion_reason": "",
                    "reviewer": "",
                    "review_notes": "",
                }
            )
            if args.limit and len(rows) >= args.limit:
                return rows
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a manual-review queue from RCL consultation metadata.")
    parser.add_argument("--projects-csv", default="data/rcl_2026_consultations/projects.csv")
    parser.add_argument("--documents-csv", default="data/rcl_2026_consultations/documents.csv")
    parser.add_argument("--output", default="data/rcl_2026_consultations/review_queue.csv")
    parser.add_argument("--limit", type=int, default=100, help="Maximum rows in the queue. Use 0 for no limit.")
    parser.add_argument("--per-priority", type=int, default=0, help="Optional cap per priority bucket.")
    args = parser.parse_args()
    if args.limit == 0:
        args.limit = None
    if args.per_priority == 0:
        args.per_priority = None

    rows = build_queue(args)
    write_csv(Path(args.output), rows)
    print(f"review_queue_rows: {len(rows)}")
    print(f"output: {Path(args.output).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
