# RCL Gold Set v0.1 - annotation protocol

## Purpose

This protocol creates review evidence for a bounded sample of RCL public-
consultation documents. The pilot does not approve documents for training by
default. It records observations needed for later legal, PII, extraction and
training-mix decisions.

## Pilot selection

- Input: `data/rcl_2026_consultations/review_queue.csv`
- Selection: `priority = 1`
- Maximum size: 40 documents
- Ordering: ascending deterministic `queue_id`
- Source: public document URLs listed by `legislacja.gov.pl`

## Review fields

Use the following controlled values where applicable:

- `manual_doc_type`: `organization_comment`, `individual_comment`,
  `government_response`, `cover_letter`, `draft_law`, `attachment`, `other`
- `manual_source_type`: `ngo`, `trade_union`, `employer_organization`,
  `professional_body`, `company`, `religious_organization`, `public_body`,
  `individual`, `unknown`, `other`
- `contains_pii`: `yes`, `no`, `uncertain`
- `pii_types`: semicolon-separated values such as `email`, `phone`, `address`,
  `signature`, `personal_identifier`, `person_name`
- `legal_status`: `review_needed`, `eligible`, `exclude`, `uncertain`
- `extraction_quality`: `good`, `usable`, `poor`, `not_extractable`
- `train_recommendation`: `include`, `exclude`, `conditional`, `undecided`

`legal_basis` is a short evidence note, not a blanket license assignment. Record
the source page, relevant public-information basis or applicable rights notice.
Use `exclusion_reason` whenever `legal_status=exclude` or
`train_recommendation=exclude`.

## Review procedure

1. Confirm that the downloaded artifact matches the listed title and source URL.
2. Identify the document and source types from the document contents.
3. Record PII observations. A public source does not make PII irrelevant.
4. Record the legal/provenance evidence available for this specific document.
5. Assess whether clean text can be extracted without material loss.
6. Make a training recommendation separately from the legal observation.
7. Enter reviewer identity, UTC review time and a concise note.

## Machine triage

`scripts/rcl_extract_pilot_text.py` may create local extracted text,
`extraction_manifest.jsonl` and `machine_observations.csv`. Treat these as
triage evidence only:

- Machine hints do not overwrite `manual_*`, `contains_pii`, `legal_status`,
  `extraction_quality` or `train_recommendation`.
- Do not copy text snippets into publishable metadata before legal/PII review.
- Empty text usually means OCR or manual inspection is needed, not that the
  document has no content.
- PII hints are recall-oriented and may include false positives; reviewers must
  confirm them before claims or release decisions.

`calibration_queue.csv` is the recommended first manual pass. It mixes empty
extractions, clean text baselines and PII-triage examples so reviewers can align
on the protocol before annotating all 40 rows.

## Ontology mapping

- The source file is an `Object` with a content-addressed `Version`.
- This document is the `Protocol`; `scripts/rcl_gold_pilot.py` implements its
  download and registration stage.
- Each execution is a `Run` with pinned selection parameters.
- Completed annotation rows are `Evidence` produced by an identified `Actor`.
- Extracted text is a local `Object`/`Version` with a `DERIVED_FROM` relation to
  the source file. Machine observations are evidence for triage, not final
  claims.
- Aggregate interpretations are later `Claim` objects; the pilot creates none
  before review.

## Publication rule

Before legal and PII review, publish only metadata, manifests, checksums, run
summaries, machine-observations without text snippets and the annotation
template. Keep downloaded binaries and extracted text local. A later version may
include only artifacts whose evidence supports that release.
