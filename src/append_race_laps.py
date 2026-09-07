from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SNAPSHOT_FILE = Path("data/latest_snapshot.json")
REPORT_FILE = Path("reports/latest.txt")
CURRENT_WEEK_MARKER = "NEW WEEK - CURRENT DAILY RACE C"
HEADERS = {"User-Agent": "Mozilla/5.0 (GT7 Daily Race Agent)"}


def _fetch_text(url: str) -> str | None:
    try:
        response = requests.get(url, headers=HEADERS, timeout=20)
        response.raise_for_status()
    except Exception as exc:
        print(f"Race laps source unavailable ({url}): {exc}")
        return None
    return BeautifulSoup(response.text, "html.parser").get_text("\n", strip=True)


def _race_c_section(text: str) -> str:
    match = re.search(
        r"(?:^|\n)(?:Daily\s+)?Race C(?:\s*:?[^\n]*)?(?:\n|\s)(.*?)(?=(?:\n(?:Daily\s+)?Race [AB](?:\s*:?[^\n]*)?(?:\n|\s))|\Z)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return match.group(1) if match else text


def _extract_laps(text: str) -> int | None:
    section = _race_c_section(text)
    patterns = (
        r"\bLaps?\s*:\s*(\d+)\b",
        r"\b(\d+)\s*(?:-|\s)lap(?:s)?\b",
        r"\bRM\s+RS\s+(\d+)\s+x\d+\s+x\d+\b",
    )
    for pattern in patterns:
        match = re.search(pattern, section, flags=re.IGNORECASE)
        if match:
            laps = int(match.group(1))
            if 1 <= laps <= 100:
                return laps
    return None


def fetch_race_c_laps(week_start: str) -> int | None:
    try:
        date_key = datetime.fromisoformat(week_start).date()
    except Exception:
        return None

    # Nopeus has historically been our primary source, but its weekly Daily
    # Race article is sometimes published late. Lights to Flag uses a stable
    # date-based URL and provides the same Race C lap-count field, so use it as
    # an independent fallback instead of silently omitting Laps from the email.
    sources = [
        f"https://nopeus-gt.app/news/dr-{date_key.isoformat()}",
        f"https://lights-to-flag.com/gt7-daily-races-{date_key.strftime('%Y%m%d')}/",
    ]

    for url in sources:
        text = _fetch_text(url)
        if not text:
            continue
        laps = _extract_laps(text)
        if laps is not None:
            print(f"Race C laps: {laps} (source: {url})")
            return laps
        print(f"Race C lap count not found in {url}")

    return None


def _insert_into_single_report(report: str, laps: int) -> str:
    # Replace an existing value in this section only.
    if re.search(r"^Laps\s*:\s*\d+\s*$", report, flags=re.MULTILINE):
        return re.sub(
            r"^Laps\s*:\s*\d+\s*$",
            f"Laps: {laps}",
            report,
            count=1,
            flags=re.MULTILINE,
        )

    lines = report.splitlines()

    # Current compact format is:
    # C Gr.x Running Daily Race C
    # Track name
    # Current WR: ...
    race_idx = next(
        (
            i
            for i, line in enumerate(lines)
            if line.startswith("C ") and "Daily Race C" in line
        ),
        None,
    )
    if race_idx is not None:
        insert_at = min(race_idx + 2, len(lines))
        lines.insert(insert_at, f"Laps: {laps}")
        return "\n".join(lines) + ("\n" if report.endswith("\n") else "")

    # Defensive fallback: put Laps immediately before Current WR if the header
    # wording changes but the rest of the compact layout remains recognizable.
    wr_idx = next((i for i, line in enumerate(lines) if line.startswith("Current WR:")), None)
    if wr_idx is not None:
        lines.insert(wr_idx, f"Laps: {laps}")
        return "\n".join(lines) + ("\n" if report.endswith("\n") else "")

    print("Race lap count found, but current report header was not recognized.")
    return report


def insert_laps_line(report: str, laps: int) -> str:
    # Monday emails contain LAST WEEK followed by CURRENT WEEK. Never touch the
    # previous-week block; enrich only the current Daily Race C section.
    if CURRENT_WEEK_MARKER in report:
        previous, current = report.split(CURRENT_WEEK_MARKER, 1)
        updated_current = _insert_into_single_report(current, laps)
        return previous + CURRENT_WEEK_MARKER + updated_current
    return _insert_into_single_report(report, laps)


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
        print("Race laps enrichment skipped: no source returned a valid Race C lap count")
        return

    race["laps"] = laps
    SNAPSHOT_FILE.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    report = REPORT_FILE.read_text(encoding="utf-8")
    updated = insert_laps_line(report, laps)
    REPORT_FILE.write_text(updated, encoding="utf-8")
    print("Race lap count added to current Daily Race C header.")


if __name__ == "__main__":
    main()
