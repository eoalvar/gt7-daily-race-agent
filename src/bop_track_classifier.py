import json
import re
from pathlib import Path
from datetime import datetime

from bop_database import (
    find_car_records,
    normalize_group,
)

VERSION = "1.0"

LATEST_SNAPSHOT_FILE = Path("data/latest_snapshot.json")
TRACK_MAP_FILE = Path("data/bop_lab/track_bop_classes.json")
REPORT_FILE = Path("reports/bop_track_classifier.txt")
RESULT_FILE = Path("data/bop_lab/current_track_bop.json")

SEP = "=" * 100
SUB = "-" * 100


def now_iso():
    return datetime.now().astimezone().isoformat()


def load_json(path):
    if not path.exists():
        raise RuntimeError(f"Required file not found: {path}")

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        raise RuntimeError(f"Could not parse {path}: {error}") from error


def detect_track(description, track_map):
    if not description:
        return None

    track_names = sorted(
        track_map.keys(),
        key=len,
        reverse=True,
    )

    description_lower = description.lower()

    for track in track_names:
        if track.lower() in description_lower:
            return track

    return None


def detect_group(description):
    if not description:
        return None

    match = re.search(
        r"\bGr\.\s*([1234B])\b",
        description,
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    value = match.group(1).upper()

    if value == "B":
        return "GR.B"

    return normalize_group(f"GR.{value}")


def latest_bop_version(records):
    versions = sorted(
        {
            str(record.get("bop_version") or "").strip()
            for record in records
            if record.get("bop_version")
        }
    )

    if not versions:
        return None

    def key(value):
        try:
            return tuple(int(part) for part in value.split("."))
        except Exception:
            return (0,)

    return sorted(versions, key=key, reverse=True)[0]


def select_record(records, speed_class, bop_version=None):
    candidates = [
        record
        for record in records
        if record.get("speed_class") == speed_class
        and (
            bop_version is None
            or str(record.get("bop_version")) == str(bop_version)
        )
    ]

    if not candidates:
        return None

    return candidates[0]


def compact_bop(record):
    if not record:
        return None

    return {
        "car": record.get("car"),
        "group": record.get("group"),
        "bop_version": record.get("bop_version"),
        "speed_class": record.get("speed_class"),
        "pp": record.get("pp"),
        "power_hp": record.get("power_hp"),
        "torque_nm": record.get("torque_nm"),
        "weight_kg": record.get("weight_kg"),
        "power_weight_hp_t": record.get("power_weight_hp_t"),
        "weight_balance": record.get("weight_balance"),
        "drivetrain": record.get("drivetrain"),
        "aspiration": record.get("aspiration"),
        "acceleration": record.get("acceleration"),
        "rotational_g": record.get("rotational_g"),
        "stability": record.get("stability"),
    }


def signature(record):
    if not record:
        return None

    return (
        record.get("power_hp"),
        record.get("weight_kg"),
        record.get("pp"),
    )


def fingerprint_profile(car, group):
    records = find_car_records(car, group)

    if not records:
        return {
            "car": car,
            "available": False,
            "reason": "No BoP database records for this car/group.",
        }

    version = latest_bop_version(records)

    by_speed = {
        speed: select_record(records, speed, version)
        for speed in ["HIGH", "MID", "LOW"]
    }

    signatures = {
        speed: signature(record)
        for speed, record in by_speed.items()
        if record
    }

    distinct = len(set(signatures.values())) if signatures else 0

    return {
        "car": car,
        "available": len(signatures) == 3,
        "bop_version": version,
        "distinct_signatures": distinct,
        "can_identify_speed_class_from_car": distinct > 1,
        "HIGH": compact_bop(by_speed.get("HIGH")),
        "MID": compact_bop(by_speed.get("MID")),
        "LOW": compact_bop(by_speed.get("LOW")),
    }


def format_bop(record):
    if not record:
        return "N/A"

    power = record.get("power_hp")
    weight = record.get("weight_kg")
    pp = record.get("pp")

    power_text = f"{power:g} HP" if isinstance(power, (int, float)) else "N/A HP"
    weight_text = f"{weight:g} kg" if isinstance(weight, (int, float)) else "N/A kg"
    pp_text = f"PP {pp:g}" if isinstance(pp, (int, float)) else "PP N/A"

    return f"{power_text} / {weight_text} / {pp_text}"


def main():
    snapshot = load_json(LATEST_SNAPSHOT_FILE)
    mapping_payload = load_json(TRACK_MAP_FILE)

    track_map = mapping_payload.get("tracks", {})

    race = snapshot.get("race", {})
    description = race.get("description", "")

    track = detect_track(description, track_map)
    group = detect_group(description)

    if not track:
        raise RuntimeError(
            "Current track was not found in the validated BoP track map. "
            "Add a validated mapping before using this classifier."
        )

    mapping = track_map[track]
    speed_class = str(mapping.get("speed_class") or "").upper()

    if speed_class not in {"HIGH", "MID", "LOW"}:
        raise RuntimeError(f"Invalid speed class for {track}: {speed_class}")

    if not group:
        raise RuntimeError("Could not determine race group from latest snapshot.")

    my_result = snapshot.get("my_result") or {}
    my_car = my_result.get("car")

    my_profile = (
        fingerprint_profile(my_car, group)
        if my_car
        else None
    )

    active_bop = None

    if my_profile and my_profile.get("available"):
        active_bop = my_profile.get(speed_class)

    top5_profiles = []

    for item in snapshot.get("top5_used_cars", [])[:5]:
        car = item.get("car")
        if not car:
            continue

        profile = fingerprint_profile(car, group)
        profile["leaderboard_count"] = item.get("count")
        profile["leaderboard_percentage"] = item.get("percentage")
        profile["active_bop"] = profile.get(speed_class)
        top5_profiles.append(profile)

    result = {
        "generated_at": now_iso(),
        "classifier_version": VERSION,
        "snapshot_timestamp": snapshot.get("timestamp"),
        "race_description": description,
        "track": track,
        "group": group,
        "speed_class": speed_class,
        "classification_confidence": mapping.get("confidence"),
        "classification_validation": mapping.get("validation", []),
        "my_car": my_car,
        "my_car_fingerprint": my_profile,
        "my_car_active_bop": active_bop,
        "top5_used_cars": top5_profiles,
        "production_pipeline_modified": False,
    }

    RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)

    RESULT_FILE.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = []
    lines.append("GT7 BOP TRACK CLASSIFIER V1.0")
    lines.append(SEP)
    lines.append(f"Snapshot            : {snapshot.get('timestamp')}")
    lines.append(f"Track               : {track}")
    lines.append(f"Group               : {group}")
    lines.append(f"BoP speed class     : {speed_class}")
    lines.append(f"Confidence          : {mapping.get('confidence')}")
    lines.append("Production modified : NO")

    lines.append("")
    lines.append("CLASSIFICATION EVIDENCE")
    lines.append(SUB)

    for evidence in mapping.get("validation", []):
        lines.append(
            f"- {evidence.get('source')} | {evidence.get('evidence')}"
        )

    lines.append("")
    lines.append("YOUR CURRENT CAR")
    lines.append(SUB)

    if not my_car:
        lines.append("No current personal car in latest snapshot.")
    elif not my_profile or not my_profile.get("available"):
        lines.append(f"Car                 : {my_car}")
        lines.append("BoP records         : unavailable")
    else:
        lines.append(f"Car                 : {my_car}")
        lines.append(f"BoP version         : {my_profile.get('bop_version')}")
        lines.append(f"HIGH                : {format_bop(my_profile.get('HIGH'))}")
        lines.append(f"MID                 : {format_bop(my_profile.get('MID'))}")
        lines.append(f"LOW                 : {format_bop(my_profile.get('LOW'))}")
        lines.append(f"Active ({speed_class})        : {format_bop(active_bop)}")
        lines.append(
            "Fingerprint useful  : "
            + (
                "YES"
                if my_profile.get("can_identify_speed_class_from_car")
                else "NO - this car has identical/insufficient BoP signatures"
            )
        )

    lines.append("")
    lines.append("TOP 5 USED CARS - ACTIVE BOP")
    lines.append(SUB)

    for index, profile in enumerate(top5_profiles, start=1):
        lines.append(
            f"{index}. {profile.get('car')} | "
            f"usage {profile.get('leaderboard_percentage')}% | "
            f"{speed_class}: {format_bop(profile.get('active_bop'))} | "
            f"fingerprint {'YES' if profile.get('can_identify_speed_class_from_car') else 'NO'}"
        )

    lines.append("")
    lines.append("RESULT")
    lines.append(SUB)
    lines.append(
        f"Current Daily Race C uses {speed_class}-speed BoP for {track}."
    )
    lines.append(
        "The active technical comparison for sleeper analysis should therefore use "
        f"the {speed_class} records from bop_database.json."
    )
    lines.append(SEP)

    report = "\n".join(lines)

    REPORT_FILE.write_text(report, encoding="utf-8")

    print(report)
    print()
    print(f"Saved report        : {REPORT_FILE}")
    print(f"Saved result        : {RESULT_FILE}")


if __name__ == "__main__":
    main()
