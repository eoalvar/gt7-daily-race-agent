import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from datetime import datetime

CURRENT_FILE = Path("data/bop_lab/sleeper_car_index.json")
HISTORY_FILE = Path("data/bop_lab/sleeper_training_history.json")
OUT_FILE = Path("data/bop_lab/structural_sleeper_index.json")
REPORT_FILE = Path("reports/sleeper_car_lab.txt")

VERSION = "0.2"
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


def calibrated_label(item, model_races):
    if model_races < MIN_INDEPENDENT_RACES:
        return "MODEL NOT READY"
    if item["appearances"] < MIN_APPEARANCES:
        return "INSUFFICIENT HISTORY"

    score = item["calibrated_structural_score"]
    positive = item["positive_signal_rate"]
    perf = item["mean_performance_percentile"]
    evidence = item["evidence_factor"]

    if score >= 72 and positive >= 0.67 and perf >= 0.65 and evidence >= 0.55:
        return "ROBUST STRUCTURAL SLEEPER"
    if score >= 64 and positive >= 0.67 and perf >= 0.60:
        return "STRUCTURAL SLEEPER"
    if score >= 58 and positive >= 0.50 and perf >= 0.55:
        return "STRUCTURAL SLEEPER CANDIDATE"
    if perf is not None and perf >= 0.75 and item["mean_usage_percentile"] >= 0.70:
        return "STRUCTURAL META"
    if score >= 54:
        return "WATCHLIST"
    return "NO STRUCTURAL SIGNAL"


def confidence(item, model_races):
    evidence = item["evidence_factor"]
    appearances = item["appearances"]

    if model_races >= 6 and appearances >= 6 and evidence >= 0.80:
        return "HIGH"
    if appearances >= 4 and evidence >= 0.65:
        return "MEDIUM"
    if appearances >= 3 and evidence >= 0.50:
        return "MEDIUM-LOW"
    if appearances >= 2:
        return "LOW-MEDIUM"
    return "LOW"


def practical_status(item):
    current_present = item["current_sci"] is not None
    structural = item["structural_label"]
    current_sci = item["current_sci"]

    if current_present and structural == "ROBUST STRUCTURAL SLEEPER":
        return "PRIORITY TEST - STRUCTURAL + CURRENT"
    if current_present and structural in {"STRUCTURAL SLEEPER", "STRUCTURAL SLEEPER CANDIDATE"}:
        return "TEST THIS WEEK"
    if not current_present and structural in {"ROBUST STRUCTURAL SLEEPER", "STRUCTURAL SLEEPER"}:
        return "HISTORICAL SIGNAL ONLY - NOT CURRENTLY CONFIRMED"
    if current_present and current_sci is not None and current_sci >= 60:
        return "CURRENT-WEEK SIGNAL ONLY"
    return "NO PRIORITY"


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
            sample = int(safe_float(car.get("sample")) or 0)
            if code is None or perf is None or share is None:
                continue

            perf_pct = percentile_rank(perf, perf_values)
            usage_pct = percentile_rank(share, shares)
            if perf_pct is None or usage_pct is None:
                continue

            observations[code].append({
                "week_start": race.get("week_start"),
                "track": race.get("track"),
                "status": race.get("status"),
                "car": name,
                "sample": sample,
                "share": share,
                "performance_target": perf,
                "performance_percentile": perf_pct,
                "usage_percentile": usage_pct,
                "sleeper_differential": perf_pct - usage_pct,
            })

    current_by_code = {
        item.get("car_code"): item
        for item in current.get("ranking") or []
        if item.get("car_code") is not None
    }

    # Data-driven evidence benchmark: median accumulated sample among cars in this model.
    # This avoids selecting a fixed driver-count threshold by hand.
    total_samples = [sum(o["sample"] for o in obs) for obs in observations.values() if obs]
    sample_benchmark = statistics.median(total_samples) if total_samples else 1.0
    sample_benchmark = max(1.0, float(sample_benchmark))

    ranking = []
    for code, obs in observations.items():
        diffs = [o["sleeper_differential"] for o in obs]
        perfs = [o["performance_percentile"] for o in obs]
        usages = [o["usage_percentile"] for o in obs]
        mean_diff = mean(diffs) or 0.0
        positive_rate = sum(1 for d in diffs if d > 0) / len(diffs)
        perf_mean = mean(perfs)
        usage_mean = mean(usages)

        raw_score = max(0.0, min(100.0, 50.0 + 50.0 * mean_diff))

        appearances = len(obs)
        appearance_rate = appearances / len(peers) if peers else 0.0
        total_sample = sum(o["sample"] for o in obs)

        # Evidence calibration:
        # 1) a car seen in fewer independent races is less certain;
        # 2) a car with a smaller accumulated driver sample is less certain.
        # The sample benchmark is empirical (median of this model), not a hand-picked constant.
        sample_reliability = total_sample / (total_sample + sample_benchmark)
        evidence_factor = math.sqrt(max(0.0, appearance_rate * sample_reliability))

        calibrated_diff = mean_diff * evidence_factor
        calibrated_score = max(0.0, min(100.0, 50.0 + 50.0 * calibrated_diff))

        current_item = current_by_code.get(code) or {}
        item = {
            "car_code": code,
            "car": obs[-1].get("car") or current_item.get("car"),
            "appearances": appearances,
            "model_independent_races": len(peers),
            "appearance_rate": appearance_rate,
            "total_driver_sample": total_sample,
            "sample_benchmark": sample_benchmark,
            "sample_reliability": sample_reliability,
            "evidence_factor": evidence_factor,
            "mean_performance_percentile": perf_mean,
            "mean_usage_percentile": usage_mean,
            "mean_sleeper_differential": mean_diff,
            "calibrated_sleeper_differential": calibrated_diff,
            "differential_stdev": stdev(diffs),
            "positive_signal_rate": positive_rate,
            "raw_structural_score": raw_score,
            "calibrated_structural_score": calibrated_score,
            "structural_sleeper_score": calibrated_score,
            "current_sci": safe_float(current_item.get("sleeper_score")),
            "current_label": current_item.get("sleeper_label"),
            "current_share_percent": safe_float(current_item.get("share_percent")),
            "current_week_present": code in current_by_code,
            "observations": obs,
        }
        item["structural_label"] = calibrated_label(item, len(peers))
        item["confidence"] = confidence(item, len(peers))
        item["practical_status"] = practical_status(item)
        ranking.append(item)

    ranking.sort(
        key=lambda x: (
            x["calibrated_structural_score"],
            x["evidence_factor"],
            x["positive_signal_rate"],
        ),
        reverse=True,
    )

    practical_ranking = [
        item for item in ranking
        if item["current_week_present"]
        and item["practical_status"] in {
            "PRIORITY TEST - STRUCTURAL + CURRENT",
            "TEST THIS WEEK",
            "CURRENT-WEEK SIGNAL ONLY",
        }
    ]

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
            "name": "evidence-calibrated cross-race performance-vs-adoption differential",
            "raw_signal": "performance_percentile - usage_percentile",
            "raw_score": "50 + 50 * mean(raw_signal)",
            "sample_benchmark": "median accumulated driver sample across cars in the active model",
            "sample_reliability": "car_total_sample / (car_total_sample + model_median_total_sample)",
            "appearance_reliability": "car_appearances / model_independent_races",
            "evidence_factor": "sqrt(appearance_reliability * sample_reliability)",
            "calibrated_signal": "mean(raw_signal) * evidence_factor",
            "calibrated_score": "50 + 50 * calibrated_signal",
            "neutral_score": 50,
            "minimum_independent_races": MIN_INDEPENDENT_RACES,
            "minimum_car_appearances": MIN_APPEARANCES,
            "technical_feature_weight": 0.0,
            "note": "Calibration shrinks weak-evidence sleeper signals toward neutral without using technical coefficients.",
        },
        "sample_benchmark": sample_benchmark,
        "cars": ranking,
        "practical_current_week_ranking": practical_ranking,
    }

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "",
        "STRUCTURAL SLEEPER MODEL V0.2 - EVIDENCE CALIBRATED",
        SUB,
        f"Model key            : {model_key}",
        f"Status               : {payload['status']}",
        f"Independent races    : {len(peers)} / {MIN_INDEPENDENT_RACES} minimum",
        f"Independent weeks    : {', '.join(payload['independent_weeks']) if peers else 'N/A'}",
        f"Sample benchmark     : {sample_benchmark:.1f} accumulated drivers (model median)",
        "Technical weight     : 0.0",
        "Calibration          : weak evidence is shrunk toward SSI 50 (neutral).",
        "",
        "TOP CALIBRATED STRUCTURAL SLEEPER SIGNALS",
        SUB,
    ]

    for i, item in enumerate(ranking[:15], 1):
        lines.append(
            f"{i:>2}. {item['car']} | SSI {item['calibrated_structural_score']:.1f} "
            f"(raw {item['raw_structural_score']:.1f}) | {item['structural_label']} | "
            f"races {item['appearances']}/{len(peers)} | sample {item['total_driver_sample']} | "
            f"evidence {item['evidence_factor']:.3f} | positive {item['positive_signal_rate']:.0%} | "
            f"Conf {item['confidence']} | {item['practical_status']}"
        )

    lines += [
        "",
        "CURRENT-WEEK PRACTICAL PRIORITIES",
        SUB,
    ]

    if practical_ranking:
        for i, item in enumerate(practical_ranking[:10], 1):
            lines.append(
                f"{i:>2}. {item['car']} | SSI {item['calibrated_structural_score']:.1f} | "
                f"Current SCI {item['current_sci']:.1f} | {item['structural_label']} | "
                f"{item['practical_status']}"
            )
    else:
        lines.append("No current-week car met the practical-priority filters.")

    lines += [
        "",
        "INTERPRETATION",
        SUB,
        "Raw SSI still measures performance rank minus adoption rank.",
        "Calibrated SSI discounts signals based on incomplete race coverage and small accumulated samples.",
        "Cars absent from the current leaderboard can remain structural signals but are not current-week recommendations.",
        "With only three independent races, confidence remains deliberately conservative.",
    ]

    old_report = REPORT_FILE.read_text(encoding="utf-8") if REPORT_FILE.exists() else ""
    REPORT_FILE.write_text(old_report.rstrip() + "\n" + "\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
