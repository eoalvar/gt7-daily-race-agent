import json
import math
from collections import defaultdict
from pathlib import Path
from datetime import datetime

CURRENT_FILE = Path("data/bop_lab/sleeper_car_index.json")
HISTORY_FILE = Path("data/bop_lab/sleeper_training_history.json")
OUT_FILE = Path("data/bop_lab/structural_sleeper_index.json")
REPORT_FILE = Path("reports/sleeper_car_lab.txt")

VERSION = "0.1"
MIN_INDEPENDENT_RACES = 3
MIN_APPEARANCES = 2
SEP = "=" * 100
SUB = "-" * 100


def now_iso():
    return datetime.now().astimezone().isoformat()


def safe_float(value):
    try:
        return float(value)
    except Exception:
        return None


def percentile_rank(value, values):
    clean = sorted(float(v) for v in values if v is not None)
    if value is None or not clean:
        return None
    v = float(value)
    below = sum(1 for x in clean if x < v)
    equal = sum(1 for x in clean if x == v)
    # Mid-rank percentile. 0 = lowest, 1 = highest.
    return (below + 0.5 * equal) / len(clean)


def mean(values):
    vals = [float(v) for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def stdev(values):
    vals = [float(v) for v in values if v is not None]
    if len(vals) < 2:
        return None
    m = sum(vals) / len(vals)
    return math.sqrt(sum((x - m) ** 2 for x in vals) / len(vals))


def label(item, model_races):
    n = item["appearances"]
    diff = item["mean_sleeper_differential"]
    positive = item["positive_signal_rate"]
    perf = item["mean_performance_percentile"]

    if model_races < MIN_INDEPENDENT_RACES:
        return "MODEL NOT READY"
    if n < MIN_APPEARANCES:
        return "INSUFFICIENT HISTORY"
    if diff is not None and diff >= 0.30 and positive >= 0.67 and perf >= 0.65:
        return "STRUCTURAL SLEEPER"
    if diff is not None and diff >= 0.18 and positive >= 0.50 and perf >= 0.58:
        return "STRUCTURAL SLEEPER CANDIDATE"
    if perf is not None and perf >= 0.75 and item["mean_usage_percentile"] >= 0.70:
        return "STRUCTURAL META"
    if diff is not None and diff >= 0.08:
        return "WATCHLIST"
    return "NO STRUCTURAL SIGNAL"


def confidence(appearances, model_races):
    if appearances >= 6 and model_races >= 6:
        return "HIGH"
    if appearances >= 4 and model_races >= 4:
        return "MEDIUM"
    if appearances >= 2:
        return "LOW-MEDIUM"
    return "LOW"


def main():
    current = json.loads(CURRENT_FILE.read_text(encoding="utf-8"))
    history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))

    group = current.get("group")
    speed = str(current.get("speed_class") or "").upper()
    model_key = f"{group}|{speed}"

    peers = [
        race for race in history.get("races", [])
        if race.get("group") == group
        and str(race.get("speed_class") or "").upper() == speed
        and race.get("week_start")
    ]

    # Defensive de-duplication by independent week.
    by_week = {}
    for race in peers:
        wk = race.get("week_start")
        old = by_week.get(wk)
        if old is None or str(race.get("captured_at") or "") >= str(old.get("captured_at") or ""):
            by_week[wk] = race
    peers = [by_week[wk] for wk in sorted(by_week)]

    observations = defaultdict(list)

    for race in peers:
        total = safe_float(race.get("total_drivers")) or 0.0
        cars = race.get("cars") or []
        perf_values = [safe_float(c.get("performance_target")) for c in cars]
        shares = [
            (safe_float(c.get("sample")) or 0.0) / total if total > 0 else None
            for c in cars
        ]

        for car, share in zip(cars, shares):
            code = car.get("car_code")
            name = car.get("car")
            perf = safe_float(car.get("performance_target"))
            if code is None or perf is None or share is None:
                continue

            perf_pct = percentile_rank(perf, perf_values)
            usage_pct = percentile_rank(share, shares)
            if perf_pct is None or usage_pct is None:
                continue

            # Positive when a car's performance rank exceeds its adoption rank.
            differential = perf_pct - usage_pct
            observations[code].append({
                "week_start": race.get("week_start"),
                "track": race.get("track"),
                "status": race.get("status"),
                "car": name,
                "sample": int(safe_float(car.get("sample")) or 0),
                "share": share,
                "performance_target": perf,
                "performance_percentile": perf_pct,
                "usage_percentile": usage_pct,
                "sleeper_differential": differential,
            })

    current_by_code = {
        item.get("car_code"): item
        for item in current.get("ranking") or []
        if item.get("car_code") is not None
    }

    ranking = []
    for code, obs in observations.items():
        diffs = [o["sleeper_differential"] for o in obs]
        perfs = [o["performance_percentile"] for o in obs]
        usages = [o["usage_percentile"] for o in obs]
        mean_diff = mean(diffs)
        positive_rate = sum(1 for d in diffs if d > 0) / len(diffs)
        perf_mean = mean(perfs)
        usage_mean = mean(usages)

        # Purely ordinal score: no hand-picked technical feature coefficients.
        # Differential spans [-1, +1]; 50 is neutral, 100 is maximum sleeper separation.
        structural_score = max(0.0, min(100.0, 50.0 + 50.0 * (mean_diff or 0.0)))

        current_item = current_by_code.get(code) or {}
        item = {
            "car_code": code,
            "car": obs[-1].get("car") or current_item.get("car"),
            "appearances": len(obs),
            "model_independent_races": len(peers),
            "appearance_rate": len(obs) / len(peers) if peers else 0.0,
            "mean_performance_percentile": perf_mean,
            "mean_usage_percentile": usage_mean,
            "mean_sleeper_differential": mean_diff,
            "differential_stdev": stdev(diffs),
            "positive_signal_rate": positive_rate,
            "structural_sleeper_score": structural_score,
            "current_sci": safe_float(current_item.get("sleeper_score")),
            "current_label": current_item.get("sleeper_label"),
            "current_share_percent": safe_float(current_item.get("share_percent")),
            "observations": obs,
        }
        item["structural_label"] = label(item, len(peers))
        item["confidence"] = confidence(len(obs), len(peers))
        ranking.append(item)

    ranking.sort(
        key=lambda x: (
            x["structural_sleeper_score"],
            x["appearances"],
            x["positive_signal_rate"],
        ),
        reverse=True,
    )

    payload = {
        "generated_at": now_iso(),
        "version": VERSION,
        "model_key": model_key,
        "group": group,
        "speed_class": speed,
        "independent_races": len(peers),
        "independent_weeks": [r.get("week_start") for r in peers],
        "status": "READY" if len(peers) >= MIN_INDEPENDENT_RACES else "BOOTSTRAP",
        "method": {
            "name": "cross-race performance-vs-adoption percentile differential",
            "performance_measure": "within-race percentile of performance_target",
            "adoption_measure": "within-race percentile of driver share",
            "differential": "performance_percentile - usage_percentile",
            "score": "50 + 50 * mean(differential)",
            "neutral_score": 50,
            "minimum_independent_races": MIN_INDEPENDENT_RACES,
            "minimum_car_appearances": MIN_APPEARANCES,
            "technical_feature_weight": 0.0,
            "note": "This layer tests repeatability of sleeper behavior across independent races. It does not use hand-picked technical coefficients.",
        },
        "cars": ranking,
    }

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "",
        "STRUCTURAL SLEEPER MODEL V0.1",
        SUB,
        f"Model key            : {model_key}",
        f"Status               : {payload['status']}",
        f"Independent races    : {len(peers)} / {MIN_INDEPENDENT_RACES} minimum",
        f"Independent weeks    : {', '.join(payload['independent_weeks']) if peers else 'N/A'}",
        "Method               : performance percentile minus usage percentile across independent races.",
        "Neutral score        : 50.0",
        "Technical weight     : 0.0",
        "",
        "TOP STRUCTURAL SLEEPER SIGNALS",
        SUB,
    ]

    for i, item in enumerate(ranking[:15], 1):
        lines.append(
            f"{i:>2}. {item['car']} | SSI {item['structural_sleeper_score']:.1f} | "
            f"{item['structural_label']} | races {item['appearances']}/{len(peers)} | "
            f"PerfPct {item['mean_performance_percentile']:.3f} | "
            f"UsePct {item['mean_usage_percentile']:.3f} | "
            f"Diff {item['mean_sleeper_differential']:+.3f} | "
            f"Positive {item['positive_signal_rate']:.0%} | Conf {item['confidence']}"
        )

    lines += [
        "",
        "INTERPRETATION",
        SUB,
        "SSI above 50 means the car repeatedly ranks better in performance than in adoption.",
        "SSI below 50 means adoption tends to exceed the car's relative performance rank.",
        "With only three independent races, labels remain provisional and confidence is intentionally limited.",
    ]

    old_report = REPORT_FILE.read_text(encoding="utf-8") if REPORT_FILE.exists() else ""
    REPORT_FILE.write_text(old_report.rstrip() + "\n" + "\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
