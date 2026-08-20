from __future__ import annotations

import json
import math
from pathlib import Path


VERSION = "0.1"
INPUT_FILE = Path("data/relative_rating_study.json")
OUTPUT_JSON = Path("data/relative_formula_lab.json")
OUTPUT_REPORT = Path("reports/relative_formula_lab.txt")

WEIGHTS = [
    (0.70, 0.30),
    (0.60, 0.40),
    (0.50, 0.50),
    (0.45, 0.55),
    (0.40, 0.60),
    (0.30, 0.70),
]

SEP = "=" * 116
SUB = "-" * 116


def clamp(value, lo=0.0, hi=10.0):
    return max(lo, min(hi, value))


def interpolate(x, anchors):
    """Piecewise-linear interpolation. anchors must be sorted by x ascending."""
    if x <= anchors[0][0]:
        return anchors[0][1]
    if x >= anchors[-1][0]:
        return anchors[-1][1]
    for (x0, y0), (x1, y1) in zip(anchors, anchors[1:]):
        if x0 <= x <= x1:
            if x1 == x0:
                return y0
            t = (x - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return anchors[-1][1]


def wr_score(gap_pct):
    # Absolute-performance scale. Lower gap is better.
    # The curve deliberately reserves 9-10 for genuinely world-class proximity.
    anchors = [
        (0.0, 10.0),
        (0.5, 9.5),
        (1.0, 9.0),
        (2.0, 8.0),
        (3.0, 7.0),
        (4.0, 6.0),
        (5.0, 5.0),
        (7.5, 3.5),
        (10.0, 2.0),
        (15.0, 0.5),
        (20.0, 0.0),
    ]
    return clamp(interpolate(float(gap_pct), anchors))


def percentile_score(top_pct):
    # Relative-to-field scale. Top % is the percentage of drivers ahead of or
    # equal to the user's rank: lower is better. Median is intentionally 5.0.
    anchors = [
        (0.0, 10.0),
        (0.1, 9.8),
        (0.5, 9.4),
        (1.0, 9.0),
        (2.0, 8.6),
        (5.0, 8.0),
        (10.0, 7.0),
        (15.0, 6.5),
        (25.0, 6.0),
        (50.0, 5.0),
        (75.0, 3.5),
        (90.0, 2.0),
        (100.0, 0.0),
    ]
    return clamp(interpolate(float(top_pct), anchors))


def robust_distribution_score(z):
    # z = (user gap - median gap) / IQR. Negative is better than median.
    # This alternative tests whether field shape is more informative than raw Top %.
    anchors = [
        (-2.00, 10.0),
        (-1.50, 9.3),
        (-1.00, 8.3),
        (-0.75, 7.5),
        (-0.50, 6.5),
        (-0.25, 5.7),
        (0.00, 5.0),
        (0.50, 3.5),
        (1.00, 2.0),
        (2.00, 0.5),
        (3.00, 0.0),
    ]
    return clamp(interpolate(float(z), anchors))


def fmt(value):
    return f"{value:.2f}" if isinstance(value, (int, float)) else "N/A"


def load_results():
    payload = json.loads(INPUT_FILE.read_text(encoding="utf-8"))
    results = payload.get("results") or []
    if not results:
        raise RuntimeError("No results found in data/relative_rating_study.json")
    return results


def evaluate(item):
    gap = float(item["user_gap_to_wr_percent"])
    top = float(item["user_top_percent"])
    z = item.get("gap_distribution", {}).get("user_robust_z")

    absolute = wr_score(gap)
    field_percentile = percentile_score(top)
    field_robust = robust_distribution_score(z) if isinstance(z, (int, float)) else None

    models = {}
    for w_abs, w_field in WEIGHTS:
        name = f"PCT_{int(w_abs*100):02d}_{int(w_field*100):02d}"
        models[name] = clamp(w_abs * absolute + w_field * field_percentile)
        if field_robust is not None:
            rname = f"ROB_{int(w_abs*100):02d}_{int(w_field*100):02d}"
            models[rname] = clamp(w_abs * absolute + w_field * field_robust)

    # Primary candidate from the preceding empirical review.
    models["CANDIDATE_45_55"] = models["PCT_45_55"]

    return {
        "week_start": item.get("week_start"),
        "group": item.get("group"),
        "race": item.get("race"),
        "drivers": item.get("drivers"),
        "gap_to_wr_percent": gap,
        "top_percent": top,
        "robust_z": z,
        "legacy_general": item.get("legacy_general"),
        "legacy_relativa": item.get("legacy_relativa"),
        "components": {
            "absolute_wr": absolute,
            "field_percentile": field_percentile,
            "field_robust": field_robust,
        },
        "models": models,
    }


def add_ranks(rows):
    model_names = sorted({name for row in rows for name in row["models"]})
    for model in model_names:
        ordered = sorted(rows, key=lambda row: row["models"].get(model, -1), reverse=True)
        for rank, row in enumerate(ordered, start=1):
            row.setdefault("ranks", {})[model] = rank


def build_report(rows):
    lines = [
        f"GT7 RELATIVA FORMULA LAB V{VERSION}",
        SEP,
        "Purpose: compare candidate 0-10 Relativa formulas without modifying production.",
        "Absolute component = proximity to WR. Field component = actual leaderboard distribution.",
        "Primary candidate = 45% WR proximity + 55% percentile-distribution score.",
        "ROB variants replace raw Top % with robust IQR position to test sensitivity to field shape.",
        "Production modified: NO",
        "",
        "PRIMARY CANDIDATE - 45/55",
        SUB,
        f"{'Week':<12} {'Grp':<6} {'Gap WR':>8} {'Top %':>8} {'WRcmp':>7} {'Grid':>7} {'Old Rel':>8} {'New Rel':>8} {'Rank':>5}",
    ]

    for row in sorted(rows, key=lambda r: r["week_start"]):
        lines.append(
            f"{row['week_start']:<12} {str(row['group']):<6} "
            f"{row['gap_to_wr_percent']:>7.3f}% {row['top_percent']:>7.2f}% "
            f"{row['components']['absolute_wr']:>7.2f} {row['components']['field_percentile']:>7.2f} "
            f"{fmt(row['legacy_relativa']):>8} {row['models']['CANDIDATE_45_55']:>8.2f} "
            f"{row['ranks']['CANDIDATE_45_55']:>5}"
        )

    lines.extend(["", "WEIGHT SENSITIVITY - PERCENTILE FIELD COMPONENT", SUB])
    pct_models = [f"PCT_{int(a*100):02d}_{int(b*100):02d}" for a, b in WEIGHTS]
    lines.append(f"{'Week':<12} " + " ".join(f"{m.replace('PCT_',''):>7}" for m in pct_models))
    for row in sorted(rows, key=lambda r: r["week_start"]):
        lines.append(f"{row['week_start']:<12} " + " ".join(f"{row['models'][m]:>7.2f}" for m in pct_models))

    lines.extend(["", "ROBUST-IQR ALTERNATIVES", SUB])
    rob_models = [f"ROB_{int(a*100):02d}_{int(b*100):02d}" for a, b in WEIGHTS]
    lines.append(f"{'Week':<12} {'Robust z':>9} " + " ".join(f"{m.replace('ROB_',''):>7}" for m in rob_models))
    for row in sorted(rows, key=lambda r: r["week_start"]):
        z = row["robust_z"]
        vals = " ".join(f"{row['models'].get(m, float('nan')):>7.2f}" for m in rob_models)
        lines.append(f"{row['week_start']:<12} {fmt(z):>9} {vals}")

    lines.extend([
        "",
        "PERFORMANCE ORDER - PRIMARY CANDIDATE",
        SUB,
    ])
    for row in sorted(rows, key=lambda r: r["models"]["CANDIDATE_45_55"], reverse=True):
        lines.append(
            f"{row['ranks']['CANDIDATE_45_55']:>2}. {row['week_start']} | {row['group']} | "
            f"Relativa {row['models']['CANDIDATE_45_55']:.2f} | Top {row['top_percent']:.2f}% | "
            f"WR +{row['gap_to_wr_percent']:.3f}%"
        )

    lines.extend([
        "",
        "INTERPRETATION",
        SUB,
        "The candidate scale is intentionally interpretable: median-field performance is centered near 5,",
        "while Top 10%, Top 5% and Top 1% field performance contribute approximately 7, 8 and 9 points.",
        "The WR component prevents two identical percentiles from being treated as equally strong when",
        "their absolute distance from the world record is materially different.",
        "No candidate should replace production until the cross-race ordering and scale are reviewed.",
        SEP,
    ])
    return "\n".join(lines) + "\n"


def main():
    if not INPUT_FILE.exists():
        raise RuntimeError("Run GT7 Relativa Rating Study first: data/relative_rating_study.json is missing")

    rows = [evaluate(item) for item in load_results()]
    add_ranks(rows)

    payload = {
        "version": VERSION,
        "status": "STUDY_ONLY",
        "production_formula_modified": False,
        "primary_candidate": "CANDIDATE_45_55",
        "weights_tested": [
            {"absolute_wr": a, "field_distribution": b} for a, b in WEIGHTS
        ],
        "rows": rows,
    }

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report = build_report(rows)
    OUTPUT_REPORT.write_text(report, encoding="utf-8")
    print(report)
    print(f"Saved: {OUTPUT_JSON}")
    print(f"Saved: {OUTPUT_REPORT}")


if __name__ == "__main__":
    main()
