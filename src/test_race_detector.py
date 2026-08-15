import os
import requests
import json
import re
import math

from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from collections import Counter

from car_database import (
    load_car_database,
    update_car_database_from_html,
    get_car_name as database_get_car_name
)


# ============================================================
# CONFIG
# ============================================================

GTSH_URL = "https://gtsh-rank.com/daily/"
MY_PSN_ID = "crazy_rooster74"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (GT7 Daily Race Agent)"
}

REPORT_DIR = Path("reports")
DATA_DIR = Path("data")
HISTORY_DIR = DATA_DIR / "history"

LATEST_REPORT_FILE = REPORT_DIR / "latest.txt"
EMAIL_SUBJECT_FILE = REPORT_DIR / "email_subject.txt"
LATEST_SNAPSHOT_FILE = DATA_DIR / "latest_snapshot.json"
WEEKLY_HISTORY_FILE = DATA_DIR / "weekly_rating_history.json"

SAO_PAULO = ZoneInfo("America/Sao_Paulo")


# ============================================================
# CENTRAL CAR DATABASE
# ============================================================

CAR_DATABASE = load_car_database()


# ============================================================
# BRAKE BALANCE DATABASE
# ============================================================

BRAKE_INFO = {
    1563: {"layout": "MR", "qual_bb": 0, "race_bb": -1},
    2157: {"layout": "FR", "qual_bb": 1, "race_bb": 2},
    2161: {"layout": "4WD", "qual_bb": 2, "race_bb": 3},
    2163: {"layout": "FR", "qual_bb": 1, "race_bb": 2},
    2164: {"layout": "FR", "qual_bb": 1, "race_bb": 2},
    2166: {"layout": "MR", "qual_bb": 0, "race_bb": -1},
    3192: {"layout": "FR", "qual_bb": 1, "race_bb": 2},
    3231: {"layout": "FF", "qual_bb": 3, "race_bb": 4},
    3245: {"layout": "FR", "qual_bb": 1, "race_bb": 2},
    3246: {"layout": "4WD", "qual_bb": 2, "race_bb": 3},
    3247: {"layout": "FR", "qual_bb": 1, "race_bb": 2},
    3248: {"layout": "MR", "qual_bb": 0, "race_bb": -1},
    3249: {"layout": "FR", "qual_bb": 1, "race_bb": 2},
    3251: {"layout": "MR", "qual_bb": -1, "race_bb": -2},
    3252: {"layout": "FR", "qual_bb": 1, "race_bb": 2},
    3253: {"layout": "4WD", "qual_bb": 1, "race_bb": 2},
    3254: {"layout": "FR", "qual_bb": 1, "race_bb": 2},
    3256: {"layout": "4WD", "qual_bb": 2, "race_bb": 3},
    3257: {"layout": "MR", "qual_bb": -1, "race_bb": -2},
    3258: {"layout": "4WD", "qual_bb": 2, "race_bb": 3},
    3259: {"layout": "FF", "qual_bb": 3, "race_bb": 4},
    3260: {"layout": "FF", "qual_bb": 3, "race_bb": 4},
    3261: {"layout": "4WD", "qual_bb": 2, "race_bb": 3},
    3262: {"layout": "FR", "qual_bb": 1, "race_bb": 2},
    3263: {"layout": "MR", "qual_bb": -1, "race_bb": -2},
    3298: {"layout": "FF", "qual_bb": 3, "race_bb": 4},
    3310: {"layout": "MR", "qual_bb": -1, "race_bb": -2},
    3399: {"layout": "FR", "qual_bb": 1, "race_bb": 2},
    3477: {"layout": "FR", "qual_bb": 1, "race_bb": 2},
    3480: {"layout": "FF", "qual_bb": 3, "race_bb": 4},
    3501: {"layout": "FR", "qual_bb": 1, "race_bb": 2},
    3537: {"layout": "FF", "qual_bb": 3, "race_bb": 4}
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

    return f"{minutes}:{seconds:02d}.{milliseconds:03d}"


def laptime_to_score(text):
    if not text or text == "N/A":
        return None

    try:
        minutes, rest = text.split(":")
        seconds, milliseconds = rest.split(".")

        return (
            int(minutes) * 60000
            + int(seconds) * 1000
            + int(milliseconds)
        )

    except Exception:
        return None


def get_car_code(driver):
    return (
        driver
        .get("ranking_stats", {})
        .get("car_code")
    )


def get_car_name(car_code):
    return database_get_car_name(
        car_code,
        CAR_DATABASE
    )


def get_user(driver):
    return driver.get("user", {})


def find_my_driver(ranking, psn_id):
    target = psn_id.strip().lower()

    for driver in ranking:
        online_id = (
            get_user(driver)
            .get("np_online_id", "")
        )

        if (
            isinstance(online_id, str)
            and online_id.strip().lower() == target
        ):
            return driver

    return None


# ============================================================
# WEEK / DAILY RACE DETECTION
# ============================================================

def monday_of_week(dt):
    monday = dt - timedelta(days=dt.weekday())

    return monday.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )


def parse_race_date_from_text(text):
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


def find_current_race_c(soup, now):
    candidates = []

    for link in soup.select(
        'a[href*="/daily/leaderboard?event="], '
        'a[href*="/daily/leaderboard/?event="]'
    ):

        parent = link.parent

        if parent is None:
            continue

        parent_text = parent.get_text(
            " ",
            strip=True
        )

        if "Daily Race C" not in parent_text:
            continue

        href = link.get("href")

        if not href:
            continue

        candidates.append({
            "url": urljoin(GTSH_URL, href),
            "text": parent_text,
            "date": parse_race_date_from_text(parent_text),
            "running": "Running" in parent_text,
            "next_week": "Next Week" in parent_text
        })

    if not candidates:
        raise RuntimeError(
            "No Daily Race C candidates were found."
        )

    running_candidates = [
        c
        for c in candidates
        if c["running"]
    ]

    if running_candidates:
        running_candidates.sort(
            key=lambda c:
                c["date"]
                or datetime.min.replace(
                    tzinfo=SAO_PAULO
                ),
            reverse=True
        )

        selected = running_candidates[0]
        selected["detection_mode"] = "explicit_running"

        return selected

    current_monday = monday_of_week(now)

    current_week_candidates = [
        c
        for c in candidates
        if (
            c["date"]
            and c["date"].date()
            == current_monday.date()
        )
    ]

    if current_week_candidates:
        selected = current_week_candidates[0]
        selected["detection_mode"] = "current_week_date"

        return selected

    valid_past = [
        c
        for c in candidates
        if (
            c["date"]
            and c["date"] <= now
            and not c["next_week"]
        )
    ]

    if valid_past:
        valid_past.sort(
            key=lambda c: c["date"],
            reverse=True
        )

        selected = valid_past[0]
        selected["detection_mode"] = "latest_non_future"

        return selected

    raise RuntimeError(
        "Could not safely determine current Daily Race C."
    )


# ============================================================
# PERSONAL RATINGS
# ============================================================

def position_score(rank, total):
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


def elite_score(rank, total):
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


def composite_rating(general, elite):
    if general is None or elite is None:
        return None

    return (
        0.60 * general
        + 0.40 * elite
    )


def percentile_ahead(rank, total):
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


def pace_band(wr_percentage):
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


# ============================================================
# LONG-TERM WEEKLY HISTORY
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

        if isinstance(data, list):
            return data

    except Exception:
        pass

    return []


def save_weekly_history(history):
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


def weekly_record_exists(history, leaderboard_url):
    return any(
        record.get("leaderboard_url") == leaderboard_url
        for record in history
    )


def build_weekly_record(
    snapshot,
    finalization_mode
):
    my = snapshot.get("my_result")

    if not my:
        return None

    race = snapshot.get(
        "race",
        {}
    )

    start_date_text = race.get(
        "start_date"
    )

    if start_date_text:
        try:
            week_start = (
                datetime
                .fromisoformat(start_date_text)
                .date()
                .isoformat()
            )

        except Exception:
            week_start = None

    else:
        week_start = None

    general = my.get(
        "position_score"
    )

    elite = my.get(
        "elite_score"
    )

    return {
        "participated": True,

        "week_start":
            week_start,

        "final_snapshot":
            snapshot.get(
                "timestamp"
            ),

        "finalization_mode":
            finalization_mode,

        "race":
            race.get(
                "description"
            ),

        "leaderboard_url":
            race.get(
                "leaderboard_url"
            ),

        "general_score":
            general,

        "elite_score":
            elite,

        "composite_rating":
            composite_rating(
                general,
                elite
            ),

        "position":
            my.get(
                "rank"
            ),

        "total_drivers":
            snapshot.get(
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

        "car":
            my.get(
                "car"
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
            )
    }


def upsert_weekly_record(
    history,
    record
):
    if not record:
        return history

    url = record.get(
        "leaderboard_url"
    )

    replaced = False

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
            replaced = True
            break

    if not replaced:
        history.append(record)

    save_weekly_history(
        history
    )

    return history


def average_metric(
    history,
    key,
    count
):
    values = [
        record.get(key)
        for record in history[-count:]
        if isinstance(
            record.get(key),
            (int, float)
        )
    ]

    if not values:
        return None

    return (
        sum(values)
        / len(values)
    )


def metric_trend(
    history,
    key,
    count=8,
    higher_is_better=True
):
    records = [
        record
        for record in history[-count:]
        if isinstance(
            record.get(key),
            (int, float)
        )
    ]

    if len(records) < 3:
        return "Insufficient history"

    values = [
        record[key]
        for record in records
    ]

    xs = list(
        range(len(values))
    )

    x_mean = (
        sum(xs)
        / len(xs)
    )

    y_mean = (
        sum(values)
        / len(values)
    )

    denominator = sum(
        (x - x_mean) ** 2
        for x in xs
    )

    if denominator == 0:
        return "STABLE"

    slope = (
        sum(
            (x - x_mean)
            * (y - y_mean)
            for x, y
            in zip(xs, values)
        )
        / denominator
    )

    if not higher_is_better:
        slope = -slope

    if slope > 0.05:
        return "IMPROVING"

    if slope < -0.05:
        return "DECLINING"

    return "STABLE"


# ============================================================
# COMPARISON HELPERS
# ============================================================

def signed_seconds(delta_ms):
    if delta_ms is None:
        return "N/A"

    sign = "+" if delta_ms > 0 else ""

    return (
        f"{sign}"
        f"{delta_ms / 1000:.3f}s"
    )


def position_change(
    old_rank,
    new_rank
):
    if (
        old_rank is None
        or new_rank is None
    ):
        return "N/A"

    difference = (
        old_rank
        - new_rank
    )

    if difference > 0:
        return (
            f"+{difference} positions"
        )

    if difference < 0:
        return (
            f"{difference} positions"
        )

    return "unchanged"


# ============================================================
# RACE METADATA
# ============================================================

def extract_multiplier(
    race_text,
    label
):
    match = re.search(
        rf"{label}\s*x(\d+)",
        race_text,
        re.IGNORECASE
    )

    if match:
        return int(
            match.group(1)
        )

    return 1


def extract_compounds(
    race_text
):
    known = [
        "RH",
        "RM",
        "RS",
        "IM",
        "W",
        "SH",
        "SM",
        "SS",
        "CH",
        "CM",
        "CS"
    ]

    tokens = race_text.split()

    return [
        compound
        for compound in known
        if compound in tokens
    ]


def extract_start_date(
    race_text
):
    return parse_race_date_from_text(
        race_text
    )


# ============================================================
# BRAKE BALANCE
# ============================================================

def format_bb(value):
    if value > 0:
        return f"+{value}"

    return str(value)


def brake_balance_recommendation(
    car_code,
    tyre_multiplier
):
    info = BRAKE_INFO.get(
        car_code
    )

    if not info:
        return {
            "qualifying": 0,
            "race": 0,
            "layout": "Unknown",
            "confidence": "Low",
            "reason":
                (
                    "Car identified by the central database, "
                    "but no brake-balance baseline has been "
                    "defined yet."
                )
        }

    qualifying = info[
        "qual_bb"
    ]

    race = info[
        "race_bb"
    ]

    layout = info[
        "layout"
    ]

    if tyre_multiplier <= 1:
        race = qualifying

    elif tyre_multiplier <= 2:

        if race > qualifying:
            race = qualifying + 1

        elif race < qualifying:
            race = qualifying - 1

    reasons = {
        "FF":
            (
                "Rearward bias helps rotation "
                "and reduces front-axle braking load."
            ),

        "FR":
            (
                "Mild rearward bias improves rotation "
                "while retaining braking stability."
            ),

        "MR":
            (
                "Neutral/slightly forward bias "
                "prioritizes rear stability."
            ),

        "4WD":
            (
                "Moderate rearward bias helps rotation "
                "without making braking too unstable."
            )
    }

    return {
        "qualifying":
            qualifying,

        "race":
            race,

        "layout":
            layout,

        "confidence":
            "Medium",

        "reason":
            reasons.get(
                layout,
                "Neutral baseline."
            )
    }


# ============================================================
# SNAPSHOT / HISTORY
# ============================================================

def load_previous_snapshot():
    if not LATEST_SNAPSHOT_FILE.exists():
        return None

    try:
        return json.loads(
            LATEST_SNAPSHOT_FILE.read_text(
                encoding="utf-8"
            )
        )

    except Exception:
        return None


def load_history_for_race(
    leaderboard_url
):
    snapshots = []

    if not HISTORY_DIR.exists():
        return snapshots

    for path in sorted(
        HISTORY_DIR.glob(
            "*.json"
        )
    ):
        try:
            data = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )

            if (
                data
                .get(
                    "race",
                    {}
                )
                .get(
                    "leaderboard_url"
                )
                == leaderboard_url
            ):
                snapshots.append(
                    data
                )

        except Exception:
            pass

    return snapshots


def snapshot_metric_score(
    snapshot,
    metric
):
    if metric == "world_record":
        return (
            snapshot
            .get(
                "world_record",
                {}
            )
            .get(
                "score"
            )
        )

    if metric.startswith("top"):

        key = metric.replace(
            "top",
            ""
        )

        value = (
            snapshot
            .get(
                "thresholds",
                {}
            )
            .get(
                key
            )
        )

        if isinstance(value, dict):
            return value.get(
                "score"
            )

        if isinstance(value, int):
            return value

        if isinstance(value, str):
            return laptime_to_score(
                value
            )

    return None


# ============================================================
# FORECAST ENGINE
# ============================================================

def linear_forecast(
    history,
    current_snapshot,
    metric,
    target_time
):
    points = []

    combined = (
        list(history)
        + [current_snapshot]
    )

    seen = set()

    for snapshot in combined:

        timestamp = snapshot.get(
            "timestamp"
        )

        score = snapshot_metric_score(
            snapshot,
            metric
        )

        if (
            timestamp
            and isinstance(
                score,
                (int, float)
            )
        ):
            key = (
                timestamp,
                score
            )

            if key in seen:
                continue

            seen.add(key)

            try:
                dt = datetime.fromisoformat(
                    timestamp
                )

                points.append(
                    (
                        dt,
                        float(score)
                    )
                )

            except Exception:
                pass

    points.sort(
        key=lambda point:
            point[0]
    )

    if len(points) < 3:
        return None

    first_time = points[0][0]

    xs = [
        (
            point[0]
            - first_time
        ).total_seconds()
        / 3600
        for point in points
    ]

    ys = [
        point[1]
        for point in points
    ]

    span_hours = (
        max(xs)
        - min(xs)
    )

    if span_hours < 4:
        return None

    x_mean = (
        sum(xs)
        / len(xs)
    )

    y_mean = (
        sum(ys)
        / len(ys)
    )

    denominator = sum(
        (x - x_mean) ** 2
        for x in xs
    )

    if denominator == 0:
        return None

    slope = (
        sum(
            (x - x_mean)
            * (y - y_mean)
            for x, y
            in zip(
                xs,
                ys
            )
        )
        / denominator
    )

    slope = min(
        slope,
        0
    )

    target_x = (
        (
            target_time
            - first_time
        ).total_seconds()
        / 3600
    )

    predicted = (
        y_mean
        + slope
        * (
            target_x
            - x_mean
        )
    )

    current_score = ys[-1]

    predicted = min(
        predicted,
        current_score
    )

    residuals = [
        y
        - (
            y_mean
            + slope
            * (
                x
                - x_mean
            )
        )
        for x, y
        in zip(
            xs,
            ys
        )
    ]

    rmse = math.sqrt(
        sum(
            residual ** 2
            for residual
            in residuals
        )
        / len(residuals)
    )

    if (
        len(points) >= 6
        and span_hours >= 48
    ):
        confidence = "High"

    elif (
        len(points) >= 4
        and span_hours >= 24
    ):
        confidence = "Medium"

    else:
        confidence = "Low"

    return {
        "predicted_score":
            int(
                round(predicted)
            ),

        "rmse_ms":
            int(
                round(rmse)
            ),

        "confidence":
            confidence,

        "samples":
            len(points),

        "span_hours":
            span_hours
    }


# ============================================================
# TARGET ENGINE
# ============================================================

def target_rank_for_percent(
    total,
    top_percent
):
    return max(
        1,
        min(
            total,
            math.ceil(
                total
                * top_percent
                / 100
            )
        )
    )


def build_targets(
    ranking,
    my_rank,
    my_score
):
    if (
        my_rank is None
        or my_score is None
    ):
        return []

    total = len(ranking)

    definitions = [
        (
            "Top 50%",
            target_rank_for_percent(
                total,
                50
            )
        ),
        (
            "Top 25%",
            target_rank_for_percent(
                total,
                25
            )
        ),
        (
            "Top 10%",
            target_rank_for_percent(
                total,
                10
            )
        ),
        (
            "Top 5%",
            target_rank_for_percent(
                total,
                5
            )
        ),
        (
            "Top 2%",
            target_rank_for_percent(
                total,
                2
            )
        ),
        (
            "Top 1%",
            target_rank_for_percent(
                total,
                1
            )
        ),
        (
            "Top 0.5%",
            target_rank_for_percent(
                total,
                0.5
            )
        ),
        (
            "Top 1000",
            min(
                1000,
                total
            )
        ),
        (
            "Top 500",
            min(
                500,
                total
            )
        ),
        (
            "Top 100",
            min(
                100,
                total
            )
        ),
        (
            "Top 50",
            min(
                50,
                total
            )
        ),
        (
            "Top 10",
            min(
                10,
                total
            )
        )
    ]

    unique_targets = {}

    for label, rank in definitions:
        if rank < my_rank:
            unique_targets[rank] = label

    results = []

    for rank in sorted(
        unique_targets.keys(),
        reverse=True
    ):
        target_score = ranking[
            rank - 1
        ].get(
            "score"
        )

        if target_score is None:
            continue

        results.append({
            "label":
                unique_targets[rank],

            "rank":
                rank,

            "score":
                target_score,

            "laptime":
                score_to_laptime(
                    target_score
                ),

            "gain_needed_ms":
                max(
                    0,
                    my_score
                    - target_score
                )
        })

    return results[:4]


# ============================================================
# GROUP RANKINGS
# ============================================================

def group_rank(
    ranking,
    predicate,
    my_driver
):
    group = [
        driver
        for driver
        in ranking
        if predicate(driver)
    ]

    my_id = (
        get_user(
            my_driver
        )
        .get(
            "np_online_id",
            ""
        )
        .lower()
    )

    for index, driver in enumerate(
        group,
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

        if driver_id == my_id:
            return (
                index,
                len(group)
            )

    return (
        None,
        len(group)
    )


# ============================================================
# CAR OVERPERFORMANCE
# ============================================================

def car_performance_indices(
    ranking,
    all_counter,
    top100_counter,
    top1000_counter
):
    total = len(ranking)

    top100_total = min(
        100,
        total
    )

    top1000_total = min(
        1000,
        total
    )

    rows = []

    for car_code, all_count in all_counter.items():

        overall_share = (
            all_count
            / total
        )

        if overall_share <= 0:
            continue

        top100_count = top100_counter.get(
            car_code,
            0
        )

        top1000_count = top1000_counter.get(
            car_code,
            0
        )

        top100_share = (
            top100_count
            / top100_total
            if top100_total
            else 0
        )

        top1000_share = (
            top1000_count
            / top1000_total
            if top1000_total
            else 0
        )

        oi100 = (
            top100_share
            / overall_share
        )

        oi1000 = (
            top1000_share
            / overall_share
        )

        index = (
            oi100 * 0.70
            + oi1000 * 0.30
        )

        if (
            all_count >= 500
            and top1000_count >= 25
        ):
            confidence = "High"

        elif (
            all_count >= 100
            and top1000_count >= 10
        ):
            confidence = "Medium"

        else:
            confidence = "Low"

        rows.append({
            "car_code":
                car_code,

            "car":
                get_car_name(
                    car_code
                ),

            "all_count":
                all_count,

            "top100":
                top100_count,

            "top1000":
                top1000_count,

            "oi100":
                oi100,

            "oi1000":
                oi1000,

            "overperformance_index":
                index,

            "confidence":
                confidence
        })

    rows.sort(
        key=lambda item:
            item[
                "overperformance_index"
            ],
        reverse=True
    )

    return rows


# ============================================================
# BEST DRIVER BY CAR
# ============================================================

def best_driver_by_car(ranking):
    result = {}

    for driver in ranking:
        car_code = get_car_code(
            driver
        )

        if (
            car_code is not None
            and car_code not in result
        ):
            result[car_code] = driver

    return result


# ============================================================
# DATA QUALITY
# ============================================================

def anomaly_warnings(
    previous,
    current,
    unknown_share
):
    warnings = []

    if unknown_share > 5:
        warnings.append(
            f"Unknown car mapping represents "
            f"{unknown_share:.1f}% of leaderboard."
        )

    same_race = (
        previous
        and previous
        .get(
            "race",
            {}
        )
        .get(
            "leaderboard_url"
        )
        == current
        .get(
            "race",
            {}
        )
        .get(
            "leaderboard_url"
        )
    )

    if same_race:

        old_total = previous.get(
            "total_drivers"
        )

        new_total = current.get(
            "total_drivers"
        )

        if (
            old_total
            and new_total
            and new_total
            < old_total * 0.70
        ):
            warnings.append(
                "Driver count dropped by more than 30%."
            )

        old_wr = snapshot_metric_score(
            previous,
            "world_record"
        )

        new_wr = snapshot_metric_score(
            current,
            "world_record"
        )

        if (
            old_wr
            and new_wr
        ):
            if new_wr > old_wr + 500:
                warnings.append(
                    "World record became more than "
                    "0.500s slower."
                )

            if old_wr - new_wr > 2000:
                warnings.append(
                    "World record improved by more than "
                    "2.000s since previous snapshot."
                )

    return warnings


# ============================================================
# MAIN
# ============================================================

def main():

    global CAR_DATABASE

    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    HISTORY_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    session = requests.Session()

    session.headers.update(
        HEADERS
    )

    now = datetime.now(
        SAO_PAULO
    )

    timestamp_iso = now.isoformat()

    timestamp_display = now.strftime(
        "%d/%m/%Y %H:%M:%S"
    )

    history_filename = now.strftime(
        "%Y-%m-%d_%H-%M-%S.json"
    )

    report_filename = now.strftime(
        "%Y-%m-%d_%H-%M-%S.txt"
    )

    # ========================================================
    # DAILY RACE PAGE
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

    # ========================================================
    # CURRENT RACE C
    # ========================================================

    race_c = find_current_race_c(
        soup,
        now
    )

    race_c_link = race_c["url"]
    race_c_text = race_c["text"]
    race_detection_mode = race_c[
        "detection_mode"
    ]

    # ========================================================
    # LEADERBOARD
    # ========================================================

    leaderboard_response = session.get(
        race_c_link,
        timeout=60
    )

    leaderboard_response.raise_for_status()

    html = leaderboard_response.text

    # ========================================================
    # UPDATE CENTRAL CAR DATABASE
    # ========================================================

    try:
        car_update = (
            update_car_database_from_html(
                html
            )
        )

        CAR_DATABASE = car_update[
            "database"
        ]

        cars_discovered_this_run = car_update[
            "discovered"
        ]

        cars_added_this_run = car_update[
            "added"
        ]

        cars_updated_this_run = car_update[
            "updated"
        ]

    except Exception:

        CAR_DATABASE = (
            load_car_database()
        )

        cars_discovered_this_run = 0
        cars_added_this_run = 0
        cars_updated_this_run = 0

    # ========================================================
    # EXTRACT RANKING
    # ========================================================

    marker = (
        "const initialRanking = "
    )

    start = html.find(
        marker
    )

    ranking = None
    source_mode = "initialRanking"

    if start != -1:

        start += len(
            marker
        )

        decoder = json.JSONDecoder()

        ranking, _ = decoder.raw_decode(
            html[
                start:
            ].lstrip()
        )

    if not ranking:

        source_mode = "update_endpoint"

        update_url = (
            race_c_link
            + (
                "&update=1"
                if "?" in race_c_link
                else "?update=1"
            )
        )

        update_response = session.get(
            update_url,
            timeout=60
        )

        update_response.raise_for_status()

        update_data = (
            update_response.json()
        )

        if isinstance(
            update_data,
            list
        ):
            ranking = update_data

        elif isinstance(
            update_data,
            dict
        ):
            candidate = (
                update_data.get(
                    "board"
                )
                or update_data.get(
                    "ranking"
                )
            )

            if isinstance(
                candidate,
                list
            ):
                ranking = candidate

    if not ranking:
        raise RuntimeError(
            "Leaderboard contains no drivers."
        )

    ranking.sort(
        key=lambda driver:
            driver.get(
                "display_rank",
                999999999
            )
    )

    # ========================================================
    # WORLD RECORD
    # ========================================================

    winner = ranking[0]

    wr_score = winner.get(
        "score"
    )

    wr_user = get_user(
        winner
    )

    wr_car_code = get_car_code(
        winner
    )

    time_103 = round(
        wr_score * 1.03
    )

    time_105 = round(
        wr_score * 1.05
    )

    # ========================================================
    # RACE METADATA
    # ========================================================

    fuel_multiplier = extract_multiplier(
        race_c_text,
        "Fuel"
    )

    tyre_multiplier = extract_multiplier(
        race_c_text,
        "Tyres"
    )

    compounds = extract_compounds(
        race_c_text
    )

    start_date = extract_start_date(
        race_c_text
    )

    # ========================================================
    # THRESHOLDS
    # ========================================================

    threshold_positions = [
        1,
        10,
        50,
        100,
        250,
        500,
        1000,
        2500,
        5000,
        10000
    ]

    thresholds = {}

    for position in threshold_positions:

        if len(ranking) >= position:

            score = ranking[
                position - 1
            ].get(
                "score"
            )

            thresholds[
                str(position)
            ] = {
                "score":
                    score,

                "laptime":
                    score_to_laptime(
                        score
                    )
            }

    # ========================================================
    # MY RESULT
    # ========================================================

    my_driver = find_my_driver(
        ranking,
        MY_PSN_ID
    )

    my_result = None
    next_targets = []
    same_car_stats = None
    country_stats = None
    dr_stats = None

    if my_driver:

        my_score = my_driver.get(
            "score"
        )

        my_rank = my_driver.get(
            "display_rank"
        )

        my_car_code = get_car_code(
            my_driver
        )

        my_user = get_user(
            my_driver
        )

        my_country = my_user.get(
            "country_code"
        )

        my_dr = my_user.get(
            "driver_rating"
        )

        wr_percentage = (
            my_score
            / wr_score
            * 100
        )

        my_general_score = position_score(
            my_rank,
            len(ranking)
        )

        my_elite_score = elite_score(
            my_rank,
            len(ranking)
        )

        my_composite = composite_rating(
            my_general_score,
            my_elite_score
        )

        my_ahead = percentile_ahead(
            my_rank,
            len(ranking)
        )

        same_car_rank, same_car_total = group_rank(
            ranking,
            lambda driver:
                get_car_code(driver)
                == my_car_code,
            my_driver
        )

        country_rank, country_total = group_rank(
            ranking,
            lambda driver:
                get_user(driver).get(
                    "country_code"
                )
                == my_country,
            my_driver
        )

        dr_rank, dr_total = group_rank(
            ranking,
            lambda driver:
                get_user(driver).get(
                    "driver_rating"
                )
                == my_dr,
            my_driver
        )

        my_result = {
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

            "car":
                get_car_name(
                    my_car_code
                ),

            "country":
                my_country,

            "driver_rating":
                my_dr,

            "gap_to_wr_ms":
                my_score
                - wr_score,

            "wr_percentage":
                wr_percentage,

            "position_score":
                my_general_score,

            "elite_score":
                my_elite_score,

            "composite_rating":
                my_composite,

            "percentile_ahead":
                my_ahead,

            "top_percent":
                my_rank
                / len(ranking)
                * 100,

            "pace_band":
                pace_band(
                    wr_percentage
                )
        }

        same_car_stats = {
            "rank":
                same_car_rank,

            "total":
                same_car_total
        }

        country_stats = {
            "rank":
                country_rank,

            "total":
                country_total,

            "country":
                my_country
        }

        dr_stats = {
            "rank":
                dr_rank,

            "total":
                dr_total,

            "dr":
                my_dr
        }

        next_targets = build_targets(
            ranking,
            my_rank,
            my_score
        )

    # ========================================================
    # CAR COUNTERS
    # ========================================================

    all_counter = Counter(
        get_car_code(driver)
        for driver in ranking
        if get_car_code(driver)
        is not None
    )

    top100 = ranking[:100]
    top500 = ranking[:500]
    top1000 = ranking[:1000]

    top100_counter = Counter(
        get_car_code(driver)
        for driver in top100
        if get_car_code(driver)
        is not None
    )

    top500_counter = Counter(
        get_car_code(driver)
        for driver in top500
        if get_car_code(driver)
        is not None
    )

    top1000_counter = Counter(
        get_car_code(driver)
        for driver in top1000
        if get_car_code(driver)
        is not None
    )

    # ========================================================
    # TOP 5 CARS + BRAKE BALANCE
    # ========================================================

    top5_used_cars = []

    for car_code, count in (
        top1000_counter
        .most_common(5)
    ):

        bb = brake_balance_recommendation(
            car_code,
            tyre_multiplier
        )

        top5_used_cars.append({
            "car_code":
                car_code,

            "car":
                get_car_name(
                    car_code
                ),

            "count":
                count,

            "percentage":
                (
                    count
                    / len(top1000)
                    * 100
                ),

            "layout":
                bb["layout"],

            "qualifying_bb":
                bb["qualifying"],

            "race_bb":
                bb["race"],

            "confidence":
                bb["confidence"],

            "reason":
                bb["reason"]
        })

    # ========================================================
    # CAR OVERPERFORMANCE
    # ========================================================

    overperformance = car_performance_indices(
        ranking,
        all_counter,
        top100_counter,
        top1000_counter
    )

    credible_overperformance = [
        car
        for car in overperformance
        if car[
            "confidence"
        ] != "Low"
    ]

    if not credible_overperformance:
        credible_overperformance = (
            overperformance
        )

    # ========================================================
    # BEST DRIVER PER CAR
    # ========================================================

    best_by_car = best_driver_by_car(
        ranking
    )

    # ========================================================
    # MY CAR VS META
    # ========================================================

    car_comparison = None

    if my_result:

        my_code = my_result[
            "car_code"
        ]

        meta_code = (
            top1000_counter
            .most_common(1)[0][0]
            if top1000_counter
            else None
        )

        my_car_best = (
            best_by_car.get(
                my_code
            )
        )

        meta_car_best = (
            best_by_car.get(
                meta_code
            )
            if meta_code is not None
            else None
        )

        car_comparison = {
            "my_car":
                get_car_name(
                    my_code
                ),

            "my_car_best_score":
                (
                    my_car_best.get(
                        "score"
                    )
                    if my_car_best
                    else None
                ),

            "my_car_best_laptime":
                (
                    score_to_laptime(
                        my_car_best.get(
                            "score"
                        )
                    )
                    if my_car_best
                    else "N/A"
                ),

            "gap_to_best_same_car_ms":
                (
                    my_result["score"]
                    - my_car_best.get(
                        "score"
                    )
                    if my_car_best
                    else None
                ),

            "meta_car":
                (
                    get_car_name(
                        meta_code
                    )
                    if meta_code is not None
                    else "N/A"
                ),

            "meta_car_best_score":
                (
                    meta_car_best.get(
                        "score"
                    )
                    if meta_car_best
                    else None
                ),

            "meta_car_best_laptime":
                (
                    score_to_laptime(
                        meta_car_best.get(
                            "score"
                        )
                    )
                    if meta_car_best
                    else "N/A"
                ),

            "theoretical_car_gap_ms":
                (
                    my_car_best.get(
                        "score"
                    )
                    - meta_car_best.get(
                        "score"
                    )
                    if (
                        my_car_best
                        and meta_car_best
                    )
                    else None
                )
        }

    # ========================================================
    # PREVIOUS SNAPSHOT
    # ========================================================

    previous = load_previous_snapshot()

    # ========================================================
    # HEALTH / CAR DATABASE COVERAGE
    # ========================================================

    unknown_count = sum(
        count
        for car_code, count
        in all_counter.items()
        if (
            isinstance(
                car_code,
                int
            )
            and car_code > 0
            and car_code
            not in CAR_DATABASE
        )
    )

    invalid_car_code_count = sum(
        count
        for car_code, count
        in all_counter.items()
        if (
            car_code is None
            or not isinstance(
                car_code,
                int
            )
            or car_code <= 0
        )
    )

    valid_car_code_entries = (
        len(ranking)
        - invalid_car_code_count
    )

    unknown_share = (
        unknown_count
        / valid_car_code_entries
        * 100
        if valid_car_code_entries > 0
        else 0
    )

    # ========================================================
    # SNAPSHOT
    # ========================================================

    snapshot = {
        "timestamp":
            timestamp_iso,

        "race": {
            "description":
                race_c_text,

            "leaderboard_url":
                race_c_link,

            "detection_mode":
                race_detection_mode,

            "source_mode":
                source_mode,

            "fuel_multiplier":
                fuel_multiplier,

            "tyre_multiplier":
                tyre_multiplier,

            "compounds":
                compounds,

            "start_date":
                (
                    start_date.isoformat()
                    if start_date
                    else None
                )
        },

        "total_drivers":
            len(ranking),

        "world_record": {
            "score":
                wr_score,

            "laptime":
                score_to_laptime(
                    wr_score
                ),

            "driver":
                wr_user.get(
                    "nick_name",
                    "Unknown"
                ),

            "psn_id":
                wr_user.get(
                    "np_online_id"
                ),

            "car_code":
                wr_car_code,

            "car":
                get_car_name(
                    wr_car_code
                )
        },

        "benchmarks": {
            "103_percent": {
                "score":
                    time_103,

                "laptime":
                    score_to_laptime(
                        time_103
                    )
            },

            "105_percent": {
                "score":
                    time_105,

                "laptime":
                    score_to_laptime(
                        time_105
                    )
            }
        },

        "thresholds":
            thresholds,

        "my_result":
            my_result,

        "same_car_stats":
            same_car_stats,

        "country_stats":
            country_stats,

        "dr_stats":
            dr_stats,

        "next_targets":
            next_targets,

        "top5_used_cars":
            top5_used_cars,

        "overperformance":
            credible_overperformance[:10],

        "car_comparison":
            car_comparison,

        "car_database": {
            "total_known_cars":
                len(
                    CAR_DATABASE
                ),

            "discovered_this_run":
                cars_discovered_this_run,

            "added_this_run":
                cars_added_this_run,

            "updated_this_run":
                cars_updated_this_run
        },

        "health": {
            "unknown_car_share":
                unknown_share,

            "unknown_car_entries":
                unknown_count,

            "invalid_car_code_entries":
                invalid_car_code_count,

            "source_mode":
                source_mode,

            "race_detection_mode":
                race_detection_mode,

            "leaderboard_entries":
                len(ranking),

            "my_driver_found":
                my_driver
                is not None
        }
    }

    # ========================================================
    # ANOMALY DETECTION
    # ========================================================

    warnings = anomaly_warnings(
        previous,
        snapshot,
        unknown_share
    )

    snapshot[
        "health"
    ][
        "warnings"
    ] = warnings

    # ========================================================
    # WEEKLY FINALIZATION
    # ========================================================

    weekly_history = load_weekly_history()

    if previous:

        previous_url = (
            previous
            .get(
                "race",
                {}
            )
            .get(
                "leaderboard_url"
            )
        )

        if (
            previous_url
            and previous_url
            != race_c_link
            and not weekly_record_exists(
                weekly_history,
                previous_url
            )
        ):
            fallback_record = build_weekly_record(
                previous,
                "backfill_last_available_snapshot"
            )

            weekly_history = upsert_weekly_record(
                weekly_history,
                fallback_record
            )

    force_final = (
        os.environ.get(
            "FINAL_WEEKLY_SNAPSHOT",
            "0"
        )
        == "1"
    )

    sunday_late = (
        now.weekday() == 6
        and now.hour >= 23
    )

    weekly_finalized_now = (
        force_final
        or sunday_late
    )

    if weekly_finalized_now:

        final_record = build_weekly_record(
            snapshot,
            "sunday_final"
        )

        weekly_history = upsert_weekly_record(
            weekly_history,
            final_record
        )

    # ========================================================
    # FORECAST
    # ========================================================

    history = load_history_for_race(
        race_c_link
    )

    forecasts = {}

    if start_date:

        sunday_end = (
            start_date
            + timedelta(days=6)
        ).replace(
            hour=23,
            minute=59,
            second=0
        )

        if sunday_end > now:

            for metric in [
                "world_record",
                "top500",
                "top1000"
            ]:

                forecast = linear_forecast(
                    history,
                    snapshot,
                    metric,
                    sunday_end
                )

                if forecast:
                    forecasts[
                        metric
                    ] = forecast

            snapshot[
                "forecast_target"
            ] = sunday_end.isoformat()

    snapshot[
        "forecasts"
    ] = forecasts

    # ========================================================
    # SAME RACE?
    # ========================================================

    same_race = (
        previous is not None
        and previous
        .get(
            "race",
            {}
        )
        .get(
            "leaderboard_url"
        )
        == race_c_link
    )

    # ========================================================
    # BUILD REPORT
    # ========================================================

    lines = []

    lines.append(
        "GT7 DAILY RACE C"
    )

    lines.append(
        "=" * 78
    )

    lines.append(
        f"Snapshot: "
        f"{timestamp_display} - Sao Paulo"
    )

    lines.append(
        race_c_text
    )

    lines.append(
        f"Race detection: "
        f"{race_detection_mode}"
    )

    lines.append(
        f"Total drivers: "
        f"{len(ranking):,}"
    )

    # ========================================================
    # WHERE YOU ARE
    # ========================================================

    lines.append("")
    lines.append(
        "WHERE YOU ARE"
    )

    if my_result:

        lines.append(
            f"PSN             : "
            f"{MY_PSN_ID}"
        )

        lines.append(
            f"Position        : "
            f"#{my_result['rank']:,} "
            f"of {len(ranking):,}"
        )

        lines.append(
            f"Time            : "
            f"{my_result['laptime']}"
        )

        lines.append(
            f"Car             : "
            f"{my_result['car']}"
        )

        lines.append(
            f"Gap to WR       : "
            f"+{my_result['gap_to_wr_ms']/1000:.3f}s"
        )

        lines.append(
            f"WR percentage   : "
            f"{my_result['wr_percentage']:.3f}%"
        )

        lines.append(
            f"Pace class      : "
            f"{my_result['pace_band']}"
        )

        lines.append(
            f"General rating  : "
            f"{my_result['position_score']:.2f} / 10"
        )

        lines.append(
            f"Elite rating    : "
            f"{my_result['elite_score']:.2f} / 10"
        )

        lines.append(
            f"Composite       : "
            f"{my_result['composite_rating']:.2f} / 10"
        )

        lines.append(
            f"Top percentile  : "
            f"Top {my_result['top_percent']:.2f}%"
        )

        lines.append(
            f"Ahead of        : "
            f"{my_result['percentile_ahead']:.2f}% "
            f"of participants"
        )

        if (
            country_stats
            and country_stats["rank"]
        ):
            lines.append(
                f"Country rank    : "
                f"#{country_stats['rank']:,} "
                f"of {country_stats['total']:,} "
                f"({country_stats['country']})"
            )

        if (
            dr_stats
            and dr_stats["rank"]
        ):
            lines.append(
                f"DR rank         : "
                f"#{dr_stats['rank']:,} "
                f"of {dr_stats['total']:,} "
                f"(DR {dr_stats['dr']})"
            )

        if (
            same_car_stats
            and same_car_stats["rank"]
        ):
            lines.append(
                f"Same-car rank   : "
                f"#{same_car_stats['rank']:,} "
                f"of {same_car_stats['total']:,}"
            )

    else:

        lines.append(
            f"{MY_PSN_ID} "
            f"not found in leaderboard."
        )

    # ========================================================
    # WORLD RECORD
    # ========================================================

    lines.append("")
    lines.append(
        "WORLD RECORD & BENCHMARKS"
    )

    lines.append(
        f"WR              : "
        f"{score_to_laptime(wr_score)} | "
        f"{wr_user.get('nick_name','Unknown')} | "
        f"{get_car_name(wr_car_code)}"
    )

    lines.append(
        f"103% WR         : "
        f"{score_to_laptime(time_103)}"
    )

    lines.append(
        f"105% WR         : "
        f"{score_to_laptime(time_105)}"
    )

    for key in [
        "10",
        "100",
        "500",
        "1000",
        "2500",
        "5000"
    ]:

        if key in thresholds:

            lines.append(
                f"Top {key:<4}        : "
                f"{thresholds[key]['laptime']}"
            )

    # ========================================================
    # TARGETS
    # ========================================================

    lines.append("")
    lines.append(
        "WHERE YOU SHOULD AIM"
    )

    if next_targets:

        for index, target in enumerate(
            next_targets,
            start=1
        ):

            lines.append(
                f"{index}. "
                f"{target['label']}: "
                f"#{target['rank']:,} | "
                f"{target['laptime']} | "
                f"gain needed "
                f"{target['gain_needed_ms']/1000:.3f}s"
            )

    else:

        lines.append(
            "No higher automatic target available."
        )

    # ========================================================
    # MY CAR VS META
    # ========================================================

    lines.append("")
    lines.append(
        "YOUR CAR VS META"
    )

    if car_comparison:

        lines.append(
            f"Your car best   : "
            f"{car_comparison['my_car_best_laptime']} | "
            f"{car_comparison['my_car']}"
        )

        if (
            car_comparison[
                "gap_to_best_same_car_ms"
            ]
            is not None
        ):
            lines.append(
                f"Gap to car best : "
                f"+{car_comparison['gap_to_best_same_car_ms']/1000:.3f}s"
            )

        lines.append(
            f"Meta car best   : "
            f"{car_comparison['meta_car_best_laptime']} | "
            f"{car_comparison['meta_car']}"
        )

        if (
            car_comparison[
                "theoretical_car_gap_ms"
            ]
            is not None
        ):
            lines.append(
                f"Best-lap delta  : "
                f"{signed_seconds(car_comparison['theoretical_car_gap_ms'])}"
            )

    else:

        lines.append(
            "No personal car comparison available."
        )

    # ========================================================
    # META
    # ========================================================

    lines.append("")
    lines.append(
        "WHAT THE META IS - TOP 5 USED IN TOP 1000"
    )

    for index, car in enumerate(
        top5_used_cars,
        start=1
    ):

        lines.append(
            f"{index}. "
            f"{car['car']} | "
            f"{car['count']} drivers | "
            f"{car['percentage']:.1f}%"
        )

    lines.append("")
    lines.append(
        "CAR OVERPERFORMANCE INDEX"
    )

    lines.append(
        "Index > 1.00 = overrepresented "
        "among the fastest drivers."
    )

    for index, car in enumerate(
        credible_overperformance[:5],
        start=1
    ):

        lines.append(
            f"{index}. "
            f"{car['car']} | "
            f"OI {car['overperformance_index']:.2f} | "
            f"Top100 {car['top100']} | "
            f"Top1000 {car['top1000']} | "
            f"{car['confidence']}"
        )

    # ========================================================
    # BRAKE BALANCE
    # ========================================================

    lines.append("")
    lines.append(
        "BRAKE BALANCE - TOP 5 USED CARS"
    )

    lines.append(
        "Convention: negative = more front, "
        "positive = more rear."
    )

    lines.append(
        "Baseline recommendations, "
        "not telemetry-proven optimums."
    )

    for index, car in enumerate(
        top5_used_cars,
        start=1
    ):

        lines.append(
            f"{index}. "
            f"{car['car']} | "
            f"Quali BB "
            f"{format_bb(car['qualifying_bb'])} | "
            f"Race BB "
            f"{format_bb(car['race_bb'])} | "
            f"{car['layout']} | "
            f"{car['confidence']}"
        )

    # ========================================================
    # STRATEGY
    # ========================================================

    lines.append("")
    lines.append(
        "RACE STRATEGY FLAGS"
    )

    lines.append(
        f"Fuel multiplier: "
        f"x{fuel_multiplier}"
    )

    lines.append(
        f"Tyre multiplier: "
        f"x{tyre_multiplier}"
    )

    lines.append(
        f"Compounds detected: "
        f"{', '.join(compounds) if compounds else 'Not detected'}"
    )

    if tyre_multiplier >= 4:

        lines.append(
            "Tyre wear is high: prioritize "
            "consistency and axle protection."
        )

    elif tyre_multiplier >= 2:

        lines.append(
            "Tyre wear is meaningful: "
            "race balance may need tyre management."
        )

    else:

        lines.append(
            "Tyre wear is low: quali and race "
            "BB can remain relatively close."
        )

    if fuel_multiplier >= 4:

        lines.append(
            "Fuel consumption is high: "
            "short-shifting/fuel saving may matter."
        )

    elif fuel_multiplier >= 2:

        lines.append(
            "Fuel consumption may influence race pace."
        )

    else:

        lines.append(
            "Fuel multiplier is low."
        )

    # ========================================================
    # FORECAST
    # ========================================================

    lines.append("")
    lines.append(
        "FORECAST TO SUNDAY"
    )

    if forecasts:

        forecast_labels = {
            "world_record":
                "World Record",
            "top500":
                "Top 500",
            "top1000":
                "Top 1000"
        }

        for metric in [
            "world_record",
            "top500",
            "top1000"
        ]:

            forecast = forecasts.get(
                metric
            )

            if forecast:

                lines.append(
                    f"{forecast_labels[metric]:<12}: "
                    f"{score_to_laptime(forecast['predicted_score'])} "
                    f"±{forecast['rmse_ms']/1000:.3f}s | "
                    f"{forecast['confidence']} confidence | "
                    f"{forecast['samples']} samples"
                )

    else:

        lines.append(
            "Not enough same-week history yet."
        )

    # ========================================================
    # LONG-TERM WEEKLY RATING HISTORY
    # ========================================================

    lines.append("")
    lines.append(
        "LONG-TERM RATING TREND"
    )

    lines.append(
        "Only FINAL Sunday ratings are used "
        "for week-to-week comparisons."
    )

    if weekly_finalized_now:

        lines.append(
            "Current race status: FINAL"
        )

    else:

        lines.append(
            "Current race status: PROVISIONAL"
        )

    if my_result:

        lines.append(
            f"Current provisional General : "
            f"{my_result['position_score']:.2f}"
        )

        lines.append(
            f"Current provisional Elite   : "
            f"{my_result['elite_score']:.2f}"
        )

        lines.append(
            f"Current provisional Composite: "
            f"{my_result['composite_rating']:.2f}"
        )

    if weekly_history:

        latest_final = weekly_history[-1]

        lines.append("")
        lines.append(
            "LATEST FINALIZED WEEK"
        )

        lines.append(
            f"Week       : "
            f"{latest_final.get('week_start','N/A')}"
        )

        lines.append(
            f"General    : "
            f"{latest_final.get('general_score',0):.2f}"
        )

        lines.append(
            f"Elite      : "
            f"{latest_final.get('elite_score',0):.2f}"
        )

        lines.append(
            f"Composite  : "
            f"{latest_final.get('composite_rating',0):.2f}"
        )

        lines.append(
            f"Top %      : "
            f"{latest_final.get('top_percent',0):.2f}%"
        )

        lines.append(
            f"WR %       : "
            f"{latest_final.get('wr_percentage',0):.3f}%"
        )

        if len(weekly_history) >= 2:

            previous_final = (
                weekly_history[-2]
            )

            general_change = (
                latest_final[
                    "general_score"
                ]
                - previous_final[
                    "general_score"
                ]
            )

            elite_change = (
                latest_final[
                    "elite_score"
                ]
                - previous_final[
                    "elite_score"
                ]
            )

            composite_change = (
                latest_final[
                    "composite_rating"
                ]
                - previous_final[
                    "composite_rating"
                ]
            )

            lines.append("")
            lines.append(
                "CHANGE VS PREVIOUS FINAL WEEK"
            )

            lines.append(
                f"General    : "
                f"{general_change:+.2f}"
            )

            lines.append(
                f"Elite      : "
                f"{elite_change:+.2f}"
            )

            lines.append(
                f"Composite  : "
                f"{composite_change:+.2f}"
            )

        avg4_general = average_metric(
            weekly_history,
            "general_score",
            4
        )

        avg4_elite = average_metric(
            weekly_history,
            "elite_score",
            4
        )

        avg4_composite = average_metric(
            weekly_history,
            "composite_rating",
            4
        )

        if avg4_general is not None:

            lines.append("")
            lines.append(
                "4-WEEK MOVING AVERAGE"
            )

            lines.append(
                f"General    : "
                f"{avg4_general:.2f}"
            )

            lines.append(
                f"Elite      : "
                f"{avg4_elite:.2f}"
            )

            lines.append(
                f"Composite  : "
                f"{avg4_composite:.2f}"
            )

        lines.append("")
        lines.append(
            "8-WEEK TREND"
        )

        lines.append(
            f"General    : "
            f"{metric_trend(weekly_history, 'general_score')}"
        )

        lines.append(
            f"Elite      : "
            f"{metric_trend(weekly_history, 'elite_score')}"
        )

        lines.append(
            f"Composite  : "
            f"{metric_trend(weekly_history, 'composite_rating')}"
        )

        lines.append(
            f"WR %       : "
            f"{metric_trend(weekly_history, 'wr_percentage', higher_is_better=False)}"
        )

        lines.append("")
        lines.append(
            "LAST FINALIZED RACES"
        )

        for record in weekly_history[-8:]:

            lines.append(
                f"{record.get('week_start','N/A')} | "
                f"Gen {record.get('general_score',0):.2f} | "
                f"Elite {record.get('elite_score',0):.2f} | "
                f"Comp {record.get('composite_rating',0):.2f} | "
                f"Top {record.get('top_percent',0):.2f}% | "
                f"WR {record.get('wr_percentage',0):.3f}%"
            )

    else:

        lines.append(
            "No finalized weekly races recorded yet."
        )

    # ========================================================
    # WHAT CHANGED
    # ========================================================

    lines.append("")
    lines.append(
        "WHAT CHANGED SINCE PREVIOUS SNAPSHOT"
    )

    if same_race:

        old_wr = snapshot_metric_score(
            previous,
            "world_record"
        )

        lines.append(
            f"World Record   : "
            f"{signed_seconds(wr_score - old_wr) if old_wr else 'N/A'}"
        )

        old_top500 = snapshot_metric_score(
            previous,
            "top500"
        )

        new_top500 = (
            thresholds
            .get(
                "500",
                {}
            )
            .get(
                "score"
            )
        )

        if (
            old_top500
            and new_top500
        ):
            lines.append(
                f"Top 500        : "
                f"{signed_seconds(new_top500 - old_top500)}"
            )

        old_my = previous.get(
            "my_result"
        )

        if (
            old_my
            and my_result
        ):

            lines.append(
                f"My position    : "
                f"#{old_my['rank']:,} -> "
                f"#{my_result['rank']:,} "
                f"({position_change(old_my['rank'], my_result['rank'])})"
            )

            lines.append(
                f"My time        : "
                f"{signed_seconds(my_result['score'] - old_my['score'])}"
            )

            old_general = old_my.get(
                "position_score"
            )

            if old_general is not None:

                delta = (
                    my_result[
                        "position_score"
                    ]
                    - old_general
                )

                lines.append(
                    f"General rating : "
                    f"{old_general:.2f} -> "
                    f"{my_result['position_score']:.2f} "
                    f"({delta:+.2f})"
                )

            old_elite = old_my.get(
                "elite_score"
            )

            if old_elite is not None:

                delta = (
                    my_result[
                        "elite_score"
                    ]
                    - old_elite
                )

                lines.append(
                    f"Elite rating   : "
                    f"{old_elite:.2f} -> "
                    f"{my_result['elite_score']:.2f} "
                    f"({delta:+.2f})"
                )

    else:

        lines.append(
            "First snapshot of this Daily Race C."
        )

    # ========================================================
    # HEALTH
    # ========================================================

    lines.append("")
    lines.append(
        "DATA QUALITY / HEALTH"
    )

    lines.append(
        f"Race detector  : "
        f"{race_detection_mode}"
    )

    lines.append(
        f"Primary source : "
        f"GTSH-Rank ({source_mode})"
    )

    lines.append(
        f"Entries        : "
        f"{len(ranking):,}"
    )

    lines.append(
        f"Car database   : "
        f"{len(CAR_DATABASE):,} known cars"
    )

    lines.append(
        f"Car mapping    : "
        f"{100 - unknown_share:.2f}% recognized"
    )

    lines.append(
        f"Unknown codes  : "
        f"{unknown_count:,} valid unmapped entries"
    )

    lines.append(
        f"Invalid codes  : "
        f"{invalid_car_code_count:,} entries"
    )

    lines.append(
        f"My PSN found   : "
        f"{'Yes' if my_driver else 'No'}"
    )

    lines.append(
        f"Weekly final   : "
        f"{'YES' if weekly_finalized_now else 'No'}"
    )

    if cars_discovered_this_run:

        lines.append(
            f"GTSH car scan  : "
            f"{cars_discovered_this_run} discovered | "
            f"{cars_added_this_run} new | "
            f"{cars_updated_this_run} updated"
        )

    if warnings:

        for warning in warnings:

            lines.append(
                f"WARNING        : "
                f"{warning}"
            )

    else:

        lines.append(
            "Status         : OK"
        )

    lines.append("")
    lines.append(
        "=" * 78
    )

    report_text = "\n".join(
        lines
    )

    # ========================================================
    # SAVE REPORTS
    # ========================================================

    LATEST_REPORT_FILE.write_text(
        report_text,
        encoding="utf-8"
    )

    dated_report = (
        REPORT_DIR
        / report_filename
    )

    dated_report.write_text(
        report_text,
        encoding="utf-8"
    )

    # ========================================================
    # SMART EMAIL SUBJECT
    # ========================================================

    if weekly_finalized_now:
        subject = (
            "GT7 Race C FINAL"
        )

    else:
        subject = (
            "GT7 Race C"
        )

    if my_result:

        subject += (
            f" | #{my_result['rank']:,}"
            f" | G {my_result['position_score']:.2f}"
            f" | E {my_result['elite_score']:.2f}"
            f" | Top {my_result['top_percent']:.1f}%"
        )

    EMAIL_SUBJECT_FILE.write_text(
        subject,
        encoding="utf-8"
    )

    # ========================================================
    # SAVE SNAPSHOT
    # ========================================================

    snapshot_json = json.dumps(
        snapshot,
        ensure_ascii=False,
        indent=2
    )

    LATEST_SNAPSHOT_FILE.write_text(
        snapshot_json,
        encoding="utf-8"
    )

    history_file = (
        HISTORY_DIR
        / history_filename
    )

    history_file.write_text(
        snapshot_json,
        encoding="utf-8"
    )

    print(
        report_text
    )


if __name__ == "__main__":
    main()