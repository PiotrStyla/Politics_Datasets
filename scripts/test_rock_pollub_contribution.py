import ast
import json
from pathlib import Path

import pyarrow.parquet as pq


ROOT = Path(__file__).parents[1]
SOURCE = "rock_pollub_pl"
DATA = ROOT / "data" / SOURCE


def lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_registry_and_dataset_contract():
    module = ast.parse((ROOT / "src/sources.py").read_text(encoding="utf-8"))
    node = next(item.value for item in module.body if isinstance(item, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "SOURCES" for target in item.targets))
    entry = ast.literal_eval(node)[SOURCE]
    assert entry["file_key"] == SOURCE
    assert entry["license_spdx"] == "CC-BY-SA-4.0"
    table = pq.read_table(DATA / f"{SOURCE}.parquet")
    assert table.column_names == ["id", "text", "source", "added", "created", "token_count", "license", "author"]
    rows = table.to_pylist()
    stats = json.loads((DATA / f"{SOURCE}.stats.json").read_text(encoding="utf-8"))
    assert len(rows) == stats["kept"] == 8
    assert sum(row["token_count"] for row in rows) == stats["tokens"] == 1177858
    assert all(row["source"] == SOURCE and row["license"] == "CC-BY-SA-4.0" and row["author"] for row in rows)


def test_attribution_samples_and_ontology():
    rows = pq.read_table(DATA / f"{SOURCE}.parquet").to_pylist()
    attribution = lines(DATA / f"{SOURCE}.attribution.jsonl")
    samples = lines(DATA / f"{SOURCE}.sample.jsonl")
    assert {row["id"] for row in rows} == {item["id"] for item in attribution}
    assert all(item["license_evidence"]["item"] and item["license_evidence"]["pdf_bitstream"] for item in attribution)
    assert {row["id"] for row in samples} == {row["id"] for row in rows}
    manifest = json.loads((ROOT / f"artifacts/{SOURCE}_ontology_manifest.json").read_text(encoding="utf-8"))
    evidence = {item["id"] for item in manifest["evidence"]}
    assert all(set(item["supported_by"]) <= evidence and item["falsification_condition"] for item in manifest["claims"])
    assert any(item["predicate"] == "VALIDATED_AGAINST" for item in manifest["relations"])
