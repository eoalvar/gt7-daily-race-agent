import json
import time
import traceback
from pathlib import Path

import requests

import backfill_history as historical
from car_database import load_car_database
from debug_current_race import get_rank, get_score
from sleeper_car_lab import build_car_statistics, calculate_index, MIN_CAR_SAMPLE
from sleeper_technical_learning import technical

VERSION = "0.1"

WEEKLY_HISTORY_FILE = Path("data/weekly_rating_history.json")
TRACK_MAP_FILE = Path("data/bop_lab/track_bop_classes.json")
CURRENT_TRACK_FILE = Path("data/bop_lab/current_track_bop.json")
BOP_DATABASE_FILE = Path("data/bop_lab/bop_database.json")
TRAINING_FILE = Path("data/bop_lab/sleeper_training_history.json")
REPORT_FILE = Path("reports/sleeper_history_backfill.txt")
ERROR_FILE = Path("data/bop_lab/sleeper_history_backfill_error.txt")

TARGET_TOTAL_RACES = 3
PAGE_DELAY_SECONDS = 0.03
SEP = "=" * 100
SUB = "-" * 100


def load_json(path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def detect_track(text, tracks):
    normalized = str(text or "").casefold()
    for name in sorted(tracks.keys(), key=len, reverse=True):
        if name.casefold() in normalized:
            return name
    return None


def fetch_complete_archived_leaderboard(session, event_url):
    ranking = []
    offset = 0
    total = None
    page_no = 0

    while total is None or offset < total:
        page_no += 1
        page = historical.fetch_page(session, event_url, offset)
        board = page.get("board") or []
        if not board:
            if offset == 0:
                raise RuntimeError("Historical leaderboard returned no drivers.")
            break

        if total is None:
            total = int(page.get("total") or len(board))

        ranking.extend(board)
        offset += len(board)

        if page_no <= 3 or page_no % 100 == 0 or offset >= total:
            print(f"  page {page_no:<4} | {offset:,}/{total:,}")

        if not page.get("has_more") and offset < total:
            raise RuntimeError(
                f"Historical pagination ended early: {offset:,}/{total:,}."
            )

        time.sleep(PAGE_DELAY_SECONDS)

    ranking.sort(
        key=lambda item: (
            int(get_rank(item) or 10**9),
            int(get_score(item) or 10**9),
        )
    )

    return ranking, int(total or len(ranking))


def existing_peer_count(history, group, speed_class):
    return len([
        race for race in history.get("races", [])
        if race.get("group") == group
        and race.get("speed_class") == speed_class
    ])


def already_stored(history, event_url):
    return any(
        race.get("leaderboard_url") == event_url
        for race in history.get("races", [])
    )


def upsert_history(history, record):
    races = history.setdefault("races", [])
    event_url = record.get("leaderboard_url")
    for i, old in enumerate(races):
        if old.get("leaderboard_url") == event_url:
            races[i] = record
            return
    races.append(record)


def build_training_record(event, track, speed_class, ranking, total, bop_records):
    if not ranking:
        raise RuntimeError("Historical ranking is empty.")

    wr_score = int(get_score(ranking[0]))
    top500_score = int(get_score(ranking[min(499, len(ranking) - 1)]))

    car_stats = build_car_statistics(
        ranking,
        total,
        load_car_database(),
    )

    results = calculate_index(
        car_stats=car_stats,
        total=total,
        wr_score=wr_score,
        top500_score=top500_score,
        all_bop_records=bop_records,
        group="GR.3",
        speed_class=speed_class,
    )

    cars = []
    for item in results:
        if item.get("all_count", 0) < MIN_CAR_SAMPLE:
            continue
        tech = technical(item.get("active_bop") or {})
        if not tech:
            continue
        quality = float(item.get("quality_component") or 0.0)
        elite = float(item.get("elite_proximity") or 0.0)
        cars.append({
            "car_code": item.get("car_code"),
            "car": item.get("car"),
            "sample": item.get("all_count"),
            "performance_target": 0.65 * quality + 0.35 * elite,
            "technical": tech,
        })

    return {
        "race_key": event.get("week_start") or event.get("leaderboard_url"),
        "leaderboard_url": event.get("leaderboard_url"),
        "captured_at": event.get("week_start"),
        "track": track,
        "group": "GR.3",
        "speed_class": speed_class,
        "status": "HISTORICAL_FINAL",
        "total_drivers": total,
        "world_record_score": wr_score,
        "top500_score": top500_score,
        "cars": cars,
    }


def main():
    weekly = load_json(WEEKLY_HISTORY_FILE, []) or []
    track_map = load_json(TRACK_MAP_FILE, {}) or {}
    current = load_json(CURRENT_TRACK_FILE, {}) or {}
    bop_database = load_json(BOP_DATABASE_FILE, {}) or {}
    history = load_json(TRAINING_FILE, {"schema_version": "0.2", "races": []}) or {
        "schema_version": "0.2", "races": []
    }

    tracks = track_map.get("tracks") or {}
    target_group = current.get("group") or "GR.3"
    target_speed = str(current.get("speed_class") or "").upper()

    if target_group != "GR.3":
        raise RuntimeError(f"Backfill currently supports GR.3 only; active group is {target_group}.")
    if target_speed not in {"HIGH", "MID", "LOW"}:
        raise RuntimeError(f"Invalid current speed class: {target_speed}")

    existing = existing_peer_count(history, target_group, target_speed)
    needed = max(0, TARGET_TOTAL_RACES - existing)

    print(f"\nGT7 SLEEPER HISTORY BACKFILL V{VERSION}\n{SEP}")
    print(f"Target group         : {target_group}")
    print(f"Target speed class   : {target_speed}")
    print(f"Existing observations: {existing}")
    print(f"Target observations  : {TARGET_TOTAL_RACES}")
    print(f"Historical races needed: {needed}\n")

    candidates = []
    for event in weekly:
        race_text = event.get("race") or ""
        event_url = event.get("leaderboard_url")
        if not event_url or "Gr.3" not in race_text:
            continue
        track = detect_track(race_text, tracks)
        if not track:
            continue
        mapping = tracks.get(track) or {}
        speed = str(mapping.get("speed_class") or "").upper()
        if speed != target_speed:
            continue
        if already_stored(history, event_url):
            continue
        candidates.append((event, track, speed))

    candidates.sort(key=lambda x: str(x[0].get("week_start") or ""), reverse=True)

    lines = [
        f"GT7 SLEEPER HISTORY BACKFILL V{VERSION}", SEP,
        f"Target group          : {target_group}",
        f"Target speed class    : {target_speed}",
        f"Existing observations : {existing}",
        f"Target observations   : {TARGET_TOTAL_RACES}",
        f"Eligible candidates   : {len(candidates)}", "",
    ]

    if needed == 0:
        lines.append("No backfill required: target evidence count already reached.")
    else:
        session = requests.Session()
        session.headers.update(historical.HEADERS)
        bop_records = bop_database.get("records") or []
        added = 0

        for event, track, speed in candidates:
            if added >= needed:
                break

            week = event.get("week_start")
            url = event.get("leaderboard_url")
            print(f"BACKFILL {week} | {track} | {speed}")

            try:
                ranking, total = fetch_complete_archived_leaderboard(session, url)
                record = build_training_record(event, track, speed, ranking, total, bop_records)
                upsert_history(history, record)
                save_json(TRAINING_FILE, history)
                added += 1
                lines.append(
                    f"ADDED {week} | {track} | {speed} | drivers {total:,} | cars {len(record['cars'])}"
                )
            except Exception as error:
                lines.append(f"FAILED {week} | {track} | {type(error).__name__}: {error}")

        final_count = existing_peer_count(history, target_group, target_speed)
        lines += ["", f"Added this run        : {added}", f"Final observations    : {final_count}"]
        if final_count >= TARGET_TOTAL_RACES:
            lines.append("STATUS                : READY FOR TECHNICAL MODEL ACTIVATION")
        else:
            lines.append("STATUS                : BOOTSTRAP - not enough validated historical races yet")

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if ERROR_FILE.exists():
        ERROR_FILE.unlink()
    print("\n" + "\n".join(lines))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        ERROR_FILE.parent.mkdir(parents=True, exist_ok=True)
        ERROR_FILE.write_text(traceback.format_exc(), encoding="utf-8")
        raise
