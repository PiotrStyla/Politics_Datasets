#!/usr/bin/env python3
"""Download and register a bounded RCL gold-set review pilot."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import mimetypes
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


PROTOCOL_ID = "rcl-gold-pilot-download"
PROTOCOL_VERSION = "0.2.0"
DEFAULT_USER_AGENT = "rcl-gold-pilot/0.1 (+research; public-source-review)"

ANNOTATION_FIELDS = [
    "queue_id",
    "priority",
    "project_id",
    "project_number",
    "project_created",
    "applicant",
    "category",
    "filename",
    "document_url",
    "listed_author",
    "document_created",
    "artifact_sha256",
    "artifact_bytes",
    "media_type",
    "fetch_status",
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


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_queue(path: Path, priority: int, limit: int) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        if priority <= 0:
            rows = list(csv.DictReader(handle))
        else:
            rows = [row for row in csv.DictReader(handle) if int(row["priority"]) == priority]
    rows.sort(key=lambda row: (int(row["priority"]), row["queue_id"]))
    return rows[:limit] if limit else rows


def fetch(url: str, user_agent: str, timeout: int, retries: int) -> tuple[bytes, str, str]:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            request = Request(url, headers={"User-Agent": user_agent})
            with urlopen(request, timeout=timeout) as response:
                content_type = response.headers.get_content_type()
                return response.read(), content_type, response.geturl()
        except (HTTPError, URLError, TimeoutError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(2**attempt)
    raise RuntimeError(f"download failed after {retries + 1} attempts: {last_error}")


def media_type_for(raw: bytes, reported: str, url: str) -> tuple[str, str]:
    if raw.startswith(b"%PDF-"):
        return "application/pdf", ".pdf"
    if raw.startswith(b"PK\x03\x04"):
        suffix = Path(urlparse(url).path).suffix.lower()
        if suffix in {".docx", ".xlsx", ".pptx"}:
            return mimetypes.guess_type(f"x{suffix}")[0] or reported, suffix
        return reported or "application/zip", suffix or ".zip"
    suffix = Path(urlparse(url).path).suffix.lower()
    return reported or "application/octet-stream", suffix if 1 < len(suffix) <= 9 else ".bin"


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    temporary_path.replace(path)


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ANNOTATION_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    temporary_path.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_checksums(output_dir: Path, raw_dir: Path) -> None:
    checksums = []
    for path in sorted(raw_dir.glob("*")):
        if path.is_file():
            checksums.append(f"{sha256_file(path)}  {path.relative_to(output_dir).as_posix()}")
    checksum_path = output_dir / "checksums.sha256"
    temporary_path = checksum_path.with_suffix(".sha256.tmp")
    temporary_path.write_text("\n".join(checksums) + "\n", encoding="ascii")
    temporary_path.replace(checksum_path)


def checkpoint_outputs(
    output_dir: Path,
    raw_dir: Path,
    manifest: list[dict[str, object]],
    annotations: list[dict[str, str]],
    failures: list[dict[str, str]],
    include_checksums: bool = False,
) -> None:
    write_jsonl(output_dir / "source_manifest.jsonl", manifest)
    write_csv(output_dir / "annotations.csv", annotations)
    write_jsonl(output_dir / "download_failures.jsonl", failures)
    if include_checksums:
        write_checksums(output_dir, raw_dir)


def read_existing_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def read_existing_annotations(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def download_queue_row(
    row: dict[str, str],
    output_dir: Path,
    raw_dir: Path,
    args: argparse.Namespace,
    run_id: str,
) -> tuple[dict[str, object] | None, dict[str, str] | None, dict[str, str] | None]:
    queue_id = row["queue_id"]
    try:
        existing = sorted(raw_dir.glob(f"{queue_id}.*"))
        if existing and not args.overwrite:
            target = existing[0]
            raw = target.read_bytes()
            reported_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            final_url = row["document_url"]
        else:
            raw, reported_type, final_url = fetch(
                row["document_url"], args.user_agent, args.timeout, args.retries
            )
            media_type, suffix = media_type_for(raw, reported_type, final_url)
            target = raw_dir / f"{queue_id}{suffix}"
            temporary_target = target.with_suffix(target.suffix + ".tmp")
            temporary_target.write_bytes(raw)
            temporary_target.replace(target)
            reported_type = media_type
            time.sleep(args.sleep)

        media_type, _ = media_type_for(raw, reported_type, final_url)
        digest = hashlib.sha256(raw).hexdigest()
        relative_path = target.relative_to(output_dir).as_posix()
        object_id = f"rcl:consultation-document:{row['project_id']}:{queue_id}"
        manifest_entry: dict[str, object] = {
            "object": {
                "id": object_id,
                "kind": "dataset_source_document",
                "name": row["filename"],
            },
            "version": {
                "id": f"sha256:{digest}",
                "digest": {"algorithm": "sha256", "value": digest},
                "bytes": len(raw),
                "media_type": media_type,
                "local_path": relative_path,
            },
            "source": {
                "url": row["document_url"],
                "resolved_url": final_url,
                "retrieved_at": utc_now(),
                "project_id": row["project_id"],
                "project_number": row["project_number"],
                "category": row["category"],
            },
            "relations": [
                {
                    "predicate": "GENERATED_BY",
                    "target": {"protocol_id": PROTOCOL_ID, "run_id": run_id},
                },
                {
                    "predicate": "DERIVED_FROM",
                    "target": {"object_id": f"rcl:project:{row['project_id']}"},
                },
            ],
            "review_status": {
                "legal_status": "unreviewed",
                "pii_status": "unreviewed",
                "train_recommendation": "undecided",
            },
        }
        annotation = {
            "queue_id": queue_id,
            "priority": row["priority"],
            "project_id": row["project_id"],
            "project_number": row["project_number"],
            "project_created": row["project_created"],
            "applicant": row["applicant"],
            "category": row["category"],
            "filename": row["filename"],
            "document_url": row["document_url"],
            "listed_author": row["author"],
            "document_created": row["doc_created"],
            "artifact_sha256": digest,
            "artifact_bytes": str(len(raw)),
            "media_type": media_type,
            "fetch_status": "downloaded",
            "manual_doc_type": "",
            "manual_source_type": "",
            "contains_pii": "unreviewed",
            "pii_types": "",
            "legal_basis": "",
            "legal_status": "unreviewed",
            "extraction_quality": "unreviewed",
            "train_recommendation": "undecided",
            "exclusion_reason": "",
            "reviewer": "",
            "reviewed_at": "",
            "review_notes": "",
        }
        return manifest_entry, annotation, None
    except Exception as exc:
        return None, None, {
            "queue_id": queue_id,
            "document_url": row["document_url"],
            "error": str(exc),
        }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Build the bounded RCL gold-set review pilot.")
    parser.add_argument("--queue", default="data/rcl_2026_consultations/review_queue.csv")
    parser.add_argument("--output-dir", default="data/rcl_gold_pilot_v0_1")
    parser.add_argument("--priority", type=int, default=1, help="Use 0 for every priority in the queue.")
    parser.add_argument("--limit", type=int, default=40, help="Use 0 for every matching row.")
    parser.add_argument("--sleep", type=float, default=0.75)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--checkpoint-every", type=int, default=25)
    parser.add_argument("--actor", default=os.environ.get("RCL_ACTOR", "unassigned"))
    parser.add_argument("--user-agent", default=os.environ.get("RCL_USER_AGENT", DEFAULT_USER_AGENT))
    args = parser.parse_args()

    started_at = utc_now()
    run_id = "rcl-gold-pilot-" + started_at.replace(":", "").replace("-", "").replace("+", "z")
    output_dir = Path(args.output_dir)
    raw_dir = output_dir / "raw_documents"
    runs_dir = output_dir / "runs"
    raw_dir.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(parents=True, exist_ok=True)

    queue_path = Path(args.queue)
    selected = read_queue(queue_path, args.priority, args.limit)
    if not selected:
        raise SystemExit(f"no queue rows found for priority {args.priority}")
    if args.workers < 1:
        parser.error("--workers must be at least 1")
    if args.checkpoint_every < 1:
        parser.error("--checkpoint-every must be at least 1")

    selected_ids = {row["queue_id"] for row in selected}
    manifest_by_queue = {
        str(entry["object"]["id"]).rsplit(":", 1)[-1]: entry
        for entry in read_existing_jsonl(output_dir / "source_manifest.jsonl")
        if str(entry["object"]["id"]).rsplit(":", 1)[-1] in selected_ids
    }
    annotation_by_queue = {
        row["queue_id"]: row
        for row in read_existing_annotations(output_dir / "annotations.csv")
        if row["queue_id"] in selected_ids
    }
    failure_by_queue = {
        str(row["queue_id"]): {str(key): str(value) for key, value in row.items()}
        for row in read_existing_jsonl(output_dir / "download_failures.jsonl")
        if str(row["queue_id"]) in selected_ids
    }
    pending = [row for row in selected if row["queue_id"] not in annotation_by_queue]
    completed_before = len(annotation_by_queue)
    print(
        f"resume: {len(annotation_by_queue)} completed, {len(pending)} pending, "
        f"{len(failure_by_queue)} prior failures"
    )

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        for batch_start in range(0, len(pending), args.checkpoint_every):
            batch = pending[batch_start : batch_start + args.checkpoint_every]
            results = executor.map(
                lambda row: download_queue_row(row, output_dir, raw_dir, args, run_id),
                batch,
            )
            for batch_offset, (row, result) in enumerate(zip(batch, results), start=1):
                manifest_entry, annotation, failure = result
                queue_id = row["queue_id"]
                index = completed_before + batch_start + batch_offset
                print(f"{index}/{len(selected)} {queue_id}: {row['filename']}")
                if failure is not None:
                    failure_by_queue[queue_id] = failure
                    print(f"ERROR {queue_id}: {failure['error']}")
                    continue
                assert manifest_entry is not None and annotation is not None
                manifest_by_queue[queue_id] = manifest_entry
                annotation_by_queue[queue_id] = annotation
                failure_by_queue.pop(queue_id, None)

            manifest = [manifest_by_queue[row["queue_id"]] for row in selected if row["queue_id"] in manifest_by_queue]
            annotations = [annotation_by_queue[row["queue_id"]] for row in selected if row["queue_id"] in annotation_by_queue]
            failures = [failure_by_queue[row["queue_id"]] for row in selected if row["queue_id"] in failure_by_queue]
            checkpoint_outputs(output_dir, raw_dir, manifest, annotations, failures)

    manifest = [manifest_by_queue[row["queue_id"]] for row in selected if row["queue_id"] in manifest_by_queue]
    annotations = [annotation_by_queue[row["queue_id"]] for row in selected if row["queue_id"] in annotation_by_queue]
    failures = [failure_by_queue[row["queue_id"]] for row in selected if row["queue_id"] in failure_by_queue]

    manifest_path = output_dir / "source_manifest.jsonl"
    annotation_path = output_dir / "annotations.csv"
    failure_path = output_dir / "download_failures.jsonl"
    write_jsonl(manifest_path, manifest)
    write_csv(annotation_path, annotations)
    write_jsonl(failure_path, failures)
    write_checksums(output_dir, raw_dir)

    finished_at = utc_now()
    run = {
        "object": {"id": "rcl:gold-set-pilot", "kind": "dataset_review_set"},
        "version": {
            "id": f"sha256:{sha256_file(manifest_path)}",
            "manifest": "source_manifest.jsonl",
        },
        "protocol": {
            "id": PROTOCOL_ID,
            "version": PROTOCOL_VERSION,
            "tool": "scripts/rcl_gold_pilot.py",
            "input_queue": str(queue_path),
            "selection": {"priority": args.priority, "limit": args.limit},
        },
        "run": {
            "id": run_id,
            "actor": args.actor,
            "started_at": started_at,
            "finished_at": finished_at,
        },
        "evidence": {
            "queue_rows_selected": len(selected),
            "documents_downloaded": len(manifest),
            "download_failures": len(failures),
            "bytes_downloaded": sum(int(row["artifact_bytes"]) for row in annotations),
            "annotation_rows_created": len(annotations),
            "reviewed_rows": 0,
        },
        "claims": [],
        "outputs": {
            "manifest": "source_manifest.jsonl",
            "annotations": "annotations.csv",
            "checksums": "checksums.sha256",
            "failures": "download_failures.jsonl",
            "raw_documents": "raw_documents/",
        },
    }
    run_path = runs_dir / f"{run_id}.json"
    run_path.write_text(json.dumps(run, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    print(f"documents_downloaded: {len(manifest)}")
    print(f"download_failures: {len(failures)}")
    print(f"manifest_sha256: {sha256_file(manifest_path)}")
    print(f"output: {output_dir.resolve()}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
