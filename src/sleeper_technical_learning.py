import json
import math
from pathlib import Path
from datetime import datetime

RESULT_FILE = Path("data/bop_lab/sleeper_car_index.json")
TRAINING_FILE = Path("data/bop_lab/sleeper_training_history.json")
REPORT_FILE = Path("reports/sleeper_car_lab.txt")
VERSION = "0.3"
MIN_RACES = 3
FEATURES = [
    "power_weight_hp_t",
    "weight_kg",
    "front_weight_pct",
    "acceleration_0_400",
    "acceleration_100_150",
    "rotational_g_60",
    "rotational_g_120",
    "rotational_g_240",
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


def week_key(value):
    text = str(value or "")[:10]
    try:
        d = datetime.fromisoformat(text)
        monday_ordinal = d.date().toordinal() - d.weekday()
        return datetime.fromordinal(monday_ordinal).date().isoformat()
    except Exception:
        return text or None


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
    pairs = [
        (float(x), float(y))
        for x, y in zip(xs, ys)
        if x is not None and y is not None
    ]

    if len(pairs) < 5:
        return None

    mx = sum(x for x, _ in pairs) / len(pairs)
    my = sum(y for _, y in pairs) / len(pairs)
    dx = [x - mx for x, _ in pairs]
    dy = [y - my for _, y in pairs]
    den = math.sqrt(sum(x * x for x in dx) * sum(y * y for y in dy))

    return None if den == 0 else sum(x * y for x, y in zip(dx, dy)) / den


def load_history():
    if TRAINING_FILE.exists():
        try:
            data = json.loads(TRAINING_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("races"), list):
                return data
        except Exception:
            pass

    return {
        "schema_version": VERSION,
        "races": [],
    }


def model_key(group, speed_class):
    return f"{group}|{speed_class}"


def normalize_history(history):
    """
    Keep at most one observation per group + speed class + week.

    A current LIVE_SNAPSHOT replaces another observation from the same week,
    because multiple snapshots from one Daily Race are not independent races.
    Different groups and speed classes remain separate models.
    """
    selected = {}

    for race in history.get("races") or []:
        group = race.get("group")
        speed = str(race.get("speed_class") or "").upper()
        wk = race.get("week_start") or week_key(
            race.get("race_key") or race.get("captured_at")
        )

        if not group or speed not in {"HIGH", "MID", "LOW"} or not wk:
            continue

        race["week_start"] = wk
        key = (group, speed, wk)
        old = selected.get(key)

        if old is None:
            selected[key] = race
            continue

        old_status = old.get("status")
        new_status = race.get("status")

        # Prefer LIVE for the active week, otherwise keep the most recently captured record.
        if new_status == "LIVE_SNAPSHOT" and old_status != "LIVE_SNAPSHOT":
            selected[key] = race
            continue

        if str(race.get("captured_at") or "") >= str(old.get("captured_at") or ""):
            selected[key] = race

    history["races"] = sorted(
        selected.values(),
        key=lambda r: (
            str(r.get("week_start") or ""),
            str(r.get("group") or ""),
            str(r.get("speed_class") or ""),
        ),
    )

    return history


def main():
    payload = json.loads(RESULT_FILE.read_text(encoding="utf-8"))
    ranking = payload.get("ranking") or []

    group = payload.get("group")
    speed_class = str(payload.get("speed_class") or "").upper()

    if not group:
        raise RuntimeError("Sleeper result has no group.")

    if speed_class not in {"HIGH", "MID", "LOW"}:
        raise RuntimeError(f"Invalid sleeper speed class: {speed_class}")

    current_week = week_key(
        payload.get("snapshot_timestamp") or payload.get("generated_at")
    )

    if not current_week:
        raise RuntimeError("Could not determine current race week.")

    cars = []

    for car in ranking:
        bop = car.get("active_bop") or {}
        tech = technical(bop)

        if not tech:
            continue

        quality = f(car.get("quality_component")) or 0.0
        elite = f(car.get("elite_proximity")) or 0.0

        cars.append(
            {
                "car_code": car.get("car_code"),
                "car": car.get("car"),
                "sample": car.get("all_count"),
                "performance_target": 0.65 * quality + 0.35 * elite,
                "technical": tech,
            }
        )

    history = normalize_history(load_history())

    record = {
        "race_key": f"live:{group}:{speed_class}:{current_week}",
        "week_start": current_week,
        "captured_at": now_iso(),
        "track": payload.get("track"),
        "group": group,
        "speed_class": speed_class,
        "model_key": model_key(group, speed_class),
        "status": "LIVE_SNAPSHOT",
        "total_drivers": payload.get("total_drivers"),
        "cars": cars,
    }

    races = history.setdefault("races", [])

    # Replace the same group/speed/week observation rather than adding another snapshot.
    replaced = False
    for index, old in enumerate(races):
        if (
            old.get("group") == group
            and str(old.get("speed_class") or "").upper() == speed_class
            and (old.get("week_start") or week_key(old.get("race_key") or old.get("captured_at"))) == current_week
        ):
            races[index] = record
            replaced = True
            break

    if not replaced:
        races.append(record)

    history = normalize_history(history)
    history["schema_version"] = VERSION
    history["updated_at"] = now_iso()

    TRAINING_FILE.parent.mkdir(parents=True, exist_ok=True)
    TRAINING_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    peers = [
        race
        for race in history.get("races") or []
        if race.get("group") == group
        and str(race.get("speed_class") or "").upper() == speed_class
    ]

    independent_weeks = sorted(
        {
            race.get("week_start")
            for race in peers
            if race.get("week_start")
        }
    )

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

        correlations[feature] = (
            sum(values) / len(values)
            if values
            else None
        )

    independent_count = len(independent_weeks)
    ready = independent_count >= MIN_RACES

    # Overview across every model currently represented in history.
    coverage = {}
    for race in history.get("races") or []:
        g = race.get("group")
        s = str(race.get("speed_class") or "").upper()
        wk = race.get("week_start")
        if not g or s not in {"HIGH", "MID", "LOW"} or not wk:
            continue
        coverage.setdefault(model_key(g, s), set()).add(wk)

    coverage = {
        key: {
            "independent_races": len(weeks),
            "status": "ACTIVE" if len(weeks) >= MIN_RACES else "BOOTSTRAP",
        }
        for key, weeks in sorted(coverage.items())
    }

    payload["version"] = VERSION
    payload["technical_learning"] = {
        "model_key": model_key(group, speed_class),
        "status": "ACTIVE" if ready else "BOOTSTRAP",
        "minimum_independent_races": MIN_RACES,
        "races_available_same_group_speed_class": independent_count,
        "independent_weeks": independent_weeks,
        "features": FEATURES,
        "observed_feature_correlations": correlations,
        "technical_weight_in_sleeper_score": 0.0,
        "multi_group_model_coverage": coverage,
        "policy": (
            "Each group + speed class is learned independently. "
            "Multiple snapshots from the same race week count once. "
            "No technical coefficient changes SCI until enough independent weeks exist; "
            "no hand-picked technical weights."
        ),
    }

    RESULT_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    old_report = (
        REPORT_FILE.read_text(encoding="utf-8")
        if REPORT_FILE.exists()
        else ""
    )

    if old_report.startswith("GT7 SLEEPER CAR LAB V0.1"):
        old_report = old_report.replace(
            "GT7 SLEEPER CAR LAB V0.1",
            "GT7 SLEEPER CAR LAB V0.3",
            1,
        )
    elif old_report.startswith("GT7 SLEEPER CAR LAB V0.2"):
        old_report = old_report.replace(
            "GT7 SLEEPER CAR LAB V0.2",
            "GT7 SLEEPER CAR LAB V0.3",
            1,
        )

    block = [
        "",
        "V0.3 MULTI-GROUP TECHNICAL LEARNING",
        "-" * 100,
        f"Model key            : {model_key(group, speed_class)}",
        f"Model status         : {'ACTIVE' if ready else 'BOOTSTRAP'}",
        f"Independent races    : {independent_count} / {MIN_RACES} minimum",
        f"Independent weeks    : {', '.join(independent_weeks) if independent_weeks else 'N/A'}",
        "Technical SCI weight : 0.0",
        "Policy               : group + speed-class models are completely separate.",
        "",
        "Observed correlations (diagnostic only):",
    ]

    for feature in FEATURES:
        value = correlations.get(feature)
        block.append(
            f"  {feature:<24} {value:+.3f}"
            if isinstance(value, (int, float))
            else f"  {feature:<24} N/A"
        )

    block += [
        "",
        "MODEL COVERAGE",
    ]

    for key, item in coverage.items():
        block.append(
            f"  {key:<14} {item['independent_races']} independent race(s) | {item['status']}"
        )

    block += [
        "",
        "Repeated snapshots from one Daily Race week never increase the independent-race count.",
        "A future GR.4/MID race, for example, trains GR.4|MID only and cannot alter GR.3|MID.",
    ]

    REPORT_FILE.write_text(
        old_report.rstrip() + "\n" + "\n".join(block) + "\n",
        encoding="utf-8",
    )

    print("\n".join(block))


if __name__ == "__main__":
    main()
