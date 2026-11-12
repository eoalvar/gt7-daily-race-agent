"""Source-independent Daily Race C DR lap-time statistics.

Input is an explicitly authorized/exported CSV, not an automated website
scraper. Reject incomplete samples before publishing population benchmarks.

CSV columns: dr,score_ms (optional: rank,psn_id)
Metadata JSON: event_id, source, source_permission, population_total,
               population_definition, observed_at
Run: python src/build_dr_benchmarks_from_csv.py --csv INPUT --metadata META --output OUT
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

DR_CODES = {1: "E", 2: "D", 3: "C", 4: "B", 5: "A", 6: "A+", 7: "S"}
DR_NAME_TO_CODE = {name: code for code, name in DR_CODES.items()}


def time_label(milliseconds):
    n = int(round(milliseconds))
    return f"{n // 60000}:{(n % 60000) // 1000:02d}.{n % 1000:03d}"


def normalize_dr(raw):
    val = str(raw).strip().upper()
    if val in DR_NAME_TO_CODE:
        return DR_NAME_TO_CODE[val]
    if val.isdigit() and int(val) in DR_CODES:
        return int(val)
    raise ValueError(f"Unknown Driver Rating group: {raw!r}")


def robust_clean_scores(scores):
    """Replicate the legacy DR report's 5× MAD cleaning rule."""
    values = [float(x) for x in scores]
    n = len(values)
    median = statistics.median(values) if values else None
    if n < 12:
        return values, {"raw_n": n, "clean_n": n, "excluded_n": 0}
    mad = statistics.median(abs(v - median) for v in values)
    if not mad:
        return values, {"raw_n": n, "clean_n": n, "excluded_n": 0}
    sigma = 1.4826 * mad
    clean = [v for v in values if median - 5 * sigma <= v <= median + 5 * sigma]
    # Do not eliminate more than 10% of a legitimate distribution.
    if len(clean) < .90 * n:
        clean = values
    return clean, {
        "raw_n": n, "clean_n": len(clean), "excluded_n": n - len(clean)
    }


def summarize(rows, metadata):
    required = ["event_id", "source", "source_permission", "population_total",
                "population_definition", "observed_at"]
    missing = [key for key in required if metadata.get(key) in (None, "", [])]
    if missing:
        raise ValueError("Missing metadata: " + ", ".join(missing))
    if metadata["source_permission"] != "authorized":
        raise ValueError("Input must be explicitly authorized for this automated analysis")
    if metadata["population_definition"] != "all_qualified_drivers":
        raise ValueError("Population must be all qualified drivers; filtered samples are not comparable")
    total = metadata["population_total"]
    if type(total) is not int or total <= 0:
        raise ValueError("population_total must be a positive integer")

    groups = defaultdict(list)
    seen_ranks = set()
    n = 0
    for row in rows:
        dr = normalize_dr(row["dr"])
        try:
            score = float(row["score_ms"])
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError("Missing or invalid score_ms") from exc
        if not math.isfinite(score) or score <= 0:
            raise ValueError("Nonpositive or nonfinite lap-time")
        rank = str(row.get("rank", "")).strip()
        if rank:
            if not rank.isdigit() or int(rank) <= 0 or int(rank) in seen_ranks:
                raise ValueError("Invalid or duplicated global rank")
            seen_ranks.add(int(rank))
        groups[dr].append(score)
        n += 1
    if n != total:
        raise ValueError(f"INCOMPLETE_POPULATION: {n} rows; expected {total}")
    if seen_ranks and (len(seen_ranks) != n or min(seen_ranks) != 1 or max(seen_ranks) != n):
        raise ValueError("Global ranks are incomplete or noncontiguous")

    stats = {}
    for code, label in DR_CODES.items():
        clean, diagnostics = robust_clean_scores(groups[code])
        avg = statistics.mean(clean) if clean else None
        std = statistics.pstdev(clean) if len(clean) >= 2 else None
        stats[str(code)] = {
            "dr": code, "label": label, "drivers": len(clean),
            "average_score": avg,
            "average_laptime": time_label(avg) if avg is not None else "N/A",
            "stddev_ms": std,
            "stddev_seconds": std / 1000 if std is not None else None,
            "diagnostics": diagnostics,
        }
    return {
        "event_id": metadata["event_id"], "source": metadata["source"],
        "observed_at": metadata["observed_at"],
        "population_definition": metadata["population_definition"],
        "population_total": total, "rows_verified": n,
        "coverage": 1.0, "dr_laptime_stats": stats,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    with args.csv.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not {"dr", "score_ms"}.issubset(reader.fieldnames):
            raise ValueError("CSV must contain dr and score_ms columns")
        result = summarize(reader, metadata)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"DR_BENCHMARKS_VERIFIED: {result['rows_verified']} records; {result['source']}")


if __name__ == "__main__":
    main()
