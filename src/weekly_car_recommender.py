import json
import math
import traceback
from pathlib import Path
from datetime import datetime

CURRENT_FILE = Path("data/bop_lab/sleeper_car_index.json")
STRUCTURAL_FILE = Path("data/bop_lab/structural_sleeper_index.json")
OUT_FILE = Path("data/bop_lab/weekly_car_recommendations.json")
REPORT_FILE = Path("reports/weekly_car_recommendations.txt")
ERROR_FILE = Path("data/bop_lab/weekly_car_recommender_error.txt")

VERSION = "0.2"
SEP = "=" * 100
SUB = "-" * 100

FEATURE_PATHS = {
    "power_weight_hp_t": ("power_weight_hp_t",),
    "weight_kg": ("weight_kg",),
    "front_weight_pct": ("weight_balance",),
    "acceleration_0_400": ("acceleration", "0_400m"),
    "acceleration_100_150": ("acceleration", "100_150_kmh"),
    "rotational_g_60": ("rotational_g", "60_kmh"),
    "rotational_g_120": ("rotational_g", "120_kmh"),
    "rotational_g_240": ("rotational_g", "240_kmh"),
}


def now_iso():
    return datetime.now().astimezone().isoformat()


def f(value):
    try:
        value = float(value)
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    except Exception:
        return None


def percentile_rank(value, values):
    value = f(value)
    clean = [f(v) for v in values]
    clean = sorted(v for v in clean if v is not None)
    if value is None or not clean:
        return None
    below = sum(1 for x in clean if x < value)
    equal = sum(1 for x in clean if x == value)
    return (below + 0.5 * equal) / len(clean)


def mean(values):
    vals = [f(v) for v in values]
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def std(values):
    vals = [f(v) for v in values]
    vals = [v for v in vals if v is not None]
    if len(vals) < 2:
        return None
    m = sum(vals) / len(vals)
    s = math.sqrt(sum((x - m) ** 2 for x in vals) / len(vals))
    return s if s > 1e-12 else None


def front_pct(balance):
    try:
        return f(str(balance).split(":", 1)[0])
    except Exception:
        return None


def nested_get(obj, path):
    value = obj
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def technical_value(bop, feature):
    path = FEATURE_PATHS.get(feature)
    if not path:
        return None
    raw = nested_get(bop or {}, path)
    if feature == "front_weight_pct":
        return front_pct(raw)
    return f(raw)


def recommendation_label(item):
    consensus = f(item.get("consensus_percentile")) or 0.0
    sci_pct = f(item.get("sci_percentile")) or 0.0
    ssi_pct = f(item.get("ssi_percentile"))
    tech_pct = f(item.get("technical_percentile_adjusted")) or 0.5
    structural_present = bool(item.get("structural_history_available"))
    ssi_pct = 0.5 if ssi_pct is None else ssi_pct

    if consensus >= 0.80 and sci_pct >= 0.65 and (not structural_present or ssi_pct >= 0.55):
        return "PRIORITY TEST"
    if consensus >= 0.68 and sci_pct >= 0.55:
        return "STRONG ALTERNATIVE"
    if consensus >= 0.58:
        return "WATCH / TEST"
    if sci_pct >= 0.80 and structural_present and ssi_pct < 0.35:
        return "CURRENT-WEEK SPECIALIST"
    if structural_present and ssi_pct >= 0.80 and sci_pct < 0.40:
        return "STRUCTURAL BUT NOT CURRENT"
    if tech_pct >= 0.80 and sci_pct < 0.45:
        return "TECHNICALLY INTERESTING"
    return "LOW PRIORITY"


def fmt_num(value, decimals=1, fallback="N/A"):
    value = f(value)
    return f"{value:.{decimals}f}" if value is not None else fallback


def build():
    current = json.loads(CURRENT_FILE.read_text(encoding="utf-8"))
    structural = json.loads(STRUCTURAL_FILE.read_text(encoding="utf-8"))

    group = current.get("group")
    speed = str(current.get("speed_class") or "").upper()
    model_key = f"{group}|{speed}"

    if structural.get("model_key") != model_key:
        raise RuntimeError(
            f"Structural model mismatch: current={model_key}, structural={structural.get('model_key')}"
        )

    current_cars = [
        item for item in current.get("ranking") or []
        if item.get("car_code") is not None and f(item.get("sleeper_score")) is not None
    ]
    if not current_cars:
        raise RuntimeError("Current Sleeper Car Index has no eligible cars.")

    structural_by_code = {
        item.get("car_code"): item
        for item in structural.get("cars") or []
        if item.get("car_code") is not None
    }

    sci_values = [f(item.get("sleeper_score")) for item in current_cars]
    ssi_values = []
    for item in structural.get("cars") or []:
        if not item.get("current_week_present"):
            continue
        score = f(item.get("calibrated_structural_score"))
        if score is None:
            score = f(item.get("structural_sleeper_score"))
        if score is not None:
            ssi_values.append(score)

    technical = current.get("technical_learning") or {}
    correlations = technical.get("observed_feature_correlations") or {}
    tech_races = int(f(technical.get("races_available_same_group_speed_class")) or 0)
    tech_reliability = max(0.0, min(1.0, tech_races / 6.0))

    feature_stats = {}
    for feature, raw_corr in correlations.items():
        corr = f(raw_corr)
        if corr is None or abs(corr) < 1e-12 or feature not in FEATURE_PATHS:
            continue
        values = [technical_value(item.get("active_bop") or {}, feature) for item in current_cars]
        m = mean(values)
        s = std(values)
        if m is not None and s is not None:
            feature_stats[feature] = {"correlation": corr, "mean": m, "std": s}

    technical_raw = {}
    for item in current_cars:
        numerator = 0.0
        denominator = 0.0
        bop = item.get("active_bop") or {}
        for feature, stats in feature_stats.items():
            value = technical_value(bop, feature)
            if value is None:
                continue
            z = (value - stats["mean"]) / stats["std"]
            corr = stats["correlation"]
            numerator += z * corr
            denominator += abs(corr)
        technical_raw[item["car_code"]] = numerator / denominator if denominator > 0 else None

    tech_values = [v for v in technical_raw.values() if f(v) is not None]

    rows = []
    for item in current_cars:
        code = item["car_code"]
        structural_item = structural_by_code.get(code) or {}
        sci = f(item.get("sleeper_score"))

        ssi = f(structural_item.get("calibrated_structural_score"))
        if ssi is None:
            ssi = f(structural_item.get("structural_sleeper_score"))

        sci_pct = percentile_rank(sci, sci_values)
        if sci_pct is None:
            sci_pct = 0.5

        ssi_pct = percentile_rank(ssi, ssi_values) if ssi is not None and ssi_values else 0.5
        if ssi_pct is None:
            ssi_pct = 0.5

        tech_raw = f(technical_raw.get(code))
        tech_pct_raw = percentile_rank(tech_raw, tech_values) if tech_raw is not None and tech_values else 0.5
        if tech_pct_raw is None:
            tech_pct_raw = 0.5
        tech_pct_adj = 0.5 + (tech_pct_raw - 0.5) * tech_reliability

        consensus = mean([sci_pct, ssi_pct, tech_pct_adj])
        if consensus is None:
            consensus = 0.5

        row = {
            "car_code": code,
            "car": item.get("car"),
            "current_sci": sci,
            "current_sci_label": item.get("sleeper_label"),
            "current_share_percent": f(item.get("share_percent")),
            "best_rank": item.get("best_rank"),
            "sci_percentile": sci_pct,
            "calibrated_ssi": ssi,
            "structural_label": structural_item.get("structural_label"),
            "structural_history_available": bool(structural_item),
            "structural_appearances": structural_item.get("appearances"),
            "ssi_percentile": ssi_pct,
            "technical_raw_fit": tech_raw,
            "technical_percentile_raw": tech_pct_raw,
            "technical_reliability": tech_reliability,
            "technical_percentile_adjusted": tech_pct_adj,
            "consensus_percentile": consensus,
            "active_bop": item.get("active_bop"),
        }
        row["recommendation"] = recommendation_label(row)
        rows.append(row)

    rows.sort(
        key=lambda x: (
            f(x.get("consensus_percentile")) or 0.0,
            f(x.get("sci_percentile")) or 0.0,
            f(x.get("ssi_percentile")) or 0.0,
        ),
        reverse=True,
    )

    for i, row in enumerate(rows, 1):
        row["recommendation_rank"] = i

    payload = {
        "generated_at": now_iso(),
        "version": VERSION,
        "track": current.get("track"),
        "group": group,
        "speed_class": speed,
        "model_key": model_key,
        "total_drivers": current.get("total_drivers"),
        "world_record_laptime": current.get("world_record_laptime"),
        "technical_model_races": tech_races,
        "technical_reliability": tech_reliability,
        "method": {
            "name": "transparent three-pillar rank consensus",
            "pillars": [
                "current SCI percentile",
                "calibrated structural SSI percentile",
                "learned technical-fit percentile",
            ],
            "consensus": "arithmetic mean of the three percentile ranks",
            "missing_structural_history": "neutral percentile 0.5",
            "technical_fit": "within-current-field standardized BoP features weighted only by empirically observed feature correlations",
            "technical_reliability": "technical percentile deviation from neutral is multiplied by min(1, independent technical races / 6)",
            "technical_hand_picked_feature_weights": False,
        },
        "technical_feature_correlations": correlations,
        "cars": rows,
    }

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    total = current.get("total_drivers")
    total_text = f"{int(total):,}" if f(total) is not None else "N/A"

    lines = [
        f"GT7 WEEKLY CAR RECOMMENDATIONS V{VERSION}",
        SEP,
        f"Track                : {payload.get('track')}",
        f"Model                : {model_key}",
        f"Total drivers        : {total_text}",
        f"WR                   : {payload.get('world_record_laptime') or 'N/A'}",
        f"Technical races      : {tech_races}",
        f"Technical reliability: {tech_reliability:.0%}",
        "",
        "FINAL WEEKLY RECOMMENDATION",
        SUB,
    ]

    for row in rows[:15]:
        ssi_text = fmt_num(row.get("calibrated_ssi"), 1)
        share_text = fmt_num(row.get("current_share_percent"), 2)
        best_rank = row.get("best_rank")
        best_rank_text = str(best_rank) if best_rank is not None else "N/A"
        lines.append(
            f"{row['recommendation_rank']:>2}. {row.get('car') or 'Unknown'} | {row['recommendation']} | "
            f"Consensus {fmt_num(row.get('consensus_percentile'), 3)} | "
            f"SCI {fmt_num(row.get('current_sci'), 1)} (pct {fmt_num(row.get('sci_percentile'), 3)}) | "
            f"SSI {ssi_text} (pct {fmt_num(row.get('ssi_percentile'), 3)}) | "
            f"Tech pct {fmt_num(row.get('technical_percentile_adjusted'), 3)} | "
            f"share {share_text}% | best #{best_rank_text}"
        )

    lines += [
        "",
        "METHOD",
        SUB,
        "SCI = what is working in the current Daily Race.",
        "SSI = what has repeatedly outperformed adoption across independent comparable races.",
        "Technical fit = BoP characteristics favored by empirically observed correlations for this group/speed class.",
        "The final ordering averages percentile ranks of the three pillars.",
        "Technical evidence is shrunk toward neutral until six independent races are available.",
        SEP,
    ]

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")
    return "\n".join(lines)


def main():
    ERROR_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        report = build()
        if ERROR_FILE.exists():
            ERROR_FILE.unlink()
        print(report)
    except Exception:
        error = traceback.format_exc()
        ERROR_FILE.write_text(error, encoding="utf-8")
        print(error)
        raise


if __name__ == "__main__":
    main()
