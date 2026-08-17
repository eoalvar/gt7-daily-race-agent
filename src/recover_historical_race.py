#!/usr/bin/env python3

from __future__ import annotations

import json
import math
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


# ======================================================================================
# CONFIGURATION
# ======================================================================================

VERSION = "2.0"

MY_PSN_ID = "crazy_rooster74"

HISTORICAL_WEEK_START = "2026-08-10"
HISTORICAL_WEEK_END = "2026-08-17"

HISTORICAL_URL = (
    "https://gtsh-rank.com/daily/leaderboard?"
    "event=HFYfEk1IVkJvQ0M4RUNBW0dGAW8BB1ZWX1ILEx1eSRMNRTdRXE0RG0deRUUeVklSTV5WQFFFXgkTUUpNUFgQU1BFRU5RUkNQGlNdVBVdVlFcTQAVUVVDREVOKC1DUBJbXEVSFVZJFg4eB1dN"
)

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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (GT7 Daily Race Agent)"
}

SEPARATOR = "=" * 100
SUB_SEPARATOR = "-" * 100


# ======================================================================================
# GENERIC HELPERS
# ======================================================================================

def score_to_laptime(
    score: Optional[int]
) -> str:

    if score is None:
        return "N/A"

    score = int(
        round(score)
    )

    minutes = (
        score // 60000
    )

    seconds = (
        (score % 60000)
        // 1000
    )

    milliseconds = (
        score % 1000
    )

    return (
        f"{minutes}:"
        f"{seconds:02d}."
        f"{milliseconds:03d}"
    )


def get_user(
    driver: Dict[str, Any]
) -> Dict[str, Any]:

    user = driver.get(
        "user",
        {}
    )

    if isinstance(
        user,
        dict
    ):
        return user

    return {}


def get_car_code(
    driver: Dict[str, Any]
) -> Optional[int]:

    stats = driver.get(
        "ranking_stats",
        {}
    )

    if not isinstance(
        stats,
        dict
    ):
        return None

    return stats.get(
        "car_code"
    )


def get_rank(
    driver: Dict[str, Any],
    fallback: Optional[int] = None
) -> Optional[int]:

    rank = driver.get(
        "display_rank"
    )

    if isinstance(
        rank,
        (int, float)
    ):
        return int(rank)

    rank = driver.get(
        "rank"
    )

    if isinstance(
        rank,
        (int, float)
    ):
        return int(rank)

    return fallback


def get_online_id(
    driver: Dict[str, Any]
) -> str:

    value = get_user(
        driver
    ).get(
        "np_online_id",
        ""
    )

    if isinstance(
        value,
        str
    ):
        return value.strip()

    return ""


def get_driver_name(
    driver: Dict[str, Any]
) -> str:

    user = get_user(
        driver
    )

    for key in [
        "nick_name",
        "nickname",
        "name",
        "np_online_id",
    ]:

        value = user.get(
            key
        )

        if isinstance(
            value,
            str
        ) and value.strip():

            return value.strip()

    return "Unknown"


def find_my_driver(
    ranking: List[Dict[str, Any]],
    psn_id: str
) -> Optional[Dict[str, Any]]:

    target = (
        psn_id
        .strip()
        .lower()
    )

    for driver in ranking:

        if (
            get_online_id(driver)
            .lower()
            == target
        ):
            return driver

    return None


# ======================================================================================
# RATING HELPERS
# ======================================================================================

def position_score(
    rank: Optional[int],
    total: int
) -> Optional[float]:

    if (
        rank is None
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
            result
        )
    )


def elite_score(
    rank: Optional[int],
    total: int
) -> Optional[float]:

    if (
        rank is None
        or rank < 1
        or total <= 1
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
            result
        )
    )


def composite_rating(
    general: Optional[float],
    elite: Optional[float]
) -> Optional[float]:

    if (
        general is None
        or elite is None
    ):
        return None

    return (
        0.60 * general
        + 0.40 * elite
    )


def percentile_ahead(
    rank: Optional[int],
    total: int
) -> Optional[float]:

    if (
        rank is None
        or total <= 1
    ):
        return None

    return (
        (total - rank)
        / (total - 1)
        * 100
    )


def pace_band(
    wr_percentage: float
) -> str:

    if wr_percentage <= 101:
        return "ALIEN"

    if wr_percentage <= 102:
        return "ELITE"

    if wr_percentage <= 103:
        return "VERY FAST"

    if wr_percentage <= 105:
        return "COMPETITIVE"

    if wr_percentage <= 108:
        return "MID-PACK"

    return "DEVELOPING"


# ======================================================================================
# INITIAL RANKING EXTRACTION
# ======================================================================================

def extract_initial_ranking(
    html: str
) -> List[Dict[str, Any]]:

    marker = (
        "const initialRanking = "
    )

    start = html.find(
        marker
    )

    if start == -1:
        return []

    start += len(
        marker
    )

    try:

        decoder = json.JSONDecoder()

        ranking, _ = (
            decoder.raw_decode(
                html[start:].lstrip()
            )
        )

        if isinstance(
            ranking,
            list
        ):
            return ranking

    except Exception:
        pass

    return []


# ======================================================================================
# UPDATE-ENDPOINT EXTRACTION
# ======================================================================================

def build_update_url(
    leaderboard_url: str
) -> str:

    if "update=1" in leaderboard_url:
        return leaderboard_url

    if "?" in leaderboard_url:
        return (
            leaderboard_url
            + "&update=1"
        )

    return (
        leaderboard_url
        + "?update=1"
    )


def extract_ranking_from_json(
    data: Any
) -> List[Dict[str, Any]]:

    if isinstance(
        data,
        list
    ):
        return [
            item
            for item in data
            if isinstance(
                item,
                dict
            )
        ]

    if not isinstance(
        data,
        dict
    ):
        return []

    possible_keys = [
        "board",
        "ranking",
        "rankings",
        "leaderboard",
        "drivers",
        "results",
        "data",
    ]

    for key in possible_keys:

        value = data.get(
            key
        )

        if isinstance(
            value,
            list
        ):

            return [
                item
                for item in value
                if isinstance(
                    item,
                    dict
                )
            ]

        if isinstance(
            value,
            dict
        ):

            nested = (
                extract_ranking_from_json(
                    value
                )
            )

            if nested:
                return nested

    for value in data.values():

        if isinstance(
            value,
            (dict, list)
        ):

            nested = (
                extract_ranking_from_json(
                    value
                )
            )

            if nested:
                return nested

    return []


# ======================================================================================
# RANKING NORMALIZATION
# ======================================================================================

def normalize_ranking(
    ranking: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:

    usable = []

    for driver in ranking:

        if not isinstance(
            driver,
            dict
        ):
            continue

        score = driver.get(
            "score"
        )

        if not isinstance(
            score,
            (int, float)
        ):
            continue

        usable.append(
            driver
        )

    # Prefer display_rank when present.
    #
    # If the archived endpoint has no rank,
    # score ascending determines leaderboard order.

    has_display_rank = any(
        isinstance(
            driver.get(
                "display_rank"
            ),
            (int, float)
        )
        for driver in usable
    )

    if has_display_rank:

        usable.sort(
            key=lambda driver:
                (
                    driver.get(
                        "display_rank",
                        999999999
                    ),
                    driver.get(
                        "score",
                        999999999
                    ),
                )
        )

    else:

        usable.sort(
            key=lambda driver:
                driver.get(
                    "score",
                    999999999
                )
        )

    return usable


# ======================================================================================
# THRESHOLDS
# ======================================================================================

def build_thresholds(
    ranking: List[Dict[str, Any]]
) -> Dict[str, Any]:

    positions = [
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

    result = {}

    for position in positions:

        if len(ranking) < position:
            continue

        driver = ranking[
            position - 1
        ]

        score = driver.get(
            "score"
        )

        result[
            str(position)
        ] = {
            "rank":
                position,

            "score":
                score,

            "laptime":
                score_to_laptime(
                    score
                ),
        }

    return result


def percentile_rank(
    total: int,
    percent: float
) -> int:

    return max(
        1,
        min(
            total,
            math.ceil(
                total
                * percent
                / 100
            )
        )
    )


def build_percentiles(
    ranking: List[Dict[str, Any]]
) -> Dict[str, Any]:

    result = {}

    for percent in [
        10,
        5,
        2,
        1,
    ]:

        rank = percentile_rank(
            len(ranking),
            percent
        )

        score = ranking[
            rank - 1
        ].get(
            "score"
        )

        result[
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

    return result


# ======================================================================================
# PERSONAL RESULT
# ======================================================================================

def build_personal_result(
    ranking: List[Dict[str, Any]],
    my_driver: Dict[str, Any],
    wr_score: int
) -> Dict[str, Any]:

    total = len(
        ranking
    )

    # Some archived data may omit display_rank.
    #
    # Therefore determine position from the normalized
    # leaderboard itself if necessary.

    rank = None

    for index, driver in enumerate(
        ranking,
        start=1
    ):

        if driver is my_driver:

            rank = get_rank(
                driver,
                index
            )

            break

    if rank is None:

        rank = get_rank(
            my_driver
        )

    score = my_driver.get(
        "score"
    )

    user = get_user(
        my_driver
    )

    car_code = get_car_code(
        my_driver
    )

    if (
        score is None
        or wr_score is None
    ):
        raise RuntimeError(
            "Historical personal score or WR is unavailable."
        )

    wr_percentage = (
        score
        / wr_score
        * 100
    )

    general = position_score(
        rank,
        total
    )

    elite = elite_score(
        rank,
        total
    )

    ahead = percentile_ahead(
        rank,
        total
    )

    return {
        "psn_id":
            MY_PSN_ID,

        "rank":
            rank,

        "score":
            score,

        "laptime":
            score_to_laptime(
                score
            ),

        "car_code":
            car_code,

        "country":
            user.get(
                "country_code"
            ),

        "driver_rating":
            user.get(
                "driver_rating"
            ),

        "gap_to_wr_ms":
            score
            - wr_score,

        "wr_percentage":
            wr_percentage,

        "position_score":
            general,

        "elite_score":
            elite,

        "composite_rating":
            composite_rating(
                general,
                elite
            ),

        "percentile_ahead":
            ahead,

        "top_percent":
            (
                rank
                / total
                * 100
            )
            if rank
            else None,

        "pace_band":
            pace_band(
                wr_percentage
            ),
    }


# ======================================================================================
# CAR META
# ======================================================================================

def build_car_meta(
    ranking: List[Dict[str, Any]]
) -> Dict[str, Any]:

    all_counter = Counter(
        get_car_code(driver)
        for driver in ranking
        if get_car_code(driver)
        is not None
    )

    top1000 = ranking[
        :min(
            1000,
            len(ranking)
        )
    ]

    top1000_counter = Counter(
        get_car_code(driver)
        for driver in top1000
        if get_car_code(driver)
        is not None
    )

    top5 = []

    denominator = len(
        top1000
    )

    for (
        car_code,
        count
    ) in top1000_counter.most_common(
        5
    ):

        percentage = (
            count
            / denominator
            * 100
            if denominator
            else 0
        )

        top5.append(
            {
                "car_code":
                    car_code,

                "count":
                    count,

                "percentage":
                    percentage,

                "all_entries":
                    all_counter.get(
                        car_code,
                        0
                    ),
            }
        )

    return {
        "top5_used_cars":
            top5,

        "unique_car_codes":
            len(
                all_counter
            ),
    }


# ======================================================================================
# WEEKLY HISTORY
# ======================================================================================

def load_weekly_history() -> List[Dict[str, Any]]:

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


def save_weekly_history(
    history: List[Dict[str, Any]]
) -> None:

    history.sort(
        key=lambda item:
            item.get(
                "week_start",
                ""
            )
    )

    WEEKLY_HISTORY_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    WEEKLY_HISTORY_FILE.write_text(
        json.dumps(
            history,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


def build_weekly_record(
    recovery: Dict[str, Any]
) -> Optional[Dict[str, Any]]:

    my = recovery.get(
        "my_result"
    )

    if not isinstance(
        my,
        dict
    ):
        return None

    return {
        "participated":
            True,

        "week_start":
            HISTORICAL_WEEK_START,

        "final_snapshot":
            recovery.get(
                "recovered_at"
            ),

        "finalization_mode":
            "historical_recovery",

        "race":
            (
                "Daily Race C "
                "Grand Valley - Highway 1"
            ),

        "leaderboard_url":
            HISTORICAL_URL,

        "general_score":
            my.get(
                "position_score"
            ),

        "elite_score":
            my.get(
                "elite_score"
            ),

        "composite_rating":
            my.get(
                "composite_rating"
            ),

        "position":
            my.get(
                "rank"
            ),

        "total_drivers":
            recovery.get(
                "total_drivers"
            ),

        "top_percent":
            my.get(
                "top_percent"
            ),

        "percentile_ahead":
            my.get(
                "percentile_ahead"
            ),

        "wr_percentage":
            my.get(
                "wr_percentage"
            ),

        "laptime":
            my.get(
                "laptime"
            ),

        "score_ms":
            my.get(
                "score"
            ),

        "car_code":
            my.get(
                "car_code"
            ),

        "country":
            my.get(
                "country"
            ),

        "driver_rating":
            my.get(
                "driver_rating"
            ),
    }


def upsert_weekly_history(
    record: Dict[str, Any]
) -> None:

    history = load_weekly_history()

    replaced = False

    for index, existing in enumerate(
        history
    ):

        same_week = (
            existing.get(
                "week_start"
            )
            == HISTORICAL_WEEK_START
        )

        same_url = (
            existing.get(
                "leaderboard_url"
            )
            == HISTORICAL_URL
        )

        if (
            same_week
            or same_url
        ):

            history[index] = record

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
# MAIN
# ======================================================================================

def main() -> None:

    RECOVERY_DIR.mkdir(
        parents=True,
        exist_ok=True
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
        f"{HISTORICAL_WEEK_START} -> "
        f"{HISTORICAL_WEEK_END}"
    )

    print(
        f"PSN ID           : "
        f"{MY_PSN_ID}"
    )

    print(
        f"Historical URL   : "
        f"{HISTORICAL_URL}"
    )

    session = requests.Session()

    session.headers.update(
        HEADERS
    )

    # ==================================================================================
    # PAGE
    # ==================================================================================

    response = session.get(
        HISTORICAL_URL,
        timeout=60
    )

    response.raise_for_status()

    html = response.text

    print("")
    print(
        f"HTTP status      : "
        f"{response.status_code}"
    )

    print(
        f"Content-Type     : "
        f"{response.headers.get('Content-Type')}"
    )

    print(
        f"Response bytes   : "
        f"{len(response.content):,}"
    )

    # ==================================================================================
    # INITIAL RANKING
    # ==================================================================================

    initial_ranking = (
        extract_initial_ranking(
            html
        )
    )

    print("")
    print(
        "INITIAL RANKING"
    )

    print(
        SUB_SEPARATOR
    )

    print(
        f"Entries          : "
        f"{len(initial_ranking):,}"
    )

    initial_my_driver = (
        find_my_driver(
            initial_ranking,
            MY_PSN_ID
        )
    )

    print(
        "My PSN present   : "
        + (
            "YES"
            if initial_my_driver
            else "NO"
        )
    )

    # ==================================================================================
    # FULL UPDATE ENDPOINT
    # ==================================================================================

    update_url = build_update_url(
        HISTORICAL_URL
    )

    print("")
    print(
        "FULL LEADERBOARD REQUEST"
    )

    print(
        SUB_SEPARATOR
    )

    print(
        f"Update URL       : "
        f"{update_url}"
    )

    update_response = session.get(
        update_url,
        timeout=120
    )

    print(
        f"HTTP status      : "
        f"{update_response.status_code}"
    )

    print(
        f"Content-Type     : "
        f"{update_response.headers.get('Content-Type')}"
    )

    print(
        f"Response bytes   : "
        f"{len(update_response.content):,}"
    )

    update_response.raise_for_status()

    ranking: List[
        Dict[str, Any]
    ] = []

    update_json = None

    try:

        update_json = (
            update_response.json()
        )

        ranking = (
            extract_ranking_from_json(
                update_json
            )
        )

    except Exception as exc:

        print(
            f"JSON parse       : FAILED "
            f"({type(exc).__name__})"
        )

    print(
        f"Update entries   : "
        f"{len(ranking):,}"
    )

    # ==================================================================================
    # FALLBACK
    # ==================================================================================

    if not ranking:

        print("")
        print(
            "Update endpoint did not return a ranking."
        )

        print(
            "Falling back to initialRanking."
        )

        ranking = (
            initial_ranking
        )

    ranking = normalize_ranking(
        ranking
    )

    print(
        f"Usable entries   : "
        f"{len(ranking):,}"
    )

    if not ranking:

        raise RuntimeError(
            "No usable historical leaderboard entries found."
        )

    # ==================================================================================
    # WORLD RECORD
    # ==================================================================================

    winner = ranking[0]

    wr_score = winner.get(
        "score"
    )

    if not isinstance(
        wr_score,
        (int, float)
    ):

        raise RuntimeError(
            "Historical WR score unavailable."
        )

    wr_score = int(
        wr_score
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
        f"{get_driver_name(winner)}"
    )

    print(
        f"PSN              : "
        f"{get_online_id(winner) or 'N/A'}"
    )

    print(
        f"Car code         : "
        f"{get_car_code(winner)}"
    )

    # ==================================================================================
    # PERSONAL DRIVER
    # ==================================================================================

    my_driver = find_my_driver(
        ranking,
        MY_PSN_ID
    )

    print("")
    print(
        "HISTORICAL DRIVER RESULT"
    )

    print(
        SUB_SEPARATOR
    )

    print(
        "Found            : "
        + (
            "YES"
            if my_driver
            else "NO"
        )
    )

    my_result = None

    if my_driver:

        my_result = (
            build_personal_result(
                ranking,
                my_driver,
                wr_score
            )
        )

        print(
            f"Rank             : "
            f"#{my_result['rank']:,}"
        )

        print(
            f"Time             : "
            f"{my_result['laptime']}"
        )

        print(
            f"Score            : "
            f"{my_result['score']} ms"
        )

        print(
            f"Gap to WR        : "
            f"+{my_result['gap_to_wr_ms']/1000:.3f}s"
        )

        print(
            f"Top percentage   : "
            f"{my_result['top_percent']:.2f}%"
        )

        print(
            f"Ahead of         : "
            f"{my_result['percentile_ahead']:.2f}%"
        )

        print(
            f"WR percentage    : "
            f"{my_result['wr_percentage']:.3f}%"
        )

        print(
            f"General rating   : "
            f"{my_result['position_score']:.2f}"
        )

        print(
            f"Elite rating     : "
            f"{my_result['elite_score']:.2f}"
        )

        print(
            f"Composite rating : "
            f"{my_result['composite_rating']:.2f}"
        )

        print(
            f"Pace band        : "
            f"{my_result['pace_band']}"
        )

        print(
            f"Car code         : "
            f"{my_result['car_code']}"
        )

    else:

        print(
            "The PSN was not found even in the "
            "leaderboard returned by the update endpoint."
        )

    # ==================================================================================
    # THRESHOLDS
    # ==================================================================================

    thresholds = (
        build_thresholds(
            ranking
        )
    )

    percentiles = (
        build_percentiles(
            ranking
        )
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
        "100",
        "500",
        "1000",
        "2500",
        "5000",
        "10000",
    ]:

        item = thresholds.get(
            key
        )

        if not item:
            continue

        print(
            f"Top {key:<5}       : "
            f"{item['laptime']}"
        )

    print("")
    print(
        f"Top 10%          : "
        f"{percentiles['10']['laptime']} "
        f"(#{percentiles['10']['rank']:,})"
    )

    print(
        f"Top 5%           : "
        f"{percentiles['5']['laptime']} "
        f"(#{percentiles['5']['rank']:,})"
    )

    print(
        f"Top 2%           : "
        f"{percentiles['2']['laptime']} "
        f"(#{percentiles['2']['rank']:,})"
    )

    # ==================================================================================
    # META
    # ==================================================================================

    meta = build_car_meta(
        ranking
    )

    # ==================================================================================
    # SAVE RECOVERY
    # ==================================================================================

    recovery = {
        "recovery_version":
            VERSION,

        "recovered_at":
            datetime.now()
            .astimezone()
            .isoformat(),

        "race_week": {
            "start":
                HISTORICAL_WEEK_START,

            "end":
                HISTORICAL_WEEK_END,
        },

        "leaderboard_url":
            HISTORICAL_URL,

        "update_url":
            update_url,

        "source": {
            "initial_ranking_entries":
                len(
                    initial_ranking
                ),

            "update_endpoint_entries":
                len(
                    extract_ranking_from_json(
                        update_json
                    )
                    if update_json
                    is not None
                    else []
                ),

            "final_entries":
                len(
                    ranking
                ),

            "used_update_endpoint":
                bool(
                    update_json
                    is not None
                ),
        },

        "total_drivers":
            len(
                ranking
            ),

        "world_record": {
            "rank":
                1,

            "score":
                wr_score,

            "laptime":
                score_to_laptime(
                    wr_score
                ),

            "driver":
                get_driver_name(
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

        "thresholds":
            thresholds,

        "percentile_thresholds":
            percentiles,

        "my_result":
            my_result,

        "car_meta":
            meta,

        "health": {
            "my_driver_found":
                my_driver
                is not None,

            "leaderboard_entries":
                len(
                    ranking
                ),

            "initial_ranking_only":
                len(ranking)
                == len(
                    initial_ranking
                ),
        },
    }

    OUTPUT_FILE.write_text(
        json.dumps(
            recovery,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print("")
    print(
        SEPARATOR
    )

    print(
        f"Saved result     : "
        f"{OUTPUT_FILE}"
    )

    # ==================================================================================
    # ADD TO LONG-TERM WEEKLY HISTORY
    # ==================================================================================

    if my_result:

        weekly_record = (
            build_weekly_record(
                recovery
            )
        )

        if weekly_record:

            upsert_weekly_history(
                weekly_record
            )

            print(
                f"Weekly history   : "
                f"UPDATED"
            )

            print(
                f"History file     : "
                f"{WEEKLY_HISTORY_FILE}"
            )

    else:

        print(
            "Weekly history   : NOT UPDATED "
            "(personal result not recovered)"
        )

    print(
        SEPARATOR
    )


if __name__ == "__main__":

    main()