import requests
import re
import json
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from collections import Counter, defaultdict

GTSH_URL = "https://gtsh-rank.com/daily/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (GT7 Daily Race Agent)"
}


# ============================================================
# AUXILIARY FUNCTIONS
# ============================================================

def score_to_laptime(score):
    """
    GTSH score is lap time in milliseconds.
    Example:
        114623 -> 1:54.623
    """

    minutes = score // 60000
    seconds = (score % 60000) // 1000
    milliseconds = score % 1000

    return f"{minutes}:{seconds:02d}.{milliseconds:03d}"


def get_car_code(driver):
    """
    Extract car code safely.
    """

    return (
        driver
        .get("ranking_stats", {})
        .get("car_code")
    )


def get_user(driver):
    """
    Extract user object safely.
    """

    return driver.get("user", {})


# ============================================================
# 1. OPEN GTSH DAILY RACE PAGE
# ============================================================

print("Opening GTSH-Rank...")

response = requests.get(
    GTSH_URL,
    headers=HEADERS,
    timeout=30
)

print("Main page HTTP status:", response.status_code)

response.raise_for_status()

soup = BeautifulSoup(
    response.text,
    "html.parser"
)


# ============================================================
# 2. FIND THE CURRENT / RUNNING DAILY RACE C
# ============================================================

race_c_link = None
race_c_text = None

leaderboard_links = soup.select(
    'a[href*="/daily/leaderboard?event="]'
)

for link in leaderboard_links:

    parent = link.parent

    if parent is None:
        continue

    parent_text = parent.get_text(
        " ",
        strip=True
    )

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

    raise RuntimeError(
        "Could not find the RUNNING Daily Race C."
    )


print()
print("CURRENT DAILY RACE C")
print("=" * 80)
print(race_c_text)

print()
print("Leaderboard URL:")
print(race_c_link)


# ============================================================
# 3. OPEN DAILY RACE C LEADERBOARD
# ============================================================

leaderboard_response = requests.get(
    race_c_link,
    headers=HEADERS,
    timeout=60
)

print()
print(
    "Leaderboard HTTP status:",
    leaderboard_response.status_code
)

leaderboard_response.raise_for_status()

html = leaderboard_response.text


# ============================================================
# 4. EXTRACT initialRanking JSON
# ============================================================

print()
print("EXTRACTING LEADERBOARD DATA")
print("=" * 80)

pattern = r"const\s+initialRanking\s*=\s*(\[.*?\]);"

match = re.search(
    pattern,
    html,
    re.DOTALL
)

if not match:

    raise RuntimeError(
        "Could not find initialRanking in the leaderboard HTML."
    )


ranking_json = match.group(1)


try:

    ranking = json.loads(ranking_json)

except json.JSONDecodeError as error:

    print("JSON decoding failed.")
    print("Error:", error)

    raise


if not ranking:

    raise RuntimeError(
        "initialRanking was found but contains no drivers."
    )


print(
    "Drivers found in initialRanking:",
    len(ranking)
)


# ============================================================
# 5. SORT RANKING
# ============================================================

ranking = sorted(
    ranking,
    key=lambda driver: driver.get(
        "display_rank",
        999999999
    )
)


# ============================================================
# 6. TOP 20
# ============================================================

print()
print("TOP 20")
print("=" * 80)


for driver in ranking[:20]:

    user = get_user(driver)

    position = driver.get(
        "display_rank",
        "-"
    )

    score = driver.get(
        "score",
        0
    )

    lap_time = score_to_laptime(score)

    name = user.get(
        "nick_name",
        "Unknown"
    )

    country = user.get(
        "country_code",
        "--"
    )

    dr = user.get(
        "driver_rating",
        "-"
    )

    car_code = get_car_code(driver)

    print(
        f"{position:>4} | "
        f"{lap_time:>9} | "
        f"{name[:25]:25} | "
        f"{country:2} | "
        f"DR {str(dr):2} | "
        f"CarCode {car_code}"
    )


# ============================================================
# 7. IMPORTANT RANKING THRESHOLDS
# ============================================================

print()
print("RANKING THRESHOLDS")
print("=" * 80)


thresholds = [
    1,
    10,
    50,
    100,
    250,
    500,
    1000,
    2500,
    5000,
    10000
]


for target in thresholds:

    if len(ranking) >= target:

        driver = ranking[target - 1]

        score = driver.get(
            "score",
            0
        )

        user = get_user(driver)

        print(
            f"TOP {target:<5} | "
            f"{score_to_laptime(score)} | "
            f"{user.get('nick_name', 'Unknown')[:25]}"
        )


# ============================================================
# 8. CAR DISTRIBUTION - ALL DRIVERS
# ============================================================

car_counter = Counter()


for driver in ranking:

    car_code = get_car_code(driver)

    if car_code is not None:

        car_counter[car_code] += 1


print()
print("CAR DISTRIBUTION - ALL DRIVERS")
print("=" * 80)


total_with_car = sum(
    car_counter.values()
)


for car_code, count in car_counter.most_common(20):

    percentage = (
        count / total_with_car * 100
        if total_with_car
        else 0
    )

    print(
        f"CarCode {car_code:<5} | "
        f"{count:>6} drivers | "
        f"{percentage:>6.2f}%"
    )


# ============================================================
# 9. CAR DISTRIBUTION - TOP 1000
# ============================================================

top1000 = ranking[:1000]

top1000_counter = Counter()


for driver in top1000:

    car_code = get_car_code(driver)

    if car_code is not None:

        top1000_counter[car_code] += 1


print()
print("CAR DISTRIBUTION - TOP 1000")
print("=" * 80)


for car_code, count in top1000_counter.most_common(15):

    percentage = (
        count / len(top1000) * 100
    )

    print(
        f"CarCode {car_code:<5} | "
        f"{count:>4} drivers | "
        f"{percentage:>6.2f}%"
    )


# ============================================================
# 10. CAR DISTRIBUTION - TOP 100
# ============================================================

top100 = ranking[:100]

top100_counter = Counter()


for driver in top100:

    car_code = get_car_code(driver)

    if car_code is not None:

        top100_counter[car_code] += 1


print()
print("CAR DISTRIBUTION - TOP 100")
print("=" * 80)


for car_code, count in top100_counter.most_common():

    percentage = (
        count / len(top100) * 100
    )

    print(
        f"CarCode {car_code:<5} | "
        f"{count:>3} drivers | "
        f"{percentage:>6.2f}%"
    )


# ============================================================
# 11. BEST LAP BY CAR
# ============================================================

best_by_car = {}


for driver in ranking:

    car_code = get_car_code(driver)

    if car_code is None:
        continue

    score = driver.get(
        "score",
        999999999
    )

    if (
        car_code not in best_by_car
        or score < best_by_car[car_code]["score"]
    ):

        best_by_car[car_code] = driver


best_car_list = sorted(
    best_by_car.items(),
    key=lambda item: item[1].get(
        "score",
        999999999
    )
)


print()
print("BEST TIME BY CAR")
print("=" * 80)


for car_code, driver in best_car_list[:20]:

    user = get_user(driver)

    score = driver.get(
        "score",
        0
    )

    position = driver.get(
        "display_rank",
        "-"
    )

    print(
        f"CarCode {car_code:<5} | "
        f"{score_to_laptime(score)} | "
        f"World Rank {str(position):>5} | "
        f"{user.get('nick_name', 'Unknown')[:25]}"
    )


# ============================================================
# 12. CAR COMPETITIVENESS
#     IMPORTANT:
#     Ignore cars with tiny samples.
# ============================================================

positions_by_car = defaultdict(list)


for driver in top1000:

    car_code = get_car_code(driver)

    if car_code is not None:

        position = driver.get(
            "display_rank"
        )

        if isinstance(position, int):

            positions_by_car[
                car_code
            ].append(position)


competitiveness = []


for car_code, positions in positions_by_car.items():

    # Minimum sample prevents a car with only
    # 1 or 2 elite drivers from appearing as
    # artificially "best".
    if len(positions) < 10:
        continue

    avg_position = (
        sum(positions) /
        len(positions)
    )

    best_driver = best_by_car[
        car_code
    ]

    competitiveness.append({

        "car_code":
            car_code,

        "drivers":
            len(positions),

        "average_position":
            avg_position,

        "best_score":
            best_driver.get(
                "score",
                0
            ),

        "best_rank":
            best_driver.get(
                "display_rank",
                "-"
            ),

        "best_driver":
            get_user(
                best_driver
            ).get(
                "nick_name",
                "Unknown"
            )

    })


# Primary sort:
# number of appearances in TOP 1000
#
# Secondary:
# average position

competitiveness.sort(
    key=lambda item: (
        -item["drivers"],
        item["average_position"]
    )
)


print()
print("CAR COMPETITIVENESS - TOP 1000")
print("=" * 80)

print(
    "Only cars with at least 10 drivers "
    "in the TOP 1000 are shown."
)

print()


for index, item in enumerate(
    competitiveness[:15],
    start=1
):

    print(
        f"{index:>2}. "
        f"CarCode {item['car_code']:<5} | "
        f"TOP1000 {item['drivers']:>4} | "
        f"AvgPos {item['average_position']:>6.1f} | "
        f"Best {score_to_laptime(item['best_score'])} | "
        f"Rank {str(item['best_rank']):>5}"
    )


# ============================================================
# 13. META SCORE
#
# Combines:
# - presence in TOP 100
# - presence in TOP 1000
# - overall popularity
#
# This is more useful than simply averaging positions.
# ============================================================

all_car_codes = set(
    car_counter.keys()
)


meta_scores = []


for car_code in all_car_codes:

    all_count = car_counter.get(
        car_code,
        0
    )

    top1000_count = top1000_counter.get(
        car_code,
        0
    )

    top100_count = top100_counter.get(
        car_code,
        0
    )

    # Weighted score.
    #
    # TOP 100 presence matters most.
    # TOP 1000 is next.
    # Overall usage matters least.

    meta_score = (
        top100_count * 10
        + top1000_count
        + (all_count / 100)
    )

    meta_scores.append({

        "car_code":
            car_code,

        "all":
            all_count,

        "top1000":
            top1000_count,

        "top100":
            top100_count,

        "score":
            meta_score

    })


meta_scores.sort(
    key=lambda item:
        item["score"],
    reverse=True
)


print()
print("META CARS")
print("=" * 80)


for index, item in enumerate(
    meta_scores[:10],
    start=1
):

    print(
        f"{index:>2}. "
        f"CarCode {item['car_code']:<5} | "
        f"TOP100 {item['top100']:>3} | "
        f"TOP1000 {item['top1000']:>4} | "
        f"All {item['all']:>6} | "
        f"MetaScore {item['score']:>8.2f}"
    )


# ============================================================
# 14. FINAL SUMMARY
# ============================================================

winner = ranking[0]

winner_user = get_user(
    winner
)

winner_car = get_car_code(
    winner
)


print()
print("=" * 80)
print("GT7 DAILY RACE C - FINAL SUMMARY")
print("=" * 80)

print()
print("RACE")
print(race_c_text)

print()
print("TOTAL DRIVERS")
print(len(ranking))

print()
print("WORLD RECORD")
print(
    score_to_laptime(
        winner.get("score", 0)
    )
)

print(
    winner_user.get(
        "nick_name",
        "Unknown"
    )
)

print(
    "CarCode",
    winner_car
)


# ============================================================
# TOP 500
# ============================================================

if len(ranking) >= 500:

    p500 = ranking[499]

    print()
    print("TOP 500 CUT")
    print(
        score_to_laptime(
            p500.get("score", 0)
        )
    )


# ============================================================
# TOP 1000
# ============================================================

if len(ranking) >= 1000:

    p1000 = ranking[999]

    print()
    print("TOP 1000 CUT")
    print(
        score_to_laptime(
            p1000.get("score", 0)
        )
    )


# ============================================================
# META RECOMMENDATION
# ============================================================

if meta_scores:

    best_meta = meta_scores[0]

    print()
    print("CURRENT META CAR")
    print(
        "CarCode",
        best_meta["car_code"]
    )

    print(
        "TOP 100:",
        best_meta["top100"]
    )

    print(
        "TOP 1000:",
        best_meta["top1000"]
    )

    print(
        "Total users:",
        best_meta["all"]
    )


print()
print("=" * 80)
print("TEST COMPLETED SUCCESSFULLY")
print("=" * 80)