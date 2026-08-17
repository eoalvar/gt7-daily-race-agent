#!/usr/bin/env python3

from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

import recover_historical_race as recovery


# ======================================================================================
# CONFIGURATION
# ======================================================================================

VERSION = "1.0"

GTSH_URL = "https://gtsh-rank.com/daily/"

MY_PSN_ID = "crazy_rooster74"

SAO_PAULO = ZoneInfo(
    "America/Sao_Paulo"
)

HEADERS = {
    "User-Agent":
        "Mozilla/5.0 (GT7 Previous Week Finalizer)"
}

DATA_DIR = Path("data")
REPORT_DIR = Path("reports")

WEEKLY_HISTORY_FILE = (
    DATA_DIR
    / "weekly_rating_history.json"
)

OUTPUT_JSON = (
    DATA_DIR
    / "previous_week_final.json"
)

OUTPUT_REPORT = (
    REPORT_DIR
    / "previous_week_final.txt"
)

SEPARATOR = "=" * 78


# ======================================================================================
# DATE HELPERS
# ======================================================================================

def monday_of_week(
    value: datetime,
) -> datetime:

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
        microsecond=0,
    )


def parse_race_date(
    text: str,
):

    return recovery.parse_date_from_text(
        text
    ) if hasattr(
        recovery,
        "parse_date_from_text"
    ) else None


def parse_date_fallback(
    text: str,
):

    import re

    match = re.search(
        r"(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})",
        text,
    )

    if not match:
        return None

    try:

        parsed = datetime.strptime(
            match.group(1),
            "%d %b %Y",
        )

        return parsed.replace(
            tzinfo=SAO_PAULO
        )

    except ValueError:

        return None


def race_date_from_text(
    text: str,
):

    result = parse_race_date(
        text
    )

    if result:
        return result

    return parse_date_fallback(
        text
    )


# ======================================================================================
# ARCHIVE DISCOVERY
# ======================================================================================

def discover_previous_race_c(
    session: requests.Session,
    target_monday: datetime,
):

    print("")
    print(
        "DISCOVERING PREVIOUS DAILY RACE C"
    )
    print(
        "-" * 78
    )

    max_pages = 8

    candidates = []

    for page in range(
        1,
        max_pages + 1,
    ):

        if page == 1:

            url = GTSH_URL

        else:

            url = (
                f"{GTSH_URL}"
                f"?page={page}&q="
            )

        print(
            f"Archive page     : {page}"
        )

        response = session.get(
            url,
            timeout=30,
        )

        response.raise_for_status()

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        links = soup.select(
            'a[href*="/daily/leaderboard?event="], '
            'a[href*="/daily/leaderboard/?event="]'
        )

        for link in links:

            parent = link.parent

            if parent is None:
                continue

            text = parent.get_text(
                " ",
                strip=True,
            )

            if (
                "Daily Race C"
                not in text
            ):
                continue

            race_date = (
                race_date_from_text(
                    text
                )
            )

            if not race_date:
                continue

            href = link.get(
                "href"
            )

            if not href:
                continue

            full_url = urljoin(
                GTSH_URL,
                href,
            )

            candidates.append(
                {
                    "date":
                        race_date,

                    "text":
                        text,

                    "url":
                        full_url,
                }
            )

            if (
                race_date.date()
                == target_monday.date()
            ):

                return {
                    "date":
                        race_date,

                    "text":
                        text,

                    "url":
                        full_url,
                }

    available = sorted(
        {
            item[
                "date"
            ].date().isoformat()
            for item in candidates
        }
    )

    raise RuntimeError(
        "Could not find the previous week's Daily Race C. "
        f"Target week: {target_monday.date()}. "
        f"Available Race C dates: {available[-10:]}"
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


def find_existing_final(
    history,
    target_week: str,
):

    for record in history:

        if (
            record.get(
                "week_start"
            )
            != target_week
        ):
            continue

        mode = str(
            record.get(
                "finalization_mode",
                ""
            )
        )

        if mode.startswith(
            "historical_"
        ):
            return record

    return None


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

            history[index] = record

            save_weekly_history(
                history
            )

            return

    history.append(
        record
    )

    save_weekly_history(
        history
    )


# ======================================================================================
# GROUP RANK
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

    target = (
        recovery
        .get_online_id(
            my_driver
        )
        .strip()
        .lower()
    )

    for index, driver in enumerate(
        group,
        start=1,
    ):

        current = (
            recovery
            .get_online_id(
                driver
            )
            .strip()
            .lower()
        )

        if current == target:

            return (
                index,
                len(group),
            )

    return (
        None,
        len(group),
    )


# ======================================================================================
# BUILD FINAL RECORD
# ======================================================================================

def build_final_record(
    event,
    ranking,
    total_records,
    extraction_mode,
):

    if not ranking:

        raise RuntimeError(
            "Historical leaderboard is empty."
        )

    winner = ranking[0]

    wr_score = winner.get(
        "score"
    )

    if not wr_score:

        raise RuntimeError(
            "Historical world record score is missing."
        )

    my_driver = (
        recovery.find_my_driver(
            ranking,
            MY_PSN_ID,
        )
    )

    if not my_driver:

        raise RuntimeError(
            f"{MY_PSN_ID} was not found "
            "in the complete historical leaderboard."
        )

    my_score = my_driver.get(
        "score"
    )

    my_rank = my_driver.get(
        "display_rank"
    )

    if (
        my_score is None
        or my_rank is None
    ):

        raise RuntimeError(
            "Personal historical entry has no score/rank."
        )

    my_rank = int(
        my_rank
    )

    my_user = recovery.get_user(
        my_driver
    )

    my_car_code = (
        recovery.get_car_code(
            my_driver
        )
    )

    my_country = my_user.get(
        "country_code"
    )

    my_dr = my_user.get(
        "driver_rating"
    )

    general = (
        recovery.general_rating(
            my_rank,
            total_records,
        )
    )

    elite = (
        recovery.elite_rating(
            my_rank,
            total_records,
        )
    )

    composite = (
        recovery.composite_rating(
            general,
            elite,
        )
    )

    ahead = (
        recovery.percentile_ahead(
            my_rank,
            total_records,
        )
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

    (
        country_rank,
        country_total,
    ) = group_rank(
        ranking,
        my_driver,
        lambda driver:
            recovery
            .get_user(
                driver
            )
            .get(
                "country_code"
            )
            == my_country,
    )

    (
        same_car_rank,
        same_car_total,
    ) = group_rank(
        ranking,
        my_driver,
        lambda driver:
            recovery
            .get_car_code(
                driver
            )
            == my_car_code,
    )

    (
        dr_rank,
        dr_total,
    ) = group_rank(
        ranking,
        my_driver,
        lambda driver:
            recovery
            .get_user(
                driver
            )
            .get(
                "driver_rating"
            )
            == my_dr,
    )

    return {
        "participated":
            True,

        "week_start":
            event[
                "date"
            ].date().isoformat(),

        "final_snapshot":
            "archived_leaderboard",

        "finalization_mode":
            "historical_previous_week_final",

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
            recovery.score_to_laptime(
                my_score
            ),

        "score_ms":
            my_score,

        "world_record":
            recovery.score_to_laptime(
                wr_score
            ),

        "world_record_ms":
            wr_score,

        "gap_to_wr_ms":
            my_score
            - wr_score,

        "car_code":
            my_car_code,

        "country":
            my_country,

        "driver_rating":
            my_dr,

        "country_rank":
            country_rank,

        "country_total":
            country_total,

        "same_car_rank":
            same_car_rank,

        "same_car_total":
            same_car_total,

        "dr_rank":
            dr_rank,

        "dr_total":
            dr_total,
    }


# ======================================================================================
# FINAL THRESHOLDS
# ======================================================================================

def score_at_rank(
    ranking,
    rank,
):

    if (
        rank < 1
        or rank > len(ranking)
    ):
        return None

    return ranking[
        rank - 1
    ].get(
        "score"
    )


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


def build_final_benchmarks(
    ranking,
):

    total = len(
        ranking
    )

    fixed = {}

    for rank in [
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
    ]:

        score = score_at_rank(
            ranking,
            rank,
        )

        if score is None:
            continue

        fixed[
            str(rank)
        ] = {
            "rank":
                rank,

            "score":
                score,

            "laptime":
                recovery.score_to_laptime(
                    score
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

        score = score_at_rank(
            ranking,
            rank,
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
                recovery.score_to_laptime(
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
# EMAIL REPORT
# ======================================================================================

def build_email_report(
    record,
    benchmarks,
):

    lines = []

    lines.append(
        "LAST WEEK - FINAL RESULT"
    )

    lines.append(
        SEPARATOR
    )

    lines.append(
        f"Week            : "
        f"{record['week_start']}"
    )

    lines.append(
        f"Race            : "
        f"{record['race']}"
    )

    lines.append("")

    lines.append(
        "YOUR FINAL RESULT"
    )

    lines.append(
        f"Position        : "
        f"#{record['position']:,} "
        f"of {record['total_drivers']:,}"
    )

    lines.append(
        f"Time            : "
        f"{record['laptime']}"
    )

    lines.append(
        f"Gap to WR       : "
        f"+{record['gap_to_wr_ms']/1000:.3f}s"
    )

    lines.append(
        f"Top percentile  : "
        f"Top {record['top_percent']:.2f}%"
    )

    lines.append(
        f"Ahead of        : "
        f"{record['percentile_ahead']:.2f}% "
        f"of participants"
    )

    lines.append(
        f"Brazil rank     : "
        f"#{record['country_rank']:,} "
        f"of {record['country_total']:,}"
    )

    lines.append(
        f"Same-car rank   : "
        f"#{record['same_car_rank']:,} "
        f"of {record['same_car_total']:,}"
    )

    lines.append("")

    lines.append(
        "FINAL RATINGS"
    )

    lines.append(
        f"General         : "
        f"{record['general_score']:.2f} / 10"
    )

    lines.append(
        f"Elite           : "
        f"{record['elite_score']:.2f} / 10"
    )

    lines.append(
        f"Composite       : "
        f"{record['composite_rating']:.2f} / 10"
    )

    lines.append(
        f"WR percentage   : "
        f"{record['wr_percentage']:.3f}%"
    )

    lines.append("")

    lines.append(
        "FINAL LEADERBOARD"
    )

    fixed = benchmarks[
        "fixed"
    ]

    for key in [
        "1",
        "100",
        "500",
        "1000",
        "2500",
        "5000",
    ]:

        item = fixed.get(
            key
        )

        if not item:
            continue

        label = (
            "WR"
            if key == "1"
            else f"Top {key}"
        )

        lines.append(
            f"{label:<15}: "
            f"{item['laptime']}"
        )

    percentiles = benchmarks[
        "percentiles"
    ]

    for key in [
        "10",
        "5",
        "2",
    ]:

        item = percentiles.get(
            key
        )

        if not item:
            continue

        lines.append(
            f"Top {key + '%':<11}: "
            f"{item['laptime']} "
            f"(#{item['rank']:,})"
        )

    lines.append("")

    lines.append(
        "Status          : FINAL - archived full leaderboard"
    )

    lines.append(
        "=" * 78
    )

    return "\n".join(
        lines
    )


# ======================================================================================
# MAIN
# ======================================================================================

def main():

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    now = datetime.now(
        SAO_PAULO
    )

    current_monday = (
        monday_of_week(
            now
        )
    )

    target_monday = (
        current_monday
        - timedelta(
            days=7
        )
    )

    target_week = (
        target_monday
        .date()
        .isoformat()
    )

    print(
        SEPARATOR
    )

    print(
        f"GT7 PREVIOUS WEEK FINALIZER V{VERSION}"
    )

    print(
        SEPARATOR
    )

    print(
        f"Current time     : "
        f"{now.isoformat()}"
    )

    print(
        f"Target week      : "
        f"{target_week}"
    )

    # ========================================================
    # Do not repeat expensive recovery if already finalized.
    # ========================================================

    history = load_weekly_history()

    existing = find_existing_final(
        history,
        target_week,
    )

    if existing:

        print("")
        print(
            "Historical final already exists."
        )

        print(
            f"Finalization     : "
            f"{existing.get('finalization_mode')}"
        )

        # Existing report is regenerated so Monday email still
        # has the final block even if the recovery was done manually.
        placeholder_benchmarks = {
            "fixed": {},
            "percentiles": {},
        }

        if OUTPUT_JSON.exists():

            try:

                saved = json.loads(
                    OUTPUT_JSON.read_text(
                        encoding="utf-8"
                    )
                )

                placeholder_benchmarks = (
                    saved.get(
                        "benchmarks",
                        placeholder_benchmarks,
                    )
                )

            except Exception:
                pass

        report = build_email_report(
            existing,
            placeholder_benchmarks,
        )

        OUTPUT_REPORT.write_text(
            report,
            encoding="utf-8",
        )

        print(
            "No historical network recovery required."
        )

        return

    # ========================================================
    # Historical recovery
    # ========================================================

    session = requests.Session()

    session.headers.update(
        HEADERS
    )

    event = discover_previous_race_c(
        session,
        target_monday,
    )

    print("")
    print(
        f"Race found       : "
        f"{event['text']}"
    )

    print(
        f"Leaderboard URL  : "
        f"{event['url']}"
    )

    print("")
    print(
        "LOADING COMPLETE HISTORICAL LEADERBOARD"
    )

    print(
        "-" * 78
    )

    result = (
        recovery.get_full_event_ranking(
            session,
            event[
                "url"
            ],
        )
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

    complete = result.get(
        "complete",
        False,
    )

    if not complete:

        raise RuntimeError(
            "Historical leaderboard was not completely loaded. "
            "Refusing to mark the week FINAL."
        )

    if (
        len(ranking)
        != total_records
    ):

        raise RuntimeError(
            "Historical leaderboard count does not match "
            "the advertised total. Refusing finalization."
        )

    # ========================================================
    # Final record
    # ========================================================

    record = build_final_record(
        event,
        ranking,
        total_records,
        extraction_mode,
    )

    benchmarks = build_final_benchmarks(
        ranking
    )

    upsert_weekly_record(
        history,
        record,
    )

    payload = {
        "version":
            VERSION,

        "generated_at":
            now.isoformat(),

        "week_start":
            target_week,

        "complete_leaderboard":
            True,

        "loaded_drivers":
            len(ranking),

        "total_drivers":
            total_records,

        "extraction_mode":
            extraction_mode,

        "result":
            record,

        "benchmarks":
            benchmarks,
    }

    OUTPUT_JSON.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    report = build_email_report(
        record,
        benchmarks,
    )

    OUTPUT_REPORT.write_text(
        report,
        encoding="utf-8",
    )

    print("")
    print(
        "FINAL RESULT"
    )

    print(
        "-" * 78
    )

    print(
        f"Position         : "
        f"#{record['position']:,}/"
        f"{record['total_drivers']:,}"
    )

    print(
        f"Time             : "
        f"{record['laptime']}"
    )

    print(
        f"Top              : "
        f"{record['top_percent']:.2f}%"
    )

    print(
        f"General          : "
        f"{record['general_score']:.2f}"
    )

    print(
        f"Elite            : "
        f"{record['elite_score']:.2f}"
    )

    print(
        f"Composite        : "
        f"{record['composite_rating']:.2f}"
    )

    print("")
    print(
        f"Weekly history   : UPDATED"
    )

    print(
        f"Email block      : "
        f"{OUTPUT_REPORT}"
    )

    print(
        f"JSON             : "
        f"{OUTPUT_JSON}"
    )

    print(
        SEPARATOR
    )


if __name__ == "__main__":

    try:

        main()

    except Exception as error:

        REPORT_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        failure_text = (
            "LAST WEEK - FINAL RESULT\n"
            + "=" * 78
            + "\n"
            + "Status          : PENDING ARCHIVE AVAILABILITY\n"
            + f"Reason          : {error}\n"
            + "The historical result was NOT marked final.\n"
            + "=" * 78
        )

        OUTPUT_REPORT.write_text(
            failure_text,
            encoding="utf-8",
        )

        print("")
        print(
            SEPARATOR
        )

        print(
            "PREVIOUS WEEK FINALIZATION FAILED"
        )

        print(
            SEPARATOR
        )

        print(
            f"{type(error).__name__}: "
            f"{error}"
        )

        sys.exit(2)