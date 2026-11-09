"""Read-only, minimal HTTP diagnostics for GTSH Daily Race C pagination.

This does not authenticate, bypass access restrictions, enumerate ranks,
print cookies, or write production reports. Designed for GitHub Actions.
"""
import re
import sys
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit, urlencode, parse_qsl
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from test_race_detector import GTSH_URL, HEADERS, find_current_race_c


def describe(label, response):
    url = urlsplit(response.url)
    print(
        f"{label}: status={response.status_code} "
        f"host={url.hostname} path={url.path} "
        f"redirects={len(response.history)} "
        f"content_type={response.headers.get('Content-Type', '-')!r} "
        f"www_authenticate={response.headers.get('WWW-Authenticate', '-')!r}"
    )
    print(
        f"{label}: content_length={len(response.content)} "
        f"is_json={'json' in response.headers.get('Content-Type', '').lower()}"
    )
    if "json" in response.headers.get("Content-Type", "").lower() and response.ok:
        try:
            payload = response.json()
            if isinstance(payload, dict):
                print(f"{label}: json_keys={sorted(payload.keys())[:20]}")
                for key in ("board", "ranking", "data", "entries", "results", "drivers"):
                    if isinstance(payload.get(key), list):
                        print(f"{label}: {key}_count={len(payload[key])}")
                        break
            elif isinstance(payload, list):
                print(f"{label}: json_list_count={len(payload)}")
        except ValueError:
            print(f"{label}: JSON decode failed")


def with_params(url, **extra):
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update(extra)
    return urlunsplit((
        parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment
    ))


def main():
    session = requests.Session()
    session.headers.update(HEADERS)
    now = datetime.now(ZoneInfo("America/Sao_Paulo"))
    home = session.get(GTSH_URL, timeout=30)
    describe("daily_index", home)
    home.raise_for_status()
    selected = find_current_race_c(BeautifulSoup(home.text, "html.parser"), now)
    print(f"selected_track={'Road Atlanta' if 'Road Atlanta' in selected['text'] else 'other'}")
    page = session.get(selected["url"], timeout=30)
    describe("leaderboard_html", page)
    page.raise_for_status()
    # Snippet only: print whether a *named* endpoint is referenced.
    html = page.text
    for term in ("page_data", "update=1", "initialRanking", "fetch(", "XMLHttpRequest"):
        print(f"html_reference_{term!r}={term in html}")
    print(f"cookies_received={len(session.cookies)} (values not printed)")

    # First request replicates the production code using a modest page size.
    target = with_params(page.url, page_data="1", offset="0", limit="100")
    primary = session.get(target, timeout=30)
    describe("page_data_regular", primary)

    # Also try only the documented-looking page_data selector, no pagination
    # expansion or non-public endpoints.
    basic = session.get(with_params(page.url, page_data="1"), timeout=30)
    describe("page_data_basic", basic)

    # Existing first-party fallback, one request only.
    update = session.get(with_params(page.url, update="1"), timeout=30)
    describe("update_fallback", update)

    if primary.status_code == 401 and basic.status_code == 401:
        print("ASSESSMENT: page_data denies unauthenticated HTTP requests (401).")
    if not primary.ok and not basic.ok and not update.ok:
        print("ASSESSMENT: no usable full-data endpoint was verified.")
    print("Diagnostic finished; no production files modified.")


if __name__ == "__main__":
    main()
