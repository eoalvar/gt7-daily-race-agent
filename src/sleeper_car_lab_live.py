import time
import traceback
from pathlib import Path

import requests

import sleeper_car_lab as base
from debug_current_race import (
    PAGE_SIZE,
    HEADERS,
    REQUEST_DELAY_SECONDS,
    fetch_page_data,
    get_rank,
    get_score,
)

SEP = "=" * 100
ERROR_FILE = Path("data/bop_lab/sleeper_car_lab_error.txt")


def safe_int(value):
    try:
        return int(value)
    except Exception:
        return None


def driver_key(driver):
    user = driver.get("user") or {}

    for field in ("np_online_id", "user_id", "account_id", "id"):
        value = user.get(field)
        if value not in (None, ""):
            return (field, str(value))

    stats = driver.get("ranking_stats") or {}
    for field in ("driver_id", "user_id", "id"):
        value = stats.get(field)
        if value not in (None, ""):
            return (field, str(value))

    return (
        "fallback",
        safe_int(get_rank(driver)),
        safe_int(get_score(driver)),
        stats.get("car_code"),
    )


def robust_live_leaderboard(event_url):
    """Load a live leaderboard without requiring its total to stay frozen.

    GTSH's leaderboard can grow while pagination is in progress. The first
    page may therefore advertise N drivers while later pages already contain
    N+x. That is normal for a live event and must not invalidate the Sleeper
    model. We track the largest advertised total, paginate until the server
    says there is no more data, then de-duplicate drivers and use the number
    actually loaded as the denominator.
    """

    session = requests.Session()
    session.headers.update(HEADERS)

    first = fetch_page_data(session, event_url, 0, PAGE_SIZE)
    first_board = first.get("board") or []

    if not first_board:
        raise RuntimeError("Live leaderboard returned no drivers on first page.")

    advertised_total = safe_int(first.get("total")) or len(first_board)
    ranking = list(first_board)
    offset = len(first_board)
    page_number = 1
    has_more = bool(first.get("has_more"))

    print(
        f"Page 1              : {len(first_board)} drivers | "
        f"loaded {len(ranking):,} | advertised {advertised_total:,}"
    )

    # Hard safety ceiling: far beyond any current GT7 Daily leaderboard.
    max_pages = 2000

    while (has_more or offset < advertised_total) and page_number < max_pages:
        page_number += 1
        page = fetch_page_data(session, event_url, offset, PAGE_SIZE)
        board = page.get("board") or []

        page_total = safe_int(page.get("total"))
        if page_total is not None:
            advertised_total = max(advertised_total, page_total)

        has_more = bool(page.get("has_more"))

        if not board:
            # A live board may change between page requests. If the server now
            # says there is no more data, accept the snapshot accumulated so far.
            if not has_more:
                break
            raise RuntimeError(
                f"Live leaderboard returned zero entries at offset {offset} while has_more=True."
            )

        ranking.extend(board)
        offset += len(board)

        if page_number <= 5 or page_number % 25 == 0 or not has_more:
            print(
                f"Page {page_number:<12}: +{len(board):<3} | "
                f"loaded {len(ranking):,} | advertised {advertised_total:,} | "
                f"has_more={has_more}"
            )

        time.sleep(REQUEST_DELAY_SECONDS)

    if page_number >= max_pages:
        raise RuntimeError("Live leaderboard pagination exceeded safety page limit.")

    # Remove duplicates caused by rank movement while the live board grows.
    unique = {}
    for driver in ranking:
        key = driver_key(driver)
        old = unique.get(key)
        if old is None:
            unique[key] = driver
            continue

        old_rank = safe_int(get_rank(old)) or 10**9
        new_rank = safe_int(get_rank(driver)) or 10**9
        if new_rank < old_rank:
            unique[key] = driver

    ranking = list(unique.values())
    ranking.sort(
        key=lambda item: (
            safe_int(get_rank(item)) or 10**9,
            safe_int(get_score(item)) or 10**9,
        )
    )

    actual_total = len(ranking)
    drift = actual_total - advertised_total

    print(
        f"Live pagination done : {actual_total:,} unique drivers | "
        f"latest advertised {advertised_total:,} | drift {drift:+,}"
    )

    if actual_total < 1000:
        raise RuntimeError(
            f"Live leaderboard unexpectedly small after pagination: {actual_total} drivers."
        )

    # Return the internally consistent snapshot size. base.run_lab() will use
    # this total for shares and its completeness check.
    return ranking, actual_total


def main():
    base.load_complete_leaderboard = robust_live_leaderboard

    try:
        base.run_lab()
        if ERROR_FILE.exists():
            ERROR_FILE.unlink()
    except Exception as exc:
        ERROR_FILE.parent.mkdir(parents=True, exist_ok=True)
        error_text = (
            "GT7 SLEEPER CAR LAB LIVE WRAPPER - ERROR\n"
            + SEP
            + "\n"
            + f"Error: {type(exc).__name__}: {exc}\n\n"
            + "TRACEBACK\n"
            + "-" * 100
            + "\n"
            + traceback.format_exc()
            + "\n"
            + SEP
            + "\n"
        )
        ERROR_FILE.write_text(error_text, encoding="utf-8")
        print(error_text)
        raise


if __name__ == "__main__":
    main()
