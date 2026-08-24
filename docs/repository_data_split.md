# Repository / Hugging Face split

This project uses GitHub for research tooling and Hugging Face for dataset
artifacts.

## GitHub

GitHub should contain:

- source-ingestion scripts,
- validation and review tooling,
- protocol definitions,
- small templates,
- documentation,
- run summaries,
- source datasheets,
- legal/provenance notes,
- schema definitions,
- small synthetic or hand-written fixtures,
- CI and reproducibility checks.

GitHub should not contain raw crawled corpora, PDFs, Word files, parquet shards,
large JSONL/CSV outputs, checkpoints, model weights, tokens, credentials or
private review notes.

## Hugging Face

Hugging Face should contain dataset artifacts:

- raw or normalized source payload snapshots when legally appropriate,
- manifest JSONL/CSV files for published dataset versions,
- parquet/arrow shards,
- extracted text corpora,
- source-level validation artifacts,
- review-approved binary samples when needed,
- dataset cards,
- per-source datasheets,
- release notes and changelogs.

Current relevant HF context checked on 2026-08-24:

- authenticated user: `PiotrSty`
- organization available: `SlayerLab`
- dataset: `SlayerLab/polish-dynaword`
- stable card metadata: `v0.2.5`, 4,319,200 documents, 9.64B tokens,
  18 sources, `cc-by-sa-4.0`

The local HF tool session currently has read-oriented scopes. Uploading or
updating datasets will require a write-capable Hugging Face token/session.

## Slayer ontology mapping

For this split:

- GitHub stores `Protocol`, tool code, schemas, documentation and claim/evidence
  summaries.
- Hugging Face stores published `Object`/`Version` payloads for datasets and
  source artifacts.
- Run outputs should be summarized in GitHub only when they are small and safe.
  The complete data payload belongs on Hugging Face.
- Every dataset release should have stable provenance: source, digest,
  transform protocol, validation evidence and legal/PII status.

## RCL current state

The current RCL work should be kept as:

- GitHub: `scripts/`, `docs/`, `README.md`, `.gitignore`, future schemas and
  source datasheets.
- Hugging Face: `data/rcl_inventory/`, `data/rcl_2026_consultations/`, raw HTML,
  document manifests, downloaded PDFs/documents, extracted text and release
  shards.
