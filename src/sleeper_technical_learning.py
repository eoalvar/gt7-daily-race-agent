import json
import math
from pathlib import Path
from datetime import datetime

RESULT_FILE = Path("data/bop_lab/sleeper_car_index.json")
TRAINING_FILE = Path("data/bop_lab/sleeper_training_history.json")
REPORT_FILE = Path("reports/sleeper_car_lab.txt")
VERSION = "0.2"
MIN_RACES = 3
FEATURES = [
    "power_weight_hp_t", "weight_kg", "front_weight_pct",
    "acceleration_0_400", "acceleration_100_150",
    "rotational_g_60", "rotational_g_120", "rotational_g_240",
]


def now_iso():
    return datetime.now().astimezone().isoformat()


def f(value):
    try:
        return float(value)
    except Exception:
        return None


def front_pct(balance):
    try:
        return float(str(balance).split(":", 1)[0])
    except Exception:
        return None


def technical(bop):
    if not bop:
        return None
    acc = bop.get("acceleration") or {}
    rot = bop.get("rotational_g") or {}
    return {
        "power_weight_hp_t": f(bop.get("power_weight_hp_t")),
        "weight_kg": f(bop.get("weight_kg")),
        "front_weight_pct": front_pct(bop.get("weight_balance")),
        "acceleration_0_400": f(acc.get("0_400m")),
        "acceleration_100_150": f(acc.get("100_150_kmh")),
        "rotational_g_60": f(rot.get("60_kmh")),
        "rotational_g_120": f(rot.get("120_kmh")),
        "rotational_g_240": f(rot.get("240_kmh")),
    }


def pearson(xs, ys):
    pairs = [(float(x), float(y)) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 5:
        return None
    mx = sum(x for x, _ in pairs) / len(pairs)
    my = sum(y for _, y in pairs) / len(pairs)
    dx = [x - mx for x, _ in pairs]
    dy = [y - my for _, y in pairs]
    den = math.sqrt(sum(x*x for x in dx) * sum(y*y for y in dy))
    return None if den == 0 else sum(x*y for x, y in zip(dx, dy)) / den


def load_history():
    if TRAINING_FILE.exists():
        try:
            data = json.loads(TRAINING_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("races"), list):
                return data
        except Exception:
            pass
    return {"schema_version": VERSION, "races": []}


def main():
    payload = json.loads(RESULT_FILE.read_text(encoding="utf-8"))
    ranking = payload.get("ranking") or []
    cars = []
    for car in ranking:
        bop = car.get("active_bop") or {}
        tech = technical(bop)
        if not tech:
            continue
        quality = f(car.get("quality_component")) or 0.0
        elite = f(car.get("elite_proximity")) or 0.0
        cars.append({
            "car_code": car.get("car_code"),
            "car": car.get("car"),
            "sample": car.get("all_count"),
            "performance_target": 0.65 * quality + 0.35 * elite,
            "technical": tech,
        })

    history = load_history()
    event_key = payload.get("snapshot_timestamp") or f"{payload.get('track')}|{payload.get('generated_at')}"
    record = {
        "race_key": event_key,
        "captured_at": now_iso(),
        "track": payload.get("track"),
        "group": payload.get("group"),
        "speed_class": payload.get("speed_class"),
        "status": "LIVE_SNAPSHOT",
        "total_drivers": payload.get("total_drivers"),
        "cars": cars,
    }
    races = history.setdefault("races", [])
    for i, old in enumerate(races):
        if old.get("race_key") == event_key:
            races[i] = record
            break
    else:
        races.append(record)
    history["updated_at"] = now_iso()
    TRAINING_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

    peers = [r for r in races if r.get("group") == payload.get("group") and r.get("speed_class") == payload.get("speed_class")]
    correlations = {}
    for feature in FEATURES:
        values = []
        for race in peers:
            rcars = race.get("cars") or []
            corr = pearson(
                [c.get("technical", {}).get(feature) for c in rcars],
                [c.get("performance_target") for c in rcars],
            )
            if corr is not None:
                values.append(corr)
        correlations[feature] = sum(values) / len(values) if values else None

    ready = len(peers) >= MIN_RACES
    payload["version"] = VERSION
    payload["technical_learning"] = {
        "status": "ACTIVE" if ready else "BOOTSTRAP",
        "minimum_independent_races": MIN_RACES,
        "races_available_same_group_speed_class": len(peers),
        "features": FEATURES,
        "observed_feature_correlations": correlations,
        "technical_weight_in_sleeper_score": 0.0,
        "policy": "No technical coefficient changes SCI until enough independent race observations exist; no hand-picked technical weights.",
    }
    RESULT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    old_report = REPORT_FILE.read_text(encoding="utf-8") if REPORT_FILE.exists() else ""
    if old_report.startswith("GT7 SLEEPER CAR LAB V0.1"):
        old_report = old_report.replace("GT7 SLEEPER CAR LAB V0.1", "GT7 SLEEPER CAR LAB V0.2", 1)
    block = [
        "", "V0.2 TECHNICAL LEARNING", "-" * 100,
        f"Model status         : {'ACTIVE' if ready else 'BOOTSTRAP'}",
        f"Independent races    : {len(peers)} / {MIN_RACES} minimum",
        "Technical SCI weight : 0.0",
        "Policy               : empirical learning only; no arbitrary technical weights.",
        "", "Observed correlations (diagnostic only):",
    ]
    for feature in FEATURES:
        value = correlations.get(feature)
        block.append(f"  {feature:<24} {value:+.3f}" if isinstance(value, (int, float)) else f"  {feature:<24} N/A")
    block += [
        "", "The history file is persistent. Repeated observations accumulate evidence for future",
        "circuit/speed-class technical modelling without changing the production Daily Race C agent.",
    ]
    REPORT_FILE.write_text(old_report.rstrip() + "\n" + "\n".join(block) + "\n", encoding="utf-8")
    print("\n".join(block))


if __name__ == "__main__":
    main()
