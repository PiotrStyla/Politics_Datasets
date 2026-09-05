"""Run from the prepared DynaWord contribution tree."""
import json
from pathlib import Path
import pyarrow.parquet as pq
import pytest
from build_open_agh_pl import SOURCE, LICENSE, FIELDS, BOOK_IDS, sha

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / SOURCE
MANIFEST = ROOT / f'artifacts/{SOURCE}_ontology_manifest.json'
pytestmark = pytest.mark.skipif(not MANIFEST.exists(), reason='Requires prepared DynaWord contribution')


def test_data_and_source_contract():
    table = pq.read_table(DATA / f'{SOURCE}.parquet')
    rows = table.to_pylist()
    stats = json.loads((DATA / f'{SOURCE}.stats.json').read_text(encoding='utf-8'))
    sidecars = [json.loads(s) for s in (DATA / f'{SOURCE}.attribution.jsonl').read_text(encoding='utf-8').splitlines()]
    assert table.column_names == FIELDS and len(rows) == stats['kept']
    assert sum(r['token_count'] for r in rows) == stats['tokens']
    assert {r['id'] for r in rows} == {s['id'] for s in sidecars}
    assert len({r['id'] for r in rows}) == len(rows)
    assert {r['source'] for r in rows} == {SOURCE}
    assert {r['license'] for r in rows} == {LICENSE}
    assert {m['book_id'] for s in sidecars for m in s['memberships']} == set(BOOK_IDS)
    sample = [json.loads(s) for s in (DATA / f'{SOURCE}.sample.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(sample) == stats['sample_count']
    by_id = {r['id']: r for r in rows}
    assert all(by_id[s['id']] == s for s in sample)
    for book in BOOK_IDS:
        ids = {s['id'] for s in sidecars if any(m['book_id'] == book for m in s['memberships'])}
        assert len(ids & {s['id'] for s in sample}) >= 3


def test_ontology_content_addresses_and_lineage():
    m = json.loads(MANIFEST.read_text(encoding='utf-8'))
    sums = next(e['payload'] for e in m['evidence'] if e['observation_type'] == 'checksums')
    assert m['version']['digest'] == 'sha256:' + sha(sums)
    assert m['protocol']['version']['digest'] == 'sha256:' + sha(m['protocol']['specification'])
    assert m['source_version']['digest'] == 'sha256:' + sha(m['source_version']['components'])
    assert '@0000000000000000000000000000000000000000/' not in m['version']['payload_uri']
    mapping = {'data/train-00000-of-00001.parquet': DATA / f'{SOURCE}.parquet'}
    for name in ('attribution.jsonl', 'decisions.jsonl', 'sample.jsonl', 'books.json', 'stats.json', 'qa.json'):
        mapping['artifacts/' + name] = DATA / f'{SOURCE}.{name}'
    for name, path in mapping.items():
        assert sha(path.read_bytes()) == sums[name]
    assert m['validation_run']['success']
    assert m['validation_run']['code_sha256'] == sums['src/publish_open_agh_pl.py']
    assert m['run']['code_sha256'] == sums['src/build_open_agh_pl.py']
    assert next(r['introduced_by_run'] for r in m['relations'] if r['predicate'] == 'VALIDATED_AGAINST') == m['validation_run']['id']
    evidence = {e['id'] for e in m['evidence']}
    assert all(set(c['supported_by']) <= evidence and c['falsification_condition'] for c in m['claims'])
    graph = {}
    for r in m['relations']:
        graph.setdefault(r['source_version_id'], []).append(r['target_version_id'])
    def visit(node, path):
        assert node not in path
        for child in graph.get(node, []):
            visit(child, path | {node})
    for node in graph:
        visit(node, set())
