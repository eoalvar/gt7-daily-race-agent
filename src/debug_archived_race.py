import requests
import json
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin


GTSH_URL = "https://gtsh-rank.com/daily/"
TARGET_WEEK = "03 Aug 2026"
TARGET_PSN = "crazy_rooster74"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (GT7 Archive Debug Agent)"
}


def extract_json_variable(html, variable_name):

    marker = f"const {variable_name} = "

    start = html.find(marker)

    if start == -1:
        return None

    start += len(marker)

    try:
        decoder = json.JSONDecoder()

        data, _ = decoder.raw_decode(
            html[start:].lstrip()
        )

        return data

    except Exception:
        return None


session = requests.Session()

session.headers.update(
    HEADERS
)


print("=" * 80)
print("GT7 ARCHIVED DAILY RACE C DEBUG")
print("=" * 80)


# ============================================================
# 1. FIND 03 AUG 2026 RACE C
# ============================================================

response = session.get(
    GTSH_URL,
    timeout=30
)

response.raise_for_status()


soup = BeautifulSoup(
    response.text,
    "html.parser"
)


target_url = None
target_text = None


for page in range(1, 10):

    if page == 1:
        page_url = GTSH_URL
    else:
        page_url = (
            f"{GTSH_URL}?page={page}&q="
        )

    print(
        f"Searching archive page {page}..."
    )


    page_response = session.get(
        page_url,
        timeout=30
    )

    page_response.raise_for_status()


    page_soup = BeautifulSoup(
        page_response.text,
        "html.parser"
    )


    for link in page_soup.select(
        'a[href*="/daily/leaderboard?event="]'
    ):

        parent = link.parent

        if parent is None:
            continue

        text = parent.get_text(
            " ",
            strip=True
        )


        if (
            "Daily Race C" in text
            and TARGET_WEEK in text
        ):

            target_url = urljoin(
                GTSH_URL,
                link.get("href")
            )

            target_text = text

            break


    if target_url:
        break


if not target_url:

    raise RuntimeError(
        "Could not find archived Daily Race C "
        "for 03 Aug 2026."
    )


print()
print("RACE FOUND")
print("-" * 80)

print(target_text)

print()
print(target_url)


# ============================================================
# 2. OPEN ARCHIVED LEADERBOARD
# ============================================================

response = session.get(
    target_url,
    timeout=60
)

response.raise_for_status()

html = response.text


print()
print("LEADERBOARD PAGE")
print("-" * 80)

print(
    "HTTP:",
    response.status_code
)

print(
    "HTML length:",
    len(html)
)


# ============================================================
# 3. INITIAL RANKING
# ============================================================

initial_ranking = extract_json_variable(
    html,
    "initialRanking"
)


print()
print("INITIAL RANKING")
print("-" * 80)


if isinstance(
    initial_ranking,
    list
):

    print(
        "Drivers:",
        len(initial_ranking)
    )


    matches = []

    for driver in initial_ranking:

        user = driver.get(
            "user",
            {}
        )

        online_id = user.get(
            "np_online_id",
            ""
        )


        if (
            isinstance(
                online_id,
                str
            )
            and TARGET_PSN.lower()
            in online_id.lower()
        ):

            matches.append(
                driver
            )


    print(
        "PSN matches:",
        len(matches)
    )


    for match in matches:

        print(
            json.dumps(
                match,
                ensure_ascii=False,
                indent=2
            )
        )


else:

    print(
        "initialRanking NOT FOUND"
    )


# ============================================================
# 4. SEARCH HTML FOR PSN
# ============================================================

print()
print("RAW HTML SEARCH")
print("-" * 80)


if TARGET_PSN.lower() in html.lower():

    print(
        "PSN FOUND directly in HTML."
    )

else:

    print(
        "PSN NOT FOUND directly in HTML."
    )


# ============================================================
# 5. FIND ALL POSSIBLE DATA VARIABLES
# ============================================================

print()
print("JAVASCRIPT DATA VARIABLES")
print("-" * 80)


patterns = [
    r"const\s+([A-Za-z0-9_]+)\s*=",
    r"let\s+([A-Za-z0-9_]+)\s*=",
    r"var\s+([A-Za-z0-9_]+)\s*="
]


variables = set()


for pattern in patterns:

    for match in re.findall(
        pattern,
        html
    ):

        variables.add(
            match
        )


for variable in sorted(
    variables
):

    if any(
        keyword in variable.lower()
        for keyword in [
            "rank",
            "driver",
            "leader",
            "data",
            "result",
            "board"
        ]
    ):

        print(
            variable
        )


# ============================================================
# 6. FIND FETCH / API CALLS
# ============================================================

print()
print("FETCH / API REFERENCES")
print("-" * 80)


for line in html.splitlines():

    lower = line.lower()

    if (
        "fetch(" in lower
        or "update=1" in lower
        or "json" in lower
        or "leaderboard" in lower
    ):

        cleaned = line.strip()

        if cleaned:

            print(
                cleaned[:1500]
            )


# ============================================================
# 7. TEST UPDATE ENDPOINTS
# ============================================================

print()
print("UPDATE ENDPOINT TESTS")
print("-" * 80)


test_urls = []


separator = (
    "&"
    if "?" in target_url
    else "?"
)


test_urls.append(
    target_url
    + separator
    + "update=1"
)


test_urls.append(
    "https://gtsh-rank.com/"
    "daily/leaderboard/?update=1"
)


for test_url in test_urls:

    print()
    print(
        "Testing:",
        test_url
    )


    try:

        r = session.get(
            test_url,
            timeout=60
        )


        print(
            "HTTP:",
            r.status_code
        )

        print(
            "Content-Type:",
            r.headers.get(
                "content-type"
            )
        )


        try:

            data = r.json()

            print(
                "JSON type:",
                type(data).__name__
            )


            if isinstance(
                data,
                list
            ):

                print(
                    "Drivers:",
                    len(data)
                )


                exact_matches = []

                partial_matches = []


                for driver in data:

                    user = driver.get(
                        "user",
                        {}
                    )

                    online_id = user.get(
                        "np_online_id",
                        ""
                    )


                    if not isinstance(
                        online_id,
                        str
                    ):
                        continue


                    if (
                        online_id.lower()
                        == TARGET_PSN.lower()
                    ):

                        exact_matches.append(
                            driver
                        )


                    if (
                        TARGET_PSN.lower()
                        in online_id.lower()
                    ):

                        partial_matches.append(
                            driver
                        )


                print(
                    "Exact PSN matches:",
                    len(
                        exact_matches
                    )
                )

                print(
                    "Partial PSN matches:",
                    len(
                        partial_matches
                    )
                )


                for match in partial_matches:

                    print(
                        json.dumps(
                            match,
                            ensure_ascii=False,
                            indent=2
                        )
                    )


        except Exception:

            print(
                "Response was not JSON."
            )

            print(
                r.text[:1000]
            )


    except Exception as error:

        print(
            "ERROR:",
            error
        )


print()
print("=" * 80)
print("END")
print("=" * 80)