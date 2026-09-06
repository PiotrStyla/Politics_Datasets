# Edukacja Medialna candidate v0.1

Checked: 2026-09-06. This scouting snapshot led to a completed publication.
For the final result and updated limitations, see
`docs/edukacja_medialna_dynaword_pr.md` and DynaWord PR #26. This file preserves
the pre-ingestion candidate assessment.

## Observed evidence

- Official source: https://edukacjamedialna.edu.pl/lekcje/
- About/licensing: https://edukacjamedialna.edu.pl/info/o-nas/
- The official about page describes more than 235 lessons. A live HTTP 200
  listing returned 255 distinct hrefs matching `/lekcje/<slug>/`. This is a
  discovered-link count, not a validated document or retained-record count.
- The about page states default CC BY-SA 3.0, except where marked otherwise.
- Two inspected lesson pages explicitly name CC BY-SA 3.0 and identify
  authors of the explanatory text and lesson scenario separately:
  https://edukacjamedialna.edu.pl/lekcje/wolne-licencje/
  https://edukacjamedialna.edu.pl/lekcje/jak-rozrozniac-informacje-prawdziwe-od-falszywych/
- The first lesson's source XML returned HTTP 200 and parsed successfully
  with root `utwor` (15,596 decoded characters, not training-text size):
  https://edukacjamedialna.edu.pl/media/catalogue/lesson/xml/wolne-licencje.xml
- Sample XML contains Dublin Core title, canonical URL, publisher,
  creator.textbook, creator.scenario, creator.expert, audience and date.
  Its date value is 2012-11-09; this is source metadata, not a verified
  timestamp for all current text revisions.
- License reference: https://creativecommons.org/licenses/by-sa/3.0/

## DynaWord presence check

Target: SlayerLab/polish-dynaword, main revision
`a916edecabc2be8832e08fb2bd9dfafcc1d2dd71`.

- Inspected the live repository file inventory; no dedicated source folder.
- Searched `src/sources.py`, `configs/source_candidates_v0_3.json`,
  `artifacts/source_findings.md`, and `artifacts/source_scouting_v0_3.md`
  at that immutable revision for edukacjamedialna / edukacja.medialna.
  No matching mentions were returned.
- The public discussion API returned all 25 discussions (start 0, count 25).
  No title identified this source. Discussion bodies and all PR diffs were
  not exhaustively searched for incidental references.
- This supports absence as an explicitly registered/contributed source;
  it does NOT establish that the texts are absent from HPLT or other web
  collections. Full cross-source text deduplication remains pending.
- Main README describes v0.2.5 stable separately from development and previews;
  stable-release metadata alone was not used to establish source absence.

## Candidate claim and limits

Hypothesis: authored Polish media-literacy explanations and scenarios can
diversify the corpus beyond legal and parliamentary prose. Training benefit
is untested. No token estimate is claimed before extraction and counting.

Prefer source XML to PDF/OCR. A text-only pilot should preserve section roles,
authors and source dates, exclude navigation/contact boilerplate and external
reading-list contents, and avoid treating unlabelled true/false options as
standalone factual prose. Shared glossary sections require deduplication.
Old technology/legal guidance needs age flags, not an assertion of currency.

## Gates before publication

1. Inventory and validate every lesson and its own license/rights exceptions.
2. Save raw payloads and license evidence with SHA-256 digests and retrieval times.
3. Register source/derived Versions, extraction Protocol and executed Run;
   link typed lineage and keep observations separate from benefit Claims.
4. Preserve attribution, original CC BY-SA version and transformation notices;
   review third-party excerpts and separately licensed attachments.
5. Validate XML extraction, Polish language, PII handling, deduplication and
   benchmark overlap; do not mark unexecuted checks as passed.
6. Produce actual tokenizer-pinned counts and full deterministic samples.
7. Publish on PiotrSty HF and submit a separate DynaWord PR only after approval
   to proceed with ingestion and after reporting unresolved review gates.

This is a scouting note, not a complete content-addressed ontology manifest.
