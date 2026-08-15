import requests
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from car_database import (
    update_car_database_from_html,
    database_stats
)


# ============================================================
# CONFIG
# ============================================================

GTSH_URL = "https://gtsh-rank.com/daily/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (GT7 Car Database Updater)"
}

REPORT_FILE = Path("data/car_database_update.txt")


# ============================================================
# FIND ANY CURRENT LEADERBOARD
# ============================================================

def find_leaderboard_url(session):

    response = session.get(
        GTSH_URL,
        timeout=30
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    links = soup.select(
        'a[href*="/daily/leaderboard?event="], '
        'a[href*="/daily/leaderboard/?event="]'
    )

    if not links:
        raise RuntimeError(
            "No leaderboard URL found on GTSH-Rank."
        )

    return urljoin(
        GTSH_URL,
        links[0].get("href")
    )


# ============================================================
# MAIN
# ============================================================

def main():

    session = requests.Session()

    session.headers.update(
        HEADERS
    )

    print(
        "GT7 CAR DATABASE UPDATE"
    )

    print(
        "=" * 70
    )

    leaderboard_url = find_leaderboard_url(
        session
    )

    print(
        f"Leaderboard: {leaderboard_url}"
    )

    response = session.get(
        leaderboard_url,
        timeout=60
    )

    response.raise_for_status()

    html = response.text

    result = update_car_database_from_html(
        html
    )

    stats = database_stats()

    lines = []

    lines.append(
        "GT7 CAR DATABASE UPDATE"
    )

    lines.append(
        "=" * 70
    )

    lines.append(
        f"Discovered in GTSH page : "
        f"{result['discovered']}"
    )

    lines.append(
        f"New car codes added     : "
        f"{result['added']}"
    )

    lines.append(
        f"Existing codes updated  : "
        f"{result['updated']}"
    )

    lines.append(
        f"Total cars in database  : "
        f"{stats['cars']}"
    )

    lines.append(
        f"Database file           : "
        f"{stats['file']}"
    )

    lines.append(
        "=" * 70
    )

    report = "\n".join(
        lines
    )

    REPORT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    REPORT_FILE.write_text(
        report,
        encoding="utf-8"
    )

    print()
    print(
        report
    )


if __name__ == "__main__":
    main()