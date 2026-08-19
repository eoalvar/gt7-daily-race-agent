import json
import re
import traceback
from pathlib import Path
from datetime import datetime

VERSION = "2.0"

LATEST_SNAPSHOT_FILE = Path("data/latest_snapshot.json")
TRACK_MAP_FILE = Path("data/bop_lab/track_bop_classes.json")
BOP_DATABASE_FILE = Path("data/bop_lab/bop_database.json")
REPORT_FILE = Path("reports/bop_track_classifier.txt")
RESULT_FILE = Path("data/bop_lab/current_track_bop.json")
ERROR_FILE = Path("data/bop_lab/current_track_bop_error.txt")

SEP = "=" * 100
SUB = "-" * 100
VALID_SPEEDS = {"HIGH", "MID", "LOW"}
VALID_GROUPS = {"GR.1", "GR.2", "GR.3", "GR.4", "GR.B"}


def now_iso():
    return datetime.now().astimezone().isoformat()


def load_json(path):
    if not path.exists():
        raise RuntimeError(f"Required file not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        raise RuntimeError(f"Could not parse {path}: {error}") from error


def normalize_group(value):
    if value is None:
        return None
    text = str(value).strip().upper().replace(" ", "")
    aliases = {
        "GR1": "GR.1", "GR.1": "GR.1",
        "GR2": "GR.2", "GR.2": "GR.2",
        "GR3": "GR.3", "GR.3": "GR.3",
        "GR4": "GR.4", "GR.4": "GR.4",
        "GRB": "GR.B", "GR.B": "GR.B",
    }
    return aliases.get(text)


def detect_track(description, track_map):
    if not description:
        return None
    lowered = description.casefold()
    aliases = []
    for track, item in track_map.items():
        aliases.append((track, track))
        for alias in item.get("aliases") or []:
            aliases.append((alias, track))
    for alias, canonical in sorted(aliases, key=lambda x: len(x[0]), reverse=True):
        if alias.casefold() in lowered:
            return canonical
    return None


def detect_group(description):
    if not description:
        return None
    match = re.search(r"\bGr\.\s*([1234B])\b", description, flags=re.IGNORECASE)
    if not match:
        return None
    token = match.group(1).upper()
    return "GR.B" if token == "B" else normalize_group(f"GR.{token}")


def detect_explicit_speed(description):
    """Prefer an explicit event BoP class whenever a source exposes it."""
    if not description:
        return None
    patterns = [
        r"\bBOP\s*\(\s*([HML])\s*\)",
        r"\bBOP\s*(?:=|:)\s*([HML])\b",
        r"\b(?:HIGH|MID|MEDIUM|LOW)[ -]?SPEED\s+BOP\b",
    ]
    upper = description.upper()
    match = re.search(patterns[0], upper) or re.search(patterns[1], upper)
    if match:
        return {"H": "HIGH", "M": "MID", "L": "LOW"}.get(match.group(1))
    if re.search(patterns[2], upper):
        if "HIGH" in upper:
            return "HIGH"
        if "LOW" in upper:
            return "LOW"
        return "MID"
    return None


def version_key(value):
    try:
        return tuple(int(part) for part in str(value).split("."))
    except Exception:
        return (0,)


def normalize_car_name(value):
    if not value:
        return ""
    text = str(value).casefold()
    text = text.replace("･", " ").replace("・", " ")
    # VGT and Vision Gran Turismo are semantic equivalents.
    text = re.sub(r"\bvision\s+gran\s+turismo\b", " vgt ", text)
    # Group suffixes are metadata rather than model identity.
    text = re.sub(r"\(\s*gr\.?\s*[1234b]\s*\)", " ", text)
    text = re.sub(r"\bgr\.?\s*[1234b]\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def car_match_score(target, candidate):
    a = normalize_car_name(target)
    b = normalize_car_name(candidate)
    if not a or not b:
        return 0
    if a == b:
        return 100
    if a in b or b in a:
        return 94
    a_tokens = set(a.split())
    b_tokens = set(b.split())
    if not a_tokens or not b_tokens:
        return 0
    overlap = len(a_tokens & b_tokens)
    union = len(a_tokens | b_tokens)
    jaccard = overlap / union if union else 0.0
    containment = overlap / min(len(a_tokens), len(b_tokens))
    return int(round(100 * (0.60 * jaccard + 0.40 * containment)))


def records_for_car(all_records, car, group):
    group = normalize_group(group)
    candidates = []
    for record in all_records:
        if normalize_group(record.get("group")) != group:
            continue
        score = car_match_score(car, record.get("car"))
        if score >= 68:
            candidates.append((score, record))
    if not candidates:
        return [], None
    best_score = max(score for score, _ in candidates)
    best_name = next(record.get("car") for score, record in candidates if score == best_score)
    selected = [record for score, record in candidates if record.get("car") == best_name]
    return selected, {
        "requested_name": car,
        "matched_name": best_name,
        "match_score": best_score,
    }


def latest_version(records):
    versions = {
        str(record.get("bop_version") or "").strip()
        for record in records
        if record.get("bop_version")
    }
    return max(versions, key=version_key) if versions else None


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


def fingerprint_profile(all_records, car, group):
    records, match = records_for_car(all_records, car, group)
    if not records:
        return {
            "car": car,
            "available": False,
            "reason": "No matching BoP records for this car/group.",
            "match": None,
        }
    version = latest_version(records)
    by_speed = {}
    for speed in ["HIGH", "MID", "LOW"]:
        selected = next(
            (
                record for record in records
                if str(record.get("speed_class") or "").upper() == speed
                and str(record.get("bop_version") or "") == str(version)
            ),
            None,
        )
        by_speed[speed] = compact_bop(selected)
    signatures = []
    for speed in ["HIGH", "MID", "LOW"]:
        item = by_speed.get(speed)
        if item:
            signatures.append((item.get("power_hp"), item.get("weight_kg"), item.get("pp")))
    return {
        "car": car,
        "available": len(signatures) == 3,
        "match": match,
        "bop_version": version,
        "distinct_signatures": len(set(signatures)),
        "can_identify_speed_class_from_car": len(signatures) == 3 and len(set(signatures)) > 1,
        "HIGH": by_speed.get("HIGH"),
        "MID": by_speed.get("MID"),
        "LOW": by_speed.get("LOW"),
    }


def resolve_track_speed(mapping, group, description):
    explicit = detect_explicit_speed(description)
    if explicit:
        return explicit, "EXPLICIT_EVENT_TEXT", "DIRECT"

    group = normalize_group(group)
    overrides = mapping.get("group_speed_classes") or {}
    if group in overrides:
        speed = str(overrides[group]).upper()
        if speed in VALID_SPEEDS:
            return speed, "GROUP_SPECIFIC_MAP", mapping.get("confidence") or "VALIDATED_EXTERNAL"

    speed = str(mapping.get("speed_class") or mapping.get("default_speed_class") or "").upper()
    if speed in VALID_SPEEDS:
        return speed, "TRACK_DEFAULT_MAP", mapping.get("confidence") or "VALIDATED_EXTERNAL"

    return None, "UNRESOLVED", "UNRESOLVED"


def format_number(value):
    if isinstance(value, (int, float)):
        return f"{value:g}"
    return "N/A"


def format_bop(record):
    if not record:
        return "N/A"
    return (
        f"{format_number(record.get('power_hp'))} HP / "
        f"{format_number(record.get('weight_kg'))} kg / "
        f"PP {format_number(record.get('pp'))}"
    )


def run_classifier():
    snapshot = load_json(LATEST_SNAPSHOT_FILE)
    mapping_payload = load_json(TRACK_MAP_FILE)
    database_payload = load_json(BOP_DATABASE_FILE)

    track_map = mapping_payload.get("tracks") or {}
    all_records = database_payload.get("records") or []
    race = snapshot.get("race") or {}
    description = race.get("description") or ""
    track = detect_track(description, track_map)
    group = detect_group(description)

    if not track:
        raise RuntimeError(
            "Current track was not found in track_bop_classes.json. "
            f"Race description: {description}"
        )
    if group not in VALID_GROUPS:
        raise RuntimeError(
            "Could not determine a supported race group from latest snapshot. "
            f"Race description: {description}"
        )

    mapping = track_map[track]
    speed_class, selection_mode, confidence = resolve_track_speed(mapping, group, description)
    if speed_class not in VALID_SPEEDS:
        raise RuntimeError(f"No valid BoP speed class for {track} / {group}")

    my_result = snapshot.get("my_result") or {}
    my_car = my_result.get("car")
    my_profile = fingerprint_profile(all_records, my_car, group) if my_car else None
    active_bop = my_profile.get(speed_class) if my_profile and my_profile.get("available") else None

    top5_profiles = []
    for item in (snapshot.get("top5_used_cars") or [])[:5]:
        car = item.get("car")
        if not car:
            continue
        profile = fingerprint_profile(all_records, car, group)
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
        "model_key": f"{group}|{speed_class}",
        "speed_class": speed_class,
        "speed_selection_mode": selection_mode,
        "classification_confidence": confidence,
        "classification_validation": mapping.get("validation") or [],
        "database_records": len(all_records),
        "my_car": my_car,
        "my_car_fingerprint": my_profile,
        "my_car_active_bop": active_bop,
        "top5_used_cars": top5_profiles,
        "production_pipeline_modified": False,
    }

    RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULT_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"GT7 BOP TRACK CLASSIFIER V{VERSION}", SEP,
        f"Generated            : {result['generated_at']}",
        f"Snapshot             : {snapshot.get('timestamp')}",
        f"Track                : {track}",
        f"Group                : {group}",
        f"Model key            : {result['model_key']}",
        f"BoP speed class      : {speed_class}",
        f"Selection mode       : {selection_mode}",
        f"Confidence           : {confidence}",
        f"BoP DB records       : {len(all_records)}",
        "Production modified  : NO", "", "CLASSIFICATION EVIDENCE", SUB,
    ]
    for evidence in mapping.get("validation") or []:
        lines.append(f"- {evidence.get('source')} | {evidence.get('evidence')}")

    lines += ["", "YOUR CURRENT CAR", SUB]
    if not my_car:
        lines.append("No current personal car in latest snapshot.")
    elif not my_profile or not my_profile.get("available"):
        lines.append(f"Car                  : {my_car}")
        lines.append("BoP records          : unavailable")
        if my_profile:
            lines.append(f"Reason               : {my_profile.get('reason')}")
    else:
        match = my_profile.get("match") or {}
        lines.append(f"Car                  : {my_car}")
        lines.append(f"Matched DB car       : {match.get('matched_name')}")
        lines.append(f"Name match score     : {match.get('match_score')}")
        lines.append(f"BoP version          : {my_profile.get('bop_version')}")
        lines.append(f"HIGH                 : {format_bop(my_profile.get('HIGH'))}")
        lines.append(f"MID                  : {format_bop(my_profile.get('MID'))}")
        lines.append(f"LOW                  : {format_bop(my_profile.get('LOW'))}")
        lines.append(f"ACTIVE {speed_class:<12}: {format_bop(active_bop)}")
        lines.append(
            "Fingerprint usable   : "
            + ("YES" if my_profile.get("can_identify_speed_class_from_car") else "NO")
        )

    lines += ["", "TOP 5 USED CARS", SUB]
    for i, profile in enumerate(top5_profiles, 1):
        match = profile.get("match") or {}
        lines.append(
            f"{i}. {profile.get('car')} | DB={match.get('matched_name')} | "
            f"score={match.get('match_score')} | active={format_bop(profile.get('active_bop'))} | "
            f"fingerprint={'YES' if profile.get('can_identify_speed_class_from_car') else 'NO'}"
        )

    lines += ["", "CLASSIFIER POLICY", SUB,
              "Priority 1: explicit BOP (H/M/L) in event text when available.",
              "Priority 2: group-specific track mapping.",
              "Priority 3: validated track default mapping.",
              "This avoids assuming that one historical track classification must apply to every group/event forever.",
              SEP]

    REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")
    if ERROR_FILE.exists():
        ERROR_FILE.unlink()
    print("\n".join(lines))


def main():
    try:
        run_classifier()
    except Exception as error:
        ERROR_FILE.parent.mkdir(parents=True, exist_ok=True)
        REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
        diagnostic = (
            f"GT7 BOP TRACK CLASSIFIER V{VERSION} - ERROR\n{SEP}\n"
            f"Generated: {now_iso()}\nError: {type(error).__name__}: {error}\n\n"
            f"TRACEBACK\n{SUB}\n{traceback.format_exc()}\n{SEP}\n"
        )
        ERROR_FILE.write_text(diagnostic, encoding="utf-8")
        REPORT_FILE.write_text(diagnostic, encoding="utf-8")
        print(diagnostic)
        raise


if __name__ == "__main__":
    main()
