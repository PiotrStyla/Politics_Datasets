# Kultura bez Barier: candidate assessment v0.1

Checked and executed: 2026-09-07. Status: published source dataset and open DynaWord PR #27.

## Source evidence

- Official catalogue: https://kulturabezbarier.org/publikacje/
- The catalogue declares CC BY-SA 3.0 alongside publications and pictograms. Preserve the declaration and verify its scope for each selected title; do not treat a catalogue-level declaration as a completed per-document rights audit.
- Scope: 12 Polish text-oriented PDF candidates, excluding the German edition, duplicate DOCX rendition, pictograms and comic before acquisition.
- Readable sample: https://kulturabezbarier.org/wp-content/uploads/2024/04/Model_Dostepnej_Kultury_2023.pdf (83 pages; attribution on page 2).
- Readable sample: https://kulturabezbarier.org/wp-content/uploads/2019/12/Napisy-dla-nieslyszacych_zasady-tworzenia_2019.pdf (13 pages; credited authors on page 13).
- Extraction warning: https://kulturabezbarier.org/wp-content/uploads/2019/12/Audiodeskrypcja-zasady-tworzenia.pdf has malformed Polish characters in the web text extraction. Validate another extractor against rendered pages before admitting this title.
- No occurrence of `licenc` was found in the web-extracted Model PDF or Publikacja_FKBB.pdf. This limited text search is not proof that no visual license notice exists.

## Executed run

- Acquired: 12 PDFs with source hashes and raw snapshots.
- Retained: 9 publication-level records, 316 pages, 608,827 characters.
- Tokens: 217,932 measured with `cl100k_base` as a proxy.
- Author coverage: 100% using PDF credits/metadata plus the official catalogue authorship statement.
- PII-pattern matches redacted: 16 email addresses and 1 labelled phone number.
- Within-source exact and seeded MinHash/Jaccard near dedup: no duplicates removed.
- Excluded: two NIMOZ training volumes due to rights/authorship conflict with the catalogue-level claim; one old audiodescription PDF due to legacy font mapping errors.
- A better `pdfplumber` extraction recovered the study-visit summary and accessibility guide that failed preliminary extraction checks.

## DynaWord presence and publication

Target main at publication: a916edecabc2be8832e08fb2bd9dfafcc1d2dd71.
The public repository metadata and all 26 discussion summaries were read. None identifies this dedicated source. Open PRs include Edukacja Medialna (#26), a different publisher/source.

No matches for the domain, foundation-name pattern or audiodescription alias were found in:

- src/sources.py
- configs/source_candidates_v0_3.json
- artifacts/source_findings.md
- artifacts/source_scouting_v0_3.md
- artifacts/source_license_review_v0_3.md
- README.md

Published source dataset: https://huggingface.co/datasets/PiotrSty/kultura-bez-barier-pl at immutable commit `4e447551196f7f7ebebd8ceaf3fc655f42dd7e93`, tagged `v1.0.0`.

DynaWord PR: https://huggingface.co/datasets/SlayerLab/polish-dynaword/discussions/27 at commit `9c8af8753e902571a1c73094cc0f3bcd31bf11fc`.

Remote audit re-downloaded and SHA-256-verified 41 files across the source repository and PR. The PR is open. The README still labels v0.2.5 stable; registry/main, an open PR and stable-release status remain separate observations. The supported claim is no dedicated source found before this PR, not zero textual overlap.

## Remaining gates

Potential value: practical Polish explanatory prose about accessible cultural services, museum visits, audiodescription and subtitling. This remains a hypothesis about mix diversity, not a measured training benefit.

Still pending at target integration: maintainer/legal interpretation of the catalogue-level CC BY-SA 3.0 scope, cross-source exact/near deduplication, benchmark contamination checks and controlled training ablations. Under the Slayer framework, the source and run are validated artifacts; inclusion in a merged or stable DynaWord release is not claimed.
