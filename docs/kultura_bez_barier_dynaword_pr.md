# Kultura bez Barier PL - DynaWord contribution

Published 2026-09-07.

- Source dataset: https://huggingface.co/datasets/PiotrSty/kultura-bez-barier-pl
- Immutable source commit: `4e447551196f7f7ebebd8ceaf3fc655f42dd7e93`
- Release tag: `v1.0.0`
- DynaWord PR: https://huggingface.co/datasets/SlayerLab/polish-dynaword/discussions/27
- PR commit: `9c8af8753e902571a1c73094cc0f3bcd31bf11fc`
- Target main at submission: `a916edecabc2be8832e08fb2bd9dfafcc1d2dd71`
- Data: 9 records, 316 pages, 217,932 `cl100k_base` proxy tokens
- License evidence: official catalogue-level CC BY-SA 3.0 declaration
- Remote verification: 41 files matched local SHA-256 digests

The contribution preserves raw PDFs, catalogue HTML, source URLs, hashes, attribution, selection decisions, QA, complete public samples, tests and a Slayer ontology manifest. Three PDFs were rejected: two due to rights/authorship conflicts and one due to defective legacy font extraction.

Pending gates are explicit: legal interpretation of catalogue-level license scope, cross-source deduplication, benchmark contamination checks and controlled training ablations. The PR is a source proposal, not a merged or stable DynaWord release.
