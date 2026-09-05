#!/usr/bin/env python3
"""Validate, publish and prepare a pinned OpenStax DynaWord contribution.

Credentials are read from HF_TOKEN or the current user's Windows environment.
No credentials are persisted in the build, artifacts or receipts.
"""
from __future__ import annotations

import argparse
import ast
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from build_openstax_pl import (
    BOOKS, FIELDS, SOURCE, OWN_REPO, TARGET, digest, write_json, read_jsonl,
    update_registry, now, normalized_key, extract,
)


def verify(root):
    import pyarrow.parquet as pq
    import tiktoken
    checksums = json.loads((root / "artifacts/checksums.json").read_text(encoding="utf-8"))
    for name, sha in checksums.items():
        if digest((root / name).read_bytes()) != sha:
            raise ValueError(f"Checksum mismatch: {name}")
    table = pq.read_table(root / "data/train-00000-of-00001.parquet")
    if table.column_names != FIELDS:
        raise ValueError("Schema mismatch")
    rows = table.to_pylist()
    stats = json.loads((root / "artifacts/stats.json").read_text(encoding="utf-8"))
    sidecars = read_jsonl(root / "artifacts/attribution.jsonl")
    if len(rows) != stats["kept"] or len(sidecars) != len(rows):
        raise ValueError("Record count mismatch")
    if len({normalized_key(r["text"]) for r in rows}) != len(rows):
        raise ValueError("Duplicate normalized output text")
    if {r["id"] for r in rows} != {s["id"] for s in sidecars}:
        raise ValueError("Attribution IDs mismatch")
    if {s["book"] for s in sidecars} != set(BOOKS):
        raise ValueError("Book coverage mismatch")
    with gzip.open(root / "artifacts/source_pages.jsonl.gz", "rt", encoding="utf-8") as stream:
        sources = {r["url"]: r for r in map(json.loads, stream)}
    sidecar_by_id = {s["id"]: s for s in sidecars}
    encoder = tiktoken.get_encoding("cl100k_base")
    for index, row in enumerate(rows, 1):
        if index % 200 == 0:
            print(f"Replaying {index}/{len(rows)} retained pages", flush=True)
        sidecar = sidecar_by_id[row["id"]]
        source = sources[sidecar["url"]]
        if row["text"] != extract(source["content_html"])[0]:
            raise ValueError("Text does not reproduce from snapshot")
        if row["token_count"] != len(encoder.encode_ordinary(row["text"])):
            raise ValueError("Tokenizer count mismatch")
        if row["license"] != "CC-BY-4.0" or not row["author"]:
            raise ValueError("License/attribution missing")
        if digest(row["text"].encode()) != sidecar["text_sha256"]:
            raise ValueError("Text checksum mismatch")
    if sum(r["token_count"] for r in rows) != stats["tokens"]:
        raise ValueError("Token total mismatch")
    rejected = read_jsonl(root / "artifacts/rejections.jsonl")
    retained_urls = {s["url"] for s in sidecars}
    rejected_urls = {r["url"] for r in rejected}
    if len(retained_urls) != len(rows) or len(rejected_urls) != len(rejected) or retained_urls & rejected_urls:
        raise ValueError("Non-unique selection decisions")
    if retained_urls | rejected_urls != set(sources):
        raise ValueError("A discovered source page has no selection decision")
    print(f"Verified {len(rows)} rows, attribution, checksums, extraction replay and token totals", flush=True)
    return stats


def ontology(root, payload_commit):
    artifacts = root / "artifacts"
    stats = json.loads((artifacts / "stats.json").read_text(encoding="utf-8"))
    checksums = json.loads((artifacts / "checksums.json").read_text(encoding="utf-8"))
    run = json.loads((artifacts / "run.json").read_text(encoding="utf-8"))
    target = json.loads((artifacts / "target_audit.json").read_text(encoding="utf-8"))
    qa = json.loads((artifacts / "qa.json").read_text(encoding="utf-8"))
    object_id = "slayer://object/dataset-source/openstax_pl"
    version_digest = digest(checksums)
    version_id = object_id.replace("/object/", "/version/") + "@sha256:" + version_digest
    upstream_object = "slayer://object/source-snapshot/openstax_pl"
    upstream_id = upstream_object.replace("/object/", "/version/") + "@sha256:" + checksums["artifacts/source_pages.jsonl.gz"]
    protocol_id = "slayer://object/protocol/openstax_pl"
    spec = {"entrypoint": "python src/build_openstax_pl.py --output WORK build", "input": "source_pages.jsonl + inventory.json",
        "normalization": "NFKC, paragraph whitespace; preserve math; exclude media and frontmatter/index/bibliography/answer-key pages",
        "quality": "minimum 200 chars; letter ratio >=0.35; langid eight-language check; drop non-Polish confidence >=0.99",
        "privacy": "email and labelled-phone redaction", "tokenizer": "cl100k_base",
        "dedup": "casefolded whitespace-normalized exact; seeded MinHashLSH and exact five-word-shingle Jaccard >=0.9",
        "dependencies": run["packages"], "code_sha256": run["code_sha256"]}
    protocol_digest = digest(spec)
    protocol_version = protocol_id.replace("/object/", "/version/") + "@sha256:" + protocol_digest
    run_id = "slayer://run/openstax_pl@sha256:" + digest(run)
    evidence = []
    for kind, payload in (("artifact_checksums", checksums), ("counts", stats), ("quality_and_limits", qa),
        ("book_licenses", {"artifact": "artifacts/books.json", "sha256": checksums["artifacts/books.json"], "editions": 8, "license": "CC-BY-4.0"}),
        ("target_registry_check", target)):
        evidence.append({"id": "slayer://evidence/openstax_pl/" + kind + "@sha256:" + digest({"run": run_id, "payload": payload}),
            "run_id": run_id, "subject_version": version_id, "observation_type": kind, "payload": payload, "observed_at": run["finished_at"]})
    evidence_ids = {e["observation_type"]: e["id"] for e in evidence}
    claims = []
    for statement, falsification, support in (
        ("The selected snapshot covers eight Polish textbook volumes with book-specific CC BY 4.0 evidence.", "A contributed book lacks the preserved license evidence or the snapshot contains another book.", ["book_licenses", "counts"]),
        ("Every discovered page has a retained or rejected decision and retained text replays from the pinned snapshot.", "A discovered URL lacks a decision or offline extraction changes the published text.", ["counts", "artifact_checksums"]),
        ("The source key is absent from the pinned pre-contribution registry; corpus-wide novelty remains untested.", "The pinned registry contains openstax_pl or a claim of completed cross-source text dedup is made.", ["target_registry_check", "quality_and_limits"]),
    ):
        claim = {"scope": version_id, "statement": statement, "falsification_condition": falsification, "asserted_by": "agent:codex",
            "supported_by": [evidence_ids[k] for k in support]}
        claims.append({"id": "slayer://claim/openstax_pl@sha256:" + digest(claim), **claim})
    uri = f"hf://datasets/{OWN_REPO}@{payload_commit}/"
    manifest = {"ontology_version": "slayer.ai/research-ontology/v0.1", "schema_version": "slayer.ai/dataset-source-contribution/v1",
        "object": {"id": object_id, "kind": "dataset_source", "name": SOURCE},
        "version": {"id": version_id, "object_id": object_id, "digest": "sha256:" + version_digest, "payload_uri": uri + "data/train-00000-of-00001.parquet", "created_at": run["finished_at"], "created_by": "agent:codex"},
        "source_object": {"id": upstream_object, "kind": "source_snapshot", "name": "Eight Polish OpenStax editions"},
        "source_version": {"id": upstream_id, "object_id": upstream_object, "digest": "sha256:" + checksums["artifacts/source_pages.jsonl.gz"], "payload_uri": uri + "artifacts/source_pages.jsonl.gz", "created_at": run["started_at"], "created_by": "agent:codex"},
        "protocol": {"id": protocol_id, "kind": "dataset_processing", "specification": spec, "version": {"id": protocol_version, "object_id": protocol_id, "digest": "sha256:" + protocol_digest, "payload_uri": uri + "src/build_openstax_pl.py", "created_at": run["started_at"], "created_by": "agent:codex"}},
        "run": {"id": run_id, "protocol_version_id": protocol_version, **run,
            "inputs": [{"role": "source_snapshot", "version_id": upstream_id}], "outputs": [{"role": "dataset", "version_id": version_id}]},
        "relations": [{"source_version_id": version_id, "predicate": pred, "target_version_id": dst, "introduced_by_run": run_id}
            for pred, dst in (("DERIVED_FROM", upstream_id), ("FILTERED_BY", protocol_version), ("COMPATIBLE_WITH", f"hf://datasets/{TARGET}@{target['revision']}"))],
        "evidence": evidence, "claims": claims,
        "claim_evidence": [{"claim_id": c["id"], "evidence_id": e, "relation": "SUPPORTS", "introduced_by_run": run_id} for c in claims for e in c["supported_by"]],
        "actors": [{"id": "agent:codex", "kind": "agent", "identity": "OpenAI Codex"}, {"id": "hf:PiotrSty", "kind": "human", "identity": "Piotr Styla"}, {"id": "org:openstax-poland", "kind": "organization", "identity": "OpenStax Poland and credited contributors"}],
        "attestations": [{"id": "slayer://attestation/openstax_pl/cross-source-dedup@sha256:" + digest({"subject": version_id, "evidence": evidence_ids["quality_and_limits"], "value": "pending_target_integration"}), "type": "cross_source_deduplication", "value": "pending_target_integration", "actor_id": "agent:codex", "subject_version": version_id, "supported_by": [evidence_ids["quality_and_limits"]], "created_at": run["finished_at"]}]}
    write_json(artifacts / "ontology.json", manifest)
    return manifest


def docs(root, payload_commit):
    stats = json.loads((root / "artifacts/stats.json").read_text(encoding="utf-8"))
    books = json.loads((root / "artifacts/books.json").read_text(encoding="utf-8"))
    notice = "# Attribution\n\nText: CC BY 4.0, https://creativecommons.org/licenses/by/4.0/.\n\n"
    for book in books:
        notice += f"- {book['title']}: {'; '.join(book['metadata'].get('citation_author', []))}; OpenStax Poland and edition contributors. Full contributor credits: {book['foreword_url']}\n"
    notice += "\nPreparation: Piotr Styla with OpenAI Codex. Changes: HTML prose extraction, media omission, Unicode/whitespace normalization, formula conversion, pattern redaction, quality filtering and deduplication. No endorsement by OpenStax is implied. Original forewords and page URLs are preserved in artifacts/books.json and attribution.jsonl.\n"
    (root / "NOTICE.md").write_text(notice, encoding="utf-8")
    body = f"""# OpenStax Poland academic textbooks

Text-only research contribution from eight Polish textbook volumes: physics
(three volumes), psychology, microeconomics, macroeconomics, marketing and nutrition.

- Discovered pages: {stats['source_pages']:,}
- Retained documents: {stats['kept']:,}
- Tokens: {stats['tokens']:,} (`cl100k_base` proxy, measured on retained text)
- Characters: {stats['chars']:,}
- License: CC BY 4.0, documented separately in each preserved Polish foreword.
- Snapshot payload commit: `{payload_commit}`

## Attribution and source

See NOTICE.md and artifacts/books.json for book authors, Polish edition contributor
credits, source URLs and book-specific license evidence. This is a snapshot of the
eight recorded Polish editions, not a blanket license assertion for all OpenStax books.
Sources: https://openstax.pl/podreczniki and https://openstax.org/books/.

## Reproduction

Install `src/openstax_requirements.txt`. Decompress
`artifacts/source_pages.jsonl.gz` into WORK/source_pages.jsonl, copy
`artifacts/books.json` into WORK/inventory.json and copy artifacts/target_audit.json
into WORK/target_audit.json. Run:

```sh
python src/build_openstax_pl.py --output WORK build
```

This replays the preserved source containers offline. Live acquisition uses
`discover`, then `fetch`; it creates a new dated snapshot. Content hashes, exact
dependency versions, execution timestamps, per-page decisions, checksums and the
Slayer ontology graph accompany the data.

## Quality and limits

Paragraph-preserving HTML extraction; media, frontmatter, indices, pages named
Bibliografia and standalone answer keys excluded. Embedded references and further
reading lists can remain in retained pages. MathML is converted using TeX annotations,
alttext or mathml-to-latex; pages with conversion failures are excluded. Email and labelled phone
patterns are redacted. Author names and attributed examples remain.

Every retained page is language-checked. Internal dedup uses normalized exact text
and seeded MinHashLSH candidates with exact five-word-shingle Jaccard >=0.9.
MinHash candidate retrieval is probabilistic. Some exercises still refer to omitted
figures; equations and tables need care in downstream processing.

Corpus-wide DynaWord exact/near dedup and benchmark contamination checks remain
pending. No claim of wholly new text or improved model quality is made. This is
a pretraining candidate split, not an evaluation set; exercises require benchmark
overlap review. Use a capped educational source share in controlled ablations.

## Files

- data/train-00000-of-00001.parquet: canonical DynaWord fields.
- artifacts/sample.jsonl: 24 deterministic complete documents, three per book.
- artifacts/attribution.jsonl: per-record URLs, contributors, hashes and changes.
- artifacts/rejections.jsonl: one decision per excluded page.
- artifacts/source_pages.jsonl.gz: immutable source content containers.
- artifacts/books.json: inventory and license evidence.
- artifacts/stats.json, qa.json, run.json, checksums.json, ontology.json: research evidence.
"""
    header = "---\nlicense: cc-by-4.0\nlanguage:\n- pl\ntask_categories:\n- text-generation\nconfigs:\n- config_name: default\n  data_files:\n  - split: train\n    path: data/train-00000-of-00001.parquet\n---\n\n"
    (root / "README.md").write_text(header + body, encoding="utf-8")
    return body


def prepare(out, payload_commit):
    root = out / "hf_repo"
    body = docs(root, payload_commit)
    ontology(root, payload_commit)
    pr = out / "dynaword_pr"
    data = pr / "data" / SOURCE
    data.mkdir(parents=True, exist_ok=True)
    (pr / "src").mkdir(exist_ok=True)
    (pr / "artifacts").mkdir(exist_ok=True)
    shutil.copy2(root / "data/train-00000-of-00001.parquet", data / f"{SOURCE}.parquet")
    for filename in ("attribution.jsonl", "sample.jsonl", "stats.json", "qa.json", "rejections.jsonl", "books.json"):
        shutil.copy2(root / "artifacts" / filename, data / f"{SOURCE}.{filename}")
    shutil.copy2(root / "NOTICE.md", data / "NOTICE.md")
    (data / f"{SOURCE}.md").write_text(body.replace("src/build_openstax_pl.py", "src/fetch_openstax_pl.py"), encoding="utf-8")
    shutil.copy2(root / "artifacts/ontology.json", pr / "artifacts/openstax_pl_ontology_manifest.json")
    shutil.copy2(root / "src/build_openstax_pl.py", pr / "src/fetch_openstax_pl.py")
    shutil.copy2(root / "src/openstax_requirements.txt", pr / "src/openstax_requirements.txt")
    shutil.copy2(Path(__file__).with_name("test_openstax_contribution.py"), pr / "src/test_openstax_contribution.py")
    (pr / "src/sources.py").write_text(update_registry((out / "target_sources.py").read_text(encoding="utf-8")), encoding="utf-8")
    stats = json.loads((root / "artifacts/stats.json").read_text(encoding="utf-8"))
    description = f"""## Add Polish OpenStax academic prose

Adds `openstax_pl`: {stats['kept']:,} documents and {stats['tokens']:,}
measured `cl100k_base` proxy tokens from eight Polish textbook volumes.
The complete discovered snapshot has {stats['source_pages']:,} pages. Each page
has an explicit retained or rejected decision.

Source: [PiotrSty/openstax-pl-textbooks](https://huggingface.co/datasets/{OWN_REPO}).
Pinned payload: `{payload_commit}`. License: **CC BY 4.0**, supported by each
Polish edition's preserved foreword and contributor attribution.

### Data sample

[24 complete deterministic sample documents, three per book](https://huggingface.co/datasets/{OWN_REPO}/blob/{payload_commit}/artifacts/sample.jsonl).
[Attribution and source URLs](https://huggingface.co/datasets/{OWN_REPO}/blob/{payload_commit}/artifacts/attribution.jsonl).
[Book-specific licensing evidence](https://huggingface.co/datasets/{OWN_REPO}/blob/{payload_commit}/artifacts/books.json).

### Validation and ontology

All retained text replays from preserved source HTML containers. Checks cover
schema, record counts, hashes, attribution IDs, token totals and book coverage.
Every retained page has a language classification. Normalized exact and seeded
MinHash candidate / exact Jaccard deduplication are applied within the source.
The Slayer graph records content-addressed source and dataset versions, the
processing protocol and actual run, typed lineage, Evidence, falsifiable Claims,
Actors and evidence-backed status.

### Integration limits

Corpus-wide exact/near dedup and benchmark overlap checks remain pending;
source-key absence does not establish textual novelty. Equations/tables and
exercises referencing omitted figures are documented limitations. Please run
the target-wide gates and test a capped educational share before a stable release.
This PR contributes the source and its review evidence, not a new stable release.
"""
    (out / "pr_description.md").write_text(description, encoding="utf-8")


def token():
    value = os.environ.get("HF_TOKEN")
    if not value and os.name == "nt":
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value = winreg.QueryValueEx(key, "HF_TOKEN")[0]
    if not value or not value.startswith("hf_"):
        raise ValueError("HF_TOKEN unavailable")
    return value


def publish(out):
    from huggingface_hub import HfApi, CommitOperationAdd
    root = out / "hf_repo"
    verify(root)
    api = HfApi(token=token())
    if api.whoami()["name"].casefold() != "piotrsty":
        raise ValueError("HF account is not PiotrSty")
    audit = json.loads((out / "target_audit.json").read_text(encoding="utf-8"))
    if api.dataset_info(TARGET).sha != audit["revision"]:
        raise ValueError("Target main changed; rebase registry before publication")
    receipt_path = out / "publication.json"
    receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
    if not receipt:
        if api.repo_exists(OWN_REPO, repo_type="dataset"):
            raise ValueError("Own repo already exists without this run's receipt; inspect before writing")
        api.create_repo(OWN_REPO, repo_type="dataset", private=True)
        receipt = {"repository": OWN_REPO, "created_at": now()}
        write_json(receipt_path, receipt)
    if not receipt.get("payload_commit"):
        files = [p for p in root.rglob("*") if p.is_file() and p.name not in ("ontology.json", "README.md") and "__pycache__" not in p.parts and ".pytest_cache" not in p.parts]
        result = api.create_commit(OWN_REPO, repo_type="dataset", commit_message="Add validated eight-book Polish OpenStax snapshot",
            operations=[CommitOperationAdd(path_in_repo=p.relative_to(root).as_posix(), path_or_fileobj=str(p)) for p in files])
        receipt["payload_commit"] = result.oid
        write_json(receipt_path, receipt)
    prepare(out, receipt["payload_commit"])
    subprocess.run([sys.executable, "-m", "pytest", "-q", str(out / "dynaword_pr/src/test_openstax_contribution.py")], check=True)
    if not receipt.get("release_commit"):
        result = api.create_commit(OWN_REPO, repo_type="dataset", parent_commit=receipt["payload_commit"],
            commit_message="Document immutable payload, attribution and Slayer ontology",
            operations=[CommitOperationAdd(path_in_repo=n, path_or_fileobj=str(root / n)) for n in ("README.md", "NOTICE.md", "artifacts/ontology.json")])
        receipt["release_commit"] = result.oid
        write_json(receipt_path, receipt)
    tags = api.list_repo_refs(OWN_REPO, repo_type="dataset").tags
    if not any(t.name == "v1.0.0" for t in tags):
        api.create_tag(OWN_REPO, repo_type="dataset", tag="v1.0.0", revision=receipt["release_commit"])
    api.update_repo_settings(OWN_REPO, repo_type="dataset", private=False)
    if not receipt.get("pr_url"):
        pr = out / "dynaword_pr"
        result = api.create_commit(TARGET, repo_type="dataset", parent_commit=audit["revision"], create_pr=True,
            commit_message="Add CC BY 4.0 Polish OpenStax academic textbooks",
            commit_description=(out / "pr_description.md").read_text(encoding="utf-8"),
            operations=[CommitOperationAdd(path_in_repo=p.relative_to(pr).as_posix(), path_or_fileobj=str(p)) for p in pr.rglob("*") if p.is_file() and "__pycache__" not in p.parts and ".pytest_cache" not in p.parts])
        receipt.update(pr_url=result.pr_url, pr_commit=result.oid)
        write_json(receipt_path, receipt)
    print(json.dumps(receipt, indent=2), flush=True)


def audit_publication(out):
    from huggingface_hub import HfApi, hf_hub_download
    from huggingface_hub.utils import disable_progress_bars
    disable_progress_bars()
    api = HfApi(token=False)
    receipt = json.loads((out / "publication.json").read_text(encoding="utf-8"))
    source = api.dataset_info(OWN_REPO)
    if source.private or source.sha != receipt["release_commit"]:
        raise ValueError("Public source release does not match receipt")
    tags = api.list_repo_refs(OWN_REPO, repo_type="dataset").tags
    if not any(t.name == "v1.0.0" and t.target_commit == source.sha for t in tags):
        raise ValueError("Release tag does not match receipt")
    number = int(receipt["pr_url"].rsplit("/", 1)[-1])
    discussion = api.get_discussion_details(TARGET, number, repo_type="dataset")
    if not discussion.is_pull_request:
        raise ValueError("Discussion is not a pull request")
    pr_info = api.dataset_info(TARGET, revision=f"refs/pr/{number}")
    if pr_info.sha != receipt["pr_commit"]:
        raise ValueError("PR revision differs from publication receipt")
    verified = []
    for repository, revision, directory in (
        (OWN_REPO, source.sha, out / "hf_repo"),
        (TARGET, pr_info.sha, out / "dynaword_pr"),
    ):
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or ".pytest_cache" in path.parts:
                continue
            name = path.relative_to(directory).as_posix()
            remote = Path(hf_hub_download(repository, name, repo_type="dataset", revision=revision,
                token=False, cache_dir=str(out / "remote_verification_cache")))
            sha = digest(remote.read_bytes())
            if sha != digest(path.read_bytes()):
                raise ValueError(f"Remote checksum mismatch: {repository}/{name}")
            verified.append({"repository": repository, "revision": revision, "path": name, "sha256": sha})
    def registry(text):
        tree = ast.parse(text)
        return ast.literal_eval(next(n.value for n in tree.body if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "SOURCES" for t in n.targets)))
    before = registry((out / "target_sources.py").read_text(encoding="utf-8"))
    after = registry((out / "dynaword_pr/src/sources.py").read_text(encoding="utf-8"))
    after.pop(SOURCE)
    if before != after:
        raise ValueError("Unrelated source registry entries changed")
    result = {"observed_at": now(), "source_revision": source.sha, "tag": "v1.0.0",
        "pr_url": receipt["pr_url"], "pr_revision": pr_info.sha, "pr_status": discussion.status,
        "target_main_revision": api.dataset_info(TARGET).sha, "verified_files": verified}
    write_json(out / "publication_audit.json", result)
    print(json.dumps({**result, "verified_files": len(verified)}, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("command", choices=["verify", "prepare", "publish", "audit"])
    parser.add_argument("--payload-commit", default="0" * 40)
    args = parser.parse_args()
    if args.command == "verify":
        verify(args.output / "hf_repo")
    elif args.command == "prepare":
        prepare(args.output, args.payload_commit)
    elif args.command == "audit":
        audit_publication(args.output)
    else:
        publish(args.output)


if __name__ == "__main__":
    main()
