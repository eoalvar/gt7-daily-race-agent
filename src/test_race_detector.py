import requests
import json
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

# ---------------------------------------------------------
# 4. Extract initialRanking from JavaScript
# ---------------------------------------------------------

print("\nEXTRACTING LEADERBOARD DATA")
print("=" * 80)

marker = "const initialRanking = "

start = html.find(marker)

if start == -1:
    raise Exception(
        "Could not find initialRanking in leaderboard page"
    )

start += len(marker)

# JSONDecoder allows us to decode exactly the JSON array,
# without relying on fragile regular expressions.

decoder = json.JSONDecoder()

ranking, end_position = decoder.raw_decode(
    html[start:].lstrip()
)

print(
    "Drivers found in initialRanking:",
    len(ranking)
)

# ---------------------------------------------------------
# 5. Show first 20 drivers
# ---------------------------------------------------------

print("\nTOP 20")
print("=" * 80)

for driver in ranking[:20]:

    position = driver.get("display_rank")

    score = driver.get("score")

    user = driver.get("user", {})

    name = user.get(
        "nick_name",
        "Unknown"
    )

    country = user.get(
        "country_code",
        ""
    )

    driver_rating = user.get(
        "driver_rating",
        ""
    )

    car_code = driver.get(
        "ranking_stats",
        {}
    ).get(
        "car_code",
        ""
    )

    # Convert milliseconds to GT7 lap-time format
    if isinstance(score, int):

        total_seconds = score / 1000

        minutes = int(
            total_seconds // 60
        )

        seconds = total_seconds % 60

        laptime = (
            f"{minutes}:{seconds:06.3f}"
        )

    else:
        laptime = str(score)

    print(
        f"{position:>4} | "
        f"{laptime:>9} | "
        f"{name:<25} | "
        f"{country:<3} | "
        f"DR {driver_rating:<2} | "
        f"CarCode {car_code}"
    )

# ---------------------------------------------------------
# 6. Basic statistics
# ---------------------------------------------------------

if ranking:

    best = ranking[0]

    best_time = best.get("score")

    if isinstance(best_time, int):

        total_seconds = best_time / 1000

        minutes = int(
            total_seconds // 60
        )

        seconds = total_seconds % 60

        best_laptime = (
            f"{minutes}:{seconds:06.3f}"
        )

    else:
        best_laptime = str(best_time)

    print("\nRACE C SUMMARY")
    print("=" * 80)

    print("Best time:", best_laptime)
    print(
        "Driver:",
        best.get("user", {}).get(
            "nick_name"
        )
    )

    print(
        "Country:",
        best.get("user", {}).get(
            "country_code"
        )
    )

    print(
        "Car code:",
        best.get("ranking_stats", {}).get(
            "car_code"
        )
    )

print("\nEND")