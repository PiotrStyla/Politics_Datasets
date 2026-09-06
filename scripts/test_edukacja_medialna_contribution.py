"""Contract checks run from the prepared DynaWord contribution tree."""
import json
from pathlib import Path
import re

import pyarrow.parquet as pq

SOURCE = "edukacja_medialna_pl"
LICENSE = "CC-BY-SA-3.0"
FIELDS = ["id", "text", "source", "added", "created", "token_count", "license", "author"]
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / SOURCE
MANIFEST = ROOT / "artifacts" / f"{SOURCE}_ontology_manifest.json"


def digest(payload):
    import hashlib
    if isinstance(payload, bytes):
        return hashlib.sha256(payload).hexdigest()
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


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
    assert sum(item["token_count"] for item in data) == stats["tokens"]
    assert sum(bool(item["selected"]) for item in decisions) == stats["kept"]
    assert len(decisions) == stats["discovered"]
    assert {item["id"] for item in data} == {item["id"] for item in attribution}
    assert all(item["source"] == SOURCE and item["license"] == LICENSE and item["author"] for item in data)
    assert all(not re.search(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", item["text"]) for item in data)
    by_id = {item["id"]: item for item in data}
    assert len(sample) == stats["sample_count"] == 12
    assert all(by_id[item["id"]] == item for item in sample)


def test_ontology_is_addressed_and_falsifiable():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    evidence = {item["id"]: item for item in manifest["evidence"]}
    checks = next(item["payload"] for item in manifest["evidence"] if item["observation_type"] == "checksums")
    for name, expected in checks.items():
        mapping = {
            "data/train-00000-of-00001.parquet": DATA / f"{SOURCE}.parquet",
            "artifacts/attribution.jsonl": DATA / f"{SOURCE}.attribution.jsonl",
            "artifacts/decisions.jsonl": DATA / f"{SOURCE}.decisions.jsonl",
            "artifacts/sample.jsonl": DATA / f"{SOURCE}.sample.jsonl",
            "artifacts/stats.json": DATA / f"{SOURCE}.stats.json",
            "artifacts/qa.json": DATA / f"{SOURCE}.qa.json",
            "src/build_edukacja_medialna_pl.py": ROOT / "src/build_edukacja_medialna_pl.py",
            "src/test_edukacja_medialna_contribution.py": ROOT / "src/test_edukacja_medialna_contribution.py",
        }
        if name in mapping:
            assert digest(mapping[name].read_bytes()) == expected
    assert all(item["falsification_condition"] for item in manifest["claims"])
    assert all(set(item["supported_by"]) <= set(evidence) for item in manifest["claims"])
    assert any(item["predicate"] == "VALIDATED_AGAINST" for item in manifest["relations"])
    assert len(manifest["runs"]) >= 2 and all(item["success"] for item in manifest["runs"])
    graph = {}
    for relation in manifest["relations"]:
        graph.setdefault(relation["source"], []).append(relation["target"])
    def visit(node, path):
        assert node not in path
        for child in graph.get(node, []):
            visit(child, path | {node})
    for node in graph:
        visit(node, set())
