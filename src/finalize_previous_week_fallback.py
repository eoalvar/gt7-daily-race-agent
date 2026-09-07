#!/usr/bin/env python3

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

HISTORY = Path("data/weekly_rating_history.json")
OUTPUT_JSON = Path("data/previous_week_final.json")
OUTPUT_REPORT = Path("reports/previous_week_final.txt")
SAO_PAULO = ZoneInfo("America/Sao_Paulo")
SEPARATOR = "=" * 78


def monday_for(dt):
    return (dt - timedelta(days=dt.weekday())).date().isoformat()


def target_week():
    now = datetime.now(SAO_PAULO)
    current = now - timedelta(days=now.weekday())
    return (current - timedelta(days=7)).date().isoformat()


def load_history():
    if not HISTORY.exists():
        return []
    data = json.loads(HISTORY.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def eligible(record, week):
    if str(record.get("week_start") or "") != week:
        return False
    if not record.get("participated"):
        return False
    return record.get("score_ms") is not None and record.get("position") is not None and record.get("total_drivers") is not None


def snapshot_dt(record):
    value = record.get("final_snapshot")
    if not isinstance(value, str):
        return datetime.min.replace(tzinfo=SAO_PAULO)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(SAO_PAULO)
    except ValueError:
        return datetime.min.replace(tzinfo=SAO_PAULO)


def build_report(record):
    lines = ["LAST WEEK - FINAL RESULT", SEPARATOR]
    lines.append(f"Week            : {record.get('week_start')}")
    lines.append(f"Race            : {record.get('race', 'Daily Race C')}")
    lines.append("")
    lines.append("YOUR FINAL AVAILABLE RESULT")
    lines.append(f"Position        : #{int(record['position']):,} of {int(record['total_drivers']):,}")
    lines.append(f"Time            : {record.get('laptime', '-')}")
    if record.get("top_percent") is not None:
        lines.append(f"Top percentile  : Top {float(record['top_percent']):.2f}%")
    if record.get("percentile_ahead") is not None:
        lines.append(f"Ahead of        : {float(record['percentile_ahead']):.2f}% of participants")
    if record.get("wr_percentage") is not None:
        lines.append(f"WR percentage   : {float(record['wr_percentage']):.3f}%")
    if record.get("cpi_score") is not None:
        lines.append(f"CPI             : {float(record['cpi_score']):.2f} / 10 ({record.get('cpi_band', '-')})")
    lines.append("")
    lines.append("Status          : FINAL FALLBACK - last valid snapshot before archive")
    lines.append("Archive         : GTSH historical leaderboard not available yet")
    lines.append("Upgrade         : Will be replaced by archived full leaderboard when available")
    lines.append(SEPARATOR)
    return "\n".join(lines)


def main():
    week = target_week()
    history = load_history()
    candidates = [r for r in history if eligible(r, week)]
    if not candidates:
        print(f"No valid snapshot fallback found for {week}.")
        raise SystemExit(2)

    source = max(candidates, key=snapshot_dt)
    record = dict(source)
    record["week_start"] = week
    record["finalization_mode"] = "snapshot_fallback_pending_archive"
    record["archive_upgrade_pending"] = True
    record["fallback_source_snapshot"] = source.get("final_snapshot")

    replaced = False
    for i, existing in enumerate(history):
        if str(existing.get("week_start") or "") == week:
            # Never downgrade an already archived definitive result.
            if str(existing.get("finalization_mode") or "").startswith("historical_"):
                print("Archived definitive result already exists; fallback not needed.")
                return
            history[i] = record
            replaced = True
            break
    if not replaced:
        history.append(record)

    history.sort(key=lambda r: str(r.get("week_start") or ""))
    HISTORY.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    payload = {
        "version": "fallback-1.0",
        "generated_at": datetime.now(SAO_PAULO).isoformat(),
        "week_start": week,
        "complete_leaderboard": False,
        "result": record,
        "benchmarks": {"fixed": {}, "percentiles": {}},
        "archive_upgrade_pending": True,
    }
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUTPUT_REPORT.write_text(build_report(record) + "\n", encoding="utf-8")
    print(f"Fallback finalized {week}: #{record['position']}/{record['total_drivers']} {record.get('laptime')}")


if __name__ == "__main__":
    main()
