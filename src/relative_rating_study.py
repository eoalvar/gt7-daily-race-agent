from __future__ import annotations

import json
import math
from pathlib import Path

import requests

import recover_historical_race as recovery


VERSION = "0.1"
HISTORY_FILE = Path("data/weekly_rating_history.json")
OUTPUT_JSON = Path("data/relative_rating_study.json")
OUTPUT_REPORT = Path("reports/relative_rating_study.txt")

# Enough recent independent races to compare different groups/tracks without
# making this diagnostic workflow unnecessarily slow.
MAX_RACES = 8

# Percentile anchors are expressed as the fraction of the leaderboard ahead.
# Example: 1 means Top 1%, 15 means Top 15%.
ANCHORS = [0.1, 0.5, 1, 2, 5, 10, 15, 25, 50, 75, 90]

SEPARATOR = "=" * 94
SUB = "-" * 94


def load_history():
    data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    records = [
        item for item in data
        if isinstance(item, dict)
        and item.get("participated") is True
        and item.get("leaderboard_url")
        and item.get("week_start")
    ]
    records.sort(key=lambda item: item["week_start"])
    return records[-MAX_RACES:]


def score_at_top_percent(scores, top_percent):
    if not scores:
        return None
    rank = max(1, min(len(scores), math.ceil(len(scores) * top_percent / 100)))
    return scores[rank - 1]


def gap_percent(score, wr_score):
    return ((score / wr_score) - 1.0) * 100.0


def quantile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * fraction
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    weight = pos - lo
    return ordered[lo] * (1 - weight) + ordered[hi] * weight


def parse_group(race_text):
    import re
    match = re.match(r"^C\s+(Gr\.[1234]|Gr\.B)\b", str(race_text or ""), flags=re.IGNORECASE)
    return match.group(1) if match else "N/A"


def analyse_race(session, record):
    result = recovery.get_full_event_ranking(session, record["leaderboard_url"])
    ranking = result["ranking"]
    scores = [
        int(driver["score"])
        for driver in ranking
        if isinstance(driver, dict) and isinstance(driver.get("score"), (int, float))
    ]
    scores.sort()
    if not scores:
        raise RuntimeError("Leaderboard has no valid scores")

    wr_score = scores[0]
    total = len(scores)
    my_score = record.get("score_ms")
    my_rank = record.get("position")
    if not isinstance(my_score, (int, float)) or not isinstance(my_rank, int):
        raise RuntimeError("Historical personal score/rank missing")

    all_gaps = [gap_percent(score, wr_score) for score in scores]
    user_gap = gap_percent(my_score, wr_score)

    anchors = {}
    for anchor in ANCHORS:
        anchor_score = score_at_top_percent(scores, anchor)
        anchors[str(anchor)] = {
            "top_percent": anchor,
            "rank": max(1, min(total, math.ceil(total * anchor / 100))),
            "score_ms": anchor_score,
            "gap_to_wr_percent": gap_percent(anchor_score, wr_score),
        }

    q25 = quantile(all_gaps, 0.25)
    q50 = quantile(all_gaps, 0.50)
    q75 = quantile(all_gaps, 0.75)
    iqr = q75 - q25 if q25 is not None and q75 is not None else None
    robust_z = None
    if iqr and iqr > 0:
        robust_z = (user_gap - q50) / iqr

    # Local density: proportion of the full field inside a narrow +/-0.10
    # percentage-point band around the user's WR gap. This captures how crowded
    # the actual time distribution is around the user's performance.
    band = 0.10
    local_count = sum(1 for value in all_gaps if abs(value - user_gap) <= band)

    return {
        "week_start": record["week_start"],
        "group": parse_group(record.get("race")),
        "race": record.get("race"),
        "drivers": total,
        "wr_score_ms": wr_score,
        "user_score_ms": int(my_score),
        "user_rank": my_rank,
        "user_top_percent": my_rank / total * 100,
        "user_gap_to_wr_percent": user_gap,
        "legacy_general": record.get("general_score"),
        "legacy_relativa": record.get("elite_score"),
        "gap_distribution": {
            "q25": q25,
            "median": q50,
            "q75": q75,
            "iqr": iqr,
            "user_robust_z": robust_z,
            "local_band_pp": band,
            "local_driver_count": local_count,
            "local_driver_percent": local_count / total * 100,
        },
        "anchors": anchors,
    }


def build_report(results):
    lines = [
        f"GT7 RELATIVA RATING STUDY V{VERSION}",
        SEPARATOR,
        "Purpose: redesign the former Elite rating using WR gap plus the real distribution of lap times.",
        "No production rating formula is changed by this study.",
        f"Races analysed: {len(results)}",
        "",
    ]

    for item in results:
        lines.extend([
            f"{item['week_start']} | {item['group']} | {item['drivers']:,} drivers",
            SUB,
            f"User Top %          : {item['user_top_percent']:.3f}%",
            f"User gap to WR      : +{item['user_gap_to_wr_percent']:.3f}%",
            f"Legacy General      : {item['legacy_general']:.2f}" if isinstance(item['legacy_general'], (int, float)) else "Legacy General      : N/A",
            f"Legacy Relativa     : {item['legacy_relativa']:.2f}" if isinstance(item['legacy_relativa'], (int, float)) else "Legacy Relativa     : N/A",
            f"Gap distribution    : Q25 +{item['gap_distribution']['q25']:.3f}% | Median +{item['gap_distribution']['median']:.3f}% | Q75 +{item['gap_distribution']['q75']:.3f}%",
            f"Robust position     : {item['gap_distribution']['user_robust_z']:.3f} IQR from median" if isinstance(item['gap_distribution']['user_robust_z'], (int, float)) else "Robust position     : N/A",
            f"Local density       : {item['gap_distribution']['local_driver_percent']:.2f}% of drivers within +/-0.10 pp of user's WR gap",
            "Distribution anchors:",
        ])
        for anchor in ANCHORS:
            data = item["anchors"][str(anchor)]
            lines.append(
                f"  Top {anchor:>4}% | rank {data['rank']:>6,} | gap to WR +{data['gap_to_wr_percent']:.3f}%"
            )
        lines.append("")

    lines.extend([
        "NEXT CALIBRATION STEP",
        SUB,
        "Use these empirical distributions to test candidate Relativa scales.",
        "The final formula should reward closeness to WR while adapting to how tightly or loosely the field is distributed.",
        "A formula will only replace the legacy logarithmic score after cross-race comparison is reviewed.",
        SEPARATOR,
    ])
    return "\n".join(lines) + "\n"


def main():
    if not HISTORY_FILE.exists():
        raise RuntimeError("data/weekly_rating_history.json not found")

    records = load_history()
    if not records:
        raise RuntimeError("No finalized participated races available")

    session = requests.Session()
    session.headers.update(recovery.HEADERS)

    results = []
    failures = []
    for index, record in enumerate(records, start=1):
        print(f"[{index}/{len(records)}] {record['week_start']}")
        try:
            results.append(analyse_race(session, record))
        except Exception as exc:
            failures.append({"week_start": record.get("week_start"), "error": str(exc)})
            print(f"FAILED: {exc}")

    if not results:
        raise RuntimeError("No race could be analysed")

    payload = {
        "version": VERSION,
        "status": "STUDY_ONLY",
        "production_formula_modified": False,
        "concept_name": "Relativa",
        "races_requested": len(records),
        "races_analysed": len(results),
        "failures": failures,
        "results": results,
    }

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUTPUT_REPORT.write_text(build_report(results), encoding="utf-8")

    print(build_report(results))
    print(f"Saved: {OUTPUT_JSON}")
    print(f"Saved: {OUTPUT_REPORT}")


if __name__ == "__main__":
    main()
