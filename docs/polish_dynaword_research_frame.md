# Polish Dynaword - research frame

## Context

This workspace is oriented around the Slayer / DynaWord Polish data effort:
turning `SlayerLab/polish-dynaword` into a full open research project, not only
a cleanup task.

Near-term focus: Polish DynaWord data work in the general-news / open Polish
pretraining-data ontology, with tasks ranging from beginner manual review to
advanced controlled training and evaluation.

Reference dataset card checked on 2026-08-24:

- Hugging Face dataset: `SlayerLab/polish-dynaword`
- current stable release noted on the card: `v0.2.5`
- stable size noted on the card: 4,319,200 documents / 9.64B tokens
- development track: `v0.3-dev`, described as candidate audits,
  quality/diversity workflow and source-gate validation
- license on the dataset card: `cc-by-sa-4.0`

## Research Goal

Build a reference Polish pretraining dataset, then test which data decisions
actually help models.

The target output is not only a cleaned dataset. The target output is a public,
reproducible research package:

- dataset releases,
- source and provenance documentation,
- data-quality and dedup tooling,
- PII and legal-review artifacts,
- controlled data-mix ablations,
- model-training runs,
- evaluation results and statistical analysis,
- a pretraining-data creation playbook,
- paper-ready methodology and results.

## Slayer Ontology Alignment

All dataset and Slayer work in this workspace should follow the artifact-focused
Slayer Research Ontology supplied in `slayer_research_ontology (1).pdf`.

The practical rule: do not treat a task as merely "a script" or "a scrape" when
it affects research data. Treat it as a contribution to a versioned research
graph:

- `Object`: logical research object, such as a source, dataset, eval, model,
  protocol, tool, failure set or provenance note.
- `Version`: immutable content-addressed snapshot of an object.
- `Relation`: typed edge between versions, such as `DERIVED_FROM`,
  `FILTERED_BY`, `TRAINED_ON`, `EVALUATED_BY`,
  `CONTAMINATION_CHECKED_AGAINST` or `VALIDATED_AGAINST`.
- `Protocol`: versioned procedure, such as scraping, filtering, dedup,
  PII-scrubbing, legal review, training, evaluation or reproduction.
- `Run`: concrete execution of a protocol with pinned inputs, config,
  environment and actor.
- `Evidence`: addressable measurement or observation produced by a run.
- `Claim`: falsifiable interpretation supported, refuted or qualified by
  evidence.
- `Actor`: person, organization, agent, CI job or worker responsible for
  creation, execution, review or attestation.

For every meaningful task, prefer outputs that can become durable graph
artifacts: source manifests, raw snapshots, checksums, transformation logs,
validation reports, evidence bundles, claims, failure sets, eval items,
verifiers or documented exclusion decisions.

Important invariants:

- Published versions are immutable; corrections create new versions.
- Historical provenance pins digests, not mutable aliases such as `latest`.
- Lineage between concrete versions remains acyclic, even when research loops.
- Evidence is append-only.
- Claims must be falsifiable and scoped to a measurable protocol or condition.
- Domain concepts such as dataset, model, eval, tokenizer, pretraining,
  benchmark and metric are profiles or applications above the kernel, not
  assumptions baked into the ontology.

## Workstreams

- Manual review and gold sets: beginner-friendly filtering, labeling and source
  inspection tasks.
- Scripted filtering and classification: reproducible heuristics and pipelines
  for quality tags, source classes and exclusion reasons.
- Dedup and data quality: exact, normalized and near-duplicate handling;
  garble/OCR detection; source-level diagnostics.
- PII scrubbing: detection, masking/removal policy, recall checks and audit
  samples.
- Provenance and legal review: traceable source basis, attribution evidence,
  license compatibility and exclusion logs.
- Data-mix analysis: token shares, source caps, temperature sampling and
  high-quality final-stage mixes.
- Controlled training runs: small and medium ablations with documented configs.
- Architecture tests: compare data effects across model families or training
  setups.
- Evals and statistics: benchmark selection, contamination checks, confidence
  intervals and effect-size reporting.
- Playbook and publication: convert practical decisions into reusable
  methodology and paper sections.

## Contribution Ladder

Each meaningful task should end in a public artifact that can be referenced in a
CV, GitHub profile or paper contribution log.

Example contribution levels:

- Beginner: labeled review batch, issue with evidence, gold-set sample,
  source-screening notes.
- Programmer: reproducible scraper, validator, classifier, data-quality report
  or CI check.
- ML engineer: training config, ablation run, evaluation table, error analysis.
- Advanced researcher: experimental design, statistical analysis, legal/source
  policy, paper section.

Significant contributions can support co-authorship, especially when they add a
verifiable dataset artifact, pipeline, validation result, training run,
evaluation, documentation or release work.

## RCL Source Role

The RCL / `legislacja.gov.pl` work should be treated as a candidate
source-ingestion and provenance pipeline, not just as scraping.

For this source family, the useful artifacts are:

- source inventory: project IDs, titles, applicants, dates and process stages,
- consultation-document manifest: category, filename, URL, author, date,
  local path, SHA-256 and selection status,
- raw HTML snapshots for auditability,
- PDF corpus artifacts grouped by project and category,
- legal/provenance note covering public-information status and downstream
  license/attribution constraints,
- optional extracted text with OCR status and quality flags,
- exclusion/retention decisions for training mixes.

RCL should be assessed separately from already-heavy legal/parliamentary text in
the DynaWord mix. The research question is not "can we add more official/legal
text?", but whether specific consultation/public-comment material adds useful
contemporary civic/institutional language without worsening legal-style
overrepresentation.

## Working Norms

- Prefer small, concrete tasks over broad research meetings.
- Keep provenance and legal notes beside the data.
- Preserve raw artifacts when feasible so decisions can be audited.
- Separate source inclusion from training-mix weighting.
- Treat failures, exclusions and quality problems as publishable evidence when
  they are documented.
- Make every task produce a reviewable artifact: CSV, JSONL, script, report,
  issue, benchmark result, model card delta or paper note.
