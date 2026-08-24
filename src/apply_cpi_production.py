from __future__ import annotations

import json
import re
from pathlib import Path

DATA_DIR = Path("data")
REPORT_DIR = Path("reports")
HISTORY_FILE = DATA_DIR / "weekly_rating_history.json"
LATEST_SNAPSHOT_FILE = DATA_DIR / "latest_snapshot.json"
CPI_SUMMARY_FILE = DATA_DIR / "cpi_history_summary.json"
LATEST_REPORT_FILE = REPORT_DIR / "latest.txt"
CPI_HISTORY_REPORT = REPORT_DIR / "cpi_history.txt"

ABS_WEIGHT = 0.50
FIELD_WEIGHT = 0.50


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


def wr_component(gap_pct):
    anchors = [
        (0.0, 10.0), (0.5, 9.5), (1.0, 9.0), (2.0, 8.0),
        (3.0, 7.0), (4.0, 6.0), (5.0, 5.0), (7.5, 3.5),
        (10.0, 2.0), (15.0, 0.5), (20.0, 0.0),
    ]
    return clamp(interpolate(float(gap_pct), anchors))


def field_component(top_pct):
    anchors = [
        (0.0, 10.0), (0.1, 9.8), (0.5, 9.4), (1.0, 9.0),
        (2.0, 8.6), (5.0, 8.0), (10.0, 7.0), (15.0, 6.5),
        (25.0, 6.0), (50.0, 5.0), (75.0, 3.5), (90.0, 2.0),
        (100.0, 0.0),
    ]
    return clamp(interpolate(float(top_pct), anchors))


def calculate_cpi(top_pct, wr_percentage):
    if not isinstance(top_pct, (int, float)) or not isinstance(wr_percentage, (int, float)):
        return None
    gap = max(0.0, float(wr_percentage) - 100.0)
    return clamp(ABS_WEIGHT * wr_component(gap) + FIELD_WEIGHT * field_component(float(top_pct)))


def cpi_band(score):
    if score is None:
        return "N/A"
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


def fmt(value, decimals=2):
    return f"{value:.{decimals}f}" if isinstance(value, (int, float)) else "N/A"


def average(values):
    clean = [float(v) for v in values if isinstance(v, (int, float))]
    return sum(clean) / len(clean) if clean else None


def trend(records, key, higher_is_better=True, count=8):
    vals = [r.get(key) for r in records[-count:] if isinstance(r.get(key), (int, float))]
    if len(vals) < 3:
        return "INSUFFICIENT HISTORY"
    xs = list(range(len(vals)))
    xm = sum(xs) / len(xs)
    ym = sum(vals) / len(vals)
    den = sum((x - xm) ** 2 for x in xs)
    if den == 0:
        return "STABLE"
    slope = sum((x - xm) * (y - ym) for x, y in zip(xs, vals)) / den
    effective = slope if higher_is_better else -slope
    if effective > 0.02:
        return "IMPROVING"
    if effective < -0.02:
        return "DECLINING"
    return "STABLE"


def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def migrate_history():
    history = load_json(HISTORY_FILE, [])
    if not isinstance(history, list):
        history = []

    changed = False
    for record in history:
        if not isinstance(record, dict) or record.get("participated") is not True:
            continue
        score = calculate_cpi(record.get("top_percent"), record.get("wr_percentage"))
        if score is None:
            continue

        if "legacy_elite_score" not in record and isinstance(record.get("elite_score"), (int, float)):
            record["legacy_elite_score"] = record.get("elite_score")
        if "legacy_general_score" not in record and isinstance(record.get("general_score"), (int, float)):
            record["legacy_general_score"] = record.get("general_score")
        if "legacy_composite_rating" not in record and isinstance(record.get("composite_rating"), (int, float)):
            record["legacy_composite_rating"] = record.get("composite_rating")

        record["cpi_score"] = score
        record["cpi_band"] = cpi_band(score)
        # Compatibility: some historical code still reads elite_score.
        record["elite_score"] = score
        record["rating_model"] = "CPI_50_50_V1"
        changed = True

    if changed:
        save_json(HISTORY_FILE, history)
    history.sort(key=lambda r: r.get("week_start", ""))
    return history


def migrate_latest_snapshot():
    snapshot = load_json(LATEST_SNAPSHOT_FILE, {})
    if not isinstance(snapshot, dict):
        return {}
    my = snapshot.get("my_result")
    if not isinstance(my, dict):
        return snapshot

    score = calculate_cpi(my.get("top_percent"), my.get("wr_percentage"))
    if score is None:
        return snapshot

    if "legacy_elite_score" not in my and isinstance(my.get("elite_score"), (int, float)):
        my["legacy_elite_score"] = my.get("elite_score")
    if "legacy_general_score" not in my and isinstance(my.get("position_score"), (int, float)):
        my["legacy_general_score"] = my.get("position_score")
    if "legacy_composite_rating" not in my and isinstance(my.get("composite_rating"), (int, float)):
        my["legacy_composite_rating"] = my.get("composite_rating")

    my["cpi_score"] = score
    my["cpi_band"] = cpi_band(score)
    my["elite_score"] = score
    my["rating_model"] = "CPI_50_50_V1"
    save_json(LATEST_SNAPSHOT_FILE, snapshot)
    return snapshot


def build_history_section(history, snapshot):
    finals = [r for r in history if isinstance(r, dict) and r.get("participated") is True and isinstance(r.get("cpi_score"), (int, float))]
    my = (snapshot.get("my_result") or {}) if isinstance(snapshot, dict) else {}
    current_cpi = my.get("cpi_score")
    current_top = my.get("top_percent")
    current_wr = my.get("wr_percentage")

    lines = [
        "LONG-TERM COMPETITIVE PERFORMANCE",
        "CPI = Competitive Performance Index | 50% WR proximity + 50% leaderboard percentile",
        "Higher CPI is better. Lower Top % and WR gap are better.",
        "",
        "CURRENT WEEK",
        f"CPI        : {fmt(current_cpi)} / 10 | {cpi_band(current_cpi)}",
        f"Top %      : {fmt(current_top)}%",
        f"WR gap     : +{fmt((current_wr - 100.0) if isinstance(current_wr, (int, float)) else None, 3)}%",
    ]

    if finals:
        latest = finals[-1]
        lines.extend([
            "",
            "LATEST FINALIZED WEEK",
            f"Week       : {latest.get('week_start', 'N/A')}",
            f"CPI        : {fmt(latest.get('cpi_score'))} / 10 | {latest.get('cpi_band', 'N/A')}",
            f"Top %      : {fmt(latest.get('top_percent'))}%",
            f"WR gap     : +{fmt((latest.get('wr_percentage') - 100.0) if isinstance(latest.get('wr_percentage'), (int, float)) else None, 3)}%",
        ])

        if isinstance(current_cpi, (int, float)):
            dcpi = current_cpi - latest.get("cpi_score", current_cpi)
            dtop = current_top - latest.get("top_percent", current_top) if isinstance(current_top, (int, float)) and isinstance(latest.get("top_percent"), (int, float)) else None
            dwr = current_wr - latest.get("wr_percentage", current_wr) if isinstance(current_wr, (int, float)) and isinstance(latest.get("wr_percentage"), (int, float)) else None
            lines.extend([
                "",
                "CURRENT WEEK VS LAST FINALIZED WEEK",
                f"CPI        : {fmt(latest.get('cpi_score'))} -> {fmt(current_cpi)} ({dcpi:+.2f})",
                f"Top %      : {fmt(latest.get('top_percent'))}% -> {fmt(current_top)}% ({dtop:+.2f} pp)" if dtop is not None else "Top %      : N/A",
                f"WR gap     : +{fmt(latest.get('wr_percentage') - 100.0, 3)}% -> +{fmt(current_wr - 100.0, 3)}% ({dwr:+.3f} pp)" if dwr is not None else "WR gap     : N/A",
            ])

        recent = finals[-4:]
        lines.extend([
            "",
            "4-WEEK FINALIZED MOVING AVERAGE",
            f"CPI        : {fmt(average([r.get('cpi_score') for r in recent]))}",
            f"Top %      : {fmt(average([r.get('top_percent') for r in recent]))}%",
            f"WR gap     : +{fmt((average([r.get('wr_percentage') for r in recent]) - 100.0) if average([r.get('wr_percentage') for r in recent]) is not None else None, 3)}%",
            "",
            "8-WEEK FINALIZED TREND",
            f"CPI        : {trend(finals, 'cpi_score', True)}",
            f"Top %      : {trend(finals, 'top_percent', False)}",
            f"WR gap     : {trend(finals, 'wr_percentage', False)}",
            "",
            "LAST FINALIZED RACES",
        ])
        for r in finals[-8:]:
            gap = (r.get("wr_percentage") - 100.0) if isinstance(r.get("wr_percentage"), (int, float)) else None
            lines.append(
                f"- {r.get('week_start', 'N/A')} | CPI {fmt(r.get('cpi_score'))} | Top {fmt(r.get('top_percent'))}% | WR +{fmt(gap, 3)}%"
            )

    return "\n".join(lines) + "\n"


def build_summary(history, snapshot):
    finals = [r for r in history if isinstance(r.get("cpi_score"), (int, float))]
    my = (snapshot.get("my_result") or {}) if isinstance(snapshot, dict) else {}
    summary = {
        "model": "CPI_50_50_V1",
        "name": "Competitive Performance Index",
        "formula": {"wr_proximity_weight": ABS_WEIGHT, "leaderboard_percentile_weight": FIELD_WEIGHT},
        "current": {
            "cpi_score": my.get("cpi_score"),
            "cpi_band": my.get("cpi_band"),
            "top_percent": my.get("top_percent"),
            "wr_percentage": my.get("wr_percentage"),
        },
        "finalized_races": len(finals),
        "cpi_trend_8": trend(finals, "cpi_score", True),
        "top_percent_trend_8": trend(finals, "top_percent", False),
        "wr_percentage_trend_8": trend(finals, "wr_percentage", False),
    }
    save_json(CPI_SUMMARY_FILE, summary)
    return summary


def simplify_report(report_text, history_section, snapshot):
    lines = report_text.splitlines()
    out = []
    skipping_long_term = False
    inserted_history = False
    my = (snapshot.get("my_result") or {}) if isinstance(snapshot, dict) else {}
    cpi = my.get("cpi_score")
    band = my.get("cpi_band")

    for line in lines:
        stripped = line.strip()

        if stripped == "LONG-TERM RATING TREND" or stripped == "LONG-TERM COMPETITIVE PERFORMANCE":
            skipping_long_term = True
            continue

        if skipping_long_term:
            if stripped == "DATA QUALITY / HEALTH":
                skipping_long_term = False
                if not inserted_history:
                    out.extend(history_section.rstrip("\n").splitlines())
                    out.append("")
                    inserted_history = True
                out.append(line)
            continue

        # Remove deprecated presentation metrics everywhere.
        if re.match(r"^(General rating|General\s*:|Elite rating|Elite\s*:|Relativa rating|Relativa\s*:|Composite\s*:)", stripped, flags=re.IGNORECASE):
            continue

        # In snapshot-change sections, remove old rating delta lines.
        if re.match(r"^(General rating|Elite rating|Relativa rating|Composite)", stripped, flags=re.IGNORECASE):
            continue

        out.append(line)

        # Add CPI immediately after WR percentage in the main current-week block.
        if stripped.startswith("WR percentage") and isinstance(cpi, (int, float)):
            out.append(f"CPI             : {cpi:.2f} / 10 | {band}")

    if not inserted_history:
        # Fallback for unexpected report layouts.
        out.append("")
        out.extend(history_section.rstrip("\n").splitlines())

    # Collapse excessive blank lines after removals.
    cleaned = []
    blank_count = 0
    for line in out:
        if line.strip() == "":
            blank_count += 1
            if blank_count <= 2:
                cleaned.append(line)
        else:
            blank_count = 0
            cleaned.append(line)
    return "\n".join(cleaned).rstrip() + "\n"


def main():
    history = migrate_history()
    snapshot = migrate_latest_snapshot()
    history_section = build_history_section(history, snapshot)
    build_summary(history, snapshot)

    CPI_HISTORY_REPORT.parent.mkdir(parents=True, exist_ok=True)
    CPI_HISTORY_REPORT.write_text(history_section, encoding="utf-8")

    if LATEST_REPORT_FILE.exists():
        text = LATEST_REPORT_FILE.read_text(encoding="utf-8")
        LATEST_REPORT_FILE.write_text(
            simplify_report(text, history_section, snapshot),
            encoding="utf-8",
        )

    print("CPI production model applied.")
    print("Deprecated General/Composite metrics retained only as legacy compatibility fields.")
    print(f"Finalized records recalculated: {len(history)}")
    print(history_section)


if __name__ == "__main__":
    main()