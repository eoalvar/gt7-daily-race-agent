import requests
import json
import re
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
# CAR DATABASE
# ============================================================

CAR_INFO = {
    2157: {
        "name": "Aston Martin V8 Vantage Gr.4",
        "layout": "FR",
        "qual_bb": 1,
        "race_bb": 2,
    },

    2161: {
        "name": "Nissan GT-R Gr.4",
        "layout": "4WD",
        "qual_bb": 2,
        "race_bb": 3,
    },

    2163: {
        "name": "Genesis Gr.4",
        "layout": "FR",
        "qual_bb": 1,
        "race_bb": 2,
    },

    2164: {
        "name": "Ford Mustang Gr.4",
        "layout": "FR",
        "qual_bb": 1,
        "race_bb": 2,
    },

    2166: {
        "name": "Alfa Romeo 4C Gr.4",
        "layout": "MR",
        "qual_bb": 0,
        "race_bb": -1,
    },

    3192: {
        "name": "Mercedes-Benz SLS AMG Gr.4",
        "layout": "FR",
        "qual_bb": 1,
        "race_bb": 2,
    },

    3231: {
        "name": "Volkswagen Scirocco Gr.4",
        "layout": "FF",
        "qual_bb": 3,
        "race_bb": 4,
    },

    3245: {
        "name": "BMW M4 Gr.4",
        "layout": "FR",
        "qual_bb": 1,
        "race_bb": 2,
    },

    3246: {
        "name": "Bugatti Veyron Gr.4",
        "layout": "4WD",
        "qual_bb": 2,
        "race_bb": 3,
    },

    3247: {
        "name": "Chevrolet Corvette C7 Gr.4",
        "layout": "FR",
        "qual_bb": 1,
        "race_bb": 2,
    },

    3248: {
        "name": "GT by Citroën Gr.4",
        "layout": "MR",
        "qual_bb": 0,
        "race_bb": -1,
    },

    3249: {
        "name": "Dodge Viper Gr.4",
        "layout": "FR",
        "qual_bb": 1,
        "race_bb": 2,
    },

    3251: {
        "name": "Honda NSX Gr.4",
        "layout": "MR",
        "qual_bb": -1,
        "race_bb": -2,
    },

    3252: {
        "name": "Jaguar F-type Gr.4",
        "layout": "FR",
        "qual_bb": 1,
        "race_bb": 2,
    },

    3253: {
        "name": "Lamborghini Huracán Gr.4",
        "layout": "4WD",
        "qual_bb": 1,
        "race_bb": 2,
    },

    3254: {
        "name": "Lexus RC F Gr.4",
        "layout": "FR",
        "qual_bb": 1,
        "race_bb": 2,
    },

    3256: {
        "name": "Mazda Atenza Gr.4",
        "layout": "4WD",
        "qual_bb": 2,
        "race_bb": 3,
    },

    3257: {
        "name": "McLaren 650S Gr.4",
        "layout": "MR",
        "qual_bb": -1,
        "race_bb": -2,
    },

    3258: {
        "name": "Mitsubishi Lancer Evolution Final Gr.4",
        "layout": "4WD",
        "qual_bb": 2,
        "race_bb": 3,
    },

    3259: {
        "name": "Peugeot RCZ Gr.4",
        "layout": "FF",
        "qual_bb": 3,
        "race_bb": 4,
    },

    3260: {
        "name": "Renault Mégane Gr.4",
        "layout": "FF",
        "qual_bb": 3,
        "race_bb": 4,
    },

    3261: {
        "name": "Subaru WRX Gr.4",
        "layout": "4WD",
        "qual_bb": 2,
        "race_bb": 3,
    },

    3262: {
        "name": "Toyota 86 Gr.4",
        "layout": "FR",
        "qual_bb": 1,
        "race_bb": 2,
    },

    3263: {
        "name": "Ferrari 458 Italia Gr.4",
        "layout": "MR",
        "qual_bb": -1,
        "race_bb": -2,
    },

    3298: {
        "name": "Audi TT Cup '16",
        "layout": "FF",
        "qual_bb": 3,
        "race_bb": 4,
    },

    3310: {
        "name": "Porsche Cayman GT4 Clubsport '16",
        "layout": "MR",
        "qual_bb": -1,
        "race_bb": -2,
    },

    3399: {
        "name": "Toyota GR Supra Race Car '19",
        "layout": "FR",
        "qual_bb": 1,
        "race_bb": 2,
    },

    3477: {
        "name": "Nissan Silvia spec-R Aero (S15) Touring Car",
        "layout": "FR",
        "qual_bb": 1,
        "race_bb": 2,
    },

    3480: {
        "name": "Suzuki Swift Sport Gr.4",
        "layout": "FF",
        "qual_bb": 3,
        "race_bb": 4,
    },

    3501: {
        "name": "Genesis G70 GR4",
        "layout": "FR",
        "qual_bb": 1,
        "race_bb": 2,
    },

    3537: {
        "name": "Mazda3 Gr.4",
        "layout": "FF",
        "qual_bb": 3,
        "race_bb": 4,
    },

    1563: {
        "name": "Renault Mégane Trophy '11",
        "layout": "MR",
        "qual_bb": 0,
        "race_bb": -1,
    },
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

    return (
        driver
        .get("ranking_stats", {})
        .get("car_code")
    )


def get_car_name(car_code):

    car = CAR_INFO.get(car_code)

    if car:
        return car["name"]

    return f"Unknown car ({car_code})"


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

    return (
        f"{sign}"
        f"{delta_ms / 1000:.3f}s"
    )


def position_change(old_rank, new_rank):

    if old_rank is None or new_rank is None:
        return "N/A"

    difference = old_rank - new_rank

    if difference > 0:
        return f"+{difference} positions"

    if difference < 0:
        return f"{difference} positions"

    return "unchanged"


def extract_tyre_multiplier(race_text):

    match = re.search(
        r"Tyres\s*x(\d+)",
        race_text,
        re.IGNORECASE
    )

    if match:
        return int(match.group(1))

    return 1


def format_bb(value):

    if value > 0:
        return f"+{value}"

    return str(value)


def brake_balance_recommendation(
    car_code,
    tyre_multiplier
):

    info = CAR_INFO.get(
        car_code
    )

    if not info:

        return {
            "qualifying": 0,
            "race": 0,
            "layout": "Unknown",
            "confidence": "Low",
            "reason":
                "Car not present in local brake-balance database."
        }

    qualifying = info[
        "qual_bb"
    ]

    race = info[
        "race_bb"
    ]

    layout = info[
        "layout"
    ]

    # When tire wear is low, keep race
    # recommendation closer to qualifying.
    if tyre_multiplier <= 1:
        race = qualifying

    elif tyre_multiplier <= 2:

        if race > qualifying:
            race = qualifying + 1

        elif race < qualifying:
            race = qualifying - 1


    if layout == "FF":

        reason = (
            "Rearward bias helps rotation under trail braking "
            "and reduces front-brake/front-tire workload."
        )

    elif layout == "FR":

        reason = (
            "Mild rearward bias improves rotation while retaining "
            "good braking stability."
        )

    elif layout == "MR":

        reason = (
            "Neutral/slightly forward bias prioritizes rear stability; "
            "the race setting also helps manage the rear axle."
        )

    elif layout == "4WD":

        reason = (
            "Moderate rearward bias is used as a starting point "
            "to improve rotation without making braking too unstable."
        )

    else:

        reason = (
            "Neutral baseline recommendation."
        )


    confidence = "Medium"

    return {
        "qualifying":
            qualifying,

        "race":
            race,

        "layout":
            layout,

        "confidence":
            confidence,

        "reason":
            reason
    }


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

start = html.find(
    marker
)

if start == -1:

    raise RuntimeError(
        "Could not find initialRanking."
    )


start += len(
    marker
)


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


winner = ranking[
    0
]

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
    world_record_score
    * 1.03
)

time_105 = round(
    world_record_score
    * 1.05
)


tyre_multiplier = extract_tyre_multiplier(
    race_c_text
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

    if len(
        ranking
    ) >= position:

        thresholds[
            str(position)
        ] = ranking[
            position - 1
        ].get(
            "score"
        )


# ============================================================
# 7. FIND MY RESULT
# ============================================================

my_driver = find_my_driver(
    ranking,
    MY_PSN_ID
)

my_result = None


if my_driver:

    my_score = my_driver.get(
        "score"
    )

    my_rank = my_driver.get(
        "display_rank"
    )

    my_car_code = get_car_code(
        my_driver
    )


    my_result = {

        "psn_id":
            MY_PSN_ID,

        "rank":
            my_rank,

        "score":
            my_score,

        "laptime":
            score_to_laptime(
                my_score
            ),

        "car_code":
            my_car_code,

        "car":
            get_car_name(
                my_car_code
            ),

        "gap_to_wr_ms":
            my_score
            - world_record_score,

        "wr_percentage":
            my_score
            / world_record_score
            * 100
    }


# ============================================================
# 8. CAR USAGE
# ============================================================

all_counter = Counter()


for driver in ranking:

    car_code = get_car_code(
        driver
    )

    if car_code is not None:

        all_counter[
            car_code
        ] += 1


top100 = ranking[
    :100
]

top500 = ranking[
    :500
]

top1000 = ranking[
    :1000
]


top100_counter = Counter(
    get_car_code(
        driver
    )
    for driver in top100
    if get_car_code(
        driver
    ) is not None
)


top500_counter = Counter(
    get_car_code(
        driver
    )
    for driver in top500
    if get_car_code(
        driver
    ) is not None
)


top1000_counter = Counter(
    get_car_code(
        driver
    )
    for driver in top1000
    if get_car_code(
        driver
    ) is not None
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

        "car_code":
            car_code,

        "car":
            get_car_name(
                car_code
            ),

        "top100":
            t100,

        "top500":
            t500,

        "top1000":
            t1000,

        "total":
            total,

        "meta_score":
            meta_score
    })


meta_scores.sort(
    key=lambda item:
        item[
            "meta_score"
        ],
    reverse=True
)


# ============================================================
# 10. TOP 5 USED CARS + BRAKE BALANCE
# ============================================================

top5_used_cars = []


for car_code, count in top1000_counter.most_common(
    5
):

    bb = brake_balance_recommendation(
        car_code,
        tyre_multiplier
    )


    top5_used_cars.append({

        "car_code":
            car_code,

        "car":
            get_car_name(
                car_code
            ),

        "count":
            count,

        "percentage":
            count
            / len(
                top1000
            )
            * 100,

        "layout":
            bb[
                "layout"
            ],

        "qualifying_bb":
            bb[
                "qualifying"
            ],

        "race_bb":
            bb[
                "race"
            ],

        "confidence":
            bb[
                "confidence"
            ],

        "reason":
            bb[
                "reason"
            ]
    })


# ============================================================
# 11. BUILD SNAPSHOT
# ============================================================

snapshot = {

    "timestamp":
        timestamp_iso,

    "race": {

        "description":
            race_c_text,

        "leaderboard_url":
            race_c_link,

        "tyre_multiplier":
            tyre_multiplier
    },

    "total_drivers":
        len(
            ranking
        ),

    "world_record": {

        "score":
            world_record_score,

        "laptime":
            score_to_laptime(
                world_record_score
            ),

        "driver":
            world_record_user.get(
                "nick_name",
                "Unknown"
            ),

        "car":
            get_car_name(
                world_record_car_code
            )
    },

    "benchmarks": {

        "103_percent":
            score_to_laptime(
                time_103
            ),

        "105_percent":
            score_to_laptime(
                time_105
            )
    },

    "thresholds": {

        position:
            score_to_laptime(
                score
            )

        for position, score
        in thresholds.items()
    },

    "my_result":
        my_result,

    "meta_cars":
        meta_scores[
            :10
        ],

    "brake_balance":
        top5_used_cars
}


# ============================================================
# 12. LOAD PREVIOUS SNAPSHOT
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
# 13. BUILD REPORT
# ============================================================

lines = []


lines.append(
    "GT7 DAILY RACE C"
)

lines.append(
    "=" * 70
)

lines.append(
    f"Snapshot: "
    f"{timestamp_display} - Sao Paulo"
)

lines.append("")

lines.append(
    race_c_text
)

lines.append("")

lines.append(
    f"Total drivers: "
    f"{len(ranking):,}"
)


# WORLD RECORD

lines.append("")

lines.append(
    "WORLD RECORD"
)

lines.append(
    f"{score_to_laptime(world_record_score)} | "
    f"{world_record_user.get('nick_name', 'Unknown')} | "
    f"{get_car_name(world_record_car_code)}"
)


# BENCHMARKS

lines.append("")

lines.append(
    "PERFORMANCE BENCHMARKS"
)

lines.append(
    f"103% WR : "
    f"{score_to_laptime(time_103)}"
)

lines.append(
    f"105% WR : "
    f"{score_to_laptime(time_105)}"
)


# RANKING CUTS

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


# MY RESULT

lines.append("")

lines.append(
    "MY RESULT"
)


if my_result:

    lines.append(
        f"PSN      : "
        f"{MY_PSN_ID}"
    )

    lines.append(
        f"Position : "
        f"#{my_result['rank']:,}"
    )

    lines.append(
        f"Time     : "
        f"{my_result['laptime']}"
    )

    lines.append(
        f"WR       : "
        f"{my_result['wr_percentage']:.3f}%"
    )

    lines.append(
        f"Gap      : "
        f"+{my_result['gap_to_wr_ms'] / 1000:.3f}s"
    )

    lines.append(
        f"Car      : "
        f"{my_result['car']}"
    )

else:

    lines.append(
        f"{MY_PSN_ID} "
        f"not found in leaderboard."
    )


# MOST USED CARS

lines.append("")

lines.append(
    "MOST USED CARS - TOP 1000"
)


for index, car in enumerate(
    top5_used_cars,
    start=1
):

    lines.append(
        f"{index}. "
        f"{car['car']} | "
        f"{car['count']} | "
        f"{car['percentage']:.1f}%"
    )


# BRAKE BALANCE

lines.append("")

lines.append(
    "BRAKE BALANCE RECOMMENDATIONS"
)

lines.append(
    "Convention: negative = more front, "
    "positive = more rear."
)

lines.append(
    f"Tyre wear multiplier detected: x{tyre_multiplier}"
)

lines.append(
    "These are recommended starting points, "
    "not verified telemetry-derived optimums."
)

lines.append("")


for index, car in enumerate(
    top5_used_cars,
    start=1
):

    lines.append(
        f"{index}. {car['car']}"
    )

    lines.append(
        f"   Layout     : "
        f"{car['layout']}"
    )

    lines.append(
        f"   Qualifying : "
        f"BB {format_bb(car['qualifying_bb'])}"
    )

    lines.append(
        f"   Race       : "
        f"BB {format_bb(car['race_bb'])}"
    )

    lines.append(
        f"   Confidence : "
        f"{car['confidence']}"
    )

    lines.append(
        f"   Reason     : "
        f"{car['reason']}"
    )

    lines.append("")


# META CARS

lines.append(
    "META CARS"
)


for index, car in enumerate(
    meta_scores[
        :5
    ],
    start=1
):

    lines.append(
        f"{index}. "
        f"{car['car']} | "
        f"Top100 {car['top100']} | "
        f"Top500 {car['top500']} | "
        f"Top1000 {car['top1000']}"
    )


# CHANGE SINCE PREVIOUS

lines.append("")

lines.append(
    "CHANGE SINCE PREVIOUS SNAPSHOT"
)


if same_race:

    old_wr = previous[
        "world_record"
    ][
        "score"
    ]

    wr_change = (
        world_record_score
        - old_wr
    )

    lines.append(
        f"World Record : "
        f"{signed_seconds(wr_change)}"
    )


    old_my = previous.get(
        "my_result"
    )


    if old_my and my_result:

        lines.append(
            f"My position  : "
            f"#{old_my['rank']:,} -> "
            f"#{my_result['rank']:,} "
            f"({position_change(old_my['rank'], my_result['rank'])})"
        )

        lines.append(
            f"My time      : "
            f"{signed_seconds(my_result['score'] - old_my['score'])}"
        )


    elif my_result and not old_my:

        lines.append(
            "My result    : first recorded lap this week"
        )

    else:

        lines.append(
            "My result    : no comparable result"
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
# 15. PRINT REPORT
# ============================================================

print(
    report_text
)