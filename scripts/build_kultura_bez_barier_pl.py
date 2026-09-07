#!/usr/bin/env python3
"""Acquire, normalize, validate and publish Polish Kultura bez Barier publications."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import pprint
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from urllib.parse import unquote

import pdfplumber
import requests
from pypdf import PdfReader

CATALOG = "https://kulturabezbarier.org/publikacje/"
SOURCE = "kultura_bez_barier_pl"
OWN_REPO = "PiotrSty/kultura-bez-barier-pl"
TARGET = "SlayerLab/polish-dynaword"
LICENSE = "CC-BY-SA-3.0"
LICENSE_URL = "https://creativecommons.org/licenses/by-sa/3.0/"
AUTHOR = "Fundacja Kultury bez Barier"
FIELDS = ["id", "text", "source", "added", "created", "token_count", "license", "author"]
UA = "KulturaBezBarierTextResearch/1.0 (PiotrSty; open Polish publication corpus)"

PUBLICATIONS = (
    ("checklisty_warsztaty_kulinarne", "Checklisty - warsztaty kulinarne dla osob z niepelnosprawnosciami", "https://kulturabezbarier.org/wp-content/uploads/2024/04/Checklisty-%E2%80%94-warsztaty-kulinarne-dla-osob-z-niepelnosprawnosciami.pdf"),
    ("model_dostepnej_kultury_2023", "Model dostepnej kultury", "https://kulturabezbarier.org/wp-content/uploads/2024/04/Model_Dostepnej_Kultury_2023.pdf"),
    ("audiodeskrypcja_obrazow", "Audiodeskrypcja obrazow - publikacja na 10 lat wspolnej pracy", "https://kulturabezbarier.org/wp-content/uploads/2022/04/Audiodeskrypcja-obrazo%CC%81w_publikacja-na-10-lat-wspo%CC%81lnej-pracy.pdf"),
    ("jak_udostepniac_kulture", "Jak udostepniac kulture osobom z niepelnosprawnosciami", "https://kulturabezbarier.org/wp-content/uploads/2019/12/Publikacja_FKBB.pdf"),
    ("podsumowanie_wizyt_studyjnych", "Podsumowanie wizyt studyjnych", "https://kulturabezbarier.org/wp-content/uploads/2019/12/Podsumowanie.pdf"),
    ("przewodnik_po_dostepnosci", "Przewodnik po dostepnosci", "https://kulturabezbarier.org/wp-content/uploads/2019/12/Otwarci-dla-wszystkich-publikacja-www.pdf"),
    ("paszport_do_sztuki", "Paszport do sztuki - dziennik z wyprawy", "https://kulturabezbarier.org/wp-content/uploads/2019/12/Gietko_FKBB_Paszport_do_sztuki_publikacja_do_netu.pdf"),
    ("filmolekcje", "Filmolekcje dla kazdego", "https://kulturabezbarier.org/wp-content/uploads/2019/12/Filmolekcje-2.pdf"),
    ("abc_gosc_niepelnosprawny", "ABC Gosc niepelnosprawny w muzeum", "https://kulturabezbarier.org/wp-content/uploads/2019/12/ABC_Gosc_niepelnosprawny_lekki.pdf"),
    ("abc_gosc_niepelnosprawny_cz2", "ABC Gosc niepelnosprawny w muzeum cz. 2", "https://kulturabezbarier.org/wp-content/uploads/2019/12/ABC_Gosc_niepelnosprawny_cz2.pdf"),
    ("audiodeskrypcja_zasady", "Audiodeskrypcja - zasady tworzenia", "https://kulturabezbarier.org/wp-content/uploads/2019/12/Audiodeskrypcja-zasady-tworzenia.pdf"),
    ("napisy_dla_nieslyszacych", "Napisy dla osob nieslyszacych i slaboslyszacych - zasady tworzenia", "https://kulturabezbarier.org/wp-content/uploads/2019/12/Napisy-dla-nieslyszacych_zasady-tworzenia_2019.pdf"),
)

AUTHORS = {
    "checklisty_warsztaty_kulinarne": "Julianna Matuszewska",
    "model_dostepnej_kultury_2023": "Fundacja Kultury bez Barier; Robert Więckowski",
    "audiodeskrypcja_obrazow": "Robert Więckowski; Anna Żórawska; Fundacja Kultury bez Barier",
    "jak_udostepniac_kulture": "Fundacja Kultury bez Barier",
    "podsumowanie_wizyt_studyjnych": "Fundacja Kultury bez Barier",
    "przewodnik_po_dostepnosci": "Monika Dubiel; Izabela Sopalska-Rybak; Aleksandra Szorc; Aleksandra Sztajerwald; Robert Więckowski",
    "paszport_do_sztuki": "Fundacja Kultury bez Barier",
    "filmolekcje": "Monika Dubiel; Aleksandra Szorc",
    "napisy_dla_nieslyszacych": "Izabela Künstler; Urszula Butkiewicz",
}

RIGHTS_CONFLICTS = {
    "abc_gosc_niepelnosprawny": "PDF copyright notice names Narodowy Instytut Muzealnictwa i Ochrony Zbiorów",
    "abc_gosc_niepelnosprawny_cz2": "PDF identifies the NIMOZ training series and foundation as a project partner",
}

LEGACY_GARBLE_WORDS = (
    "widad", "dad", "mied", "byd", "kooca", "przestrzeo", "poznad", "zostad",
    "współgrad", "uwzględnid", "zamieścid",
)


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(value).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_lines(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def read_lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def normalize(text):
    text = unicodedata.normalize("NFKC", text).replace("\u00ad", "").replace("\u200b", "")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    lines = [re.sub(r"[ \t\xa0]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def http_get(url, attempts=5):
    response = None
    for attempt in range(attempts):
        response = requests.get(url, timeout=(20, 120), headers={"User-Agent": UA, "Accept-Language": "pl"})
        if response.status_code not in (429, 500, 502, 503, 504):
            response.raise_for_status()
            return response
        time.sleep(2 ** attempt)
    response.raise_for_status()


def catalog_license_evidence(html):
    text = normalize(re.sub(r"<[^>]+>", " ", html))
    compact = " ".join(text.split())
    required = ("publikacje autorstwa Fundacji Kultury bez Barier", "CC BY-SA 3.0")
    if not all(phrase.casefold() in compact.casefold() for phrase in required):
        raise ValueError("catalogue-level authorship/license declaration not found")
    if re.search(r"(?i)CC\s*BY[- ]NC|licenses/by-nc", compact):
        raise ValueError("noncommercial marker found in catalogue")
    marker = compact.casefold().index("publikacje autorstwa")
    return compact[marker:marker + 700]


def pdf_created(metadata):
    raw = str((metadata or {}).get("/CreationDate", ""))
    match = re.search(r"D:(\d{4})(\d{2})(\d{2})", raw)
    if match:
        year, month, day = map(int, match.groups())
        if 1990 <= year <= datetime.now().year and 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"
    return "unknown"


def extract_pdf(path):
    reader = PdfReader(path)
    pages = []
    failures = []
    with pdfplumber.open(path) as document:
        for index, page in enumerate(document.pages, 1):
            try:
                pages.append(normalize(page.extract_text() or ""))
            except Exception as error:
                pages.append("")
                failures.append({"page": index, "error": str(error)})
    return {
        "page_count": len(reader.pages),
        "metadata": {str(k): str(v) for k, v in (reader.metadata or {}).items()},
        "pages": pages,
        "page_failures": failures,
    }


def acquire(out):
    if (out / "inventory.json").exists():
        raise ValueError("inventory exists; use a fresh output for a new immutable acquisition")
    out.mkdir(parents=True, exist_ok=True)
    raw_dir = out / "raw"
    raw_dir.mkdir(exist_ok=True)
    catalog = http_get(CATALOG)
    (out / "catalog.html").write_bytes(catalog.content)
    declaration = catalog_license_evidence(catalog.text)
    normalized_catalog = unicodedata.normalize("NFC", unquote(catalog.text)).casefold()
    records, failures = [], []
    for index, (slug, title, url) in enumerate(PUBLICATIONS, 1):
        try:
            normalized_name = unicodedata.normalize("NFC", unquote(Path(url).name)).casefold()
            if normalized_name not in normalized_catalog:
                raise ValueError("allowlisted URL not found in catalogue HTML")
            response = http_get(url)
            if not response.content.startswith(b"%PDF"):
                raise ValueError("response is not a PDF")
            path = raw_dir / f"{slug}.pdf"
            path.write_bytes(response.content)
            extracted = extract_pdf(path)
            records.append({"slug": slug, "title": title, "url": url, "observed_at": now(),
                "pdf_sha256": sha(response.content), "bytes": len(response.content), **extracted})
        except Exception as error:
            failures.append({"slug": slug, "url": url, "error": str(error)})
        print(f"Acquired {index}/{len(PUBLICATIONS)}; failures={len(failures)}", flush=True)
        time.sleep(0.2)
    save(out / "inventory.json", {"catalog_url": CATALOG, "catalog_sha256": sha(catalog.content),
        "catalog_observed_at": now(), "catalog_license_evidence": declaration,
        "license_scope_note": "Catalogue-level declaration adjacent to the linked publications; not a per-PDF embedded assertion.",
        "selected_publications": [list(item) for item in PUBLICATIONS], "records": records, "failures": failures,
        "explicit_exclusions": ["German Model edition", "PNG/SVG pictograms", "Igor comic", "duplicate DOCX rendition"]})
    if failures:
        raise ValueError("acquisition incomplete; inspect inventory failures")


def repair_wrapped_text(pages):
    output = []
    for page in pages:
        lines = [line for line in page.splitlines() if not re.fullmatch(r"\s*\d{1,3}\s*", line)]
        text = "\n".join(lines)
        text = re.sub(r"(?<=\w)-\n(?=[a-ząćęłńóśźż])", "", text)
        text = re.sub(r"(?<![.!?:;])\n(?=[a-ząćęłńóśźż])", " ", text)
        output.append(normalize(text))
    return normalize("\n\n".join(part for part in output if part))


def credit_lines(pages):
    selected = pages[:3] + pages[-3:]
    pattern = re.compile(r"(?i)(?:^|\b)(autor(?:zy|ka|ki)?|teksty|opracowanie|redakcja|publikację wspólnie stworzyli|copyright|©)(?:\b|:)")
    return [normalize(line)[:500] for page in selected for line in page.splitlines() if pattern.search(line)][:40]


def near_dedup(rows):
    from datasketch import MinHash, MinHashLSH
    index = MinHashLSH(threshold=0.8, num_perm=128)
    features, kept, removed = {}, [], []
    for row in rows:
        words = re.findall(r"\w+", row["text"].casefold())
        shingles = {" ".join(words[i:i + 5]).encode() for i in range(max(0, len(words) - 4))}
        sig = MinHash(num_perm=128, seed=1)
        if not shingles:
            kept.append(row)
            continue
        sig.update_batch(sorted(shingles))
        for candidate in sorted(index.query(sig)):
            score = len(shingles & features[candidate]) / len(shingles | features[candidate])
            if score >= 0.9:
                removed.append({"id": row["id"], "duplicate_of": candidate, "jaccard": score})
                break
        else:
            kept.append(row)
            features[row["id"]] = shingles
            index.insert(row["id"], sig)
    return kept, removed


def build(out):
    import pyarrow as pa
    import pyarrow.parquet as pq
    import tiktoken
    from langid.langid import LanguageIdentifier, model
    inventory = load(out / "inventory.json")
    if inventory["failures"] or len(inventory["records"]) != len(PUBLICATIONS):
        raise ValueError("cannot build from incomplete inventory")
    encoder = tiktoken.get_encoding("cl100k_base")
    identifier = LanguageIdentifier.from_modelstring(model, norm_probs=True)
    identifier.set_languages(["pl", "en", "de", "cs", "sk", "uk", "ru"])
    rows, attribution, decisions, seen = [], [], [], {}
    pii = Counter()
    added = inventory["catalog_observed_at"][:10]
    for record in sorted(inventory["records"], key=lambda item: item["slug"]):
        path = out / "raw" / f"{record['slug']}.pdf"
        if sha(path.read_bytes()) != record["pdf_sha256"]:
            raise ValueError("raw PDF checksum mismatch: " + record["slug"])
        body = repair_wrapped_text(record["pages"])
        letters = len(re.findall(r"[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]", body))
        garbled_controls = sum(0x80 <= ord(char) <= 0x9F or ord(char) == 0xFFFD for char in body)
        combining_marks = sum(unicodedata.combining(char) > 0 for char in body)
        legacy_garble_words = sum(body.casefold().count(word.casefold()) for word in LEGACY_GARBLE_WORDS)
        reason = ""
        if record["slug"] in RIGHTS_CONFLICTS:
            reason = "rights_or_authorship_conflict"
        elif record["page_failures"]:
            reason = "page_extraction_failure"
        elif garbled_controls:
            reason = "text_extraction_garbled"
        elif combining_marks:
            reason = "text_extraction_split_diacritics"
        elif legacy_garble_words > 10:
            reason = "text_extraction_legacy_font_mapping"
        elif len(body) < 1000:
            reason = "too_little_extractable_text"
        elif letters / max(len(body), 1) < 0.55:
            reason = "low_letter_ratio"
        language, confidence = identifier.classify(body[:20000]) if body else ("unknown", 0.0)
        if not reason and language != "pl" and confidence >= 0.98:
            reason = "non_polish"
        body, emails = re.subn(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[REDACTED:EMAIL]", body)
        body, phones = re.subn(r"(?i)(?:\btelefon|\btel\.)\s*:?[ \t]*(?:\+48[ \t]*)?\d(?:[ .-]?\d){8}\b", "[REDACTED:PHONE]", body)
        pii.update(email=emails, labelled_phone=phones)
        text = body
        key = " ".join(text.casefold().split())
        if not reason and key in seen:
            reason = "normalized_duplicate"
        row_id = SOURCE + "_" + record["slug"]
        decisions.append({"id": row_id, "selected": not bool(reason), "reason": reason or "include",
            "pdf_sha256": record["pdf_sha256"], "page_count": record["page_count"],
            "language": language, "language_confidence": float(confidence), "garbled_controls": garbled_controls,
            "combining_marks": combining_marks, "legacy_garble_words": legacy_garble_words,
            "rights_conflict": RIGHTS_CONFLICTS.get(record["slug"])})
        if reason:
            continue
        seen[key] = row_id
        created = pdf_created(record["metadata"])
        author = AUTHORS[record["slug"]]
        rows.append({"id": row_id, "text": text, "source": SOURCE, "added": added,
            "created": created, "token_count": len(encoder.encode_ordinary(text)), "license": LICENSE, "author": author})
        attribution.append({"id": row_id, "slug": record["slug"], "title": record["title"], "url": record["url"], "publisher": AUTHOR,
            "author": author, "author_basis": "Official catalogue authorship statement plus PDF metadata or publication credit lines where available.",
            "pdf_metadata": record["metadata"], "credit_lines": credit_lines(record["pages"]),
            "created": created, "created_semantics": "PDF CreationDate metadata when valid; otherwise unknown",
            "license": LICENSE, "license_url": LICENSE_URL, "license_evidence_url": CATALOG,
            "license_scope_note": inventory["license_scope_note"], "pdf_sha256": record["pdf_sha256"],
            "text_sha256": sha(text.encode()), "page_count": record["page_count"], "language": language,
            "language_confidence": float(confidence), "transformations": ["pdfplumber page text extraction", "page-number removal",
                "line-wrap and hyphen repair", "Unicode and whitespace normalization", "email and labelled-phone redaction"]})
    rows, near_removed = near_dedup(rows)
    removed = {item["id"]: item for item in near_removed}
    for decision in decisions:
        if decision["id"] in removed:
            decision.update(selected=False, reason="near_duplicate", duplicate_of=removed[decision["id"]]["duplicate_of"], jaccard=removed[decision["id"]]["jaccard"])
    kept_ids = {row["id"] for row in rows}
    attribution = [item for item in attribution if item["id"] in kept_ids]
    root = out / "hf_repo"
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "artifacts/raw").mkdir(parents=True, exist_ok=True)
    schema = pa.schema([(field, pa.int64() if field == "token_count" else pa.string()) for field in FIELDS])
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), root / "data/train-00000-of-00001.parquet", compression="zstd")
    write_lines(root / "artifacts/attribution.jsonl", attribution)
    write_lines(root / "artifacts/decisions.jsonl", decisions)
    samples = sorted(rows, key=lambda row: sha(("sample:" + row["id"]).encode()))[:12]
    write_lines(root / "artifacts/sample.jsonl", samples)
    inventory_copy = dict(inventory)
    inventory_copy["records"] = [{k: v for k, v in item.items() if k != "pages"} for item in inventory["records"]]
    save(root / "artifacts/inventory.json", inventory_copy)
    catalog_snapshot = out / "catalog.html"
    if sha(catalog_snapshot.read_bytes()) != inventory["catalog_sha256"]:
        raise ValueError("catalogue snapshot checksum mismatch")
    shutil.copy2(catalog_snapshot, root / "artifacts/catalog.html")
    for record in inventory["records"]:
        shutil.copy2(out / "raw" / f"{record['slug']}.pdf", root / "artifacts/raw" / f"{record['slug']}.pdf")
    stats = {"discovered": len(PUBLICATIONS), "acquired": len(inventory["records"]), "kept": len(rows),
        "rejected": len(decisions) - len(rows), "tokens": sum(row["token_count"] for row in rows),
        "characters": sum(len(row["text"]) for row in rows), "pages": sum(item["page_count"] for item in attribution),
        "sample_count": len(samples), "author_coverage": sum(bool(row["author"]) for row in rows) / len(rows) if rows else 0,
        "unknown_created": sum(row["created"] == "unknown" for row in rows), "added": added}
    qa = {"license_gate": "official catalogue-level CC BY-SA 3.0 declaration; per-PDF embedded notices not required or asserted",
        "pii_pattern_matches": dict(pii), "exact_normalized_dedup": True,
        "near_dedup": {"method": "seeded MinHash 128 / LSH 0.8 candidates / exact 5-word Jaccard >= 0.9", "removed": near_removed},
        "cross_source_dedup": "pending target integration", "benchmark_overlap": "pending",
        "limitations": ["catalogue-level rights statement requires maintainer/legal interpretation for each linked publication",
            "PDF extraction can flatten tables and omit images", "embedded third-party quotations require review",
            "pattern checks are not comprehensive de-identification", "text novelty and training benefit are not asserted"]}
    save(root / "artifacts/stats.json", stats)
    save(root / "artifacts/qa.json", qa)
    run = {"id": "run:" + sha({"code": sha(Path(__file__).read_bytes()), "catalog": inventory["catalog_sha256"],
        "pdfs": [item["pdf_sha256"] for item in inventory["records"]]}), "started_at": inventory["catalog_observed_at"],
        "finished_at": now(), "code_sha256": sha(Path(__file__).read_bytes()), "success": True,
        "inputs": {"catalog_sha256": inventory["catalog_sha256"], "pdf_sha256": [item["pdf_sha256"] for item in inventory["records"]]}, "stats": stats}
    save(root / "artifacts/run.json", run)
    print(json.dumps(stats, ensure_ascii=False, indent=2), flush=True)


def checksums(root):
    excluded = {"artifacts/checksums.json", "artifacts/ontology.json", "artifacts/validation_run.json"}
    return {path.relative_to(root).as_posix(): sha(path.read_bytes()) for path in sorted(root.rglob("*"))
            if path.is_file() and path.relative_to(root).as_posix() not in excluded}


def registry(base):
    tree = ast.parse(base)
    node = next(item.value for item in tree.body if isinstance(item, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "SOURCES" for target in item.targets))
    if SOURCE in ast.literal_eval(node):
        raise ValueError("source already registered")
    entry = {"file_key": SOURCE, "pretty": "Kultura bez Barier - Polish accessibility guides",
        "license": LICENSE, "license_spdx": LICENSE,
        "traceable": "Official publication catalogue declares the linked foundation-authored materials CC BY-SA 3.0; raw PDFs, catalogue HTML, URLs, hashes, attribution and exclusions are preserved.",
        "upstream": CATALOG, "provenance": "Pinned PiotrSty/kultura-bez-barier-pl snapshot acquired from the official Fundacja Kultury bez Barier publication catalogue.",
        "domain": "instructional/cultural-accessibility", "created": "per-record PDF metadata or unknown", "is_ocr": False, "custom_datasheet": True}
    offset = sum(len(line) for line in base.splitlines(keepends=True)[:node.lineno - 1]) + node.col_offset + 1
    return base[:offset] + "\n    " + repr(SOURCE) + ": " + pprint.pformat(entry, width=96, sort_dicts=False).replace("\n", "\n    ") + "," + base[offset:]


def verify_core(out):
    import pyarrow.parquet as pq
    root = out / "hf_repo"
    table = pq.read_table(root / "data/train-00000-of-00001.parquet")
    rows = table.to_pylist()
    stats = load(root / "artifacts/stats.json")
    attribution = read_lines(root / "artifacts/attribution.jsonl")
    decisions = read_lines(root / "artifacts/decisions.jsonl")
    sample = read_lines(root / "artifacts/sample.jsonl")
    assert table.column_names == FIELDS
    assert len(rows) == stats["kept"] == len(attribution)
    assert len(decisions) == stats["discovered"]
    assert sum(bool(item["selected"]) for item in decisions) == stats["kept"]
    assert sum(row["token_count"] for row in rows) == stats["tokens"]
    assert {row["id"] for row in rows} == {item["id"] for item in attribution}
    assert all(row["source"] == SOURCE and row["license"] == LICENSE and row["author"] for row in rows)
    assert not ({item["slug"] for item in attribution} & set(RIGHTS_CONFLICTS))
    assert all(not re.search(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", row["text"]) for row in rows)
    by_id = {row["id"]: row for row in rows}
    assert len(sample) == min(12, len(rows)) and all(by_id[item["id"]] == item for item in sample)
    if (root / "artifacts/checksums.json").exists():
        for name, digest in load(root / "artifacts/checksums.json").items():
            assert sha((root / name).read_bytes()) == digest
    return stats


def prepare(out, target_revision):
    root = out / "hf_repo"
    (root / "src").mkdir(exist_ok=True)
    shutil.copy2(Path(__file__), root / "src/build_kultura_bez_barier_pl.py")
    shutil.copy2(Path(__file__).with_name("kultura_bez_barier_requirements.txt"), root / "src/requirements.txt")
    shutil.copy2(Path(__file__).with_name("test_kultura_bez_barier_contribution.py"), root / "src/test_kultura_bez_barier_contribution.py")
    stats = load(root / "artifacts/stats.json")
    notice = f"""# Notice and attribution\n\nSource: {CATALOG}\n\nThe official catalogue describes the linked publications as authored by Fundacja Kultury bez Barier and states that they are made available under CC BY-SA 3.0. The catalogue HTML, raw PDFs, source URLs and SHA-256 digests are preserved. This is catalogue-level evidence; an embedded per-PDF license assertion is not claimed.\n\nDataset transformations: text extraction, removal of page-number-only lines, line-wrap repair, Unicode/whitespace normalization, limited PII-pattern redaction, exact and near deduplication. Images are not included in the training text. Attribution and a modification notice must be preserved under CC BY-SA 3.0.\n"""
    (root / "NOTICE.md").write_text(notice, encoding="utf-8")
    readme = f"""---\nlicense: cc-by-sa-3.0\nlanguage:\n- pl\ntask_categories:\n- text-generation\nconfigs:\n- config_name: default\n  data_files:\n  - split: train\n    path: data/train-00000-of-00001.parquet\n---\n\n# Kultura bez Barier PL\n\nPolish text extracted from openly published accessibility guides by Fundacja Kultury bez Barier.\n\n- Input publications: {stats['discovered']}\n- Retained records: {stats['kept']}\n- Extracted pages: {stats['pages']}\n- Tokens: {stats['tokens']:,} (`cl100k_base` proxy)\n- License evidence: catalogue-level CC BY-SA 3.0 declaration\n- Author coverage: {stats['author_coverage']:.1%}\n\nSee `NOTICE.md` and `artifacts/` for the source inventory, raw PDFs, attribution, selection decisions, QA, checksums, samples and Slayer ontology manifest.\n\n## Limitations\n\nThe source catalogue provides the licensing statement; an embedded statement was not found or required for every PDF. Maintainer/legal review of that scope remains appropriate. PDF extraction may flatten tables and omit visual meaning. Cross-source DynaWord deduplication, benchmark-overlap checks and controlled training ablations remain pending.\n"""
    (root / "README.md").write_text(readme, encoding="utf-8")
    digest_map = checksums(root)
    save(root / "artifacts/checksums.json", digest_map)
    verified_stats = verify_core(out)
    validation = {"id": "run:" + sha({"checksums": digest_map, "target": target_revision}), "started_at": now(),
        "finished_at": now(), "success": True, "protocol": "dataset-contract-and-checksum-validation-v1",
        "target_main_revision": target_revision, "stats": verified_stats}
    save(root / "artifacts/validation_run.json", validation)
    build_run = load(root / "artifacts/run.json")
    check_id = "evidence:checksums:" + sha(digest_map)
    qa = load(root / "artifacts/qa.json")
    qa_id = "evidence:qa:" + sha(qa)
    dataset_version = "version:dataset:" + sha(digest_map)
    source_version = "version:source:" + sha({"pdfs": build_run["inputs"]["pdf_sha256"], "catalog": build_run["inputs"]["catalog_sha256"]})
    ontology = {"schema": "slayer-research-ontology-profile-v1", "objects": [
            {"id": "object:source:kultura-bez-barier", "type": "Source"}, {"id": "object:dataset:kultura-bez-barier-pl", "type": "Dataset"}],
        "versions": [{"id": source_version, "object": "object:source:kultura-bez-barier", "content_address": source_version.rsplit(":", 1)[-1]},
            {"id": dataset_version, "object": "object:dataset:kultura-bez-barier-pl", "content_address": dataset_version.rsplit(":", 1)[-1]}],
        "protocols": [{"id": "protocol:pdf-text-v1", "procedure": "allowlist, pdfplumber extraction, normalization, PII patterns, exact and seeded near dedup"},
            {"id": "protocol:contract-v1", "procedure": "schema, checksum, sample, rights-evidence and ontology contract checks"}],
        "runs": [{"id": build_run["id"], "protocol": "protocol:pdf-text-v1", "success": True,
            "started_at": build_run["started_at"], "finished_at": build_run["finished_at"]}, validation],
        "evidence": [{"id": check_id, "observation_type": "checksums", "payload": digest_map, "produced_by": validation["id"]},
            {"id": qa_id, "observation_type": "qa", "payload": qa, "produced_by": build_run["id"]}],
        "claims": [{"id": "claim:replayable", "statement": "The retained dataset files replay from the pinned catalogue and PDF snapshot under the published protocol.",
            "supported_by": [check_id], "falsification_condition": "A published checksum differs or the builder cannot reproduce retained text from the pinned raw PDFs."},
            {"id": "claim:rights-qualified", "statement": "The official catalogue presents the linked foundation-authored publications as CC BY-SA 3.0; per-PDF embedded licensing is not asserted.",
            "supported_by": [qa_id], "falsification_condition": "The pinned catalogue lacks that declaration or a selected file is outside its demonstrated scope."}],
        "actors": [{"id": "actor:piotrsty", "type": "Contributor"}, {"id": "actor:fundacja-kultury-bez-barier", "type": "Organization"},
            {"id": "actor:codex", "type": "Agent"}],
        "relations": [{"source": dataset_version, "predicate": "DERIVED_FROM", "target": source_version},
            {"source": dataset_version, "predicate": "GENERATED_BY", "target": build_run["id"]},
            {"source": dataset_version, "predicate": "VALIDATED_AGAINST", "target": validation["id"]}],
        "pending": ["cross-source deduplication", "benchmark contamination check", "maintainer/legal review of catalogue-level license scope", "controlled training ablation"]}
    save(root / "artifacts/ontology.json", ontology)


def verify(out):
    stats = verify_core(out)
    root = out / "hf_repo"
    manifest = load(root / "artifacts/ontology.json")
    evidence_ids = {item["id"] for item in manifest["evidence"]}
    assert all(item["falsification_condition"] and set(item["supported_by"]) <= evidence_ids for item in manifest["claims"])
    assert len(manifest["runs"]) >= 2 and all(item["success"] for item in manifest["runs"])
    assert any(item["predicate"] == "VALIDATED_AGAINST" for item in manifest["relations"])
    print(json.dumps({"verified": True, **stats}, ensure_ascii=False, indent=2), flush=True)


def hf_token():
    value = os.environ.get("HF_TOKEN")
    if not value and os.name == "nt":
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value = winreg.QueryValueEx(key, "HF_TOKEN")[0]
    if not value or not value.startswith("hf_"):
        raise ValueError("HF_TOKEN unavailable")
    return value


def all_files(root):
    return [path for path in sorted(root.rglob("*")) if path.is_file() and "__pycache__" not in path.parts and ".pytest_cache" not in path.parts]


def assemble_pr(out, base, source_commit):
    root = out / "hf_repo"
    pr = out / "dynaword_pr"
    data = pr / "data" / SOURCE
    data.mkdir(parents=True, exist_ok=True)
    (pr / "src").mkdir(exist_ok=True)
    (pr / "artifacts").mkdir(exist_ok=True)
    shutil.copy2(root / "data/train-00000-of-00001.parquet", data / f"{SOURCE}.parquet")
    for name in ("attribution.jsonl", "decisions.jsonl", "sample.jsonl", "stats.json", "qa.json"):
        shutil.copy2(root / "artifacts" / name, data / f"{SOURCE}.{name}")
    shutil.copy2(root / "NOTICE.md", data / "NOTICE.md")
    shutil.copy2(root / "README.md", data / f"{SOURCE}.md")
    shutil.copy2(root / "artifacts/ontology.json", pr / f"artifacts/{SOURCE}_ontology_manifest.json")
    shutil.copy2(Path(__file__), pr / "src/build_kultura_bez_barier_pl.py")
    shutil.copy2(Path(__file__).with_name("test_kultura_bez_barier_contribution.py"), pr / "src/test_kultura_bez_barier_contribution.py")
    (pr / "src/sources.py").write_text(registry(base), encoding="utf-8")
    stats = load(root / "artifacts/stats.json")
    description = f"""## Add Polish cultural-accessibility guides\n\nAdds `{SOURCE}`: **{stats['kept']} records, {stats['pages']} extracted pages and {stats['tokens']:,} measured `cl100k_base` proxy tokens** from the official Fundacja Kultury bez Barier publication catalogue.\n\nSource dataset: https://huggingface.co/datasets/{OWN_REPO}/tree/{source_commit}\n\n### Data sample\n\n- [{stats['sample_count']} complete deterministic sample records](https://huggingface.co/datasets/{OWN_REPO}/blob/{source_commit}/artifacts/sample.jsonl)\n- [Per-record attribution, URLs and rights evidence](https://huggingface.co/datasets/{OWN_REPO}/blob/{source_commit}/artifacts/attribution.jsonl)\n- [Selection decisions](https://huggingface.co/datasets/{OWN_REPO}/blob/{source_commit}/artifacts/decisions.jsonl)\n\n### Rights and method\n\nThe official catalogue describes these linked foundation-authored publications as CC BY-SA 3.0. The contribution preserves the catalogue HTML, raw PDFs, URLs, hashes, attribution and modification notice. This is catalogue-level evidence; it does not assert that every PDF embeds a separate license notice. Text was extracted with pdfplumber, normalized, checked for limited PII patterns, and exact/near-deduplicated within source.\n\n### Slayer ontology and remaining gates\n\nThe manifest separates content-addressed source/dataset Versions, processing and validation Protocols, executed Runs, Evidence, falsifiable Claims, Actors and typed lineage. Cross-source DynaWord deduplication, benchmark-overlap testing, legal interpretation of the catalogue-level scope and controlled training ablations remain pending. PDF extraction may flatten tables and omit visual meaning. This PR proposes a source, not a merged or stable release.\n"""
    (out / "pr_description.md").write_text(description, encoding="utf-8")
    return pr


def publish(out):
    from huggingface_hub import CommitOperationAdd, HfApi
    api = HfApi(token=hf_token())
    if api.whoami()["name"].casefold() != "piotrsty":
        raise ValueError("unexpected HF account")
    target = api.dataset_info(TARGET)
    registry_url = f"https://huggingface.co/datasets/{TARGET}/resolve/{target.sha}/src/sources.py"
    base = http_get(registry_url).content.decode("utf-8")
    discussions = list(api.get_repo_discussions(TARGET, repo_type="dataset"))
    if SOURCE in base or any("kultura bez barier" in item.title.casefold() for item in discussions):
        raise ValueError("source registration or proposal already exists")
    prepare(out, target.sha)
    verify(out)
    root = out / "hf_repo"
    receipt_path = out / "publication.json"
    receipt = load(receipt_path) if receipt_path.exists() else {}
    if not receipt:
        if api.repo_exists(OWN_REPO, repo_type="dataset"):
            raise ValueError("own HF repository already exists without this run receipt")
        api.create_repo(OWN_REPO, repo_type="dataset", private=True)
        receipt = {"source_repo": OWN_REPO, "target_main_revision": target.sha, "created_at": now()}
        save(receipt_path, receipt)
    if receipt["target_main_revision"] != target.sha:
        raise ValueError("target main changed since publication started; inspect before continuing")
    if not receipt.get("source_commit"):
        source_commit = api.create_commit(OWN_REPO, repo_type="dataset", commit_message="Add validated Kultura bez Barier Polish publications",
            operations=[CommitOperationAdd(path_in_repo=path.relative_to(root).as_posix(), path_or_fileobj=str(path)) for path in all_files(root)])
        receipt["source_commit"] = source_commit.oid
        save(receipt_path, receipt)
    source_revision = receipt["source_commit"]
    if not any(item.name == "v1.0.0" for item in api.list_repo_refs(OWN_REPO, repo_type="dataset").tags):
        api.create_tag(OWN_REPO, repo_type="dataset", tag="v1.0.0", revision=source_revision)
    api.update_repo_settings(OWN_REPO, repo_type="dataset", private=False)
    pr = assemble_pr(out, base, source_revision)
    subprocess.run([sys.executable, "-m", "pytest", "-q", str(pr / "src/test_kultura_bez_barier_contribution.py")], check=True)
    if not receipt.get("pr_url"):
        result = api.create_commit(TARGET, repo_type="dataset", parent_commit=target.sha, create_pr=True,
            commit_message="Add CC BY-SA 3.0 Polish cultural-accessibility guides",
            commit_description=(out / "pr_description.md").read_text(encoding="utf-8"),
            operations=[CommitOperationAdd(path_in_repo=path.relative_to(pr).as_posix(), path_or_fileobj=str(path)) for path in all_files(pr)])
        receipt.update(tag="v1.0.0", pr_url=result.pr_url, pr_commit=result.oid, published_at=now())
        save(receipt_path, receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2), flush=True)


def audit(out):
    from huggingface_hub import HfApi, hf_hub_download
    api = HfApi(token=False)
    receipt = load(out / "publication.json")
    info = api.dataset_info(OWN_REPO)
    if info.private or info.sha != receipt["source_commit"]:
        raise ValueError("source repo visibility or revision mismatch")
    if not any(item.name == receipt["tag"] and item.target_commit == info.sha for item in api.list_repo_refs(OWN_REPO, repo_type="dataset").tags):
        raise ValueError("release tag mismatch")
    number = int(receipt["pr_url"].rsplit("/", 1)[-1])
    discussion = api.get_discussion_details(TARGET, number, repo_type="dataset")
    pr_info = api.dataset_info(TARGET, revision=f"refs/pr/{number}")
    if not discussion.is_pull_request or pr_info.sha != receipt["pr_commit"]:
        raise ValueError("PR identity mismatch")
    checked = []
    for repo, revision, root in ((OWN_REPO, info.sha, out / "hf_repo"), (TARGET, pr_info.sha, out / "dynaword_pr")):
        for path in all_files(root):
            name = path.relative_to(root).as_posix()
            remote = Path(hf_hub_download(repo, name, repo_type="dataset", revision=revision, token=False,
                                          cache_dir=str(out / "remote_cache")))
            if sha(remote.read_bytes()) != sha(path.read_bytes()):
                raise ValueError("remote mismatch: " + name)
            checked.append({"repo": repo, "revision": revision, "path": name, "sha256": sha(remote.read_bytes())})
    result = {"observed_at": now(), "source_revision": info.sha, "pr_revision": pr_info.sha,
        "pr_status": discussion.status, "target_main_revision": api.dataset_info(TARGET).sha, "verified_files": checked}
    save(out / "publication_audit.json", result)
    shutil.rmtree(out / "remote_cache", ignore_errors=True)
    print(json.dumps({**result, "verified_files": len(checked)}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("command", choices=["acquire", "build", "verify", "publish", "audit"])
    arguments = parser.parse_args()
    globals()[arguments.command](arguments.output)
