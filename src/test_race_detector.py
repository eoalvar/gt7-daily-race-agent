import requests
import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from collections import Counter

# ============================================================
# CONFIG
# ============================================================

GTSH_URL = "https://gtsh-rank.com/daily/"
MY_PSN_ID = "crazy_rooster74"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (GT7 Daily Race Agent)"
}

REPORT_DIR = Path("reports")
DATA_DIR = Path("data")
HISTORY_DIR = DATA_DIR / "history"

LATEST_REPORT_FILE = REPORT_DIR / "latest.txt"
LATEST_SNAPSHOT_FILE = DATA_DIR / "latest_snapshot.json"

SAO_PAULO = ZoneInfo("America/Sao_Paulo")


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
    if score is None:
        return "N/A"

    score = int(round(score))

    minutes = score // 60000
    seconds = (score % 60000) // 1000
    milliseconds = score % 1000

    return f"{minutes}:{seconds:02d}.{milliseconds:03d}"


def get_car_code(driver):
    return driver.get("ranking_stats", {}).get("car_code")


def get_car_name(car_code):
    return CAR_NAMES.get(
        car_code,
        f"Unknown car ({car_code})"
    )


def get_user(driver):
    return driver.get("user", {})


def find_my_driver(ranking, psn_id):
    target = psn_id.strip().lower()

    for driver in ranking:
        online_id = get_user(driver).get(
            "np_online_id",
            ""
        )

        if (
            isinstance(online_id, str)
            and online_id.strip().lower() == target
        ):
            return driver

    return None


def load_previous_snapshot():
    if not LATEST_SNAPSHOT_FILE.exists():
        return None

    try:
        return json.loads(
            LATEST_SNAPSHOT_FILE.read_text(
                encoding="utf-8"
            )
        )
    except Exception:
        return None


def signed_seconds(delta_ms):
    sign = "+" if delta_ms > 0 else ""
    return f"{sign}{delta_ms / 1000:.3f}s"


def position_change(old_rank, new_rank):
    if old_rank is None or new_rank is None:
        return "N/A"

    difference = old_rank - new_rank

    if difference > 0:
        return f"+{difference} positions"

    if difference < 0:
        return f"{difference} positions"

    return "unchanged"


# ============================================================
# CREATE FOLDERS
# ============================================================

REPORT_DIR.mkdir(
    parents=True,
    exist_ok=True
)

DATA_DIR.mkdir(
    parents=True,
    exist_ok=True
)

HISTORY_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# 1. OPEN DAILY RACE PAGE
# ============================================================

response = requests.get(
    GTSH_URL,
    headers=HEADERS,
    timeout=30
)

response.raise_for_status()

soup = BeautifulSoup(
    response.text,
    "html.parser"
)


# ============================================================
# 2. FIND RUNNING DAILY RACE C
# ============================================================

race_c_link = None
race_c_text = None

for link in soup.select(
    'a[href*="/daily/leaderboard?event="]'
):

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


# ============================================================
# 3. OPEN LEADERBOARD
# ============================================================

leaderboard_response = requests.get(
    race_c_link,
    headers=HEADERS,
    timeout=60
)

leaderboard_response.raise_for_status()

html = leaderboard_response.text


# ============================================================
# 4. EXTRACT initialRanking
# ============================================================

marker = "const initialRanking = "

start = html.find(marker)

if start == -1:
    raise RuntimeError(
        "Could not find initialRanking."
    )

start += len(marker)

decoder = json.JSONDecoder()

ranking, _ = decoder.raw_decode(
    html[start:].lstrip()
)

if not ranking:
    raise RuntimeError(
        "Leaderboard contains no drivers."
    )


ranking.sort(
    key=lambda driver:
        driver.get(
            "display_rank",
            999999999
        )
)


# ============================================================
# 5. BASIC DATA
# ============================================================

now = datetime.now(
    SAO_PAULO
)

timestamp_iso = now.isoformat()

timestamp_display = now.strftime(
    "%d/%m/%Y %H:%M:%S"
)

history_filename = now.strftime(
    "%Y-%m-%d_%H-%M-%S.json"
)

winner = ranking[0]

world_record_score = winner.get(
    "score"
)

world_record_user = get_user(
    winner
)

world_record_car_code = get_car_code(
    winner
)

time_103 = round(
    world_record_score * 1.03
)

time_105 = round(
    world_record_score * 1.05
)


# ============================================================
# 6. THRESHOLDS
# ============================================================

threshold_positions = [
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

thresholds = {}

for position in threshold_positions:

    if len(ranking) >= position:
        thresholds[str(position)] = ranking[
            position - 1
        ].get("score")


# ============================================================
# 7. FIND MY RESULT
# ============================================================

my_driver = find_my_driver(
    ranking,
    MY_PSN_ID
)

my_result = None

if my_driver:
    my_score = my_driver.get("score")
    my_rank = my_driver.get("display_rank")
    my_car_code = get_car_code(my_driver)

    my_result = {
        "psn_id": MY_PSN_ID,
        "rank": my_rank,
        "score": my_score,
        "laptime": score_to_laptime(my_score),
        "car_code": my_car_code,
        "car": get_car_name(my_car_code),
        "gap_to_wr_ms":
            my_score - world_record_score,
        "wr_percentage":
            my_score / world_record_score * 100
    }


# ============================================================
# 8. CAR USAGE
# ============================================================

all_counter = Counter()

for driver in ranking:
    car_code = get_car_code(driver)

    if car_code is not None:
        all_counter[car_code] += 1


top100 = ranking[:100]
top500 = ranking[:500]
top1000 = ranking[:1000]

top100_counter = Counter(
    get_car_code(d)
    for d in top100
    if get_car_code(d) is not None
)

top500_counter = Counter(
    get_car_code(d)
    for d in top500
    if get_car_code(d) is not None
)

top1000_counter = Counter(
    get_car_code(d)
    for d in top1000
    if get_car_code(d) is not None
)


# ============================================================
# 9. META SCORE
# ============================================================

meta_scores = []

for car_code in all_counter:

    total = all_counter.get(
        car_code,
        0
    )

    t100 = top100_counter.get(
        car_code,
        0
    )

    t500 = top500_counter.get(
        car_code,
        0
    )

    t1000 = top1000_counter.get(
        car_code,
        0
    )

    meta_score = (
        t100 * 10
        + t500 * 2
        + t1000
        + total / 100
    )

    meta_scores.append({
        "car_code": car_code,
        "car": get_car_name(car_code),
        "top100": t100,
        "top500": t500,
        "top1000": t1000,
        "total": total,
        "meta_score": meta_score
    })


meta_scores.sort(
    key=lambda x:
        x["meta_score"],
    reverse=True
)


# ============================================================
# 10. BUILD SNAPSHOT
# ============================================================

snapshot = {
    "timestamp": timestamp_iso,

    "race": {
        "description": race_c_text,
        "leaderboard_url": race_c_link
    },

    "total_drivers": len(ranking),

    "world_record": {
        "score": world_record_score,
        "laptime":
            score_to_laptime(
                world_record_score
            ),
        "driver":
            world_record_user.get(
                "nick_name",
                "Unknown"
            ),
        "psn_id":
            world_record_user.get(
                "np_online_id"
            ),
        "car_code":
            world_record_car_code,
        "car":
            get_car_name(
                world_record_car_code
            )
    },

    "benchmarks": {
        "103_percent": {
            "score": time_103,
            "laptime":
                score_to_laptime(
                    time_103
                )
        },

        "105_percent": {
            "score": time_105,
            "laptime":
                score_to_laptime(
                    time_105
                )
        }
    },

    "thresholds": {
        position: {
            "score": score,
            "laptime":
                score_to_laptime(
                    score
                )
        }
        for position, score
        in thresholds.items()
    },

    "my_result": my_result,

    "meta_cars": meta_scores[:10]
}


# ============================================================
# 11. LOAD PREVIOUS SNAPSHOT
# ============================================================

previous = load_previous_snapshot()

same_race = (
    previous is not None
    and previous.get(
        "race",
        {}
    ).get(
        "leaderboard_url"
    ) == race_c_link
)


# ============================================================
# 12. BUILD REPORT
# ============================================================

lines = []

lines.append(
    "GT7 DAILY RACE C"
)

lines.append(
    "=" * 70
)

lines.append(
    f"Snapshot: {timestamp_display} - Sao Paulo"
)

lines.append("")

lines.append(
    race_c_text
)

lines.append("")

lines.append(
    f"Total drivers: {len(ranking):,}"
)

lines.append("")

lines.append(
    "WORLD RECORD"
)

lines.append(
    f"{score_to_laptime(world_record_score)} | "
    f"{world_record_user.get('nick_name', 'Unknown')} | "
    f"{get_car_name(world_record_car_code)}"
)

lines.append("")

lines.append(
    "PERFORMANCE BENCHMARKS"
)

lines.append(
    f"103% WR : {score_to_laptime(time_103)}"
)

lines.append(
    f"105% WR : {score_to_laptime(time_105)}"
)

lines.append("")

lines.append(
    "RANKING CUTS"
)

for position in [
    "10",
    "50",
    "100",
    "250",
    "500",
    "1000",
    "2500",
    "5000"
]:
    if position in thresholds:
        lines.append(
            f"Top {position:<4}: "
            f"{score_to_laptime(thresholds[position])}"
        )


lines.append("")

lines.append(
    "MY RESULT"
)

if my_result:

    lines.append(
        f"PSN      : {MY_PSN_ID}"
    )

    lines.append(
        f"Position : #{my_result['rank']:,}"
    )

    lines.append(
        f"Time     : {my_result['laptime']}"
    )

    lines.append(
        f"WR       : {my_result['wr_percentage']:.3f}%"
    )

    lines.append(
        f"Gap      : +{my_result['gap_to_wr_ms'] / 1000:.3f}s"
    )

    lines.append(
        f"Car      : {my_result['car']}"
    )

else:

    lines.append(
        f"{MY_PSN_ID} not found in leaderboard."
    )


lines.append("")

lines.append(
    "MOST USED CARS - TOP 1000"
)

for index, (
    car_code,
    count
) in enumerate(
    top1000_counter.most_common(5),
    start=1
):

    lines.append(
        f"{index}. "
        f"{get_car_name(car_code)} | "
        f"{count} | "
        f"{count / len(top1000) * 100:.1f}%"
    )


lines.append("")

lines.append(
    "META CARS"
)

for index, car in enumerate(
    meta_scores[:5],
    start=1
):

    lines.append(
        f"{index}. {car['car']} | "
        f"Top100 {car['top100']} | "
        f"Top500 {car['top500']} | "
        f"Top1000 {car['top1000']}"
    )


# ============================================================
# 13. COMPARISON WITH PREVIOUS SNAPSHOT
# ============================================================

lines.append("")
lines.append(
    "CHANGE SINCE PREVIOUS SNAPSHOT"
)

if same_race:

    old_wr = previous[
        "world_record"
    ]["score"]

    wr_change = (
        world_record_score
        - old_wr
    )

    lines.append(
        f"World Record : {signed_seconds(wr_change)}"
    )


    old_top500 = (
        previous
        .get("thresholds", {})
        .get("500", {})
        .get("score")
    )

    new_top500 = thresholds.get(
        "500"
    )

    if (
        old_top500 is not None
        and new_top500 is not None
    ):

        lines.append(
            f"Top 500      : "
            f"{signed_seconds(new_top500 - old_top500)}"
        )


    old_my = previous.get(
        "my_result"
    )

    if old_my and my_result:

        lines.append(
            f"My position   : "
            f"#{old_my['rank']:,} -> "
            f"#{my_result['rank']:,} "
            f"({position_change(old_my['rank'], my_result['rank'])})"
        )

        lines.append(
            f"My time       : "
            f"{signed_seconds(my_result['score'] - old_my['score'])}"
        )

    elif my_result and not old_my:

        lines.append(
            "My result     : first recorded lap this week"
        )

    else:

        lines.append(
            "My result     : no comparable result"
        )

else:

    lines.append(
        "First snapshot of this Daily Race C."
    )


lines.append("")
lines.append(
    "=" * 70
)


report_text = "\n".join(
    lines
)


# ============================================================
# 14. SAVE FILES
# ============================================================

LATEST_REPORT_FILE.write_text(
    report_text,
    encoding="utf-8"
)


snapshot_json = json.dumps(
    snapshot,
    ensure_ascii=False,
    indent=2
)


LATEST_SNAPSHOT_FILE.write_text(
    snapshot_json,
    encoding="utf-8"
)


history_file = (
    HISTORY_DIR
    / history_filename
)

history_file.write_text(
    snapshot_json,
    encoding="utf-8"
)


# ============================================================
# 15. PRINT SHORT REPORT TO ACTIONS LOG
# ============================================================

print()
print(report_text)
print()
print(
    f"Report saved to: {LATEST_REPORT_FILE}"
)
print(
    f"Snapshot saved to: {LATEST_SNAPSHOT_FILE}"
)
print(
    f"History saved to: {history_file}"
)