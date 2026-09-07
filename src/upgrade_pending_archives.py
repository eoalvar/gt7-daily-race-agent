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


def pending_records(history):
    records = []
    for record in history:
        if not isinstance(record, dict):
            continue
        mode = str(record.get("finalization_mode") or "")
        pending = record.get("archive_upgrade_pending") is True or mode == "snapshot_fallback_pending_archive"
        week = str(record.get("week_start") or "").strip()
        if pending and week:
            records.append(record)
    # Keep only the latest record for each week.
    by_week = {}
    for record in records:
        by_week[str(record.get("week_start"))] = record
    return [by_week[k] for k in sorted(by_week)]


def parse_week(week: str):
    return datetime.strptime(week, "%Y-%m-%d").replace(tzinfo=SAO_PAULO)


def try_load_complete(session, url):
    if not url:
        return None
    try:
        result = recovery.get_full_event_ranking(session, url)
    except Exception as error:
        print(f"Stored leaderboard URL not ready: {type(error).__name__}: {error}")
        return None

    ranking = result.get("ranking") or []
    total_records = result.get("total_records")
    complete = result.get("complete", False)
    if not complete or not isinstance(total_records, int) or len(ranking) != total_records:
        print(
            "Stored leaderboard URL is reachable but not complete yet: "
            f"loaded={len(ranking)} total={total_records} complete={complete}"
        )
        return None
    return result


def main():
    history = load_history()
    pending = pending_records(history)

    if not pending:
        print("No pending Daily C archive upgrades.")
        return

    session = requests.Session()
    session.headers.update(finalizer.HEADERS)

    upgraded = 0
    for source in pending:
        week = str(source.get("week_start"))
        print(f"Checking pending archive for {week}...")
        target = parse_week(week)

        # Primary path: use the exact leaderboard URL captured during the race week.
        # GTSH can expose a completed archived leaderboard before its server-rendered
        # archive index changes from Running to Archived, so archive-page discovery is
        # not a reliable gate for finalization.
        url = str(source.get("leaderboard_url") or "").strip()
        result = try_load_complete(session, url)
        event = None

        if result is not None:
            event_text = str(source.get("race") or "Daily Race C")
            event_text = event_text.replace(" Running ", " Archived ", 1)
            event = {"date": target, "text": event_text, "url": url}
            print("Using stored leaderboard URL; full leaderboard is complete.")
        else:
            # Secondary path for historical rows that lack a usable stored URL.
            try:
                event = finalizer.discover_previous_race_c(session, target)
                result = try_load_complete(session, event["url"])
            except Exception as error:
                print(f"Archive index still unavailable for {week}: {error}")
                result = None

        if event is None or result is None:
            print(f"No definitive full leaderboard available yet for {week}.")
            continue

        try:
            ranking = result["ranking"]
            total_records = result["total_records"]
            extraction_mode = result["mode"]

            record = finalizer.build_final_record(
                event,
                ranking,
                total_records,
                extraction_mode,
            )
            benchmarks = finalizer.build_final_benchmarks(ranking)

            record["week_start"] = week
            record["archive_upgrade_pending"] = False
            record.pop("fallback_source_snapshot", None)

            finalizer.upsert_weekly_record(history, record)

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
