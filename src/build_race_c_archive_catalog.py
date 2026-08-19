import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

GTSH_URL = "https://gtsh-rank.com/daily/"
OUT_FILE = Path("data/race_c_archive_catalog.json")
REPORT_FILE = Path("reports/race_c_archive_catalog.txt")
MAX_ARCHIVE_PAGES = 400
REQUEST_DELAY_SECONDS = 0.08
GT7_LAUNCH = datetime(2022, 3, 4)
HEADERS = {"User-Agent": "Mozilla/5.0 (GT7 Race C Archive Catalog)"}


def parse_date(text):
    match = re.search(r"(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})", text or "")
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%d %b %Y")
    except ValueError:
        return None


def normalize_space(text):
    return re.sub(r"\s+", " ", text or "").strip()


def local_race_text(link):
    # Prefer the smallest ancestor that contains the Race C label and the link.
    node = link
    best = ""
    for _ in range(7):
        node = getattr(node, "parent", None)
        if node is None:
            break
        text = normalize_space(node.get_text(" ", strip=True))
        if "Daily Race C" in text:
            best = text
            # Stop before a container grows into a full A/B/C page block.
            if "Daily Race A" not in text and "Daily Race B" not in text:
                return text
    return best or normalize_space(link.get_text(" ", strip=True))


def main():
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(HEADERS)
    events = {}
    pages_read = 0
    oldest_seen = None

    print("GT7 DAILY RACE C - FULL ARCHIVE CATALOG")
    print("=" * 90)

    for page in range(1, MAX_ARCHIVE_PAGES + 1):
        url = GTSH_URL if page == 1 else f"{GTSH_URL}?page={page}&q="
        response = session.get(url, timeout=45)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        links = soup.select(
            'a[href*="/daily/leaderboard?event="], '
            'a[href*="/daily/leaderboard/?event="]'
        )
        if not links:
            break

        page_dates = []
        page_added = 0
        for link in links:
            text = local_race_text(link)
            if "Daily Race C" not in text:
                continue
            race_date = parse_date(text)
            if race_date is None:
                continue
            page_dates.append(race_date)
            if race_date < GT7_LAUNCH:
                continue
            href = link.get("href")
            if not href:
                continue
            full_url = urljoin(GTSH_URL, href)
            if full_url not in events:
                page_added += 1
            events[full_url] = {
                "week_start": race_date.date().isoformat(),
                "date": race_date.date().isoformat(),
                "race_description": text,
                "leaderboard_url": full_url,
                "source": "GTSH_RANK_ARCHIVE",
            }

        pages_read = page
        if page_dates:
            page_oldest = min(page_dates)
            oldest_seen = page_oldest if oldest_seen is None else min(oldest_seen, page_oldest)

        if page <= 5 or page % 10 == 0:
            print(f"Page {page:>3}: +{page_added:>3} Race C events | total {len(events):>4}")

        if page_dates and min(page_dates) < GT7_LAUNCH:
            break
        time.sleep(REQUEST_DELAY_SECONDS)

    catalog = sorted(events.values(), key=lambda x: (x["week_start"], x["leaderboard_url"]))
    OUT_FILE.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "GT7 DAILY RACE C - FULL ARCHIVE CATALOG",
        "=" * 90,
        f"Generated       : {datetime.now().astimezone().isoformat()}",
        f"Pages read      : {pages_read}",
        f"Race C events   : {len(catalog)}",
        f"Oldest seen     : {oldest_seen.date().isoformat() if oldest_seen else 'N/A'}",
        f"Saved catalog   : {OUT_FILE}",
        "",
        "This stage only catalogs event metadata and leaderboard URLs.",
        "It does NOT download full historical leaderboards.",
        "=" * 90,
    ]
    REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
