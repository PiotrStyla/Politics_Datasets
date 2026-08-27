#!/usr/bin/env python3
"""Build a compact, searchable RCL index from a pinned private HF snapshot."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from huggingface_hub import HfApi, snapshot_download


DEFAULT_REPO = "PiotrSty/rcl-legislacja-consultations"
DEFAULT_REVISION = "d9646f04d15b29b9b9d45896804f6240eaad7cb6"
DEFAULT_OUTPUT = Path("data/rcl_search_index_v0_1")
DEFAULT_REMOTE_DIR = "search_index/v0.1.0"

BATCHES = (
    "rcl_gold_pilot_v0_1",
    "rcl_remaining_consultations_v0_1",
    "rcl_2026_selected_remaining_918_v0_1",
    "rcl_2025_selected_v0_1",
    "rcl_2026_delta_20260826_v0_1",
)

INDEX_COLUMNS = (
    "id",
    "text",
    "source_batch",
    "queue_id",
    "project_id",
    "project_number",
    "project_created",
    "applicant",
    "category",
    "filename",
    "document_url",
    "listed_author",
    "document_created",
    "media_type",
    "source_sha256",
    "text_sha256",
    "char_count",
    "word_count",
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
    "review_notes",
    "source_repo",
    "source_revision",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def read_annotations(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {row["queue_id"]: row for row in csv.DictReader(handle)}


def queue_id_from_manifest(row: dict[str, Any]) -> str:
    local_path = row.get("version", {}).get("local_path", "")
    return Path(local_path).stem


def source_by_queue_id(path: Path) -> dict[str, dict[str, Any]]:
    return {queue_id_from_manifest(row): row for row in read_jsonl(path)}


def build_row(
    snapshot: Path,
    batch: str,
    extraction: dict[str, Any],
    source: dict[str, Any],
    annotation: dict[str, str],
    repo_id: str,
    revision: str,
) -> dict[str, Any]:
    queue_id = queue_id_from_manifest(extraction)
    text_rel = extraction.get("version", {}).get("local_path", "")
    text_path = snapshot / batch / Path(text_rel)
    text = text_path.read_text(encoding="utf-8", errors="replace") if text_path.exists() else ""

    source_meta = source.get("source", {})
    source_version = source.get("version", {})
    text_version = extraction.get("version", {})
    run_evidence = extraction.get("run_evidence", {})
    source_review = source.get("review_status", {})

    def value(name: str, fallback: Any = "") -> Any:
        return annotation.get(name, "") or fallback

    return {
        "id": f"rcl:{batch}:{queue_id}",
        "text": text,
        "source_batch": batch,
        "queue_id": queue_id,
        "project_id": value("project_id", source_meta.get("project_id", "")),
        "project_number": value("project_number", source_meta.get("project_number", "")),
        "project_created": value("project_created"),
        "applicant": value("applicant"),
        "category": value("category", source_meta.get("category", "")),
        "filename": value("filename", source.get("object", {}).get("name", "")),
        "document_url": value(
            "document_url", source_meta.get("resolved_url") or source_meta.get("url", "")
        ),
        "listed_author": value("listed_author"),
        "document_created": value("document_created"),
        "media_type": value("media_type", source_version.get("media_type", "")),
        "source_sha256": value(
            "artifact_sha256", source_version.get("digest", {}).get("value", "")
        ),
        "text_sha256": text_version.get("digest", {}).get("value", ""),
        "char_count": int(text_version.get("chars") or len(text)),
        "word_count": int(text_version.get("words") or len(text.split())),
        "extract_status": run_evidence.get("extract_status", ""),
        "extraction_quality": value("extraction_quality"),
        "manual_doc_type": value("manual_doc_type"),
        "manual_source_type": value("manual_source_type"),
        "contains_pii": value("contains_pii", source_review.get("pii_status", "")),
        "pii_types": value("pii_types"),
        "legal_status": value("legal_status", source_review.get("legal_status", "unreviewed")),
        "train_recommendation": value(
            "train_recommendation", source_review.get("train_recommendation", "undecided")
        ),
        "reviewer": value("reviewer"),
        "reviewed_at": value("reviewed_at"),
        "review_notes": value("review_notes"),
        "source_repo": repo_id,
        "source_revision": revision,
    }


def build_index(snapshot: Path, repo_id: str, revision: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for batch in BATCHES:
        root = snapshot / batch
        extraction_path = root / "extraction_manifest.jsonl"
        source_path = root / "source_manifest.jsonl"
        if not extraction_path.exists() or not source_path.exists():
            raise FileNotFoundError(f"Missing manifests for {batch}")

        sources = source_by_queue_id(source_path)
        annotations = read_annotations(root / "annotations.csv")
        for extraction in read_jsonl(extraction_path):
            queue_id = queue_id_from_manifest(extraction)
            source = sources.get(queue_id)
            if source is None:
                raise ValueError(f"Missing source manifest row for {batch}/{queue_id}")
            rows.append(
                build_row(
                    snapshot,
                    batch,
                    extraction,
                    source,
                    annotations.get(queue_id, {}),
                    repo_id,
                    revision,
                )
            )

    df = pd.DataFrame(rows, columns=INDEX_COLUMNS)
    if df["id"].duplicated().any():
        duplicates = df.loc[df["id"].duplicated(), "id"].tolist()[:10]
        raise ValueError(f"Duplicate index IDs: {duplicates}")
    return df


def write_artifacts(df: pd.DataFrame, output_dir: Path, repo_id: str, revision: str) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    index_path = output_dir / "rcl_search_index.parquet"
    df.to_parquet(index_path, index=False, compression="zstd")

    generated_at = utc_now()
    evidence = {
        "artifact_type": "evidence/rcl-search-index-validation",
        "generated_at": generated_at,
        "source": {"repository": repo_id, "revision": revision},
        "index": {
            "path": index_path.name,
            "sha256": sha256_file(index_path),
            "bytes": index_path.stat().st_size,
            "rows": len(df),
            "rows_with_text": int(df["text"].astype(bool).sum()),
            "unique_ids": int(df["id"].nunique()),
            "source_batches": df["source_batch"].value_counts().sort_index().to_dict(),
            "extract_statuses": df["extract_status"].value_counts(dropna=False).sort_index().to_dict(),
            "legal_statuses": df["legal_status"].value_counts(dropna=False).sort_index().to_dict(),
            "pii_statuses": df["contains_pii"].value_counts(dropna=False).sort_index().to_dict(),
            "total_chars": int(df["char_count"].sum()),
            "total_words": int(df["word_count"].sum()),
        },
        "checks": {
            "all_ids_unique": bool(df["id"].is_unique),
            "all_rows_have_source_url": bool(df["document_url"].astype(bool).all()),
            "all_rows_have_source_digest": bool(df["source_sha256"].astype(bool).all()),
            "text_presence_matches_extract_status": bool(
                (df["text"].astype(bool) == df["extract_status"].eq("extracted")).all()
            ),
        },
        "interpretation_boundary": (
            "This derivative enables private retrieval. It does not change legal, PII, "
            "quality, redistribution, or training eligibility statuses."
        ),
    }
    evidence_path = output_dir / "rcl_search_index_evidence.json"
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )

    run = {
        "artifact_type": "run/rcl-search-index-build",
        "tool": "scripts/rcl_build_search_index.py",
        "protocol_version": "0.1.0",
        "actor": "Codex-assisted",
        "generated_at": generated_at,
        "inputs": {"repository": repo_id, "revision": revision, "batches": list(BATCHES)},
        "outputs": {
            "index": index_path.name,
            "index_sha256": evidence["index"]["sha256"],
            "evidence": evidence_path.name,
        },
    }
    (output_dir / "rcl_search_index_run.json").write_text(
        json.dumps(run, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    return evidence


def upload_artifacts(repo_id: str, output_dir: Path, remote_dir: str) -> str:
    result = HfApi().upload_folder(
        repo_id=repo_id,
        repo_type="dataset",
        folder_path=output_dir,
        path_in_repo=remote_dir,
        commit_message="Add compact private RCL search index v0.1.0",
    )
    return result.oid


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-id", default=DEFAULT_REPO)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--remote-dir", default=DEFAULT_REMOTE_DIR)
    parser.add_argument("--upload", action="store_true")
    args = parser.parse_args()

    allow_patterns = []
    for batch in BATCHES:
        allow_patterns.extend(
            [
                f"{batch}/source_manifest.jsonl",
                f"{batch}/extraction_manifest.jsonl",
                f"{batch}/annotations.csv",
                f"{batch}/extracted_text/*",
            ]
        )

    snapshot = Path(
        snapshot_download(
            repo_id=args.repo_id,
            repo_type="dataset",
            revision=args.revision,
            allow_patterns=allow_patterns,
        )
    )
    df = build_index(snapshot, args.repo_id, args.revision)
    evidence = write_artifacts(df, args.output_dir, args.repo_id, args.revision)
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))

    if args.upload:
        oid = upload_artifacts(args.repo_id, args.output_dir, args.remote_dir)
        print(json.dumps({"uploaded": True, "commit": oid, "path": args.remote_dir}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
