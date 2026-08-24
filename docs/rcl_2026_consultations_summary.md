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

## Next Tasks

- Complete manual review of the 40 pilot rows in
  `data/rcl_gold_pilot_v0_1/annotations.csv`.
- Re-run `scripts/rcl_validate_gold_pilot.py` after annotation.
- Summarize annotation evidence and formulate only claims supported by the
  reviewed sample.
- Add checkpoint/resume writes to `scripts/rcl_downloader.py` before larger
  source batches.
- Normalize document file extensions and preserve original filenames for later
  extraction runs.
