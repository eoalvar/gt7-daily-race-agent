import requests
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from collections import Counter, defaultdict

GTSH_URL = "https://gtsh-rank.com/daily/"

headers = {
    "User-Agent": "Mozilla/5.0 (GT7 Daily Race Agent)"
}

# =========================================================
# 1. OPEN DAILY RACE PAGE
# =========================================================

response = requests.get(
    GTSH_URL,
    headers=headers,
    timeout=30
)

if response.status_code != 200:
    raise Exception("Could not access GTSH-Rank")

soup = BeautifulSoup(response.text, "html.parser")

# =========================================================
# 2. FIND CURRENT DAILY RACE C
# =========================================================

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

# =========================================================
# 3. OPEN LEADERBOARD
# =========================================================

leaderboard_response = requests.get(
    race_c_link,
    headers=headers,
    timeout=30
)

if leaderboard_response.status_code != 200:
    raise Exception(
        "Could not access Race C leaderboard"
    )

html = leaderboard_response.text

# =========================================================
# 4. EXTRACT initialRanking
# =========================================================

match = re.search(
    r'initialRanking\s*=\s*(\[[\s\S]*?\]);',
    html
)

if not match:
    raise Exception(
        "Could not find initialRanking in leaderboard page"
    )

ranking_text = match.group(1)

# =========================================================
# 5. CONVERT JAVASCRIPT OBJECTS TO SOMETHING WE CAN READ
# =========================================================

# Find individual objects inside initialRanking.
objects = re.findall(
    r'\{[^{}]*\}',
    ranking_text
)

drivers = []

for obj in objects:

    # Time
    time_match = re.search(
        r'(?:time|lapTime|bestTime)\s*:\s*["\']([^"\']+)["\']',
        obj,
        re.IGNORECASE
    )

    # Driver name
    name_match = re.search(
        r'(?:name|playerName|driverName)\s*:\s*["\']([^"\']*)["\']',
        obj,
        re.IGNORECASE
    )

    # Country
    country_match = re.search(
        r'(?:country|countryCode)\s*:\s*["\']([^"\']*)["\']',
        obj,
        re.IGNORECASE
    )

    # DR
    dr_match = re.search(
        r'(?:dr|driverRating)\s*:\s*["\']?([^,"\'} ]+)',
        obj,
        re.IGNORECASE
    )

    # Car code
    car_match = re.search(
        r'(?:carCode|car|carId)\s*:\s*["\']?(\d+)',
        obj,
        re.IGNORECASE
    )

    if time_match and name_match:

        drivers.append({
            "time": time_match.group(1),
            "name": name_match.group(1),
            "country": country_match.group(1) if country_match else "",
            "dr": dr_match.group(1) if dr_match else "",
            "car": car_match.group(1) if car_match else ""
        })

# =========================================================
# 6. IF REGEX FAILED, TRY ALTERNATIVE EXTRACTION
# =========================================================

if not drivers:

    # Extract common quoted values from the JavaScript.
    # This is only a diagnostic fallback.
    print("ERROR: Could not decode driver objects.")
    print()
    print("initialRanking was found, but its structure")
    print("could not be decoded by this version of the script.")
    print()
    print("Please send ONLY these lines from the GitHub log:")
    print("Drivers found / ERROR section.")
    raise Exception("Could not decode leaderboard data")

# =========================================================
# 7. SORT BY LAP TIME
# =========================================================

def time_to_seconds(t):

    try:
        parts = t.split(":")

        if len(parts) == 2:
            minutes = float(parts[0])
            seconds = float(parts[1])
            return minutes * 60 + seconds

        return float(t)

    except:
        return 999999


drivers.sort(
    key=lambda x: time_to_seconds(x["time"])
)

# =========================================================
# 8. RACE INFORMATION
# =========================================================

print("GT7 DAILY RACE C ANALYSIS")
print("=" * 70)

print("Race:")
print(race_c_text)

print()
print("Leaderboard:")
print(race_c_link)

print()
print("Drivers found:", len(drivers))

# =========================================================
# 9. TOP 20
# =========================================================

print()
print("TOP 20")
print("=" * 70)

for position, driver in enumerate(drivers[:20], start=1):

    print(
        f"{position:3} | "
        f"{driver['time']:>8} | "
        f"{driver['name'][:25]:25} | "
        f"{driver['country']:2} | "
        f"DR {driver['dr']:>2} | "
        f"Car {driver['car']}"
    )

# =========================================================
# 10. CAR DISTRIBUTION
# =========================================================

car_counter = Counter(
    d["car"]
    for d in drivers
    if d["car"]
)

print()
print("CAR DISTRIBUTION")
print("=" * 70)

for car, count in car_counter.most_common(20):

    print(
        f"Car {car:>5}: {count:>6} drivers"
    )

# =========================================================
# 11. BEST TIME BY CAR
# =========================================================

best_by_car = {}

for driver in drivers:

    car = driver["car"]

    if not car:
        continue

    if (
        car not in best_by_car
        or time_to_seconds(driver["time"])
        < time_to_seconds(best_by_car[car]["time"])
    ):
        best_by_car[car] = driver

print()
print("BEST TIME BY CAR")
print("=" * 70)

sorted_best_cars = sorted(
    best_by_car.items(),
    key=lambda x: time_to_seconds(x[1]["time"])
)

for car, driver in sorted_best_cars[:20]:

    print(
        f"Car {car:>5} | "
        f"{driver['time']:>8} | "
        f"{driver['name']}"
    )

# =========================================================
# 12. TOP 1000 CAR COMPETITIVENESS
# =========================================================

top1000 = drivers[:1000]

positions_by_car = defaultdict(list)

for position, driver in enumerate(top1000, start=1):

    if driver["car"]:
        positions_by_car[driver["car"]].append(position)

print()
print("CAR COMPETITIVENESS")
print("=" * 70)

print("Based on TOP 1000 drivers")
print()

competitiveness = []

for car, positions in positions_by_car.items():

    avg_position = sum(positions) / len(positions)

    best_driver = best_by_car.get(car)

    best_time = (
        best_driver["time"]
        if best_driver
        else ""
    )

    competitiveness.append({
        "car": car,
        "drivers": len(positions),
        "avg_position": avg_position,
        "best_time": best_time,
        "best_driver": (
            best_driver["name"]
            if best_driver
            else ""
        )
    })

competitiveness.sort(
    key=lambda x: x["avg_position"]
)

for rank, item in enumerate(
    competitiveness[:20],
    start=1
):

    print(
        f"{rank:2}. "
        f"Car {item['car']:>5} | "
        f"Drivers {item['drivers']:>4} | "
        f"Avg Pos {item['avg_position']:>7.1f} | "
        f"Best {item['best_time']:>8} | "
        f"{item['best_driver']}"
    )

# =========================================================
# 13. FINAL SUMMARY
# =========================================================

best = drivers[0]

print()
print("RACE C SUMMARY")
print("=" * 70)

print("Best time:", best["time"])
print("Driver:", best["name"])
print("Country:", best["country"])
print("Car code:", best["car"])
print("Total drivers:", len(drivers))

print()
print("TEST COMPLETED SUCCESSFULLY")