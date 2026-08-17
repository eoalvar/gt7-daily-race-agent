#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


HISTORICAL_LEADERBOARD_URL = (
    "https://gtsh-rank.com/daily/leaderboard?"
    "event=HFYfEk1IVkJvQ0M4RUNBW0dGAW8BB1ZWX1ILEx1eSRMNRTdRXE0RG0deRUUe"
    "VklSTV5WQFFFXgkTUUpNUFgQU1BFRU5RUkNQGlNdVBVdVlFcTQAVUVVDREVOKC1D"
    "UBJbXEVSFVZJFg4eB1dN"
)

PSN_ID = "crazy_rooster74"

OUTPUT_DIR = Path("data/historical_recovery")
OUTPUT_JSON = OUTPUT_DIR / "daily_race_c_2026-08-10_final.json"

SEPARATOR = "=" * 100
SUB_SEPARATOR = "-" * 100


def safe_get(
    data: Dict[str, Any],
    *keys: str,
    default: Any = None,
) -> Any:
    current: Any = data

    for key in keys:
        if not isinstance(current, dict):
            return default

        current = current.get(key)

        if current is None:
            return default

    return current


def format_laptime_from_score(
    score: Optional[int],
) -> Optional[str]:
    if not isinstance(score, int):
        return None

    minutes = score // 60000
    remainder = score % 60000
    seconds = remainder // 1000
    milliseconds = remainder % 1000

    return (
        f"{minutes}:"
        f"{seconds:02d}."
        f"{milliseconds:03d}"
    )


def find_possible_rankings(
    data: Any,
) -> List[List[Dict[str, Any]]]:
    results: List[List[Dict[str, Any]]] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            if node and all(
                isinstance(item, dict)
                for item in node[: min(len(node), 10)]
            ):
                keys = set()

                for item in node[: min(len(node), 10)]:
                    keys.update(item.keys())

                likely_fields = {
                    "rank",
                    "score",
                    "psnId",
                    "psn_id",
                    "userId",
                    "nickname",
                    "displayName",
                    "carCode",
                    "car_code",
                }

                if keys & likely_fields:
                    results.append(node)

            for item in node:
                walk(item)

        elif isinstance(node, dict):
            for value in node.values():
                walk(value)

    walk(data)

    return results


def extract_psn_id(
    item: Dict[str, Any],
) -> Optional[str]:
    candidates = [
        item.get("psn_id"),
        item.get("psnId"),
        item.get("userId"),
        item.get("user_id"),
        item.get("onlineId"),
        item.get("online_id"),
        item.get("accountId"),
        item.get("account_id"),
    ]

    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()

    user = item.get("user")

    if isinstance(user, dict):
        return extract_psn_id(user)

    driver = item.get("driver")

    if isinstance(driver, dict):
        return extract_psn_id(driver)

    return None


def extract_driver_name(
    item: Dict[str, Any],
) -> Optional[str]:
    candidates = [
        item.get("driver"),
        item.get("nickname"),
        item.get("displayName"),
        item.get("display_name"),
        item.get("name"),
    ]

    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()

    user = item.get("user")

    if isinstance(user, dict):
        return extract_driver_name(user)

    return None


def extract_rank(
    item: Dict[str, Any],
) -> Optional[int]:
    candidates = [
        item.get("rank"),
        item.get("position"),
        item.get("ranking"),
    ]

    for candidate in candidates:
        if isinstance(candidate, int):
            return candidate

    return None


def extract_score(
    item: Dict[str, Any],
) -> Optional[int]:
    candidates = [
        item.get("score"),
        item.get("time"),
        item.get("lapTime"),
        item.get("laptime"),
        item.get("lap_time"),
    ]

    for candidate in candidates:
        if isinstance(candidate, int):
            return candidate

    return None


def extract_car_code(
    item: Dict[str, Any],
) -> Optional[int]:
    candidates = [
        item.get("car_code"),
        item.get("carCode"),
        item.get("car_id"),
        item.get("carId"),
    ]

    for candidate in candidates:
        if isinstance(candidate, int):
            return candidate

    car = item.get("car")

    if isinstance(car, dict):
        return extract_car_code(car)

    return None


def extract_country(
    item: Dict[str, Any],
) -> Optional[str]:
    candidates = [
        item.get("country"),
        item.get("countryCode"),
        item.get("country_code"),
    ]

    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()

    user = item.get("user")

    if isinstance(user, dict):
        return extract_country(user)

    return None


def locate_driver(
    ranking_lists: List[List[Dict[str, Any]]],
    psn_id: str,
) -> Optional[Dict[str, Any]]:
    target = psn_id.lower()

    for ranking in ranking_lists:
        for item in ranking:
            found_psn = extract_psn_id(item)

            if found_psn and found_psn.lower() == target:
                return item

    return None


def best_ranking_list(
    ranking_lists: List[List[Dict[str, Any]]],
) -> Optional[List[Dict[str, Any]]]:
    if not ranking_lists:
        return None

    ranked = sorted(
        ranking_lists,
        key=lambda rows: len(rows),
        reverse=True,
    )

    return ranked[0]


def print_sample(
    ranking: Optional[List[Dict[str, Any]]],
) -> None:
    if not ranking:
        return

    print("")
    print("RANKING SAMPLE")
    print(SUB_SEPARATOR)

    for index, item in enumerate(
        ranking[:5],
        start=1,
    ):
        print(
            f"{index}. "
            f"rank={extract_rank(item)} | "
            f"psn={extract_psn_id(item)} | "
            f"driver={extract_driver_name(item)} | "
            f"score={extract_score(item)}"
        )


def main() -> None:
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    print(SEPARATOR)
    print("GT7 HISTORICAL DAILY RACE C RECOVERY")
    print(SEPARATOR)

    print("Race week        : 2026-08-10 -> 2026-08-17")
    print(f"PSN ID           : {PSN_ID}")
    print(f"Historical URL   : {HISTORICAL_LEADERBOARD_URL}")
    print("")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/126.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    response = requests.get(
        HISTORICAL_LEADERBOARD_URL,
        headers=headers,
        timeout=45,
    )

    print(f"HTTP status      : {response.status_code}")
    print(f"Content-Type     : {response.headers.get('content-type')}")
    print(f"Response bytes   : {len(response.content):,}")

    response.raise_for_status()

    text = response.text

    print("")
    print("SEARCHING PAGE CONTENT")
    print(SUB_SEPARATOR)

    psn_present = (
        PSN_ID.lower()
        in text.lower()
    )

    print(
        "PSN visible raw  : "
        + (
            "YES"
            if psn_present
            else "NO"
        )
    )

    possible_json_objects: List[Any] = []

    try:
        direct_json = response.json()
        possible_json_objects.append(
            direct_json
        )

        print("Direct JSON      : YES")

    except Exception:
        print("Direct JSON      : NO")

    script_json_patterns = [
        r'<script[^>]*type=["\']application/json["\'][^>]*>(.*?)</script>',
        r'__NEXT_DATA__\s*=\s*({.*?})\s*;',
        r'window\.__INITIAL_STATE__\s*=\s*({.*?})\s*;',
        r'initialRanking\s*[:=]\s*(\[[\s\S]*?\])',
    ]

    for pattern in script_json_patterns:
        matches = re.findall(
            pattern,
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )

        for match in matches:
            candidate = match.strip()

            try:
                parsed = json.loads(
                    candidate
                )

                possible_json_objects.append(
                    parsed
                )
            except Exception:
                continue

    all_rankings: List[
        List[Dict[str, Any]]
    ] = []

    for obj in possible_json_objects:
        all_rankings.extend(
            find_possible_rankings(obj)
        )

    print(
        f"Ranking arrays   : {len(all_rankings)}"
    )

    primary_ranking = best_ranking_list(
        all_rankings
    )

    if primary_ranking:
        print(
            f"Largest ranking  : {len(primary_ranking):,} entries"
        )
    else:
        print(
            "Largest ranking  : NOT FOUND"
        )

    print_sample(
        primary_ranking
    )

    my_entry = locate_driver(
        all_rankings,
        PSN_ID,
    )

    result: Dict[str, Any] = {
        "race_week": "2026-08-10",
        "historical_url": HISTORICAL_LEADERBOARD_URL,
        "http_status": response.status_code,
        "response_bytes": len(
            response.content
        ),
        "psn_id": PSN_ID,
        "psn_visible_in_raw_page": psn_present,
        "ranking_arrays_found": len(
            all_rankings
        ),
        "largest_ranking_size": (
            len(primary_ranking)
            if primary_ranking
            else None
        ),
        "driver_found": (
            my_entry is not None
        ),
        "driver_result": None,
    }

    if my_entry is not None:
        score = extract_score(
            my_entry
        )

        driver_result = {
            "rank": extract_rank(
                my_entry
            ),
            "psn_id": extract_psn_id(
                my_entry
            ),
            "driver": extract_driver_name(
                my_entry
            ),
            "score": score,
            "laptime": format_laptime_from_score(
                score
            ),
            "car_code": extract_car_code(
                my_entry
            ),
            "country": extract_country(
                my_entry
            ),
            "raw_entry": my_entry,
        }

        result[
            "driver_result"
        ] = driver_result

        print("")
        print("HISTORICAL DRIVER RESULT")
        print(SUB_SEPARATOR)

        print(
            f"Found            : YES"
        )
        print(
            f"Rank             : {driver_result['rank']}"
        )
        print(
            f"PSN ID           : {driver_result['psn_id']}"
        )
        print(
            f"Driver           : {driver_result['driver']}"
        )
        print(
            f"Lap time         : {driver_result['laptime']}"
        )
        print(
            f"Score            : {driver_result['score']}"
        )
        print(
            f"Car code         : {driver_result['car_code']}"
        )
        print(
            f"Country          : {driver_result['country']}"
        )

    else:
        print("")
        print("HISTORICAL DRIVER RESULT")
        print(SUB_SEPARATOR)

        print("Found            : NO")

        if psn_present:
            print(
                "Note             : PSN text exists in the page, "
                "but the script could not identify the ranking structure."
            )
        else:
            print(
                "Note             : PSN was not visible in the HTML/JSON "
                "returned by this request."
            )

    OUTPUT_JSON.write_text(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print("")
    print(SEPARATOR)
    print(
        f"Saved result     : {OUTPUT_JSON}"
    )
    print(SEPARATOR)


if __name__ == "__main__":
    try:
        main()

    except Exception as exc:
        print("")
        print(SEPARATOR)
        print("RECOVERY FAILED")
        print(SEPARATOR)
        print(
            f"{type(exc).__name__}: {exc}"
        )
        sys.exit(1)