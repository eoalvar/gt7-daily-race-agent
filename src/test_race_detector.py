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
# CAR CODE -> CAR NAME
# ============================================================

CAR_NAMES = {
    2157: "Aston Martin V8 Vantage Gr.4",
    2161: "Nissan GT-R Gr.4",
    2163: "Genesis Gr.4",
    2164: "Ford Mustang Gr.4",
    2166: "Alfa Romeo 4C Gr.4",

    3192: "Mercedes-Benz SLS AMG Gr.4",

    3231: "Volkswagen Scirocco Gr.4",

    3245: "BMW M4 Gr.4",
    3246: "Bugatti Veyron Gr.4",
    3247: "Chevrolet Corvette C7 Gr.4",
    3248: "GT by Citroën Gr.4",
    3249: "Dodge Viper Gr.4",

    3251: "Honda NSX Gr.4",
    3252: "Jaguar F-type Gr.4",
    3253: "Lamborghini Huracán Gr.4",
    3254: "Lexus RC F Gr.4",
    3256: "Mazda Atenza Gr.4",
    3257: "McLaren 650S Gr.4",
    3258: "Mitsubishi Lancer Evolution Final Gr.4",
    3259: "Peugeot RCZ Gr.4",
    3260: "Renault Mégane Gr.4",
    3261: "Subaru WRX Gr.4",
    3262: "Toyota 86 Gr.4",
    3263: "Ferrari 458 Italia Gr.4",

    3298: "Audi TT Cup '16",
    3310: "Porsche Cayman GT4 Clubsport '16",

    3399: "Toyota GR Supra Race Car '19",

    3477: "Nissan Silvia spec-R Aero (S15) Touring Car",
    3480: "Suzuki Swift Sport Gr.4",

    3501: "Genesis G70 GR4",

    3537: "Mazda3 Gr.4",

    1563: "Renault Mégane Trophy '11"
}


# ============================================================
# AUXILIARY FUNCTIONS
# ============================================================

def score_to_laptime(score):
    if not isinstance(score, int):
        return "N/A"

    minutes = score // 60000
    seconds = (score % 60000) // 1000
    milliseconds = score % 1000

    return f"{minutes}:{seconds:02d}.{milliseconds:03d}"


def get_car_code(driver):
    return (
        driver
        .get("ranking_stats", {})
        .get("car_code")
    )


def get_car_name(car_code):
    if car_code in CAR_NAMES:
        return CAR_NAMES[car_code]

    return f"Unknown car ({car_code})"


def get_user(driver):
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
# 2. FIND CURRENT DAILY RACE C
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
# 3. OPEN LEADERBOARD
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
# 4. EXTRACT initialRanking
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
        "Could not find initialRanking in leaderboard HTML."
    )


ranking_json = match.group(1)

ranking = json.loads(
    ranking_json
)

if not ranking:
    raise RuntimeError(
        "initialRanking contains no drivers."
    )


ranking = sorted(
    ranking,
    key=lambda driver: driver.get(
        "display_rank",
        999999999
    )
)


print(
    "Drivers found:",
    len(ranking)
)


# ============================================================
# 5. TOP 20
# ============================================================

print()
print("TOP 20")
print("=" * 100)


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
    car_name = get_car_name(car_code)

    print(
        f"{position:>4} | "
        f"{score_to_laptime(score):>9} | "
        f"{name[:22]:22} | "
        f"{country:2} | "
        f"DR {str(dr):2} | "
        f"{car_name}"
    )


# ============================================================
# 6. RANKING THRESHOLDS
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
    5000
]


for target in thresholds:

    if len(ranking) >= target:

        driver = ranking[target - 1]

        print(
            f"TOP {target:<5} | "
            f"{score_to_laptime(driver.get('score', 0))}"
        )


# ============================================================
# 7. CAR DISTRIBUTION - ALL DRIVERS
# ============================================================

car_counter = Counter()


for driver in ranking:

    car_code = get_car_code(driver)

    if car_code is not None:

        car_counter[car_code] += 1


total_with_car = sum(
    car_counter.values()
)


print()
print("CAR DISTRIBUTION - ALL DRIVERS")
print("=" * 100)


for car_code, count in car_counter.most_common(20):

    percentage = (
        count / total_with_car * 100
        if total_with_car
        else 0
    )

    print(
        f"{get_car_name(car_code):45} | "
        f"{count:>6} drivers | "
        f"{percentage:>6.2f}%"
    )


# ============================================================
# 8. CAR DISTRIBUTION - TOP 1000
# ============================================================

top1000 = ranking[:1000]

top1000_counter = Counter()


for driver in top1000:

    car_code = get_car_code(driver)

    if car_code is not None:
        top1000_counter[car_code] += 1


print()
print("CAR DISTRIBUTION - TOP 1000")
print("=" * 100)


for car_code, count in top1000_counter.most_common(15):

    percentage = (
        count / len(top1000) * 100
    )

    print(
        f"{get_car_name(car_code):45} | "
        f"{count:>4} drivers | "
        f"{percentage:>6.2f}%"
    )


# ============================================================
# 9. CAR DISTRIBUTION - TOP 100
# ============================================================

top100 = ranking[:100]

top100_counter = Counter()


for driver in top100:

    car_code = get_car_code(driver)

    if car_code is not None:
        top100_counter[car_code] += 1


print()
print("CAR DISTRIBUTION - TOP 100")
print("=" * 100)


for car_code, count in top100_counter.most_common():

    percentage = (
        count / len(top100) * 100
    )

    print(
        f"{get_car_name(car_code):45} | "
        f"{count:>3} drivers | "
        f"{percentage:>6.2f}%"
    )


# ============================================================
# 10. BEST TIME BY CAR
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
    key=lambda item:
        item[1].get(
            "score",
            999999999
        )
)


print()
print("BEST TIME BY CAR")
print("=" * 110)


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
        f"{get_car_name(car_code):45} | "
        f"{score_to_laptime(score)} | "
        f"World Rank {str(position):>5} | "
        f"{user.get('nick_name', 'Unknown')[:25]}"
    )


# ============================================================
# 11. CAR COMPETITIVENESS - TOP 1000
# ============================================================

positions_by_car = defaultdict(list)


for driver in top1000:

    car_code = get_car_code(driver)

    if car_code is None:
        continue

    position = driver.get(
        "display_rank"
    )

    if isinstance(position, int):

        positions_by_car[
            car_code
        ].append(position)


competitiveness = []


for car_code, positions in positions_by_car.items():

    if len(positions) < 10:
        continue

    avg_position = (
        sum(positions)
        / len(positions)
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
            )

    })


competitiveness.sort(
    key=lambda item: (
        -item["drivers"],
        item["average_position"]
    )
)


print()
print("CAR COMPETITIVENESS - TOP 1000")
print("=" * 110)

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
        f"{get_car_name(item['car_code']):42} | "
        f"TOP1000 {item['drivers']:>4} | "
        f"AvgPos {item['average_position']:>6.1f} | "
        f"Best {score_to_laptime(item['best_score'])} | "
        f"Rank {str(item['best_rank']):>5}"
    )


# ============================================================
# 12. META SCORE
# ============================================================

meta_scores = []


for car_code in car_counter.keys():

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
print("=" * 110)


for index, item in enumerate(
    meta_scores[:10],
    start=1
):

    print(
        f"{index:>2}. "
        f"{get_car_name(item['car_code']):42} | "
        f"TOP100 {item['top100']:>3} | "
        f"TOP1000 {item['top1000']:>4} | "
        f"All {item['all']:>6} | "
        f"MetaScore {item['score']:>8.2f}"
    )


# ============================================================
# 13. FINAL SUMMARY
# ============================================================

winner = ranking[0]

winner_user = get_user(
    winner
)

winner_car = get_car_code(
    winner
)


print()
print("=" * 100)
print("GT7 DAILY RACE C - FINAL SUMMARY")
print("=" * 100)

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
    get_car_name(
        winner_car
    )
)


if len(ranking) >= 100:

    print()
    print(
        "TOP 100 CUT:",
        score_to_laptime(
            ranking[99].get(
                "score",
                0
            )
        )
    )


if len(ranking) >= 500:

    print(
        "TOP 500 CUT:",
        score_to_laptime(
            ranking[499].get(
                "score",
                0
            )
        )
    )


if len(ranking) >= 1000:

    print(
        "TOP 1000 CUT:",
        score_to_laptime(
            ranking[999].get(
                "score",
                0
            )
        )
    )


if meta_scores:

    best_meta = meta_scores[0]

    print()
    print("CURRENT META CAR")

    print(
        get_car_name(
            best_meta["car_code"]
        )
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


# ============================================================
# 14. UNKNOWN CAR CODES
# ============================================================

unknown_codes = [
    car_code
    for car_code in car_counter.keys()
    if car_code not in CAR_NAMES
]


if unknown_codes:

    print()
    print("UNKNOWN CAR CODES")
    print("=" * 80)

    for car_code in sorted(
        unknown_codes
    ):

        print(
            f"{car_code} | "
            f"{car_counter[car_code]} drivers"
        )


print()
print("=" * 100)
print("TEST COMPLETED SUCCESSFULLY")
print("=" * 100)