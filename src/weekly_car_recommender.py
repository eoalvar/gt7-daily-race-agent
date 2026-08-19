import json
import math
from pathlib import Path
from datetime import datetime

CURRENT_FILE = Path("data/bop_lab/sleeper_car_index.json")
STRUCTURAL_FILE = Path("data/bop_lab/structural_sleeper_index.json")
OUT_FILE = Path("data/bop_lab/weekly_car_recommendations.json")
REPORT_FILE = Path("reports/weekly_car_recommendations.txt")

VERSION = "0.1"
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


def std(values):
    vals = [float(v) for v in values if v is not None]
    if len(vals) < 2:
        return None
    m = sum(vals) / len(vals)
    s = math.sqrt(sum((x - m) ** 2 for x in vals) / len(vals))
    return s if s > 0 else None


def front_pct(balance):
    try:
        return float(str(balance).split(":", 1)[0])
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
    consensus = item["consensus_percentile"]
    sci_pct = item["sci_percentile"]
    ssi_pct = item["ssi_percentile"]
    tech_pct = item["technical_percentile_adjusted"]
    structural_present = item["structural_history_available"]

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


def main():
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
        if item.get("car_code") is not None
    ]
    if not current_cars:
        raise RuntimeError("Current Sleeper Car Index has no eligible cars.")

    structural_by_code = {
        item.get("car_code"): item
        for item in structural.get("cars") or []
        if item.get("car_code") is not None
    }

    sci_values = [f(item.get("sleeper_score")) for item in current_cars]
    ssi_values = [
        f(item.get("calibrated_structural_score") or item.get("structural_sleeper_score"))
        for item in structural.get("cars") or []
        if item.get("current_week_present")
    ]

    technical = current.get("technical_learning") or {}
    correlations = technical.get("observed_feature_correlations") or {}
    tech_races = int(technical.get("races_available_same_group_speed_class") or 0)

    # Technical evidence is deliberately damped at low race counts.
    # 3 races = 50% of the deviation from neutral; 6+ = full technical percentile.
    tech_reliability = max(0.0, min(1.0, tech_races / 6.0))

    feature_stats = {}
    for feature, corr in correlations.items():
        corr = f(corr)
        if corr is None or abs(corr) < 1e-12 or feature not in FEATURE_PATHS:
            continue
        values = [technical_value(item.get("active_bop") or {}, feature) for item in current_cars]
        m = mean(values)
        s = std(values)
        if m is not None and s is not None:
            feature_stats[feature] = {
                "correlation": corr,
                "mean": m,
                "std": s,
            }

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
        technical_raw[item["car_code"]] = numerator / denominator if denominator else None

    tech_values = list(technical_raw.values())

    rows = []
    for item in current_cars:
        code = item["car_code"]
        structural_item = structural_by_code.get(code) or {}
        sci = f(item.get("sleeper_score"))
        ssi = f(
            structural_item.get("calibrated_structural_score")
            or structural_item.get("structural_sleeper_score")
        )

        sci_pct = percentile_rank(sci, sci_values)
        ssi_pct = percentile_rank(ssi, ssi_values) if ssi is not None else 0.5
        tech_raw = technical_raw.get(code)
        tech_pct_raw = percentile_rank(tech_raw, tech_values) if tech_raw is not None else 0.5
        tech_pct_adj = 0.5 + (tech_pct_raw - 0.5) * tech_reliability

        # Consensus uses rank percentiles rather than mixing SCI/SSI raw scales.
        # Missing structural history is neutral (0.5), not zero.
        consensus = mean([sci_pct, ssi_pct, tech_pct_adj])

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
            x["consensus_percentile"],
            x["sci_percentile"],
            x["ssi_percentile"],
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
            "note": "Raw SCI, SSI and technical fit remain separately visible; consensus is for ordering, not a replacement for the three pillars.",
        },
        "technical_feature_correlations": correlations,
        "cars": rows,
    }

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"GT7 WEEKLY CAR RECOMMENDATIONS V{VERSION}",
        SEP,
        f"Track                : {payload['track']}",
        f"Model                : {model_key}",
        f"Total drivers        : {payload['total_drivers']:,}" if payload.get("total_drivers") else "Total drivers        : N/A",
        f"WR                   : {payload.get('world_record_laptime')}",
        f"Technical races      : {tech_races}",
        f"Technical reliability: {tech_reliability:.0%}",
        "",
        "FINAL WEEKLY RECOMMENDATION",
        SUB,
    ]

    for row in rows[:15]:
        lines.append(
            f"{row['recommendation_rank']:>2}. {row['car']} | {row['recommendation']} | "
            f"Consensus {row['consensus_percentile']:.3f} | "
            f"SCI {row['current_sci']:.1f} (pct {row['sci_percentile']:.3f}) | "
            f"SSI {row['calibrated_ssi']:.1f} (pct {row['ssi_percentile']:.3f}) "
            if row['calibrated_ssi'] is not None else
            f"{row['recommendation_rank']:>2}. {row['car']} | {row['recommendation']} | "
            f"Consensus {row['consensus_percentile']:.3f} | "
            f"SCI {row['current_sci']:.1f} (pct {row['sci_percentile']:.3f}) | SSI N/A (neutral 0.500) "
        )
        lines[-1] += (
            f"| Tech pct {row['technical_percentile_adjusted']:.3f} "
            f"| share {row['current_share_percent']:.2f}% | best #{row['best_rank']}"
        )

    lines += [
        "",
        "METHOD",
        SUB,
        "SCI = what is working in the current Daily Race.",
        "SSI = what has repeatedly outperformed adoption across independent comparable races.",
        "Technical fit = BoP characteristics favored by empirically observed correlations for this group/speed class.",
        "The final ordering averages percentile ranks of the three pillars; it never hides the underlying values.",
        "Technical evidence is shrunk toward neutral until six independent races are available.",
        SEP,
    ]

    report = "\n".join(lines)
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
