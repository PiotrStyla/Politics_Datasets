"""Contract checks run from the prepared DynaWord contribution tree."""
import hashlib
import json
from pathlib import Path
import re

import pyarrow.parquet as pq

SOURCE = "kultura_bez_barier_pl"
LICENSE = "CC-BY-SA-3.0"
FIELDS = ["id", "text", "source", "added", "created", "token_count", "license", "author"]
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / SOURCE
MANIFEST = ROOT / "artifacts" / f"{SOURCE}_ontology_manifest.json"


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_dataset_contract_and_samples():
    table = pq.read_table(DATA / f"{SOURCE}.parquet")
    data = table.to_pylist()
    stats = json.loads((DATA / f"{SOURCE}.stats.json").read_text(encoding="utf-8"))
    attribution = rows(DATA / f"{SOURCE}.attribution.jsonl")
    decisions = rows(DATA / f"{SOURCE}.decisions.jsonl")
    sample = rows(DATA / f"{SOURCE}.sample.jsonl")
    assert table.column_names == FIELDS
    assert len(data) == stats["kept"] == len(attribution)
    assert len(decisions) == stats["discovered"]
    assert sum(bool(item["selected"]) for item in decisions) == stats["kept"]
    assert sum(item["token_count"] for item in data) == stats["tokens"]
    assert {item["id"] for item in data} == {item["id"] for item in attribution}
    assert all(item["source"] == SOURCE and item["license"] == LICENSE and item["author"] for item in data)
    assert all(not re.search(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", item["text"]) for item in data)
    by_id = {item["id"]: item for item in data}
    assert len(sample) == stats["sample_count"] == min(12, len(data))
    assert all(by_id[item["id"]] == item for item in sample)


def test_ontology_is_addressed_and_falsifiable():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    evidence = {item["id"] for item in manifest["evidence"]}
    assert all(item["falsification_condition"] for item in manifest["claims"])
    assert all(set(item["supported_by"]) <= evidence for item in manifest["claims"])
    assert len(manifest["runs"]) >= 2 and all(item["success"] for item in manifest["runs"])
    assert any(item["predicate"] == "VALIDATED_AGAINST" for item in manifest["relations"])
    checks = next(item["payload"] for item in manifest["evidence"] if item["observation_type"] == "checksums")
    mapping = {
        "data/train-00000-of-00001.parquet": DATA / f"{SOURCE}.parquet",
        "artifacts/attribution.jsonl": DATA / f"{SOURCE}.attribution.jsonl",
        "artifacts/decisions.jsonl": DATA / f"{SOURCE}.decisions.jsonl",
        "artifacts/sample.jsonl": DATA / f"{SOURCE}.sample.jsonl",
        "artifacts/stats.json": DATA / f"{SOURCE}.stats.json",
        "artifacts/qa.json": DATA / f"{SOURCE}.qa.json",
        "src/build_kultura_bez_barier_pl.py": ROOT / "src/build_kultura_bez_barier_pl.py",
        "src/test_kultura_bez_barier_contribution.py": ROOT / "src/test_kultura_bez_barier_contribution.py",
    }
    for name, path in mapping.items():
        assert digest(path.read_bytes()) == checks[name]
