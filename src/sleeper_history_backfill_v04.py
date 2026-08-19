import json
import time
from collections import defaultdict
from pathlib import Path
from datetime import datetime

import requests

from backfill_history import get_full_event_ranking
from car_database import load_car_database
from sleeper_history_backfill import (
    load_json,
    normalize_group,
    week_key,
    build_training_cars,
    clean_existing_history,
)
from bop_track_classifier import (
    detect_track,
    resolve_track_speed,
)

VERSION = "0.4"
MIN_RACES = 3
VALID_GROUPS = {"GR.1", "GR.2", "GR.3", "GR.4", "GR.B"}
VALID_SPEEDS = {"HIGH", "MID", "LOW"}

WEEKLY_HISTORY_FILE = Path("data/weekly_rating_history.json")
TRAINING_FILE = Path("data/bop_lab/sleeper_training_history.json")
TRACK_MAP_FILE = Path("data/bop_lab/track_bop_classes.json")
BOP_DB_FILE = Path("data/bop_lab/bop_database.json")
CURRENT_RESULT_FILE = Path("data/bop_lab/sleeper_car_index.json")
REPORT_FILE = Path("reports/sleeper_history_backfill.txt")
ERROR_FILE = Path("data/bop_lab/sleeper_history_backfill_error.txt")

SEP = "=" * 100


def current_week_key(current):
    stamp = current.get("snapshot_timestamp") or current.get("generated_at")
    return week_key(stamp)


def resolve_historical_track_and_speed(description, group, mapping_payload):
    tracks = mapping_payload.get("tracks") or {}
    track = detect_track(description, tracks)
    if not track:
        return None, None, "UNRESOLVED_TRACK"
    mapping = tracks.get(track) or {}
    speed, mode, _confidence = resolve_track_speed(mapping, group, description)
    return track, speed, mode


def main():
    weekly = load_json(WEEKLY_HISTORY_FILE, []) or []
    history = load_json(
        TRAINING_FILE,
        {"schema_version": VERSION, "races": []},
    ) or {"schema_version": VERSION, "races": []}
    track_map = load_json(TRACK_MAP_FILE, {}) or {}
    bop_db = load_json(BOP_DB_FILE, {}) or {}
    current = load_json(CURRENT_RESULT_FILE, {}) or {}

    target_group = current.get("group")
    target_speed = str(current.get("speed_class") or "").upper()
    cur_week = current_week_key(current)

    if target_group not in VALID_GROUPS:
        raise RuntimeError(f"Invalid or missing current group: {target_group}")
    if target_speed not in VALID_SPEEDS:
        raise RuntimeError(f"Invalid or missing current speed class: {target_speed}")
    if not cur_week:
        raise RuntimeError("Could not determine current live week.")

    removed = clean_existing_history(
        history,
        target_group,
        target_speed,
        cur_week,
    )

    existing = [
        r for r in history.get("races", [])
        if r.get("group") == target_group
        and str(r.get("speed_class") or "").upper() == target_speed
    ]
    independent_weeks = {
        r.get("week_start") for r in existing if r.get("week_start")
    }

    candidates = []
    unresolved_track = 0
    wrong_speed = 0
    explicit_speed_count = 0
    group_map_count = 0
    default_map_count = 0

    for item in weekly:
        desc = item.get("race_description") or item.get("description") or ""
        group = normalize_group(desc)
        if group != target_group:
            continue

        track, speed, mode = resolve_historical_track_and_speed(
            desc,
            group,
            track_map,
        )
        if not track:
            unresolved_track += 1
            continue
        if speed != target_speed:
            wrong_speed += 1
            continue

        if mode == "EXPLICIT_EVENT_TEXT":
            explicit_speed_count += 1
        elif mode == "GROUP_SPECIFIC_MAP":
            group_map_count += 1
        elif mode == "TRACK_DEFAULT_MAP":
            default_map_count += 1

        url = item.get("leaderboard_url")
        wk = week_key(
            item.get("week_start")
            or item.get("date")
            or item.get("timestamp")
        )
        if not url or not wk:
            continue
        if wk == cur_week or wk in independent_weeks:
            continue

        candidates.append((wk, track, url, desc, mode))

    unique = {}
    for candidate in candidates:
        unique.setdefault(candidate[0], candidate)
    candidates = sorted(unique.values(), key=lambda x: x[0], reverse=True)

    lines = [
        f"GT7 SLEEPER HISTORY BACKFILL V{VERSION}", SEP,
        f"Target model          : {target_group}|{target_speed}",
        f"Current live week     : {cur_week}",
        f"Removed invalid/duplicate observations : {len(removed)}",
        f"Existing independent observations      : {len(independent_weeks)}",
        f"Target observations   : {MIN_RACES}",
        f"Eligible historical weeks : {len(candidates)}",
        f"Unresolved track rows : {unresolved_track}",
        f"Other speed-class rows: {wrong_speed}",
        f"Speed resolution      : explicit={explicit_speed_count}, group-map={group_map_count}, default-map={default_map_count}",
        "",
    ]

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 GT7 Sleeper Historical Backfill V0.4"
    })
    car_names = load_car_database()
    bop_records = bop_db.get("records") or []
    added = 0

    for wk, track, url, desc, mode in candidates:
        current_weeks = {
            r.get("week_start")
            for r in history.get("races", [])
            if r.get("group") == target_group
            and str(r.get("speed_class") or "").upper() == target_speed
            and r.get("week_start")
        }
        if len(current_weeks) >= MIN_RACES:
            break

        try:
            ranking, total = get_full_event_ranking(session, url)
            if not ranking or not total:
                lines.append(f"SKIP {wk} | {track} | no ranking")
                continue

            cars = build_training_cars(
                ranking,
                total,
                target_group,
                target_speed,
                bop_records,
                car_names,
            )
            if len(cars) < 5:
                lines.append(
                    f"SKIP {wk} | {track} | only {len(cars)} usable cars"
                )
                continue

            history.setdefault("races", []).append({
                "race_key": f"historical:{target_group}:{target_speed}:{wk}",
                "week_start": wk,
                "captured_at": datetime.now().astimezone().isoformat(),
                "track": track,
                "group": target_group,
                "speed_class": target_speed,
                "model_key": f"{target_group}|{target_speed}",
                "speed_resolution_mode": mode,
                "status": "HISTORICAL_FINAL",
                "leaderboard_url": url,
                "total_drivers": total,
                "cars": cars,
            })
            independent_weeks.add(wk)
            added += 1
            lines.append(
                f"ADDED {wk} | {track} | {target_group}|{target_speed} | "
                f"{mode} | drivers {total:,} | cars {len(cars)}"
            )
            time.sleep(0.2)
        except Exception as exc:
            lines.append(
                f"ERROR {wk} | {track} | {type(exc).__name__}: {exc}"
            )

    history["schema_version"] = VERSION
    history["updated_at"] = datetime.now().astimezone().isoformat()
    TRAINING_FILE.parent.mkdir(parents=True, exist_ok=True)
    TRAINING_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    final_weeks = sorted({
        r.get("week_start")
        for r in history.get("races", [])
        if r.get("group") == target_group
        and str(r.get("speed_class") or "").upper() == target_speed
        and r.get("week_start")
    })
    final_count = len(final_weeks)

    model_coverage = defaultdict(set)
    for r in history.get("races", []):
        g = r.get("group")
        s = str(r.get("speed_class") or "").upper()
        wk = r.get("week_start")
        if g in VALID_GROUPS and s in VALID_SPEEDS and wk:
            model_coverage[f"{g}|{s}"].add(wk)

    lines += [
        "",
        f"Added this run        : {added}",
        f"Final independent observations : {final_count}",
        f"Independent weeks     : {', '.join(final_weeks) if final_weeks else 'N/A'}",
        f"STATUS                : {'READY' if final_count >= MIN_RACES else 'BOOTSTRAP'}",
        "",
        "ALL MODEL COVERAGE",
    ]
    for key, weeks in sorted(model_coverage.items()):
        lines.append(
            f"{key:<14} | {len(weeks)} independent race(s) | "
            f"{'READY' if len(weeks) >= MIN_RACES else 'BOOTSTRAP'}"
        )

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")
    if ERROR_FILE.exists():
        ERROR_FILE.unlink()
    print("\n".join(lines))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        ERROR_FILE.parent.mkdir(parents=True, exist_ok=True)
        ERROR_FILE.write_text(
            f"GT7 SLEEPER HISTORY BACKFILL V{VERSION} ERROR\n{SEP}\n"
            f"{type(exc).__name__}: {exc}\n",
            encoding="utf-8",
        )
        raise
