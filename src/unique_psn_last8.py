from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import requests

import recover_historical_race as recovery

HISTORY_FILE = Path("data/weekly_rating_history.json")
SNAPSHOT_FILE = Path("data/latest_snapshot.json")
OUT_JSON = Path("data/unique_psn_last8.json")
OUT_REPORT = Path("reports/unique_psn_last8.txt")
MAX_RACES = 8


def norm_psn(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value.casefold() if value else None


def race_key(item):
    return str(item.get("week_start") or item.get("start_date") or item.get("timestamp") or "")


def load_latest_races():
    races = []

    if HISTORY_FILE.exists():
        history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        if isinstance(history, list):
            for item in history:
                if not isinstance(item, dict) or not item.get("leaderboard_url"):
                    continue
                races.append({
                    "week_start": item.get("week_start"),
                    "race": item.get("race"),
                    "leaderboard_url": item.get("leaderboard_url"),
                    "source": "weekly_history",
                })

    if SNAPSHOT_FILE.exists():
        snap = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
        race = snap.get("race") or {}
        if race.get("leaderboard_url"):
            current = {
                "week_start": (race.get("start_date") or "")[:10],
                "race": race.get("description"),
                "leaderboard_url": race.get("leaderboard_url"),
                "source": "latest_snapshot",
            }
            races.append(current)

    # Deduplicate by leaderboard URL, preferring the latest occurrence.
    dedup = {}
    for item in races:
        dedup[item["leaderboard_url"]] = item
    races = list(dedup.values())
    races.sort(key=race_key)
    return races[-MAX_RACES:]


def extract_psn(driver):
    if not isinstance(driver, dict):
        return None
    user = driver.get("user") or {}
    for key in ("np_online_id", "nick_name", "nickname"):
        value = user.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def main():
    races = load_latest_races()
    if len(races) < MAX_RACES:
        raise RuntimeError(f"Only {len(races)} Daily Race C records with leaderboard URLs were found; need {MAX_RACES}.")

    session = requests.Session()
    session.headers.update(recovery.HEADERS)

    appearances = Counter()
    original_case = {}
    per_race = []
    failures = []

    for idx, race in enumerate(races, 1):
        label = race.get("week_start") or f"race_{idx}"
        print(f"[{idx}/{len(races)}] Loading {label}")
        try:
            result = recovery.get_full_event_ranking(session, race["leaderboard_url"])
            ranking = result.get("ranking") or []
            psns = set()
            missing_psn = 0
            for driver in ranking:
                psn = extract_psn(driver)
                key = norm_psn(psn)
                if key:
                    psns.add(key)
                    original_case.setdefault(key, psn)
                else:
                    missing_psn += 1

            for key in psns:
                appearances[key] += 1

            per_race.append({
                "week_start": race.get("week_start"),
                "race": race.get("race"),
                "leaderboard_url": race.get("leaderboard_url"),
                "leaderboard_rows": len(ranking),
                "unique_psn": len(psns),
                "rows_without_psn": missing_psn,
            })
            print(f"  rows={len(ranking):,} | unique PSN={len(psns):,} | missing PSN={missing_psn:,}")
        except Exception as exc:
            failures.append({"week_start": race.get("week_start"), "error": str(exc)})
            print(f"  FAILED: {exc}")

    if failures:
        raise RuntimeError(f"Could not analyse all 8 races: {failures}")

    frequency = Counter(appearances.values())
    unique_total = len(appearances)
    total_slots = sum(item["unique_psn"] for item in per_race)
    repeat_slots = total_slots - unique_total

    recurring_2plus = sum(1 for n in appearances.values() if n >= 2)
    recurring_4plus = sum(1 for n in appearances.values() if n >= 4)
    all_8 = sum(1 for n in appearances.values() if n == 8)

    payload = {
        "races_analysed": len(per_race),
        "unique_psn_across_8": unique_total,
        "sum_of_unique_psn_per_race": total_slots,
        "repeat_participation_slots": repeat_slots,
        "unique_psn_2plus_races": recurring_2plus,
        "unique_psn_4plus_races": recurring_4plus,
        "unique_psn_all_8_races": all_8,
        "participation_frequency": {str(k): frequency.get(k, 0) for k in range(1, 9)},
        "races": per_race,
        "psn_participation_counts": {
            original_case.get(key, key): count
            for key, count in sorted(appearances.items(), key=lambda kv: (-kv[1], kv[0]))
        },
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "GT7 DAILY RACE C - UNIQUE PSN STUDY (LAST 8)",
        "=" * 86,
        f"Unique PSN across 8 races : {unique_total:,}",
        f"Sum of race participants  : {total_slots:,}",
        f"Repeat participation slots: {repeat_slots:,}",
        "",
        "PARTICIPATION FREQUENCY",
    ]
    for k in range(1, 9):
        lines.append(f"Exactly {k} of 8 races : {frequency.get(k, 0):,} PSN")
    lines.extend([
        "",
        f"At least 2 races : {recurring_2plus:,} PSN",
        f"At least 4 races : {recurring_4plus:,} PSN",
        f"All 8 races      : {all_8:,} PSN",
        "",
        "PER-RACE COUNTS",
    ])
    for item in per_race:
        lines.append(
            f"{item.get('week_start') or 'N/A'} | {item['unique_psn']:,} unique PSN | {item['leaderboard_rows']:,} rows"
        )
    lines.append("=" * 86)
    report = "\n".join(lines) + "\n"
    OUT_REPORT.write_text(report, encoding="utf-8")

    print(report)
    print(f"Saved: {OUT_JSON}")
    print(f"Saved: {OUT_REPORT}")


if __name__ == "__main__":
    main()
