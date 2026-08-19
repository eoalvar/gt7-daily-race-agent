import json
from pathlib import Path

REPORT_FILE = Path("reports/latest.txt")
RECOMMENDATIONS_FILE = Path("data/bop_lab/weekly_car_recommendations.json")

TOP_N = 5
SEP = "=" * 78
SUB = "-" * 78


def safe_float(value):
    try:
        return float(value)
    except Exception:
        return None


def fmt_score(value):
    value = safe_float(value)
    return f"{value:.1f}" if value is not None else "N/A"


def fmt_pct_rank(value):
    value = safe_float(value)
    return f"{100.0 * value:.0f}%" if value is not None else "N/A"


def fmt_share(value):
    value = safe_float(value)
    return f"{value:.2f}%" if value is not None else "N/A"


def main():
    if not REPORT_FILE.exists():
        raise RuntimeError("reports/latest.txt not found")

    if not RECOMMENDATIONS_FILE.exists():
        print("Weekly recommendation file not found; email remains unchanged.")
        return

    payload = json.loads(RECOMMENDATIONS_FILE.read_text(encoding="utf-8"))
    cars = payload.get("cars") or []
    if not cars:
        print("Weekly recommendation ranking is empty; email remains unchanged.")
        return

    lines = [
        "",
        "CARS TO TEST THIS WEEK",
        SUB,
        (
            f"Model: {payload.get('model_key') or 'N/A'} | "
            f"Technical evidence: {fmt_pct_rank(payload.get('technical_reliability'))}"
        ),
        "SCI = current-week signal | SSI = structural signal | Tech = learned BoP/circuit fit",
        "",
    ]

    for row in cars[:TOP_N]:
        rank = row.get("recommendation_rank") or "-"
        car = row.get("car") or "Unknown car"
        recommendation = row.get("recommendation") or "N/A"
        sci = fmt_score(row.get("current_sci"))
        ssi = fmt_score(row.get("calibrated_ssi"))
        tech = fmt_pct_rank(row.get("technical_percentile_adjusted"))
        consensus = fmt_pct_rank(row.get("consensus_percentile"))
        share = fmt_share(row.get("current_share_percent"))
        best_rank = row.get("best_rank")
        best_rank_text = f"#{best_rank}" if best_rank is not None else "N/A"

        lines.append(
            f"{rank}. {car} | {recommendation} | "
            f"Consensus {consensus} | SCI {sci} | SSI {ssi} | Tech {tech} | "
            f"Usage {share} | Best {best_rank_text}"
        )

    lines += [
        "",
        "Note: this ranking is an experimental decision-support layer and does not replace the current leaderboard benchmarks.",
        SEP,
    ]

    original = REPORT_FILE.read_text(encoding="utf-8").rstrip()
    REPORT_FILE.write_text(original + "\n" + "\n".join(lines) + "\n", encoding="utf-8")
    print(f"Appended Top {min(TOP_N, len(cars))} weekly car recommendations to reports/latest.txt")


if __name__ == "__main__":
    main()
