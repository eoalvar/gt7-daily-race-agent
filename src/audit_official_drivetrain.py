import json
import re
import time
import requests

from pathlib import Path
from bs4 import BeautifulSoup


# ============================================================
# CONFIG
# ============================================================

DATA_DIR = Path("data")

REPORT_FILE = (
    DATA_DIR
    / "official_drivetrain_audit.txt"
)

JSON_FILE = (
    DATA_DIR
    / "official_drivetrain_audit.json"
)

BASE_URL = (
    "https://www.gran-turismo.com/"
    "us/gt7/carlist/id/car{}"
)

HEADERS = {
    "User-Agent":
        "Mozilla/5.0 (GT7 Daily Race Agent)"
}


# ============================================================
# CURRENT BRAKE DATABASE
# ============================================================

BRAKE_INFO = {

    1563: {"layout": "MR"},
    2157: {"layout": "FR"},
    2161: {"layout": "4WD"},
    2163: {"layout": "FR"},
    2164: {"layout": "FR"},
    2166: {"layout": "MR"},
    3192: {"layout": "FR"},
    3231: {"layout": "FF"},
    3245: {"layout": "FR"},
    3246: {"layout": "4WD"},
    3247: {"layout": "FR"},
    3248: {"layout": "MR"},
    3249: {"layout": "FR"},
    3251: {"layout": "MR"},
    3252: {"layout": "FR"},
    3253: {"layout": "4WD"},
    3254: {"layout": "FR"},
    3256: {"layout": "4WD"},
    3257: {"layout": "MR"},
    3258: {"layout": "4WD"},
    3259: {"layout": "FF"},
    3260: {"layout": "FF"},
    3261: {"layout": "4WD"},
    3262: {"layout": "FR"},
    3263: {"layout": "MR"},
    3298: {"layout": "FF"},
    3310: {"layout": "MR"},
    3399: {"layout": "FR"},
    3477: {"layout": "FR"},
    3480: {"layout": "FF"},
    3501: {"layout": "FR"},
    3537: {"layout": "FF"}
}


# ============================================================
# LOAD CENTRAL CAR DATABASE
# ============================================================

def load_car_names():

    path = (
        DATA_DIR
        / "car_names.json"
    )

    if not path.exists():
        return {}

    try:

        data = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(
            data,
            dict
        ):
            return {}

        result = {}

        for key, value in data.items():

            try:
                code = int(
                    key
                )

            except Exception:
                continue

            result[
                code
            ] = value

        return result

    except Exception:
        return {}


# ============================================================
# NORMALIZE DRIVETRAIN
# ============================================================

def normalize_drivetrain(value):

    if not isinstance(
        value,
        str
    ):
        return None

    value = (
        value
        .strip()
        .upper()
    )

    aliases = {

        "AWD":
            "4WD",

        "4X4":
            "4WD",

        "FOUR-WHEEL DRIVE":
            "4WD",

        "FOUR WHEEL DRIVE":
            "4WD",

        "FRONT-WHEEL DRIVE":
            "FF",

        "FRONT WHEEL DRIVE":
            "FF"
    }

    value = aliases.get(
        value,
        value
    )

    if value in {
        "FF",
        "FR",
        "MR",
        "RR",
        "4WD"
    }:
        return value

    return None


# ============================================================
# CAR NAME
# ============================================================

def extract_car_name(
    soup
):

    h1 = soup.find(
        "h1"
    )

    if h1:

        value = h1.get_text(
            " ",
            strip=True
        )

        if value:
            return value

    if soup.title:

        title = soup.title.get_text(
            " ",
            strip=True
        )

        title = re.sub(
            r"\s*-\s*Gran Turismo 7 Car List.*$",
            "",
            title,
            flags=re.IGNORECASE
        )

        if title:
            return title

    return None


# ============================================================
# DRIVETRAIN EXTRACTION
# ============================================================

def extract_drivetrain(
    html
):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    # ========================================================
    # METHOD 1
    # Find any element whose visible text is "Drivetrain".
    # Then inspect neighbouring elements.
    # ========================================================

    drivetrain_labels = soup.find_all(
        string=re.compile(
            r"^\s*Drivetrain\s*$",
            re.IGNORECASE
        )
    )

    for label_text in drivetrain_labels:

        label = label_text.parent

        if label is None:
            continue

        # Next sibling
        sibling = label.find_next_sibling()

        if sibling:

            value = normalize_drivetrain(
                sibling.get_text(
                    " ",
                    strip=True
                )
            )

            if value:
                return value

        # Parent container
        parent = label.parent

        if parent:

            parent_text = parent.get_text(
                " ",
                strip=True
            )

            match = re.search(
                r"Drivetrain\s+"
                r"(FF|FR|MR|RR|4WD|AWD)",
                parent_text,
                re.IGNORECASE
            )

            if match:

                value = normalize_drivetrain(
                    match.group(1)
                )

                if value:
                    return value

        # Look at nearby elements
        current = label

        for _ in range(8):

            current = current.find_next()

            if current is None:
                break

            text = current.get_text(
                " ",
                strip=True
            )

            value = normalize_drivetrain(
                text
            )

            if value:
                return value

    # ========================================================
    # METHOD 2
    # Flatten visible page text and search around Drivetrain.
    # ========================================================

    visible_text = soup.get_text(
        " ",
        strip=True
    )

    match = re.search(
        r"\bDrivetrain\b"
        r".{0,100}?"
        r"\b(FF|FR|MR|RR|4WD|AWD)\b",
        visible_text,
        re.IGNORECASE
        | re.DOTALL
    )

    if match:

        value = normalize_drivetrain(
            match.group(1)
        )

        if value:
            return value

    # ========================================================
    # METHOD 3
    # Search raw HTML, stripping tags between label and value.
    # ========================================================

    match = re.search(
        r"Drivetrain"
        r".{0,500}?"
        r">\s*(FF|FR|MR|RR|4WD|AWD)\s*<",
        html,
        re.IGNORECASE
        | re.DOTALL
    )

    if match:

        value = normalize_drivetrain(
            match.group(1)
        )

        if value:
            return value

    # ========================================================
    # METHOD 4
    # Very broad raw HTML fallback.
    # ========================================================

    position = html.lower().find(
        "drivetrain"
    )

    if position != -1:

        fragment = html[
            position:
            position + 1500
        ]

        fragment_text = BeautifulSoup(
            fragment,
            "html.parser"
        ).get_text(
            " ",
            strip=True
        )

        match = re.search(
            r"\b(FF|FR|MR|RR|4WD|AWD)\b",
            fragment_text,
            re.IGNORECASE
        )

        if match:

            value = normalize_drivetrain(
                match.group(1)
            )

            if value:
                return value

    return None


# ============================================================
# DEBUG FRAGMENT
# ============================================================

def drivetrain_debug_fragment(
    html
):

    position = html.lower().find(
        "drivetrain"
    )

    if position == -1:
        return "Word 'Drivetrain' not present in raw HTML."

    start = max(
        0,
        position - 300
    )

    end = min(
        len(html),
        position + 1200
    )

    fragment = html[
        start:end
    ]

    fragment = re.sub(
        r"\s+",
        " ",
        fragment
    )

    return fragment[:1500]


# ============================================================
# REQUEST OFFICIAL PAGE
# ============================================================

def fetch_official_car(
    session,
    car_code
):

    url = BASE_URL.format(
        car_code
    )

    try:

        response = session.get(
            url,
            timeout=30
        )

        response.raise_for_status()

        html = response.text

        soup = BeautifulSoup(
            html,
            "html.parser"
        )

        drivetrain = extract_drivetrain(
            html
        )

        return {

            "success":
                True,

            "url":
                response.url,

            "http":
                response.status_code,

            "name":
                extract_car_name(
                    soup
                ),

            "drivetrain":
                drivetrain,

            "debug_fragment":
                (
                    None
                    if drivetrain
                    else drivetrain_debug_fragment(
                        html
                    )
                ),

            "error":
                None
        }

    except Exception as exc:

        return {

            "success":
                False,

            "url":
                url,

            "http":
                None,

            "name":
                None,

            "drivetrain":
                None,

            "debug_fragment":
                None,

            "error":
                str(
                    exc
                )
        }


# ============================================================
# MAIN
# ============================================================

def main():

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    car_names = load_car_names()

    session = requests.Session()

    session.headers.update(
        HEADERS
    )

    results = []

    matches = 0
    mismatches = 0
    unresolved = 0
    failures = 0


    for index, (
        car_code,
        current
    ) in enumerate(
        BRAKE_INFO.items(),
        start=1
    ):

        local_name = car_names.get(
            car_code,
            f"Unknown car ({car_code})"
        )

        current_layout = (
            normalize_drivetrain(
                current[
                    "layout"
                ]
            )
        )

        print(
            f"[{index:02d}/{len(BRAKE_INFO)}] "
            f"{car_code} | "
            f"{local_name}"
        )

        official = fetch_official_car(
            session,
            car_code
        )

        official_layout = (
            official[
                "drivetrain"
            ]
        )

        if not official[
            "success"
        ]:

            status = (
                "REQUEST_FAILED"
            )

            failures += 1

        elif official_layout is None:

            status = (
                "DRIVETRAIN_NOT_FOUND"
            )

            unresolved += 1

        elif (
            official_layout
            == current_layout
        ):

            status = (
                "MATCH"
            )

            matches += 1

        else:

            status = (
                "MISMATCH"
            )

            mismatches += 1


        results.append({

            "car_code":
                car_code,

            "local_name":
                local_name,

            "official_name":
                official[
                    "name"
                ],

            "current_layout":
                current_layout,

            "official_layout":
                official_layout,

            "status":
                status,

            "official_url":
                official[
                    "url"
                ],

            "http":
                official[
                    "http"
                ],

            "debug_fragment":
                official[
                    "debug_fragment"
                ],

            "error":
                official[
                    "error"
                ]
        })


        time.sleep(
            0.20
        )


    # ========================================================
    # JSON
    # ========================================================

    structured = {

        "cars_audited":
            len(
                BRAKE_INFO
            ),

        "matches":
            matches,

        "mismatches":
            mismatches,

        "unresolved":
            unresolved,

        "request_failures":
            failures,

        "results":
            results
    }


    JSON_FILE.write_text(
        json.dumps(
            structured,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


    # ========================================================
    # REPORT
    # ========================================================

    lines = []


    lines.append(
        "GT7 OFFICIAL DRIVETRAIN AUDIT"
    )

    lines.append(
        "=" * 86
    )

    lines.append(
        "Source              : Official Gran Turismo 7 Car List"
    )

    lines.append(
        f"Cars audited        : "
        f"{len(BRAKE_INFO)}"
    )

    lines.append(
        f"Layout matches      : "
        f"{matches}"
    )

    lines.append(
        f"Layout mismatches   : "
        f"{mismatches}"
    )

    lines.append(
        f"Unresolved pages    : "
        f"{unresolved}"
    )

    lines.append(
        f"Request failures    : "
        f"{failures}"
    )


    lines.append("")
    lines.append(
        "ALL CARS"
    )

    lines.append(
        "-" * 86
    )


    for item in results:

        lines.append(
            f"{item['car_code']} | "
            f"{item['status']:<22} | "
            f"{item['local_name']} | "
            f"Current {item['current_layout']} | "
            f"Official {item['official_layout']}"
        )


    lines.append("")
    lines.append(
        "LAYOUT MISMATCHES REQUIRING CORRECTION"
    )

    lines.append(
        "-" * 86
    )


    mismatch_items = [
        item
        for item in results
        if item[
            "status"
        ] == "MISMATCH"
    ]


    if mismatch_items:

        for item in mismatch_items:

            lines.append(
                f"Code {item['car_code']} | "
                f"{item['local_name']} | "
                f"CURRENT {item['current_layout']} "
                f"-> OFFICIAL {item['official_layout']}"
            )

    else:

        lines.append(
            "None."
        )


    lines.append("")
    lines.append(
        "UNRESOLVED / REQUEST FAILURES"
    )

    lines.append(
        "-" * 86
    )


    problematic = [
        item
        for item in results
        if item[
            "status"
        ] in (
            "DRIVETRAIN_NOT_FOUND",
            "REQUEST_FAILED"
        )
    ]


    if problematic:

        for item in problematic:

            lines.append(
                f"Code {item['car_code']} | "
                f"{item['local_name']} | "
                f"{item['status']}"
            )

    else:

        lines.append(
            "None."
        )


    unresolved_with_debug = [
        item
        for item in results
        if (
            item[
                "status"
            ] == "DRIVETRAIN_NOT_FOUND"
            and item.get(
                "debug_fragment"
            )
        )
    ]


    if unresolved_with_debug:

        lines.append("")
        lines.append(
            "FIRST UNRESOLVED HTML DEBUG"
        )

        lines.append(
            "-" * 86
        )

        first = (
            unresolved_with_debug[
                0
            ]
        )

        lines.append(
            f"Code: "
            f"{first['car_code']}"
        )

        lines.append(
            first[
                "debug_fragment"
            ]
        )


    lines.append("")
    lines.append(
        "=" * 86
    )


    report = "\n".join(
        lines
    )


    REPORT_FILE.write_text(
        report,
        encoding="utf-8"
    )


    print("")
    print(
        report
    )


if __name__ == "__main__":

    main()