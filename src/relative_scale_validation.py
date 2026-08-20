from __future__ import annotations

import json
from pathlib import Path


VERSION = "0.1"
OUTPUT_JSON = Path("data/relative_scale_validation.json")
OUTPUT_REPORT = Path("reports/relative_scale_validation.txt")

SEP = "=" * 104
SUB = "-" * 104

# Candidate selected for final scale validation: equal weighting between
# absolute proximity to WR and relative position in the actual field.
ABS_WEIGHT = 0.50
FIELD_WEIGHT = 0.50

TOP_PCT_GRID = [0.1, 0.5, 1, 2, 5, 10, 15, 25, 50, 75, 90]
GAP_GRID = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 7.5, 10.0]


def clamp(value, lo=0.0, hi=10.0):
    return max(lo, min(hi, value))


def interpolate(x, anchors):
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


def relativa(gap_pct, top_pct):
    return clamp(
        ABS_WEIGHT * wr_score(gap_pct)
        + FIELD_WEIGHT * percentile_score(top_pct)
    )


def grade_band(score):
    if score >= 9.0:
        return "WORLD-CLASS"
    if score >= 8.0:
        return "ELITE"
    if score >= 7.0:
        return "VERY STRONG"
    if score >= 6.0:
        return "COMPETITIVE"
    if score >= 5.0:
        return "MID-FIELD"
    if score >= 4.0:
        return "BELOW MID-FIELD"
    return "DEVELOPING"


def build_matrix():
    rows = []
    for top_pct in TOP_PCT_GRID:
        row = {
            "top_percent": top_pct,
            "field_component": percentile_score(top_pct),
            "scores": {},
        }
        for gap in GAP_GRID:
            row["scores"][str(gap)] = relativa(gap, top_pct)
        rows.append(row)
    return rows


def build_scenarios():
    scenarios = [
        ("Near-WR world-class", 0.5, 0.1),
        ("Top 1% and very close to WR", 1.0, 1.0),
        ("Top 5% with strong absolute pace", 2.0, 5.0),
        ("Top 10% with strong absolute pace", 2.5, 10.0),
        ("Top 10% but larger WR gap", 4.0, 10.0),
        ("Top 25% with good absolute pace", 3.0, 25.0),
        ("Top 25% with weak absolute pace", 5.0, 25.0),
        ("Median grid with decent WR gap", 4.0, 50.0),
        ("Median grid with weak WR gap", 7.5, 50.0),
        ("Bottom quarter and weak WR gap", 7.5, 75.0),
        ("Bottom 10% and far from WR", 10.0, 90.0),
    ]

    return [
        {
            "label": label,
            "gap_to_wr_percent": gap,
            "top_percent": top,
            "absolute_component": wr_score(gap),
            "field_component": percentile_score(top),
            "relative_score": relativa(gap, top),
            "band": grade_band(relativa(gap, top)),
        }
        for label, gap, top in scenarios
    ]


def validation_checks(matrix, scenarios):
    checks = []

    # Monotonicity: at fixed Top %, getting closer to WR must never reduce score.
    abs_monotonic = True
    for row in matrix:
        vals = [row["scores"][str(g)] for g in GAP_GRID]
        if any(a < b for a, b in zip(vals, vals[1:])):
            abs_monotonic = False
            break
    checks.append({"check": "Closer WR gap always improves score", "passed": abs_monotonic})

    # Monotonicity: at fixed WR gap, better percentile must never reduce score.
    field_monotonic = True
    for gap in GAP_GRID:
        vals = [next(row for row in matrix if row["top_percent"] == t)["scores"][str(gap)] for t in TOP_PCT_GRID]
        if any(a < b for a, b in zip(vals, vals[1:])):
            field_monotonic = False
            break
    checks.append({"check": "Better Top % always improves score", "passed": field_monotonic})

    score_map = {item["label"]: item["relative_score"] for item in scenarios}
    checks.extend([
        {
            "check": "Near-WR world-class scenario reaches at least 9.5",
            "passed": score_map["Near-WR world-class"] >= 9.5,
        },
        {
            "check": "Top 1% +1% WR reaches at least 9.0",
            "passed": score_map["Top 1% and very close to WR"] >= 9.0,
        },
        {
            "check": "Strong Top 5% scenario reaches at least 8.0",
            "passed": score_map["Top 5% with strong absolute pace"] >= 8.0,
        },
        {
            "check": "Strong Top 10% scenario sits near 7.0-8.0",
            "passed": 7.0 <= score_map["Top 10% with strong absolute pace"] <= 8.0,
        },
        {
            "check": "Median scenario remains near scale midpoint",
            "passed": 4.5 <= score_map["Median grid with decent WR gap"] <= 6.0,
        },
        {
            "check": "Bottom 10% weak pace remains below 3.0",
            "passed": score_map["Bottom 10% and far from WR"] < 3.0,
        },
    ])

    return checks


def build_report(matrix, scenarios, checks):
    lines = [
        f"GT7 RELATIVA SCALE VALIDATION V{VERSION}",
        SEP,
        "Purpose: validate the interpretation and monotonic behavior of the proposed Relativa 0-10 scale.",
        "Candidate formula: 50% WR proximity + 50% actual leaderboard percentile.",
        "Production modified: NO",
        "",
        "SCENARIO TESTS",
        SUB,
        f"{'Scenario':<43} {'Gap WR':>8} {'Top %':>8} {'WRcmp':>7} {'Grid':>7} {'Rel':>6} {'Band':<18}",
    ]

    for item in scenarios:
        lines.append(
            f"{item['label']:<43} "
            f"{item['gap_to_wr_percent']:>7.1f}% "
            f"{item['top_percent']:>7.1f}% "
            f"{item['absolute_component']:>7.2f} "
            f"{item['field_component']:>7.2f} "
            f"{item['relative_score']:>6.2f} "
            f"{item['band']:<18}"
        )

    lines.extend([
        "",
        "FULL SCALE MATRIX",
        SUB,
        "Rows = Top % in leaderboard | Columns = gap to WR",
        f"{'Top %':>7} " + " ".join(f"+{gap:>4.1f}%" for gap in GAP_GRID),
    ])

    for row in matrix:
        lines.append(
            f"{row['top_percent']:>6.1f}% "
            + " ".join(f"{row['scores'][str(gap)]:>6.2f}" for gap in GAP_GRID)
        )

    lines.extend(["", "VALIDATION CHECKS", SUB])
    for check in checks:
        lines.append(f"{'PASS' if check['passed'] else 'FAIL':<5} | {check['check']}")

    passed = sum(1 for item in checks if item["passed"])
    lines.extend([
        "",
        "SUMMARY",
        SUB,
        f"Checks passed: {passed}/{len(checks)}",
        "Recommended interpretation bands:",
        "  9.0-10.0 = WORLD-CLASS",
        "  8.0-8.99 = ELITE",
        "  7.0-7.99 = VERY STRONG",
        "  6.0-6.99 = COMPETITIVE",
        "  5.0-5.99 = MID-FIELD",
        "  4.0-4.99 = BELOW MID-FIELD",
        "  <4.0     = DEVELOPING",
        "",
        "If all checks pass and the matrix is judged intuitive, this 50/50 scale is suitable",
        "for promotion to production followed by historical recalculation.",
        SEP,
    ])
    return "\n".join(lines) + "\n"


def main():
    matrix = build_matrix()
    scenarios = build_scenarios()
    checks = validation_checks(matrix, scenarios)

    payload = {
        "version": VERSION,
        "status": "STUDY_ONLY",
        "production_formula_modified": False,
        "formula": {
            "absolute_wr_weight": ABS_WEIGHT,
            "field_percentile_weight": FIELD_WEIGHT,
        },
        "matrix": matrix,
        "scenarios": scenarios,
        "checks": checks,
        "all_checks_passed": all(item["passed"] for item in checks),
    }

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    report = build_report(matrix, scenarios, checks)
    OUTPUT_REPORT.write_text(report, encoding="utf-8")
    print(report)
    print(f"Saved: {OUTPUT_JSON}")
    print(f"Saved: {OUTPUT_REPORT}")


if __name__ == "__main__":
    main()
