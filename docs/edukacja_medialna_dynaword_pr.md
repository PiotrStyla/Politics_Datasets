# Edukacja Medialna PL: DynaWord contribution

Published: 2026-09-06

- Source repository: https://huggingface.co/datasets/PiotrSty/edukacja-medialna-pl
- Stable tag: `v1.0.1`
- Immutable source revision: `5ad711084f722532b1fb643625913f7a41ad7505`
- DynaWord PR: https://huggingface.co/datasets/SlayerLab/polish-dynaword/discussions/26
- Immutable PR revision: `f37ac1dded9a76e17d0c81163bf282afe1d5f59d`
- Pinned target `main`: `a916edecabc2be8832e08fb2bd9dfafcc1d2dd71`

## Result

- 255 lesson URLs discovered and acquired without fetch failures.
- 252 documents retained; 3 excluded for missing creator attribution.
- 728,987 `cl100k_base` proxy tokens and 2,033,576 characters.
- 100% author coverage among retained records.
- 12 complete deterministic samples.
- CC BY-SA 3.0 required explicitly on both the lesson page and source XML.
- One example email was pattern-redacted; no labelled phone match was found.
- No within-source normalized exact or near duplicate was removed.

## Scope and caveats

The dataset is a text-only extraction of authored lesson explanations and
scenarios from official source XML. External reading lists and long-quote
elements were omitted. Source dates are preserved but do not establish that
historical technology or legal guidance is current. Pattern checks are not
comprehensive de-identification. Remaining inline third-party excerpts require
review. Cross-source DynaWord exact/near deduplication and benchmark overlap
remain integration gates. Training benefit is an untested diversity hypothesis.

## Reproducibility and ontology

The publication contains raw XML, acquisition and file checksums, per-record
attribution and rights, selection decisions, QA, the pinned builder and tests.
The Slayer manifest separates content-addressed source and derived Versions,
processing and validation Protocols, executed Runs, typed lineage, append-only
Evidence, falsifiable Claims and Actors. The local contract suite passed 2 tests;
the builder unit suite passed 3 tests. A remote checksum audit verified 28 files.
