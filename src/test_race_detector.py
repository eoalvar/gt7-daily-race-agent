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

import re
import json
from collections import Counter


# ---------------------------------------------------------
# 4. Extract initialRanking JavaScript data
# ---------------------------------------------------------

print("\nEXTRACTING LEADERBOARD DATA")
print("=" * 80)

match = re.search(
    r'const\s+initialRanking\s*=\s*(\[[\s\S]*?\]);',
    html
)

if not match:
    raise Exception(
        "Could not find initialRanking in leaderboard HTML"
    )

ranking_json = match.group(1)

try:
    ranking = json.loads(ranking_json)
except json.JSONDecodeError as e:
    raise Exception(
        f"Could not decode initialRanking JSON: {e}"
    )

print(
    "Drivers found in initialRanking:",
    len(ranking)
)


# ---------------------------------------------------------
# 5. Normalize driver data
# ---------------------------------------------------------

drivers = []

for entry in ranking:

    user = entry.get("user", {})
    stats = entry.get("ranking_stats", {})

    driver = {
        "rank": entry.get("display_rank"),
        "name": user.get("nick_name"),
        "np_online_id": user.get("np_online_id"),
        "country": user.get("country_code"),
        "driver_rating": user.get("driver_rating"),
        "sportsmanship_rating": user.get(
            "sportsmanship_rating"
        ),
        "car_code": stats.get("car_code"),
        "score": entry.get("score"),
        "update_time": entry.get("update_time"),
    }

    drivers.append(driver)


# ---------------------------------------------------------
# 6. Convert score to lap time
# ---------------------------------------------------------

def format_laptime(milliseconds):

    if milliseconds is None:
        return "N/A"

    total_seconds = milliseconds / 1000

    minutes = int(total_seconds // 60)

    seconds = total_seconds - (
        minutes * 60
    )

    return f"{minutes}:{seconds:06.3f}"


for driver in drivers:

    driver["laptime"] = format_laptime(
        driver["score"]
    )


# ---------------------------------------------------------
# 7. Display TOP 20
# ---------------------------------------------------------

print("\nTOP 20")
print("=" * 80)

for driver in drivers[:20]:

    print(
        f"{driver['rank']:4} | "
        f"{driver['laptime']:>8} | "
        f"{str(driver['name']):25} | "
        f"{driver['country']:2} | "
        f"DR {driver['driver_rating']} | "
        f"CarCode {driver['car_code']}"
    )


# ---------------------------------------------------------
# 8. Car distribution
# ---------------------------------------------------------

print("\nCAR DISTRIBUTION")
print("=" * 80)

car_counts = Counter(
    driver["car_code"]
    for driver in drivers
    if driver["car_code"] is not None
)

for car_code, count in car_counts.most_common(20):

    print(
        f"CarCode {car_code}: "
        f"{count} drivers"
    )


# ---------------------------------------------------------
# 9. Best lap for each car
# ---------------------------------------------------------

print("\nBEST TIME BY CAR")
print("=" * 80)

best_by_car = {}

for driver in drivers:

    car = driver["car_code"]

    if car is None:
        continue

    if (
        car not in best_by_car
        or driver["score"]
        < best_by_car[car]["score"]
    ):
        best_by_car[car] = driver


for car_code, driver in sorted(
    best_by_car.items(),
    key=lambda x: x[1]["score"]
)[:20]:

    print(
        f"CarCode {car_code} | "
        f"{driver['laptime']} | "
        f"{driver['name']}"
    )


# ---------------------------------------------------------
# 10. Race summary
# ---------------------------------------------------------

print("\nRACE C SUMMARY")
print("=" * 80)

if drivers:

    leader = drivers[0]

    print(
        "Best time:",
        leader["laptime"]
    )

    print(
        "Driver:",
        leader["name"]
    )

    print(
        "Country:",
        leader["country"]
    )

    print(
        "Car code:",
        leader["car_code"]
    )

print("\nEND")

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