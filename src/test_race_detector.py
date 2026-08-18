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
    get_car_name as database_get_car_name,
    load_car_technical_database,
    get_car_layout
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

CAR_TECHNICAL_DATABASE = (
    load_car_technical_database()
)


# ============================================================
# BRAKE BIAS V2
# ============================================================

BRAKE_BIAS_BASELINES = {

    "FF": {
        "qualifying": (1, 2),
        "race": (2, 3),
        "reason":
            (
                "FF cars place substantial braking and cornering "
                "load on the front axle. A modest rearward bias "
                "can aid rotation and reduce front tyre stress."
            )
    },

    "FR": {
        "qualifying": (0, 1),
        "race": (1, 2),
        "reason":
            (
                "FR cars generally tolerate a mild rearward "
                "bias while retaining predictable braking stability."
            )
    },

    "MR": {
        "qualifying": (-1, 0),
        "race": (-1, 0),
        "reason":
            (
                "MR cars can become sensitive to rear instability "
                "under braking. A neutral to slightly forward bias "
                "is a conservative starting point."
            )
    },

    "4WD": {
        "qualifying": (1, 2),
        "race": (2, 3),
        "reason":
            (
                "4WD cars generally tolerate a modest rearward bias, "
                "helping rotation while retaining strong braking stability."
            )
    },

    "RR": {
        "qualifying": (-1, 0),
        "race": (-2, -1),
        "reason":
            (
                "RR cars carry substantial rear mass and may benefit "
                "from a modestly forward brake bias to protect rear stability."
            )
    }
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

    return driver.get(
        "user",
        {}
    )


def find_my_driver(
    ranking,
    psn_id
):

    target = psn_id.strip().lower()

    for driver in ranking:

        online_id = (
            get_user(driver)
            .get(
                "np_online_id",
                ""
            )
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

    monday = (
        dt
        - timedelta(
            days=dt.weekday()
        )
    )

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


def race_letters_in_text(text):

    if not isinstance(text, str):
        return set()

    matches = re.findall(
        r"\bDaily\s+Race\s+([ABC])\b",
        text,
        flags=re.IGNORECASE
    )

    return {
        item.upper()
        for item in matches
    }


def extract_local_race_block(link):

    """
    Find the smallest local DOM block around a leaderboard link
    that clearly refers to exactly ONE Daily Race.

    This prevents a parent/container containing Race A + B + C
    from being misclassified as Race C.
    """

    node = link

    best = None

    for depth in range(8):

        if node is None:
            break

        try:

            text = node.get_text(
                " ",
                strip=True
            )

        except Exception:

            text = ""

        text = re.sub(
            r"\s+",
            " ",
            text
        ).strip()

        if text:

            letters = race_letters_in_text(
                text
            )

            if len(letters) == 1:

                letter = next(
                    iter(letters)
                )

                candidate = {
                    "text": text,
                    "letter": letter,
                    "depth": depth
                }

                if best is None:

                    best = candidate

                else:

                    # Prefer the smaller/closer block.
                    if (
                        len(text)
                        < len(best["text"])
                    ):

                        best = candidate

        node = node.parent

    return best


def validate_selected_race_c(
    candidate
):

    if not isinstance(
        candidate,
        dict
    ):

        raise RuntimeError(
            "Race C safety validation failed: invalid candidate."
        )

    text = candidate.get(
        "text",
        ""
    )

    letters = race_letters_in_text(
        text
    )

    if letters != {"C"}:

        raise RuntimeError(
            "Race C safety validation failed. "
            f"Detected Daily Race letters: {sorted(letters)}. "
            "Expected only Daily Race C."
        )

    if not re.search(
        r"\bDaily\s+Race\s+C\b",
        text,
        flags=re.IGNORECASE
    ):

        raise RuntimeError(
            "Race C safety validation failed: "
            "the selected block does not explicitly contain Daily Race C."
        )

    if re.search(
        r"\bDaily\s+Race\s+[AB]\b",
        text,
        flags=re.IGNORECASE
    ):

        raise RuntimeError(
            "Race C safety validation failed: "
            "the selected block also contains Race A or Race B."
        )

    return True


def find_current_race_c(
    soup,
    now
):

    candidates = []

    seen_urls = set()

    links = soup.select(
        'a[href*="/daily/leaderboard?event="], '
        'a[href*="/daily/leaderboard/?event="]'
    )

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

        if full_url in seen_urls:
            continue

        local_block = extract_local_race_block(
            link
        )

        if not local_block:
            continue

        if local_block[
            "letter"
        ] != "C":
            continue

        block_text = local_block[
            "text"
        ]

        # Important additional safety rule:
        # local block must contain only Race C.

        letters = race_letters_in_text(
            block_text
        )

        if letters != {"C"}:
            continue

        race_date = (
            parse_race_date_from_text(
                block_text
            )
        )

        running = bool(
            re.search(
                r"\bRunning\b",
                block_text,
                flags=re.IGNORECASE
            )
        )

        next_week = bool(
            re.search(
                r"\bNext\s+Week\b",
                block_text,
                flags=re.IGNORECASE
            )
        )

        candidates.append(
            {
                "url":
                    full_url,

                "text":
                    block_text,

                "date":
                    race_date,

                "running":
                    running,

                "next_week":
                    next_week,

                "local_depth":
                    local_block[
                        "depth"
                    ]
            }
        )

        seen_urls.add(
            full_url
        )

    if not candidates:

        raise RuntimeError(
            "No unambiguous Daily Race C candidates were found."
        )

    # ========================================================
    # 1. Prefer explicit RUNNING Race C
    # ========================================================

    running_candidates = [
        candidate
        for candidate in candidates
        if (
            candidate[
                "running"
            ]
            and not candidate[
                "next_week"
            ]
        )
    ]

    if running_candidates:

        running_candidates.sort(
            key=lambda candidate:
                (
                    candidate[
                        "date"
                    ]
                    or datetime.min.replace(
                        tzinfo=SAO_PAULO
                    ),
                    -candidate.get(
                        "local_depth",
                        999
                    )
                ),
            reverse=True
        )

        selected = (
            running_candidates[
                0
            ]
        )

        selected[
            "detection_mode"
        ] = "explicit_running_local_block"

        validate_selected_race_c(
            selected
        )

        return selected

    # ========================================================
    # 2. Current week date
    # ========================================================

    current_monday = monday_of_week(
        now
    )

    current_week_candidates = [
        candidate
        for candidate in candidates
        if (
            candidate[
                "date"
            ]
            and candidate[
                "date"
            ].date()
            == current_monday.date()
            and not candidate[
                "next_week"
            ]
        )
    ]

    if current_week_candidates:

        current_week_candidates.sort(
            key=lambda candidate:
                candidate.get(
                    "local_depth",
                    999
                )
        )

        selected = (
            current_week_candidates[
                0
            ]
        )

        selected[
            "detection_mode"
        ] = "current_week_local_block"

        validate_selected_race_c(
            selected
        )

        return selected

    # ========================================================
    # 3. Latest non-future Race C
    # ========================================================

    valid_past = [
        candidate
        for candidate in candidates
        if (
            candidate[
                "date"
            ]
            and candidate[
                "date"
            ] <= now
            and not candidate[
                "next_week"
            ]
        )
    ]

    if valid_past:

        valid_past.sort(
            key=lambda candidate:
                candidate[
                    "date"
                ],
            reverse=True
        )

        selected = (
            valid_past[
                0
            ]
        )

        selected[
            "detection_mode"
        ] = "latest_non_future_local_block"

        validate_selected_race_c(
            selected
        )

        return selected

    raise RuntimeError(
        "Could not safely determine the current Daily Race C."
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
        min(
            10.0,
            result
        )
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
        min(
            10.0,
            result
        )
    )


def composite_rating(general, elite):

    if (
        general is None
        or elite is None
    ):
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

        if isinstance(
            data,
            list
        ):
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


def weekly_record_exists(
    history,
    leaderboard_url
):

    return any(
        record.get(
            "leaderboard_url"
        )
        == leaderboard_url
        for record in history
    )


def build_weekly_record(
    snapshot,
    finalization_mode
):

    my = snapshot.get(
        "my_result"
    )

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
                .fromisoformat(
                    start_date_text
                )
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
        "participated":
            True,

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
        history.append(
            record
        )

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
        record.get(
            key
        )
        for record in history[
            -count:
        ]
        if isinstance(
            record.get(
                key
            ),
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
        for record in history[
            -count:
        ]
        if isinstance(
            record.get(
                key
            ),
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
        range(
            len(values)
        )
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
            in zip(
                xs,
                values
            )
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

    sign = (
        "+"
        if delta_ms > 0
        else ""
    )

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
# BRAKE BIAS
# ============================================================

def format_bb_value(value):

    if value is None:
        return "N/A"

    if value > 0:
        return f"+{value}"

    return str(
        value
    )


def format_bb_range(range_value):

    if not range_value:
        return "N/A"

    low, high = range_value

    if low == high:
        return format_bb_value(
            low
        )

    return (
        f"{format_bb_value(low)} "
        f"to "
        f"{format_bb_value(high)}"
    )


def brake_bias_recommendation(
    car_code,
    tyre_multiplier
):

    layout = get_car_layout(
        car_code,
        CAR_TECHNICAL_DATABASE
    )

    if not layout:

        return {
            "layout":
                "Unknown",

            "qualifying_range":
                None,

            "race_range":
                None,

            "qualifying_start":
                None,

            "race_start":
                None,

            "confidence":
                "UNVALIDATED",

            "reason":
                (
                    "Car is identified, but drivetrain metadata "
                    "has not yet been validated in the central database."
                ),

            "wear_adjustment":
                "No recommendation generated."
        }

    baseline = (
        BRAKE_BIAS_BASELINES.get(
            layout
        )
    )

    if not baseline:

        return {
            "layout":
                layout,

            "qualifying_range":
                None,

            "race_range":
                None,

            "qualifying_start":
                None,

            "race_start":
                None,

            "confidence":
                "UNVALIDATED",

            "reason":
                (
                    "Validated drivetrain exists, but no "
                    "Brake Bias model is defined for this layout."
                ),

            "wear_adjustment":
                "No recommendation generated."
        }

    qual_low, qual_high = (
        baseline[
            "qualifying"
        ]
    )

    race_low, race_high = (
        baseline[
            "race"
        ]
    )

    qualifying_start = int(
        round(
            (
                qual_low
                + qual_high
            )
            / 2
        )
    )

    if tyre_multiplier <= 1:

        race_start = qualifying_start

        wear_adjustment = (
            "Low tyre wear: start close to the qualifying setting."
        )

    elif tyre_multiplier <= 2:

        race_start = int(
            round(
                (
                    race_low
                    + race_high
                )
                / 2
            )
        )

        wear_adjustment = (
            "Moderate tyre wear: use the middle of the "
            "conservative race range."
        )

    elif tyre_multiplier <= 4:

        if layout in (
            "FF",
            "FR",
            "4WD"
        ):

            race_start = race_high

            wear_adjustment = (
                "Meaningful tyre wear: start toward the rearward "
                "end of the race range to reduce front-axle load."
            )

        elif layout in (
            "MR",
            "RR"
        ):

            race_start = race_low

            wear_adjustment = (
                "Meaningful tyre wear: start toward the forward "
                "end of the race range to prioritize rear stability."
            )

        else:

            race_start = int(
                round(
                    (
                        race_low
                        + race_high
                    )
                    / 2
                )
            )

            wear_adjustment = (
                "Meaningful tyre wear: use the middle of the range."
            )

    else:

        if layout in (
            "FF",
            "FR",
            "4WD"
        ):

            race_start = race_high

            wear_adjustment = (
                "High tyre wear: begin at the rearward end of the "
                "heuristic range, without exceeding it."
            )

        elif layout in (
            "MR",
            "RR"
        ):

            race_start = race_low

            wear_adjustment = (
                "High tyre wear: begin at the forward end of the "
                "heuristic range, without exceeding it."
            )

        else:

            race_start = int(
                round(
                    (
                        race_low
                        + race_high
                    )
                    / 2
                )
            )

            wear_adjustment = (
                "High tyre wear: remain inside the conservative range."
            )

    return {
        "layout":
            layout,

        "qualifying_range":
            (
                qual_low,
                qual_high
            ),

        "race_range":
            (
                race_low,
                race_high
            ),

        "qualifying_start":
            qualifying_start,

        "race_start":
            race_start,

        "confidence":
            "HEURISTIC",

        "reason":
            baseline[
                "reason"
            ],

        "wear_adjustment":
            wear_adjustment
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

    if metric.startswith(
        "top"
    ):

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

        if isinstance(
            value,
            dict
        ):
            return value.get(
                "score"
            )

        if isinstance(
            value,
            int
        ):
            return value

        if isinstance(
            value,
            str
        ):
            return laptime_to_score(
                value
            )

    return None


# ============================================================
# FORECAST HELPERS
# ============================================================

def forecast_parse_datetime(value):

    if not value:
        return None

    try:
        return datetime.fromisoformat(
            value
        )

    except Exception:
        return None


def forecast_linear_regression(points):

    if len(points) < 2:
        return None

    xs = [
        float(x)
        for x, _
        in points
    ]

    ys = [
        float(y)
        for _, y
        in points
    ]

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

    intercept = (
        y_mean
        - slope * x_mean
    )

    residuals = [
        y
        - (
            slope * x
            + intercept
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

    return {
        "slope":
            slope,

        "intercept":
            intercept,

        "rmse":
            rmse
    }


def forecast_threshold_score(
    snapshot,
    rank
):

    value = (
        snapshot
        .get(
            "thresholds",
            {}
        )
        .get(
            str(rank)
        )
    )

    if isinstance(
        value,
        dict
    ):
        return value.get(
            "score"
        )

    if isinstance(
        value,
        (int, float)
    ):
        return value

    return None


def forecast_percentile_threshold_score(
    snapshot,
    percent
):

    value = (
        snapshot
        .get(
            "percentile_thresholds",
            {}
        )
        .get(
            str(percent)
        )
    )

    if isinstance(
        value,
        dict
    ):
        return value.get(
            "score"
        )

    if isinstance(
        value,
        (int, float)
    ):
        return value

    return None


def forecast_world_record_score(
    snapshot
):

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


def forecast_personal_score(
    snapshot
):

    result = snapshot.get(
        "my_result"
    )

    if not result:
        return None

    return result.get(
        "score"
    )


def forecast_personal_rank(
    snapshot
):

    result = snapshot.get(
        "my_result"
    )

    if not result:
        return None

    return result.get(
        "rank"
    )


def current_week_forecast_snapshots(
    history,
    current_snapshot
):

    current_url = (
        current_snapshot
        .get(
            "race",
            {}
        )
        .get(
            "leaderboard_url"
        )
    )

    combined = (
        list(history)
        + [current_snapshot]
    )

    selected = []
    seen = set()

    for snapshot in combined:

        url = (
            snapshot
            .get(
                "race",
                {}
            )
            .get(
                "leaderboard_url"
            )
        )

        if url != current_url:
            continue

        timestamp_text = snapshot.get(
            "timestamp"
        )

        timestamp = forecast_parse_datetime(
            timestamp_text
        )

        if not timestamp:
            continue

        if timestamp_text in seen:
            continue

        seen.add(
            timestamp_text
        )

        selected.append(
            snapshot
        )

    selected.sort(
        key=lambda item:
            forecast_parse_datetime(
                item[
                    "timestamp"
                ]
            )
    )

    return selected


def forecast_build_time_axis(
    snapshots,
    race_start
):

    output = []

    for snapshot in snapshots:

        timestamp = forecast_parse_datetime(
            snapshot.get(
                "timestamp"
            )
        )

        if not timestamp:
            continue

        hours = (
            timestamp
            - race_start
        ).total_seconds() / 3600

        output.append(
            (
                hours,
                snapshot
            )
        )

    return output


def forecast_metric_v2(
    snapshots,
    race_start,
    target_time,
    extractor,
    direction="down"
):

    axis = forecast_build_time_axis(
        snapshots,
        race_start
    )

    points = []

    for hours, snapshot in axis:

        value = extractor(
            snapshot
        )

        if isinstance(
            value,
            (int, float)
        ):

            points.append(
                (
                    hours,
                    float(value)
                )
            )

    if len(points) < 3:
        return None

    regression = forecast_linear_regression(
        points
    )

    if not regression:
        return None

    span_hours = (
        max(
            x
            for x, _
            in points
        )
        - min(
            x
            for x, _
            in points
        )
    )

    slope = regression[
        "slope"
    ]

    if direction == "down":
        slope = min(
            slope,
            0
        )

    elif direction == "up":
        slope = max(
            slope,
            0
        )

    target_x = (
        target_time
        - race_start
    ).total_seconds() / 3600

    predicted = (
        regression[
            "intercept"
        ]
        + slope * target_x
    )

    current_value = points[
        -1
    ][
        1
    ]

    if direction == "down":

        predicted = min(
            predicted,
            current_value
        )

    elif direction == "up":

        predicted = max(
            predicted,
            current_value
        )

    if (
        len(points) >= 10
        and span_hours >= 72
    ):

        confidence = "HIGH"

    elif (
        len(points) >= 6
        and span_hours >= 24
    ):

        confidence = "MEDIUM"

    else:

        confidence = "LOW"

    return {
        "predicted":
            predicted,

        "current":
            current_value,

        "slope_per_hour":
            slope,

        "rmse":
            regression[
                "rmse"
            ],

        "samples":
            len(points),

        "span_hours":
            span_hours,

        "confidence":
            confidence
    }


def forecast_score_at_rank(
    ranking,
    rank
):

    if not ranking:
        return None

    rank = max(
        1,
        min(
            len(ranking),
            int(rank)
        )
    )

    return ranking[
        rank - 1
    ].get(
        "score"
    )


def forecast_percentile_rank(
    total,
    percent
):

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


def forecast_current_percentile_score(
    ranking,
    percent
):

    rank = forecast_percentile_rank(
        len(ranking),
        percent
    )

    return {
        "rank":
            rank,

        "score":
            forecast_score_at_rank(
                ranking,
                rank
            )
    }


def forecast_projected_percentile_score(
    ranking,
    top500_forecast,
    top1000_forecast,
    percent
):

    current = forecast_current_percentile_score(
        ranking,
        percent
    )

    current_score = current[
        "score"
    ]

    if current_score is None:
        return None

    projected_deltas = []

    if top500_forecast:

        projected_deltas.append(
            top500_forecast[
                "predicted"
            ]
            - top500_forecast[
                "current"
            ]
        )

    if top1000_forecast:

        projected_deltas.append(
            top1000_forecast[
                "predicted"
            ]
            - top1000_forecast[
                "current"
            ]
        )

    expected_delta = (
        sum(projected_deltas)
        / len(projected_deltas)
        if projected_deltas
        else 0
    )

    confidence_values = []

    if top500_forecast:

        confidence_values.append(
            top500_forecast.get(
                "confidence",
                "LOW"
            )
        )

    if top1000_forecast:

        confidence_values.append(
            top1000_forecast.get(
                "confidence",
                "LOW"
            )
        )

    confidence = (
        "LOW"
        if not confidence_values
        else confidence_values[0]
    )

    return {
        "current_rank":
            current[
                "rank"
            ],

        "current_score":
            current_score,

        "predicted_score":
            int(
                round(
                    current_score
                    + expected_delta
                )
            ),

        "estimated_change_ms":
            int(
                round(
                    expected_delta
                )
            ),

        "mode":
            "FALLBACK",

        "confidence":
            confidence,

        "samples":
            0
    }


def build_percentile_forecast(
    snapshots,
    ranking,
    race_start,
    sunday_end,
    percent,
    top500_forecast,
    top1000_forecast
):

    direct = forecast_metric_v2(
        snapshots,
        race_start,
        sunday_end,
        extractor=lambda snapshot:
            forecast_percentile_threshold_score(
                snapshot,
                percent
            ),
        direction="down"
    )

    current = forecast_current_percentile_score(
        ranking,
        percent
    )

    if direct:

        return {
            "current_rank":
                current[
                    "rank"
                ],

            "current_score":
                current[
                    "score"
                ],

            "predicted_score":
                int(
                    round(
                        direct[
                            "predicted"
                        ]
                    )
                ),

            "estimated_change_ms":
                int(
                    round(
                        direct[
                            "predicted"
                        ]
                        - direct[
                            "current"
                        ]
                    )
                ),

            "mode":
                "DIRECT",

            "confidence":
                direct[
                    "confidence"
                ],

            "samples":
                direct[
                    "samples"
                ],

            "span_hours":
                direct[
                    "span_hours"
                ],

            "rmse":
                direct[
                    "rmse"
                ]
        }

    fallback = forecast_projected_percentile_score(
        ranking,
        top500_forecast,
        top1000_forecast,
        percent
    )

    if fallback:
        return fallback

    return None


def forecast_rank_if_no_improvement(
    snapshots,
    current_snapshot,
    race_start,
    target_time
):

    current_result = current_snapshot.get(
        "my_result"
    )

    if not current_result:
        return None

    current_score = current_result.get(
        "score"
    )

    current_rank = current_result.get(
        "rank"
    )

    if (
        current_score is None
        or current_rank is None
    ):
        return None

    comparable = []

    for snapshot in snapshots:

        score = forecast_personal_score(
            snapshot
        )

        rank = forecast_personal_rank(
            snapshot
        )

        timestamp = forecast_parse_datetime(
            snapshot.get(
                "timestamp"
            )
        )

        if (
            score == current_score
            and isinstance(
                rank,
                (int, float)
            )
            and timestamp
        ):

            comparable.append(
                snapshot
            )

    if len(comparable) < 3:

        return {
            "current_rank":
                current_rank,

            "projected_rank":
                None,

            "confidence":
                "INSUFFICIENT",

            "samples":
                len(comparable),

            "span_hours":
                0
        }

    forecast = forecast_metric_v2(
        comparable,
        race_start,
        target_time,
        extractor=forecast_personal_rank,
        direction="up"
    )

    if not forecast:
        return None

    projected_rank = max(
        current_rank,
        int(
            round(
                forecast[
                    "predicted"
                ]
            )
        )
    )

    return {
        "current_rank":
            current_rank,

        "projected_rank":
            projected_rank,

        "confidence":
            forecast[
                "confidence"
            ],

        "samples":
            forecast[
                "samples"
            ],

        "span_hours":
            forecast[
                "span_hours"
            ],

        "rank_growth_per_hour":
            forecast[
                "slope_per_hour"
            ]
    }


def forecast_total_drivers(
    snapshots,
    race_start,
    target_time
):

    forecast = forecast_metric_v2(
        snapshots,
        race_start,
        target_time,
        extractor=lambda snapshot:
            snapshot.get(
                "total_drivers"
            ),
        direction="up"
    )

    if not forecast:
        return None

    return {
        "current":
            int(
                round(
                    forecast[
                        "current"
                    ]
                )
            ),

        "predicted":
            int(
                round(
                    forecast[
                        "predicted"
                    ]
                )
            ),

        "confidence":
            forecast[
                "confidence"
            ],

        "samples":
            forecast[
                "samples"
            ]
    }


def forecast_overall_confidence(
    forecasts
):

    values = {
        "HIGH": 3,
        "MEDIUM": 2,
        "LOW": 1
    }

    scores = []

    for forecast in forecasts:

        if not forecast:
            continue

        confidence = forecast.get(
            "confidence"
        )

        if confidence in values:

            scores.append(
                values[
                    confidence
                ]
            )

    if not scores:
        return "LOW"

    average = (
        sum(scores)
        / len(scores)
    )

    if average >= 2.5:
        return "HIGH"

    if average >= 1.5:
        return "MEDIUM"

    return "LOW"


def build_forecast_v2(
    history,
    current_snapshot,
    ranking,
    race_start,
    sunday_end
):

    snapshots = current_week_forecast_snapshots(
        history,
        current_snapshot
    )

    if len(snapshots) < 3:

        return {
            "available":
                False,

            "reason":
                "Fewer than 3 comparable current-week snapshots."
        }

    wr_forecast = forecast_metric_v2(
        snapshots,
        race_start,
        sunday_end,
        extractor=forecast_world_record_score,
        direction="down"
    )

    top100_forecast = forecast_metric_v2(
        snapshots,
        race_start,
        sunday_end,
        extractor=lambda snapshot:
            forecast_threshold_score(
                snapshot,
                100
            ),
        direction="down"
    )

    top500_forecast = forecast_metric_v2(
        snapshots,
        race_start,
        sunday_end,
        extractor=lambda snapshot:
            forecast_threshold_score(
                snapshot,
                500
            ),
        direction="down"
    )

    top1000_forecast = forecast_metric_v2(
        snapshots,
        race_start,
        sunday_end,
        extractor=lambda snapshot:
            forecast_threshold_score(
                snapshot,
                1000
            ),
        direction="down"
    )

    top10 = build_percentile_forecast(
        snapshots,
        ranking,
        race_start,
        sunday_end,
        10,
        top500_forecast,
        top1000_forecast
    )

    top5 = build_percentile_forecast(
        snapshots,
        ranking,
        race_start,
        sunday_end,
        5,
        top500_forecast,
        top1000_forecast
    )

    total_forecast = forecast_total_drivers(
        snapshots,
        race_start,
        sunday_end
    )

    personal_rank_projection = (
        forecast_rank_if_no_improvement(
            snapshots,
            current_snapshot,
            race_start,
            sunday_end
        )
    )

    current_result = current_snapshot.get(
        "my_result"
    )

    personal = None

    if current_result:

        current_score = current_result.get(
            "score"
        )

        current_rank = current_result.get(
            "rank"
        )

        current_top_percent = current_result.get(
            "top_percent"
        )

        projected_rank = None
        projected_top_percent = None

        if personal_rank_projection:

            projected_rank = (
                personal_rank_projection.get(
                    "projected_rank"
                )
            )

        if (
            projected_rank is not None
            and total_forecast
        ):

            projected_total = max(
                total_forecast[
                    "predicted"
                ],
                projected_rank
            )

            projected_top_percent = (
                projected_rank
                / projected_total
                * 100
            )

        personal = {
            "score":
                current_score,

            "current_rank":
                current_rank,

            "current_top_percent":
                current_top_percent,

            "projected_rank":
                projected_rank,

            "projected_top_percent":
                projected_top_percent,

            "rank_forecast_confidence":
                (
                    personal_rank_projection.get(
                        "confidence"
                    )
                    if personal_rank_projection
                    else "INSUFFICIENT"
                )
        }

    targets = {}

    if (
        current_result
        and current_result.get(
            "score"
        )
    ):

        personal_score = current_result[
            "score"
        ]

        if top10:

            targets[
                "top10"
            ] = {
                "score":
                    top10[
                        "predicted_score"
                    ],

                "gain_needed_ms":
                    max(
                        0,
                        personal_score
                        - top10[
                            "predicted_score"
                        ]
                    ),

                "mode":
                    top10.get(
                        "mode",
                        "UNKNOWN"
                    )
            }

        if top5:

            targets[
                "top5"
            ] = {
                "score":
                    top5[
                        "predicted_score"
                    ],

                "gain_needed_ms":
                    max(
                        0,
                        personal_score
                        - top5[
                            "predicted_score"
                        ]
                    ),

                "mode":
                    top5.get(
                        "mode",
                        "UNKNOWN"
                    )
            }

    confidence = forecast_overall_confidence(
        [
            wr_forecast,
            top100_forecast,
            top500_forecast,
            top1000_forecast,
            total_forecast,
            top10,
            top5
        ]
    )

    timestamps = [
        forecast_parse_datetime(
            snapshot.get(
                "timestamp"
            )
        )
        for snapshot in snapshots
    ]

    timestamps = [
        timestamp
        for timestamp in timestamps
        if timestamp
    ]

    span_hours = 0

    if len(timestamps) >= 2:

        span_hours = (
            max(timestamps)
            - min(timestamps)
        ).total_seconds() / 3600

    return {
        "available":
            True,

        "model":
            "CURRENT_WEEK_HYBRID_V2",

        "historical_training":
            "INSUFFICIENT",

        "samples":
            len(snapshots),

        "span_hours":
            span_hours,

        "confidence":
            confidence,

        "world_record":
            wr_forecast,

        "top100":
            top100_forecast,

        "top500":
            top500_forecast,

        "top1000":
            top1000_forecast,

        "top10_percent":
            top10,

        "top5_percent":
            top5,

        "total_drivers":
            total_forecast,

        "personal":
            personal,

        "targets":
            targets
    }


# ============================================================
# FORECAST REPORT
# ============================================================

def forecast_report_lines(
    forecast
):

    lines = []

    lines.append(
        "FORECAST TO SUNDAY - V2"
    )

    if not forecast.get(
        "available"
    ):

        lines.append(
            forecast.get(
                "reason",
                "Forecast unavailable."
            )
        )

        return lines

    lines.append(
        f"Model           : "
        f"{forecast['model']}"
    )

    lines.append(
        f"Confidence      : "
        f"{forecast['confidence']}"
    )

    lines.append(
        f"Samples         : "
        f"{forecast['samples']}"
    )

    lines.append(
        f"Observed span   : "
        f"{forecast['span_hours']:.1f} h"
    )

    lines.append(
        "Historical model: not yet active "
        "(insufficient cross-week training data)"
    )

    lines.append("")
    lines.append(
        "PROJECTED LEADERBOARD"
    )

    metrics = [
        (
            "world_record",
            "WR"
        ),
        (
            "top100",
            "Top 100"
        ),
        (
            "top500",
            "Top 500"
        ),
        (
            "top1000",
            "Top 1000"
        )
    ]

    for key, label in metrics:

        item = forecast.get(
            key
        )

        if not item:
            continue

        lines.append(
            f"{label:<15}: "
            f"{score_to_laptime(item['predicted'])} | "
            f"{item['confidence']} | "
            f"{item['samples']} samples"
        )

    top10 = forecast.get(
        "top10_percent"
    )

    if top10:

        lines.append(
            f"{'Top 10%':<15}: "
            f"{score_to_laptime(top10['predicted_score'])} | "
            f"{top10.get('mode','UNKNOWN')} | "
            f"{top10.get('confidence','LOW')}"
        )

    top5 = forecast.get(
        "top5_percent"
    )

    if top5:

        lines.append(
            f"{'Top 5%':<15}: "
            f"{score_to_laptime(top5['predicted_score'])} | "
            f"{top5.get('mode','UNKNOWN')} | "
            f"{top5.get('confidence','LOW')}"
        )

    total = forecast.get(
        "total_drivers"
    )

    if total:

        lines.append(
            f"{'Drivers':<15}: "
            f"{total['current']:,} -> "
            f"~{total['predicted']:,}"
        )

    personal = forecast.get(
        "personal"
    )

    if personal:

        lines.append("")
        lines.append(
            "IF YOU DO NOT IMPROVE"
        )

        lines.append(
            f"Current time    : "
            f"{score_to_laptime(personal['score'])}"
        )

        lines.append(
            f"Current rank    : "
            f"#{personal['current_rank']:,}"
        )

        if (
            personal[
                "current_top_percent"
            ]
            is not None
        ):

            lines.append(
                f"Current Top %   : "
                f"{personal['current_top_percent']:.2f}%"
            )

        if (
            personal[
                "projected_rank"
            ]
            is not None
        ):

            lines.append(
                f"Projected rank  : "
                f"~#{personal['projected_rank']:,}"
            )

        else:

            lines.append(
                "Projected rank  : "
                "insufficient comparable rank history"
            )

        if (
            personal[
                "projected_top_percent"
            ]
            is not None
        ):

            lines.append(
                f"Projected Top % : "
                f"~{personal['projected_top_percent']:.2f}%"
            )

        lines.append(
            f"Rank confidence : "
            f"{personal['rank_forecast_confidence']}"
        )

    targets = forecast.get(
        "targets",
        {}
    )

    if targets:

        lines.append("")
        lines.append(
            "TARGETS FOR SUNDAY"
        )

        if "top10" in targets:

            target = targets[
                "top10"
            ]

            lines.append(
                f"Top 10% target  : "
                f"{score_to_laptime(target['score'])} | "
                f"gain needed "
                f"{target['gain_needed_ms']/1000:.3f}s | "
                f"{target.get('mode','UNKNOWN')}"
            )

        if "top5" in targets:

            target = targets[
                "top5"
            ]

            lines.append(
                f"Top 5% target   : "
                f"{score_to_laptime(target['score'])} | "
                f"gain needed "
                f"{target['gain_needed_ms']/1000:.3f}s | "
                f"{target.get('mode','UNKNOWN')}"
            )

    lines.append("")

    lines.append(
        "Percentile mode : "
        "DIRECT = forecast learned from the observed Top 5%/10% series; "
        "FALLBACK = inferred from Top 500/1000 until enough direct snapshots exist."
    )

    lines.append(
        "Forecast note   : "
        "V2 uses current-week leaderboard evolution. "
        "Cross-week historical learning will activate "
        "after sufficient multi-week intraday data exists."
    )

    return lines


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

    total = len(
        ranking
    )

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

            unique_targets[
                rank
            ] = label

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
                unique_targets[
                    rank
                ],

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

    return results[
        :4
    ]


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
        for driver in ranking
        if predicate(
            driver
        )
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

    total = len(
        ranking
    )

    top100_total = min(
        100,
        total
    )

    top1000_total = min(
        1000,
        total
    )

    rows = []

    for (
        car_code,
        all_count
    ) in all_counter.items():

        overall_share = (
            all_count
            / total
        )

        if overall_share <= 0:
            continue

        top100_count = (
            top100_counter.get(
                car_code,
                0
            )
        )

        top1000_count = (
            top1000_counter.get(
                car_code,
                0
            )
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
            oi100
            * 0.70
            + oi1000
            * 0.30
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

def best_driver_by_car(
    ranking
):

    result = {}

    for driver in ranking:

        car_code = get_car_code(
            driver
        )

        if (
            car_code is not None
            and car_code not in result
        ):

            result[
                car_code
            ] = driver

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
            f"{unknown_share:.1f}% of valid leaderboard entries."
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
    global CAR_TECHNICAL_DATABASE

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

    # Final hard stop before any leaderboard request.

    validate_selected_race_c(
        race_c
    )

    race_c_link = race_c[
        "url"
    ]

    race_c_text = race_c[
        "text"
    ]

    race_detection_mode = race_c[
        "detection_mode"
    ]

    print(
        "=" * 78
    )

    print(
        "RACE C SAFETY CHECK"
    )

    print(
        "=" * 78
    )

    print(
        "Expected         : Daily Race C"
    )

    print(
        "Detected         : Daily Race C"
    )

    print(
        f"Status           : "
        f"{'Running' if race_c.get('running') else 'Current week'}"
    )

    print(
        f"Detection mode   : "
        f"{race_detection_mode}"
    )

    print(
        f"Race date        : "
        f"{race_c.get('date')}"
    )

    print(
        f"Description      : "
        f"{race_c_text}"
    )

    print(
        f"Leaderboard URL  : "
        f"{race_c_link}"
    )

    print(
        "Validation       : PASSED"
    )

    print(
        "=" * 78
    )

    # ========================================================
    # LEADERBOARD PAGE
    # ========================================================

    leaderboard_response = session.get(
        race_c_link,
        timeout=60
    )

    leaderboard_response.raise_for_status()

    html = leaderboard_response.text

    # ========================================================
    # CAR DATABASE UPDATE
    # ========================================================

    try:

        car_update = update_car_database_from_html(
            html
        )

        CAR_DATABASE = car_update[
            "database"
        ]

        CAR_TECHNICAL_DATABASE = (
            load_car_technical_database()
        )

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

        CAR_DATABASE = load_car_database()

        CAR_TECHNICAL_DATABASE = (
            load_car_technical_database()
        )

        cars_discovered_this_run = 0
        cars_added_this_run = 0
        cars_updated_this_run = 0

    # ========================================================
    # EXTRACT RANKING - LIVE PAGE_DATA FIRST
    # ========================================================

    # GTSH may embed a stale initialRanking in the leaderboard HTML.
    # The page_data endpoint is the live source used by the site itself,
    # so it is now the PRIMARY source. initialRanking and update=1 are
    # retained only as fallbacks.

    ranking = None
    source_mode = None
    live_total_drivers = None

    def extract_page_data_payload(payload):

        entries = None
        total = None
        returned_offset = None
        returned_limit = None
        has_more = None

        if isinstance(payload, list):
            entries = payload

        elif isinstance(payload, dict):

            # Known/likely list keys used by leaderboard APIs.
            for key in (
                "board",
                "ranking",
                "data",
                "entries",
                "results",
                "drivers"
            ):
                value = payload.get(key)
                if isinstance(value, list):
                    entries = value
                    break

            # Some responses wrap the useful object one level deeper.
            if entries is None:
                for wrapper_key in (
                    "page",
                    "result",
                    "payload"
                ):
                    wrapper = payload.get(wrapper_key)
                    if not isinstance(wrapper, dict):
                        continue

                    for key in (
                        "board",
                        "ranking",
                        "data",
                        "entries",
                        "results",
                        "drivers"
                    ):
                        value = wrapper.get(key)
                        if isinstance(value, list):
                            entries = value
                            payload = wrapper
                            break

                    if entries is not None:
                        break

            for key in (
                "total",
                "total_drivers",
                "totalDrivers",
                "count",
                "recordsTotal"
            ):
                value = payload.get(key)
                if isinstance(value, (int, float)):
                    total = int(value)
                    break

            for key in ("offset", "start"):
                value = payload.get(key)
                if isinstance(value, (int, float)):
                    returned_offset = int(value)
                    break

            for key in ("limit", "page_size", "pageSize"):
                value = payload.get(key)
                if isinstance(value, (int, float)):
                    returned_limit = int(value)
                    break

            for key in ("has_more", "hasMore", "more"):
                value = payload.get(key)
                if isinstance(value, bool):
                    has_more = value
                    break

        return (
            entries,
            total,
            returned_offset,
            returned_limit,
            has_more
        )

    # --------------------------------------------------------
    # 1. PRIMARY SOURCE: LIVE page_data=1
    # --------------------------------------------------------

    try:

        live_ranking = []
        seen_ranks = set()
        offset = 0

        # Ask for a large page. If GTSH caps the page size, the loop
        # advances by the number of entries actually returned.
        requested_limit = 1000
        max_pages = 1000

        for page_number in range(max_pages):

            separator = (
                "&"
                if "?" in race_c_link
                else "?"
            )

            page_url = (
                race_c_link
                + separator
                + "page_data=1"
                + f"&offset={offset}"
                + f"&limit={requested_limit}"
            )

            page_response = session.get(
                page_url,
                timeout=60
            )

            page_response.raise_for_status()

            page_payload = page_response.json()

            (
                page_entries,
                page_total,
                returned_offset,
                returned_limit,
                has_more
            ) = extract_page_data_payload(
                page_payload
            )

            if page_total is not None:
                live_total_drivers = page_total

            if not isinstance(page_entries, list):
                raise RuntimeError(
                    "page_data response did not contain a ranking list."
                )

            if not page_entries:
                break

            added_this_page = 0

            for driver in page_entries:

                if not isinstance(driver, dict):
                    continue

                rank = driver.get(
                    "display_rank"
                )

                # Prefer rank as a stable deduplication key.
                if isinstance(rank, (int, float)):
                    rank_key = int(rank)

                    if rank_key in seen_ranks:
                        continue

                    seen_ranks.add(rank_key)

                live_ranking.append(driver)
                added_this_page += 1

            if added_this_page == 0:
                break

            # Stop when the server tells us that the complete live
            # leaderboard has been collected.
            if (
                live_total_drivers is not None
                and len(live_ranking) >= live_total_drivers
            ):
                break

            if has_more is False:
                break

            # Advance using the number of records actually returned.
            # This remains correct even if GTSH ignores/caps limit=1000.
            next_offset = offset + len(page_entries)

            if next_offset <= offset:
                break

            offset = next_offset

        if live_ranking:

            ranking = live_ranking
            source_mode = "live_page_data"

            print(
                f"Leaderboard source: LIVE page_data | "
                f"entries={len(ranking):,} | "
                f"server_total={live_total_drivers}"
            )

    except Exception as exc:

        print(
            "WARNING: live page_data leaderboard failed: "
            f"{exc}"
        )

        ranking = None

    # --------------------------------------------------------
    # 2. FALLBACK: initialRanking embedded in HTML
    # --------------------------------------------------------

    if not ranking:

        marker = "const initialRanking = "

        start = html.find(
            marker
        )

        if start != -1:

            try:

                start += len(
                    marker
                )

                decoder = json.JSONDecoder()

                candidate_ranking, _ = decoder.raw_decode(
                    html[
                        start:
                    ].lstrip()
                )

                if isinstance(candidate_ranking, list) and candidate_ranking:

                    ranking = candidate_ranking
                    source_mode = "initialRanking_fallback"

                    print(
                        "WARNING: using HTML initialRanking fallback | "
                        f"entries={len(ranking):,}"
                    )

            except Exception as exc:

                print(
                    "WARNING: initialRanking fallback failed: "
                    f"{exc}"
                )

    # --------------------------------------------------------
    # 3. LAST FALLBACK: update=1 endpoint
    # --------------------------------------------------------

    if not ranking:

        try:

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

            update_data = update_response.json()

            if isinstance(update_data, list):

                ranking = update_data

            elif isinstance(update_data, dict):

                candidate = (
                    update_data.get(
                        "board"
                    )
                    or update_data.get(
                        "ranking"
                    )
                    or update_data.get(
                        "data"
                    )
                    or update_data.get(
                        "entries"
                    )
                )

                if isinstance(candidate, list):
                    ranking = candidate

            if ranking:

                source_mode = "update_endpoint_fallback"

                print(
                    "WARNING: using update=1 fallback | "
                    f"entries={len(ranking):,}"
                )

        except Exception as exc:

            print(
                "WARNING: update=1 fallback failed: "
                f"{exc}"
            )

    if not ranking:

        raise RuntimeError(
            "Leaderboard contains no drivers from live page_data, "
            "initialRanking, or update=1."
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
    # FIXED-RANK THRESHOLDS
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
    # DIRECT PERCENTILES
    # ========================================================

    percentile_thresholds = {}

    for percent in [
        10,
        5
    ]:

        percentile_rank_value = forecast_percentile_rank(
            len(ranking),
            percent
        )

        percentile_score_value = forecast_score_at_rank(
            ranking,
            percentile_rank_value
        )

        percentile_thresholds[
            str(percent)
        ] = {
            "percent":
                percent,

            "rank":
                percentile_rank_value,

            "score":
                percentile_score_value,

            "laptime":
                score_to_laptime(
                    percentile_score_value
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
    my_brake_bias = None

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

        (
            same_car_rank,
            same_car_total
        ) = group_rank(
            ranking,
            lambda driver:
                get_car_code(
                    driver
                )
                == my_car_code,
            my_driver
        )

        (
            country_rank,
            country_total
        ) = group_rank(
            ranking,
            lambda driver:
                get_user(
                    driver
                ).get(
                    "country_code"
                )
                == my_country,
            my_driver
        )

        (
            dr_rank,
            dr_total
        ) = group_rank(
            ranking,
            lambda driver:
                get_user(
                    driver
                ).get(
                    "driver_rating"
                )
                == my_dr,
            my_driver
        )

        my_brake_bias = brake_bias_recommendation(
            my_car_code,
            tyre_multiplier
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
        get_car_code(
            driver
        )
        for driver in ranking
        if get_car_code(
            driver
        ) is not None
    )

    top100 = ranking[:100]
    top1000 = ranking[:1000]

    top100_counter = Counter(
        get_car_code(
            driver
        )
        for driver in top100
        if get_car_code(
            driver
        ) is not None
    )

    top1000_counter = Counter(
        get_car_code(
            driver
        )
        for driver in top1000
        if get_car_code(
            driver
        ) is not None
    )

    # ========================================================
    # TOP 5 USED CARS + BRAKE BIAS
    # ========================================================

    top5_used_cars = []

    for (
        car_code,
        count
    ) in (
        top1000_counter
        .most_common(
            5
        )
    ):

        bb = brake_bias_recommendation(
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
                bb[
                    "layout"
                ],

            "qualifying_range":
                bb[
                    "qualifying_range"
                ],

            "race_range":
                bb[
                    "race_range"
                ],

            "qualifying_start":
                bb[
                    "qualifying_start"
                ],

            "race_start":
                bb[
                    "race_start"
                ],

            "confidence":
                bb[
                    "confidence"
                ],

            "reason":
                bb[
                    "reason"
                ],

            "wear_adjustment":
                bb[
                    "wear_adjustment"
                ]
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
            .most_common(
                1
            )[0][0]
            if top1000_counter
            else None
        )

        my_car_best = best_by_car.get(
            my_code
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
                    my_result[
                        "score"
                    ]
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

    previous = load_previous_snapshot()

    # ========================================================
    # HEALTH
    # ========================================================

    unknown_count = sum(
        count
        for (
            car_code,
            count
        ) in all_counter.items()
        if (
            isinstance(
                car_code,
                int
            )
            and car_code > 0
            and car_code not in CAR_DATABASE
        )
    )

    invalid_car_code_count = sum(
        count
        for (
            car_code,
            count
        ) in all_counter.items()
        if (
            not isinstance(
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

            "safety_validation":
                "PASSED",

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

        "percentile_thresholds":
            percentile_thresholds,

        "my_result":
            my_result,

        "my_brake_bias":
            my_brake_bias,

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
            credible_overperformance[
                :10
            ],

        "car_comparison":
            car_comparison,

        "car_database": {
            "total_known_cars":
                len(
                    CAR_DATABASE
                ),

            "technical_records":
                len(
                    CAR_TECHNICAL_DATABASE
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

            "race_safety_validation":
                "PASSED",

            "leaderboard_entries":
                len(ranking),

            "my_driver_found":
                my_driver
                is not None
        }
    }

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

    forecast_v2 = {
        "available":
            False,

        "reason":
            "Race start date unavailable."
    }

    if start_date:

        sunday_end = (
            start_date
            + timedelta(
                days=6
            )
        ).replace(
            hour=23,
            minute=59,
            second=0
        )

        if sunday_end > now:

            forecast_v2 = build_forecast_v2(
                history=history,
                current_snapshot=snapshot,
                ranking=ranking,
                race_start=start_date,
                sunday_end=sunday_end
            )

            snapshot[
                "forecast_target"
            ] = sunday_end.isoformat()

        else:

            forecast_v2 = {
                "available":
                    False,

                "reason":
                    "The race week has already ended."
            }

    snapshot[
        "forecast_v2"
    ] = forecast_v2

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
    # REPORT
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
        "Race validation: PASSED - Daily Race C only"
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
            and country_stats[
                "rank"
            ]
        ):

            lines.append(
                f"Country rank    : "
                f"#{country_stats['rank']:,} "
                f"of {country_stats['total']:,} "
                f"({country_stats['country']})"
            )

        if (
            dr_stats
            and dr_stats[
                "rank"
            ]
        ):

            lines.append(
                f"DR rank         : "
                f"#{dr_stats['rank']:,} "
                f"of {dr_stats['total']:,} "
                f"(DR {dr_stats['dr']})"
            )

        if (
            same_car_stats
            and same_car_stats[
                "rank"
            ]
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

        for (
            index,
            target
        ) in enumerate(
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
    # YOUR CAR VS META
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

    for (
        index,
        car
    ) in enumerate(
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

    for (
        index,
        car
    ) in enumerate(
        credible_overperformance[
            :5
        ],
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
    # BRAKE BIAS
    # ========================================================

    lines.append("")
    lines.append(
        "YOUR BRAKE BIAS STARTING POINT"
    )

    lines.append(
        "Convention: negative = more front, "
        "positive = more rear."
    )

    if (
        my_result
        and my_brake_bias
    ):

        lines.append(
            f"Car             : "
            f"{my_result['car']}"
        )

        lines.append(
            f"Drivetrain      : "
            f"{my_brake_bias['layout']}"
        )

        lines.append(
            f"Qualifying range: "
            f"{format_bb_range(my_brake_bias['qualifying_range'])}"
        )

        lines.append(
            f"Qualifying start: "
            f"{format_bb_value(my_brake_bias['qualifying_start'])}"
        )

        lines.append(
            f"Race range      : "
            f"{format_bb_range(my_brake_bias['race_range'])}"
        )

        lines.append(
            f"Race start      : "
            f"{format_bb_value(my_brake_bias['race_start'])}"
        )

        lines.append(
            f"Confidence      : "
            f"{my_brake_bias['confidence']}"
        )

        lines.append(
            f"Wear adjustment : "
            f"{my_brake_bias['wear_adjustment']}"
        )

        lines.append(
            f"Rationale       : "
            f"{my_brake_bias['reason']}"
        )

    else:

        lines.append(
            "No personal Brake Bias recommendation available."
        )

    lines.append("")
    lines.append(
        "BRAKE BIAS - TOP 5 USED CARS"
    )

    lines.append(
        "Conservative heuristic starting ranges, "
        "not telemetry-proven optimum settings."
    )

    for (
        index,
        car
    ) in enumerate(
        top5_used_cars,
        start=1
    ):

        lines.append(
            f"{index}. "
            f"{car['car']} | "
            f"{car['layout']} | "
            f"Quali "
            f"{format_bb_range(car['qualifying_range'])} "
            f"(start {format_bb_value(car['qualifying_start'])}) | "
            f"Race "
            f"{format_bb_range(car['race_range'])} "
            f"(start {format_bb_value(car['race_start'])}) | "
            f"{car['confidence']}"
        )

    # ========================================================
    # STRATEGY FLAGS
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
            "Tyre wear is low."
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

    lines.extend(
        forecast_report_lines(
            forecast_v2
        )
    )

    # ========================================================
    # LONG-TERM RATING
    # ========================================================

    lines.append("")
    lines.append(
        "LONG-TERM RATING TREND"
    )

    lines.append(
        "Higher General, Elite and Composite ratings are better."
    )

    lines.append(
        "Lower Top % and WR % are better."
    )

    lines.append(
        "Only FINAL Sunday ratings are used "
        "for historical trend calculations."
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

        lines.append("")
        lines.append(
            "CURRENT WEEK"
        )

        lines.append(
            f"General    : "
            f"{my_result['position_score']:.2f}"
        )

        lines.append(
            f"Elite      : "
            f"{my_result['elite_score']:.2f}"
        )

        lines.append(
            f"Composite  : "
            f"{my_result['composite_rating']:.2f}"
        )

        lines.append(
            f"Top %      : "
            f"{my_result['top_percent']:.2f}%"
        )

        lines.append(
            f"WR %       : "
            f"{my_result['wr_percentage']:.3f}%"
        )

    current_assessment = None
    composite_trend = None
    wr_trend = None

    if weekly_history:

        latest_final = weekly_history[
            -1
        ]

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

        if my_result:

            current_general = my_result.get(
                "position_score"
            )

            current_elite = my_result.get(
                "elite_score"
            )

            current_composite = my_result.get(
                "composite_rating"
            )

            current_top = my_result.get(
                "top_percent"
            )

            current_wr = my_result.get(
                "wr_percentage"
            )

            last_general = latest_final.get(
                "general_score"
            )

            last_elite = latest_final.get(
                "elite_score"
            )

            last_composite = latest_final.get(
                "composite_rating"
            )

            last_top = latest_final.get(
                "top_percent"
            )

            last_wr = latest_final.get(
                "wr_percentage"
            )

            lines.append("")
            lines.append(
                "CURRENT WEEK VS LAST FINALIZED WEEK"
            )

            delta_general = (
                current_general
                - last_general
            )

            delta_elite = (
                current_elite
                - last_elite
            )

            delta_composite = (
                current_composite
                - last_composite
            )

            delta_top = (
                current_top
                - last_top
            )

            delta_wr = (
                current_wr
                - last_wr
            )

            lines.append(
                f"General    : "
                f"{last_general:.2f} -> "
                f"{current_general:.2f} "
                f"({delta_general:+.2f}) | "
                f"{'BETTER' if delta_general > 0.01 else 'WORSE' if delta_general < -0.01 else 'STABLE'}"
            )

            lines.append(
                f"Elite      : "
                f"{last_elite:.2f} -> "
                f"{current_elite:.2f} "
                f"({delta_elite:+.2f}) | "
                f"{'BETTER' if delta_elite > 0.01 else 'WORSE' if delta_elite < -0.01 else 'STABLE'}"
            )

            lines.append(
                f"Composite  : "
                f"{last_composite:.2f} -> "
                f"{current_composite:.2f} "
                f"({delta_composite:+.2f}) | "
                f"{'BETTER' if delta_composite > 0.01 else 'WORSE' if delta_composite < -0.01 else 'STABLE'}"
            )

            lines.append(
                f"Top %      : "
                f"{last_top:.2f}% -> "
                f"{current_top:.2f}% "
                f"({delta_top:+.2f} pp) | "
                f"{'BETTER' if delta_top < -0.05 else 'WORSE' if delta_top > 0.05 else 'STABLE'}"
            )

            lines.append(
                f"WR %       : "
                f"{last_wr:.3f}% -> "
                f"{current_wr:.3f}% "
                f"({delta_wr:+.3f} pp) | "
                f"{'BETTER' if delta_wr < -0.01 else 'WORSE' if delta_wr > 0.01 else 'STABLE'}"
            )

            assessment_score = 0

            if delta_composite > 0.05:
                assessment_score += 2

            elif delta_composite < -0.05:
                assessment_score -= 2

            if delta_top < -0.50:
                assessment_score += 1

            elif delta_top > 0.50:
                assessment_score -= 1

            if delta_wr < -0.05:
                assessment_score += 1

            elif delta_wr > 0.05:
                assessment_score -= 1

            if assessment_score >= 2:

                current_assessment = (
                    "ABOVE LAST WEEK"
                )

            elif assessment_score <= -2:

                current_assessment = (
                    "BELOW LAST WEEK"
                )

            else:

                current_assessment = (
                    "SIMILAR TO LAST WEEK"
                )

            lines.append("")

            lines.append(
                f"Current week assessment : "
                f"{current_assessment}"
            )

        if len(
            weekly_history
        ) >= 2:

            previous_final = weekly_history[
                -2
            ]

            lines.append("")
            lines.append(
                "LATEST FINALIZED WEEK VS PRIOR FINALIZED WEEK"
            )

            lines.append(
                f"General    : "
                f"{previous_final['general_score']:.2f} -> "
                f"{latest_final['general_score']:.2f} "
                f"({latest_final['general_score'] - previous_final['general_score']:+.2f})"
            )

            lines.append(
                f"Elite      : "
                f"{previous_final['elite_score']:.2f} -> "
                f"{latest_final['elite_score']:.2f} "
                f"({latest_final['elite_score'] - previous_final['elite_score']:+.2f})"
            )

            lines.append(
                f"Composite  : "
                f"{previous_final['composite_rating']:.2f} -> "
                f"{latest_final['composite_rating']:.2f} "
                f"({latest_final['composite_rating'] - previous_final['composite_rating']:+.2f})"
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

        avg4_top = average_metric(
            weekly_history,
            "top_percent",
            4
        )

        avg4_wr = average_metric(
            weekly_history,
            "wr_percentage",
            4
        )

        lines.append("")
        lines.append(
            "4-WEEK FINALIZED MOVING AVERAGE"
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

        lines.append(
            f"Top %      : "
            f"{avg4_top:.2f}%"
        )

        lines.append(
            f"WR %       : "
            f"{avg4_wr:.3f}%"
        )

        general_trend = metric_trend(
            weekly_history,
            "general_score"
        )

        elite_trend = metric_trend(
            weekly_history,
            "elite_score"
        )

        composite_trend = metric_trend(
            weekly_history,
            "composite_rating"
        )

        top_trend = metric_trend(
            weekly_history,
            "top_percent",
            higher_is_better=False
        )

        wr_trend = metric_trend(
            weekly_history,
            "wr_percentage",
            higher_is_better=False
        )

        lines.append("")
        lines.append(
            "8-WEEK FINALIZED TREND"
        )

        lines.append(
            f"General    : "
            f"{general_trend}"
        )

        lines.append(
            f"Elite      : "
            f"{elite_trend}"
        )

        lines.append(
            f"Composite  : "
            f"{composite_trend}"
        )

        lines.append(
            f"Top %      : "
            f"{top_trend}"
        )

        lines.append(
            f"WR %       : "
            f"{wr_trend}"
        )

        if current_assessment:

            lines.append("")
            lines.append(
                "PERFORMANCE SUMMARY"
            )

            lines.append(
                f"Current week vs last final : "
                f"{current_assessment}"
            )

            lines.append(
                f"Long-term Composite trend  : "
                f"{composite_trend}"
            )

            lines.append(
                f"Long-term WR % trend       : "
                f"{wr_trend}"
            )

            if (
                current_assessment
                == "BELOW LAST WEEK"
                and composite_trend
                == "IMPROVING"
            ):

                interpretation = (
                    "Short-term pullback inside an "
                    "improving long-term trend."
                )

            elif (
                current_assessment
                == "ABOVE LAST WEEK"
                and composite_trend
                == "IMPROVING"
            ):

                interpretation = (
                    "Current performance confirms the "
                    "improving long-term trend."
                )

            elif (
                current_assessment
                == "BELOW LAST WEEK"
                and composite_trend
                == "DECLINING"
            ):

                interpretation = (
                    "Current performance reinforces the "
                    "declining long-term trend."
                )

            elif (
                current_assessment
                == "ABOVE LAST WEEK"
                and composite_trend
                == "DECLINING"
            ):

                interpretation = (
                    "Short-term recovery inside a "
                    "declining long-term trend."
                )

            else:

                interpretation = (
                    "Current performance is broadly "
                    "consistent with recent history."
                )

            lines.append(
                f"Interpretation               : "
                f"{interpretation}"
            )

        lines.append("")
        lines.append(
            "LAST FINALIZED RACES"
        )

        for record in weekly_history[
            -8:
        ]:

            lines.append(
                f"{record.get('week_start','N/A')} | "
                f"Gen {record.get('general_score',0):.2f} | "
                f"Elite {record.get('elite_score',0):.2f} | "
                f"Comp {record.get('composite_rating',0):.2f} | "
                f"Top {record.get('top_percent',0):.2f}% | "
                f"WR {record.get('wr_percentage',0):.3f}%"
            )

    else:

        lines.append("")
        lines.append(
            "No finalized weekly races recorded yet."
        )

    # ========================================================
    # CHANGES SINCE PREVIOUS SNAPSHOT
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
    # DATA QUALITY
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
        "Race validation: PASSED"
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
        f"Technical DB   : "
        f"{len(CAR_TECHNICAL_DATABASE):,} validated/known records"
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

    lines.append(
        f"Percentile data: "
        f"Top 10% and Top 5% direct snapshot stored"
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
    # EMAIL SUBJECT
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

    main() os
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
    get_car_name as database_get_car_name,
    load_car_technical_database,
    get_car_layout
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

CAR_TECHNICAL_DATABASE = (
    load_car_technical_database()
)


# ============================================================
# BRAKE BIAS V2
# ============================================================

BRAKE_BIAS_BASELINES = {

    "FF": {
        "qualifying": (1, 2),
        "race": (2, 3),
        "reason":
            (
                "FF cars place substantial braking and cornering "
                "load on the front axle. A modest rearward bias "
                "can aid rotation and reduce front tyre stress."
            )
    },

    "FR": {
        "qualifying": (0, 1),
        "race": (1, 2),
        "reason":
            (
                "FR cars generally tolerate a mild rearward "
                "bias while retaining predictable braking stability."
            )
    },

    "MR": {
        "qualifying": (-1, 0),
        "race": (-1, 0),
        "reason":
            (
                "MR cars can become sensitive to rear instability "
                "under braking. A neutral to slightly forward bias "
                "is a conservative starting point."
            )
    },

    "4WD": {
        "qualifying": (1, 2),
        "race": (2, 3),
        "reason":
            (
                "4WD cars generally tolerate a modest rearward bias, "
                "helping rotation while retaining strong braking stability."
            )
    },

    "RR": {
        "qualifying": (-1, 0),
        "race": (-2, -1),
        "reason":
            (
                "RR cars carry substantial rear mass and may benefit "
                "from a modestly forward brake bias to protect rear stability."
            )
    }
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

    return driver.get(
        "user",
        {}
    )


def find_my_driver(
    ranking,
    psn_id
):

    target = psn_id.strip().lower()

    for driver in ranking:

        online_id = (
            get_user(driver)
            .get(
                "np_online_id",
                ""
            )
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

    monday = (
        dt
        - timedelta(
            days=dt.weekday()
        )
    )

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


def race_letters_in_text(text):

    if not isinstance(text, str):
        return set()

    matches = re.findall(
        r"\bDaily\s+Race\s+([ABC])\b",
        text,
        flags=re.IGNORECASE
    )

    return {
        item.upper()
        for item in matches
    }


def extract_local_race_block(link):

    """
    Find the smallest local DOM block around a leaderboard link
    that clearly refers to exactly ONE Daily Race.

    This prevents a parent/container containing Race A + B + C
    from being misclassified as Race C.
    """

    node = link

    best = None

    for depth in range(8):

        if node is None:
            break

        try:

            text = node.get_text(
                " ",
                strip=True
            )

        except Exception:

            text = ""

        text = re.sub(
            r"\s+",
            " ",
            text
        ).strip()

        if text:

            letters = race_letters_in_text(
                text
            )

            if len(letters) == 1:

                letter = next(
                    iter(letters)
                )

                candidate = {
                    "text": text,
                    "letter": letter,
                    "depth": depth
                }

                if best is None:

                    best = candidate

                else:

                    # Prefer the smaller/closer block.
                    if (
                        len(text)
                        < len(best["text"])
                    ):

                        best = candidate

        node = node.parent

    return best


def validate_selected_race_c(
    candidate
):

    if not isinstance(
        candidate,
        dict
    ):

        raise RuntimeError(
            "Race C safety validation failed: invalid candidate."
        )

    text = candidate.get(
        "text",
        ""
    )

    letters = race_letters_in_text(
        text
    )

    if letters != {"C"}:

        raise RuntimeError(
            "Race C safety validation failed. "
            f"Detected Daily Race letters: {sorted(letters)}. "
            "Expected only Daily Race C."
        )

    if not re.search(
        r"\bDaily\s+Race\s+C\b",
        text,
        flags=re.IGNORECASE
    ):

        raise RuntimeError(
            "Race C safety validation failed: "
            "the selected block does not explicitly contain Daily Race C."
        )

    if re.search(
        r"\bDaily\s+Race\s+[AB]\b",
        text,
        flags=re.IGNORECASE
    ):

        raise RuntimeError(
            "Race C safety validation failed: "
            "the selected block also contains Race A or Race B."
        )

    return True


def find_current_race_c(
    soup,
    now
):

    candidates = []

    seen_urls = set()

    links = soup.select(
        'a[href*="/daily/leaderboard?event="], '
        'a[href*="/daily/leaderboard/?event="]'
    )

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

        if full_url in seen_urls:
            continue

        local_block = extract_local_race_block(
            link
        )

        if not local_block:
            continue

        if local_block[
            "letter"
        ] != "C":
            continue

        block_text = local_block[
            "text"
        ]

        # Important additional safety rule:
        # local block must contain only Race C.

        letters = race_letters_in_text(
            block_text
        )

        if letters != {"C"}:
            continue

        race_date = (
            parse_race_date_from_text(
                block_text
            )
        )

        running = bool(
            re.search(
                r"\bRunning\b",
                block_text,
                flags=re.IGNORECASE
            )
        )

        next_week = bool(
            re.search(
                r"\bNext\s+Week\b",
                block_text,
                flags=re.IGNORECASE
            )
        )

        candidates.append(
            {
                "url":
                    full_url,

                "text":
                    block_text,

                "date":
                    race_date,

                "running":
                    running,

                "next_week":
                    next_week,

                "local_depth":
                    local_block[
                        "depth"
                    ]
            }
        )

        seen_urls.add(
            full_url
        )

    if not candidates:

        raise RuntimeError(
            "No unambiguous Daily Race C candidates were found."
        )

    # ========================================================
    # 1. Prefer explicit RUNNING Race C
    # ========================================================

    running_candidates = [
        candidate
        for candidate in candidates
        if (
            candidate[
                "running"
            ]
            and not candidate[
                "next_week"
            ]
        )
    ]

    if running_candidates:

        running_candidates.sort(
            key=lambda candidate:
                (
                    candidate[
                        "date"
                    ]
                    or datetime.min.replace(
                        tzinfo=SAO_PAULO
                    ),
                    -candidate.get(
                        "local_depth",
                        999
                    )
                ),
            reverse=True
        )

        selected = (
            running_candidates[
                0
            ]
        )

        selected[
            "detection_mode"
        ] = "explicit_running_local_block"

        validate_selected_race_c(
            selected
        )

        return selected

    # ========================================================
    # 2. Current week date
    # ========================================================

    current_monday = monday_of_week(
        now
    )

    current_week_candidates = [
        candidate
        for candidate in candidates
        if (
            candidate[
                "date"
            ]
            and candidate[
                "date"
            ].date()
            == current_monday.date()
            and not candidate[
                "next_week"
            ]
        )
    ]

    if current_week_candidates:

        current_week_candidates.sort(
            key=lambda candidate:
                candidate.get(
                    "local_depth",
                    999
                )
        )

        selected = (
            current_week_candidates[
                0
            ]
        )

        selected[
            "detection_mode"
        ] = "current_week_local_block"

        validate_selected_race_c(
            selected
        )

        return selected

    # ========================================================
    # 3. Latest non-future Race C
    # ========================================================

    valid_past = [
        candidate
        for candidate in candidates
        if (
            candidate[
                "date"
            ]
            and candidate[
                "date"
            ] <= now
            and not candidate[
                "next_week"
            ]
        )
    ]

    if valid_past:

        valid_past.sort(
            key=lambda candidate:
                candidate[
                    "date"
                ],
            reverse=True
        )

        selected = (
            valid_past[
                0
            ]
        )

        selected[
            "detection_mode"
        ] = "latest_non_future_local_block"

        validate_selected_race_c(
            selected
        )

        return selected

    raise RuntimeError(
        "Could not safely determine the current Daily Race C."
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
        min(
            10.0,
            result
        )
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
        min(
            10.0,
            result
        )
    )


def composite_rating(general, elite):

    if (
        general is None
        or elite is None
    ):
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

        if isinstance(
            data,
            list
        ):
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


def weekly_record_exists(
    history,
    leaderboard_url
):

    return any(
        record.get(
            "leaderboard_url"
        )
        == leaderboard_url
        for record in history
    )


def build_weekly_record(
    snapshot,
    finalization_mode
):

    my = snapshot.get(
        "my_result"
    )

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
                .fromisoformat(
                    start_date_text
                )
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
        "participated":
            True,

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
        history.append(
            record
        )

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
        record.get(
            key
        )
        for record in history[
            -count:
        ]
        if isinstance(
            record.get(
                key
            ),
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
        for record in history[
            -count:
        ]
        if isinstance(
            record.get(
                key
            ),
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
        range(
            len(values)
        )
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
            in zip(
                xs,
                values
            )
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

    sign = (
        "+"
        if delta_ms > 0
        else ""
    )

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
# BRAKE BIAS
# ============================================================

def format_bb_value(value):

    if value is None:
        return "N/A"

    if value > 0:
        return f"+{value}"

    return str(
        value
    )


def format_bb_range(range_value):

    if not range_value:
        return "N/A"

    low, high = range_value

    if low == high:
        return format_bb_value(
            low
        )

    return (
        f"{format_bb_value(low)} "
        f"to "
        f"{format_bb_value(high)}"
    )


def brake_bias_recommendation(
    car_code,
    tyre_multiplier
):

    layout = get_car_layout(
        car_code,
        CAR_TECHNICAL_DATABASE
    )

    if not layout:

        return {
            "layout":
                "Unknown",

            "qualifying_range":
                None,

            "race_range":
                None,

            "qualifying_start":
                None,

            "race_start":
                None,

            "confidence":
                "UNVALIDATED",

            "reason":
                (
                    "Car is identified, but drivetrain metadata "
                    "has not yet been validated in the central database."
                ),

            "wear_adjustment":
                "No recommendation generated."
        }

    baseline = (
        BRAKE_BIAS_BASELINES.get(
            layout
        )
    )

    if not baseline:

        return {
            "layout":
                layout,

            "qualifying_range":
                None,

            "race_range":
                None,

            "qualifying_start":
                None,

            "race_start":
                None,

            "confidence":
                "UNVALIDATED",

            "reason":
                (
                    "Validated drivetrain exists, but no "
                    "Brake Bias model is defined for this layout."
                ),

            "wear_adjustment":
                "No recommendation generated."
        }

    qual_low, qual_high = (
        baseline[
            "qualifying"
        ]
    )

    race_low, race_high = (
        baseline[
            "race"
        ]
    )

    qualifying_start = int(
        round(
            (
                qual_low
                + qual_high
            )
            / 2
        )
    )

    if tyre_multiplier <= 1:

        race_start = qualifying_start

        wear_adjustment = (
            "Low tyre wear: start close to the qualifying setting."
        )

    elif tyre_multiplier <= 2:

        race_start = int(
            round(
                (
                    race_low
                    + race_high
                )
                / 2
            )
        )

        wear_adjustment = (
            "Moderate tyre wear: use the middle of the "
            "conservative race range."
        )

    elif tyre_multiplier <= 4:

        if layout in (
            "FF",
            "FR",
            "4WD"
        ):

            race_start = race_high

            wear_adjustment = (
                "Meaningful tyre wear: start toward the rearward "
                "end of the race range to reduce front-axle load."
            )

        elif layout in (
            "MR",
            "RR"
        ):

            race_start = race_low

            wear_adjustment = (
                "Meaningful tyre wear: start toward the forward "
                "end of the race range to prioritize rear stability."
            )

        else:

            race_start = int(
                round(
                    (
                        race_low
                        + race_high
                    )
                    / 2
                )
            )

            wear_adjustment = (
                "Meaningful tyre wear: use the middle of the range."
            )

    else:

        if layout in (
            "FF",
            "FR",
            "4WD"
        ):

            race_start = race_high

            wear_adjustment = (
                "High tyre wear: begin at the rearward end of the "
                "heuristic range, without exceeding it."
            )

        elif layout in (
            "MR",
            "RR"
        ):

            race_start = race_low

            wear_adjustment = (
                "High tyre wear: begin at the forward end of the "
                "heuristic range, without exceeding it."
            )

        else:

            race_start = int(
                round(
                    (
                        race_low
                        + race_high
                    )
                    / 2
                )
            )

            wear_adjustment = (
                "High tyre wear: remain inside the conservative range."
            )

    return {
        "layout":
            layout,

        "qualifying_range":
            (
                qual_low,
                qual_high
            ),

        "race_range":
            (
                race_low,
                race_high
            ),

        "qualifying_start":
            qualifying_start,

        "race_start":
            race_start,

        "confidence":
            "HEURISTIC",

        "reason":
            baseline[
                "reason"
            ],

        "wear_adjustment":
            wear_adjustment
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

    if metric.startswith(
        "top"
    ):

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

        if isinstance(
            value,
            dict
        ):
            return value.get(
                "score"
            )

        if isinstance(
            value,
            int
        ):
            return value

        if isinstance(
            value,
            str
        ):
            return laptime_to_score(
                value
            )

    return None


# ============================================================
# FORECAST HELPERS
# ============================================================

def forecast_parse_datetime(value):

    if not value:
        return None

    try:
        return datetime.fromisoformat(
            value
        )

    except Exception:
        return None


def forecast_linear_regression(points):

    if len(points) < 2:
        return None

    xs = [
        float(x)
        for x, _
        in points
    ]

    ys = [
        float(y)
        for _, y
        in points
    ]

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

    intercept = (
        y_mean
        - slope * x_mean
    )

    residuals = [
        y
        - (
            slope * x
            + intercept
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

    return {
        "slope":
            slope,

        "intercept":
            intercept,

        "rmse":
            rmse
    }


def forecast_threshold_score(
    snapshot,
    rank
):

    value = (
        snapshot
        .get(
            "thresholds",
            {}
        )
        .get(
            str(rank)
        )
    )

    if isinstance(
        value,
        dict
    ):
        return value.get(
            "score"
        )

    if isinstance(
        value,
        (int, float)
    ):
        return value

    return None


def forecast_percentile_threshold_score(
    snapshot,
    percent
):

    value = (
        snapshot
        .get(
            "percentile_thresholds",
            {}
        )
        .get(
            str(percent)
        )
    )

    if isinstance(
        value,
        dict
    ):
        return value.get(
            "score"
        )

    if isinstance(
        value,
        (int, float)
    ):
        return value

    return None


def forecast_world_record_score(
    snapshot
):

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


def forecast_personal_score(
    snapshot
):

    result = snapshot.get(
        "my_result"
    )

    if not result:
        return None

    return result.get(
        "score"
    )


def forecast_personal_rank(
    snapshot
):

    result = snapshot.get(
        "my_result"
    )

    if not result:
        return None

    return result.get(
        "rank"
    )


def current_week_forecast_snapshots(
    history,
    current_snapshot
):

    current_url = (
        current_snapshot
        .get(
            "race",
            {}
        )
        .get(
            "leaderboard_url"
        )
    )

    combined = (
        list(history)
        + [current_snapshot]
    )

    selected = []
    seen = set()

    for snapshot in combined:

        url = (
            snapshot
            .get(
                "race",
                {}
            )
            .get(
                "leaderboard_url"
            )
        )

        if url != current_url:
            continue

        timestamp_text = snapshot.get(
            "timestamp"
        )

        timestamp = forecast_parse_datetime(
            timestamp_text
        )

        if not timestamp:
            continue

        if timestamp_text in seen:
            continue

        seen.add(
            timestamp_text
        )

        selected.append(
            snapshot
        )

    selected.sort(
        key=lambda item:
            forecast_parse_datetime(
                item[
                    "timestamp"
                ]
            )
    )

    return selected


def forecast_build_time_axis(
    snapshots,
    race_start
):

    output = []

    for snapshot in snapshots:

        timestamp = forecast_parse_datetime(
            snapshot.get(
                "timestamp"
            )
        )

        if not timestamp:
            continue

        hours = (
            timestamp
            - race_start
        ).total_seconds() / 3600

        output.append(
            (
                hours,
                snapshot
            )
        )

    return output


def forecast_metric_v2(
    snapshots,
    race_start,
    target_time,
    extractor,
    direction="down"
):

    axis = forecast_build_time_axis(
        snapshots,
        race_start
    )

    points = []

    for hours, snapshot in axis:

        value = extractor(
            snapshot
        )

        if isinstance(
            value,
            (int, float)
        ):

            points.append(
                (
                    hours,
                    float(value)
                )
            )

    if len(points) < 3:
        return None

    regression = forecast_linear_regression(
        points
    )

    if not regression:
        return None

    span_hours = (
        max(
            x
            for x, _
            in points
        )
        - min(
            x
            for x, _
            in points
        )
    )

    slope = regression[
        "slope"
    ]

    if direction == "down":
        slope = min(
            slope,
            0
        )

    elif direction == "up":
        slope = max(
            slope,
            0
        )

    target_x = (
        target_time
        - race_start
    ).total_seconds() / 3600

    predicted = (
        regression[
            "intercept"
        ]
        + slope * target_x
    )

    current_value = points[
        -1
    ][
        1
    ]

    if direction == "down":

        predicted = min(
            predicted,
            current_value
        )

    elif direction == "up":

        predicted = max(
            predicted,
            current_value
        )

    if (
        len(points) >= 10
        and span_hours >= 72
    ):

        confidence = "HIGH"

    elif (
        len(points) >= 6
        and span_hours >= 24
    ):

        confidence = "MEDIUM"

    else:

        confidence = "LOW"

    return {
        "predicted":
            predicted,

        "current":
            current_value,

        "slope_per_hour":
            slope,

        "rmse":
            regression[
                "rmse"
            ],

        "samples":
            len(points),

        "span_hours":
            span_hours,

        "confidence":
            confidence
    }


def forecast_score_at_rank(
    ranking,
    rank
):

    if not ranking:
        return None

    rank = max(
        1,
        min(
            len(ranking),
            int(rank)
        )
    )

    return ranking[
        rank - 1
    ].get(
        "score"
    )


def forecast_percentile_rank(
    total,
    percent
):

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


def forecast_current_percentile_score(
    ranking,
    percent
):

    rank = forecast_percentile_rank(
        len(ranking),
        percent
    )

    return {
        "rank":
            rank,

        "score":
            forecast_score_at_rank(
                ranking,
                rank
            )
    }


def forecast_projected_percentile_score(
    ranking,
    top500_forecast,
    top1000_forecast,
    percent
):

    current = forecast_current_percentile_score(
        ranking,
        percent
    )

    current_score = current[
        "score"
    ]

    if current_score is None:
        return None

    projected_deltas = []

    if top500_forecast:

        projected_deltas.append(
            top500_forecast[
                "predicted"
            ]
            - top500_forecast[
                "current"
            ]
        )

    if top1000_forecast:

        projected_deltas.append(
            top1000_forecast[
                "predicted"
            ]
            - top1000_forecast[
                "current"
            ]
        )

    expected_delta = (
        sum(projected_deltas)
        / len(projected_deltas)
        if projected_deltas
        else 0
    )

    confidence_values = []

    if top500_forecast:

        confidence_values.append(
            top500_forecast.get(
                "confidence",
                "LOW"
            )
        )

    if top1000_forecast:

        confidence_values.append(
            top1000_forecast.get(
                "confidence",
                "LOW"
            )
        )

    confidence = (
        "LOW"
        if not confidence_values
        else confidence_values[0]
    )

    return {
        "current_rank":
            current[
                "rank"
            ],

        "current_score":
            current_score,

        "predicted_score":
            int(
                round(
                    current_score
                    + expected_delta
                )
            ),

        "estimated_change_ms":
            int(
                round(
                    expected_delta
                )
            ),

        "mode":
            "FALLBACK",

        "confidence":
            confidence,

        "samples":
            0
    }


def build_percentile_forecast(
    snapshots,
    ranking,
    race_start,
    sunday_end,
    percent,
    top500_forecast,
    top1000_forecast
):

    direct = forecast_metric_v2(
        snapshots,
        race_start,
        sunday_end,
        extractor=lambda snapshot:
            forecast_percentile_threshold_score(
                snapshot,
                percent
            ),
        direction="down"
    )

    current = forecast_current_percentile_score(
        ranking,
        percent
    )

    if direct:

        return {
            "current_rank":
                current[
                    "rank"
                ],

            "current_score":
                current[
                    "score"
                ],

            "predicted_score":
                int(
                    round(
                        direct[
                            "predicted"
                        ]
                    )
                ),

            "estimated_change_ms":
                int(
                    round(
                        direct[
                            "predicted"
                        ]
                        - direct[
                            "current"
                        ]
                    )
                ),

            "mode":
                "DIRECT",

            "confidence":
                direct[
                    "confidence"
                ],

            "samples":
                direct[
                    "samples"
                ],

            "span_hours":
                direct[
                    "span_hours"
                ],

            "rmse":
                direct[
                    "rmse"
                ]
        }

    fallback = forecast_projected_percentile_score(
        ranking,
        top500_forecast,
        top1000_forecast,
        percent
    )

    if fallback:
        return fallback

    return None


def forecast_rank_if_no_improvement(
    snapshots,
    current_snapshot,
    race_start,
    target_time
):

    current_result = current_snapshot.get(
        "my_result"
    )

    if not current_result:
        return None

    current_score = current_result.get(
        "score"
    )

    current_rank = current_result.get(
        "rank"
    )

    if (
        current_score is None
        or current_rank is None
    ):
        return None

    comparable = []

    for snapshot in snapshots:

        score = forecast_personal_score(
            snapshot
        )

        rank = forecast_personal_rank(
            snapshot
        )

        timestamp = forecast_parse_datetime(
            snapshot.get(
                "timestamp"
            )
        )

        if (
            score == current_score
            and isinstance(
                rank,
                (int, float)
            )
            and timestamp
        ):

            comparable.append(
                snapshot
            )

    if len(comparable) < 3:

        return {
            "current_rank":
                current_rank,

            "projected_rank":
                None,

            "confidence":
                "INSUFFICIENT",

            "samples":
                len(comparable),

            "span_hours":
                0
        }

    forecast = forecast_metric_v2(
        comparable,
        race_start,
        target_time,
        extractor=forecast_personal_rank,
        direction="up"
    )

    if not forecast:
        return None

    projected_rank = max(
        current_rank,
        int(
            round(
                forecast[
                    "predicted"
                ]
            )
        )
    )

    return {
        "current_rank":
            current_rank,

        "projected_rank":
            projected_rank,

        "confidence":
            forecast[
                "confidence"
            ],

        "samples":
            forecast[
                "samples"
            ],

        "span_hours":
            forecast[
                "span_hours"
            ],

        "rank_growth_per_hour":
            forecast[
                "slope_per_hour"
            ]
    }


def forecast_total_drivers(
    snapshots,
    race_start,
    target_time
):

    forecast = forecast_metric_v2(
        snapshots,
        race_start,
        target_time,
        extractor=lambda snapshot:
            snapshot.get(
                "total_drivers"
            ),
        direction="up"
    )

    if not forecast:
        return None

    return {
        "current":
            int(
                round(
                    forecast[
                        "current"
                    ]
                )
            ),

        "predicted":
            int(
                round(
                    forecast[
                        "predicted"
                    ]
                )
            ),

        "confidence":
            forecast[
                "confidence"
            ],

        "samples":
            forecast[
                "samples"
            ]
    }


def forecast_overall_confidence(
    forecasts
):

    values = {
        "HIGH": 3,
        "MEDIUM": 2,
        "LOW": 1
    }

    scores = []

    for forecast in forecasts:

        if not forecast:
            continue

        confidence = forecast.get(
            "confidence"
        )

        if confidence in values:

            scores.append(
                values[
                    confidence
                ]
            )

    if not scores:
        return "LOW"

    average = (
        sum(scores)
        / len(scores)
    )

    if average >= 2.5:
        return "HIGH"

    if average >= 1.5:
        return "MEDIUM"

    return "LOW"


def build_forecast_v2(
    history,
    current_snapshot,
    ranking,
    race_start,
    sunday_end
):

    snapshots = current_week_forecast_snapshots(
        history,
        current_snapshot
    )

    if len(snapshots) < 3:

        return {
            "available":
                False,

            "reason":
                "Fewer than 3 comparable current-week snapshots."
        }

    wr_forecast = forecast_metric_v2(
        snapshots,
        race_start,
        sunday_end,
        extractor=forecast_world_record_score,
        direction="down"
    )

    top100_forecast = forecast_metric_v2(
        snapshots,
        race_start,
        sunday_end,
        extractor=lambda snapshot:
            forecast_threshold_score(
                snapshot,
                100
            ),
        direction="down"
    )

    top500_forecast = forecast_metric_v2(
        snapshots,
        race_start,
        sunday_end,
        extractor=lambda snapshot:
            forecast_threshold_score(
                snapshot,
                500
            ),
        direction="down"
    )

    top1000_forecast = forecast_metric_v2(
        snapshots,
        race_start,
        sunday_end,
        extractor=lambda snapshot:
            forecast_threshold_score(
                snapshot,
                1000
            ),
        direction="down"
    )

    top10 = build_percentile_forecast(
        snapshots,
        ranking,
        race_start,
        sunday_end,
        10,
        top500_forecast,
        top1000_forecast
    )

    top5 = build_percentile_forecast(
        snapshots,
        ranking,
        race_start,
        sunday_end,
        5,
        top500_forecast,
        top1000_forecast
    )

    total_forecast = forecast_total_drivers(
        snapshots,
        race_start,
        sunday_end
    )

    personal_rank_projection = (
        forecast_rank_if_no_improvement(
            snapshots,
            current_snapshot,
            race_start,
            sunday_end
        )
    )

    current_result = current_snapshot.get(
        "my_result"
    )

    personal = None

    if current_result:

        current_score = current_result.get(
            "score"
        )

        current_rank = current_result.get(
            "rank"
        )

        current_top_percent = current_result.get(
            "top_percent"
        )

        projected_rank = None
        projected_top_percent = None

        if personal_rank_projection:

            projected_rank = (
                personal_rank_projection.get(
                    "projected_rank"
                )
            )

        if (
            projected_rank is not None
            and total_forecast
        ):

            projected_total = max(
                total_forecast[
                    "predicted"
                ],
                projected_rank
            )

            projected_top_percent = (
                projected_rank
                / projected_total
                * 100
            )

        personal = {
            "score":
                current_score,

            "current_rank":
                current_rank,

            "current_top_percent":
                current_top_percent,

            "projected_rank":
                projected_rank,

            "projected_top_percent":
                projected_top_percent,

            "rank_forecast_confidence":
                (
                    personal_rank_projection.get(
                        "confidence"
                    )
                    if personal_rank_projection
                    else "INSUFFICIENT"
                )
        }

    targets = {}

    if (
        current_result
        and current_result.get(
            "score"
        )
    ):

        personal_score = current_result[
            "score"
        ]

        if top10:

            targets[
                "top10"
            ] = {
                "score":
                    top10[
                        "predicted_score"
                    ],

                "gain_needed_ms":
                    max(
                        0,
                        personal_score
                        - top10[
                            "predicted_score"
                        ]
                    ),

                "mode":
                    top10.get(
                        "mode",
                        "UNKNOWN"
                    )
            }

        if top5:

            targets[
                "top5"
            ] = {
                "score":
                    top5[
                        "predicted_score"
                    ],

                "gain_needed_ms":
                    max(
                        0,
                        personal_score
                        - top5[
                            "predicted_score"
                        ]
                    ),

                "mode":
                    top5.get(
                        "mode",
                        "UNKNOWN"
                    )
            }

    confidence = forecast_overall_confidence(
        [
            wr_forecast,
            top100_forecast,
            top500_forecast,
            top1000_forecast,
            total_forecast,
            top10,
            top5
        ]
    )

    timestamps = [
        forecast_parse_datetime(
            snapshot.get(
                "timestamp"
            )
        )
        for snapshot in snapshots
    ]

    timestamps = [
        timestamp
        for timestamp in timestamps
        if timestamp
    ]

    span_hours = 0

    if len(timestamps) >= 2:

        span_hours = (
            max(timestamps)
            - min(timestamps)
        ).total_seconds() / 3600

    return {
        "available":
            True,

        "model":
            "CURRENT_WEEK_HYBRID_V2",

        "historical_training":
            "INSUFFICIENT",

        "samples":
            len(snapshots),

        "span_hours":
            span_hours,

        "confidence":
            confidence,

        "world_record":
            wr_forecast,

        "top100":
            top100_forecast,

        "top500":
            top500_forecast,

        "top1000":
            top1000_forecast,

        "top10_percent":
            top10,

        "top5_percent":
            top5,

        "total_drivers":
            total_forecast,

        "personal":
            personal,

        "targets":
            targets
    }


# ============================================================
# FORECAST REPORT
# ============================================================

def forecast_report_lines(
    forecast
):

    lines = []

    lines.append(
        "FORECAST TO SUNDAY - V2"
    )

    if not forecast.get(
        "available"
    ):

        lines.append(
            forecast.get(
                "reason",
                "Forecast unavailable."
            )
        )

        return lines

    lines.append(
        f"Model           : "
        f"{forecast['model']}"
    )

    lines.append(
        f"Confidence      : "
        f"{forecast['confidence']}"
    )

    lines.append(
        f"Samples         : "
        f"{forecast['samples']}"
    )

    lines.append(
        f"Observed span   : "
        f"{forecast['span_hours']:.1f} h"
    )

    lines.append(
        "Historical model: not yet active "
        "(insufficient cross-week training data)"
    )

    lines.append("")
    lines.append(
        "PROJECTED LEADERBOARD"
    )

    metrics = [
        (
            "world_record",
            "WR"
        ),
        (
            "top100",
            "Top 100"
        ),
        (
            "top500",
            "Top 500"
        ),
        (
            "top1000",
            "Top 1000"
        )
    ]

    for key, label in metrics:

        item = forecast.get(
            key
        )

        if not item:
            continue

        lines.append(
            f"{label:<15}: "
            f"{score_to_laptime(item['predicted'])} | "
            f"{item['confidence']} | "
            f"{item['samples']} samples"
        )

    top10 = forecast.get(
        "top10_percent"
    )

    if top10:

        lines.append(
            f"{'Top 10%':<15}: "
            f"{score_to_laptime(top10['predicted_score'])} | "
            f"{top10.get('mode','UNKNOWN')} | "
            f"{top10.get('confidence','LOW')}"
        )

    top5 = forecast.get(
        "top5_percent"
    )

    if top5:

        lines.append(
            f"{'Top 5%':<15}: "
            f"{score_to_laptime(top5['predicted_score'])} | "
            f"{top5.get('mode','UNKNOWN')} | "
            f"{top5.get('confidence','LOW')}"
        )

    total = forecast.get(
        "total_drivers"
    )

    if total:

        lines.append(
            f"{'Drivers':<15}: "
            f"{total['current']:,} -> "
            f"~{total['predicted']:,}"
        )

    personal = forecast.get(
        "personal"
    )

    if personal:

        lines.append("")
        lines.append(
            "IF YOU DO NOT IMPROVE"
        )

        lines.append(
            f"Current time    : "
            f"{score_to_laptime(personal['score'])}"
        )

        lines.append(
            f"Current rank    : "
            f"#{personal['current_rank']:,}"
        )

        if (
            personal[
                "current_top_percent"
            ]
            is not None
        ):

            lines.append(
                f"Current Top %   : "
                f"{personal['current_top_percent']:.2f}%"
            )

        if (
            personal[
                "projected_rank"
            ]
            is not None
        ):

            lines.append(
                f"Projected rank  : "
                f"~#{personal['projected_rank']:,}"
            )

        else:

            lines.append(
                "Projected rank  : "
                "insufficient comparable rank history"
            )

        if (
            personal[
                "projected_top_percent"
            ]
            is not None
        ):

            lines.append(
                f"Projected Top % : "
                f"~{personal['projected_top_percent']:.2f}%"
            )

        lines.append(
            f"Rank confidence : "
            f"{personal['rank_forecast_confidence']}"
        )

    targets = forecast.get(
        "targets",
        {}
    )

    if targets:

        lines.append("")
        lines.append(
            "TARGETS FOR SUNDAY"
        )

        if "top10" in targets:

            target = targets[
                "top10"
            ]

            lines.append(
                f"Top 10% target  : "
                f"{score_to_laptime(target['score'])} | "
                f"gain needed "
                f"{target['gain_needed_ms']/1000:.3f}s | "
                f"{target.get('mode','UNKNOWN')}"
            )

        if "top5" in targets:

            target = targets[
                "top5"
            ]

            lines.append(
                f"Top 5% target   : "
                f"{score_to_laptime(target['score'])} | "
                f"gain needed "
                f"{target['gain_needed_ms']/1000:.3f}s | "
                f"{target.get('mode','UNKNOWN')}"
            )

    lines.append("")

    lines.append(
        "Percentile mode : "
        "DIRECT = forecast learned from the observed Top 5%/10% series; "
        "FALLBACK = inferred from Top 500/1000 until enough direct snapshots exist."
    )

    lines.append(
        "Forecast note   : "
        "V2 uses current-week leaderboard evolution. "
        "Cross-week historical learning will activate "
        "after sufficient multi-week intraday data exists."
    )

    return lines


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

    total = len(
        ranking
    )

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

            unique_targets[
                rank
            ] = label

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
                unique_targets[
                    rank
                ],

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

    return results[
        :4
    ]


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
        for driver in ranking
        if predicate(
            driver
        )
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

    total = len(
        ranking
    )

    top100_total = min(
        100,
        total
    )

    top1000_total = min(
        1000,
        total
    )

    rows = []

    for (
        car_code,
        all_count
    ) in all_counter.items():

        overall_share = (
            all_count
            / total
        )

        if overall_share <= 0:
            continue

        top100_count = (
            top100_counter.get(
                car_code,
                0
            )
        )

        top1000_count = (
            top1000_counter.get(
                car_code,
                0
            )
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
            oi100
            * 0.70
            + oi1000
            * 0.30
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

def best_driver_by_car(
    ranking
):

    result = {}

    for driver in ranking:

        car_code = get_car_code(
            driver
        )

        if (
            car_code is not None
            and car_code not in result
        ):

            result[
                car_code
            ] = driver

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
            f"{unknown_share:.1f}% of valid leaderboard entries."
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
    global CAR_TECHNICAL_DATABASE

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

    # Final hard stop before any leaderboard request.

    validate_selected_race_c(
        race_c
    )

    race_c_link = race_c[
        "url"
    ]

    race_c_text = race_c[
        "text"
    ]

    race_detection_mode = race_c[
        "detection_mode"
    ]

    print(
        "=" * 78
    )

    print(
        "RACE C SAFETY CHECK"
    )

    print(
        "=" * 78
    )

    print(
        "Expected         : Daily Race C"
    )

    print(
        "Detected         : Daily Race C"
    )

    print(
        f"Status           : "
        f"{'Running' if race_c.get('running') else 'Current week'}"
    )

    print(
        f"Detection mode   : "
        f"{race_detection_mode}"
    )

    print(
        f"Race date        : "
        f"{race_c.get('date')}"
    )

    print(
        f"Description      : "
        f"{race_c_text}"
    )

    print(
        f"Leaderboard URL  : "
        f"{race_c_link}"
    )

    print(
        "Validation       : PASSED"
    )

    print(
        "=" * 78
    )

    # ========================================================
    # LEADERBOARD PAGE
    # ========================================================

    leaderboard_response = session.get(
        race_c_link,
        timeout=60
    )

    leaderboard_response.raise_for_status()

    html = leaderboard_response.text

    # ========================================================
    # CAR DATABASE UPDATE
    # ========================================================

    try:

        car_update = update_car_database_from_html(
            html
        )

        CAR_DATABASE = car_update[
            "database"
        ]

        CAR_TECHNICAL_DATABASE = (
            load_car_technical_database()
        )

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

        CAR_DATABASE = load_car_database()

        CAR_TECHNICAL_DATABASE = (
            load_car_technical_database()
        )

        cars_discovered_this_run = 0
        cars_added_this_run = 0
        cars_updated_this_run = 0

    # ========================================================
    # EXTRACT RANKING - LIVE PAGE_DATA FIRST
    # ========================================================

    # GTSH may embed a stale initialRanking in the leaderboard HTML.
    # The page_data endpoint is the live source used by the site itself,
    # so it is now the PRIMARY source. initialRanking and update=1 are
    # retained only as fallbacks.

    ranking = None
    source_mode = None
    live_total_drivers = None

    def extract_page_data_payload(payload):

        entries = None
        total = None
        returned_offset = None
        returned_limit = None
        has_more = None

        if isinstance(payload, list):
            entries = payload

        elif isinstance(payload, dict):

            # Known/likely list keys used by leaderboard APIs.
            for key in (
                "board",
                "ranking",
                "data",
                "entries",
                "results",
                "drivers"
            ):
                value = payload.get(key)
                if isinstance(value, list):
                    entries = value
                    break

            # Some responses wrap the useful object one level deeper.
            if entries is None:
                for wrapper_key in (
                    "page",
                    "result",
                    "payload"
                ):
                    wrapper = payload.get(wrapper_key)
                    if not isinstance(wrapper, dict):
                        continue

                    for key in (
                        "board",
                        "ranking",
                        "data",
                        "entries",
                        "results",
                        "drivers"
                    ):
                        value = wrapper.get(key)
                        if isinstance(value, list):
                            entries = value
                            payload = wrapper
                            break

                    if entries is not None:
                        break

            for key in (
                "total",
                "total_drivers",
                "totalDrivers",
                "count",
                "recordsTotal"
            ):
                value = payload.get(key)
                if isinstance(value, (int, float)):
                    total = int(value)
                    break

            for key in ("offset", "start"):
                value = payload.get(key)
                if isinstance(value, (int, float)):
                    returned_offset = int(value)
                    break

            for key in ("limit", "page_size", "pageSize"):
                value = payload.get(key)
                if isinstance(value, (int, float)):
                    returned_limit = int(value)
                    break

            for key in ("has_more", "hasMore", "more"):
                value = payload.get(key)
                if isinstance(value, bool):
                    has_more = value
                    break

        return (
            entries,
            total,
            returned_offset,
            returned_limit,
            has_more
        )

    # --------------------------------------------------------
    # 1. PRIMARY SOURCE: LIVE page_data=1
    # --------------------------------------------------------

    try:

        live_ranking = []
        seen_ranks = set()
        offset = 0

        # Ask for a large page. If GTSH caps the page size, the loop
        # advances by the number of entries actually returned.
        requested_limit = 1000
        max_pages = 1000

        for page_number in range(max_pages):

            separator = (
                "&"
                if "?" in race_c_link
                else "?"
            )

            page_url = (
                race_c_link
                + separator
                + "page_data=1"
                + f"&offset={offset}"
                + f"&limit={requested_limit}"
            )

            page_response = session.get(
                page_url,
                timeout=60
            )

            page_response.raise_for_status()

            page_payload = page_response.json()

            (
                page_entries,
                page_total,
                returned_offset,
                returned_limit,
                has_more
            ) = extract_page_data_payload(
                page_payload
            )

            if page_total is not None:
                live_total_drivers = page_total

            if not isinstance(page_entries, list):
                raise RuntimeError(
                    "page_data response did not contain a ranking list."
                )

            if not page_entries:
                break

            added_this_page = 0

            for driver in page_entries:

                if not isinstance(driver, dict):
                    continue

                rank = driver.get(
                    "display_rank"
                )

                # Prefer rank as a stable deduplication key.
                if isinstance(rank, (int, float)):
                    rank_key = int(rank)

                    if rank_key in seen_ranks:
                        continue

                    seen_ranks.add(rank_key)

                live_ranking.append(driver)
                added_this_page += 1

            if added_this_page == 0:
                break

            # Stop when the server tells us that the complete live
            # leaderboard has been collected.
            if (
                live_total_drivers is not None
                and len(live_ranking) >= live_total_drivers
            ):
                break

            if has_more is False:
                break

            # Advance using the number of records actually returned.
            # This remains correct even if GTSH ignores/caps limit=1000.
            next_offset = offset + len(page_entries)

            if next_offset <= offset:
                break

            offset = next_offset

        if live_ranking:

            ranking = live_ranking
            source_mode = "live_page_data"

            print(
                f"Leaderboard source: LIVE page_data | "
                f"entries={len(ranking):,} | "
                f"server_total={live_total_drivers}"
            )

    except Exception as exc:

        print(
            "WARNING: live page_data leaderboard failed: "
            f"{exc}"
        )

        ranking = None

    # --------------------------------------------------------
    # 2. FALLBACK: initialRanking embedded in HTML
    # --------------------------------------------------------

    if not ranking:

        marker = "const initialRanking = "

        start = html.find(
            marker
        )

        if start != -1:

            try:

                start += len(
                    marker
                )

                decoder = json.JSONDecoder()

                candidate_ranking, _ = decoder.raw_decode(
                    html[
                        start:
                    ].lstrip()
                )

                if isinstance(candidate_ranking, list) and candidate_ranking:

                    ranking = candidate_ranking
                    source_mode = "initialRanking_fallback"

                    print(
                        "WARNING: using HTML initialRanking fallback | "
                        f"entries={len(ranking):,}"
                    )

            except Exception as exc:

                print(
                    "WARNING: initialRanking fallback failed: "
                    f"{exc}"
                )

    # --------------------------------------------------------
    # 3. LAST FALLBACK: update=1 endpoint
    # --------------------------------------------------------

    if not ranking:

        try:

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

            update_data = update_response.json()

            if isinstance(update_data, list):

                ranking = update_data

            elif isinstance(update_data, dict):

                candidate = (
                    update_data.get(
                        "board"
                    )
                    or update_data.get(
                        "ranking"
                    )
                    or update_data.get(
                        "data"
                    )
                    or update_data.get(
                        "entries"
                    )
                )

                if isinstance(candidate, list):
                    ranking = candidate

            if ranking:

                source_mode = "update_endpoint_fallback"

                print(
                    "WARNING: using update=1 fallback | "
                    f"entries={len(ranking):,}"
                )

        except Exception as exc:

            print(
                "WARNING: update=1 fallback failed: "
                f"{exc}"
            )

    if not ranking:

        raise RuntimeError(
            "Leaderboard contains no drivers from live page_data, "
            "initialRanking, or update=1."
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
    # FIXED-RANK THRESHOLDS
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
    # DIRECT PERCENTILES
    # ========================================================

    percentile_thresholds = {}

    for percent in [
        10,
        5
    ]:

        percentile_rank_value = forecast_percentile_rank(
            len(ranking),
            percent
        )

        percentile_score_value = forecast_score_at_rank(
            ranking,
            percentile_rank_value
        )

        percentile_thresholds[
            str(percent)
        ] = {
            "percent":
                percent,

            "rank":
                percentile_rank_value,

            "score":
                percentile_score_value,

            "laptime":
                score_to_laptime(
                    percentile_score_value
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
    my_brake_bias = None

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

        (
            same_car_rank,
            same_car_total
        ) = group_rank(
            ranking,
            lambda driver:
                get_car_code(
                    driver
                )
                == my_car_code,
            my_driver
        )

        (
            country_rank,
            country_total
        ) = group_rank(
            ranking,
            lambda driver:
                get_user(
                    driver
                ).get(
                    "country_code"
                )
                == my_country,
            my_driver
        )

        (
            dr_rank,
            dr_total
        ) = group_rank(
            ranking,
            lambda driver:
                get_user(
                    driver
                ).get(
                    "driver_rating"
                )
                == my_dr,
            my_driver
        )

        my_brake_bias = brake_bias_recommendation(
            my_car_code,
            tyre_multiplier
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
        get_car_code(
            driver
        )
        for driver in ranking
        if get_car_code(
            driver
        ) is not None
    )

    top100 = ranking[:100]
    top1000 = ranking[:1000]

    top100_counter = Counter(
        get_car_code(
            driver
        )
        for driver in top100
        if get_car_code(
            driver
        ) is not None
    )

    top1000_counter = Counter(
        get_car_code(
            driver
        )
        for driver in top1000
        if get_car_code(
            driver
        ) is not None
    )

    # ========================================================
    # TOP 5 USED CARS + BRAKE BIAS
    # ========================================================

    top5_used_cars = []

    for (
        car_code,
        count
    ) in (
        top1000_counter
        .most_common(
            5
        )
    ):

        bb = brake_bias_recommendation(
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
                bb[
                    "layout"
                ],

            "qualifying_range":
                bb[
                    "qualifying_range"
                ],

            "race_range":
                bb[
                    "race_range"
                ],

            "qualifying_start":
                bb[
                    "qualifying_start"
                ],

            "race_start":
                bb[
                    "race_start"
                ],

            "confidence":
                bb[
                    "confidence"
                ],

            "reason":
                bb[
                    "reason"
                ],

            "wear_adjustment":
                bb[
                    "wear_adjustment"
                ]
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
            .most_common(
                1
            )[0][0]
            if top1000_counter
            else None
        )

        my_car_best = best_by_car.get(
            my_code
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
                    my_result[
                        "score"
                    ]
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

    previous = load_previous_snapshot()

    # ========================================================
    # HEALTH
    # ========================================================

    unknown_count = sum(
        count
        for (
            car_code,
            count
        ) in all_counter.items()
        if (
            isinstance(
                car_code,
                int
            )
            and car_code > 0
            and car_code not in CAR_DATABASE
        )
    )

    invalid_car_code_count = sum(
        count
        for (
            car_code,
            count
        ) in all_counter.items()
        if (
            not isinstance(
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

            "safety_validation":
                "PASSED",

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

        "percentile_thresholds":
            percentile_thresholds,

        "my_result":
            my_result,

        "my_brake_bias":
            my_brake_bias,

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
            credible_overperformance[
                :10
            ],

        "car_comparison":
            car_comparison,

        "car_database": {
            "total_known_cars":
                len(
                    CAR_DATABASE
                ),

            "technical_records":
                len(
                    CAR_TECHNICAL_DATABASE
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

            "race_safety_validation":
                "PASSED",

            "leaderboard_entries":
                len(ranking),

            "my_driver_found":
                my_driver
                is not None
        }
    }

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

    forecast_v2 = {
        "available":
            False,

        "reason":
            "Race start date unavailable."
    }

    if start_date:

        sunday_end = (
            start_date
            + timedelta(
                days=6
            )
        ).replace(
            hour=23,
            minute=59,
            second=0
        )

        if sunday_end > now:

            forecast_v2 = build_forecast_v2(
                history=history,
                current_snapshot=snapshot,
                ranking=ranking,
                race_start=start_date,
                sunday_end=sunday_end
            )

            snapshot[
                "forecast_target"
            ] = sunday_end.isoformat()

        else:

            forecast_v2 = {
                "available":
                    False,

                "reason":
                    "The race week has already ended."
            }

    snapshot[
        "forecast_v2"
    ] = forecast_v2

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
    # REPORT
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
        "Race validation: PASSED - Daily Race C only"
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
            and country_stats[
                "rank"
            ]
        ):

            lines.append(
                f"Country rank    : "
                f"#{country_stats['rank']:,} "
                f"of {country_stats['total']:,} "
                f"({country_stats['country']})"
            )

        if (
            dr_stats
            and dr_stats[
                "rank"
            ]
        ):

            lines.append(
                f"DR rank         : "
                f"#{dr_stats['rank']:,} "
                f"of {dr_stats['total']:,} "
                f"(DR {dr_stats['dr']})"
            )

        if (
            same_car_stats
            and same_car_stats[
                "rank"
            ]
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

        for (
            index,
            target
        ) in enumerate(
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
    # YOUR CAR VS META
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

    for (
        index,
        car
    ) in enumerate(
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

    for (
        index,
        car
    ) in enumerate(
        credible_overperformance[
            :5
        ],
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
    # BRAKE BIAS
    # ========================================================

    lines.append("")
    lines.append(
        "YOUR BRAKE BIAS STARTING POINT"
    )

    lines.append(
        "Convention: negative = more front, "
        "positive = more rear."
    )

    if (
        my_result
        and my_brake_bias
    ):

        lines.append(
            f"Car             : "
            f"{my_result['car']}"
        )

        lines.append(
            f"Drivetrain      : "
            f"{my_brake_bias['layout']}"
        )

        lines.append(
            f"Qualifying range: "
            f"{format_bb_range(my_brake_bias['qualifying_range'])}"
        )

        lines.append(
            f"Qualifying start: "
            f"{format_bb_value(my_brake_bias['qualifying_start'])}"
        )

        lines.append(
            f"Race range      : "
            f"{format_bb_range(my_brake_bias['race_range'])}"
        )

        lines.append(
            f"Race start      : "
            f"{format_bb_value(my_brake_bias['race_start'])}"
        )

        lines.append(
            f"Confidence      : "
            f"{my_brake_bias['confidence']}"
        )

        lines.append(
            f"Wear adjustment : "
            f"{my_brake_bias['wear_adjustment']}"
        )

        lines.append(
            f"Rationale       : "
            f"{my_brake_bias['reason']}"
        )

    else:

        lines.append(
            "No personal Brake Bias recommendation available."
        )

    lines.append("")
    lines.append(
        "BRAKE BIAS - TOP 5 USED CARS"
    )

    lines.append(
        "Conservative heuristic starting ranges, "
        "not telemetry-proven optimum settings."
    )

    for (
        index,
        car
    ) in enumerate(
        top5_used_cars,
        start=1
    ):

        lines.append(
            f"{index}. "
            f"{car['car']} | "
            f"{car['layout']} | "
            f"Quali "
            f"{format_bb_range(car['qualifying_range'])} "
            f"(start {format_bb_value(car['qualifying_start'])}) | "
            f"Race "
            f"{format_bb_range(car['race_range'])} "
            f"(start {format_bb_value(car['race_start'])}) | "
            f"{car['confidence']}"
        )

    # ========================================================
    # STRATEGY FLAGS
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
            "Tyre wear is low."
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

    lines.extend(
        forecast_report_lines(
            forecast_v2
        )
    )

    # ========================================================
    # LONG-TERM RATING
    # ========================================================

    lines.append("")
    lines.append(
        "LONG-TERM RATING TREND"
    )

    lines.append(
        "Higher General, Elite and Composite ratings are better."
    )

    lines.append(
        "Lower Top % and WR % are better."
    )

    lines.append(
        "Only FINAL Sunday ratings are used "
        "for historical trend calculations."
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

        lines.append("")
        lines.append(
            "CURRENT WEEK"
        )

        lines.append(
            f"General    : "
            f"{my_result['position_score']:.2f}"
        )

        lines.append(
            f"Elite      : "
            f"{my_result['elite_score']:.2f}"
        )

        lines.append(
            f"Composite  : "
            f"{my_result['composite_rating']:.2f}"
        )

        lines.append(
            f"Top %      : "
            f"{my_result['top_percent']:.2f}%"
        )

        lines.append(
            f"WR %       : "
            f"{my_result['wr_percentage']:.3f}%"
        )

    current_assessment = None
    composite_trend = None
    wr_trend = None

    if weekly_history:

        latest_final = weekly_history[
            -1
        ]

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

        if my_result:

            current_general = my_result.get(
                "position_score"
            )

            current_elite = my_result.get(
                "elite_score"
            )

            current_composite = my_result.get(
                "composite_rating"
            )

            current_top = my_result.get(
                "top_percent"
            )

            current_wr = my_result.get(
                "wr_percentage"
            )

            last_general = latest_final.get(
                "general_score"
            )

            last_elite = latest_final.get(
                "elite_score"
            )

            last_composite = latest_final.get(
                "composite_rating"
            )

            last_top = latest_final.get(
                "top_percent"
            )

            last_wr = latest_final.get(
                "wr_percentage"
            )

            lines.append("")
            lines.append(
                "CURRENT WEEK VS LAST FINALIZED WEEK"
            )

            delta_general = (
                current_general
                - last_general
            )

            delta_elite = (
                current_elite
                - last_elite
            )

            delta_composite = (
                current_composite
                - last_composite
            )

            delta_top = (
                current_top
                - last_top
            )

            delta_wr = (
                current_wr
                - last_wr
            )

            lines.append(
                f"General    : "
                f"{last_general:.2f} -> "
                f"{current_general:.2f} "
                f"({delta_general:+.2f}) | "
                f"{'BETTER' if delta_general > 0.01 else 'WORSE' if delta_general < -0.01 else 'STABLE'}"
            )

            lines.append(
                f"Elite      : "
                f"{last_elite:.2f} -> "
                f"{current_elite:.2f} "
                f"({delta_elite:+.2f}) | "
                f"{'BETTER' if delta_elite > 0.01 else 'WORSE' if delta_elite < -0.01 else 'STABLE'}"
            )

            lines.append(
                f"Composite  : "
                f"{last_composite:.2f} -> "
                f"{current_composite:.2f} "
                f"({delta_composite:+.2f}) | "
                f"{'BETTER' if delta_composite > 0.01 else 'WORSE' if delta_composite < -0.01 else 'STABLE'}"
            )

            lines.append(
                f"Top %      : "
                f"{last_top:.2f}% -> "
                f"{current_top:.2f}% "
                f"({delta_top:+.2f} pp) | "
                f"{'BETTER' if delta_top < -0.05 else 'WORSE' if delta_top > 0.05 else 'STABLE'}"
            )

            lines.append(
                f"WR %       : "
                f"{last_wr:.3f}% -> "
                f"{current_wr:.3f}% "
                f"({delta_wr:+.3f} pp) | "
                f"{'BETTER' if delta_wr < -0.01 else 'WORSE' if delta_wr > 0.01 else 'STABLE'}"
            )

            assessment_score = 0

            if delta_composite > 0.05:
                assessment_score += 2

            elif delta_composite < -0.05:
                assessment_score -= 2

            if delta_top < -0.50:
                assessment_score += 1

            elif delta_top > 0.50:
                assessment_score -= 1

            if delta_wr < -0.05:
                assessment_score += 1

            elif delta_wr > 0.05:
                assessment_score -= 1

            if assessment_score >= 2:

                current_assessment = (
                    "ABOVE LAST WEEK"
                )

            elif assessment_score <= -2:

                current_assessment = (
                    "BELOW LAST WEEK"
                )

            else:

                current_assessment = (
                    "SIMILAR TO LAST WEEK"
                )

            lines.append("")

            lines.append(
                f"Current week assessment : "
                f"{current_assessment}"
            )

        if len(
            weekly_history
        ) >= 2:

            previous_final = weekly_history[
                -2
            ]

            lines.append("")
            lines.append(
                "LATEST FINALIZED WEEK VS PRIOR FINALIZED WEEK"
            )

            lines.append(
                f"General    : "
                f"{previous_final['general_score']:.2f} -> "
                f"{latest_final['general_score']:.2f} "
                f"({latest_final['general_score'] - previous_final['general_score']:+.2f})"
            )

            lines.append(
                f"Elite      : "
                f"{previous_final['elite_score']:.2f} -> "
                f"{latest_final['elite_score']:.2f} "
                f"({latest_final['elite_score'] - previous_final['elite_score']:+.2f})"
            )

            lines.append(
                f"Composite  : "
                f"{previous_final['composite_rating']:.2f} -> "
                f"{latest_final['composite_rating']:.2f} "
                f"({latest_final['composite_rating'] - previous_final['composite_rating']:+.2f})"
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

        avg4_top = average_metric(
            weekly_history,
            "top_percent",
            4
        )

        avg4_wr = average_metric(
            weekly_history,
            "wr_percentage",
            4
        )

        lines.append("")
        lines.append(
            "4-WEEK FINALIZED MOVING AVERAGE"
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

        lines.append(
            f"Top %      : "
            f"{avg4_top:.2f}%"
        )

        lines.append(
            f"WR %       : "
            f"{avg4_wr:.3f}%"
        )

        general_trend = metric_trend(
            weekly_history,
            "general_score"
        )

        elite_trend = metric_trend(
            weekly_history,
            "elite_score"
        )

        composite_trend = metric_trend(
            weekly_history,
            "composite_rating"
        )

        top_trend = metric_trend(
            weekly_history,
            "top_percent",
            higher_is_better=False
        )

        wr_trend = metric_trend(
            weekly_history,
            "wr_percentage",
            higher_is_better=False
        )

        lines.append("")
        lines.append(
            "8-WEEK FINALIZED TREND"
        )

        lines.append(
            f"General    : "
            f"{general_trend}"
        )

        lines.append(
            f"Elite      : "
            f"{elite_trend}"
        )

        lines.append(
            f"Composite  : "
            f"{composite_trend}"
        )

        lines.append(
            f"Top %      : "
            f"{top_trend}"
        )

        lines.append(
            f"WR %       : "
            f"{wr_trend}"
        )

        if current_assessment:

            lines.append("")
            lines.append(
                "PERFORMANCE SUMMARY"
            )

            lines.append(
                f"Current week vs last final : "
                f"{current_assessment}"
            )

            lines.append(
                f"Long-term Composite trend  : "
                f"{composite_trend}"
            )

            lines.append(
                f"Long-term WR % trend       : "
                f"{wr_trend}"
            )

            if (
                current_assessment
                == "BELOW LAST WEEK"
                and composite_trend
                == "IMPROVING"
            ):

                interpretation = (
                    "Short-term pullback inside an "
                    "improving long-term trend."
                )

            elif (
                current_assessment
                == "ABOVE LAST WEEK"
                and composite_trend
                == "IMPROVING"
            ):

                interpretation = (
                    "Current performance confirms the "
                    "improving long-term trend."
                )

            elif (
                current_assessment
                == "BELOW LAST WEEK"
                and composite_trend
                == "DECLINING"
            ):

                interpretation = (
                    "Current performance reinforces the "
                    "declining long-term trend."
                )

            elif (
                current_assessment
                == "ABOVE LAST WEEK"
                and composite_trend
                == "DECLINING"
            ):

                interpretation = (
                    "Short-term recovery inside a "
                    "declining long-term trend."
                )

            else:

                interpretation = (
                    "Current performance is broadly "
                    "consistent with recent history."
                )

            lines.append(
                f"Interpretation               : "
                f"{interpretation}"
            )

        lines.append("")
        lines.append(
            "LAST FINALIZED RACES"
        )

        for record in weekly_history[
            -8:
        ]:

            lines.append(
                f"{record.get('week_start','N/A')} | "
                f"Gen {record.get('general_score',0):.2f} | "
                f"Elite {record.get('elite_score',0):.2f} | "
                f"Comp {record.get('composite_rating',0):.2f} | "
                f"Top {record.get('top_percent',0):.2f}% | "
                f"WR {record.get('wr_percentage',0):.3f}%"
            )

    else:

        lines.append("")
        lines.append(
            "No finalized weekly races recorded yet."
        )

    # ========================================================
    # CHANGES SINCE PREVIOUS SNAPSHOT
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
    # DATA QUALITY
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
        "Race validation: PASSED"
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
        f"Technical DB   : "
        f"{len(CAR_TECHNICAL_DATABASE):,} validated/known records"
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

    lines.append(
        f"Percentile data: "
        f"Top 10% and Top 5% direct snapshot stored"
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
    # EMAIL SUBJECT
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