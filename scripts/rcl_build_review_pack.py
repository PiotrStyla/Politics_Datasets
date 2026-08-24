#!/usr/bin/env python3
"""Build a local HTML/CSV review pack for RCL pilot annotation."""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path


PROTOCOL_ID = "rcl-gold-pilot-review-pack"
PROTOCOL_VERSION = "0.1.0"

REVIEW_FIELDS = [
    "calibration_rank",
    "queue_id",
    "review_reason",
    "filename",
    "document_url",
    "raw_path",
    "text_path",
    "source_media_type",
    "machine_review_priority",
    "machine_doc_type_hint",
    "machine_source_type_hint",
    "machine_pii_hint",
    "machine_pii_types",
    "machine_extraction_quality_hint",
    "char_count",
    "word_count",
    "manual_doc_type",
    "manual_source_type",
    "contains_pii",
    "pii_types",
    "legal_basis",
    "legal_status",
    "extraction_quality",
    "train_recommendation",
    "exclusion_reason",
    "reviewer",
    "reviewed_at",
    "review_notes",
]

CONTROLLED_VALUES = {
    "manual_doc_type": [
        "organization_comment",
        "individual_comment",
        "government_response",
        "cover_letter",
        "draft_law",
        "attachment",
        "other",
    ],
    "manual_source_type": [
        "ngo",
        "trade_union",
        "employer_organization",
        "professional_body",
        "company",
        "religious_organization",
        "public_body",
        "individual",
        "unknown",
        "other",
    ],
    "contains_pii": ["yes", "no", "uncertain"],
    "legal_status": ["review_needed", "eligible", "exclude", "uncertain"],
    "extraction_quality": ["good", "usable", "poor", "not_extractable"],
    "train_recommendation": ["include", "exclude", "conditional", "undecided"],
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def load_rows(root: Path, queue_path: Path) -> list[dict[str, str]]:
    queue_rows = read_csv(queue_path)
    observations = {row["queue_id"]: row for row in read_csv(root / "machine_observations.csv")}
    annotations = {row["queue_id"]: row for row in read_csv(root / "annotations.csv")}
    rows: list[dict[str, str]] = []
    for queue_row in queue_rows:
        queue_id = queue_row["queue_id"]
        observation = observations.get(queue_id, {})
        annotation = annotations[queue_id]
        row = {
            "calibration_rank": queue_row["calibration_rank"],
            "queue_id": queue_id,
            "review_reason": queue_row["review_reason"],
            "filename": queue_row["filename"],
            "document_url": queue_row["document_url"],
            "raw_path": queue_row["raw_path"],
            "text_path": queue_row["text_path"],
            "source_media_type": queue_row["source_media_type"],
            "machine_review_priority": queue_row["machine_review_priority"],
            "machine_doc_type_hint": observation.get("machine_doc_type_hint", ""),
            "machine_source_type_hint": observation.get("machine_source_type_hint", ""),
            "machine_pii_hint": queue_row["machine_pii_hint"],
            "machine_pii_types": queue_row["machine_pii_types"],
            "machine_extraction_quality_hint": queue_row["machine_extraction_quality_hint"],
            "char_count": queue_row["char_count"],
            "word_count": queue_row["word_count"],
            "manual_doc_type": annotation["manual_doc_type"],
            "manual_source_type": annotation["manual_source_type"],
            "contains_pii": annotation["contains_pii"],
            "pii_types": annotation["pii_types"],
            "legal_basis": annotation["legal_basis"],
            "legal_status": annotation["legal_status"],
            "extraction_quality": annotation["extraction_quality"],
            "train_recommendation": annotation["train_recommendation"],
            "exclusion_reason": annotation["exclusion_reason"],
            "reviewer": annotation["reviewer"],
            "reviewed_at": annotation["reviewed_at"],
            "review_notes": annotation["review_notes"],
        }
        rows.append(row)
    return rows


def css() -> str:
    return """
:root {
  color-scheme: light;
  --bg: #f7f7f4;
  --panel: #ffffff;
  --ink: #1d2528;
  --muted: #667174;
  --line: #d9dfdc;
  --accent: #2f6f73;
  --warn: #9a5b12;
  --bad: #a13c3c;
  --good: #397650;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: Arial, Helvetica, sans-serif;
  font-size: 14px;
  line-height: 1.45;
}
header {
  padding: 24px 28px 16px;
  border-bottom: 1px solid var(--line);
  background: #eef3f0;
}
h1 {
  margin: 0 0 8px;
  font-size: 26px;
  letter-spacing: 0;
}
h2 {
  margin: 22px 0 10px;
  font-size: 18px;
  letter-spacing: 0;
}
p { max-width: 980px; margin: 6px 0; }
main { padding: 18px 28px 40px; }
.summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
  margin: 0 0 18px;
  max-width: 1080px;
}
.metric {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 12px;
}
.metric strong { display: block; font-size: 22px; }
.metric span { color: var(--muted); }
.table-wrap {
  overflow-x: auto;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--panel);
}
table {
  width: 100%;
  border-collapse: collapse;
  min-width: 1080px;
}
th, td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--line);
  vertical-align: top;
  text-align: left;
}
th {
  position: sticky;
  top: 0;
  background: #eef3f0;
  font-size: 12px;
  text-transform: uppercase;
  color: #3f4d4f;
}
tr:target { outline: 3px solid #86b6b1; outline-offset: -3px; }
a { color: var(--accent); font-weight: 700; text-decoration: none; }
a:hover { text-decoration: underline; }
.badge {
  display: inline-block;
  padding: 2px 7px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: #f9faf8;
  white-space: nowrap;
  font-size: 12px;
}
.bad { color: var(--bad); border-color: #e0b5b5; background: #fff6f6; }
.warn { color: var(--warn); border-color: #e3c48d; background: #fff9ed; }
.good { color: var(--good); border-color: #b6d6c0; background: #f1faf3; }
.muted { color: var(--muted); }
.controls {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 10px;
  max-width: 1180px;
}
.control {
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--panel);
  padding: 10px;
}
.control code {
  display: block;
  margin-top: 6px;
  color: var(--muted);
  white-space: normal;
}
"""


def badge(value: str, kind: str = "") -> str:
    class_name = "badge"
    if kind:
        class_name += f" {kind}"
    return f'<span class="{class_name}">{html.escape(value or "-")}</span>'


def link(path: str, label: str) -> str:
    return f'<a href="{html.escape(path)}">{html.escape(label)}</a>'


def relative_from_pack(output_dir: Path, target: Path) -> str:
    return Path(os.path.relpath(target.resolve(), output_dir.resolve())).as_posix()


def html_document(
    root: Path,
    output_dir: Path,
    rows: list[dict[str, str]],
    created_at: str,
    title: str,
    description: str,
    sheet_name: str,
) -> str:
    reason_counts = {
        reason: sum(1 for row in rows if row["review_reason"] == reason)
        for reason in sorted({row["review_reason"] for row in rows})
    }
    rows_html: list[str] = []
    for row in rows:
        raw_href = relative_from_pack(output_dir, root / row["raw_path"])
        text_href = relative_from_pack(output_dir, root / row["text_path"])
        pii_kind = "bad" if row["machine_pii_hint"] == "yes" else "warn"
        quality = row["machine_extraction_quality_hint"]
        quality_kind = "good" if quality == "good" else "bad" if quality == "not_extractable" else "warn"
        status_kind = "good" if row["manual_doc_type"] else "warn"
        rows_html.append(
            "<tr id=\"{queue_id}\">"
            "<td>{rank}</td>"
            "<td><strong>{queue_id}</strong><br>{reason}</td>"
            "<td>{filename}<br><span class=\"muted\">{media}</span></td>"
            "<td>{raw}<br>{text}<br>{source}</td>"
            "<td>{doc_type}<br>{source_type}</td>"
            "<td>{pii}<br><span class=\"muted\">{pii_types}</span></td>"
            "<td>{quality}<br><span class=\"muted\">chars {chars} / words {words}</span></td>"
            "<td>{review_status}<br><span class=\"muted\">{reviewer}</span></td>"
            "</tr>".format(
                rank=html.escape(row["calibration_rank"]),
                queue_id=html.escape(row["queue_id"]),
                reason=badge(row["review_reason"]),
                filename=html.escape(row["filename"]),
                media=html.escape(row["source_media_type"]),
                raw=link(raw_href, "raw document"),
                text=link(text_href, "extracted text"),
                source=link(row["document_url"], "RCL source"),
                doc_type=badge(row["machine_doc_type_hint"]),
                source_type=badge(row["machine_source_type_hint"]),
                pii=badge(row["machine_pii_hint"], pii_kind),
                pii_types=html.escape(row["machine_pii_types"] or "no machine type hit"),
                quality=badge(quality, quality_kind),
                chars=html.escape(row.get("char_count", "")),
                words=html.escape(row.get("word_count", "")),
                review_status=badge(row["manual_doc_type"] or "not reviewed", status_kind),
                reviewer=html.escape(row["reviewer"] or "reviewer empty"),
            )
        )

    controlled = "".join(
        f"<div class=\"control\"><strong>{html.escape(field)}</strong><code>{html.escape(', '.join(values))}</code></div>"
        for field, values in CONTROLLED_VALUES.items()
    )
    metrics = "".join(
        f"<div class=\"metric\"><strong>{count}</strong><span>{html.escape(reason)}</span></div>"
        for reason, count in reason_counts.items()
    )
    metrics += f"<div class=\"metric\"><strong>{len(rows)}</strong><span>review rows</span></div>"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>{css()}</style>
</head>
<body>
  <header>
    <h1>{html.escape(title)}</h1>
    <p>{html.escape(description)}</p>
    <p class="muted">Generated at {html.escape(created_at)}. Fill decisions in <code>{html.escape(sheet_name)}</code>, then transfer settled fields into <code>annotations.csv</code>.</p>
  </header>
  <main>
    <section class="summary">{metrics}</section>
    <h2>Controlled Values</h2>
    <section class="controls">{controlled}</section>
    <h2>Review Queue</h2>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Rank</th>
            <th>ID / reason</th>
            <th>Document</th>
            <th>Open</th>
            <th>Machine type</th>
            <th>PII hint</th>
            <th>Extraction</th>
            <th>Manual status</th>
          </tr>
        </thead>
        <tbody>
          {''.join(rows_html)}
        </tbody>
      </table>
    </div>
  </main>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a local review pack for RCL pilot rows.")
    parser.add_argument("--input-dir", default="data/rcl_gold_pilot_v0_1")
    parser.add_argument("--queue", default="calibration_queue.csv")
    parser.add_argument("--output-dir", default="review_pack")
    parser.add_argument("--sheet-name", default="calibration_review_sheet.csv")
    parser.add_argument("--title", default="RCL Calibration Review Pack")
    parser.add_argument(
        "--description",
        default=(
            "Local review surface for RCL pilot rows. Raw documents and extracted text "
            "are linked locally and should not be published before legal and PII review."
        ),
    )
    parser.add_argument("--actor", default="unassigned")
    args = parser.parse_args()

    started_at = utc_now()
    run_id = "rcl-review-pack-" + started_at.replace(":", "").replace("-", "").replace("+", "z")
    root = Path(args.input_dir)
    output_dir = root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = load_rows(root, root / args.queue)

    missing: list[str] = []
    for row in rows:
        for field in ["raw_path", "text_path"]:
            path = root / row[field]
            if not path.is_file():
                missing.append(f"{field}: {path}")
    if missing:
        raise SystemExit("missing review-pack inputs:\n" + "\n".join(missing))

    review_sheet_path = output_dir / args.sheet_name
    write_csv(review_sheet_path, REVIEW_FIELDS, rows)
    index_path = output_dir / "index.html"
    index_path.write_text(
        html_document(root, output_dir, rows, started_at, args.title, args.description, args.sheet_name),
        encoding="utf-8",
        newline="\n",
    )

    protocol_src = Path("docs/rcl_gold_set_annotation_protocol.md")
    if protocol_src.is_file():
        shutil.copyfile(protocol_src, output_dir / "annotation_protocol.md")

    run = {
        "object": {"id": "rcl:gold-set-pilot-review-pack", "kind": "local_review_pack"},
        "protocol": {
            "id": PROTOCOL_ID,
            "version": PROTOCOL_VERSION,
            "tool": "scripts/rcl_build_review_pack.py",
            "input": args.queue,
        },
        "run": {
            "id": run_id,
            "actor": args.actor,
            "started_at": started_at,
            "finished_at": utc_now(),
        },
        "evidence": {
            "rows": len(rows),
            "missing_inputs": len(missing),
            "output_files": [
                f"{args.output_dir}/index.html",
                f"{args.output_dir}/{args.sheet_name}",
                f"{args.output_dir}/annotation_protocol.md",
            ],
        },
        "claims": [],
        "publication_boundary": {
            "local_only": True,
            "reason": "review pack links local raw documents and local extracted text before legal/PII review",
        },
    }
    runs_dir = root / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_path = runs_dir / f"{run_id}.json"
    run_path.write_text(json.dumps(run, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    print(f"review_rows: {len(rows)}")
    print(f"index: {index_path.resolve()}")
    print(f"review_sheet: {review_sheet_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
