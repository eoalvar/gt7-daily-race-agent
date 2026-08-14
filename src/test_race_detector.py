import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

GTSH_URL = "https://gtsh-rank.com/daily/"

headers = {
    "User-Agent": "Mozilla/5.0 (GT7 Daily Race Agent)"
}

# ---------------------------------------------------------
# 1. Open Daily Race page
# ---------------------------------------------------------

response = requests.get(
    GTSH_URL,
    headers=headers,
    timeout=30
)

print("Main page HTTP status:", response.status_code)

if response.status_code != 200:
    raise Exception("Could not access GTSH-Rank")

soup = BeautifulSoup(response.text, "html.parser")

# ---------------------------------------------------------
# 2. Find current Race C
# ---------------------------------------------------------

race_c_link = None
race_c_text = None

for link in soup.select('a[href*="/daily/leaderboard?event="]'):

    parent_text = link.parent.get_text(" ", strip=True)

    if (
        "Running" in parent_text
        and "Daily Race C" in parent_text
    ):
        race_c_link = urljoin(
            GTSH_URL,
            link.get("href")
        )
        race_c_text = parent_text
        break

if not race_c_link:
    raise Exception(
        "Could not find current Daily Race C leaderboard"
    )

print("\nCURRENT DAILY RACE C")
print("=" * 80)
print(race_c_text)
print("\nURL:")
print(race_c_link)

# ---------------------------------------------------------
# 3. Open leaderboard
# ---------------------------------------------------------

leaderboard_response = requests.get(
    race_c_link,
    headers=headers,
    timeout=30
)

print(
    "\nLeaderboard HTTP status:",
    leaderboard_response.status_code
)

if leaderboard_response.status_code != 200:
    raise Exception(
        "Could not access Race C leaderboard"
    )

html = leaderboard_response.text

leaderboard_soup = BeautifulSoup(
    html,
    "html.parser"
)

# ---------------------------------------------------------
# 4. Look for tables
# ---------------------------------------------------------

print("\nTABLE ANALYSIS")
print("=" * 80)

tables = leaderboard_soup.find_all("table")

print("Tables found:", len(tables))

for i, table in enumerate(tables, start=1):

    print(f"\nTABLE #{i}")
    print("-" * 80)

    rows = table.find_all("tr")

    print("Rows:", len(rows))

    for row in rows[:10]:

        cells = row.find_all(
            ["th", "td"]
        )

        values = [
            cell.get_text(" ", strip=True)
            for cell in cells
        ]

        print(values)

# ---------------------------------------------------------
# 5. Search JavaScript / HTML for API references
# ---------------------------------------------------------

print("\nPOSSIBLE DATA SOURCES")
print("=" * 80)

keywords = [
    "fetch(",
    "ajax",
    "api/",
    "/api",
    "leaderboard",
    "json",
    "datatable",
    "DataTable",
    "XMLHttpRequest"
]

lines = html.splitlines()

found = set()

for line in lines:

    lower = line.lower()

    for keyword in keywords:

        if keyword.lower() in lower:

            cleaned = line.strip()

            if cleaned and cleaned not in found:
                print(cleaned[:2000])
                found.add(cleaned)

            break

# ---------------------------------------------------------
# 6. List script sources
# ---------------------------------------------------------

print("\nJAVASCRIPT FILES")
print("=" * 80)

scripts = leaderboard_soup.find_all("script")

print("Scripts found:", len(scripts))

for script in scripts:

    src = script.get("src")

    if src:
        print(urljoin(race_c_link, src))

print("\nEND")