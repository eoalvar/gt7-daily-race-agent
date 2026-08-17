#!/usr/bin/env python3

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from urllib.parse import (
    parse_qs,
    urlencode,
    urlparse,
    urlunparse,
)

import requests


# ======================================================================================
# CONFIGURATION
# ======================================================================================

VERSION = "3.0"

MY_PSN_ID = "crazy_rooster74"

HISTORICAL_LEADERBOARD_URL = (
    "https://gtsh-rank.com/daily/leaderboard?"
    "event=HFYfEk1IVkJvQ0M4RUNBW0dGAW8BB1ZWX1ILEx1eSRMNRTdRXE0RG0deRUUeVklSTV5WQFFFXgkTUUpNUFgQU1BFRU5RUkNQGlNdVBVdVlFcTQAVUVVDREVOKC1DUBJbXEVSFVZJFg4eB1dN"
)

RACE_WEEK_START = "2026-08-10"
RACE_WEEK_END = "2026-08-17"

PAGE_SIZE = 100
MAX_LEADERBOARD_PAGES = 1000
REQUEST_DELAY_SECONDS = 0.08

HEADERS = {
    "User-Agent": "Mozilla/5.0 (GT7 Historical Race Recovery V3.0)",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
}

DATA_DIR = Path("data")
RECOVERY_DIR = DATA_DIR / "historical_recovery"

OUTPUT_FILE = (
    RECOVERY_DIR
    / "daily_race_c_2026-08-10_final.json"
)

WEEKLY_HISTORY_FILE = (
    DATA_DIR
    / "weekly_rating_history.json"
)

SEPARATOR = "=" * 100
SUB_SEPARATOR = "-" * 100


# ======================================================================================
# BASIC HELPERS
# ======================================================================================

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

    user = driver.get("user")

    return (
        user
        if isinstance(user, dict)
        else {}
    )


def get_online_id(driver):
    value = (
        get_user(driver)
        .get(
            "np_online_id",
            ""
        )
    )

    if not isinstance(value, str):
        return ""

    return value.strip()


def get_nickname(driver):
    value = (
        get_user(driver)
        .get(
            "nick_name"
        )
    )

    if isinstance(value, str) and value.strip():
        return value.strip()

    return None


def get_car_code(driver):
    if not isinstance(driver, dict):
        return None

    stats = driver.get(
        "ranking_stats"
    )

    if not isinstance(stats, dict):
        return None

    return stats.get(
        "car_code"
    )


def normalize_psn(value):
    if not isinstance(value, str):
        return ""

    return value.strip().lower()


def find_my_driver(
    ranking,
    psn_id,
):
    target = normalize_psn(
        psn_id
    )

    for driver in ranking:
        if (
            normalize_psn(
                get_online_id(driver)
            )
            == target
        ):
            return driver

    return None


# ======================================================================================
# RATINGS
# ======================================================================================

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


# ======================================================================================
# JSON VARIABLE EXTRACTION
# ======================================================================================

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
            decoder = (
                json.JSONDecoder()
            )

            value, _ = (
                decoder.raw_decode(
                    html[start:].lstrip()
                )
            )

            return value

        except Exception:
            continue

    return None


# ======================================================================================
# URL HELPERS
# ======================================================================================

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

    query["page_data"] = [
        "1"
    ]

    query["offset"] = [
        str(offset)
    ]

    query["limit"] = [
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


# ======================================================================================
# PAGED FETCH
# ======================================================================================

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
                HEADERS["User-Agent"],

            "Accept":
                "application/json",
        },
        timeout=60,
    )

    response.raise_for_status()

    content_type = (
        response.headers
        .get(
            "Content-Type",
            ""
        )
    )

    if (
        "application/json"
        not in content_type.lower()
    ):
        raise RuntimeError(
            "Paged historical response was not JSON. "
            f"Content-Type: {content_type}"
        )

    data = response.json()

    if not isinstance(
        data,
        dict,
    ):
        raise RuntimeError(
            "Paged historical response is not a JSON object."
        )

    board = data.get(
        "board"
    )

    if not isinstance(
        board,
        list,
    ):
        raise RuntimeError(
            "Paged historical response has no board array."
        )

    actual_offset = int(
        data.get(
            "offset",
            0,
        )
    )

    limit = int(
        data.get(
            "limit",
            PAGE_SIZE,
        )
    )

    total = int(
        data.get(
            "total",
            0,
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


# ======================================================================================
# FULL HISTORICAL LEADERBOARD
# ======================================================================================

def get_full_event_ranking(
    session,
    event_url,
):
    canonical_url = (
        canonical_leaderboard_url(
            event_url
        )
    )

    print(
        f"Canonical URL    : "
        f"{canonical_url}"
    )

    response = session.get(
        canonical_url,
        timeout=60,
    )

    response.raise_for_status()

    html = response.text

    print(
        f"HTTP status      : "
        f"{response.status_code}"
    )

    print(
        "Content-Type     : "
        f"{response.headers.get('Content-Type')}"
    )

    print(
        f"Response bytes   : "
        f"{len(response.content):,}"
    )

    initial_server_page = (
        extract_json_variable(
            html,
            "initialServerPage",
        )
    )

    # ------------------------------------------------------------------
    # Preferred mode:
    # archived server page + page_data pagination
    # ------------------------------------------------------------------

    if (
        isinstance(
            initial_server_page,
            dict,
        )
        and isinstance(
            initial_server_page.get(
                "board"
            ),
            list,
        )
    ):
        first_board = (
            initial_server_page[
                "board"
            ]
        )

        total_records = int(
            initial_server_page.get(
                "total",
                len(first_board),
            )
        )

        server_offset = int(
            initial_server_page.get(
                "offset",
                0,
            )
        )

        server_limit = int(
            initial_server_page.get(
                "limit",
                PAGE_SIZE,
            )
        )

        has_more = bool(
            initial_server_page.get(
                "has_more",
                total_records
                > len(first_board),
            )
        )

        print("")
        print(
            "HISTORICAL SERVER PAGE"
        )
        print(
            SUB_SEPARATOR
        )

        print(
            f"First page       : "
            f"{len(first_board)} drivers"
        )

        print(
            f"Total records    : "
            f"{total_records:,}"
        )

        print(
            f"Offset           : "
            f"{server_offset}"
        )

        print(
            f"Limit            : "
            f"{server_limit}"
        )

        print(
            f"Has more         : "
            f"{has_more}"
        )

        all_drivers = list(
            first_board
        )

        seen_keys = set()

        for driver in first_board:

            rank = driver.get(
                "display_rank"
            )

            psn = normalize_psn(
                get_online_id(driver)
            )

            key = (
                rank,
                psn,
                driver.get(
                    "score"
                ),
            )

            seen_keys.add(
                key
            )

        offset = (
            server_offset
            + server_limit
        )

        page_number = 2

        while (
            offset < total_records
            and page_number
            <= MAX_LEADERBOARD_PAGES
        ):
            page = fetch_page(
                session,
                canonical_url,
                offset,
            )

            if (
                page["offset"]
                != offset
            ):
                raise RuntimeError(
                    "Pagination mismatch: "
                    f"requested offset "
                    f"{offset}, "
                    f"received "
                    f"{page['offset']}."
                )

            board = page[
                "board"
            ]

            if not board:
                break

            added = 0

            for driver in board:

                rank = driver.get(
                    "display_rank"
                )

                psn = normalize_psn(
                    get_online_id(driver)
                )

                key = (
                    rank,
                    psn,
                    driver.get(
                        "score"
                    ),
                )

                if key in seen_keys:
                    continue

                seen_keys.add(
                    key
                )

                all_drivers.append(
                    driver
                )

                added += 1

            if (
                page_number <= 5
                or page_number % 25 == 0
                or not page[
                    "has_more"
                ]
            ):
                first_rank = (
                    board[0]
                    .get(
                        "display_rank"
                    )
                    if board
                    else None
                )

                last_rank = (
                    board[-1]
                    .get(
                        "display_rank"
                    )
                    if board
                    else None
                )

                print(
                    f"Page {page_number:<4}      : "
                    f"ranks "
                    f"{first_rank}-"
                    f"{last_rank} | "
                    f"+{added} | "
                    f"{len(all_drivers):,}/"
                    f"{total_records:,}"
                )

            if not page[
                "has_more"
            ]:
                break

            next_limit = page.get(
                "limit",
                PAGE_SIZE,
            )

            if (
                not isinstance(
                    next_limit,
                    int,
                )
                or next_limit <= 0
            ):
                next_limit = (
                    PAGE_SIZE
                )

            offset += next_limit
            page_number += 1

            time.sleep(
                REQUEST_DELAY_SECONDS
            )

        all_drivers.sort(
            key=lambda driver:
                driver.get(
                    "display_rank",
                    999999999,
                )
        )

        print("")
        print(
            "PAGINATION RESULT"
        )
        print(
            SUB_SEPARATOR
        )

        print(
            f"Loaded drivers   : "
            f"{len(all_drivers):,}"
        )

        print(
            f"Expected total   : "
            f"{total_records:,}"
        )

        complete = (
            len(all_drivers)
            >= total_records
        )

        print(
            f"Complete         : "
            f"{'YES' if complete else 'NO'}"
        )

        if not complete:
            print(
                "WARNING          : "
                "Full historical leaderboard was not completely loaded."
            )

        return {
            "ranking":
                all_drivers,

            "total_records":
                total_records,

            "mode":
                "server_paged_page_data",

            "complete":
                complete,
        }

    # ------------------------------------------------------------------
    # Fallback:
    # full initialRanking if available
    # ------------------------------------------------------------------

    ranking = (
        extract_json_variable(
            html,
            "initialRanking",
        )
    )

    if (
        isinstance(
            ranking,
            list,
        )
        and ranking
    ):
        ranking.sort(
            key=lambda driver:
                driver.get(
                    "display_rank",
                    999999999,
                )
        )

        print("")
        print(
            "FULL INITIAL RANKING"
        )
        print(
            SUB_SEPARATOR
        )

        print(
            f"Entries          : "
            f"{len(ranking):,}"
        )

        return {
            "ranking":
                ranking,

            "total_records":
                len(ranking),

            "mode":
                "full_initialRanking",

            "complete":
                True,
        }

    raise RuntimeError(
        "Could not extract the archived leaderboard. "
        "Neither initialServerPage nor a usable initialRanking was found."
    )


# ======================================================================================
# THRESHOLDS
# ======================================================================================

def get_rank_entry(
    ranking,
    rank,
):
    if not ranking:
        return None

    if rank < 1:
        return None

    if rank > len(ranking):
        return None

    return ranking[
        rank - 1
    ]


def percentile_rank(
    total,
    percent,
):
    return max(
        1,
        min(
            total,
            math.ceil(
                total
                * percent
                / 100
            ),
        ),
    )


def build_thresholds(
    ranking,
):
    total = len(
        ranking
    )

    fixed_ranks = [
        1,
        10,
        50,
        100,
        250,
        500,
        1000,
        2500,
        5000,
        10000,
    ]

    fixed = {}

    for rank in fixed_ranks:

        entry = get_rank_entry(
            ranking,
            rank,
        )

        if not entry:
            continue

        score = entry.get(
            "score"
        )

        fixed[
            str(rank)
        ] = {
            "rank":
                rank,

            "score":
                score,

            "laptime":
                score_to_laptime(
                    score
                ),

            "psn_id":
                get_online_id(
                    entry
                ),

            "driver":
                get_nickname(
                    entry
                ),

            "car_code":
                get_car_code(
                    entry
                ),
        }

    percentiles = {}

    for percent in [
        10,
        5,
        2,
        1,
        0.5,
    ]:
        rank = percentile_rank(
            total,
            percent,
        )

        entry = get_rank_entry(
            ranking,
            rank,
        )

        if not entry:
            continue

        score = entry.get(
            "score"
        )

        percentiles[
            str(percent)
        ] = {
            "percent":
                percent,

            "rank":
                rank,

            "score":
                score,

            "laptime":
                score_to_laptime(
                    score
                ),
        }

    return {
        "fixed":
            fixed,

        "percentiles":
            percentiles,
    }


# ======================================================================================
# GROUP STATS
# ======================================================================================

def group_rank(
    ranking,
    my_driver,
    predicate,
):
    group = [
        driver
        for driver in ranking
        if predicate(
            driver
        )
    ]

    target = normalize_psn(
        get_online_id(
            my_driver
        )
    )

    for index, driver in enumerate(
        group,
        start=1,
    ):
        if (
            normalize_psn(
                get_online_id(driver)
            )
            == target
        ):
            return (
                index,
                len(group),
            )

    return (
        None,
        len(group),
    )


# ======================================================================================
# WEEKLY HISTORY
# ======================================================================================

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
                ""
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


def upsert_weekly_record(
    history,
    record,
):
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
        same_url = (
            existing.get(
                "leaderboard_url"
            )
            == target_url
        )

        same_week = (
            existing.get(
                "week_start"
            )
            == target_week
        )

        if (
            same_url
            or same_week
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


# ======================================================================================
# BUILD PERSONAL RECORD
# ======================================================================================

def build_personal_record(
    ranking,
    total_records,
    my_driver,
):
    winner = ranking[0]

    wr_score = winner.get(
        "score"
    )

    my_score = my_driver.get(
        "score"
    )

    my_rank = my_driver.get(
        "display_rank"
    )

    if (
        wr_score is None
        or my_score is None
        or my_rank is None
    ):
        raise RuntimeError(
            "Historical driver record is missing rank or score."
        )

    my_rank = int(
        my_rank
    )

    my_user = get_user(
        my_driver
    )

    my_car_code = get_car_code(
        my_driver
    )

    my_country = my_user.get(
        "country_code"
    )

    my_dr = my_user.get(
        "driver_rating"
    )

    general = general_rating(
        my_rank,
        total_records,
    )

    elite = elite_rating(
        my_rank,
        total_records,
    )

    composite = composite_rating(
        general,
        elite,
    )

    ahead = percentile_ahead(
        my_rank,
        total_records,
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

    same_car_rank, same_car_total = (
        group_rank(
            ranking,
            my_driver,
            lambda driver:
                get_car_code(
                    driver
                )
                == my_car_code,
        )
    )

    country_rank, country_total = (
        group_rank(
            ranking,
            my_driver,
            lambda driver:
                get_user(
                    driver
                ).get(
                    "country_code"
                )
                == my_country,
        )
    )

    dr_rank, dr_total = (
        group_rank(
            ranking,
            my_driver,
            lambda driver:
                get_user(
                    driver
                ).get(
                    "driver_rating"
                )
                == my_dr,
        )
    )

    return {
        "psn_id":
            MY_PSN_ID,

        "rank":
            my_rank,

        "score":
            my_score,

        "laptime":
            score_to_laptime(
                my_score
            ),

        "car_code":
            my_car_code,

        "country":
            my_country,

        "driver_rating":
            my_dr,

        "gap_to_wr_ms":
            my_score
            - wr_score,

        "wr_percentage":
            wr_percentage,

        "general_score":
            general,

        "elite_score":
            elite,

        "composite_rating":
            composite,

        "top_percent":
            top_percent,

        "percentile_ahead":
            ahead,

        "same_car_rank":
            same_car_rank,

        "same_car_total":
            same_car_total,

        "country_rank":
            country_rank,

        "country_total":
            country_total,

        "dr_rank":
            dr_rank,

        "dr_total":
            dr_total,
    }


# ======================================================================================
# MAIN
# ======================================================================================

def main():
    RECOVERY_DIR.mkdir(
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
        f"Race week        : "
        f"{RACE_WEEK_START} -> "
        f"{RACE_WEEK_END}"
    )

    print(
        f"PSN ID           : "
        f"{MY_PSN_ID}"
    )

    print(
        f"Historical URL   : "
        f"{HISTORICAL_LEADERBOARD_URL}"
    )

    print("")

    session = (
        requests.Session()
    )

    session.headers.update(
        HEADERS
    )

    # ------------------------------------------------------------------
    # Load complete archived leaderboard
    # ------------------------------------------------------------------

    result = get_full_event_ranking(
        session,
        HISTORICAL_LEADERBOARD_URL,
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

    complete = result[
        "complete"
    ]

    if not ranking:
        raise RuntimeError(
            "Historical leaderboard is empty."
        )

    ranking.sort(
        key=lambda driver:
            driver.get(
                "display_rank",
                999999999,
            )
    )

    # ------------------------------------------------------------------
    # World record
    # ------------------------------------------------------------------

    winner = ranking[0]

    wr_score = winner.get(
        "score"
    )

    print("")
    print(
        "WORLD RECORD"
    )
    print(
        SUB_SEPARATOR
    )

    print(
        f"Time             : "
        f"{score_to_laptime(wr_score)}"
    )

    print(
        f"Driver           : "
        f"{get_nickname(winner)}"
    )

    print(
        f"PSN              : "
        f"{get_online_id(winner)}"
    )

    print(
        f"Car code         : "
        f"{get_car_code(winner)}"
    )

    # ------------------------------------------------------------------
    # Personal result
    # ------------------------------------------------------------------

    my_driver = find_my_driver(
        ranking,
        MY_PSN_ID,
    )

    personal = None

    print("")
    print(
        "HISTORICAL DRIVER RESULT"
    )
    print(
        SUB_SEPARATOR
    )

    if my_driver:

        personal = build_personal_record(
            ranking,
            total_records,
            my_driver,
        )

        print(
            "Found            : YES"
        )

        print(
            f"Rank             : "
            f"#{personal['rank']:,}"
            f"/{total_records:,}"
        )

        print(
            f"Time             : "
            f"{personal['laptime']}"
        )

        print(
            f"Gap to WR        : "
            f"+{personal['gap_to_wr_ms']/1000:.3f}s"
        )

        print(
            f"Top percentage   : "
            f"{personal['top_percent']:.2f}%"
        )

        print(
            f"Ahead of         : "
            f"{personal['percentile_ahead']:.2f}%"
        )

        print(
            f"General rating   : "
            f"{personal['general_score']:.2f}"
        )

        print(
            f"Elite rating     : "
            f"{personal['elite_score']:.2f}"
        )

        print(
            f"Composite        : "
            f"{personal['composite_rating']:.2f}"
        )

        print(
            f"Car code         : "
            f"{personal['car_code']}"
        )

        print(
            f"Country          : "
            f"{personal['country']}"
        )

        print(
            f"Country rank     : "
            f"{personal['country_rank']}"
            f"/{personal['country_total']}"
        )

        print(
            f"Same-car rank    : "
            f"{personal['same_car_rank']}"
            f"/{personal['same_car_total']}"
        )

    else:

        print(
            "Found            : NO"
        )

        print(
            f"Searched entries : "
            f"{len(ranking):,}"
        )

        print(
            "Note             : "
            "The complete historical ranking was searched, "
            "but the PSN was not found."
        )

    # ------------------------------------------------------------------
    # Benchmarks
    # ------------------------------------------------------------------

    thresholds = build_thresholds(
        ranking
    )

    print("")
    print(
        "FINAL LEADERBOARD BENCHMARKS"
    )
    print(
        SUB_SEPARATOR
    )

    for key in [
        "1",
        "10",
        "50",
        "100",
        "250",
        "500",
        "1000",
        "2500",
        "5000",
    ]:
        item = (
            thresholds[
                "fixed"
            ].get(
                key
            )
        )

        if not item:
            continue

        print(
            f"Top {key:<12}: "
            f"{item['laptime']}"
        )

    print("")

    for key in [
        "10",
        "5",
        "2",
        "1",
        "0.5",
    ]:
        item = (
            thresholds[
                "percentiles"
            ].get(
                key
            )
        )

        if not item:
            continue

        print(
            f"Top {key}%"
            f"{' ' * max(0, 9 - len(key))}: "
            f"{item['laptime']} "
            f"(#{item['rank']:,})"
        )

    # ------------------------------------------------------------------
    # Save recovery JSON
    # ------------------------------------------------------------------

    recovery = {
        "version":
            VERSION,

        "race_week_start":
            RACE_WEEK_START,

        "race_week_end":
            RACE_WEEK_END,

        "leaderboard_url":
            HISTORICAL_LEADERBOARD_URL,

        "extraction_mode":
            extraction_mode,

        "complete_leaderboard":
            complete,

        "total_drivers":
            total_records,

        "loaded_drivers":
            len(ranking),

        "world_record": {
            "score":
                wr_score,

            "laptime":
                score_to_laptime(
                    wr_score
                ),

            "driver":
                get_nickname(
                    winner
                ),

            "psn_id":
                get_online_id(
                    winner
                ),

            "car_code":
                get_car_code(
                    winner
                ),
        },

        "personal_result":
            personal,

        "thresholds":
            thresholds,
    }

    OUTPUT_FILE.write_text(
        json.dumps(
            recovery,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # ------------------------------------------------------------------
    # Update weekly history
    # ------------------------------------------------------------------

    weekly_updated = False

    if personal:

        weekly_record = {
            "participated":
                True,

            "week_start":
                RACE_WEEK_START,

            "final_snapshot":
                "archived_leaderboard",

            "finalization_mode":
                "historical_recovery_v3",

            "extraction_mode":
                extraction_mode,

            "race":
                "Daily Race C historical recovery",

            "leaderboard_url":
                HISTORICAL_LEADERBOARD_URL,

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
                total_records,

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

            "world_record":
                score_to_laptime(
                    wr_score
                ),

            "world_record_ms":
                wr_score,

            "gap_to_wr_ms":
                personal[
                    "gap_to_wr_ms"
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

            "country_rank":
                personal[
                    "country_rank"
                ],

            "country_total":
                personal[
                    "country_total"
                ],

            "same_car_rank":
                personal[
                    "same_car_rank"
                ],

            "same_car_total":
                personal[
                    "same_car_total"
                ],
        }

        history = (
            load_weekly_history()
        )

        upsert_weekly_record(
            history,
            weekly_record,
        )

        weekly_updated = True

    # ------------------------------------------------------------------
    # Final output
    # ------------------------------------------------------------------

    print("")
    print(
        SEPARATOR
    )

    print(
        f"Saved result     : "
        f"{OUTPUT_FILE}"
    )

    print(
        "Weekly history   : "
        + (
            "UPDATED"
            if weekly_updated
            else (
                "NOT UPDATED "
                "(personal result not recovered)"
            )
        )
    )

    print(
        f"Extraction mode  : "
        f"{extraction_mode}"
    )

    print(
        f"Loaded drivers   : "
        f"{len(ranking):,}/"
        f"{total_records:,}"
    )

    print(
        SEPARATOR
    )


if __name__ == "__main__":
    main()