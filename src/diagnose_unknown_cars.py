import json
import requests
from pathlib import Path
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from car_database import (
    load_car_database,
    update_car_database_from_html
)


# ============================================================
# CONFIG
# ============================================================

GTSH_URL = "https://gtsh-rank.com/daily/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (GT7 Unknown Car Diagnostic)"
}

DATA_DIR = Path("data")

REPORT_FILE = (
    DATA_DIR
    / "unknown_car_diagnostic.txt"
)

JSON_FILE = (
    DATA_DIR
    / "unknown_car_diagnostic.json"
)

SAO_PAULO = ZoneInfo(
    "America/Sao_Paulo"
)


# ============================================================
# HELPERS
# ============================================================

def get_user(driver):

    return driver.get(
        "user",
        {}
    )


def get_car_code(driver):

    return (
        driver
        .get(
            "ranking_stats",
            {}
        )
        .get(
            "car_code"
        )
    )


def find_current_race_c(
    soup
):

    candidates = []


    for link in soup.select(
        'a[href*="/daily/leaderboard?event="], '
        'a[href*="/daily/leaderboard/?event="]'
    ):

        parent = link.parent

        if parent is None:
            continue


        text = parent.get_text(
            " ",
            strip=True
        )


        if (
            "Daily Race C"
            not in text
        ):
            continue


        href = link.get(
            "href"
        )


        if not href:
            continue


        candidates.append(
            {
                "url":
                    urljoin(
                        GTSH_URL,
                        href
                    ),

                "text":
                    text,

                "running":
                    "Running"
                    in text
            }
        )


    running = [
        item
        for item in candidates
        if item[
            "running"
        ]
    ]


    if running:

        return running[
            0
        ]


    if candidates:

        return candidates[
            0
        ]


    raise RuntimeError(
        "Daily Race C not found."
    )


def extract_initial_ranking(
    html
):

    marker = (
        "const initialRanking = "
    )


    start = html.find(
        marker
    )


    if start == -1:

        return None


    start += len(
        marker
    )


    try:

        decoder = (
            json.JSONDecoder()
        )


        ranking, _ = (
            decoder.raw_decode(
                html[
                    start:
                ].lstrip()
            )
        )


        if isinstance(
            ranking,
            list
        ):

            return ranking


    except Exception:

        pass


    return None


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


    # ========================================================
    # FIND CURRENT RACE C
    # ========================================================

    response = session.get(
        GTSH_URL,
        timeout=30
    )


    response.raise_for_status()


    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )


    race = find_current_race_c(
        soup
    )


    # ========================================================
    # GET LEADERBOARD
    # ========================================================

    leaderboard_response = (
        session.get(
            race[
                "url"
            ],
            timeout=60
        )
    )


    leaderboard_response.raise_for_status()


    html = (
        leaderboard_response.text
    )


    # ========================================================
    # UPDATE CAR DATABASE FIRST
    # ========================================================

    try:

        update_result = (
            update_car_database_from_html(
                html
            )
        )


        database = (
            update_result[
                "database"
            ]
        )


    except Exception:

        update_result = {
            "discovered":
                0,

            "added":
                0,

            "updated":
                0
        }


        database = (
            load_car_database()
        )


    # ========================================================
    # RANKING
    # ========================================================

    ranking = extract_initial_ranking(
        html
    )


    if not ranking:

        update_url = (
            race[
                "url"
            ]
            + (
                "&update=1"
                if "?"
                in race[
                    "url"
                ]
                else "?update=1"
            )
        )


        update_response = (
            session.get(
                update_url,
                timeout=60
            )
        )


        update_response.raise_for_status()


        data = (
            update_response.json()
        )


        if isinstance(
            data,
            list
        ):

            ranking = data


        elif isinstance(
            data,
            dict
        ):

            ranking = (
                data.get(
                    "board"
                )
                or data.get(
                    "ranking"
                )
            )


    if not isinstance(
        ranking,
        list
    ):

        raise RuntimeError(
            "Could not retrieve leaderboard."
        )


    # ========================================================
    # DIAGNOSTIC
    # ========================================================

    total_entries = len(
        ranking
    )


    with_code = 0

    without_code = 0

    recognized = 0

    unknown_codes = Counter()

    missing_code_examples = []

    unknown_examples = {}


    for driver in ranking:

        car_code = get_car_code(
            driver
        )


        # ----------------------------------------------------
        # No car_code at all
        # ----------------------------------------------------

        if car_code is None:

            without_code += 1


            if (
                len(
                    missing_code_examples
                )
                < 20
            ):

                user = get_user(
                    driver
                )


                missing_code_examples.append(
                    {
                        "rank":
                            driver.get(
                                "display_rank"
                            ),

                        "score":
                            driver.get(
                                "score"
                            ),

                        "psn":
                            user.get(
                                "np_online_id"
                            ),

                        "country":
                            user.get(
                                "country_code"
                            ),

                        "ranking_stats":
                            driver.get(
                                "ranking_stats"
                            )
                    }
                )


            continue


        with_code += 1


        # ----------------------------------------------------
        # Recognized car
        # ----------------------------------------------------

        if car_code in database:

            recognized += 1

            continue


        # ----------------------------------------------------
        # Unknown numeric code
        # ----------------------------------------------------

        unknown_codes[
            car_code
        ] += 1


        if (
            car_code
            not in unknown_examples
        ):

            user = get_user(
                driver
            )


            unknown_examples[
                car_code
            ] = {
                "rank":
                    driver.get(
                        "display_rank"
                    ),

                "score":
                    driver.get(
                        "score"
                    ),

                "psn":
                    user.get(
                        "np_online_id"
                    ),

                "country":
                    user.get(
                        "country_code"
                    )
            }


    unknown_code_entries = sum(
        unknown_codes.values()
    )


    fully_recognized_share = (
        recognized
        / total_entries
        * 100
        if total_entries
        else 0
    )


    missing_code_share = (
        without_code
        / total_entries
        * 100
        if total_entries
        else 0
    )


    unknown_code_share = (
        unknown_code_entries
        / total_entries
        * 100
        if total_entries
        else 0
    )


    # ========================================================
    # STRUCTURED RESULT
    # ========================================================

    result = {

        "generated_at":
            datetime.now(
                SAO_PAULO
            ).isoformat(),

        "race":
            race,

        "database": {

            "known_codes":
                len(
                    database
                ),

            "gtsh_discovered_this_run":
                update_result.get(
                    "discovered",
                    0
                ),

            "gtsh_added_this_run":
                update_result.get(
                    "added",
                    0
                ),

            "gtsh_updated_this_run":
                update_result.get(
                    "updated",
                    0
                )
        },

        "leaderboard": {

            "total_entries":
                total_entries,

            "entries_with_car_code":
                with_code,

            "entries_without_car_code":
                without_code,

            "recognized_entries":
                recognized,

            "unknown_code_entries":
                unknown_code_entries,

            "recognized_share":
                fully_recognized_share,

            "missing_code_share":
                missing_code_share,

            "unknown_code_share":
                unknown_code_share
        },

        "unknown_codes": [

            {
                "car_code":
                    code,

                "count":
                    count,

                "example":
                    unknown_examples.get(
                        code
                    )
            }

            for code, count
            in unknown_codes.most_common()

        ],

        "missing_code_examples":
            missing_code_examples
    }


    JSON_FILE.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


    # ========================================================
    # TEXT REPORT
    # ========================================================

    lines = []


    lines.append(
        "GT7 UNKNOWN CAR DIAGNOSTIC"
    )

    lines.append(
        "=" * 78
    )


    lines.append(
        f"Race                  : "
        f"{race['text']}"
    )


    lines.append(
        f"Database known cars   : "
        f"{len(database):,}"
    )


    lines.append(
        f"Leaderboard entries   : "
        f"{total_entries:,}"
    )


    lines.append(
        f"Entries with car_code : "
        f"{with_code:,}"
    )


    lines.append(
        f"Entries without code  : "
        f"{without_code:,} "
        f"({missing_code_share:.4f}%)"
    )


    lines.append(
        f"Recognized entries    : "
        f"{recognized:,} "
        f"({fully_recognized_share:.4f}%)"
    )


    lines.append(
        f"Unknown-code entries  : "
        f"{unknown_code_entries:,} "
        f"({unknown_code_share:.4f}%)"
    )


    lines.append(
        f"Unknown numeric codes : "
        f"{len(unknown_codes)}"
    )


    # ========================================================
    # UNKNOWN CODES
    # ========================================================

    lines.append("")

    lines.append(
        "UNKNOWN NUMERIC CAR CODES"
    )

    lines.append(
        "-" * 78
    )


    if unknown_codes:

        for (
            code,
            count
        ) in unknown_codes.most_common():

            example = (
                unknown_examples.get(
                    code,
                    {}
                )
            )


            lines.append(
                f"Code {code} | "
                f"{count} entries | "
                f"example rank #{example.get('rank')} | "
                f"PSN {example.get('psn')}"
            )


    else:

        lines.append(
            "None."
        )


    # ========================================================
    # MISSING CODES
    # ========================================================

    lines.append("")

    lines.append(
        "ENTRIES WITHOUT car_code"
    )

    lines.append(
        "-" * 78
    )


    if missing_code_examples:

        for item in missing_code_examples:

            lines.append(
                f"Rank #{item.get('rank')} | "
                f"PSN {item.get('psn')} | "
                f"Country {item.get('country')} | "
                f"Score {item.get('score')} | "
                f"ranking_stats={item.get('ranking_stats')}"
            )


    else:

        lines.append(
            "None."
        )


    # ========================================================
    # CONCLUSION
    # ========================================================

    lines.append("")

    lines.append(
        "CONCLUSION"
    )

    lines.append(
        "-" * 78
    )


    if (
        unknown_code_entries == 0
        and without_code == 0
    ):

        lines.append(
            "100% of leaderboard entries have a recognized car code."
        )


    elif (
        unknown_code_entries == 0
        and without_code > 0
    ):

        lines.append(
            "All numeric car codes are recognized. "
            "The mapping gap is entirely caused by leaderboard "
            "entries where GTSH provides no car_code."
        )


    elif unknown_code_entries > 0:

        lines.append(
            "At least one numeric car code is not present in "
            "the current central database. These codes should "
            "be treated as possible new/unmapped cars."
        )


    lines.append("")

    lines.append(
        "=" * 78
    )


    report = "\n".join(
        lines
    )


    REPORT_FILE.write_text(
        report,
        encoding="utf-8"
    )


    print(
        report
    )


if __name__ == "__main__":

    main()