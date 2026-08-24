# RCL 2026 consultations - run summary

Date: 2026-08-24

## Artifacts

- Full project inventory: `data/rcl_inventory/`
- 2026 consultation metadata batch: `data/rcl_2026_consultations/`
- Manual-review queue: `data/rcl_2026_consultations/review_queue.csv`
- Run manifest: `data/rcl_2026_consultations/runs/rcl_run_20260824T060410.834641z0000.json`

## Protocol

The 2026 batch used `scripts/rcl_downloader.py` with:

```powershell
--max-pages 0 --max-projects 150 --no-download --save-html --output-dir data\rcl_2026_consultations
```

This means it crawled the 150 newest RCL law-project entries, corresponding to
the 2026 slice in the current list ordering, entered project pages and
consultation catalogs, saved raw HTML and metadata, but did not download
document binaries.

## Evidence

- Projects in full inventory: 2606
- Projects in 2026 consultation batch: 150
- Projects with consultation catalog URL: 127
- Documents found in consultation catalogs: 1672
- Documents selected by current keyword filter: 1000
- Downloaded documents in this run: 0
- Run errors: 0

## Document Categories

- 927 - `Stanowiska zgłoszone w ramach konsultacji publicznych`
- 513 - `Projekt`
- 180 - `Pisma kierujące projekt do konsultacji publicznych`
- 35 - `Odniesienie się wnioskodawcy do uwag`
- 17 - `Odrębna konferencja z udziałem podmiotów publicznych`

## File Extensions

- 871 - `.pdf`
- 356 - `.docx`
- 248 - missing or non-standard suffix
- 53 - `.docm`
- 33 - `.doc`
- 16 - `.xades`
- 9 - `.zip`
- 8 - `.msg`
- 7 - `.xlsx`
- 4 - `.jpg`
- 2 - `.odt`

Some apparent suffixes include descriptive text such as
`.pdf - odniesienie do uwag`; filename normalization needs a dedicated pass
before binary download and text extraction.

## Manual Review Queue

`scripts/rcl_review_queue.py` generated 82 priority rows:

- 40 priority-1 rows from `Stanowiska zgłoszone w ramach konsultacji publicznych`
- 40 priority-2 rows mostly from `Odniesienie się wnioskodawcy do uwag`
- 2 priority-4 rows from lower-priority selected categories

The queue contains empty fields for:

- manual document type,
- manual source type,
- PII risk,
- legal/provenance status,
- training-candidate decision,
- exclusion reason,
- reviewer,
- review notes.

## Initial Claim Candidates

These are not final claims yet; they are candidate claims that need review
evidence.

- RCL 2026 consultation catalogs contain substantial organization/public-comment
  material, not only government project files.
- The current keyword filter is useful but too broad: it selects all
  `Stanowiska...` and `Odniesienie...`, but also a small number of project/pismo
  files via filename/category matches.
- RCL consultation data should enter the Polish Dynaword pipeline through
  source-level legal/provenance review and PII screening before any training-mix
  decision.
- Older years may contain more mature consultation responses than the newest
  open projects, so 2025 is a strong next metadata batch candidate.

## Gold Review Pilot v0.1

Completed on 2026-08-24 with `scripts/rcl_gold_pilot.py`:

- Selection: 40 deterministic `priority=1` queue rows.
- Downloads: 40 successful, 0 failures.
- Formats: 34 PDF and 6 DOCX.
- Total local payload: 16,391,096 bytes.
- Uniqueness: 40 source URLs and 40 SHA-256 digests.
- Manifest SHA-256:
  `38f3fde085c3ce8ba79af68e4205f9118f314be2447e4b50936d4403e82b00d4`.
- Validation: pass, with the expected warning that 0 manual reviews are
  complete.
- HF commit:
  `9baef9826ba68c73493fd1d31a8c2d784e13828f`.
- HF immutable tag: `v0.1.0-metadata`.

The HF artifact contains the manifest, checksums, annotation table, protocol,
run evidence and validation report. Raw PDF/DOCX binaries remain local until
document-level legal and PII review.

## Text Extraction Pilot v0.1

Completed on 2026-08-24 with `scripts/rcl_extract_pilot_text.py`:

- Input: the 40-document `data/rcl_gold_pilot_v0_1/source_manifest.jsonl`.
- Local text outputs: `data/rcl_gold_pilot_v0_1/extracted_text/`.
- Text extraction rows: 40.
- Status: 38 extracted, 2 empty-text extractions.
- Text payload: 901,490 bytes of local UTF-8 text.
- Machine extraction-quality hints: 33 good, 3 usable, 2 poor, 2 not
  extractable.
- Machine PII hints: 34 yes, 6 uncertain.
- Machine document-type hints after category-first correction: 40
  organization_comment.
- Extraction manifest SHA-256:
  `c9c3b7de41436b61e104b34653b7732d20e8865c28449337a8aeb22bf958627d`.
- Validation: pass, with expected warnings that empty/low-quality extraction
  and PII hints require manual review.

The extraction stage creates evidence for triage only. It does not update the
manual annotation fields and does not create training-eligibility claims.
Extracted text remains local until legal and PII review.

## Calibration Queue v0.1

`scripts/rcl_make_calibration_queue.py` created
`data/rcl_gold_pilot_v0_1/calibration_queue.csv` with 10 rows:

- 2 `ocr_or_scan_review` rows for empty-text PDFs.
- 4 `clean_text_baseline` rows with good extraction and no machine PII hit.
- 4 `pii_triage_baseline` rows with good extraction and machine PII hints.

Use this queue to calibrate reviewer interpretation before annotating all 40
pilot rows.

## Review Pack v0.1

`scripts/rcl_build_review_pack.py` created a local-only review pack:

- HTML index:
  `data/rcl_gold_pilot_v0_1/review_pack/index.html`.
- Editable review sheet:
  `data/rcl_gold_pilot_v0_1/review_pack/calibration_review_sheet.csv`.
- Protocol copy:
  `data/rcl_gold_pilot_v0_1/review_pack/annotation_protocol.md`.
- Rows: 10.

The review pack links local raw documents and local extracted text. It should
not be published before legal and PII review.

## Draft Calibration Review v0.1

`scripts/rcl_draft_calibration_review.py` created conservative draft
suggestions:

- Suggestions CSV:
  `data/rcl_gold_pilot_v0_1/review_pack/calibration_review_suggestions.csv`.
- Suggestions summary:
  `data/rcl_gold_pilot_v0_1/review_pack/calibration_review_suggestions.md`.
- Rows: 10.
- Draft document types: 8 `organization_comment`, 2 `government_response`.
- Draft source types: 3 `ngo`, 2 `employer_organization`, 2 `public_body`,
  2 `religious_organization`, 1 `professional_body`.
- Draft PII status: 4 `yes`, 6 `uncertain`.
- Draft extraction quality: 8 `good`, 2 `not_extractable`.
- Draft training recommendation: 8 `conditional`, 2 `exclude`.
- Legal status: all 10 remain `review_needed`.

These rows are not final human annotations and do not create legal/training
claims. They are a starting point for reviewer calibration.

## Calibration Apply Gate v0.1

`scripts/rcl_apply_calibration_review.py` was added as the controlled path from
review-pack decisions into `annotations.csv`.

Current dry-run result on 2026-08-24:

- Source rows: 10.
- Accepted rows: 0.
- Applied rows: 0.
- Skipped rows: 10.
- Skip reason: all draft rows have
  `manual_review_status=needs_human_acceptance`.
- `annotations.csv` was not changed.

The script writes `review_pack/calibration_apply_report.json` and requires
`--commit` for any annotation-table update. It also requires accepted statuses
(`accepted`, `reviewed` or `approved`) and reviewer metadata before copying
fields into the main annotation table.

## Next Tasks

- Complete manual review of the 10 calibration rows in
  `data/rcl_gold_pilot_v0_1/review_pack/calibration_review_sheet.csv`, using
  `data/rcl_gold_pilot_v0_1/review_pack/index.html` as the navigation surface.
- Compare against
  `data/rcl_gold_pilot_v0_1/review_pack/calibration_review_suggestions.csv` and
  explicitly accept or edit each suggested value.
- After calibration, apply settled fields to
  `data/rcl_gold_pilot_v0_1/annotations.csv`.
- Use `scripts/rcl_apply_calibration_review.py --commit` only after accepted
  statuses and reviewer metadata are present.
- Re-run `scripts/rcl_validate_gold_pilot.py` after annotation.
- Re-run `scripts/rcl_validate_extraction.py` after any extraction changes.
- Summarize annotation evidence and formulate only claims supported by the
  reviewed sample.
- Add checkpoint/resume writes to `scripts/rcl_downloader.py` before larger
  source batches.
- Normalize document file extensions and preserve original filenames for later
  extraction runs.
