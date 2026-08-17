#!/usr/bin/env python3

from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import (
    urlparse,
    parse_qs,
    urlencode,
    urlunparse,
)

import requests


# ============================================================
# CONFIG
# ============================================================

VERSION = "3.0"

MY_PSN_ID = "crazy_rooster74"

# Historical Daily Race C: 10 Aug 2026 -> 17 Aug 2026
HISTORICAL_URL = (
    "https://gtsh-rank.com/daily/leaderboard?"
    "event=HFYfEk1IVkJvQ0M4RUNBW0dGAW8BB1ZWX1ILEx1eSRMNRTdRXE0RG0deRUUeVklSTV5WQFFFXgkTUUpNUFgQU1BFRU5RUkNQGlNdVBVdVlFcTQAVUVVDREVOKC1DUBJbXEVSFVZJFg4eB1dN"
)

RACE_WEEK_START = "2026-08-10"

PAGE_SIZE = 100
MAX_LEADERBOARD_PAGES = 1000
REQUEST_DELAY_SECONDS = 0.08

HEADERS = {
    "User-Agent": "Mozilla/5.0 (GT7 Historical Race Recovery V3)"
}

DATA_DIR = Path("data")
OUTPUT_DIR = DATA_DIR / "historical_recovery"

OUTPUT_JSON = (
    OUTPUT_DIR
    / "daily_race_c_2026-08-10_final.json"
)

OUTPUT_TXT = (
    OUTPUT_DIR
    / "daily_race_c_2026-08-10_final.txt"
)

WEEKLY_HISTORY_FILE = (
    DATA_DIR
    / "weekly_rating_history.json"
)

SAO_PAULO = ZoneInfo(
    "America/Sao_Paulo"
)

SEPARATOR = "=" * 100
SUB_SEPARATOR = "-" * 100


# ============================================================
# CAR NAMES
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
    3537: "Mazda3 Gr.4",
}


# ============================================================
# GENERIC HELPERS
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
    if not isinstance(driver, dict):
        return {}

    return driver.get(
        "user",
        {},
    )


def get_car_code(driver):
    if not isinstance(driver, dict):
        return None

    return (
        driver
        .get(
            "ranking_stats",
            {},
        )
        .get(
            "car_code"
        )
    )


def get_car_name(car_code):
    return CAR_NAMES.get(
        car_code,
        f"Unknown car ({car_code})",
    )


def get_online_id(driver):
    value = (
        get_user(driver)
        .get(
            "np_online_id",
            "",
        )
    )

    if not isinstance(
        value,
        str,
    ):
        return ""

    return value.strip().lower()


def find_my_driver(
    ranking,
    psn_id,
):
    target = (
        psn_id
        .strip()
        .lower()
    )

    for driver in ranking:
        if get_online_id(driver) == target:
            return driver

    return None


# ============================================================
# RATINGS
# ============================================================

def general_rating(
    rank,
    total,
):
    if (
        rank is None
        or total is None
        or total <= 1
    ):
        return None

    result = (
        10
        * (
            1
            - (
                (rank - 1)
                / (total - 1)
            )
        )
    )

    return max(
        0.0,
        min(
            10.0,
            result,
        ),
    )


def elite_rating(
    rank,
    total,
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

    result = (
        10
        * (
            1
            - math.log(rank)
            / math.log(total)
        )
    )

    return max(
        0.0,
        min(
            10.0,
            result,
        ),
    )


def composite_rating(
    general,
    elite,
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
    total,
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
# JSON VARIABLE EXTRACTOR
# ============================================================

def extract_json_variable(
    html,
    variable_name,
):
    markers = [
        f"const {variable_name} = ",
        f"let {variable_name} = ",
        f"var {variable_name} = ",
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
    event_url,
):
    parsed = urlparse(
        event_url
    )

    path = (
        parsed.path
        .rstrip("/")
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
            parsed.fragment,
        )
    )


# ============================================================
# PAGED API URL
# ============================================================

def build_page_url(
    event_url,
    offset,
    limit=PAGE_SIZE,
):
    parsed = urlparse(
        canonical_leaderboard_url(
            event_url
        )
    )

    query = parse_qs(
        parsed.query,
        keep_blank_values=True,
    )

    query[
        "page_data"
    ] = ["1"]

    query[
        "offset"
    ] = [
        str(offset)
    ]

    query[
        "limit"
    ] = [
        str(limit)
    ]

    query_string = urlencode(
        query,
        doseq=True,
    )

    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            query_string,
            parsed.fragment,
        )
    )


# ============================================================
# FETCH PAGED DATA
# ============================================================

def fetch_page(
    session,
    event_url,
    offset,
):
    url = build_page_url(
        event_url,
        offset,
        PAGE_SIZE,
    )

    response = session.get(
        url,
        headers={
            "User-Agent":
                HEADERS[
                    "User-Agent"
                ],

            "Accept":
                "application/json",
        },
        timeout=60,
    )

    response.raise_for_status()

    data = response.json()

    if not isinstance(
        data,
        dict,
    ):
        raise RuntimeError(
            "Paged response is not a JSON object."
        )

    board = data.get(
        "board"
    )

    if not isinstance(
        board,
        list,
    ):
        raise RuntimeError(
            "Paged response has no board array."
        )

    try:
        actual_offset = int(
            data.get(
                "offset",
                0,
            )
        )
    except Exception:
        actual_offset = 0

    try:
        limit = int(
            data.get(
                "limit",
                PAGE_SIZE,
            )
        )
    except Exception:
        limit = PAGE_SIZE

    try:
        total = int(
            data.get(
                "total",
                0,
            )
        )
    except Exception:
        total = 0

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
                    False,
                )
            ),

        "leader_time":
            data.get(
                "leader_time"
            ),

        "url":
            url,
    }


# ============================================================
# LOAD HISTORICAL EVENT
# ============================================================

def load_initial_event(
    session,
    event_url,
):
    canonical_url = (
        canonical_leaderboard_url(
            event_url
        )
    )

    response = session.get(
        canonical_url,
        timeout=60,
    )

    response.raise_for_status()

    html = response.text

    initial_server_page = (
        extract_json_variable(
            html,
            "initialServerPage",
        )
    )

    initial_ranking = (
        extract_json_variable(
            html,
            "initialRanking",
        )
    )

    return {
        "url":
            canonical_url,

        "html":
            html,

        "initial_server_page":
            initial_server_page,

        "initial_ranking":
            initial_ranking,

        "response_bytes":
            len(
                response.content
            ),
    }


# ============================================================
# DETERMINE FIRST PAGE + TOTAL
# ============================================================

def get_first_page_info(
    initial,
):
    server_page = (
        initial.get(
            "initial_server_page"
        )
    )

    if (
        isinstance(
            server_page,
            dict,
        )
        and isinstance(
            server_page.get(
                "board"
            ),
            list,
        )
    ):
        board = (
            server_page[
                "board"
            ]
        )

        try:
            total = int(
                server_page.get(
                    "total",
                    len(board),
                )
            )
        except Exception:
            total = len(
                board
            )

        try:
            limit = int(
                server_page.get(
                    "limit",
                    PAGE_SIZE,
                )
            )
        except Exception:
            limit = PAGE_SIZE

        try:
            offset = int(
                server_page.get(
                    "offset",
                    0,
                )
            )
        except Exception:
            offset = 0

        return {
            "board":
                board,

            "total":
                total,

            "limit":
                limit,

            "offset":
                offset,

            "has_more":
                bool(
                    server_page.get(
                        "has_more",
                        total > len(board),
                    )
                ),

            "mode":
                "initialServerPage",
        }

    ranking = initial.get(
        "initial_ranking"
    )

    if (
        isinstance(
            ranking,
            list,
        )
        and ranking
    ):
        return {
            "board":
                ranking,

            "total":
                len(ranking),

            "limit":
                len(ranking),

            "offset":
                0,

            "has_more":
                False,

            "mode":
                "initialRanking",
        }

    raise RuntimeError(
        "Could not identify first historical leaderboard page."
    )


# ============================================================
# PAGINATED SEARCH FOR PSN
# ============================================================

def search_historical_driver(
    session,
    event_url,
    first_page,
    psn_id,
):
    target = (
        psn_id
        .strip()
        .lower()
    )

    board = first_page[
        "board"
    ]

    total = first_page[
        "total"
    ]

    limit = (
        first_page[
            "limit"
        ]
        or PAGE_SIZE
    )

    if limit <= 0:
        limit = PAGE_SIZE

    print("")
    print(
        "PAGED HISTORICAL LEADERBOARD"
    )
    print(
        SUB_SEPARATOR
    )

    print(
        f"Total records    : {total:,}"
    )

    print(
        f"Page size        : {limit}"
    )

    print(
        f"Initial entries  : {len(board)}"
    )

    # --------------------------------------------------------
    # First page
    # --------------------------------------------------------

    found = find_my_driver(
        board,
        target,
    )

    if found:

        print(
            "PSN found        : YES on initial page"
        )

        return {
            "driver":
                found,

            "total":
                total,

            "pages_requested":
                0,

            "entries_examined":
                len(board),

            "mode":
                "initial_page",
        }

    print(
        "PSN found        : NO on initial page"
    )

    # --------------------------------------------------------
    # If full ranking was embedded, nothing more to fetch.
    # --------------------------------------------------------

    if not first_page[
        "has_more"
    ]:

        return {
            "driver":
                None,

            "total":
                total,

            "pages_requested":
                0,

            "entries_examined":
                len(board),

            "mode":
                first_page[
                    "mode"
                ],
        }

    # --------------------------------------------------------
    # Continue with page_data=1
    # --------------------------------------------------------

    offset = (
        first_page[
            "offset"
        ]
        + limit
    )

    entries_examined = len(
        board
    )

    pages_requested = 0

    for page_number in range(
        2,
        MAX_LEADERBOARD_PAGES + 1,
    ):

        if (
            total
            and offset >= total
        ):
            break

        page = fetch_page(
            session,
            event_url,
            offset,
        )

        pages_requested += 1

        if (
            page[
                "offset"
            ]
            != offset
        ):
            raise RuntimeError(
                "Pagination mismatch: "
                f"requested offset {offset}, "
                f"received {page['offset']}."
            )

        page_board = (
            page[
                "board"
            ]
        )

        if not page_board:
            break

        entries_examined += len(
            page_board
        )

        first_rank = (
            page_board[
                0
            ].get(
                "display_rank"
            )
        )

        last_rank = (
            page_board[
                -1
            ].get(
                "display_rank"
            )
        )

        if (
            page_number <= 5
            or page_number % 25 == 0
        ):
            print(
                f"Page {page_number:<4}: "
                f"ranks {first_rank}-{last_rank} | "
                f"examined {entries_examined:,}/"
                f"{total:,}"
            )

        found = find_my_driver(
            page_board,
            target,
        )

        if found:

            print(
                f"PSN found        : YES on page {page_number}"
            )

            return {
                "driver":
                    found,

                "total":
                    total,

                "pages_requested":
                    pages_requested,

                "entries_examined":
                    entries_examined,

                "mode":
                    "page_data_search",
            }

        if not page[
            "has_more"
        ]:
            break

        page_limit = (
            page[
                "limit"
            ]
            or PAGE_SIZE
        )

        if page_limit <= 0:
            page_limit = PAGE_SIZE

        offset += (
            page_limit
        )

        time.sleep(
            REQUEST_DELAY_SECONDS
        )

    return {
        "driver":
            None,

        "total":
            total,

        "pages_requested":
            pages_requested,

        "entries_examined":
            entries_examined,

        "mode":
            "page_data_search",
    }


# ============================================================
# WORLD RECORD
# ============================================================

def extract_world_record(
    first_page,
):
    board = (
        first_page[
            "board"
        ]
    )

    if not board:
        return None

    winner = min(
        board,
        key=lambda driver:
            driver.get(
                "display_rank",
                999999999,
            ),
    )

    score = winner.get(
        "score"
    )

    user = get_user(
        winner
    )

    return {
        "score":
            score,

        "laptime":
            score_to_laptime(
                score
            ),

        "driver":
            user.get(
                "nick_name"
            ),

        "psn_id":
            user.get(
                "np_online_id"
            ),

        "car_code":
            get_car_code(
                winner
            ),

        "car":
            get_car_name(
                get_car_code(
                    winner
                )
            ),
    }


# ============================================================
# BUILD PERSONAL RESULT
# ============================================================

def build_personal_result(
    driver,
    total,
    world_record,
):
    if not driver:
        return None

    rank = driver.get(
        "display_rank"
    )

    score = driver.get(
        "score"
    )

    if (
        rank is None
        or score is None
        or total <= 0
    ):
        return None

    rank = int(
        rank
    )

    score = int(
        score
    )

    user = get_user(
        driver
    )

    car_code = get_car_code(
        driver
    )

    general = general_rating(
        rank,
        total,
    )

    elite = elite_rating(
        rank,
        total,
    )

    composite = composite_rating(
        general,
        elite,
    )

    ahead = percentile_ahead(
        rank,
        total,
    )

    top_percent = (
        rank
        / total
        * 100
    )

    wr_score = (
        world_record.get(
            "score"
        )
        if world_record
        else None
    )

    if (
        wr_score
        and wr_score > 0
    ):
        wr_percentage = (
            score
            / wr_score
            * 100
        )

        gap_to_wr_ms = (
            score
            - wr_score
        )

    else:
        wr_percentage = None
        gap_to_wr_ms = None

    return {
        "psn_id":
            user.get(
                "np_online_id",
                MY_PSN_ID,
            ),

        "driver":
            user.get(
                "nick_name"
            ),

        "rank":
            rank,

        "score":
            score,

        "laptime":
            score_to_laptime(
                score
            ),

        "total_drivers":
            total,

        "top_percent":
            top_percent,

        "percentile_ahead":
            ahead,

        "general_score":
            general,

        "elite_score":
            elite,

        "composite_rating":
            composite,

        "wr_percentage":
            wr_percentage,

        "gap_to_wr_ms":
            gap_to_wr_ms,

        "car_code":
            car_code,

        "car":
            get_car_name(
                car_code
            ),

        "country":
            user.get(
                "country_code"
            ),

        "driver_rating":
            user.get(
                "driver_rating"
            ),
    }


# ============================================================
# WEEKLY HISTORY
# ============================================================

def load_weekly_history():
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
            list,
        ):
            return data

    except Exception:
        pass

    return []


def save_weekly_history(
    history,
):
    history.sort(
        key=lambda item:
            item.get(
                "week_start",
                "",
            )
    )

    WEEKLY_HISTORY_FILE.write_text(
        json.dumps(
            history,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def build_weekly_history_record(
    personal,
    event_url,
):
    if not personal:
        return None

    return {
        "participated":
            True,

        "week_start":
            RACE_WEEK_START,

        "final_snapshot":
            "archived_leaderboard",

        "finalization_mode":
            "historical_recovery_page_data",

        "race":
            "Daily Race C - Grand Valley - Highway 1 - Gr.4",

        "leaderboard_url":
            canonical_leaderboard_url(
                event_url
            ),

        "general_score":
            personal[
                "general_score"
            ],

        "elite_score":
            personal[
                "elite_score"
            ],

        "composite_rating":
            personal[
                "composite_rating"
            ],

        "position":
            personal[
                "rank"
            ],

        "total_drivers":
            personal[
                "total_drivers"
            ],

        "top_percent":
            personal[
                "top_percent"
            ],

        "percentile_ahead":
            personal[
                "percentile_ahead"
            ],

        "wr_percentage":
            personal[
                "wr_percentage"
            ],

        "laptime":
            personal[
                "laptime"
            ],

        "score_ms":
            personal[
                "score"
            ],

        "car":
            personal[
                "car"
            ],

        "car_code":
            personal[
                "car_code"
            ],

        "country":
            personal[
                "country"
            ],

        "driver_rating":
            personal[
                "driver_rating"
            ],
    }


def upsert_weekly_history(
    record,
):
    if not record:
        return {
            "updated":
                False,

            "action":
                "not_written",
        }

    history = (
        load_weekly_history()
    )

    target_week = record.get(
        "week_start"
    )

    target_url = record.get(
        "leaderboard_url"
    )

    replaced = False

    for index, existing in enumerate(
        history
    ):

        same_week = (
            existing.get(
                "week_start"
            )
            == target_week
        )

        same_url = (
            existing.get(
                "leaderboard_url"
            )
            == target_url
        )

        if (
            same_week
            or same_url
        ):
            history[
                index
            ] = record

            replaced = True
            break

    if not replaced:
        history.append(
            record
        )

    save_weekly_history(
        history
    )

    return {
        "updated":
            True,

        "action":
            (
                "replaced"
                if replaced
                else "inserted"
            ),

        "records":
            len(history),
    }


# ============================================================
# REPORT
# ============================================================

def build_report(
    initial,
    first_page,
    search_result,
    world_record,
    personal,
    history_result,
):
    lines = []

    lines.append(
        SEPARATOR
    )

    lines.append(
        f"GT7 HISTORICAL DAILY RACE C RECOVERY V{VERSION}"
    )

    lines.append(
        SEPARATOR
    )

    lines.append(
        "Race week        : "
        "2026-08-10 -> 2026-08-17"
    )

    lines.append(
        f"PSN ID           : {MY_PSN_ID}"
    )

    lines.append(
        f"Historical URL   : {HISTORICAL_URL}"
    )

    lines.append(
        f"Initial mode     : {first_page['mode']}"
    )

    lines.append(
        f"Response bytes   : {initial['response_bytes']:,}"
    )

    lines.append("")

    lines.append(
        "HISTORICAL LEADERBOARD"
    )

    lines.append(
        SUB_SEPARATOR
    )

    lines.append(
        f"Total drivers    : {search_result['total']:,}"
    )

    lines.append(
        f"Entries examined : {search_result['entries_examined']:,}"
    )

    lines.append(
        f"Pages requested  : {search_result['pages_requested']:,}"
    )

    lines.append(
        f"Search mode      : {search_result['mode']}"
    )

    if world_record:

        lines.append("")

        lines.append(
            "WORLD RECORD"
        )

        lines.append(
            SUB_SEPARATOR
        )

        lines.append(
            f"Time             : {world_record['laptime']}"
        )

        lines.append(
            f"Driver           : {world_record.get('driver')}"
        )

        lines.append(
            f"PSN              : {world_record.get('psn_id')}"
        )

        lines.append(
            f"Car              : {world_record.get('car')}"
        )

    lines.append("")

    lines.append(
        "HISTORICAL DRIVER RESULT"
    )

    lines.append(
        SUB_SEPARATOR
    )

    if not personal:

        lines.append(
            "Found            : NO"
        )

        lines.append(
            f"PSN              : {MY_PSN_ID}"
        )

        lines.append(
            "Note             : PSN was not found after paginating "
            "the complete archived leaderboard."
        )

    else:

        lines.append(
            "Found            : YES"
        )

        lines.append(
            f"PSN              : {personal['psn_id']}"
        )

        lines.append(
            f"Rank             : #{personal['rank']:,}"
        )

        lines.append(
            f"Total drivers    : {personal['total_drivers']:,}"
        )

        lines.append(
            f"Lap time         : {personal['laptime']}"
        )

        lines.append(
            f"Car              : {personal['car']}"
        )

        if (
            personal[
                "gap_to_wr_ms"
            ]
            is not None
        ):
            lines.append(
                "Gap to WR        : "
                f"+{personal['gap_to_wr_ms']/1000:.3f}s"
            )

        if (
            personal[
                "wr_percentage"
            ]
            is not None
        ):
            lines.append(
                "WR percentage    : "
                f"{personal['wr_percentage']:.3f}%"
            )

        lines.append(
            "Top percentage   : "
            f"{personal['top_percent']:.2f}%"
        )

        lines.append(
            "Ahead of field   : "
            f"{personal['percentile_ahead']:.2f}%"
        )

        lines.append(
            "General rating   : "
            f"{personal['general_score']:.2f}"
        )

        lines.append(
            "Elite rating     : "
            f"{personal['elite_score']:.2f}"
        )

        lines.append(
            "Composite rating : "
            f"{personal['composite_rating']:.2f}"
        )

        lines.append(
            f"Country          : {personal.get('country')}"
        )

        lines.append(
            f"Driver rating    : {personal.get('driver_rating')}"
        )

    lines.append("")

    lines.append(
        "WEEKLY HISTORY"
    )

    lines.append(
        SUB_SEPARATOR
    )

    if history_result[
        "updated"
    ]:

        lines.append(
            "Updated          : YES"
        )

        lines.append(
            f"Action           : {history_result['action'].upper()}"
        )

        lines.append(
            f"Week             : {RACE_WEEK_START}"
        )

        lines.append(
            f"History records  : {history_result['records']}"
        )

        lines.append(
            f"File             : {WEEKLY_HISTORY_FILE}"
        )

    else:

        lines.append(
            "Updated          : NO"
        )

        lines.append(
            "Reason           : personal historical result not recovered"
        )

    lines.append("")

    lines.append(
        SEPARATOR
    )

    lines.append(
        f"Saved JSON       : {OUTPUT_JSON}"
    )

    lines.append(
        f"Saved report     : {OUTPUT_TXT}"
    )

    lines.append(
        SEPARATOR
    )

    return "\n".join(
        lines
    )


# ============================================================
# MAIN
# ============================================================

def main():

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    print(
        SEPARATOR
    )

    print(
        f"GT7 HISTORICAL DAILY RACE C RECOVERY V{VERSION}"
    )

    print(
        SEPARATOR
    )

    print(
        "Race week        : "
        "2026-08-10 -> 2026-08-17"
    )

    print(
        f"PSN ID           : {MY_PSN_ID}"
    )

    print(
        f"Historical URL   : {HISTORICAL_URL}"
    )

    session = requests.Session()

    session.headers.update(
        HEADERS
    )

    # --------------------------------------------------------
    # Load historical event page
    # --------------------------------------------------------

    initial = load_initial_event(
        session,
        HISTORICAL_URL,
    )

    first_page = get_first_page_info(
        initial
    )

    print("")

    print(
        "INITIAL HISTORICAL PAGE"
    )

    print(
        SUB_SEPARATOR
    )

    print(
        f"Mode             : {first_page['mode']}"
    )

    print(
        f"Entries          : {len(first_page['board'])}"
    )

    print(
        f"Total            : {first_page['total']:,}"
    )

    print(
        f"Has more         : {first_page['has_more']}"
    )

    # --------------------------------------------------------
    # World record
    # --------------------------------------------------------

    world_record = extract_world_record(
        first_page
    )

    if world_record:

        print("")

        print(
            "WORLD RECORD"
        )

        print(
            SUB_SEPARATOR
        )

        print(
            f"Time             : {world_record['laptime']}"
        )

        print(
            f"Driver           : {world_record.get('driver')}"
        )

        print(
            f"PSN              : {world_record.get('psn_id')}"
        )

        print(
            f"Car              : {world_record.get('car')}"
        )

    # --------------------------------------------------------
    # Search complete historical leaderboard
    # --------------------------------------------------------

    search_result = search_historical_driver(
        session,
        HISTORICAL_URL,
        first_page,
        MY_PSN_ID,
    )

    personal = build_personal_result(
        search_result[
            "driver"
        ],
        search_result[
            "total"
        ],
        world_record,
    )

    # --------------------------------------------------------
    # Update weekly history
    # --------------------------------------------------------

    weekly_record = (
        build_weekly_history_record(
            personal,
            HISTORICAL_URL,
        )
    )

    history_result = (
        upsert_weekly_history(
            weekly_record
        )
        if weekly_record
        else {
            "updated":
                False,

            "action":
                "not_written",
        }
    )

    # --------------------------------------------------------
    # Save structured output
    # --------------------------------------------------------

    output = {
        "version":
            VERSION,

        "generated_at":
            datetime.now(
                SAO_PAULO
            ).isoformat(),

        "race_week_start":
            RACE_WEEK_START,

        "historical_url":
            canonical_leaderboard_url(
                HISTORICAL_URL
            ),

        "initial_mode":
            first_page[
                "mode"
            ],

        "total_drivers":
            search_result[
                "total"
            ],

        "entries_examined":
            search_result[
                "entries_examined"
            ],

        "pages_requested":
            search_result[
                "pages_requested"
            ],

        "world_record":
            world_record,

        "personal_result":
            personal,

        "weekly_history":
            history_result,
    }

    OUTPUT_JSON.write_text(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    report = build_report(
        initial,
        first_page,
        search_result,
        world_record,
        personal,
        history_result,
    )

    OUTPUT_TXT.write_text(
        report,
        encoding="utf-8",
    )

    print("")

    print(
        report
    )


if __name__ == "__main__":
    main()