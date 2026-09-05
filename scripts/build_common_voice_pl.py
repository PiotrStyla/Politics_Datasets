#!/usr/bin/env python3
"""Build the text-only Polish Common Voice contribution for DynaWord.

The source Parquet embeds audio. This builder uses DuckDB column projection over
HTTP and never materializes the audio column or direct contributor metadata.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import importlib.metadata
import json
import pathlib
import platform
import re
import shutil
import sys
import unicodedata
from typing import Any


SOURCE_NAME = "common_voice_pl"
MIRROR_REPOSITORY = "Peacockery/common-voice-scripted-speech-26"
MIRROR_REVISION = "b4d8b94d43831475de59a455345acf6945cfd66e"
UPSTREAM_DATASET_ID = "cmqinmu2a00winq07gyrtri0q"
UPSTREAM_VERSION = "26.0"
UPSTREAM_RELEASE_DATE = "2026-06-12"
UPSTREAM_URL = f"https://mozilladatacollective.com/datasets/{UPSTREAM_DATASET_ID}"
SOURCE_PARQUET_PATH = (
    "data/validated/"
    "common_voice_scripted_speech_26_0__pl__cmqinmu2a00winq07gyrtri0q.parquet"
)
SOURCE_PARQUET_URL = (
    f"https://huggingface.co/datasets/{MIRROR_REPOSITORY}/resolve/"
    f"{MIRROR_REVISION}/{SOURCE_PARQUET_PATH}"
)
SOURCE_PARQUET_SHA256 = "abd846a0411d04cf88920161100625e9cbe64a111d17474ac49375f490dafb3a"
SOURCE_PARQUET_SIZE = 4_481_707_510
TARGET_REPOSITORY = "SlayerLab/polish-dynaword"
OWN_REPOSITORY = "PiotrSty/common-voice-pl-text"
SOURCE_LICENSE = "CC0-1.0"
AUTHOR = "Mozilla Common Voice contributors"
EXPECTED_FIELDS = (
    "id", "text", "source", "added", "created", "token_count", "license", "author"
)
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
URL_RE = re.compile(r"(?i)\b(?:https?://|www\.)\S+")
EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
PESEL_RE = re.compile(r"(?<!\d)\d{11}(?!\d)")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?48[ .-]?)?(?:\d[ .-]?){9}(?!\d)")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
HTML_RE = re.compile(r"<[^>]{1,120}>")
REPEATED_RE = re.compile(r"(.)\1{7,}", re.IGNORECASE)


class BuildError(ValueError):
    pass


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def write_json(path: pathlib.Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    value = value.replace("\u00a0", " ").replace("\u200b", "")
    return " ".join(value.split()).strip()


def dedup_key(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).casefold()
    folded = "".join(" " if unicodedata.category(ch).startswith("P") else ch for ch in folded)
    return " ".join(folded.split())


def quality_rejection(text: str) -> str | None:
    if len(text) < 12:
        return "too_short"
    if len(text) > 500:
        return "too_long"
    if CONTROL_RE.search(text):
        return "control_character"
    if HTML_RE.search(text):
        return "html"
    if URL_RE.search(text):
        return "url"
    if EMAIL_RE.search(text):
        return "email"
    if PESEL_RE.search(text):
        return "pesel_like"
    if PHONE_RE.search(text):
        return "phone_like"
    if REPEATED_RE.search(text):
        return "repeated_character"
    letters = sum(ch.isalpha() for ch in text)
    if letters < 6 or letters / max(1, len(text)) < 0.45:
        return "low_letter_ratio"
    return None


def stable_id(key: str) -> str:
    return f"{SOURCE_NAME}_{hashlib.sha256(key.encode('utf-8')).hexdigest()}"


def source_registry_entry() -> str:
    return f'''    "{SOURCE_NAME}": {{
        "file_key": "{SOURCE_NAME}",
        "pretty": "Mozilla Common Voice Polish validated sentences (v26.0)",
        "license": "{SOURCE_LICENSE}",
        "license_spdx": "{SOURCE_LICENSE}",
        "traceable": "Mozilla Data Collective distributes Common Voice Scripted "
                     "Speech 26.0 under CC0-1.0; this text-only projection retains "
                     "only sentences associated with validated recordings.",
        "upstream": "{UPSTREAM_URL}",
        "provenance": "Official Mozilla dataset {UPSTREAM_DATASET_ID}, accessed "
                      "through the pinned row-normalized HF mirror "
                      "{MIRROR_REPOSITORY}@{MIRROR_REVISION}.",
        "domain": "spoken/scripted contemporary sentences",
        "created": "{UPSTREAM_RELEASE_DATE}, {UPSTREAM_RELEASE_DATE}",
        "is_ocr": False,
        "custom_datasheet": True,
    }},
'''


def update_registry(registry: str) -> str:
    if re.search(rf'^\s{{4}}["\']{SOURCE_NAME}["\']\s*:', registry, re.MULTILINE):
        required = (
            f'"file_key": "{SOURCE_NAME}"',
            f'"license_spdx": "{SOURCE_LICENSE}"',
            f'"upstream": "{UPSTREAM_URL}"',
        )
        if not all(value in registry for value in required):
            raise BuildError(f"existing {SOURCE_NAME} registry entry differs from the contract")
        return registry
    marker = '    "global_voices": {'
    if registry.count(marker) != 1:
        raise BuildError("cannot locate global_voices registry entry")
    return registry.replace(marker, source_registry_entry() + marker, 1)


def source_rows() -> list[dict[str, Any]]:
    import duckdb

    query = """
        SELECT
            sentence_id, sentence, sentence_domain, source_dataset_id,
            collection, locale, language, license, license_url,
            duration_ms, up_votes, down_votes
        FROM read_parquet(?)
        ORDER BY sentence_id, sentence
    """
    connection = duckdb.connect()
    try:
        table = connection.execute(query, [SOURCE_PARQUET_URL]).to_arrow_table()
    finally:
        connection.close()
    return table.to_pylist()


def aggregate(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    sentence_ids: set[str] = set()
    rejected: collections.Counter[str] = collections.Counter()
    contract: collections.Counter[str] = collections.Counter()

    for row in rows:
        if row.get("locale") != "pl" or row.get("language") != "Polish":
            contract["unexpected_language"] += 1
            continue
        if row.get("source_dataset_id") != UPSTREAM_DATASET_ID:
            contract["unexpected_dataset_id"] += 1
            continue
        if str(row.get("license") or "").upper() != SOURCE_LICENSE:
            contract["unexpected_license"] += 1
            continue
        text = normalize_text(str(row.get("sentence") or ""))
        reason = quality_rejection(text)
        if reason:
            rejected[reason] += 1
            continue
        key = dedup_key(text)
        if not key:
            rejected["empty_dedup_key"] += 1
            continue
        sentence_id = str(row.get("sentence_id") or "").strip()
        if not sentence_id:
            rejected["missing_sentence_id"] += 1
            continue
        sentence_ids.add(sentence_id)
        current = groups.get(key)
        candidate = {
            "key": key,
            "text": text,
            "sentence_id": sentence_id,
            "sentence_ids": {sentence_id},
            "clip_count": 1,
            "duration_ms": int(row.get("duration_ms") or 0),
            "up_votes": int(row.get("up_votes") or 0),
            "down_votes": int(row.get("down_votes") or 0),
            "sentence_domain": str(row.get("sentence_domain") or "").strip(),
            "collection": str(row.get("collection") or "").strip(),
            "license_url": str(row.get("license_url") or "").strip(),
        }
        if current is None:
            groups[key] = candidate
            continue
        current["clip_count"] += 1
        current["duration_ms"] += candidate["duration_ms"]
        current["up_votes"] = max(current["up_votes"], candidate["up_votes"])
        current["down_votes"] = max(current["down_votes"], candidate["down_votes"])
        current["sentence_ids"].add(sentence_id)
        if (sentence_id, text) < (current["sentence_id"], current["text"]):
            current["sentence_id"] = sentence_id
            current["text"] = text
        if not current["sentence_domain"] and candidate["sentence_domain"]:
            current["sentence_domain"] = candidate["sentence_domain"]

    if contract:
        raise BuildError(f"source contract violations: {dict(contract)}")
    result = sorted(groups.values(), key=lambda item: (item["key"], item["sentence_id"]))
    for item in result:
        item["sentence_id_count"] = len(item.pop("sentence_ids"))
    diagnostics = {
        "source_rows": len(rows),
        "accepted_source_sentence_ids": len(sentence_ids),
        "rejected_source_rows": sum(rejected.values()),
        "drop_by_reason_source_rows": dict(sorted(rejected.items())),
        "normalized_unique_sentences": len(result),
        "collapsed_accepted_rows": len(rows) - sum(rejected.values()) - len(result),
    }
    return result, diagnostics


def datasheet(stats: dict[str, Any]) -> str:
    return f"""# Common Voice Polish text v26.0

Text-only projection of Polish sentences associated with validated recordings
in Mozilla Common Voice Scripted Speech 26.0.

## Source and scope

- Official upstream: {UPSTREAM_URL}
- Upstream dataset ID: `{UPSTREAM_DATASET_ID}`
- Upstream release: `{UPSTREAM_VERSION}` ({UPSTREAM_RELEASE_DATE})
- Pinned access mirror: `{MIRROR_REPOSITORY}@{MIRROR_REVISION}`
- Selected split: `validated`
- Language: Polish (`pl`)
- License: `{SOURCE_LICENSE}`
- Records: {stats['kept']:,}
- Tokens: {stats['tokens']:,} (`cl100k_base` proxy)

Audio, `client_id`, age, gender, accent, file paths and other direct contributor
metadata are not selected. Repeated recordings of the same normalized sentence
are represented once; aggregate clip count and duration are retained only in the
attribution sidecar.

## Processing

1. Read only selected metadata columns from the pinned Parquet with DuckDB.
2. Require the expected Polish locale, upstream dataset ID and CC0 license.
3. Normalize Unicode and whitespace.
4. Exclude malformed text and simple URL, email, telephone and PESEL-like matches.
5. Collapse case/punctuation-equivalent text within this source.
6. Compute deterministic IDs and `cl100k_base` token counts.

This source has not yet been cross-deduplicated against every released DynaWord
source. The target integration should run the corpus-wide exact and near-duplicate
protocol before a training release. Short isolated sentences should also receive
a source cap in training-mix experiments.
"""


def dataset_card(stats: dict[str, Any], payload_revision: str) -> str:
    return f"""---
license: cc0-1.0
language:
- pl
task_categories:
- text-generation
size_categories:
- 10K<n<100K
pretty_name: Common Voice Polish validated text v26.0
---

# Common Voice Polish validated text v26.0

Versioned text-only research snapshot prepared for Polish DynaWord. It contains
{stats['kept']:,} unique Polish sentences associated with validated Common Voice
recordings and {stats['tokens']:,} `cl100k_base` proxy tokens.

The dataset is derived from [Mozilla Common Voice Scripted Speech 26.0]({UPSTREAM_URL})
through the pinned mirror `{MIRROR_REPOSITORY}@{MIRROR_REVISION}`. The source is
distributed under `CC0-1.0`.

## Files

- `data/train-00000-of-00001.parquet`: DynaWord-compatible text rows.
- `data/common_voice_pl.attribution.jsonl`: non-identifying sentence lineage.
- `data/common_voice_pl.sample.jsonl`: deterministic 20-row sample.
- `artifacts/common_voice_pl.stats.json`: counts and filter diagnostics.
- `artifacts/common_voice_pl.license-evidence.json`: licensing evidence.
- `artifacts/common_voice_pl_ontology_manifest.json`: Slayer ontology graph.
- `src/fetch_common_voice_pl.py`: deterministic rebuild protocol.

The immutable payload revision recorded by the ontology manifest is
`{payload_revision}`. Corpus-wide DynaWord deduplication remains an integration
step; no claim of cross-source novelty is made here.
"""


def contract_test() -> str:
    return f'''"""Contract checks for the {SOURCE_NAME} contribution."""

import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "{SOURCE_NAME}"
MANIFEST = ROOT / "artifacts" / "{SOURCE_NAME}_ontology_manifest.json"


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_schema_and_counts():
    parquet = DATA / "{SOURCE_NAME}.parquet"
    stats = json.loads((DATA / "{SOURCE_NAME}.stats.json").read_text(encoding="utf-8"))
    table = pq.read_table(parquet)
    assert table.column_names == {list(EXPECTED_FIELDS)!r}
    assert table.num_rows == stats["kept"]
    assert len(set(table.column("id").to_pylist())) == table.num_rows
    assert len(set(table.column("text").to_pylist())) == table.num_rows
    assert set(table.column("source").to_pylist()) == {{"{SOURCE_NAME}"}}
    assert set(table.column("license").to_pylist()) == {{"{SOURCE_LICENSE}"}}


def test_privacy_and_sidecars():
    stats = json.loads((DATA / "{SOURCE_NAME}.stats.json").read_text(encoding="utf-8"))
    sidecar = DATA / "{SOURCE_NAME}.attribution.jsonl"
    sample = DATA / "{SOURCE_NAME}.sample.jsonl"
    lines = [json.loads(line) for line in sidecar.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == stats["kept"]
    assert len(sample.read_text(encoding="utf-8").splitlines()) == min(20, stats["kept"])
    forbidden = {{"client_id", "age", "gender", "accents", "path", "audio"}}
    assert all(not (forbidden & set(item)) for item in lines)


def test_manifest_and_checksums():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    required = {{"object", "version", "protocol", "run", "relations", "evidence", "claims", "claim_evidence", "actors", "attestations"}}
    assert required <= set(manifest)
    assert manifest["ontology_version"] == "slayer.ai/research-ontology/v0.1"
    assert manifest["version"]["payload_uri"].startswith("hf://datasets/{OWN_REPOSITORY}@")
    evidence = {{item["observation_type"]: item["payload"] for item in manifest["evidence"]}}
    checksums = evidence["artifact_checksums"]
    expected = {{
        "parquet_sha256": DATA / "{SOURCE_NAME}.parquet",
        "attribution_sha256": DATA / "{SOURCE_NAME}.attribution.jsonl",
        "stats_sha256": DATA / "{SOURCE_NAME}.stats.json",
        "license_evidence_sha256": DATA / "{SOURCE_NAME}.license-evidence.json",
        "sample_sha256": DATA / "{SOURCE_NAME}.sample.jsonl",
    }}
    if "language_audit_sha256" in checksums:
        expected["language_audit_sha256"] = ROOT / "artifacts" / "{SOURCE_NAME}_language_audit.json"
    assert {{key: sha256_file(path) for key, path in expected.items()}} == checksums
'''


def build_manifest(
    stats: dict[str, Any], artifact_digests: dict[str, str], payload_revision: str,
    target_revision: str, run_id: str, run_at: str, script_sha256: str,
    language_audit: dict[str, Any] | None,
) -> dict[str, Any]:
    object_id = f"slayer://object/dataset-source/{SOURCE_NAME}"
    version_digest = canonical_sha256({
        "source_revision": MIRROR_REVISION,
        "upstream_dataset_id": UPSTREAM_DATASET_ID,
        "artifacts": artifact_digests,
    })
    version_id = f"slayer://version/dataset-source/{SOURCE_NAME}@sha256:{version_digest}"
    protocol_id = f"slayer://object/protocol/{SOURCE_NAME}-text-projection"
    protocol_spec = {
        "entrypoint": "python src/fetch_common_voice_pl.py",
        "source_path": "src/fetch_common_voice_pl.py",
        "selection": {
            "locale": "pl", "language": "Polish", "split": "validated",
            "columns_excluded": ["audio", "client_id", "age", "gender", "accents", "variant", "path"],
        },
        "normalization": "Unicode NFKC and whitespace collapse",
        "deduplication": "casefolded punctuation-insensitive exact key within source",
        "quality_filters": ["length", "control characters", "HTML", "URL", "email", "phone-like", "PESEL-like", "letter ratio"],
        "tokenizer": "cl100k_base",
    }
    protocol_digest = canonical_sha256({"script_sha256": script_sha256, "spec": protocol_spec})
    protocol_version_id = f"slayer://version/protocol/{SOURCE_NAME}-text-projection@sha256:{protocol_digest}"

    def evidence(kind: str, payload: Any) -> dict[str, Any]:
        digest = canonical_sha256({"run": run_id, "subject": version_id, "kind": kind, "payload": payload})
        return {
            "id": f"slayer://evidence/{SOURCE_NAME}/{kind}@sha256:{digest}",
            "run_id": run_id, "subject_version": version_id,
            "observation_type": kind, "payload": payload, "observed_at": run_at,
        }

    evidence_items = [
        evidence("dataset_record_counts", stats),
        evidence("artifact_checksums", artifact_digests),
        evidence("license_metadata", {
            "license": SOURCE_LICENSE, "official_dataset": UPSTREAM_URL,
            "mirror_revision": MIRROR_REVISION,
            "source_parquet_sha256": SOURCE_PARQUET_SHA256,
            "source_parquet_size": SOURCE_PARQUET_SIZE,
            "artifact": f"data/{SOURCE_NAME}/{SOURCE_NAME}.license-evidence.json",
        }),
        evidence("direct_metadata_exclusion", {
            "selected_direct_identifiers": 0,
            "excluded_columns": protocol_spec["selection"]["columns_excluded"],
            "text_filter_drop_counts": stats["drop_by_reason_source_rows"],
        }),
        evidence("target_registry_check", {
            "target": f"hf://datasets/{TARGET_REPOSITORY}@{target_revision}",
            "source_key_absent_before_contribution": True,
            "cross_source_exact_dedup_completed": False,
            "cross_source_near_dedup_completed": False,
        }),
        evidence("schema_validation", {"schema": list(EXPECTED_FIELDS), "records": stats["kept"], "valid": True}),
    ]
    if language_audit is not None:
        evidence_items.append(evidence("language_audit", {
            "artifact": f"artifacts/{SOURCE_NAME}_language_audit.json",
            "sha256": artifact_digests["language_audit_sha256"],
            "sample_rows": language_audit["sample_rows"],
            "polish_share": language_audit["polish_share"],
            "interpretation_limit": language_audit["interpretation_limit"],
        }))
    by_type = {item["observation_type"]: item["id"] for item in evidence_items}

    def claim(statement: str, falsification: str, supports: list[str]) -> dict[str, Any]:
        digest = canonical_sha256({"scope": version_id, "statement": statement, "falsification": falsification})
        return {
            "id": f"slayer://claim/{SOURCE_NAME}@sha256:{digest}",
            "scope": version_id, "statement": statement, "asserted_by": "hf:PiotrSty",
            "supported_by": supports, "falsification_condition": falsification,
        }

    claims = [
        claim(
            "The artifact contains one retained row per within-source normalized sentence after the recorded filters.",
            "A retained normalized key occurs more than once or an accepted key is absent without a recorded rejection.",
            [by_type["dataset_record_counts"], by_type["schema_validation"]],
        ),
        claim(
            "The pinned source records and official dataset page identify the selected material as CC0-1.0.",
            "The pinned records or official dataset terms identify a conflicting license.",
            [by_type["license_metadata"]],
        ),
        claim(
            "No source client identifier, demographic field, path or audio payload is included in the published projection.",
            "A forbidden direct-source metadata field is present in the Parquet or attribution sidecar.",
            [by_type["direct_metadata_exclusion"], by_type["schema_validation"]],
        ),
        claim(
            "The source key was absent from the pinned DynaWord registry before this contribution; corpus-wide novelty is not asserted.",
            "The source key exists in the pinned pre-contribution registry or this contribution asserts completed cross-source deduplication.",
            [by_type["target_registry_check"]],
        ),
    ]
    claim_links = [
        {"claim_id": item["id"], "evidence_id": evidence_id, "relation": "SUPPORTS", "introduced_by_run": run_id}
        for item in claims for evidence_id in item["supported_by"]
    ]
    source_version = f"hf://datasets/{MIRROR_REPOSITORY}@{MIRROR_REVISION}"
    upstream_version = f"mdc://dataset/{UPSTREAM_DATASET_ID}@{UPSTREAM_VERSION}"
    target_version = f"hf://datasets/{TARGET_REPOSITORY}@{target_revision}"

    def attestation(kind: str, value: Any, supports: list[str]) -> dict[str, Any]:
        payload = {
            "type": kind, "value": value, "actor_id": "hf:PiotrSty",
            "subject_version": version_id, "supported_by": supports,
        }
        digest = canonical_sha256(payload)
        return {
            "id": f"slayer://attestation/{SOURCE_NAME}/{kind}@sha256:{digest}",
            **payload, "created_at": run_at,
        }

    return {
        "schema_version": "slayer.ai/dataset-source-contribution/v1",
        "ontology_version": "slayer.ai/research-ontology/v0.1",
        "object": {"id": object_id, "kind": "dataset_source", "name": SOURCE_NAME, "metadata": {"language": "pl", "domain": "spoken/scripted", "provider": "Mozilla Data Collective"}},
        "version": {
            "id": version_id, "object_id": object_id, "digest": f"sha256:{version_digest}",
            "schema_version": "slayer.ai/dataset-source/v1",
            "payload_uri": f"hf://datasets/{OWN_REPOSITORY}@{payload_revision}/data/train-00000-of-00001.parquet",
            "created_at": run_at, "created_by": "hf:PiotrSty",
        },
        "protocol": {
            "id": protocol_id, "kind": "dataset_filtering", "name": f"{SOURCE_NAME}-text-projection",
            "version": {
                "id": protocol_version_id, "object_id": protocol_id,
                "digest": f"sha256:{protocol_digest}", "code_sha256": script_sha256,
                "schema_version": "slayer.ai/protocol/v1",
                "payload_uri": f"hf://datasets/{OWN_REPOSITORY}@{payload_revision}/src/fetch_common_voice_pl.py",
                "created_at": run_at, "created_by": "hf:PiotrSty",
            },
            "specification": protocol_spec,
        },
        "run": {
            "id": run_id, "protocol_version_id": protocol_version_id, "actor_id": "hf:PiotrSty",
            "git_commit": payload_revision, "started_at": run_at, "finished_at": run_at,
            "config": protocol_spec,
            "environment": {
                "python": sys.version, "platform": platform.platform(), "machine": platform.machine(),
                "packages": {name: importlib.metadata.version(name) for name in ("duckdb", "pyarrow", "tiktoken")},
                "determinism": {"sampling": "hash-ranked sample only", "seed": "sha256(sample:id)"},
            },
            "inputs": [
                {"role": "official_upstream", "version_id": upstream_version},
                {"role": "access_mirror", "version_id": source_version},
                {"role": "target_base", "version_id": target_version},
            ],
            "outputs": [{"role": "dataset_source", "version_id": version_id}],
        },
        "relations": [
            {"source_version_id": version_id, "predicate": "DERIVED_FROM", "target_version_id": source_version, "introduced_by_run": run_id},
            {"source_version_id": source_version, "predicate": "MIRRORS", "target_version_id": upstream_version, "introduced_by_run": run_id},
            {"source_version_id": version_id, "predicate": "FILTERED_BY", "target_version_id": protocol_version_id, "introduced_by_run": run_id},
            {"source_version_id": version_id, "predicate": "COMPATIBLE_WITH", "target_version_id": target_version, "introduced_by_run": run_id},
        ],
        "evidence": evidence_items,
        "claims": claims,
        "claim_evidence": claim_links,
        "actors": [
            {"id": "hf:PiotrSty", "kind": "human", "identity": "Piotr Styła", "identifiers": {"hugging_face": "PiotrSty", "github": "PiotrStyla"}},
            {"id": "org:mozilla-data-collective", "kind": "organization", "identity": "Mozilla Data Collective", "identifiers": {"dataset_id": UPSTREAM_DATASET_ID}},
            {"id": "agent:codex", "kind": "agent", "identity": "OpenAI Codex", "identifiers": {}},
        ],
        "attestations": [
            attestation("schema_valid", True, [by_type["schema_validation"], by_type["artifact_checksums"]]),
            attestation("license_status", "documented_cc0_1_0", [by_type["license_metadata"]]),
            attestation("cross_source_deduplication", "pending_target_integration", [by_type["target_registry_check"]]),
        ],
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    if not COMMIT_PATTERN.fullmatch(args.target_revision):
        raise BuildError("target revision must be a 40-character commit")
    if not COMMIT_PATTERN.fullmatch(args.payload_revision):
        raise BuildError("payload revision must be a 40-character commit")
    if not args.target_registry.is_file():
        raise BuildError("target sources.py is missing")
    registry = args.target_registry.read_text(encoding="utf-8")
    if re.search(rf'^\s{{4}}["\']{SOURCE_NAME}["\']\s*:', registry, re.MULTILINE):
        raise BuildError(f"{SOURCE_NAME} already exists in the pinned target registry")

    import pyarrow as pa
    import pyarrow.parquet as pq
    import tiktoken

    source = source_rows()
    retained, diagnostics = aggregate(source)
    encoder = tiktoken.get_encoding("cl100k_base")
    schema = pa.schema([
        ("id", pa.string()), ("text", pa.string()), ("source", pa.string()),
        ("added", pa.string()), ("created", pa.string()), ("token_count", pa.int64()),
        ("license", pa.string()), ("author", pa.string()),
    ])
    rows: list[dict[str, Any]] = []
    sidecars: list[dict[str, Any]] = []
    domains: collections.Counter[str] = collections.Counter()
    for item in retained:
        identifier = stable_id(item["key"])
        token_count = len(encoder.encode_ordinary(item["text"]))
        rows.append({
            "id": identifier, "text": item["text"], "source": SOURCE_NAME,
            "added": args.added_date, "created": UPSTREAM_RELEASE_DATE,
            "token_count": token_count, "license": SOURCE_LICENSE, "author": AUTHOR,
        })
        domain = item["sentence_domain"] or "unspecified"
        domains[domain] += 1
        sidecars.append({
            "id": identifier, "sentence_id": item["sentence_id"],
            "sentence_id_count": item["sentence_id_count"], "clip_count": item["clip_count"],
            "total_duration_ms": item["duration_ms"], "up_votes": item["up_votes"],
            "down_votes": item["down_votes"], "sentence_domain": domain,
            "source_dataset_id": UPSTREAM_DATASET_ID, "upstream_version": UPSTREAM_VERSION,
            "mirror_repository": MIRROR_REPOSITORY, "mirror_revision": MIRROR_REVISION,
            "license": SOURCE_LICENSE,
        })

    if not rows:
        raise BuildError("all source rows were filtered")
    stats = {
        **diagnostics,
        "kept": len(rows), "chars": sum(len(row["text"]) for row in rows),
        "whitespace_words": sum(len(row["text"].split()) for row in rows),
        "tokens": sum(row["token_count"] for row in rows),
        "source": SOURCE_NAME, "license": SOURCE_LICENSE,
        "licenses": {SOURCE_LICENSE: len(rows)}, "authors_with_value": len(rows),
        "added": args.added_date, "created_min": UPSTREAM_RELEASE_DATE,
        "created_max": UPSTREAM_RELEASE_DATE, "by_sentence_domain": dict(sorted(domains.items())),
        "source_repository": MIRROR_REPOSITORY, "source_revision": MIRROR_REVISION,
        "source_parquet_path": SOURCE_PARQUET_PATH,
        "source_parquet_sha256": SOURCE_PARQUET_SHA256,
        "source_parquet_size": SOURCE_PARQUET_SIZE,
        "upstream_dataset_id": UPSTREAM_DATASET_ID, "upstream_version": UPSTREAM_VERSION,
        "target_base_revision": args.target_revision,
        "cross_source_exact_dedup_completed": False,
        "cross_source_near_dedup_completed": False,
        "stats_recomputed_from_output_rows": True,
    }
    run_at = args.run_at
    run_id = f"common-voice-pl-v26-{run_at.replace(':', '').replace('-', '')}"
    script_path = pathlib.Path(__file__).resolve()
    script_sha256 = sha256_file(script_path)

    hf_root = args.output / "hf_repo"
    pr_root = args.output / "dynaword_pr"
    for directory in (hf_root / "data", hf_root / "artifacts", hf_root / "src", pr_root / "data" / SOURCE_NAME, pr_root / "artifacts", pr_root / "src"):
        directory.mkdir(parents=True, exist_ok=True)

    hf_parquet = hf_root / "data" / "train-00000-of-00001.parquet"
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), hf_parquet, compression="zstd", row_group_size=4096)
    pr_parquet = pr_root / "data" / SOURCE_NAME / f"{SOURCE_NAME}.parquet"
    shutil.copy2(hf_parquet, pr_parquet)

    sidecar_text = "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in sidecars)
    sample_rows = sorted(rows, key=lambda row: hashlib.sha256(("sample:" + row["id"]).encode()).hexdigest())[:20]
    sample_text = "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in sample_rows)
    for root, data_dir in ((hf_root, hf_root / "data"), (pr_root, pr_root / "data" / SOURCE_NAME)):
        (data_dir / f"{SOURCE_NAME}.attribution.jsonl").write_text(sidecar_text, encoding="utf-8")
        (data_dir / f"{SOURCE_NAME}.sample.jsonl").write_text(sample_text, encoding="utf-8")
        write_json(data_dir / f"{SOURCE_NAME}.stats.json", stats)
        write_json(data_dir / f"{SOURCE_NAME}.license-evidence.json", {
            "status": "documented-open-cc0",
            "license": SOURCE_LICENSE,
            "official_dataset": UPSTREAM_URL,
            "official_dataset_id": UPSTREAM_DATASET_ID,
            "upstream_release": UPSTREAM_VERSION,
            "upstream_release_date": UPSTREAM_RELEASE_DATE,
            "pinned_access_mirror": f"hf://datasets/{MIRROR_REPOSITORY}@{MIRROR_REVISION}/{SOURCE_PARQUET_PATH}",
            "source_parquet_sha256": SOURCE_PARQUET_SHA256,
            "source_parquet_size": SOURCE_PARQUET_SIZE,
            "spdx": "https://spdx.org/licenses/CC0-1.0.html",
            "creative_commons": "https://creativecommons.org/publicdomain/zero/1.0/",
            "finding": "The official dataset page and pinned mirror identify the release as CC0-1.0.",
            "review_scope": "dataset-level license metadata; not independent legal advice",
        })
        (data_dir / f"{SOURCE_NAME}.md").write_text(datasheet(stats), encoding="utf-8")
        (data_dir / "NOTICE.md").write_text(
            "# Attribution and provenance\n\nSource: Mozilla Data Collective, Common Voice "
            f"Scripted Speech {UPSTREAM_VERSION} - Polish (`{UPSTREAM_DATASET_ID}`). "
            f"License: `{SOURCE_LICENSE}`. Text-only preparation: Piotr Styla.\n",
            encoding="utf-8",
        )

    artifact_digests = {
        "parquet_sha256": sha256_file(pr_parquet),
        "attribution_sha256": sha256_file(pr_root / "data" / SOURCE_NAME / f"{SOURCE_NAME}.attribution.jsonl"),
        "stats_sha256": sha256_file(pr_root / "data" / SOURCE_NAME / f"{SOURCE_NAME}.stats.json"),
        "license_evidence_sha256": sha256_file(pr_root / "data" / SOURCE_NAME / f"{SOURCE_NAME}.license-evidence.json"),
        "sample_sha256": sha256_file(pr_root / "data" / SOURCE_NAME / f"{SOURCE_NAME}.sample.jsonl"),
    }
    language_audit = None
    if args.language_audit:
        language_audit = json.loads(args.language_audit.read_text(encoding="utf-8"))
        for root in (hf_root, pr_root):
            shutil.copy2(args.language_audit, root / "artifacts" / f"{SOURCE_NAME}_language_audit.json")
        artifact_digests["language_audit_sha256"] = sha256_file(args.language_audit)
    manifest = build_manifest(
        stats, artifact_digests, args.payload_revision, args.target_revision,
        run_id, run_at, script_sha256, language_audit,
    )
    for root in (hf_root, pr_root):
        write_json(root / "artifacts" / f"{SOURCE_NAME}_ontology_manifest.json", manifest)
        shutil.copy2(script_path, root / "src" / "fetch_common_voice_pl.py")
    (hf_root / "README.md").write_text(dataset_card(stats, args.payload_revision), encoding="utf-8")
    (pr_root / "src" / "sources.py").write_text(update_registry(registry), encoding="utf-8")
    (pr_root / "src" / "test_common_voice_pl_contract.py").write_text(contract_test(), encoding="utf-8")
    write_json(args.output / "build_summary.json", {"stats": stats, "artifact_digests": artifact_digests, "payload_revision": args.payload_revision})
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-registry", type=pathlib.Path, required=True)
    parser.add_argument("--target-revision", required=True)
    parser.add_argument("--payload-revision", required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--language-audit", type=pathlib.Path)
    parser.add_argument("--added-date", default="2026-09-05")
    parser.add_argument("--run-at", default="2026-09-05T12:00:00Z")
    args = parser.parse_args()
    stats = build(args)
    print(json.dumps(stats, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
