#!/usr/bin/env python3

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

import finalize_previous_week as finalizer
import recover_historical_race as recovery

HISTORY_FILE = Path("data/weekly_rating_history.json")
SAO_PAULO = ZoneInfo("America/Sao_Paulo")


def load_history():
    if not HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def pending_weeks(history):
    weeks = []
    for record in history:
        if not isinstance(record, dict):
            continue
        mode = str(record.get("finalization_mode") or "")
        pending = record.get("archive_upgrade_pending") is True or mode == "snapshot_fallback_pending_archive"
        week = str(record.get("week_start") or "").strip()
        if pending and week and week not in weeks:
            weeks.append(week)
    return sorted(weeks)


def parse_week(week: str):
    return datetime.strptime(week, "%Y-%m-%d").replace(tzinfo=SAO_PAULO)


def main():
    history = load_history()
    weeks = pending_weeks(history)

    if not weeks:
        print("No pending Daily C archive upgrades.")
        return

    session = requests.Session()
    session.headers.update(finalizer.HEADERS)

    upgraded = 0
    for week in weeks:
        print(f"Checking pending archive for {week}...")
        target = parse_week(week)

        try:
            event = finalizer.discover_previous_race_c(session, target)
        except Exception as error:
            print(f"Archive still unavailable for {week}: {error}")
            continue

        try:
            result = recovery.get_full_event_ranking(session, event["url"])
            ranking = result["ranking"]
            total_records = result["total_records"]
            extraction_mode = result["mode"]
            complete = result.get("complete", False)

            if not complete or len(ranking) != total_records:
                print(f"Archive found for {week}, but full leaderboard is not complete yet.")
                continue

            record = finalizer.build_final_record(
                event,
                ranking,
                total_records,
                extraction_mode,
            )
            benchmarks = finalizer.build_final_benchmarks(ranking)

            # Force exact target week in case the page text carries an unexpected date.
            record["week_start"] = week
            record["archive_upgrade_pending"] = False
            record.pop("fallback_source_snapshot", None)

            finalizer.upsert_weekly_record(history, record)

            # Keep the detailed payload available when the upgraded race is the latest
            # pending week. This does not affect the current Daily C email by itself.
            payload = {
                "version": finalizer.VERSION,
                "generated_at": datetime.now(SAO_PAULO).isoformat(),
                "week_start": week,
                "complete_leaderboard": True,
                "loaded_drivers": len(ranking),
                "total_drivers": total_records,
                "extraction_mode": extraction_mode,
                "result": record,
                "benchmarks": benchmarks,
                "archive_upgrade_pending": False,
            }
            finalizer.OUTPUT_JSON.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            print(
                f"UPGRADED {week}: #{record['position']:,}/{record['total_drivers']:,} "
                f"{record['laptime']}"
            )
            upgraded += 1

        except Exception as error:
            print(f"Could not upgrade {week} yet: {type(error).__name__}: {error}")

    print(f"Archive upgrade check complete. Upgraded: {upgraded}.")


if __name__ == "__main__":
    main()
