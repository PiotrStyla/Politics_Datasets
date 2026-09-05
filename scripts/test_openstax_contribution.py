"""Checks for the published DynaWord OpenStax contribution directory."""
import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / 'openstax_pl'
MANIFEST = ROOT / 'artifacts/openstax_pl_ontology_manifest.json'
pytestmark = pytest.mark.skipif(not MANIFEST.exists(), reason='Run from the prepared DynaWord contribution directory')


def canonical(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def test_records_and_sidecars():
    table = pq.read_table(DATA / 'openstax_pl.parquet')
    stats = json.loads((DATA / 'openstax_pl.stats.json').read_text(encoding='utf-8'))
    rows = table.to_pylist()
    assert table.column_names == ['id', 'text', 'source', 'added', 'created', 'token_count', 'license', 'author']
    assert len(rows) == stats['kept']
    assert sum(r['token_count'] for r in rows) == stats['tokens']
    assert len({r['id'] for r in rows}) == len(rows)
    assert {r['license'] for r in rows} == {'CC-BY-4.0'}
    attribution = [json.loads(line) for line in (DATA / 'openstax_pl.attribution.jsonl').read_text(encoding='utf-8').splitlines()]
    assert {r['id'] for r in rows} == {r['id'] for r in attribution}
    assert len({r['book'] for r in attribution}) == 8
    samples = [json.loads(line) for line in (DATA / 'openstax_pl.sample.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(samples) == 24
    by_id = {r['id']: r for r in rows}
    assert all(by_id[r['id']] == r for r in samples)


def test_ontology_hashes_links_and_dag():
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    assert manifest['ontology_version'] == 'slayer.ai/research-ontology/v0.1'
    evidence = {e['id']: e for e in manifest['evidence']}
    claims = {c['id']: c for c in manifest['claims']}
    checksums = next(e['payload'] for e in evidence.values() if e['observation_type'] == 'artifact_checksums')
    assert manifest['version']['digest'] == 'sha256:' + canonical(checksums)
    assert manifest['protocol']['version']['digest'] == 'sha256:' + canonical(manifest['protocol']['specification'])
    assert '@0000000000000000000000000000000000000000/' not in manifest['version']['payload_uri']
    mapping = {'data/train-00000-of-00001.parquet': DATA / 'openstax_pl.parquet'}
    for name in ('attribution.jsonl', 'sample.jsonl', 'stats.json', 'qa.json', 'rejections.jsonl', 'books.json'):
        mapping['artifacts/' + name] = DATA / ('openstax_pl.' + name)
    for key, path in mapping.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == checksums[key]
    for link in manifest['claim_evidence']:
        assert link['claim_id'] in claims and link['evidence_id'] in evidence
    graph = {}
    for relation in manifest['relations']:
        graph.setdefault(relation['source_version_id'], []).append(relation['target_version_id'])
    def visit(node, path):
        assert node not in path
        for child in graph.get(node, []):
            visit(child, path | {node})
    for node in graph:
        visit(node, set())
