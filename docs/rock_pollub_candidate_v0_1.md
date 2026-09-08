# ROCK Politechnika Lubelska: candidate assessment v0.1

## Decision

Accepted as a small, explicitly licensed eight-book subset. The complete ROCK
source is not proposed because most candidate PDF bitstreams do not carry the
same machine-readable rights evidence as their parent item records.

The qualified subset was published as `PiotrSty/rock-pollub-pl-books` v1.0.0
and proposed to Polish DynaWord in PR #33 on 2026-09-08.

## Source

- Repository collection: https://rock.pollub.pl/collections/a42db069-319d-4d51-88d1-490ee7e6bad8
- Publisher policy: https://wpl.pollub.pl/pl/i/Polityka-publikacyjna/20
- Collection size observed on 2026-09-08: 771 archived items.
- Candidate filter: `CC-BY-SA-4.0`, Polish, `Book`, and subtype
  `Monograph`, `Handbook`, or `Workbook`.

## Pilot result

- Target: 20 records.
- Records with matching item-level and original-PDF-level CC BY-SA 4.0 evidence: 8.
- Acquisition rejections: 599.
- Missing PDF-bitstream rights evidence: 597.
- PDF above the temporary 50 MiB pilot limit: 2.
- Retained after text QA: 8.
- Text: 3,380,937 characters.
- Tokens: 1,177,858 using `cl100k_base`.
- Author coverage: 100%.
- PII pattern replacements: 2 email addresses, 0 labelled phone numbers.
- Isolated unreadable PDF glyphs: 2, represented as `[UNREADABLE_GLYPH]`.
- Final Parquet size: 1,267,933 bytes.
- Complete local pilot footprint: 9,041,746 bytes; no PDF is retained.

## Existing DynaWord overlap

The eight pilot titles were compared with the `id` and `attribution` columns of
all 42,071 records in the current `biblioteka_nauki` Parquet. No normalized
exact-title substring or fuzzy title match at 0.90 or above was detected.
This is metadata evidence only. Target-wide text deduplication remains pending.
The comparison target is pinned to DynaWord revision
`02bcb0b5f991a30f8454c6444f701633b71f69d4`.

## Slayer ontology mapping

- `Object`: source collection and derived pilot dataset.
- `Version`: content-addressed source inventory and dataset artifacts.
- `Protocol`: item and PDF rights gate, extraction, normalization, PII patterns,
  and within-pilot exact/near deduplication.
- `Run`: timestamped execution with measured statistics.
- `Evidence`: hashed inventory, QA report, and metadata-overlap audit.
- `Claim`: eligibility and absence of detected title overlap are falsifiable;
  training value and full-corpus novelty remain explicitly untested.
- `Relation`: derived dataset version is linked to its source version and run.

## Remaining gates

- Decide whether publisher policy plus item-level license is sufficient for the
  597 records whose PDF bitstream omits machine-readable rights metadata.
- Run target-wide text deduplication during integration.
- Check benchmark contamination and quoted third-party textual material.
- Run a controlled training ablation before making a training-value claim.

## Publication

- Dataset: https://huggingface.co/datasets/PiotrSty/rock-pollub-pl-books
- Immutable source commit: `76f0b7fbd134947e3f143bb72dd27c3029cdd979`
- Release tag: `v1.0.0`
- DynaWord PR: https://huggingface.co/datasets/SlayerLab/polish-dynaword/discussions/33
- PR commit: `3c845cd4a0708da984aa5ae0b1f86b1af5c28adf`
- Remote audit: 31 files verified byte-for-byte; PR status `open`.

## Reproduction

```powershell
python scripts/build_rock_pollub_pl.py --output data/rock_pollub_pl_pilot_v0_1 acquire
python scripts/build_rock_pollub_pl.py --output data/rock_pollub_pl_pilot_v0_1 audit_overlap
python scripts/build_rock_pollub_pl.py --output data/rock_pollub_pl_pilot_v0_1 build
python scripts/build_rock_pollub_pl.py --output data/rock_pollub_pl_pilot_v0_1 verify
```
