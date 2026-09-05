# Open AGH chemistry contribution v1.0.0

## Publication

- Source: https://huggingface.co/datasets/PiotrSty/open-agh-chemistry-pl
- Release tag: `v1.0.0`
- Release commit: `b1871d64734ad5e10816e5b2245aaf7a32b930db`
- Immutable payload: `07d38bfdb3c9ac961f0aed380195cada1871d53b`
- DynaWord PR: https://huggingface.co/datasets/SlayerLab/polish-dynaword/discussions/25
- PR commit: `904b2487aafcaea61bea487c512e5dcc5bcc7e5d`
- Target base: `a916edecabc2be8832e08fb2bd9dfafcc1d2dd71`

This is an open source-contribution PR, not a merged or stable DynaWord release.

## Source scope

Only the four approved original Polish chemistry editions were collected:

| AGH book ID | Subject | Discovered modules | Retained records |
| --- | --- | ---: | ---: |
| 29 | General chemistry | 186 | 184 |
| 1394 | Inorganic chemistry and periodic table | 49 | 48 |
| 37 | Polymer chemistry | 82 | 81 |
| 1893 | Corrosion and corrosion protection | 57 | 57 |

Official book cards: `https://epodreczniki.open.agh.edu.pl/handbook/{id}`.
Original Polish titles, authors, ISBNs and institutional attribution are preserved
in the source artifacts and data sidecar. No other subject or translated edition
was included.

The public handbook/items APIs expose module IDs and observed revision labels.
The public HTML preview endpoint supplies readable text without authentication.
The authenticated revision-content endpoint was not used for acquisition.
Module revisions were checked against the inventory after each HTML fetch;
the preserved byte hashes, not mutable preview URLs, identify this snapshot.

## Counts and verification

- Snapshot: 2026-09-05
- Discovered and downloaded unique modules: 374, no download failures
- Retained records: 370
- Measured tokens: 564,028 (`tiktoken` / `cl100k_base` proxy)
- Characters: 1,446,015
- Rejected: two short bodies and two book-information pages
- Within-source normalized exact/MinHash-Jaccard duplicates removed: zero
- Complete deterministic samples: 12, selected three per book
- Parquet SHA-256: `a26d4fa2d515238bf2f2d028b18e641ecd0735ee65a79e045bc7cc44601f5ee8`

Repeated builds produced byte-identical Parquet. All 370 records were replayed
from the preserved HTML; token counts and author values were checked individually.
Six importer tests and two staged contribution-contract tests passed.

Post-publication audit verified all 35 remote files against local SHA-256 hashes,
the public release tag and the PR revision on 2026-09-05. PR #25 was open; target
main remained at the audited base. Existing source registry content was preserved.

[Sample records](https://huggingface.co/datasets/PiotrSty/open-agh-chemistry-pl/blob/07d38bfdb3c9ac961f0aed380195cada1871d53b/artifacts/sample.jsonl)
and [licensing evidence](https://huggingface.co/datasets/PiotrSty/open-agh-chemistry-pl/blob/07d38bfdb3c9ac961f0aed380195cada1871d53b/artifacts/books.json)
are pinned to the immutable payload.

## Rights, quality and research graph

Each official EPUB independently supplied a CC BY-SA 4.0 rights page, original
book link and required attribution notice. Those XHTML pages, their hashes and
original EPUB response hashes accompany the snapshot. Only source text/metadata
is redistributed, not EPUB image binaries. NOTICE.md preserves publisher credit,
authors, original edition links, license links and modification notices. This
adaptation is shared under CC BY-SA 4.0.

Native LaTeX is retained; media are omitted and table cells are flattened.
Text can still refer to missing figures. Balanced delimiters are not a proof
of equation correctness. Language classification covers all retained text.
Email and labelled-phone patterns had zero matches; these checks are not
comprehensive de-identification. Public author attribution remains, and preserved
raw source snapshots are explicitly not claimed to be de-identified.

The Slayer graph includes content-addressed source/dataset Versions, build and
validation Protocols, actual Runs, typed lineage, addressable Evidence, separately
falsifiable Claims, Actors and an evidence-backed pending cross-source gate.
Tests check source/code digests and the acyclic version graph.

Corpus-wide DynaWord exact/near deduplication and benchmark overlap checks remain
pending. No textual-novelty or model-improvement claim is made. Evaluate a capped
chemistry source share in controlled ablations before stable-release integration.

## Reproduce

Install `scripts/open_agh_requirements.txt`. Live acquisition:

```powershell
python -X utf8 scripts/build_open_agh_pl.py --output data/open_agh_chemistry_pl_v1 discover
python -X utf8 scripts/build_open_agh_pl.py --output data/open_agh_chemistry_pl_v1 fetch
python -X utf8 scripts/build_open_agh_pl.py --output data/open_agh_chemistry_pl_v1 build
python -X utf8 scripts/publish_open_agh_pl.py --output data/open_agh_chemistry_pl_v1 verify
python -X utf8 -m pytest -q scripts/test_build_open_agh_pl.py
```

Discovery refuses to overwrite an existing inventory or create another proposal
when AGH is identified in the checked target surfaces. For offline replay,
download the pinned source release, decompress artifacts/modules.jsonl.gz to
WORK/modules.jsonl, copy artifacts/books.json to WORK/inventory.json and
artifacts/target_audit.json to WORK/target_audit.json. Run the released
`src/build_open_agh_pl.py --output WORK build`. Run timestamps will describe a new
execution, while the dataset can be byte-identical.

The publisher's `publish` command is an explicit remote write, using HF_TOKEN
without logging it. It stages privately, tests the PR contract, publishes the
version and opens a PR; it never merges. A local publication.json receipt records
the remote commits. Use `audit` for public read-only checksum/tag/PR checks.
