from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

PAGE_SIZE = 1000
REQUEST_DELAY_SECONDS = 0.0
HEADERS = {
    "User-Agent": "Mozilla/5.0 (GT7 Daily Race Agent)",
    "Accept": "application/json,text/plain,*/*",
}


def _page_url(event_url: str, offset: int, limit: int = PAGE_SIZE) -> str:
    parsed = urlparse(event_url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["page_data"] = ["1"]
    query["offset"] = [str(offset)]
    query["limit"] = [str(limit)]
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urlencode(query, doseq=True),
            parsed.fragment,
        )
    )


def fetch_page_data(session, event_url: str, offset: int, limit: int = PAGE_SIZE):
    response = session.get(_page_url(event_url, offset, limit), headers=HEADERS, timeout=60)
    response.raise_for_status()
    payload = response.json()

    if isinstance(payload, list):
        return {
            "board": payload,
            "total": None,
            "has_more": len(payload) >= limit,
        }

    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected GTSH page_data payload type")

    board = None
    for key in ("board", "ranking", "data", "entries", "results", "drivers"):
        value = payload.get(key)
        if isinstance(value, list):
            board = value
            break

    total = None
    for key in ("total", "total_drivers", "totalDrivers", "count", "recordsTotal"):
        value = payload.get(key)
        if isinstance(value, (int, float)):
            total = int(value)
            break

    has_more = None
    for key in ("has_more", "hasMore", "more"):
        value = payload.get(key)
        if isinstance(value, bool):
            has_more = value
            break

    if has_more is None:
        has_more = bool(board) and (total is None or offset + len(board) < total)

    return {
        "board": board or [],
        "total": total,
        "has_more": has_more,
    }


def get_rank(driver):
    if not isinstance(driver, dict):
        return None
    value = driver.get("display_rank")
    if isinstance(value, (int, float)):
        return int(value)
    stats = driver.get("ranking_stats") or {}
    value = stats.get("rank")
    return int(value) if isinstance(value, (int, float)) else None


def get_score(driver):
    if not isinstance(driver, dict):
        return None
    value = driver.get("score")
    if isinstance(value, (int, float)):
        return value
    stats = driver.get("ranking_stats") or {}
    value = stats.get("score")
    return value if isinstance(value, (int, float)) else None


def get_car_code(driver):
    if not isinstance(driver, dict):
        return None
    stats = driver.get("ranking_stats") or {}
    value = stats.get("car_code")
    if isinstance(value, (int, float)):
        return int(value)
    value = driver.get("car_code")
    return int(value) if isinstance(value, (int, float)) else None
