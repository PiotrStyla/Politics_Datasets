# TED Polish procurement notices: candidate assessment v0.1

Date: 2026-09-08
Status: published source dataset and open DynaWord PR; merge and legal/mix gates remain pending.
Scope: original Polish-language notice prose from TED; no attachments,
machine-translated language variants, or procurement submissions.

## Evidence observed in this research run

- E1: HF repository `PleIAs/TEDEUTenders`, revision
  `2752d9d6f7628387583eac2435caa11edb36b9c1`, declares 224,049 rows,
  including 20,594 with `language=POL`. After conflicting duplicate-row checks,
  the pinned index contains 20,588 unique notice identifiers.
- E2: Repository files include annual Parquet files named 2015 through 2024.
  This does not establish complete annual coverage. Metadata declares CC0-1.0,
  but the README ends with an all-rights-reserved statement. Do not silently
  resolve this conflict by relabelling the mirror as a cleared CC0 corpus.
- E3: TED's official legal notice expressly allows commercial and non-commercial
  reuse of procurement notices unless otherwise noted. It separately assigns
  CC BY 4.0 to editorial site content and CC0 to metadata. These are different
  scopes. Exceptions include third-party works and identifiable individuals.
- E4: TED documents public, unauthenticated search and daily/monthly XML downloads.
- E5: DynaWord main revision `02bcb0b5f991a30f8454c6444f701633b71f69d4`
  was inspected immediately before publication. No dedicated TED source was
  registered and no matching proposal was present. This is not proof of zero
  document overlap with other sources.
- E6: The mirror preview contains U+FFFD encoding damage and contact details,
  so mirror text is not training input. The official TED Search API supplied
  all 20,588 records and substantive Polish narrative fields for 19,333;
  1,255 records used official XML fallback.
- E7: The deterministic build retained 15,544 documents and measured
  42,475,098 `cl100k_base` proxy tokens. It rejected 1,014 records as too short,
  2,350 exact normalized duplicates and 1,680 near duplicates. Retained records
  have 100% institutional author coverage, no U+FFFD and no detected raw email.
- E8: The source dataset was published as
  `PiotrSty/ted-polish-procurement-notices@c2075874d36035e6cbc29b252155ac1da299cd13`
  with tag `v1.0.0`. DynaWord PR #32 is based on main revision
  `02bcb0b5f991a30f8454c6444f701633b71f69d4`; 30 remote files matched local
  SHA-256 values in the post-publication audit.

## Claims and limitations

- C1 (supported by E1, E4, E7): the bounded contribution is a substantial
  42.5M-token administrative and technical corpus. It is not claimed to be a
  complete historical inventory of all Polish TED notices.
- C2 (qualified by E2, E3): Prefer a direct official XML importer with the
  specific notice-reuse terms preserved, rather than republishing the HF mirror
  under an unqualified CC0 claim. Legal review of exceptions remains pending.
- C3 (supported by E7, still requiring training experiments): descriptions of
  goods, construction, services and technical requirements add substantial
  domain prose, but duplicate and form-like material is frequent. Inclusion
  and training-mix weight therefore remain separate decisions.

## Executed protocol

1. Pin the mirror revision and enumerate unique Polish-labelled identifiers.
2. Fetch checksum-addressed official Search API records in exact-ID batches;
   use official XML only where Polish narrative fields are absent.
3. Extract Polish narrative and institutional attribution; omit structured
   contact/address fields and attachments, then apply bounded PII patterns.
4. Remove frequent exact boilerplate, too-short records, exact duplicates and
   seeded MinHash/LSH near duplicates; count with `cl100k_base`.
5. Publish Parquet, full deterministic samples, per-record attribution and
   decisions, QA, checksums, executed runs and a Slayer ontology manifest.
6. Open DynaWord PR #32. Per-notice exception/legal review, cross-source dedup,
   benchmark-overlap testing and mix cap/ablation remain explicit pending gates.

## Sources

- https://huggingface.co/datasets/PleIAs/TEDEUTenders
- https://datasets-server.huggingface.co/statistics?dataset=PleIAs%2FTEDEUTenders&config=default&split=train
- https://ted.europa.eu/en/legal-notice
- https://docs.ted.europa.eu/api/latest/search.html
- https://api.ted.europa.eu/swagger-ui/index.html
- https://docs.ted.europa.eu/ODS/latest/reuse/download-xml.html
- https://huggingface.co/datasets/PiotrSty/ted-polish-procurement-notices
- https://huggingface.co/datasets/SlayerLab/polish-dynaword/discussions/32
