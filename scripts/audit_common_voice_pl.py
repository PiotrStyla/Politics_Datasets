#!/usr/bin/env python3
"""Create a deterministic language and shape audit for Common Voice Polish text."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import pathlib
import statistics

import langid
import pyarrow.parquet as pq
from langid.langid import LanguageIdentifier, model


LANGUAGES = ["pl", "en", "de", "cs", "sk", "uk", "ru", "fr"]


def quantiles(values: list[int]) -> dict[str, float]:
    ordered = sorted(values)
    if not ordered:
        return {}

    def percentile(fraction: float) -> float:
        index = (len(ordered) - 1) * fraction
        lower = int(index)
        upper = min(lower + 1, len(ordered) - 1)
        weight = index - lower
        return ordered[lower] * (1 - weight) + ordered[upper] * weight

    return {
        "min": ordered[0], "p10": percentile(0.10), "p50": percentile(0.50),
        "p90": percentile(0.90), "p99": percentile(0.99), "max": ordered[-1],
        "mean": statistics.fmean(ordered),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parquet", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--sample-size", type=int, default=5000)
    args = parser.parse_args()

    table = pq.read_table(args.parquet, columns=["id", "text", "token_count"])
    rows = table.to_pylist()
    sample = sorted(
        rows,
        key=lambda row: hashlib.sha256(("language-audit:" + row["id"]).encode()).hexdigest(),
    )[: args.sample_size]
    identifier = LanguageIdentifier.from_modelstring(model, norm_probs=True)
    identifier.set_languages(LANGUAGES)
    counts: collections.Counter[str] = collections.Counter()
    high_confidence_non_polish = []
    for row in sample:
        language, confidence = identifier.classify(row["text"])
        counts[language] += 1
        if language != "pl" and confidence >= 0.95 and len(high_confidence_non_polish) < 50:
            high_confidence_non_polish.append({
                "id": row["id"], "language": language,
                "confidence": confidence, "text": row["text"],
            })

    payload = {
        "protocol": "langid.py constrained to pl,en,de,cs,sk,uk,ru,fr",
        "interpretation_limit": "Short and archaic Polish sentences can be misclassified; this audit is evidence, not an automatic exclusion rule.",
        "population_rows": len(rows),
        "sample_method": "lowest sha256(language-audit:<id>)",
        "sample_rows": len(sample),
        "language_counts": dict(sorted(counts.items())),
        "polish_share": counts["pl"] / len(sample) if sample else 0.0,
        "high_confidence_non_polish_examples": high_confidence_non_polish,
        "character_length": quantiles([len(row["text"]) for row in rows]),
        "token_count": quantiles([int(row["token_count"]) for row in rows]),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
