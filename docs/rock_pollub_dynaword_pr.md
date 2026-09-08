# ROCK Politechnika Lubelska -> Polish DynaWord

Status observed on 2026-09-08: published source dataset and open DynaWord PR.

- Source dataset: https://huggingface.co/datasets/PiotrSty/rock-pollub-pl-books
- Source revision: `76f0b7fbd134947e3f143bb72dd27c3029cdd979`
- Stable tag: `v1.0.0`
- Pull request: https://huggingface.co/datasets/SlayerLab/polish-dynaword/discussions/33
- PR revision: `3c845cd4a0708da984aa5ae0b1f86b1af5c28adf`
- Pinned target base: `02bcb0b5f991a30f8454c6444f701633b71f69d4`
- Records: 8 complete Polish academic books.
- Tokens: 1,177,858 measured with `cl100k_base`.
- License: `CC-BY-SA-4.0` at both item and matched original-PDF bitstream level.
- Samples: 8 deterministic complete records.
- Remote verification: 31 files matched local SHA-256 digests.

The PR deliberately excludes 597 otherwise relevant records whose original PDF
bitstream omits matching machine-readable rights metadata, plus two PDFs above
the 50 MiB pilot limit. No exact or fuzzy title overlap was detected against
the 42,071-row `biblioteka_nauki` attribution column at the pinned target
revision. Target-wide text deduplication and training ablations remain pending.
