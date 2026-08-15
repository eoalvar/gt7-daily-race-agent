import requests
import json
import math
import re
import time
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse


# ============================================================
# CONFIG
# ============================================================

GTSH_URL = "https://gtsh-rank.com/daily/"
MY_PSN_ID = "crazy_rooster74"

BACKFILL_WEEKS = 26
MAX_ARCHIVE_PAGES = 30

PAGE_SIZE = 100
MAX_LEADERBOARD_PAGES = 1000

REQUEST_DELAY_SECONDS = 0.20

HEADERS = {
    "User-Agent": "Mozilla/5.0 (GT7 Daily Race History Backfill)",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8"
}

DATA_DIR = Path("data")

WEEKLY_HISTORY_FILE = (
    DATA_DIR
    / "weekly_rating_history.json"
)

BACKFILL_LOG_FILE = (
    DATA_DIR
    / "backfill_history_log.txt"
)

SAO_PAULO = ZoneInfo(
    "America/Sao_Paulo"
)


# ============================================================
# CAR DATABASE
# ============================================================

CAR_NAMES = {
    1563: "Renault Mégane Trophy '11",
    2157: "Aston Martin V8 Vantage Gr.4",
    2161: "Nissan GT-R Gr.4",
    2163: "Genesis Gr.4",
    2164: "Ford Mustang Gr.4",
    2166: "Alfa Romeo 4C Gr.4",
    3192: "Mercedes-Benz SLS AMG Gr.4",
    3231: "Volkswagen Scirocco Gr.4",
    3245: "BMW M4 Gr.4",
    3246: "Bugatti Veyron Gr.4",
    3247: "Chevrolet Corvette C7 Gr.4",
    3248: "GT by Citroën Gr.4",
    3249: "Dodge Viper Gr.4",
    3251: "Honda NSX Gr.4",
    3252: "Jaguar F-type Gr.4",
    3253: "Lamborghini Huracán Gr.4",
    3254: "Lexus RC F Gr.4",
    3256: "Mazda Atenza Gr.4",
    3257: "McLaren 650S Gr.4",
    3258: "Mitsubishi Lancer Evolution Final Gr.4",
    3259: "Peugeot RCZ Gr.4",
    3260: "Renault Mégane Gr.4",
    3261: "Subaru WRX Gr.4",
    3262: "Toyota 86 Gr.4",
    3263: "Ferrari 458 Italia Gr.4",
    3298: "Audi TT Cup '16",
    3310: "Porsche Cayman GT4 Clubsport '16",
    3399: "Toyota GR Supra Race Car '19",
    3477: "Nissan Silvia spec-R Aero (S15) Touring Car",
    3480: "Suzuki Swift Sport Gr.4",
    3501: "Genesis G70 GR4",
    3537: "Mazda3 Gr.4",

    # Known from archived Gr.3 test
    3352: "Toyota GR Supra Racing Concept '18"
}


# ============================================================
# BASIC HELPERS
# ============================================================

def score_to_laptime(score):

    if score is None:
        return "N/A"

    score = int(
        round(score)
    )

    minutes = (
        score
        // 60000
    )

    seconds = (
        score
        % 60000
    ) // 1000

    milliseconds = (
        score
        % 1000
    )

    return (
        f"{minutes}:"
        f"{seconds:02d}."
        f"{milliseconds:03d}"
    )


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


def get_car_name(car_code):

    return CAR_NAMES.get(
        car_code,
        f"Unknown car ({car_code})"
    )


def online_id(driver):

    value = (
        get_user(driver)
        .get(
            "np_online_id",
            ""
        )
    )

    if not isinstance(
        value,
        str
    ):
        return ""

    return (
        value
        .strip()
        .lower()
    )


def find_my_driver(
    ranking,
    psn_id
):

    target = (
        psn_id
        .strip()
        .lower()
    )

    for driver in ranking:

        if (
            online_id(driver)
            == target
        ):

            return driver

    return None


# ============================================================
# RATING FORMULAS
# ============================================================

def general_rating(
    rank,
    total
):

    if (
        rank is None
        or total is None
        or total <= 1
    ):

        return None

    result = 10 * (
        1
        - (
            (rank - 1)
            / (total - 1)
        )
    )

    return max(
        0.0,
        min(
            10.0,
            result
        )
    )


def elite_rating(
    rank,
    total
):

    if (
        rank is None
        or total is None
        or total <= 1
        or rank < 1
    ):

        return None

    if rank == 1:
        return 10.0

    result = 10 * (
        1
        - math.log(rank)
        / math.log(total)
    )

    return max(
        0.0,
        min(
            10.0,
            result
        )
    )


def composite_rating(
    general,
    elite
):

    if (
        general is None
        or elite is None
    ):

        return None

    return (
        general * 0.60
        + elite * 0.40
    )


def percentile_ahead(
    rank,
    total
):

    if (
        rank is None
        or total is None
        or total <= 1
    ):

        return None

    return (
        (
            total
            - rank
        )
        / (
            total
            - 1
        )
        * 100
    )


# ============================================================
# DATE HELPERS
# ============================================================

def parse_date_from_text(
    text
):

    match = re.search(
        r"(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})",
        text
    )

    if not match:
        return None

    try:

        parsed = datetime.strptime(
            match.group(1),
            "%d %b %Y"
        )

        return parsed.replace(
            tzinfo=SAO_PAULO
        )

    except ValueError:

        return None


def monday_of_week(
    value
):

    monday = (
        value
        - timedelta(
            days=value.weekday()
        )
    )

    return monday.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )


# ============================================================
# EXISTING HISTORY
# ============================================================

def load_existing_history():

    if not WEEKLY_HISTORY_FILE.exists():
        return []

    try:

        data = json.loads(
            WEEKLY_HISTORY_FILE.read_text(
                encoding="utf-8"
            )
        )

        if isinstance(
            data,
            list
        ):

            return data

    except Exception:
        pass

    return []


def save_history(
    history
):

    history.sort(
        key=lambda item:
            item.get(
                "week_start",
                ""
            )
    )

    WEEKLY_HISTORY_FILE.write_text(
        json.dumps(
            history,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


def upsert_record(
    history,
    record
):

    url = record.get(
        "leaderboard_url"
    )

    for index, existing in enumerate(
        history
    ):

        if (
            existing.get(
                "leaderboard_url"
            )
            == url
        ):

            history[
                index
            ] = record

            return

    history.append(
        record
    )


# ============================================================
# ARCHIVE DISCOVERY
# ============================================================

def discover_race_c_events(
    session,
    cutoff_date,
    current_week
):

    events = {}

    reached_cutoff = False

    print()
    print(
        "SEARCHING GTSH-RANK ARCHIVE"
    )
    print(
        "=" * 78
    )

    for page in range(
        1,
        MAX_ARCHIVE_PAGES + 1
    ):

        page_url = (
            GTSH_URL
            if page == 1
            else (
                f"{GTSH_URL}"
                f"?page={page}&q="
            )
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

        page_dates = []

        leaderboard_links = soup.select(
            'a[href*="/daily/leaderboard?event="]'
        )

        if not leaderboard_links:

            print(
                "No leaderboard links found. "
                "Stopping archive search."
            )

            break

        for link in leaderboard_links:

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

            race_date = parse_date_from_text(
                text
            )

            if race_date is None:
                continue

            page_dates.append(
                race_date
            )

            if race_date > current_week:
                continue

            if race_date < cutoff_date:
                continue

            href = link.get(
                "href"
            )

            if not href:
                continue

            full_url = urljoin(
                GTSH_URL,
                href
            )

            events[
                full_url
            ] = {
                "date":
                    race_date,

                "text":
                    text,

                "url":
                    full_url
            }

        if page_dates:

            oldest_on_page = min(
                page_dates
            )

            if (
                oldest_on_page
                < cutoff_date
                - timedelta(
                    days=14
                )
            ):

                reached_cutoff = True

        if reached_cutoff:

            print(
                "Six-month cutoff reached."
            )

            break

        time.sleep(
            REQUEST_DELAY_SECONDS
        )

    result = list(
        events.values()
    )

    result.sort(
        key=lambda event:
            event[
                "date"
            ]
    )

    return result


# ============================================================
# SERVER PAGINATION HELPERS
# ============================================================

def add_query_params(
    url,
    **params
):

    parsed = urlparse(
        url
    )

    current = parse_qs(
        parsed.query,
        keep_blank_values=True
    )

    for key, value in params.items():

        current[
            key
        ] = [
            str(value)
        ]

    new_query = urlencode(
        current,
        doseq=True
    )

    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment
        )
    )


def extract_json_variable(
    html,
    variable_name
):

    patterns = [
        f"const {variable_name} = ",
        f"let {variable_name} = ",
        f"var {variable_name} = "
    ]

    for marker in patterns:

        start = html.find(
            marker
        )

        if start == -1:
            continue

        start += len(
            marker
        )

        try:

            decoder = (
                json.JSONDecoder()
            )

            data, _ = (
                decoder.raw_decode(
                    html[
                        start:
                    ]
                    .lstrip()
                )
            )

            return data

        except Exception:

            continue

    return None


def extract_initial_server_page(
    html
):

    data = extract_json_variable(
        html,
        "initialServerPage"
    )

    if isinstance(
        data,
        dict
    ):

        return data

    return None


def extract_initial_ranking(
    html
):

    data = extract_json_variable(
        html,
        "initialRanking"
    )

    if isinstance(
        data,
        list
    ):

        return data

    return None


def normalize_page_response(
    data
):

    if not isinstance(
        data,
        dict
    ):

        return None

    board = data.get(
        "board"
    )

    if not isinstance(
        board,
        list
    ):

        return None

    offset = data.get(
        "offset",
        0
    )

    limit = data.get(
        "limit",
        PAGE_SIZE
    )

    total = (
        data.get(
            "total"
        )
        or data.get(
            "total_records"
        )
        or data.get(
            "totalRecords"
        )
        or data.get(
            "count"
        )
    )

    try:
        offset = int(
            offset
        )
    except Exception:
        offset = 0

    try:
        limit = int(
            limit
        )
    except Exception:
        limit = PAGE_SIZE

    try:
        total = (
            int(total)
            if total is not None
            else None
        )
    except Exception:
        total = None

    return {
        "board":
            board,

        "offset":
            offset,

        "limit":
            limit,

        "total":
            total,

        "raw":
            data
    }


def fetch_server_page(
    session,
    event_url,
    offset,
    limit=PAGE_SIZE
):

    page_url = add_query_params(
        event_url,
        offset=offset,
        limit=limit
    )

    headers = {
        **HEADERS,
        "Accept": "application/json"
    }

    response = session.get(
        page_url,
        headers=headers,
        timeout=60
    )

    response.raise_for_status()

    content_type = (
        response.headers.get(
            "content-type",
            ""
        )
        .lower()
    )

    # Primary mode:
    # the server returns JSON for offset/limit requests.

    if (
        "application/json"
        in content_type
    ):

        return normalize_page_response(
            response.json()
        )

    # Fallback:
    # if it returned HTML, try initialServerPage.

    html = response.text

    server_page = extract_initial_server_page(
        html
    )

    normalized = normalize_page_response(
        server_page
    )

    if normalized:

        return normalized

    return None


# ============================================================
# FULL HISTORICAL LEADERBOARD
# ============================================================

def get_full_event_ranking(
    session,
    event_url
):

    response = session.get(
        event_url,
        timeout=60
    )

    response.raise_for_status()

    html = response.text

    server_page = extract_initial_server_page(
        html
    )

    normalized = normalize_page_response(
        server_page
    )


    # --------------------------------------------------------
    # Modern archived board:
    # server-paged mode
    # --------------------------------------------------------

    if normalized:

        all_drivers = []

        seen_ids = set()

        offset = normalized[
            "offset"
        ]

        total_records = normalized[
            "total"
        ]

        current_page = normalized


        for _ in range(
            MAX_LEADERBOARD_PAGES
        ):

            board = current_page[
                "board"
            ]

            if not board:
                break


            new_items = 0


            for driver in board:

                unique_key = (
                    driver.get(
                        "line_replay_id"
                    )
                    or (
                        online_id(driver),
                        driver.get(
                            "score"
                        ),
                        driver.get(
                            "display_rank"
                        )
                    )
                )


                if unique_key in seen_ids:
                    continue


                seen_ids.add(
                    unique_key
                )

                all_drivers.append(
                    driver
                )

                new_items += 1


            if new_items == 0:
                break


            page_offset = current_page[
                "offset"
            ]

            page_limit = (
                current_page[
                    "limit"
                ]
                or PAGE_SIZE
            )


            next_offset = (
                page_offset
                + page_limit
            )


            # If the server told us total count,
            # stop exactly at the end.

            if (
                total_records is not None
                and next_offset
                >= total_records
            ):
                break


            # A short page is normally the last page.

            if len(
                board
            ) < page_limit:

                break


            time.sleep(
                REQUEST_DELAY_SECONDS
            )


            current_page = fetch_server_page(
                session,
                event_url,
                next_offset,
                PAGE_SIZE
            )


            if not current_page:
                break


            if (
                total_records is None
                and current_page[
                    "total"
                ] is not None
            ):

                total_records = (
                    current_page[
                        "total"
                    ]
                )


        all_drivers.sort(
            key=lambda driver:
                driver.get(
                    "display_rank",
                    999999999
                )
        )


        return {
            "ranking":
                all_drivers,

            "total_records":
                (
                    total_records
                    if total_records is not None
                    else len(
                        all_drivers
                    )
                ),

            "mode":
                "server_paged"
        }


    # --------------------------------------------------------
    # Legacy / current board:
    # entire initialRanking is embedded
    # --------------------------------------------------------

    ranking = extract_initial_ranking(
        html
    )


    if ranking:

        ranking.sort(
            key=lambda driver:
                driver.get(
                    "display_rank",
                    999999999
                )
        )


        return {
            "ranking":
                ranking,

            "total_records":
                len(
                    ranking
                ),

            "mode":
                "full_initialRanking"
        }


    raise RuntimeError(
        "Could not extract leaderboard data."
    )


# ============================================================
# HISTORICAL RECORD
# ============================================================

def build_record(
    event,
    ranking,
    total_records,
    extraction_mode
):

    if not ranking:
        return None


    # WR is always rank 1.

    winner = min(
        ranking,
        key=lambda driver:
            driver.get(
                "display_rank",
                999999999
            )
    )


    wr_score = winner.get(
        "score"
    )


    if not wr_score:
        return None


    my_driver = find_my_driver(
        ranking,
        MY_PSN_ID
    )


    if not my_driver:

        return {
            "participated":
                False,

            "week_start":
                event[
                    "date"
                ]
                .date()
                .isoformat(),

            "race":
                event[
                    "text"
                ],

            "leaderboard_url":
                event[
                    "url"
                ],

            "total_drivers":
                total_records,

            "extraction_mode":
                extraction_mode
        }


    my_score = my_driver.get(
        "score"
    )

    my_rank = my_driver.get(
        "display_rank"
    )

    my_user = get_user(
        my_driver
    )

    my_car_code = get_car_code(
        my_driver
    )


    general = general_rating(
        my_rank,
        total_records
    )

    elite = elite_rating(
        my_rank,
        total_records
    )

    composite = composite_rating(
        general,
        elite
    )

    ahead = percentile_ahead(
        my_rank,
        total_records
    )

    top_percent = (
        my_rank
        / total_records
        * 100
    )

    wr_percentage = (
        my_score
        / wr_score
        * 100
    )


    # --------------------------------------------------------
    # SAME CAR RANK
    # --------------------------------------------------------

    same_car_drivers = [
        driver
        for driver in ranking
        if get_car_code(
            driver
        )
        == my_car_code
    ]


    same_car_rank = None


    for index, driver in enumerate(
        same_car_drivers,
        start=1
    ):

        if (
            online_id(driver)
            == MY_PSN_ID.lower()
        ):

            same_car_rank = index
            break


    # --------------------------------------------------------
    # COUNTRY RANK
    # --------------------------------------------------------

    my_country = (
        my_user.get(
            "country_code"
        )
    )


    country_drivers = [
        driver
        for driver in ranking
        if (
            get_user(driver)
            .get(
                "country_code"
            )
            == my_country
        )
    ]


    country_rank = None


    for index, driver in enumerate(
        country_drivers,
        start=1
    ):

        if (
            online_id(driver)
            == MY_PSN_ID.lower()
        ):

            country_rank = index
            break


    return {
        "participated":
            True,

        "week_start":
            event[
                "date"
            ]
            .date()
            .isoformat(),

        "final_snapshot":
            "archived_leaderboard",

        "finalization_mode":
            "historical_backfill",

        "extraction_mode":
            extraction_mode,

        "race":
            event[
                "text"
            ],

        "leaderboard_url":
            event[
                "url"
            ],

        "general_score":
            general,

        "elite_score":
            elite,

        "composite_rating":
            composite,

        "position":
            my_rank,

        "total_drivers":
            total_records,

        "top_percent":
            top_percent,

        "percentile_ahead":
            ahead,

        "wr_percentage":
            wr_percentage,

        "laptime":
            score_to_laptime(
                my_score
            ),

        "score_ms":
            my_score,

        "world_record":
            score_to_laptime(
                wr_score
            ),

        "world_record_ms":
            wr_score,

        "gap_to_wr_ms":
            my_score
            - wr_score,

        "car":
            get_car_name(
                my_car_code
            ),

        "car_code":
            my_car_code,

        "country":
            my_country,

        "driver_rating":
            my_user.get(
                "driver_rating"
            ),

        "country_rank":
            country_rank,

        "country_total":
            len(
                country_drivers
            ),

        "same_car_rank":
            same_car_rank,

        "same_car_total":
            len(
                same_car_drivers
            )
    }


# ============================================================
# TREND HELPERS
# ============================================================

def linear_metric_trend(
    records,
    key,
    higher_is_better=True
):

    values = [
        record.get(
            key
        )
        for record in records
        if (
            record.get(
                "participated"
            )
            and isinstance(
                record.get(
                    key
                ),
                (int, float)
            )
        )
    ]


    if len(values) < 2:
        return None


    first = values[
        0
    ]

    last = values[
        -1
    ]

    change = (
        last
        - first
    )

    improvement = (
        change
        if higher_is_better
        else -change
    )


    return {
        "first":
            first,

        "last":
            last,

        "change":
            change,

        "improvement":
            improvement
    }


# ============================================================
# MAIN
# ============================================================

def main():

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )


    now = datetime.now(
        SAO_PAULO
    )


    current_monday = monday_of_week(
        now
    )


    cutoff_date = (
        current_monday
        - timedelta(
            weeks=BACKFILL_WEEKS
        )
    )


    print()
    print(
        "GT7 DAILY RACE C - "
        "6 MONTH HISTORY BACKFILL"
    )
    print(
        "=" * 78
    )

    print(
        f"PSN ID: {MY_PSN_ID}"
    )

    print(
        f"From: {cutoff_date.date()}"
    )

    print(
        f"To: {current_monday.date()}"
    )

    print()


    session = requests.Session()

    session.headers.update(
        HEADERS
    )


    # ========================================================
    # DISCOVER EVENTS
    # ========================================================

    events = discover_race_c_events(
        session,
        cutoff_date,
        current_monday
    )


    print()

    print(
        f"Daily Race C events found: "
        f"{len(events)}"
    )

    print()


    if not events:

        raise RuntimeError(
            "No historical Daily Race C events "
            "were found."
        )


    # ========================================================
    # LOAD HISTORY
    # ========================================================

    history = load_existing_history()


    participated_records = []

    missing_weeks = []

    failed_events = []


    # ========================================================
    # PROCESS EVENTS
    # ========================================================

    for index, event in enumerate(
        events,
        start=1
    ):

        print(
            f"[{index}/{len(events)}] "
            f"{event['date'].date()} "
            f"Daily Race C"
        )

        print(
            f"    {event['text'][:140]}"
        )


        try:

            result = get_full_event_ranking(
                session,
                event[
                    "url"
                ]
            )


            ranking = result[
                "ranking"
            ]

            total_records = result[
                "total_records"
            ]

            extraction_mode = result[
                "mode"
            ]


            print(
                f"    Extraction mode: "
                f"{extraction_mode}"
            )

            print(
                f"    Drivers loaded: "
                f"{len(ranking):,}"
            )

            print(
                f"    Total drivers: "
                f"{total_records:,}"
            )


            record = build_record(
                event,
                ranking,
                total_records,
                extraction_mode
            )


            if not record:

                print(
                    "    ERROR: invalid leaderboard."
                )

                failed_events.append(
                    event
                )

                continue


            if not record.get(
                "participated"
            ):

                print(
                    f"    {MY_PSN_ID}: NOT FOUND"
                )

                missing_weeks.append(
                    record
                )

                continue


            print(
                f"    FOUND: {MY_PSN_ID}"
            )

            print(
                f"    Position: "
                f"#{record['position']:,} "
                f"of {record['total_drivers']:,}"
            )

            print(
                f"    Time: "
                f"{record['laptime']}"
            )

            print(
                f"    Car: "
                f"{record['car']}"
            )

            print(
                f"    General: "
                f"{record['general_score']:.2f}"
            )

            print(
                f"    Elite: "
                f"{record['elite_score']:.2f}"
            )

            print(
                f"    Composite: "
                f"{record['composite_rating']:.2f}"
            )

            print(
                f"    Top: "
                f"{record['top_percent']:.2f}%"
            )

            print(
                f"    WR: "
                f"{record['wr_percentage']:.3f}%"
            )


            upsert_record(
                history,
                record
            )


            participated_records.append(
                record
            )


        except Exception as error:

            print(
                f"    ERROR: {error}"
            )

            failed_events.append(
                event
            )


        time.sleep(
            REQUEST_DELAY_SECONDS
        )


    # ========================================================
    # SAVE HISTORY
    # ========================================================

    save_history(
        history
    )


    participated_records.sort(
        key=lambda item:
            item[
                "week_start"
            ]
    )


    # ========================================================
    # SUMMARY
    # ========================================================

    summary = []


    summary.append(
        "GT7 DAILY RACE C - HISTORICAL BACKFILL"
    )

    summary.append(
        "=" * 78
    )

    summary.append(
        f"Period searched: "
        f"{cutoff_date.date()} "
        f"to {current_monday.date()}"
    )

    summary.append(
        f"Race C events found: "
        f"{len(events)}"
    )

    summary.append(
        f"Participated: "
        f"{len(participated_records)}"
    )

    summary.append(
        f"PSN not found: "
        f"{len(missing_weeks)}"
    )

    summary.append(
        f"Extraction failures: "
        f"{len(failed_events)}"
    )


    if participated_records:

        summary.append("")

        summary.append(
            "HISTORICAL RATINGS"
        )


        for record in participated_records:

            summary.append(
                f"{record['week_start']} | "
                f"G {record['general_score']:.2f} | "
                f"E {record['elite_score']:.2f} | "
                f"C {record['composite_rating']:.2f} | "
                f"Top {record['top_percent']:.2f}% | "
                f"WR {record['wr_percentage']:.3f}% | "
                f"#{record['position']:,}/"
                f"{record['total_drivers']:,} | "
                f"{record['car']}"
            )


        general_trend = (
            linear_metric_trend(
                participated_records,
                "general_score",
                True
            )
        )


        elite_trend = (
            linear_metric_trend(
                participated_records,
                "elite_score",
                True
            )
        )


        composite_trend = (
            linear_metric_trend(
                participated_records,
                "composite_rating",
                True
            )
        )


        wr_trend = (
            linear_metric_trend(
                participated_records,
                "wr_percentage",
                False
            )
        )


        summary.append("")

        summary.append(
            "CHANGE ACROSS AVAILABLE HISTORY"
        )


        if general_trend:

            summary.append(
                f"General: "
                f"{general_trend['first']:.2f} "
                f"-> "
                f"{general_trend['last']:.2f} "
                f"({general_trend['change']:+.2f})"
            )


        if elite_trend:

            summary.append(
                f"Elite: "
                f"{elite_trend['first']:.2f} "
                f"-> "
                f"{elite_trend['last']:.2f} "
                f"({elite_trend['change']:+.2f})"
            )


        if composite_trend:

            summary.append(
                f"Composite: "
                f"{composite_trend['first']:.2f} "
                f"-> "
                f"{composite_trend['last']:.2f} "
                f"({composite_trend['change']:+.2f})"
            )


        if wr_trend:

            direction = (
                "improvement"
                if wr_trend[
                    "improvement"
                ] > 0
                else "deterioration"
            )


            summary.append(
                f"WR %: "
                f"{wr_trend['first']:.3f}% "
                f"-> "
                f"{wr_trend['last']:.3f}% "
                f"({abs(wr_trend['change']):.3f} pp "
                f"{direction})"
            )


    if missing_weeks:

        summary.append("")

        summary.append(
            "WEEKS WITHOUT A RECORDED LAP"
        )


        for record in missing_weeks:

            summary.append(
                record[
                    "week_start"
                ]
            )


    if failed_events:

        summary.append("")

        summary.append(
            "FAILED EVENTS"
        )


        for event in failed_events:

            summary.append(
                f"{event['date'].date()} | "
                f"{event['url']}"
            )


    summary.append("")

    summary.append(
        f"Saved to: "
        f"{WEEKLY_HISTORY_FILE}"
    )

    summary.append(
        "=" * 78
    )


    summary_text = "\n".join(
        summary
    )


    BACKFILL_LOG_FILE.write_text(
        summary_text,
        encoding="utf-8"
    )


    print()
    print(
        summary_text
    )


if __name__ == "__main__":
    main()