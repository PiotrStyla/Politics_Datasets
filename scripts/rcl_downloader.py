#!/usr/bin/env python3
"""
Download public RCL legislative-process metadata and consultation PDFs.

The script intentionally uses only Python's standard library so it can run in a
fresh workspace. It crawls list pages from legislacja.gov.pl, finds each
project's "Konsultacje publiczne" catalog, records document metadata, and
optionally downloads matching PDFs.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import html
import json
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen


BASE_URL = "https://legislacja.gov.pl"
DEFAULT_USER_AGENT = "rcl-public-data-downloader/0.1 (+research; contact: local)"
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


@dataclass
class Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["Node"] = field(default_factory=list)
    text_parts: list[str] = field(default_factory=list)

    def text(self, sep: str = " ") -> str:
        parts = list(self.text_parts)
        for child in self.children:
            child_text = child.text(sep=sep)
            if child_text:
                parts.append(child_text)
        return normalize_space(sep.join(parts))

    def has_class(self, class_name: str) -> bool:
        return class_name in self.attrs.get("class", "").split()

    def find_all(self, predicate: Callable[["Node"], bool]) -> list["Node"]:
        found: list[Node] = []
        if predicate(self):
            found.append(self)
        for child in self.children:
            found.extend(child.find_all(predicate))
        return found

    def first(self, predicate: Callable[["Node"], bool]) -> "Node | None":
        if predicate(self):
            return self
        for child in self.children:
            match = child.first(predicate)
            if match is not None:
                return match
        return None


class TreeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("document")
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag.lower(), {k.lower(): v or "" for k, v in attrs})
        self.stack[-1].children.append(node)
        if tag.lower() not in VOID_TAGS:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for idx in range(len(self.stack) - 1, 0, -1):
            if self.stack[idx].tag == tag:
                del self.stack[idx:]
                break

    def handle_data(self, data: str) -> None:
        if data and data.strip():
            self.stack[-1].text_parts.append(data)


@dataclass
class Project:
    project_id: str
    title: str
    project_url: str
    applicant: str = ""
    number: str = ""
    number_url: str = ""
    created: str = ""
    modified: str = ""
    consultation_url: str = ""


@dataclass
class Document:
    project_id: str
    project_title: str
    project_number: str
    category_id: str
    category: str
    filename: str
    document_url: str
    author: str = ""
    created: str = ""
    local_path: str = ""
    sha256: str = ""
    bytes: int = 0
    downloaded: bool = False
    selected: bool = False
    error: str = ""


def normalize_space(value: str) -> str:
    value = html.unescape(value or "")
    value = value.replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def slugify(value: str, max_len: int = 90) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_text = re.sub(r"[^a-zA-Z0-9._-]+", "-", ascii_text).strip("-._")
    return (ascii_text[:max_len].strip("-._") or "item").lower()


def parse_html(source: str) -> Node:
    parser = TreeParser()
    parser.feed(source)
    parser.close()
    return parser.root


def fetch(url: str, user_agent: str, timeout: int, retries: int, sleep_s: float) -> bytes:
    last_error: Exception | None = None
    for attempt in range(1, retries + 2):
        try:
            request = Request(url, headers={"User-Agent": user_agent})
            with urlopen(request, timeout=timeout) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError) as exc:
            last_error = exc
            if attempt <= retries:
                time.sleep(sleep_s * attempt)
    raise RuntimeError(f"failed to fetch {url}: {last_error}") from last_error


def fetch_text(url: str, args: argparse.Namespace) -> str:
    raw = fetch(url, args.user_agent, args.timeout, args.retries, args.sleep)
    return raw.decode("utf-8", errors="replace")


def list_url(type_id: int, page: int, page_size: int, create_from: str = "", create_to: str = "") -> str:
    params: dict[str, str | int] = {"typeId": type_id, "pNumber": page, "pSize": page_size}
    if create_from:
        params["createDateFrom"] = create_from
    if create_to:
        params["createDateTo"] = create_to
    return f"{BASE_URL}/lista?{urlencode(params)}#list"


def extract_total_count(source: str) -> int | None:
    match = re.search(r"Lista projektów według wybranych kryteriów:\s*(\d+)", normalize_space(source))
    return int(match.group(1)) if match else None


def parse_list_page(source: str) -> list[Project]:
    root = parse_html(source)
    table = root.first(lambda n: n.tag == "table" and n.attrs.get("id") == "table")
    if table is None:
        return []
    projects: list[Project] = []
    rows = table.find_all(lambda n: n.tag == "tr")
    for row in rows:
        cells = [child for child in row.children if child.tag == "td"]
        if len(cells) < 5:
            continue
        title_link = cells[0].first(lambda n: n.tag == "a" and "/projekt/" in n.attrs.get("href", ""))
        if title_link is None:
            continue
        href = title_link.attrs["href"]
        project_id_match = re.search(r"/projekt/(\d+)", href)
        if not project_id_match:
            continue
        applicant_link = cells[1].first(lambda n: n.tag == "a")
        number_link = cells[2].first(lambda n: n.tag == "a")
        projects.append(
            Project(
                project_id=project_id_match.group(1),
                title=title_link.text(),
                project_url=urljoin(BASE_URL, href),
                applicant=applicant_link.text() if applicant_link else cells[1].text(),
                number=number_link.text() if number_link else cells[2].text(),
                number_url=urljoin(BASE_URL, number_link.attrs.get("href", "")) if number_link else "",
                created=cells[3].text(),
                modified=cells[4].text(),
            )
        )
    return projects


def find_consultation_url(project: Project, source: str) -> str:
    root = parse_html(source)
    links = root.find_all(lambda n: n.tag == "a" and f"/projekt/{project.project_id}/katalog/" in n.attrs.get("href", ""))
    for link in links:
        if "konsultacje publiczne" in link.text().lower():
            return urljoin(BASE_URL, link.attrs["href"].split("#")[0])
    return ""


def parse_documents(project: Project, source: str) -> list[Document]:
    root = parse_html(source)
    docs: list[Document] = []
    clearboxes = root.find_all(lambda n: n.tag == "div" and n.has_class("clearbox"))
    for box in clearboxes:
        category_node = box.first(lambda n: n.tag == "li" and n.has_class("childdir"))
        if category_node is None:
            continue
        category_id = category_node.attrs.get("id", "")
        category = category_node.text()
        category = re.sub(r"Data ostatniej modyfikacji:.*$", "", category).strip()
        doc_nodes = box.find_all(lambda n: n.tag == "li" and n.has_class("doc"))
        for doc_node in doc_nodes:
            link = doc_node.first(lambda n: n.tag == "a" and "/docs/" in n.attrs.get("href", ""))
            if link is None:
                continue
            full_text = doc_node.text()
            author = ""
            author_match = re.search(r"Autor dokumentu:\s*(.*?)(?:,\s*wprowadzony przez:|Data utworzenia:|$)", full_text)
            if author_match:
                author = normalize_space(author_match.group(1).strip(" ,"))
            created = ""
            date_match = re.search(r"Data utworzenia:\s*(\d{2}-\d{2}-\d{4})", full_text)
            if date_match:
                created = date_match.group(1)
            docs.append(
                Document(
                    project_id=project.project_id,
                    project_title=project.title,
                    project_number=project.number,
                    category_id=category_id,
                    category=category,
                    filename=link.text(),
                    document_url=urljoin(BASE_URL, link.attrs["href"]),
                    author=author,
                    created=created,
                )
            )
    return docs


def document_matches(doc: Document, keywords: Iterable[str], all_docs: bool) -> bool:
    if all_docs:
        return True
    haystack = f"{doc.category} {doc.filename}".lower()
    return any(keyword.lower() in haystack for keyword in keywords)


def safe_filename(filename: str, fallback_url: str) -> str:
    parsed_name = Path(urlparse(fallback_url).path).name
    name = filename or parsed_name or "document.pdf"
    stem = slugify(Path(name).stem, max_len=100)
    suffix = Path(name).suffix.lower() or Path(parsed_name).suffix.lower() or ".pdf"
    if not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
        suffix = ".pdf"
    return f"{stem}{suffix}"


def download_document(doc: Document, output_dir: Path, args: argparse.Namespace) -> None:
    project_dir = output_dir / "pdf" / f"{doc.project_id}_{slugify(doc.project_number or doc.project_title, 50)}"
    category_dir = project_dir / f"{doc.category_id}_{slugify(doc.category, 60)}"
    category_dir.mkdir(parents=True, exist_ok=True)
    target = category_dir / safe_filename(doc.filename, doc.document_url)
    if target.exists() and not args.overwrite:
        raw = target.read_bytes()
    else:
        raw = fetch(doc.document_url, args.user_agent, args.timeout, args.retries, args.sleep)
        target.write_bytes(raw)
        time.sleep(args.sleep)
    doc.local_path = str(target)
    doc.sha256 = hashlib.sha256(raw).hexdigest()
    doc.bytes = len(raw)
    doc.downloaded = True


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    with temporary_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temporary_path.replace(path)


def append_jsonl(path: Path, rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    temporary_path.replace(path)


def dataclass_dict(obj: object) -> dict[str, object]:
    return dict(vars(obj))


def write_outputs(output_dir: Path, projects: list[Project], documents: list[Document]) -> None:
    project_fields = list(vars(Project("", "", "")).keys())
    document_fields = list(vars(Document("", "", "", "", "", "", "")).keys())
    write_csv(output_dir / "projects.csv", [dataclass_dict(p) for p in projects], project_fields)
    write_csv(output_dir / "documents.csv", [dataclass_dict(d) for d in documents], document_fields)
    append_jsonl(output_dir / "projects.jsonl", (dataclass_dict(p) for p in projects))
    append_jsonl(output_dir / "documents.jsonl", (dataclass_dict(d) for d in documents))


def write_checkpoint(
    output_dir: Path,
    projects: list[Project],
    documents: list[Document],
    processed_project_ids: set[str],
    complete: bool,
) -> None:
    write_outputs(output_dir, projects, documents)
    state = {
        "version": "0.1",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "complete": complete,
        "projects_discovered": len(projects),
        "projects_processed": len(processed_project_ids),
        "documents_found": len(documents),
        "processed_project_ids": sorted(processed_project_ids),
    }
    checkpoint_path = output_dir / "checkpoint.json"
    temporary_path = checkpoint_path.with_suffix(".json.tmp")
    temporary_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary_path.replace(checkpoint_path)


def load_resume_state(output_dir: Path) -> tuple[dict[str, Project], list[Document], set[str]]:
    checkpoint_path = output_dir / "checkpoint.json"
    projects_path = output_dir / "projects.csv"
    documents_path = output_dir / "documents.csv"
    if not checkpoint_path.exists() or not projects_path.exists() or not documents_path.exists():
        return {}, [], set()

    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    with projects_path.open(newline="", encoding="utf-8") as handle:
        prior_projects = {row["project_id"]: Project(**row) for row in csv.DictReader(handle)}

    documents: list[Document] = []
    with documents_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            row["bytes"] = int(row["bytes"] or 0)
            row["downloaded"] = row["downloaded"].lower() == "true"
            row["selected"] = row["selected"].lower() == "true"
            documents.append(Document(**row))

    processed_project_ids = set(checkpoint.get("processed_project_ids", []))
    return prior_projects, documents, processed_project_ids


def process_project(
    project: Project,
    args: argparse.Namespace,
    output_dir: Path,
    raw_dir: Path,
) -> tuple[list[Document], bool]:
    documents: list[Document] = []
    try:
        project_html = fetch_text(project.project_url, args)
        if args.save_html:
            (raw_dir / f"project_{project.project_id}.html").write_text(project_html, encoding="utf-8")
        project.consultation_url = find_consultation_url(project, project_html)
        if project.consultation_url:
            time.sleep(args.sleep)
            consultation_html = fetch_text(project.consultation_url, args)
            if args.save_html:
                (raw_dir / f"consultations_{project.project_id}.html").write_text(
                    consultation_html,
                    encoding="utf-8",
                )
            for doc in parse_documents(project, consultation_html):
                doc.selected = document_matches(doc, args.category_keyword, args.all_consultation_docs)
                if doc.selected and not args.no_download:
                    try:
                        download_document(doc, output_dir, args)
                    except Exception as exc:  # keep crawling after one bad file
                        doc.error = str(exc)
                documents.append(doc)
            time.sleep(args.sleep)
        return documents, True
    except Exception as exc:
        return [
            Document(
                project_id=project.project_id,
                project_title=project.title,
                project_number=project.number,
                category_id="",
                category="",
                filename="",
                document_url="",
                error=str(exc),
            )
        ], False


def crawl(args: argparse.Namespace) -> tuple[list[Project], list[Document]]:
    output_dir = Path(args.output_dir)
    raw_dir = output_dir / "raw_html"
    if args.save_html:
        raw_dir.mkdir(parents=True, exist_ok=True)

    first_url = list_url(args.type_id, 1, args.page_size, args.create_from, args.create_to)
    first_html = fetch_text(first_url, args)
    if args.save_html:
        (raw_dir / "list_0001.html").write_text(first_html, encoding="utf-8")
    total_count = extract_total_count(first_html)
    total_pages = max(1, (total_count + args.page_size - 1) // args.page_size) if total_count else 1
    if args.max_pages:
        total_pages = min(total_pages, args.max_pages)

    projects: list[Project] = []
    seen_project_ids: set[str] = set()
    for page in range(1, total_pages + 1):
        if page == 1:
            page_html = first_html
        else:
            page_url = list_url(args.type_id, page, args.page_size, args.create_from, args.create_to)
            page_html = fetch_text(page_url, args)
            if args.save_html:
                (raw_dir / f"list_{page:04d}.html").write_text(page_html, encoding="utf-8")
            time.sleep(args.sleep)
        page_projects = parse_list_page(page_html)
        for project in page_projects:
            if project.project_id in seen_project_ids:
                continue
            projects.append(project)
            seen_project_ids.add(project.project_id)
            if args.max_projects and len(projects) >= args.max_projects:
                break
        if args.max_projects and len(projects) >= args.max_projects:
            break
        print(f"list page {page}/{total_pages}: {len(page_projects)} projects", file=sys.stderr)

    if args.list_only:
        return projects, []

    prior_projects: dict[str, Project] = {}
    documents: list[Document] = []
    processed_project_ids: set[str] = set()
    if args.resume:
        prior_projects, documents, processed_project_ids = load_resume_state(output_dir)
        for project in projects:
            prior = prior_projects.get(project.project_id)
            if prior is not None:
                project.consultation_url = prior.consultation_url
        print(
            f"resume: {len(processed_project_ids)} projects, {len(documents)} documents",
            file=sys.stderr,
        )

    pending = [
        (idx, project)
        for idx, project in enumerate(projects, start=1)
        if project.project_id not in processed_project_ids
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        results = executor.map(
            lambda item: process_project(item[1], args, output_dir, raw_dir),
            pending,
        )
        for handled, ((idx, project), (project_documents, project_completed)) in enumerate(
            zip(pending, results),
            start=1,
        ):
            print(f"project {idx}/{len(projects)}: {project.project_id} {project.number}", file=sys.stderr)
            documents = [
                doc
                for doc in documents
                if not (doc.project_id == project.project_id and doc.error and not doc.document_url)
            ]
            documents.extend(project_documents)
            if project_completed:
                processed_project_ids.add(project.project_id)
            if args.checkpoint_every and handled % args.checkpoint_every == 0:
                write_checkpoint(output_dir, projects, documents, processed_project_ids, complete=False)

    write_checkpoint(
        output_dir,
        projects,
        documents,
        processed_project_ids,
        complete=len(processed_project_ids) == len(projects),
    )

    return projects, documents


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download RCL project metadata and public-consultation PDFs.")
    parser.add_argument("--output-dir", default="data/rcl", help="Output directory for CSV, JSONL, raw HTML, and PDFs.")
    parser.add_argument("--type-id", type=int, default=2, help="RCL project type. 2 means Projekty ustaw.")
    parser.add_argument("--page-size", type=int, default=100, help="RCL list page size.")
    parser.add_argument("--max-pages", type=int, default=1, help="Limit list pages while developing. Use 0 for all pages.")
    parser.add_argument("--max-projects", type=int, default=0, help="Limit projects. Use 0 for no limit.")
    parser.add_argument("--create-from", default="", help="Optional RCL createDateFrom filter, e.g. 2026-01-01.")
    parser.add_argument("--create-to", default="", help="Optional RCL createDateTo filter, e.g. 2026-08-24.")
    parser.add_argument("--category-keyword", action="append", default=["stanowisk", "uwag"], help="Keyword for selecting consultation document categories/files. Can be repeated.")
    parser.add_argument("--all-consultation-docs", action="store_true", help="Download every document in the consultation catalog.")
    parser.add_argument("--list-only", action="store_true", help="Only crawl list pages and write the project inventory.")
    parser.add_argument("--no-download", action="store_true", help="Only write metadata, do not download PDFs.")
    parser.add_argument("--save-html", action="store_true", help="Save raw list/project/catalog HTML for auditability.")
    parser.add_argument("--overwrite", action="store_true", help="Re-download PDFs even if a local file exists.")
    parser.add_argument("--resume", action="store_true", help="Resume a checkpointed crawl in the output directory.")
    parser.add_argument("--checkpoint-every", type=int, default=25, help="Write a resumable checkpoint every N projects. Use 0 to disable intermediate checkpoints.")
    parser.add_argument("--workers", type=int, default=1, help="Concurrent project workers. Keep low to avoid overloading the source service.")
    parser.add_argument("--sleep", type=float, default=0.5, help="Delay between requests in seconds.")
    parser.add_argument("--timeout", type=int, default=45, help="HTTP timeout in seconds.")
    parser.add_argument("--retries", type=int, default=2, help="HTTP retry count.")
    parser.add_argument("--user-agent", default=os.environ.get("RCL_USER_AGENT", DEFAULT_USER_AGENT))
    return parser


def write_run_summary(
    output_dir: Path,
    args: argparse.Namespace,
    projects: list[Project],
    documents: list[Document],
    started_at: str,
    finished_at: str,
) -> None:
    selected = sum(1 for doc in documents if doc.selected)
    downloaded = sum(1 for doc in documents if doc.downloaded)
    errors = [doc.error for doc in documents if doc.error]
    summary = {
        "object": {
            "kind": "dataset_source_inventory",
            "name": "rcl_legislacja_gov_pl",
            "source_url": BASE_URL,
        },
        "protocol": {
            "kind": "source_crawl",
            "tool": "scripts/rcl_downloader.py",
            "version": "0.3",
        },
        "run": {
            "started_at": started_at,
            "finished_at": finished_at,
            "args": vars(args),
        },
        "evidence": {
            "projects": len(projects),
            "documents_found": len(documents),
            "documents_selected": selected,
            "documents_downloaded": downloaded,
            "errors": len(errors),
            "error_samples": errors[:20],
        },
        "outputs": {
            "projects_csv": str(output_dir / "projects.csv"),
            "projects_jsonl": str(output_dir / "projects.jsonl"),
            "documents_csv": str(output_dir / "documents.csv"),
            "documents_jsonl": str(output_dir / "documents.jsonl"),
        },
    }
    runs_dir = output_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_id = started_at.replace(":", "").replace("-", "").replace("+", "z")
    (runs_dir / f"rcl_run_{run_id}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    started_at = datetime.now(timezone.utc).isoformat()
    if args.max_pages == 0:
        args.max_pages = None
    if args.max_projects == 0:
        args.max_projects = None
    if args.workers < 1:
        parser.error("--workers must be at least 1")

    output_dir = Path(args.output_dir)
    projects, documents = crawl(args)

    write_outputs(output_dir, projects, documents)
    finished_at = datetime.now(timezone.utc).isoformat()
    write_run_summary(output_dir, args, projects, documents, started_at, finished_at)

    selected = sum(1 for doc in documents if doc.selected)
    downloaded = sum(1 for doc in documents if doc.downloaded)
    errors = sum(1 for doc in documents if doc.error)
    print(f"projects: {len(projects)}")
    print(f"documents found: {len(documents)}")
    print(f"documents selected: {selected}")
    print(f"documents downloaded: {downloaded}")
    print(f"errors: {errors}")
    print(f"output: {output_dir.resolve()}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
