# OpenStax Poland: eight academic textbook volumes

## Publication

- Source: https://huggingface.co/datasets/PiotrSty/openstax-pl-textbooks
- Release: `v1.0.0`, commit `08649ffa3252d2bc72c1eb8a64204cdcf6230d05`
- Immutable payload: `5b31f74eb3733b330c6093dabc919fe304f6ef6f`
- DynaWord PR: https://huggingface.co/datasets/SlayerLab/polish-dynaword/discussions/23
- Target base: `a916edecabc2be8832e08fb2bd9dfafcc1d2dd71`
- PR commit: `339fdfa3e758f4d0ff5d52252ec5ab079c75ffc5`

This is a source contribution proposed for review, not a merged source or a
new stable DynaWord training release.

## Scope and counts

Eight Polish editions: physics volumes 1-3, psychology, microeconomics,
macroeconomics, marketing and nutrition. Each preserved book foreword explicitly
provides CC BY 4.0 evidence. This does not assert that all OpenStax editions or
third-party media have the same license. The contribution is text-only.

- Snapshot date: 2026-09-05
- Discovered and downloaded pages: 1,612
- Retained documents: 1,422
- Tokens: 4,632,374, measured using tiktoken `cl100k_base` (proxy tokenizer)
- Characters: 12,375,066
- Whitespace-delimited words: 1,703,169
- Parquet SHA-256: `8455c23e9f775a155f349a00dbbe29c321b9056059226c5840a9d200d1bc2081`

[24 complete samples, three per book](https://huggingface.co/datasets/PiotrSty/openstax-pl-textbooks/blob/5b31f74eb3733b330c6093dabc919fe304f6ef6f/artifacts/sample.jsonl)
are accompanied by per-document source URLs, content hashes and attribution.

## Selection and QA

Rejected pages: 153 frontmatter/index/bibliography/standalone answer keys;
14 failed formula conversion; 8 normalized exact duplicates; 7 confidently
non-Polish pages; 4 too short; 3 low letter ratio; 1 near duplicate.

HTML paragraph extraction omits media and navigation. TeX annotations or a
versioned MathML converter preserve formulas. Empty source placeholders and
spacing nodes are removed; missing operands are never inferred. Embedded
references, further-reading lists and exercises referring to omitted figures
can remain. This is not a claim of perfect equation or table reconstruction.

All retained pages are language classified. Exact normalization and seeded
MinHash candidate retrieval plus exact five-word-shingle Jaccard >=0.9 are
applied within the source. Probabilistic retrieval can miss similar pairs.
Email and labelled-phone patterns are checked; this is not comprehensive PII
de-identification. Published author names and attributed examples remain.

All 1,422 retained texts were replayed from saved HTML and every token count
recomputed. Two builds produced byte-identical Parquet. Eight importer tests
and two staged contribution-contract tests passed before PR creation.

## Slayer research graph

Post-publication audit on 2026-09-05 verified all 30 remote source/PR files
against local SHA-256 hashes, the release tag and unchanged existing registry
entries. PR #23 was open and the target main remained at the audited base.

The manifest records Object and content-addressed Version, pinned source
snapshot, Protocol, actual timed Run with code/dependency hashes, typed lineage,
addressable Evidence, separately falsifiable Claims, Actors and an explicitly
pending cross-source deduplication attestation. No training-gain claim is made.

Corpus-wide DynaWord exact/near deduplication and benchmark overlap checks
remain pending. Exercises are pretraining candidates, not a clean evaluation
set. Test a capped educational source share in controlled ablations before
stable-release inclusion. Registry absence is not proof of text novelty.

## Reproduce and verify

Install `scripts/openstax_requirements.txt`. The live acquisition commands are:

```powershell
python -X utf8 scripts/build_openstax_pl.py --output data/openstax_pl_v1 discover
python -X utf8 scripts/build_openstax_pl.py --output data/openstax_pl_v1 fetch
python -X utf8 scripts/build_openstax_pl.py --output data/openstax_pl_v1 build
python -X utf8 scripts/publish_openstax_pl.py --output data/openstax_pl_v1 verify
python -X utf8 -m pytest -q scripts/test_build_openstax_pl.py
```

Discovery intentionally stops if a matching source is already registered or
proposed. For exact offline replay, use the released source snapshot instead:
decompress `artifacts/source_pages.jsonl.gz` to WORK/source_pages.jsonl, copy
`artifacts/books.json` to WORK/inventory.json and copy `artifacts/target_audit.json`
to WORK/target_audit.json. Run the pinned HF `src/build_openstax_pl.py` with
`--output WORK build`. The data output is deterministic; Run timestamps describe
the new execution and therefore its evidence version will differ.

`publish_openstax_pl.py publish` is an explicit remote write command. It checks
the PiotrSty identity and pinned target base, stages a private payload, validates
the PR contract, publishes the release and opens (never merges) a PR. It reads
HF_TOKEN without printing it. Do not invoke it to inspect an existing release.
The receipt is stored under the output directory.

`publish_openstax_pl.py --output data/openstax_pl_v1 audit` is a public read-only
remote check of release/tag, PR status, every contributed file hash and unchanged
existing registry entries; it saves `publication_audit.json` locally.
