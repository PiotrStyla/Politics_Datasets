# Open AGH candidate screening v0.1

Observed: 2026-09-05. Scope: candidate discovery only; no corpus ingestion or PR.

## Recommendation

Polish academic textbook prose from Open AGH. Start with four chemistry titles,
whose indexed official book cards identify CC BY-SA 4.0:

| Book | Official source |
| --- | --- |
| Chemia ogolna | https://epodreczniki.open.agh.edu.pl/handbook/29 |
| Podstawy chemii nieorganicznej - uklad okresowy | https://epodreczniki.open.agh.edu.pl/handbook/1394 |
| Podstawy chemii polimerow | https://epodreczniki.open.agh.edu.pl/handbook/37 |
| Korozja i ochrona przed korozja | https://epodreczniki.open.agh.edu.pl/handbook/1893 |

The titles in this ASCII screening note are transliterated; ingestion must
preserve the original Polish titles and author names.

Official general licensing policy:
https://www.cel.agh.edu.pl/otwarte-zasoby-podreczniki/

The cards expose authors, reviewers, ISBN, publication/update years and an
explicit license. The publisher describes the textbooks as peer-reviewed and
available online and for download. Preserve attribution and ShareAlike terms;
do not generalize this license to unrelated repository items or third-party media.

## Evidence and limits

Protocol: inspect official indexed book cards and publisher policy; query the
HF repository API, pinned registry, source file inventory and discussion titles;
search the findings/scouting/candidate documents for AGH-related references.
Actor: OpenAI Codex, requested by Piotr Styla.

Target version: SlayerLab/polish-dynaword at
`a916edecabc2be8832e08fb2bd9dfafcc1d2dd71`.

Evidence: no dedicated AGH source in src/sources.py, no AGH-named data/importer
artifact in the main file list, no AGH proposal among 23 discussion titles.
No match in source_scouting_v0_3.md or source_candidates_v0_3.json; a match for
epodreczniki.pl in source_findings.md concerns the separate Ministry platform.
This was not a text-level scan of the training Parquet files or every PR body.

Official reader example:
https://epodreczniki.open.agh.edu.pl/handbook/29/module/568/reader

Direct requests to the catalog succeed but return a JavaScript application
shell. Book-card text was available through indexed official search results.
Live rendered/API extraction, downloadable format checks and archived per-book
license evidence are still necessary before treating the corpus as release-ready.

Claim: this is a promising separately attributable source, not currently
identified as its own DynaWord contribution in the checked surfaces.
Falsification: an AGH source entry, contributed artifact or matching proposal
exists in those pinned surfaces. This claim does not assert textual novelty.

Research hypothesis: chemistry/materials prose adds useful domain coverage to
our eight-volume OpenStax contribution. Training benefit is untested.

## Gates before publication

- Confirm and archive each current book/module license and attribution.
- Inventory only Polish original editions; do not ingest translations by default.
- Extract prose while preserving equations; audit tables and omitted-media references.
- Deduplicate reused modules both across books and against DynaWord, including web shards.
- Check PII patterns and potential benchmark overlap; record exclusions.
- Measure actual tokens with a named tokenizer; no size estimate is asserted here.
- Build content-addressed versions, typed lineage, actual runs, Evidence and Claims.
- Publish a PiotrSty source snapshot and a separate PR only in the implementation phase.
