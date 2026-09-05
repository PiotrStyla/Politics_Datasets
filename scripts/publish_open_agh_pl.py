#!/usr/bin/env python3
"""Verify, publish and independently audit the Open AGH contribution."""
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

from build_open_agh_pl import (BOOK_IDS, SOURCE, OWN_REPO, TARGET, LICENSE, FIELDS,
    sha, save, read, read_lines, now, extract, normalize, module_map, registry)


def verify(out):
    import pyarrow.parquet as pq
    import tiktoken
    started = now()
    root = out / "hf_repo"
    sums = read(root / "artifacts/checksums.json")
    for name, value in sums.items():
        if sha((root / name).read_bytes()) != value:
            raise ValueError("Checksum mismatch: " + name)
    table = pq.read_table(root / "data/train-00000-of-00001.parquet")
    rows = table.to_pylist()
    books = read(root / "artifacts/books.json")
    modules = module_map(books)
    raw = {r["module_id"]: r for r in map(json.loads, gzip.decompress((root / "artifacts/modules.jsonl.gz").read_bytes()).decode().splitlines())}
    decisions = read_lines(root / "artifacts/decisions.jsonl")
    sidecars = read_lines(root / "artifacts/attribution.jsonl")
    stats = read(root / "artifacts/stats.json")
    if table.column_names != FIELDS or len(rows) != stats["kept"] or len({r["id"] for r in rows}) != len(rows):
        raise ValueError("Schema/count/identity mismatch")
    if len(decisions) != len(modules) or {d["module_id"] for d in decisions} != set(raw) or set(raw) != set(modules):
        raise ValueError("Incomplete source decisions")
    by_id = {s["id"]: s for s in sidecars}
    if len(sidecars) != len(rows) or set(by_id) != {r["id"] for r in rows}:
        raise ValueError("Attribution mismatch")
    if {d["module_id"] for d in decisions if d["selected"]} != {s["module_id"] for s in sidecars}:
        raise ValueError("Selected decision mismatch")
    if {b["book_id"] for s in sidecars for b in s["memberships"]} != set(BOOK_IDS):
        raise ValueError("Book coverage mismatch")
    encoder = tiktoken.get_encoding("cl100k_base")
    for row in rows:
        sidecar = by_id[row["id"]]
        mid = sidecar["module_id"]
        expected = normalize(modules[mid]["title"]) + "\n\n" + extract(raw[mid]["html"])[0]
        if row["text"] != expected or sha(expected.encode()) != sidecar["text_sha256"]:
            raise ValueError("Snapshot replay mismatch")
        if row["token_count"] != len(encoder.encode_ordinary(row["text"])):
            raise ValueError("Token count mismatch")
        if row["license"] != LICENSE or row["author"] != "; ".join(modules[mid]["authors"]):
            raise ValueError("Rights/author mismatch")
    if sum(r["token_count"] for r in rows) != stats["tokens"]:
        raise ValueError("Token total mismatch")
    report = {"started_at": started, "finished_at": now(), "actor_id": "agent:codex",
        "protocol": "checksum/schema/coverage/source-text replay/per-record token and author validation",
        "code_sha256": sha(Path(__file__).read_bytes()), "dataset_checksums_sha256": sha(sums),
        "verified_records": len(rows), "verified_tokens": stats["tokens"], "success": True}
    save(out / "validation_report.json", report)
    print(f"Verified {len(rows)} records, all source decisions, text replay and token counts", flush=True)
    return report


def ontology(root, payload, validation):
    artifact = root / "artifacts"
    sums, run = read(artifact / "checksums.json"), read(artifact / "run.json")
    audit = read(artifact / "target_audit.json")
    uri = f"hf://datasets/{OWN_REPO}@{payload}/"
    def version(kind, digest, path):
        obj = f"slayer://object/{kind}/{SOURCE}"
        return {"id": obj.replace("/object/", "/version/") + "@sha256:" + digest,
            "object_id": obj, "digest": "sha256:" + digest, "payload_uri": uri + path,
            "created_at": run["finished_at"], "created_by": "agent:codex"}
    data_v = version("dataset-source", sha(sums), "data/train-00000-of-00001.parquet")
    source_spec = {name: sums[name] for name in ("artifacts/modules.jsonl.gz", "artifacts/books.json")}
    source_v = version("source-snapshot", sha(source_spec), "artifacts/modules.jsonl.gz")
    source_v.update(components=source_spec, inventory_uri=uri + "artifacts/books.json")
    spec = {"command": "python src/build_open_agh_pl.py --output WORK build", "code_sha256": run["code_sha256"],
        "packages": run["packages"], "input": "inventory.json and modules.jsonl", "allowlist": list(BOOK_IDS),
        "minimum_body_chars": 200, "minimum_letter_ratio": 0.35, "tokenizer": "cl100k_base",
        "language_check": "langid eight-language classification; reject non-PL confidence >=0.99",
        "dedup": "module identity, normalized exact body, seeded MinHashLSH + exact 5-word-shingle Jaccard >=.9",
        "extraction": "HTML prose, native LaTeX, exclude media; reject unbalanced math delimiters",
        "privacy": "email and labelled-phone redaction; official author attribution preserved"}
    protocol_v = version("protocol", sha(spec), "src/build_open_agh_pl.py")
    validation_v = version("validation-protocol", sha({"code": validation["code_sha256"], "protocol": validation["protocol"]}), "src/publish_open_agh_pl.py")
    run_id = f"slayer://run/{SOURCE}@sha256:" + sha(run)
    validation_id = f"slayer://run/{SOURCE}/validation@sha256:" + sha(validation)
    evidence = []
    for kind, content in (("checksums", sums), ("counts", read(artifact / "stats.json")), ("quality", read(artifact / "qa.json")),
        ("license", {"books_artifact": uri + "artifacts/books.json", "sha256": sums["artifacts/books.json"], "editions": list(BOOK_IDS), "license": LICENSE}),
        ("target_audit", audit), ("validation", validation)):
        evidence.append({"id": f"slayer://evidence/{SOURCE}/{kind}@sha256:" + sha(content), "observation_type": kind,
            "subject_version": data_v["id"], "run_id": validation_id if kind == "validation" else run_id,
            "payload": content, "observed_at": validation["finished_at"] if kind == "validation" else run["finished_at"]})
    evidence_ids = {e["observation_type"]: e["id"] for e in evidence}
    claims = []
    for statement, falsification, support in (
        ("The four selected editions have preserved explicit CC BY-SA 4.0 rights and module authorship.", "An included edition lacks its rights page or a retained module lacks attribution.", ["license", "validation"]),
        ("Every discovered module has a selection decision and each retained text and token count replay from the snapshot.", "A module has no decision or a reproduced record/token count differs.", ["counts", "validation"]),
        ("A dedicated AGH registration/proposal was not identified in the audited registry and discussion titles; textual novelty remains untested.", "The pinned registry or recorded discussion titles identify this contribution.", ["target_audit", "quality"]),
    ):
        body = {"statement": statement, "falsification_condition": falsification, "scope": data_v["id"],
            "asserted_by": "agent:codex", "supported_by": [evidence_ids[k] for k in support]}
        claims.append({"id": f"slayer://claim/{SOURCE}@sha256:" + sha(body), **body})
    manifest = {"ontology_version": "slayer.ai/research-ontology/v0.1", "schema_version": "slayer.ai/dataset-source-contribution/v1",
        "object": {"id": data_v["object_id"], "kind": "dataset_source", "name": SOURCE}, "version": data_v,
        "source_object": {"id": source_v["object_id"], "kind": "source_snapshot"}, "source_version": source_v,
        "protocol": {"id": protocol_v["object_id"], "kind": "protocol", "version": protocol_v, "specification": spec},
        "validation_protocol": {"id": validation_v["object_id"], "kind": "protocol", "version": validation_v, "description": validation["protocol"]},
        "run": {"id": run_id, **run, "protocol_version_id": protocol_v["id"], "inputs": [source_v["id"]], "outputs": [data_v["id"]]},
        "validation_run": {"id": validation_id, **validation, "protocol_version_id": validation_v["id"], "inputs": [data_v["id"]], "outputs": [evidence_ids["validation"]]},
        "evidence": evidence, "claims": claims,
        "claim_evidence": [{"claim_id": c["id"], "evidence_id": e, "relation": "SUPPORTS"} for c in claims for e in c["supported_by"]],
        "relations": [{"source_version_id": data_v["id"], "predicate": p, "target_version_id": v, "introduced_by_run": validation_id if p == "VALIDATED_AGAINST" else run_id}
            for p, v in (("DERIVED_FROM", source_v["id"]), ("FILTERED_BY", protocol_v["id"]), ("VALIDATED_AGAINST", validation_v["id"]),
                ("COMPATIBLE_WITH", f"hf://datasets/{TARGET}@{audit['revision']}"))],
        "actors": [{"id": "agent:codex", "kind": "agent", "identity": "OpenAI Codex"}, {"id": "hf:PiotrSty", "kind": "human", "identity": "Piotr Styla"},
            {"id": "org:agh", "kind": "organization", "identity": "AGH University of Krakow and credited authors"}],
        "attestations": [{"id": f"slayer://attestation/{SOURCE}@sha256:" + sha({"subject": data_v["id"], "state": "pending", "evidence": evidence_ids["quality"]}),
            "type": "cross_source_deduplication", "value": "pending_target_integration", "actor_id": "agent:codex", "subject_version": data_v["id"], "supported_by": [evidence_ids["quality"]], "created_at": run["finished_at"]}]}
    save(artifact / "ontology.json", manifest)


def prepare(out, payload):
    root = out / "hf_repo"
    stats, books = read(root / "artifacts/stats.json"), read(root / "artifacts/books.json")
    ontology(root, payload, read(out / "validation_report.json"))
    notice = "# Attribution and license\n\nCC BY-SA 4.0: https://creativecommons.org/licenses/by-sa/4.0/deed.pl\n\n"
    for book in books:
        authors = sorted({a for m in book["occurrences"] for a in m["authors"]})
        notice += f"## {book['title']}\n\nAuthors: {'; '.join(authors)}.\n\nPublisher: {book['metadata']['publisher']}.\n\n"
        notice += "Wersja oryginalna e-podr\u0119cznika dost\u0119pna na stronie: " + book["url"] + "\n\n"
    notice += "Preparation: Piotr Styla with OpenAI Codex. Changes: module-level HTML prose extraction, media removal, whitespace/Unicode normalization, formula preservation, pattern redaction, quality filtering and deduplication. No endorsement by AGH is implied. The recorded rights pages and per-module authors are in artifacts/books.json and attribution.jsonl. This text adaptation is shared under CC BY-SA 4.0.\n"
    (root / "NOTICE.md").write_text(notice, encoding="utf-8")
    body = f"""# Open AGH Polish chemistry textbooks

Four Polish editions: general chemistry, inorganic chemistry, polymer chemistry,
and corrosion/corrosion protection. This is an independent text-only adaptation.

- Snapshot: {stats['added']}
- Module occurrences: {stats['module_occurrences']}; unique modules: {stats['unique_modules']}
- Retained records: {stats['kept']}; measured tokens: {stats['tokens']} (`cl100k_base` proxy)
- Characters: {stats['chars']}
- License: CC BY-SA 4.0, independently documented in each official EPUB rights page.
- Immutable payload: `{payload}`

## Source, attribution and changes

See NOTICE.md, artifacts/books.json and artifacts/attribution.jsonl for the
original edition URLs, module authors, institutional credit, book-specific
rights XHTML, observed revision labels and hashes. Preserve attribution,
original publication links, license links and notices of modifications.
The license assertion concerns these four editions, not every repository item.
No media binaries are redistributed. Published source HTML snapshots are not
de-identified; only the selected text undergoes the documented pattern checks.

## Reproduction

Install `src/open_agh_requirements.txt`. Decompress artifacts/modules.jsonl.gz
into WORK/modules.jsonl; copy artifacts/books.json to WORK/inventory.json and
artifacts/target_audit.json to WORK/target_audit.json. Run:

```sh
python src/build_open_agh_pl.py --output WORK build
python src/publish_open_agh_pl.py --output WORK verify
```

Build is offline and preserves native LaTeX, including chemical notation.
The data replay is deterministic; a new Run has new execution timestamps.
Live acquisition uses `discover` and `fetch` in a fresh output directory.
API revisions are observed labels; immutable identity is the recorded byte hash.

## QA and limitations

Each discovered unique module has a selection decision. Minimum body length
200 chars; letter ratio >=0.35; reject unbalanced LaTeX delimiters and confidently
non-Polish text. All retained text, author attribution and token counts are replayed.
Module identity and normalized exact dedup precede seeded MinHashLSH candidates
and exact five-word-shingle Jaccard >=0.9. Candidate retrieval is probabilistic.

Media are omitted, so some prose references missing figures. Tables are flattened;
retaining LaTeX and balanced delimiters does not establish equation correctness.
Email/labelled-phone checks are limited, not comprehensive PII de-identification.
The `created` field is a book publication metadata proxy, not a module creation date.
Embedded citations may remain. Corpus-wide DynaWord exact/near dedup and benchmark
overlap checks remain pending. Test a capped chemistry source share in controlled
ablations; neither textual novelty nor training gains are asserted.

## Review artifacts

- artifacts/sample.jsonl: {stats['sample_count']} complete deterministic sample records, selected three per book.
- artifacts/attribution.jsonl and decisions.jsonl: record provenance and selection decisions.
- artifacts/books.json and modules.jsonl.gz: source snapshot and official licensing evidence.
- artifacts/checksums.json, stats.json, qa.json, run.json, ontology.json: versioned research evidence.

The Slayer graph separates Objects/Versions, processing and validation Protocols,
actual Runs, typed lineage, Evidence, falsifiable Claims, Actors and pending gates.
This is a pretraining candidate source, not an uncontaminated benchmark or a stable
DynaWord release. The HF train split points only to data/*.parquet.
"""
    header = "---\nlicense: cc-by-sa-4.0\nlanguage:\n- pl\ntask_categories:\n- text-generation\nconfigs:\n- config_name: default\n  data_files:\n  - split: train\n    path: data/train-00000-of-00001.parquet\n---\n\n"
    (root / "README.md").write_text(header + body, encoding="utf-8")
    pr = out / "dynaword_pr"
    data = pr / "data" / SOURCE
    data.mkdir(parents=True, exist_ok=True)
    (pr / "src").mkdir(exist_ok=True)
    (pr / "artifacts").mkdir(exist_ok=True)
    shutil.copy2(root / "data/train-00000-of-00001.parquet", data / f"{SOURCE}.parquet")
    for name in ("attribution.jsonl", "decisions.jsonl", "sample.jsonl", "books.json", "stats.json", "qa.json"):
        shutil.copy2(root / "artifacts" / name, data / f"{SOURCE}.{name}")
    shutil.copy2(root / "NOTICE.md", data / "NOTICE.md")
    (data / f"{SOURCE}.md").write_text(body, encoding="utf-8")
    shutil.copy2(root / "artifacts/ontology.json", pr / f"artifacts/{SOURCE}_ontology_manifest.json")
    for path in (root / "src").glob("*"):
        if path.is_file():
            shutil.copy2(path, pr / "src" / path.name)
    (pr / "src/sources.py").write_text(registry((out / "target_sources.py").read_text(encoding="utf-8")), encoding="utf-8")
    description = f"""## Add Open AGH Polish chemistry prose

Adds `{SOURCE}` from four Polish chemistry textbooks: **{stats['kept']} records,
{stats['tokens']:,} measured cl100k_base proxy tokens**, from {stats['unique_modules']} discovered modules.
Book IDs: 29, 1394, 37, 1893. Text only, with per-module authorship and CC BY-SA 4.0
documented in each preserved official EPUB rights page. Attribution, original
edition links, ShareAlike terms and modification notices are preserved.

Source: [PiotrSty/open-agh-chemistry-pl](https://huggingface.co/datasets/{OWN_REPO}).
Immutable payload: `{payload}`.

### Data sample

[{stats['sample_count']} complete deterministic sample records](https://huggingface.co/datasets/{OWN_REPO}/blob/{payload}/artifacts/sample.jsonl).
[Book-specific rights evidence](https://huggingface.co/datasets/{OWN_REPO}/blob/{payload}/artifacts/books.json).
[Per-record authors and original URLs](https://huggingface.co/datasets/{OWN_REPO}/blob/{payload}/artifacts/attribution.jsonl).

### Verification and Slayer ontology

All retained texts, token counts and author fields replay from the immutable
snapshot. Every discovered module has a selection decision. Source identity,
exact normalization and seeded MinHash/Jaccard dedup are applied within source.
The manifest includes content-addressed Objects/Versions, processing and validation
Protocols, actual Runs, typed lineage, Evidence, falsifiable Claims and Actors.

### Remaining integration gates

Cross-source DynaWord exact/near dedup and benchmark overlap checks remain pending.
Source-key absence does not prove textual novelty. Media are omitted; references
to missing figures, flattened tables and formula quality require downstream care.
Test a capped chemistry share in controlled ablations before stable-release inclusion.
This PR proposes a source, not a merged or stable DynaWord release.
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


def files(root):
    return [p for p in sorted(root.rglob("*")) if p.is_file() and "__pycache__" not in p.parts and ".pytest_cache" not in p.parts]


def publish(out):
    from huggingface_hub import HfApi, CommitOperationAdd
    from huggingface_hub.utils import disable_progress_bars
    disable_progress_bars()
    verify(out)
    root = out / "hf_repo"
    api = HfApi(token=token())
    if api.whoami()["name"].casefold() != "piotrsty":
        raise ValueError("Unexpected HF account")
    audit = read(out / "target_audit.json")
    if api.dataset_info(TARGET).sha != audit["revision"]:
        raise ValueError("Target changed; inspect/rebase before publication")
    receipt_path = out / "publication.json"
    receipt = read(receipt_path) if receipt_path.exists() else {}
    if not receipt:
        if api.repo_exists(OWN_REPO, repo_type="dataset"):
            raise ValueError("Existing source repository without this run receipt")
        api.create_repo(OWN_REPO, repo_type="dataset", private=True)
        receipt = {"repository": OWN_REPO, "created_at": now()}
        save(receipt_path, receipt)
    if not receipt.get("payload_commit"):
        result = api.create_commit(OWN_REPO, repo_type="dataset", commit_message="Add validated four-book AGH chemistry snapshot",
            operations=[CommitOperationAdd(path_in_repo=p.relative_to(root).as_posix(), path_or_fileobj=str(p)) for p in files(root) if p.name not in ("README.md", "NOTICE.md", "ontology.json")])
        receipt["payload_commit"] = result.oid
        save(receipt_path, receipt)
    prepare(out, receipt["payload_commit"])
    subprocess.run([sys.executable, "-m", "pytest", "-q", str(out / "dynaword_pr/src/test_open_agh_contribution.py")], check=True)
    if not receipt.get("release_commit"):
        result = api.create_commit(OWN_REPO, repo_type="dataset", parent_commit=receipt["payload_commit"], commit_message="Document attribution and pinned Slayer research graph",
            operations=[CommitOperationAdd(path_in_repo=n, path_or_fileobj=str(root / n)) for n in ("README.md", "NOTICE.md", "artifacts/ontology.json")])
        receipt["release_commit"] = result.oid
        save(receipt_path, receipt)
    if not any(t.name == "v1.0.0" for t in api.list_repo_refs(OWN_REPO, repo_type="dataset").tags):
        api.create_tag(OWN_REPO, repo_type="dataset", tag="v1.0.0", revision=receipt["release_commit"])
    api.update_repo_settings(OWN_REPO, repo_type="dataset", private=False)
    if not receipt.get("pr_url"):
        pr = out / "dynaword_pr"
        result = api.create_commit(TARGET, repo_type="dataset", parent_commit=audit["revision"], create_pr=True,
            commit_message="Add CC BY-SA 4.0 Open AGH Polish chemistry textbooks",
            commit_description=(out / "pr_description.md").read_text(encoding="utf-8"),
            operations=[CommitOperationAdd(path_in_repo=p.relative_to(pr).as_posix(), path_or_fileobj=str(p)) for p in files(pr)])
        receipt.update(pr_url=result.pr_url, pr_commit=result.oid)
        save(receipt_path, receipt)
    print(json.dumps(receipt, indent=2), flush=True)


def audit(out):
    from huggingface_hub import HfApi, hf_hub_download
    from huggingface_hub.utils import disable_progress_bars
    disable_progress_bars()
    api = HfApi(token=False)
    receipt = read(out / "publication.json")
    info = api.dataset_info(OWN_REPO)
    if info.private or info.sha != receipt["release_commit"]:
        raise ValueError("Release visibility/revision mismatch")
    if not any(t.name == "v1.0.0" and t.target_commit == info.sha for t in api.list_repo_refs(OWN_REPO, repo_type="dataset").tags):
        raise ValueError("Tag mismatch")
    number = int(receipt["pr_url"].rsplit("/", 1)[-1])
    discussion = api.get_discussion_details(TARGET, number, repo_type="dataset")
    pr_info = api.dataset_info(TARGET, revision=f"refs/pr/{number}")
    if not discussion.is_pull_request or pr_info.sha != receipt["pr_commit"]:
        raise ValueError("PR identity/revision mismatch")
    verified = []
    for repo, revision, root in ((OWN_REPO, info.sha, out / "hf_repo"), (TARGET, pr_info.sha, out / "dynaword_pr")):
        for path in files(root):
            name = path.relative_to(root).as_posix()
            remote = Path(hf_hub_download(repo, name, repo_type="dataset", revision=revision, token=False, cache_dir=str(out / "remote_verification_cache")))
            if sha(remote.read_bytes()) != sha(path.read_bytes()):
                raise ValueError("Remote checksum mismatch: " + name)
            verified.append({"repository": repo, "revision": revision, "path": name, "sha256": sha(remote.read_bytes())})
    base = (out / "target_sources.py").read_text(encoding="utf-8")
    if (out / "dynaword_pr/src/sources.py").read_text(encoding="utf-8") != registry(base):
        raise ValueError("Unrelated registry changes")
    result = {"observed_at": now(), "source_revision": info.sha, "pr_url": receipt["pr_url"], "pr_status": discussion.status,
        "pr_revision": pr_info.sha, "target_main_revision": api.dataset_info(TARGET).sha, "verified_files": verified}
    save(out / "publication_audit.json", result)
    print(json.dumps({**result, "verified_files": len(verified)}, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("command", choices=["verify", "publish", "audit"])
    args = parser.parse_args()
    globals()[args.command](args.output)
