import json
import time
from collections import defaultdict
from pathlib import Path
from datetime import datetime

import requests

from backfill_history import get_full_event_ranking, get_car_code
from car_database import load_car_database, get_car_name
from sleeper_car_lab import (
    bayesian_lift,
    quality_component,
    TIER_WEIGHTS,
    PRIOR_STRENGTH,
)
from bop_track_classifier import records_for_car, latest_version

VERSION = "0.2"
MIN_RACES = 3
MIN_CAR_SAMPLE = 20

WEEKLY_HISTORY_FILE = Path("data/weekly_rating_history.json")
TRAINING_FILE = Path("data/bop_lab/sleeper_training_history.json")
TRACK_MAP_FILE = Path("data/bop_lab/track_bop_classes.json")
BOP_DB_FILE = Path("data/bop_lab/bop_database.json")
CURRENT_RESULT_FILE = Path("data/bop_lab/sleeper_car_index.json")
REPORT_FILE = Path("reports/sleeper_history_backfill.txt")

SEP = "=" * 100


def load_json(path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def safe_int(v):
    try:
        return int(v)
    except Exception:
        return None


def safe_float(v):
    try:
        return float(v)
    except Exception:
        return None


def normalize_group(text):
    s = str(text or "").upper().replace(" ", "")
    if "GR.3" in s or "GR3" in s:
        return "GR.3"
    if "GR.4" in s or "GR4" in s:
        return "GR.4"
    if "GR.2" in s or "GR2" in s:
        return "GR.2"
    if "GR.1" in s or "GR1" in s:
        return "GR.1"
    if "GR.B" in s or "GRB" in s:
        return "GR.B"
    return None


def normalize_track(text, track_map):
    hay = str(text or "").lower()
    best = None
    for track in track_map:
        if track.lower() in hay:
            if best is None or len(track) > len(best):
                best = track
    return best


def speed_for_track(track_map, track):
    item = (track_map.get("tracks") or {}).get(track) or {}
    speed = str(item.get("speed_class") or "").upper()
    return speed if speed in {"HIGH", "MID", "LOW"} else None


def week_key(value):
    text = str(value or "")[:10]
    try:
        d = datetime.fromisoformat(text)
        monday = d.date().toordinal() - d.weekday()
        return datetime.fromordinal(monday).date().isoformat()
    except Exception:
        return text or None


def active_bop(all_records, car, group, speed):
    records, _ = records_for_car(all_records, car, group)
    if not records:
        return None
    version = latest_version(records)
    return next((r for r in records
                 if str(r.get("bop_version")) == str(version)
                 and str(r.get("speed_class") or "").upper() == speed), None)


def technical(record):
    if not record:
        return None
    acc = record.get("acceleration") or {}
    rot = record.get("rotational_g") or {}
    try:
        front = float(str(record.get("weight_balance")).split(":", 1)[0])
    except Exception:
        front = None
    return {
        "power_weight_hp_t": safe_float(record.get("power_weight_hp_t")),
        "weight_kg": safe_float(record.get("weight_kg")),
        "front_weight_pct": front,
        "acceleration_0_400": safe_float(acc.get("0_400m")),
        "acceleration_100_150": safe_float(acc.get("100_150_kmh")),
        "rotational_g_60": safe_float(rot.get("60_kmh")),
        "rotational_g_120": safe_float(rot.get("120_kmh")),
        "rotational_g_240": safe_float(rot.get("240_kmh")),
    }


def build_training_cars(ranking, total, group, speed, bop_records, car_names):
    stats = defaultdict(lambda: {
        "n": 0, "t100": 0, "t500": 0, "t1000": 0,
        "best_rank": None, "best_score": None,
    })

    for driver in ranking:
        try:
            code = int(get_car_code(driver))
        except Exception:
            continue
        rank = safe_int(driver.get("rank"))
        if rank is None:
            rank = safe_int((driver.get("ranking_stats") or {}).get("rank"))
        score = safe_int(driver.get("score"))
        if score is None:
            score = safe_int((driver.get("ranking_stats") or {}).get("score"))
        s = stats[code]
        s["n"] += 1
        if rank:
            s["t100"] += int(rank <= 100)
            s["t500"] += int(rank <= 500)
            s["t1000"] += int(rank <= 1000)
            if s["best_rank"] is None or rank < s["best_rank"]:
                s["best_rank"] = rank
        if score is not None and (s["best_score"] is None or score < s["best_score"]):
            s["best_score"] = score

    wr = min((s["best_score"] for s in stats.values() if s["best_score"] is not None), default=None)
    ranked_scores = sorted(s["best_score"] for s in stats.values() if s["best_score"] is not None)
    top500_proxy = ranked_scores[min(len(ranked_scores)-1, max(0, len(ranked_scores)//3))] if ranked_scores else None
    elite_scale = max(1.0, float((top500_proxy or wr or 1) - (wr or 0)))

    cars = []
    for code, s in stats.items():
        if s["n"] < MIN_CAR_SAMPLE:
            continue
        car = get_car_name(code, car_names)
        bop = active_bop(bop_records, car, group, speed)
        tech = technical(bop)
        if not tech:
            continue
        lifts = {
            100: bayesian_lift(s["t100"], s["n"], 100, total),
            500: bayesian_lift(s["t500"], s["n"], 500, total),
            1000: bayesian_lift(s["t1000"], s["n"], 1000, total),
        }
        weighted = sum(TIER_WEIGHTS[t] * __import__("math").log(max(lifts[t], 1e-9)) for t in TIER_WEIGHTS)
        quality = quality_component(__import__("math").exp(weighted))
        elite = 0.0
        if wr is not None and s["best_score"] is not None:
            elite = __import__("math").exp(-max(0.0, float(s["best_score"] - wr)) / elite_scale)
        cars.append({
            "car_code": code,
            "car": car,
            "sample": s["n"],
            "performance_target": 0.65 * quality + 0.35 * elite,
            "technical": tech,
        })
    return cars


def current_week_key(current):
    stamp = current.get("snapshot_timestamp") or current.get("generated_at")
    return week_key(stamp)


def clean_existing_history(history, target_group, target_speed, current_week):
    races = history.get("races") or []
    cleaned = []
    seen_independent = set()
    removed = []

    for race in races:
        group = race.get("group")
        speed = race.get("speed_class")
        status = race.get("status")
        wk = race.get("week_start") or week_key(race.get("race_key") or race.get("captured_at"))

        # Keep live current observation exactly once.
        if status == "LIVE_SNAPSHOT":
            key = ("LIVE", group, speed, wk)
        else:
            key = ("HIST", group, speed, wk)

        # Historical records from the current week are not independent races.
        if status == "HISTORICAL_FINAL" and group == target_group and speed == target_speed and wk == current_week:
            removed.append(race)
            continue

        # For training independence, one historical observation per group/speed/week.
        if key in seen_independent:
            removed.append(race)
            continue

        seen_independent.add(key)
        race["week_start"] = wk
        cleaned.append(race)

    history["races"] = cleaned
    return removed


def main():
    weekly = load_json(WEEKLY_HISTORY_FILE, []) or []
    history = load_json(TRAINING_FILE, {"schema_version": "0.2", "races": []}) or {"schema_version": "0.2", "races": []}
    track_map = load_json(TRACK_MAP_FILE, {}) or {}
    bop_db = load_json(BOP_DB_FILE, {}) or {}
    current = load_json(CURRENT_RESULT_FILE, {}) or {}

    target_group = current.get("group") or "GR.3"
    target_speed = str(current.get("speed_class") or "").upper()
    cur_week = current_week_key(current)

    removed = clean_existing_history(history, target_group, target_speed, cur_week)

    existing = [r for r in history.get("races", [])
                if r.get("group") == target_group and r.get("speed_class") == target_speed]
    independent_weeks = {r.get("week_start") for r in existing if r.get("week_start")}

    candidates = []
    for item in weekly:
        desc = item.get("race_description") or item.get("description") or ""
        group = normalize_group(desc)
        if group != target_group:
            continue
        track = normalize_track(desc, track_map.get("tracks") or {})
        if not track:
            continue
        speed = speed_for_track(track_map, track)
        if speed != target_speed:
            continue
        url = item.get("leaderboard_url")
        wk = week_key(item.get("week_start") or item.get("date") or item.get("timestamp"))
        if not url or not wk:
            continue
        # Never backfill the same week as the current live race.
        if wk == cur_week:
            continue
        # One independent observation per week.
        if wk in independent_weeks:
            continue
        candidates.append((wk, track, url, desc))

    # newest historical weeks first; dedupe candidate list by week
    unique = {}
    for candidate in candidates:
        unique.setdefault(candidate[0], candidate)
    candidates = sorted(unique.values(), key=lambda x: x[0], reverse=True)

    lines = [
        f"GT7 SLEEPER HISTORY BACKFILL V{VERSION}", SEP,
        f"Target group          : {target_group}",
        f"Target speed class    : {target_speed}",
        f"Current live week     : {cur_week}",
        f"Removed false/duplicate observations : {len(removed)}",
        f"Existing independent observations    : {len(existing)}",
        f"Target observations   : {MIN_RACES}",
        f"Eligible historical weeks : {len(candidates)}", "",
    ]

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 GT7 Sleeper Historical Backfill"})
    car_names = load_car_database()
    bop_records = bop_db.get("records") or []
    added = 0

    for wk, track, url, desc in candidates:
        current_count = len([r for r in history.get("races", [])
                             if r.get("group") == target_group and r.get("speed_class") == target_speed])
        if current_count >= MIN_RACES:
            break
        try:
            ranking, total = get_full_event_ranking(session, url)
            if not ranking or not total:
                lines.append(f"SKIP {wk} | {track} | no ranking")
                continue
            cars = build_training_cars(ranking, total, target_group, target_speed, bop_records, car_names)
            if len(cars) < 5:
                lines.append(f"SKIP {wk} | {track} | only {len(cars)} usable cars")
                continue
            history.setdefault("races", []).append({
                "race_key": f"historical:{wk}:{url}",
                "week_start": wk,
                "captured_at": datetime.now().astimezone().isoformat(),
                "track": track,
                "group": target_group,
                "speed_class": target_speed,
                "status": "HISTORICAL_FINAL",
                "leaderboard_url": url,
                "total_drivers": total,
                "cars": cars,
            })
            independent_weeks.add(wk)
            added += 1
            lines.append(f"ADDED {wk} | {track} | {target_speed} | drivers {total:,} | cars {len(cars)}")
            time.sleep(0.2)
        except Exception as exc:
            lines.append(f"ERROR {wk} | {track} | {type(exc).__name__}: {exc}")

    history["updated_at"] = datetime.now().astimezone().isoformat()
    TRAINING_FILE.parent.mkdir(parents=True, exist_ok=True)
    TRAINING_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

    final_count = len([r for r in history.get("races", [])
                       if r.get("group") == target_group and r.get("speed_class") == target_speed])
    final_weeks = sorted({r.get("week_start") for r in history.get("races", [])
                          if r.get("group") == target_group and r.get("speed_class") == target_speed and r.get("week_start")})
    lines += ["", f"Added this run        : {added}", f"Final independent observations : {final_count}",
              f"Independent weeks     : {', '.join(final_weeks) if final_weeks else 'N/A'}",
              f"STATUS                : {'READY' if final_count >= MIN_RACES else 'BOOTSTRAP'}"]
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
