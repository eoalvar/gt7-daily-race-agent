from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SNAPSHOT_FILE = Path("data/latest_snapshot.json")
REPORT_FILE = Path("reports/latest.txt")


def fetch_race_c_laps(week_start: str) -> int | None:
    try:
        date_key = datetime.fromisoformat(week_start).date().isoformat()
    except Exception:
        return None

    url = f"https://nopeus-gt.app/news/dr-{date_key}"
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (GT7 Daily Race Agent)"},
            timeout=20,
        )
        response.raise_for_status()
    except Exception as exc:
        print(f"Race laps source unavailable: {exc}")
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    text = soup.get_text("\n", strip=True)

    # Restrict the search to the Race C section so Race A/B lap counts cannot
    # be mistaken for Race C.
    race_c = re.search(
        r"(?:^|\n)Race C(?:\n|\s)(.*?)(?=(?:\nRace [AB](?:\n|\s))|\Z)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    section = race_c.group(1) if race_c else text

    match = re.search(r"\bLaps?\s*:\s*(\d+)\b", section, flags=re.IGNORECASE)
    if not match:
        print(f"Race C lap count not found in {url}")
        return None

    laps = int(match.group(1))
    if not 1 <= laps <= 100:
        return None
    print(f"Race C laps: {laps} (source: {url})")
    return laps


def insert_laps_line(report: str, laps: int) -> str:
    if re.search(r"^Laps\s*:\s*\d+\s*$", report, flags=re.MULTILINE):
        return re.sub(
            r"^Laps\s*:\s*\d+\s*$",
            f"Laps: {laps}",
            report,
            count=1,
            flags=re.MULTILINE,
        )

    lines = report.splitlines()

    # Insert in the compact race-summary header, immediately after the track.
    race_idx = next(
        (
            i
            for i, line in enumerate(lines)
            if line.startswith("C ") and line.rstrip().endswith("Daily Race C")
        ),
        None,
    )
    if race_idx is not None and race_idx + 1 < len(lines):
        lines.insert(race_idx + 2, f"Laps: {laps}")
        return "\n".join(lines) + ("\n" if report.endswith("\n") else "")

    return report


def main():
    if not SNAPSHOT_FILE.exists() or not REPORT_FILE.exists():
        print("Race laps enrichment skipped: snapshot/report unavailable")
        return

    try:
        snapshot = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Race laps enrichment skipped: invalid snapshot ({exc})")
        return

    race = snapshot.get("race") if isinstance(snapshot, dict) else None
    if not isinstance(race, dict):
        print("Race laps enrichment skipped: race block unavailable")
        return

    week_start = race.get("start_date")
    if not isinstance(week_start, str) or not week_start:
        print("Race laps enrichment skipped: start_date unavailable")
        return

    laps = fetch_race_c_laps(week_start)
    if laps is None:
        # This information is supplemental. A source outage must never block
        # the Daily Race C report or its email.
        return

    race["laps"] = laps
    SNAPSHOT_FILE.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    report = REPORT_FILE.read_text(encoding="utf-8")
    updated = insert_laps_line(report, laps)
    REPORT_FILE.write_text(updated, encoding="utf-8")
    print("Race lap count added to Daily Race C header.")


if __name__ == "__main__":
    main()
