import requests
import json
import math
import re
import time
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from urllib.parse import (
    urljoin,
    urlparse,
    parse_qs,
    urlencode,
    urlunparse
)


# ============================================================
# CONFIG
# ============================================================

GTSH_URL = "https://gtsh-rank.com/daily/"
MY_PSN_ID = "crazy_rooster74"

BACKFILL_WEEKS = 26
MAX_ARCHIVE_PAGES = 30

PAGE_SIZE = 100
MAX_LEADERBOARD_PAGES = 1000

REQUEST_DELAY_SECONDS = 0.08

HEADERS = {
    "User-Agent": "Mozilla/5.0 (GT7 Daily Race History Backfill)"
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
    3352: "Toyota GR Supra Racing Concept '18",
    3399: "Toyota GR Supra Race Car '19",
    3477: "Nissan Silvia spec-R Aero (S15) Touring Car",
    3480: "Suzuki Swift Sport Gr.4",
    3501: "Genesis G70 GR4",
    3537: "Mazda3 Gr.4"
}


# ============================================================
# BASIC HELPERS
# ============================================================

def score_to_laptime(score):
    if score is None:
        return "N/A"

    score = int(round(score))

    minutes = score // 60000
    seconds = (score % 60000) // 1000
    milliseconds = score % 1000

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


def get_online_id(driver):
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

    return value.strip().lower()


def find_my_driver(
    ranking,
    psn_id
):
    target = psn_id.strip().lower()

    for driver in ranking:
        if get_online_id(driver) == target:
            return driver

    return None


# ============================================================
# RATINGS
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
        min(10.0, result)
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
        min(10.0, result)
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
        (total - rank)
        / (total - 1)
        * 100
    )


# ============================================================
# DATE HELPERS
# ============================================================

def parse_date_from_text(text):
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


def monday_of_week(value):
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
# HISTORY FILE
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

        if isinstance(data, list):
            return data

    except Exception:
        pass

    return []


def save_history(history):
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
            history[index] = record
            return

    history.append(record)


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
            break

        page_dates = []

        for link in links:

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

            oldest = min(
                page_dates
            )

            if (
                oldest
                < cutoff_date
                - timedelta(
                    days=14
                )
            ):
                reached_cutoff = True

        if reached_cutoff:
            break

        time.sleep(
            REQUEST_DELAY_SECONDS
        )

    result = list(
        events.values()
    )

    result.sort(
        key=lambda item:
            item[
                "date"
            ]
    )

    return result


# ============================================================
# JSON VARIABLE EXTRACTOR
# ============================================================

def extract_json_variable(
    html,
    variable_name
):
    markers = [
        f"const {variable_name} = ",
        f"let {variable_name} = ",
        f"var {variable_name} = "
    ]

    for marker in markers:

        start = html.find(
            marker
        )

        if start == -1:
            continue

        start += len(
            marker
        )

        try:
            decoder = json.JSONDecoder()

            value, _ = decoder.raw_decode(
                html[start:].lstrip()
            )

            return value

        except Exception:
            continue

    return None


# ============================================================
# CANONICAL URL
# ============================================================

def canonical_leaderboard_url(
    event_url
):
    parsed = urlparse(
        event_url
    )

    path = parsed.path.rstrip(
        "/"
    )

    if path.endswith(
        "/daily/leaderboard"
    ):
        path += "/"

    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            path,
            parsed.params,
            parsed.query,
            parsed.fragment
        )
    )


# ============================================================
# PAGE URL
# CRITICAL: page_data=1
# ============================================================

def build_page_url(
    event_url,
    offset,
    limit=PAGE_SIZE
):
    parsed = urlparse(
        canonical_leaderboard_url(
            event_url
        )
    )

    query = parse_qs(
        parsed.query,
        keep_blank_values=True
    )

    query["page_data"] = ["1"]
    query["offset"] = [str(offset)]
    query["limit"] = [str(limit)]

    query_string = urlencode(
        query,
        doseq=True
    )

    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            query_string,
            parsed.fragment
        )
    )


# ============================================================
# FETCH PAGE
# ============================================================

def fetch_page(
    session,
    event_url,
    offset
):
    url = build_page_url(
        event_url,
        offset,
        PAGE_SIZE
    )

    response = session.get(
        url,
        headers={
            "User-Agent":
                HEADERS["User-Agent"],

            "Accept":
                "application/json"
        },
        timeout=60
    )

    response.raise_for_status()

    data = response.json()

    if not isinstance(
        data,
        dict
    ):
        raise RuntimeError(
            "Paged response is not a JSON object."
        )

    board = data.get(
        "board"
    )

    if not isinstance(
        board,
        list
    ):
        raise RuntimeError(
            "Paged response has no board array."
        )

    actual_offset = int(
        data.get(
            "offset",
            0
        )
    )

    limit = int(
        data.get(
            "limit",
            PAGE_SIZE
        )
    )

    total = int(
        data.get(
            "total",
            0
        )
    )

    return {
        "board":
            board,

        "offset":
            actual_offset,

        "limit":
            limit,

        "total":
            total,

        "has_more":
            bool(
                data.get(
                    "has_more",
                    False
                )
            ),

        "leader_time":
            data.get(
                "leader_time"
            )
    }


# ============================================================
# FULL HISTORICAL LEADERBOARD
# ============================================================

def get_full_event_ranking(
    session,
    event_url
):
    canonical_url = (
        canonical_leaderboard_url(
            event_url
        )
    )

    response = session.get(
        canonical_url,
        timeout=60
    )

    response.raise_for_status()

    html = response.text

    initial_server_page = (
        extract_json_variable(
            html,
            "initialServerPage"
        )
    )


    # ========================================================
    # HISTORICAL PAGED BOARD
    # ========================================================

    if isinstance(
        initial_server_page,
        dict
    ) and isinstance(
        initial_server_page.get(
            "board"
        ),
        list
    ):

        total_records = int(
            initial_server_page.get(
                "total",
                0
            )
        )

        first_board = (
            initial_server_page[
                "board"
            ]
        )

        all_drivers = list(
            first_board
        )

        seen_ranks = {
            driver.get(
                "display_rank"
            )
            for driver in first_board
        }

        print(
            f"        page 1: "
            f"{len(first_board)} drivers | "
            f"total {total_records:,}"
        )


        offset = PAGE_SIZE


        for page_number in range(
            2,
            MAX_LEADERBOARD_PAGES + 1
        ):

            if (
                total_records
                and offset >= total_records
            ):
                break


            page = fetch_page(
                session,
                canonical_url,
                offset
            )


            if (
                page["offset"]
                != offset
            ):

                raise RuntimeError(
                    f"Pagination error: requested "
                    f"offset {offset}, received "
                    f"{page['offset']}."
                )


            board = page[
                "board"
            ]


            if not board:
                break


            # Avoid duplicates
            for driver in board:

                rank = driver.get(
                    "display_rank"
                )

                if rank in seen_ranks:
                    continue

                seen_ranks.add(
                    rank
                )

                all_drivers.append(
                    driver
                )


            if (
                page_number <= 3
                or page_number % 50 == 0
            ):

                first_rank = (
                    board[0].get(
                        "display_rank"
                    )
                )

                last_rank = (
                    board[-1].get(
                        "display_rank"
                    )
                )

                print(
                    f"        page {page_number}: "
                    f"ranks {first_rank}-{last_rank} | "
                    f"{len(all_drivers):,}/"
                    f"{total_records:,}"
                )


            if not page[
                "has_more"
            ]:

                break


            offset += (
                page[
                    "limit"
                ]
            )


            time.sleep(
                REQUEST_DELAY_SECONDS
            )


        all_drivers.sort(
            key=lambda driver:
                driver.get(
                    "display_rank",
                    999999999
                )
        )


        if (
            total_records
            and len(all_drivers)
            != total_records
        ):

            print(
                f"        WARNING: loaded "
                f"{len(all_drivers):,} of "
                f"{total_records:,}"
            )


        return {
            "ranking":
                all_drivers,

            "total_records":
                total_records,

            "mode":
                "server_paged_page_data"
        }


    # ========================================================
    # FULL INITIAL RANKING
    # ========================================================

    ranking = extract_json_variable(
        html,
        "initialRanking"
    )


    if (
        isinstance(
            ranking,
            list
        )
        and ranking
    ):

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
                len(ranking),

            "mode":
                "full_initialRanking"
        }


    raise RuntimeError(
        "Could not extract leaderboard."
    )


# ============================================================
# BUILD RECORD
# ============================================================

def build_record(
    event,
    ranking,
    total_records,
    extraction_mode
):
    if not ranking:
        return None

    winner = ranking[0]

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
                event["date"]
                .date()
                .isoformat(),

            "race":
                event["text"],

            "leaderboard_url":
                event["url"],

            "total_drivers":
                total_records,

            "extraction_mode":
                extraction_mode
        }


    my_score = my_driver.get(
        "score"
    )

    my_rank = int(
        my_driver.get(
            "display_rank"
        )
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


    # ========================================================
    # SAME CAR
    # ========================================================

    same_car = [
        driver
        for driver in ranking
        if get_car_code(
            driver
        ) == my_car_code
    ]

    same_car_rank = None

    for index, driver in enumerate(
        same_car,
        start=1
    ):

        if (
            get_online_id(driver)
            == MY_PSN_ID.lower()
        ):

            same_car_rank = index
            break


    # ========================================================
    # COUNTRY
    # ========================================================

    my_country = my_user.get(
        "country_code"
    )

    country_group = [
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
        country_group,
        start=1
    ):

        if (
            get_online_id(driver)
            == MY_PSN_ID.lower()
        ):

            country_rank = index
            break


    return {
        "participated":
            True,

        "week_start":
            event["date"]
            .date()
            .isoformat(),

        "final_snapshot":
            "archived_leaderboard",

        "finalization_mode":
            "historical_backfill",

        "extraction_mode":
            extraction_mode,

        "race":
            event["text"],

        "leaderboard_url":
            event["url"],

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
            my_score - wr_score,

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
            len(country_group),

        "same_car_rank":
            same_car_rank,

        "same_car_total":
            len(same_car)
    }


# ============================================================
# TREND
# ============================================================

def metric_change(
    records,
    key,
    higher_is_better=True
):
    values = [
        record.get(key)
        for record in records
        if isinstance(
            record.get(key),
            (int, float)
        )
    ]

    if len(values) < 2:
        return None

    first = values[0]
    last = values[-1]

    change = last - first

    improvement = (
        change
        if higher_is_better
        else -change
    )

    return {
        "first": first,
        "last": last,
        "change": change,
        "improvement": improvement
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
            "No historical events found."
        )


    history = load_existing_history()

    participated = []
    missing = []
    failures = []


    for number, event in enumerate(
        events,
        start=1
    ):

        print(
            f"[{number}/{len(events)}] "
            f"{event['date'].date()}"
        )

        print(
            f"    {event['text'][:150]}"
        )


        try:

            result = get_full_event_ranking(
                session,
                event["url"]
            )


            ranking = result[
                "ranking"
            ]

            total = result[
                "total_records"
            ]


            print(
                f"    Mode: "
                f"{result['mode']}"
            )

            print(
                f"    Drivers loaded: "
                f"{len(ranking):,}"
            )

            print(
                f"    Total: "
                f"{total:,}"
            )


            record = build_record(
                event,
                ranking,
                total,
                result["mode"]
            )


            if not record:

                failures.append(
                    event
                )

                print(
                    "    ERROR: invalid record"
                )

                continue


            if not record.get(
                "participated"
            ):

                missing.append(
                    record
                )

                print(
                    f"    {MY_PSN_ID}: NOT FOUND"
                )

                continue


            participated.append(
                record
            )

            upsert_record(
                history,
                record
            )


            print(
                f"    FOUND: "
                f"{MY_PSN_ID}"
            )

            print(
                f"    Position: "
                f"#{record['position']:,}/"
                f"{record['total_drivers']:,}"
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


        except Exception as error:

            failures.append(
                {
                    "date":
                        event["date"],

                    "url":
                        event["url"],

                    "error":
                        str(error)
                }
            )

            print(
                f"    ERROR: {error}"
            )


        time.sleep(
            REQUEST_DELAY_SECONDS
        )


    save_history(
        history
    )


    participated.sort(
        key=lambda item:
            item["week_start"]
    )


    lines = []


    lines.append(
        "GT7 DAILY RACE C - HISTORICAL BACKFILL"
    )

    lines.append(
        "=" * 78
    )

    lines.append(
        f"Period searched: "
        f"{cutoff_date.date()} "
        f"to {current_monday.date()}"
    )

    lines.append(
        f"Race C events found: "
        f"{len(events)}"
    )

    lines.append(
        f"Participated: "
        f"{len(participated)}"
    )

    lines.append(
        f"PSN not found: "
        f"{len(missing)}"
    )

    lines.append(
        f"Extraction failures: "
        f"{len(failures)}"
    )


    if participated:

        lines.append("")

        lines.append(
            "HISTORICAL RATINGS"
        )


        for record in participated:

            lines.append(
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


        general = metric_change(
            participated,
            "general_score"
        )

        elite = metric_change(
            participated,
            "elite_score"
        )

        composite = metric_change(
            participated,
            "composite_rating"
        )

        wr = metric_change(
            participated,
            "wr_percentage",
            False
        )


        if (
            general
            or elite
            or composite
            or wr
        ):

            lines.append("")

            lines.append(
                "CHANGE ACROSS AVAILABLE HISTORY"
            )


        if general:

            lines.append(
                f"General: "
                f"{general['first']:.2f} "
                f"-> "
                f"{general['last']:.2f} "
                f"({general['change']:+.2f})"
            )


        if elite:

            lines.append(
                f"Elite: "
                f"{elite['first']:.2f} "
                f"-> "
                f"{elite['last']:.2f} "
                f"({elite['change']:+.2f})"
            )


        if composite:

            lines.append(
                f"Composite: "
                f"{composite['first']:.2f} "
                f"-> "
                f"{composite['last']:.2f} "
                f"({composite['change']:+.2f})"
            )


        if wr:

            if wr[
                "improvement"
            ] > 0:

                direction = (
                    "improvement"
                )

            elif wr[
                "improvement"
            ] < 0:

                direction = (
                    "deterioration"
                )

            else:

                direction = (
                    "unchanged"
                )


            lines.append(
                f"WR %: "
                f"{wr['first']:.3f}% "
                f"-> "
                f"{wr['last']:.3f}% "
                f"({abs(wr['change']):.3f} pp "
                f"{direction})"
            )


    if missing:

        lines.append("")

        lines.append(
            "WEEKS WITHOUT A RECORDED LAP"
        )

        for record in missing:
            lines.append(
                record["week_start"]
            )


    if failures:

        lines.append("")

        lines.append(
            "FAILED EVENTS"
        )

        for failure in failures:

            if isinstance(
                failure,
                dict
            ):

                date_value = failure.get(
                    "date"
                )

                if hasattr(
                    date_value,
                    "date"
                ):

                    date_text = str(
                        date_value.date()
                    )

                else:

                    date_text = str(
                        date_value
                    )


                lines.append(
                    f"{date_text} | "
                    f"{failure.get('error','Unknown error')}"
                )


    lines.append("")

    lines.append(
        f"Saved to: "
        f"{WEEKLY_HISTORY_FILE}"
    )

    lines.append(
        "=" * 78
    )


    report = "\n".join(
        lines
    )


    BACKFILL_LOG_FILE.write_text(
        report,
        encoding="utf-8"
    )


    print()
    print(
        report
    )


if __name__ == "__main__":
    main()