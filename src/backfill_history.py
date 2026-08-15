import requests
import json
import math
import re
import time
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from urllib.parse import urljoin


# ============================================================
# CONFIG
# ============================================================

GTSH_URL = "https://gtsh-rank.com/daily/"

MY_PSN_ID = "crazy_rooster74"

BACKFILL_WEEKS = 26

MAX_ARCHIVE_PAGES = 30

REQUEST_DELAY_SECONDS = 0.5

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

        online_id = (
            get_user(driver)
            .get(
                "np_online_id",
                ""
            )
        )

        if (
            isinstance(
                online_id,
                str
            )
            and online_id
            .strip()
            .lower()
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
        r"(\d{1,2}\s+"
        r"[A-Za-z]{3}\s+"
        r"\d{4})",
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
            WEEKLY_HISTORY_FILE
            .read_text(
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
# LEADERBOARD EXTRACTION
# ============================================================

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
                ]
                .lstrip()
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


def get_event_ranking(
    session,
    event_url
):
    response = session.get(
        event_url,
        timeout=60
    )

    response.raise_for_status()

    ranking = extract_initial_ranking(
        response.text
    )

    if not ranking:

        separator = (
            "&"
            if "?"
            in event_url
            else "?"
        )

        update_url = (
            event_url
            + separator
            + "update=1"
        )

        try:
            update_response = session.get(
                update_url,
                timeout=60
            )

            update_response.raise_for_status()

            candidate = (
                update_response.json()
            )

            if isinstance(
                candidate,
                list
            ):
                ranking = candidate

        except Exception:
            ranking = None

    if not ranking:
        return None

    ranking.sort(
        key=lambda driver:
            driver.get(
                "display_rank",
                999999999
            )
    )

    return ranking


# ============================================================
# BUILD HISTORICAL RECORD
# ============================================================

def build_record(
    event,
    ranking
):
    total = len(
        ranking
    )

    if total == 0:
        return None

    winner = ranking[
        0
    ]

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
                total
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
        total
    )

    elite = elite_rating(
        my_rank,
        total
    )

    composite = composite_rating(
        general,
        elite
    )

    ahead = percentile_ahead(
        my_rank,
        total
    )

    top_percent = (
        my_rank
        / total
        * 100
    )

    wr_percentage = (
        my_score
        / wr_score
        * 100
    )


    same_car_drivers = [
        driver
        for driver
        in ranking
        if get_car_code(
            driver
        )
        == my_car_code
    ]


    same_car_rank = None


    my_online_id = (
        my_user
        .get(
            "np_online_id",
            ""
        )
        .lower()
    )


    for index, driver in enumerate(
        same_car_drivers,
        start=1
    ):

        driver_id = (
            get_user(
                driver
            )
            .get(
                "np_online_id",
                ""
            )
            .lower()
        )

        if (
            driver_id
            == my_online_id
        ):
            same_car_rank = index
            break


    my_country = (
        my_user
        .get(
            "country_code"
        )
    )


    country_drivers = [
        driver
        for driver
        in ranking
        if (
            get_user(
                driver
            )
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

        driver_id = (
            get_user(
                driver
            )
            .get(
                "np_online_id",
                ""
            )
            .lower()
        )

        if (
            driver_id
            == my_online_id
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
            total,

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
# SUMMARY / TREND
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
        for record
        in records
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

    current_monday = (
        monday_of_week(
            now
        )
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
        f"PSN ID: "
        f"{MY_PSN_ID}"
    )

    print(
        f"From: "
        f"{cutoff_date.date()}"
    )

    print(
        f"To: "
        f"{current_monday.date()}"
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
            "No historical Daily Race C events "
            "were found."
        )


    history = load_existing_history()

    participated_records = []

    missing_weeks = []

    failed_events = []


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
            f"    {event['text'][:120]}"
        )


        try:

            ranking = get_event_ranking(
                session,
                event[
                    "url"
                ]
            )


            if not ranking:

                print(
                    "    ERROR: leaderboard "
                    "could not be extracted."
                )

                failed_events.append(
                    event
                )

                continue


            print(
                f"    Drivers: "
                f"{len(ranking):,}"
            )


            record = build_record(
                event,
                ranking
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
                    f"    {MY_PSN_ID}: "
                    f"NOT FOUND"
                )

                missing_weeks.append(
                    record
                )

                continue


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
                f"    ERROR: "
                f"{error}"
            )

            failed_events.append(
                event
            )


        time.sleep(
            REQUEST_DELAY_SECONDS
        )


    save_history(
        history
    )


    participated_records.sort(
        key=lambda item:
            item[
                "week_start"
            ]
    )


    summary = []


    summary.append(
        "GT7 DAILY RACE C - "
        "HISTORICAL BACKFILL"
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
                f"{record['total_drivers']:,}"
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