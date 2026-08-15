import requests
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from car_database import (
    load_car_database,
    save_car_database,
    extract_car_database_from_html
)


# ============================================================
# CONFIG
# ============================================================

GTSH_URL = "https://gtsh-rank.com/daily/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (GT7 Car Database Updater)"
}

DATA_DIR = Path("data")

REPORT_FILE = (
    DATA_DIR
    / "car_database_update.txt"
)

MAX_ARCHIVE_PAGES = 15

MAX_LEADERBOARDS_TO_SCAN = 30


# ============================================================
# DISCOVER LEADERBOARD URLS
# ============================================================

def discover_leaderboard_urls(session):

    discovered = {}

    print(
        "SEARCHING GTSH-RANK LEADERBOARDS"
    )

    print(
        "=" * 70
    )


    for page in range(
        1,
        MAX_ARCHIVE_PAGES + 1
    ):

        if page == 1:

            page_url = GTSH_URL

        else:

            page_url = (
                f"{GTSH_URL}"
                f"?page={page}&q="
            )


        print(
            f"Reading archive page {page}..."
        )


        response = session.get(
            page_url,
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

            continue


        for link in links:

            href = link.get(
                "href"
            )


            if not href:

                continue


            full_url = urljoin(
                GTSH_URL,
                href
            )


            parent = link.parent


            if parent is not None:

                description = (
                    parent.get_text(
                        " ",
                        strip=True
                    )
                )

            else:

                description = ""


            discovered[
                full_url
            ] = description


            if (
                len(discovered)
                >= MAX_LEADERBOARDS_TO_SCAN
            ):

                break


        if (
            len(discovered)
            >= MAX_LEADERBOARDS_TO_SCAN
        ):

            break


    return [
        {
            "url":
                url,

            "description":
                description
        }

        for url, description
        in discovered.items()
    ]


# ============================================================
# SCAN LEADERBOARDS
# ============================================================

def scan_leaderboards(
    session,
    leaderboards
):

    combined = {}

    scan_results = []


    for index, item in enumerate(
        leaderboards,
        start=1
    ):

        url = item[
            "url"
        ]

        description = item[
            "description"
        ]


        print()

        print(
            f"[{index}/{len(leaderboards)}] "
            f"Opening leaderboard..."
        )


        try:

            response = session.get(
                url,
                timeout=60
            )

            response.raise_for_status()


            html = response.text


            cars = (
                extract_car_database_from_html(
                    html
                )
            )


            marker_present = (
                "carNames"
                in html
            )


            print(
                f"    HTTP: "
                f"{response.status_code}"
            )

            print(
                f"    HTML length: "
                f"{len(html):,}"
            )

            print(
                f"    carNames marker: "
                f"{'YES' if marker_present else 'NO'}"
            )

            print(
                f"    Cars extracted: "
                f"{len(cars)}"
            )


            if cars:

                combined.update(
                    cars
                )


            scan_results.append(
                {
                    "url":
                        url,

                    "description":
                        description,

                    "marker_present":
                        marker_present,

                    "cars_extracted":
                        len(cars),

                    "status":
                        "OK"
                }
            )


        except Exception as error:

            print(
                f"    ERROR: {error}"
            )


            scan_results.append(
                {
                    "url":
                        url,

                    "description":
                        description,

                    "marker_present":
                        False,

                    "cars_extracted":
                        0,

                    "status":
                        f"ERROR: {error}"
                }
            )


    return (
        combined,
        scan_results
    )


# ============================================================
# MERGE DATABASE
# ============================================================

def merge_database(
    discovered
):

    current = load_car_database()

    before_count = len(
        current
    )

    added = 0

    updated = 0


    for car_code, name in (
        discovered.items()
    ):

        previous = current.get(
            car_code
        )


        if previous is None:

            added += 1


        elif previous != name:

            updated += 1


        current[
            car_code
        ] = name


    save_car_database(
        current
    )


    return {
        "database":
            current,

        "before":
            before_count,

        "after":
            len(current),

        "added":
            added,

        "updated":
            updated
    }


# ============================================================
# CHECK KNOWN UNKNOWN CODES
# ============================================================

def check_historical_unknowns(
    database
):

    codes = [
        3311,
        3588,
        3600,
        3238,
        2179,
        3397,
        3607,
        3436,
        3499,
        365,
        3348,
        3405
    ]


    results = []


    for code in codes:

        results.append(
            (
                code,
                database.get(
                    code
                )
            )
        )


    return results


# ============================================================
# MAIN
# ============================================================

def main():

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )


    session = requests.Session()

    session.headers.update(
        HEADERS
    )


    print()

    print(
        "GT7 COMPLETE CAR DATABASE UPDATE"
    )

    print(
        "=" * 70
    )


    # ========================================================
    # DISCOVER PAGES
    # ========================================================

    leaderboards = (
        discover_leaderboard_urls(
            session
        )
    )


    print()

    print(
        f"Leaderboards discovered: "
        f"{len(leaderboards)}"
    )


    if not leaderboards:

        raise RuntimeError(
            "No GTSH-Rank leaderboards were discovered."
        )


    # ========================================================
    # SCAN PAGES
    # ========================================================

    discovered, scan_results = (
        scan_leaderboards(
            session,
            leaderboards
        )
    )


    # ========================================================
    # MERGE
    # ========================================================

    result = merge_database(
        discovered
    )


    database = result[
        "database"
    ]


    # ========================================================
    # REPORT
    # ========================================================

    lines = []


    lines.append(
        "GT7 COMPLETE CAR DATABASE UPDATE"
    )

    lines.append(
        "=" * 70
    )


    lines.append(
        f"Leaderboards scanned       : "
        f"{len(scan_results)}"
    )


    pages_with_marker = sum(
        1
        for item in scan_results
        if item[
            "marker_present"
        ]
    )


    pages_with_cars = sum(
        1
        for item in scan_results
        if item[
            "cars_extracted"
        ] > 0
    )


    lines.append(
        f"Pages with carNames marker : "
        f"{pages_with_marker}"
    )


    lines.append(
        f"Pages yielding car catalog : "
        f"{pages_with_cars}"
    )


    lines.append(
        f"Unique GTSH cars discovered: "
        f"{len(discovered)}"
    )


    lines.append(
        f"Database before update     : "
        f"{result['before']}"
    )


    lines.append(
        f"New car codes added        : "
        f"{result['added']}"
    )


    lines.append(
        f"Existing names updated     : "
        f"{result['updated']}"
    )


    lines.append(
        f"Total cars in database     : "
        f"{result['after']}"
    )


    # ========================================================
    # HISTORICAL UNKNOWN TEST
    # ========================================================

    lines.append("")

    lines.append(
        "HISTORICAL UNKNOWN-CODE CHECK"
    )

    lines.append(
        "-" * 70
    )


    historical_checks = (
        check_historical_unknowns(
            database
        )
    )


    resolved = 0


    for code, name in (
        historical_checks
    ):

        if name:

            resolved += 1

            lines.append(
                f"{code}: {name}"
            )

        else:

            lines.append(
                f"{code}: STILL UNKNOWN"
            )


    lines.append("")

    lines.append(
        f"Historical codes resolved  : "
        f"{resolved}/"
        f"{len(historical_checks)}"
    )


    # ========================================================
    # PAGE DIAGNOSTICS
    # ========================================================

    lines.append("")

    lines.append(
        "PAGE SCAN DIAGNOSTICS"
    )

    lines.append(
        "-" * 70
    )


    for index, item in enumerate(
        scan_results,
        start=1
    ):

        lines.append(
            f"{index:02d}. "
            f"marker="
            f"{'YES' if item['marker_present'] else 'NO'} | "
            f"cars={item['cars_extracted']} | "
            f"{item['status']}"
        )


    lines.append("")

    lines.append(
        f"Database file: "
        f"data/car_names.json"
    )

    lines.append(
        "=" * 70
    )


    report = "\n".join(
        lines
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