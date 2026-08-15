import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re
import json
from collections import Counter, defaultdict


GTSH_URL = "https://gtsh-rank.com/daily/"

headers = {
    "User-Agent": "Mozilla/5.0 (GT7 Daily Race Agent)"
}


# =========================================================
# FUNÇÕES AUXILIARES
# =========================================================

def score_to_seconds(score):
    """
    Converte o score usado pelo GT7/GTSH-Rank para segundos.

    Exemplo:
        114623 -> 114.623
    """

    minutes = score // 60000
    seconds = (score % 60000) / 1000

    return minutes * 60 + seconds


def format_time(score):
    """
    Converte:
        114623
    em:
        1:54.623
    """

    total_seconds = score_to_seconds(score)

    minutes = int(total_seconds // 60)
    seconds = total_seconds - (minutes * 60)

    return f"{minutes}:{seconds:06.3f}"


def extract_drivers(initial_ranking):
    """
    Converte o JSON original do GTSH-Rank
    para uma estrutura simples de pilotos.
    """

    drivers = []

    for entry in initial_ranking:

        user = entry.get("user", {})
        stats = entry.get("ranking_stats", {})

        score = entry.get("score")

        driver = {
            "rank": entry.get("display_rank"),
            "time_ms": score,
            "time_seconds": score_to_seconds(score) if score else None,
            "replay_id": entry.get("replay_id"),

            "country": user.get("country_code"),
            "name": user.get("nick_name"),
            "psn_id": user.get("np_online_id"),

            "driver_rating": user.get("driver_rating"),
            "sportsmanship_rating": user.get(
                "sportsmanship_rating"
            ),

            "car_code": stats.get("car_code"),

            "update_time": entry.get("update_time"),
        }

        drivers.append(driver)

    return drivers


# =========================================================
# 1. ABRIR DAILY RACE
# =========================================================

response = requests.get(
    GTSH_URL,
    headers=headers,
    timeout=30
)

print("Main page HTTP status:", response.status_code)

if response.status_code != 200:
    raise Exception("Could not access GTSH-Rank")

soup = BeautifulSoup(
    response.text,
    "html.parser"
)


# =========================================================
# 2. ENCONTRAR DAILY RACE C
# =========================================================

race_c_link = None
race_c_text = None

for link in soup.select(
    'a[href*="/daily/leaderboard?event="]'
):

    parent = link.parent

    if not parent:
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

    raise Exception(
        "Could not find current Daily Race C leaderboard"
    )


print("\nCURRENT DAILY RACE C")
print("=" * 80)

print(race_c_text)

print("\nURL:")
print(race_c_link)


# =========================================================
# 3. ABRIR LEADERBOARD
# =========================================================

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


# =========================================================
# 4. ENCONTRAR initialRanking
# =========================================================

print("\nEXTRACTING LEADERBOARD DATA")
print("=" * 80)


match = re.search(
    r'const initialRanking\s*=\s*(\[.*?\]);',
    html,
    re.DOTALL
)

if not match:

    raise Exception(
        "Could not find initialRanking in leaderboard page"
    )


initial_ranking_text = match.group(1)


try:

    initial_ranking = json.loads(
        initial_ranking_text
    )

except json.JSONDecodeError as e:

    raise Exception(
        f"Could not decode initialRanking: {e}"
    )


drivers = extract_drivers(
    initial_ranking
)


print(
    "Drivers found in initialRanking:",
    len(drivers)
)


# =========================================================
# 5. TOP 20
# =========================================================

print("\nTOP 20")
print("=" * 80)

for driver in drivers[:20]:

    print(
        f"{driver['rank']:4} | "
        f"{format_time(driver['time_ms']):>8} | "
        f"{driver['name']:<25} | "
        f"{driver['country'] or '--':<2} | "
        f"DR {driver['driver_rating']} | "
        f"CarCode {driver['car_code']}"
    )


# =========================================================
# 6. DISTRIBUIÇÃO DOS CARROS
# =========================================================

print("\nCAR DISTRIBUTION")
print("=" * 80)


car_counter = Counter(
    driver["car_code"]
    for driver in drivers
    if driver["car_code"] is not None
)


for car_code, count in car_counter.most_common(20):

    print(
        f"CarCode {car_code}: "
        f"{count} drivers"
    )


# =========================================================
# 7. MELHOR TEMPO POR CARRO
# =========================================================

print("\nBEST TIME BY CAR")
print("=" * 80)


best_by_car = {}


for driver in drivers:

    car_code = driver["car_code"]

    if car_code is None:
        continue

    if car_code not in best_by_car:

        best_by_car[car_code] = driver

    elif (
        driver["time_ms"]
        < best_by_car[car_code]["time_ms"]
    ):

        best_by_car[car_code] = driver


sorted_best_by_car = sorted(
    best_by_car.items(),
    key=lambda x: x[1]["time_ms"]
)


for car_code, driver in sorted_best_by_car[:20]:

    print(
        f"CarCode {car_code} | "
        f"{format_time(driver['time_ms'])} | "
        f"{driver['name']}"
    )


# =========================================================
# 8. COMPETITIVIDADE DOS CARROS
#
# Análise somente dos TOP 1000.
#
# Exigimos pelo menos 10 pilotos por carro
# para evitar resultados estatisticamente frágeis.
# =========================================================

print("\nCAR COMPETITIVENESS")
print("=" * 80)

TOP_N = 1000
MIN_DRIVERS = 10


top_drivers = drivers[:TOP_N]


car_positions = defaultdict(list)

car_best_driver = {}


for driver in top_drivers:

    car_code = driver["car_code"]

    if car_code is None:
        continue

    car_positions[car_code].append(
        driver["rank"]
    )

    if car_code not in car_best_driver:

        car_best_driver[car_code] = driver

    elif (
        driver["time_ms"]
        < car_best_driver[car_code]["time_ms"]
    ):

        car_best_driver[car_code] = driver


competitive_cars = []


for car_code, positions in car_positions.items():

    if len(positions) < MIN_DRIVERS:
        continue

    avg_position = (
        sum(positions) / len(positions)
    )

    best_driver = car_best_driver[car_code]

    competitive_cars.append({

        "car_code": car_code,

        "drivers": len(positions),

        "avg_position": avg_position,

        "best_time": best_driver["time_ms"],

        "best_driver": best_driver["name"],

    })


competitive_cars.sort(
    key=lambda x: x["avg_position"]
)


print(
    f"Analysis based on TOP {TOP_N} drivers"
)

print(
    f"Minimum sample: {MIN_DRIVERS} drivers"
)

print()


for index, car in enumerate(
    competitive_cars[:20],
    start=1
):

    print(
        f"{index:2}. "
        f"CarCode {car['car_code']} | "
        f"Drivers {car['drivers']:4} | "
        f"Avg Pos {car['avg_position']:6.1f} | "
        f"Best {format_time(car['best_time'])} | "
        f"{car['best_driver']}"
    )


# =========================================================
# 9. TENTAR DESCOBRIR NOMES DOS CARROS
#
# Procuramos referências no HTML/JavaScript
# relacionadas a car_code e aos códigos encontrados.
# =========================================================

print("\nCAR CODE MAPPING INVESTIGATION")
print("=" * 80)


car_codes_to_find = set(
    car_counter.keys()
)


# ---------------------------------------------------------
# 9A. Procurar no HTML por estruturas relacionadas
# ---------------------------------------------------------

keywords = [

    "car_code",
    "carCode",
    "car-code",
    "carName",
    "car_name",
    "carNames",
    "cars",
    "vehicle",
    "vehicles",

]


print("\nRelevant HTML/JavaScript lines:")
print("-" * 80)


lines = html.splitlines()

found_lines = set()


for line in lines:

    lower = line.lower()

    for keyword in keywords:

        if keyword.lower() in lower:

            cleaned = line.strip()

            if (
                cleaned
                and cleaned not in found_lines
            ):

                print(cleaned[:2000])

                found_lines.add(cleaned)

            break


# ---------------------------------------------------------
# 9B. Procurar especificamente alguns CarCodes
# ---------------------------------------------------------

print("\nSpecific CarCode references:")
print("-" * 80)


# Limitamos aos 20 mais frequentes
# para não produzir um log gigantesco.

for car_code, count in car_counter.most_common(20):

    occurrences = []

    search_string = str(car_code)

    for line in lines:

        if search_string in line:

            occurrences.append(
                line.strip()
            )

            if len(occurrences) >= 3:
                break

    print(
        f"\nCarCode {car_code} "
        f"({count} drivers)"
    )

    if occurrences:

        for occurrence in occurrences:

            print(
                occurrence[:1000]
            )

    else:

        print(
            "No direct HTML reference found."
        )


# =========================================================
# 10. JAVASCRIPT FILES
# =========================================================

print("\nJAVASCRIPT FILES")
print("=" * 80)


scripts = leaderboard_soup.find_all(
    "script"
)


print(
    "Scripts found:",
    len(scripts)
)


for script in scripts:

    src = script.get("src")

    if src:

        print(
            urljoin(
                race_c_link,
                src
            )
        )


# =========================================================
# 11. RESUMO FINAL
# =========================================================

print("\nRACE C SUMMARY")
print("=" * 80)


if drivers:

    best_driver = drivers[0]

    print(
        "Best time:",
        format_time(
            best_driver["time_ms"]
        )
    )

    print(
        "Driver:",
        best_driver["name"]
    )

    print(
        "Country:",
        best_driver["country"]
    )

    print(
        "Car code:",
        best_driver["car_code"]
    )

    print(
        "Total drivers:",
        len(drivers)
    )


print("\nEND")