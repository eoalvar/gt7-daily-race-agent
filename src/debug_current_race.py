import json
import re
import time
from urllib.parse import (
    urljoin,
    urlparse,
    parse_qs,
    urlencode,
    urlunparse,
)

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIG
# ============================================================

GTSH_URL = "https://gtsh-rank.com/daily/"
MY_PSN_ID = "crazy_rooster74"

PAGE_SIZE = 100

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

REQUEST_DELAY_SECONDS = 0.10


# ============================================================
# FORMATTING
# ============================================================

def separator(char="=", length=100):
    print(char * length)


def section(title):
    print()
    print(title)
    separator("-", 100)


def score_to_laptime(score):
    if score is None:
        return "N/A"

    try:
        score = int(round(float(score)))
    except Exception:
        return str(score)

    minutes = score // 60000
    seconds = (score % 60000) // 1000
    milliseconds = score % 1000

    return (
        f"{minutes}:"
        f"{seconds:02d}."
        f"{milliseconds:03d}"
    )


# ============================================================
# DRIVER HELPERS
# ============================================================

def get_user(driver):
    if not isinstance(driver, dict):
        return {}

    user = driver.get("user", {})

    if isinstance(user, dict):
        return user

    return {}


def get_online_id(driver):
    value = get_user(driver).get(
        "np_online_id",
        ""
    )

    if not isinstance(value, str):
        return ""

    return value.strip()


def get_online_id_lower(driver):
    return get_online_id(
        driver
    ).lower()


def get_car_code(driver):
    if not isinstance(driver, dict):
        return None

    stats = driver.get(
        "ranking_stats",
        {}
    )

    if not isinstance(stats, dict):
        return None

    return stats.get(
        "car_code"
    )


def get_rank(driver):
    if not isinstance(driver, dict):
        return None

    return driver.get(
        "display_rank"
    )


def get_score(driver):
    if not isinstance(driver, dict):
        return None

    return driver.get(
        "score"
    )


def find_driver(
    ranking,
    psn_id
):
    target = psn_id.strip().lower()

    for driver in ranking:

        if (
            get_online_id_lower(driver)
            == target
        ):
            return driver

    return None


# ============================================================
# JSON VARIABLE EXTRACTION
# ============================================================

def extract_json_variable(
    html,
    variable_name
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

        text = html[
            start:
        ].lstrip()

        try:

            decoder = json.JSONDecoder()

            value, _ = decoder.raw_decode(
                text
            )

            return value

        except Exception:
            continue

    return None


# ============================================================
# DATE / RACE DISCOVERY
# ============================================================

def parse_race_date(text):
    match = re.search(
        r"(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})",
        text
    )

    if not match:
        return None

    return match.group(1)


def race_priority(text):
    lower = text.lower()

    score = 0

    if "daily race c" in lower:
        score += 100

    if "running" in lower:
        score += 50

    if "next week" in lower:
        score -= 100

    return score


def discover_current_race_c(
    session
):
    response = session.get(
        GTSH_URL,
        timeout=60
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    links = soup.select(
        'a[href*="/daily/leaderboard?event="], '
        'a[href*="/daily/leaderboard/?event="]'
    )

    candidates = []

    seen_urls = set()

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

        seen_urls.add(
            full_url
        )

        # The useful race description may be located
        # several DOM levels above the leaderboard link.
        texts = []

        node = link

        for _ in range(6):

            if node is None:
                break

            try:
                text = node.get_text(
                    " ",
                    strip=True
                )
            except Exception:
                text = ""

            if text:
                texts.append(
                    text
                )

            node = node.parent

        best_text = ""

        for text in texts:

            lower = text.lower()

            if "daily race c" in lower:
                best_text = text
                break

        if not best_text:

            best_text = (
                link.get_text(
                    " ",
                    strip=True
                )
            )

        lower = best_text.lower()

        if "daily race c" not in lower:
            continue

        candidates.append(
            {
                "url":
                    full_url,

                "text":
                    best_text,

                "date":
                    parse_race_date(
                        best_text
                    ),

                "priority":
                    race_priority(
                        best_text
                    ),
            }
        )

    if not candidates:

        raise RuntimeError(
            "No Daily Race C candidate found "
            "on the GTSH daily page."
        )

    candidates.sort(
        key=lambda item:
            item["priority"],
        reverse=True
    )

    return {
        "response":
            response,

        "candidates":
            candidates,

        "selected":
            candidates[0],
    }


# ============================================================
# CANONICAL LEADERBOARD URL
# ============================================================

def canonical_leaderboard_url(
    event_url
):
    parsed = urlparse(
        event_url
    )

    path = parsed.path.rstrip(
        "/"
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
# PAGE_DATA URL
# ============================================================

def build_page_url(
    event_url,
    offset,
    limit=PAGE_SIZE
):
    parsed = urlparse(
        canonical_leaderboard_url(
            event_url
        )
    )

    query = parse_qs(
        parsed.query,
        keep_blank_values=True
    )

    query["page_data"] = ["1"]
    query["offset"] = [
        str(offset)
    ]
    query["limit"] = [
        str(limit)
    ]

    query_string = urlencode(
        query,
        doseq=True
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
# FETCH PAGE_DATA
# ============================================================

def fetch_page_data(
    session,
    event_url,
    offset,
    limit=PAGE_SIZE
):
    url = build_page_url(
        event_url,
        offset,
        limit
    )

    response = session.get(
        url,
        headers={
            **HEADERS,
            "Accept":
                "application/json",
        },
        timeout=60
    )

    response.raise_for_status()

    content_type = response.headers.get(
        "Content-Type",
        ""
    )

    try:

        data = response.json()

    except Exception as error:

        raise RuntimeError(
            f"page_data response was not JSON "
            f"at offset {offset}. "
            f"Content-Type={content_type}. "
            f"Error={error}"
        )

    if not isinstance(
        data,
        dict
    ):

        raise RuntimeError(
            f"page_data response at offset "
            f"{offset} is not a JSON object."
        )

    board = data.get(
        "board"
    )

    if not isinstance(
        board,
        list
    ):

        raise RuntimeError(
            f"page_data response at offset "
            f"{offset} has no board array."
        )

    return {
        "url":
            url,

        "http_status":
            response.status_code,

        "content_type":
            content_type,

        "response_bytes":
            len(response.content),

        "board":
            board,

        "offset":
            data.get(
                "offset"
            ),

        "limit":
            data.get(
                "limit"
            ),

        "total":
            data.get(
                "total"
            ),

        "has_more":
            data.get(
                "has_more"
            ),

        "leader_time":
            data.get(
                "leader_time"
            ),

        "raw":
            data,
    }


# ============================================================
# PRINT PAGE
# ============================================================

def print_page_result(
    page
):
    board = page[
        "board"
    ]

    print(
        f"Requested URL    : "
        f"{page['url']}"
    )

    print(
        f"HTTP status      : "
        f"{page['http_status']}"
    )

    print(
        f"Content-Type     : "
        f"{page['content_type']}"
    )

    print(
        f"Response bytes   : "
        f"{page['response_bytes']:,}"
    )

    print(
        f"Returned offset  : "
        f"{page['offset']}"
    )

    print(
        f"Returned limit   : "
        f"{page['limit']}"
    )

    print(
        f"Total drivers    : "
        f"{page['total']}"
    )

    print(
        f"Entries          : "
        f"{len(board)}"
    )

    print(
        f"Has more         : "
        f"{page['has_more']}"
    )

    print(
        f"Leader time raw  : "
        f"{page['leader_time']}"
    )

    if board:

        print(
            f"First rank       : "
            f"{get_rank(board[0])}"
        )

        print(
            f"Last rank        : "
            f"{get_rank(board[-1])}"
        )

        print(
            f"First time       : "
            f"{score_to_laptime(get_score(board[0]))}"
        )

        print(
            f"First PSN        : "
            f"{get_online_id(board[0])}"
        )


# ============================================================
# PRINT DRIVER
# ============================================================

def print_driver(
    driver,
    total=None
):
    if not driver:

        print(
            "Found            : NO"
        )

        return

    rank = get_rank(
        driver
    )

    score = get_score(
        driver
    )

    user = get_user(
        driver
    )

    print(
        "Found            : YES"
    )

    print(
        f"PSN              : "
        f"{get_online_id(driver)}"
    )

    if total:

        print(
            f"Rank             : "
            f"#{rank:,}/{int(total):,}"
        )

    else:

        print(
            f"Rank             : "
            f"#{rank}"
        )

    print(
        f"Time             : "
        f"{score_to_laptime(score)}"
    )

    print(
        f"Score raw        : "
        f"{score}"
    )

    print(
        f"Car code         : "
        f"{get_car_code(driver)}"
    )

    print(
        f"Country          : "
        f"{user.get('country_code')}"
    )

    print(
        f"Driver rating    : "
        f"{user.get('driver_rating')}"
    )


# ============================================================
# SEARCH PSN AROUND EXPECTED POSITION
# ============================================================

def search_psn_near_offsets(
    session,
    event_url,
    offsets
):
    target = MY_PSN_ID.lower()

    results = []

    for offset in offsets:

        page = fetch_page_data(
            session,
            event_url,
            offset,
            PAGE_SIZE
        )

        driver = None

        for candidate in page[
            "board"
        ]:

            if (
                get_online_id_lower(
                    candidate
                )
                == target
            ):

                driver = candidate
                break

        results.append(
            {
                "offset":
                    offset,

                "page":
                    page,

                "driver":
                    driver,
            }
        )

        if driver:
            break

        time.sleep(
            REQUEST_DELAY_SECONDS
        )

    return results


# ============================================================
# MAIN
# ============================================================

def main():
    print()

    separator()

    print(
        "GT7 CURRENT DAILY RACE C DIAGNOSTIC"
    )

    separator()

    print(
        f"PSN ID           : "
        f"{MY_PSN_ID}"
    )

    print()

    session = requests.Session()

    session.headers.update(
        HEADERS
    )

    # ========================================================
    # STEP 1 - DAILY PAGE
    # ========================================================

    section(
        "1. DAILY PAGE / RACE DETECTION"
    )

    discovery = discover_current_race_c(
        session
    )

    daily_response = discovery[
        "response"
    ]

    candidates = discovery[
        "candidates"
    ]

    selected = discovery[
        "selected"
    ]

    print(
        f"Daily HTTP       : "
        f"{daily_response.status_code}"
    )

    print(
        f"Daily bytes      : "
        f"{len(daily_response.content):,}"
    )

    print(
        f"Race C candidates: "
        f"{len(candidates)}"
    )

    print()

    for index, candidate in enumerate(
        candidates,
        start=1
    ):

        print(
            f"Candidate {index}"
        )

        print(
            f"  Date           : "
            f"{candidate['date']}"
        )

        print(
            f"  Priority       : "
            f"{candidate['priority']}"
        )

        print(
            f"  Text           : "
            f"{candidate['text'][:300]}"
        )

        print(
            f"  URL            : "
            f"{candidate['url']}"
        )

        print()

    print(
        "SELECTED CURRENT RACE C"
    )

    print(
        f"Date             : "
        f"{selected['date']}"
    )

    print(
        f"Text             : "
        f"{selected['text'][:500]}"
    )

    print(
        f"URL              : "
        f"{selected['url']}"
    )

    canonical_url = (
        canonical_leaderboard_url(
            selected["url"]
        )
    )

    print(
        f"Canonical URL    : "
        f"{canonical_url}"
    )

    # ========================================================
    # STEP 2 - MAIN LEADERBOARD HTML
    # ========================================================

    section(
        "2. MAIN LEADERBOARD HTML"
    )

    response = session.get(
        canonical_url,
        timeout=60
    )

    response.raise_for_status()

    html = response.text

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

    initial_ranking = (
        extract_json_variable(
            html,
            "initialRanking"
        )
    )

    initial_server_page = (
        extract_json_variable(
            html,
            "initialServerPage"
        )
    )

    # ========================================================
    # INITIAL RANKING
    # ========================================================

    print()

    print(
        "initialRanking"
    )

    if isinstance(
        initial_ranking,
        list
    ):

        print(
            f"Entries          : "
            f"{len(initial_ranking):,}"
        )

        initial_driver = (
            find_driver(
                initial_ranking,
                MY_PSN_ID
            )
        )

        print(
            f"My PSN present   : "
            f"{'YES' if initial_driver else 'NO'}"
        )

        if initial_ranking:

            print(
                f"First rank       : "
                f"{get_rank(initial_ranking[0])}"
            )

            print(
                f"Last rank        : "
                f"{get_rank(initial_ranking[-1])}"
            )

            print(
                f"Leader time      : "
                f"{score_to_laptime(get_score(initial_ranking[0]))}"
            )

    else:

        print(
            "Not found / invalid"
        )

    # ========================================================
    # INITIAL SERVER PAGE
    # ========================================================

    print()

    print(
        "initialServerPage"
    )

    server_board = []

    server_total = None

    if isinstance(
        initial_server_page,
        dict
    ):

        server_board = (
            initial_server_page.get(
                "board",
                []
            )
        )

        if not isinstance(
            server_board,
            list
        ):
            server_board = []

        server_total = (
            initial_server_page.get(
                "total"
            )
        )

        print(
            f"Entries          : "
            f"{len(server_board):,}"
        )

        print(
            f"Total            : "
            f"{server_total}"
        )

        print(
            f"Offset           : "
            f"{initial_server_page.get('offset')}"
        )

        print(
            f"Limit            : "
            f"{initial_server_page.get('limit')}"
        )

        print(
            f"Has more         : "
            f"{initial_server_page.get('has_more')}"
        )

        print(
            f"Leader time      : "
            f"{initial_server_page.get('leader_time')}"
        )

        server_driver = (
            find_driver(
                server_board,
                MY_PSN_ID
            )
        )

        print(
            f"My PSN present   : "
            f"{'YES' if server_driver else 'NO'}"
        )

    else:

        print(
            "Not found / invalid"
        )

    # ========================================================
    # STEP 3 - LIVE PAGE_DATA OFFSET 0
    # ========================================================

    section(
        "3. LIVE page_data=1 - OFFSET 0"
    )

    page_zero = fetch_page_data(
        session,
        canonical_url,
        0,
        PAGE_SIZE
    )

    print_page_result(
        page_zero
    )

    live_total = (
        page_zero.get(
            "total"
        )
    )

    live_driver_zero = (
        find_driver(
            page_zero["board"],
            MY_PSN_ID
        )
    )

    print()

    print(
        f"My PSN in page   : "
        f"{'YES' if live_driver_zero else 'NO'}"
    )

    # ========================================================
    # STEP 4 - CHECK APPROXIMATE PREVIOUS POSITION
    # ========================================================

    section(
        "4. PSN SEARCH AROUND PREVIOUS POSITION"
    )

    print(
        "Yesterday the PSN was around rank #3,055."
    )

    print(
        "Testing page_data pages around that area."
    )

    print()

    offsets = [
        2800,
        2900,
        3000,
        3100,
        3200,
        3300,
    ]

    search_results = (
        search_psn_near_offsets(
            session,
            canonical_url,
            offsets
        )
    )

    found_driver = None
    found_page = None

    for result in search_results:

        page = result[
            "page"
        ]

        board = page[
            "board"
        ]

        if board:

            first_rank = get_rank(
                board[0]
            )

            last_rank = get_rank(
                board[-1]
            )

        else:

            first_rank = None
            last_rank = None

        print(
            f"Offset {result['offset']:>5}: "
            f"ranks {first_rank}-{last_rank} | "
            f"total {page['total']} | "
            f"PSN "
            f"{'FOUND' if result['driver'] else 'not found'}"
        )

        if result[
            "driver"
        ]:

            found_driver = (
                result[
                    "driver"
                ]
            )

            found_page = page

            break

    # ========================================================
    # STEP 5 - PERSONAL RESULT
    # ========================================================

    section(
        "5. CURRENT PSN RESULT"
    )

    if found_driver:

        print_driver(
            found_driver,
            found_page.get(
                "total"
            )
        )

    else:

        print(
            "PSN was not found in offsets "
            "2800-3300."
        )

        print()

        print(
            "This does NOT yet prove that the "
            "PSN is absent from the current leaderboard."
        )

        print(
            "The rank may have moved substantially "
            "since yesterday."
        )

    # ========================================================
    # STEP 6 - FRESHNESS COMPARISON
    # ========================================================

    section(
        "6. DATA FRESHNESS COMPARISON"
    )

    initial_total = None

    if isinstance(
        initial_server_page,
        dict
    ):

        initial_total = (
            initial_server_page.get(
                "total"
            )
        )

    initial_leader = None

    if (
        isinstance(
            initial_ranking,
            list
        )
        and initial_ranking
    ):

        initial_leader = (
            get_score(
                initial_ranking[0]
            )
        )

    page_data_leader = None

    if page_zero[
        "board"
    ]:

        page_data_leader = (
            get_score(
                page_zero[
                    "board"
                ][0]
            )
        )

    print(
        f"HTML server total: "
        f"{initial_total}"
    )

    print(
        f"page_data total  : "
        f"{live_total}"
    )

    print()

    print(
        f"HTML leader      : "
        f"{score_to_laptime(initial_leader)}"
    )

    print(
        f"page_data leader : "
        f"{score_to_laptime(page_data_leader)}"
    )

    print()

    if (
        initial_total is not None
        and live_total is not None
    ):

        try:

            difference = (
                int(live_total)
                - int(initial_total)
            )

            print(
                f"Driver difference: "
                f"{difference:+,}"
            )

        except Exception:
            pass

    # ========================================================
    # STEP 7 - DIAGNOSTIC CONCLUSION
    # ========================================================

    section(
        "7. AUTOMATIC DIAGNOSTIC"
    )

    html_psn_found = False

    if isinstance(
        initial_ranking,
        list
    ):

        html_psn_found = (
            find_driver(
                initial_ranking,
                MY_PSN_ID
            )
            is not None
        )

    page_data_psn_found = (
        found_driver is not None
        or live_driver_zero is not None
    )

    if page_data_psn_found:

        print(
            "RESULT: page_data=1 can see the PSN."
        )

        if not html_psn_found:

            print(
                "The HTML initialRanking does not "
                "contain the PSN, but the paginated "
                "leaderboard does."
            )

            print()

            print(
                "LIKELY CAUSE:"
            )

            print(
                "The main Daily Race C routine is "
                "relying too heavily on initialRanking "
                "instead of the paginated server board."
            )

    else:

        print(
            "RESULT: PSN not found in the tested "
            "page_data range."
        )

        print()

        if (
            initial_total is not None
            and live_total is not None
            and int(initial_total)
            == int(live_total)
            and initial_leader
            == page_data_leader
        ):

            print(
                "HTML and page_data currently expose "
                "the same leaderboard state."
            )

            print(
                "If these values are known to be old, "
                "the stale data is probably upstream "
                "rather than only in the local script."
            )

        else:

            print(
                "The HTML and page_data sources differ."
            )

            print(
                "This suggests a source-selection or "
                "freshness issue that should be investigated."
            )

    print()

    separator()

    print(
        "DIAGNOSTIC COMPLETE"
    )

    print(
        "No files were modified."
    )

    separator()


if __name__ == "__main__":
    main()
