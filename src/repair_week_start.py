#!/usr/bin/env python3

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

HISTORY = Path("data/weekly_rating_history.json")
SAO_PAULO = ZoneInfo("America/Sao_Paulo")


def monday_for(dt: datetime) -> str:
    return (dt - timedelta(days=dt.weekday())).date().isoformat()


def infer_week_start(record):
    if record.get("week_start"):
        return record["week_start"]

    # Prefer an explicit race date if GTSH supplied one.
    race = str(record.get("race") or "")
    match = re.search(r"\b(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})\b", race)
    if match:
        try:
            dt = datetime.strptime(match.group(0), "%d %b %Y").replace(tzinfo=SAO_PAULO)
            return monday_for(dt)
        except ValueError:
            pass

    # Final snapshots are taken during the race week; use their Sao Paulo date.
    stamp = record.get("final_snapshot")
    if isinstance(stamp, str):
        try:
            dt = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(SAO_PAULO)
            return monday_for(dt)
        except ValueError:
            pass

    return None


def main():
    if not HISTORY.exists():
        print("No weekly history file; nothing to repair.")
        return

    history = json.loads(HISTORY.read_text(encoding="utf-8"))
    changed = 0
    for record in history:
        if not record.get("week_start"):
            inferred = infer_week_start(record)
            if inferred:
                record["week_start"] = inferred
                changed += 1
                print(f"Repaired week_start={inferred}: {record.get('race', '')[:90]}")

    history.sort(key=lambda item: str(item.get("week_start") or ""))
    HISTORY.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Repaired {changed} historical record(s).")


if __name__ == "__main__":
    main()
