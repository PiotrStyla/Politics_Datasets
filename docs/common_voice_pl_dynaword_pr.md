# Add CC0 Polish Common Voice validated text (v26.0)

## Scope

This contribution adds a text-only projection of Polish sentences associated
with validated recordings in Mozilla Common Voice Scripted Speech 26.0. It does
not include audio, contributor identifiers, demographic fields or file paths.

## Data

- Source rows inspected: `138,798` validated clip records
- Unique normalized sentences retained: `45,043`
- Characters: `2,637,100`
- Whitespace-delimited words: `379,819`
- Tokens: `994,922` (`cl100k_base` proxy)
- License: `CC0-1.0`
- Deterministic data sample: [common_voice_pl.sample.jsonl](https://huggingface.co/datasets/PiotrSty/common-voice-pl-text/blob/v1.0.0/data/common_voice_pl.sample.jsonl)
- Published source snapshot: [PiotrSty/common-voice-pl-text v1.0.0](https://huggingface.co/datasets/PiotrSty/common-voice-pl-text/tree/v1.0.0)

The build rejected `2,557` source rows (`2,538` too short and `19` too long)
and collapsed `91,198` repeated clip rows after within-source normalization.

## Provenance

- Official dataset: `Mozilla Data Collective / Common Voice Scripted Speech 26.0 - Polish`
- Official dataset ID: `cmqinmu2a00winq07gyrtri0q`
- Release date: `2026-06-12`
- Pinned access mirror: `Peacockery/common-voice-scripted-speech-26@b4d8b94d43831475de59a455345acf6945cfd66e`
- Source Parquet LFS SHA-256: `abd846a0411d04cf88920161100625e9cbe64a111d17474ac49375f490dafb3a`
- Immutable prepared payload: `PiotrSty/common-voice-pl-text@2e3e62d374df8cad50e443a356e2c2bec86e10b4`
- Prepared Parquet SHA-256: `2c22fb1be8badb75f55c0f1f6719360ab50dc798054a7673d67b2780c41858b2`

The source is read with DuckDB column projection, so the 4.48 GB embedded audio
payload is never downloaded or copied into this contribution.

## Quality and privacy

- Unicode NFKC and whitespace normalization
- Casefolded punctuation-insensitive exact deduplication within the source
- Simple malformed-text, URL, email, telephone-like and PESEL-like filters
- Deterministic `langid.py` audit on 5,000 rows: `99.7%` classified as Polish
- No `client_id`, age, gender, accent, source path or audio column retained
- DynaWord schema: `id, text, source, added, created, token_count, license, author`

## Slayer ontology

The PR includes a content-addressed source version, versioned filtering
protocol, concrete run, typed lineage, checksummed Evidence, falsifiable Claims,
Actors and attestations. Evidence and claims are kept as separate objects.

## Limitations and integration decision

This is a short-sentence source containing contemporary, institutional and
older literary Polish. It should not be described as spontaneous conversation.
Some text may overlap Wikipedia, public-domain literature or parliamentary
material already represented in DynaWord.

Corpus-wide exact and near-duplicate checks are explicitly marked as pending;
no cross-source novelty claim is made. I recommend running the existing
corpus-wide dedup protocol and testing a capped source share in data-mix
ablations before including it in a stable training release.

## Verification

- `7 passed` local unit and contribution-contract tests
- Source key absent from pinned target base `a916edecabc2be8832e08fb2bd9dfafcc1d2dd71`
- Repeated build reproduced the same prepared Parquet SHA-256
