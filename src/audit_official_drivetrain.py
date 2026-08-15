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
        "Mozilla/5.0 "
        "(GT7 Daily Race Agent - drivetrain audit)"
}


# ============================================================
# CURRENT BRAKE DATABASE
#
# These are the layouts currently used by our main script.
# The purpose of this program is to verify them against the
# official Gran Turismo car pages.
# ============================================================

BRAKE_INFO = {

    1563: {
        "layout": "MR"
    },

    2157: {
        "layout": "FR"
    },

    2161: {
        "layout": "4WD"
    },

    2163: {
        "layout": "FR"
    },

    2164: {
        "layout": "FR"
    },

    2166: {
        "layout": "MR"
    },

    3192: {
        "layout": "FR"
    },

    3231: {
        "layout": "FF"
    },

    3245: {
        "layout": "FR"
    },

    3246: {
        "layout": "4WD"
    },

    3247: {
        "layout": "FR"
    },

    3248: {
        "layout": "MR"
    },

    3249: {
        "layout": "FR"
    },

    3251: {
        "layout": "MR"
    },

    3252: {
        "layout": "FR"
    },

    3253: {
        "layout": "4WD"
    },

    3254: {
        "layout": "FR"
    },

    3256: {
        "layout": "4WD"
    },

    3257: {
        "layout": "MR"
    },

    3258: {
        "layout": "4WD"
    },

    3259: {
        "layout": "FF"
    },

    3260: {
        "layout": "FF"
    },

    3261: {
        "layout": "4WD"
    },

    3262: {
        "layout": "FR"
    },

    3263: {
        "layout": "MR"
    },

    3298: {
        "layout": "FF"
    },

    3310: {
        "layout": "MR"
    },

    3399: {
        "layout": "FR"
    },

    3477: {
        "layout": "FR"
    },

    3480: {
        "layout": "FF"
    },

    3501: {
        "layout": "FR"
    },

    3537: {
        "layout": "FF"
    }
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
            "FF",

        "REAR-WHEEL DRIVE":
            "FR",

        "REAR WHEEL DRIVE":
            "FR"
    }


    return aliases.get(
        value,
        value
    )


# ============================================================
# EXTRACT PAGE TITLE / CAR NAME
# ============================================================

def extract_car_name(
    soup
):

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


    heading = soup.find(
        ["h1", "h2"]
    )


    if heading:

        text = heading.get_text(
            " ",
            strip=True
        )


        if text:

            return text


    return None


# ============================================================
# EXTRACT OFFICIAL DRIVETRAIN
# ============================================================

def extract_drivetrain(
    html
):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )


    # --------------------------------------------------------
    # Method 1:
    # Search structured text around the word Drivetrain.
    # --------------------------------------------------------

    text = soup.get_text(
        "\n",
        strip=True
    )


    lines = [
        line.strip()
        for line
        in text.splitlines()
        if line.strip()
    ]


    for index, line in enumerate(
        lines
    ):

        if (
            line.lower()
            == "drivetrain"
        ):

            for candidate in lines[
                index + 1:
                index + 5
            ]:

                normalized = normalize_drivetrain(
                    candidate
                )


                if normalized in {
                    "FF",
                    "FR",
                    "MR",
                    "RR",
                    "4WD"
                }:

                    return normalized


    # --------------------------------------------------------
    # Method 2:
    # Regex over visible text.
    # --------------------------------------------------------

    match = re.search(
        r"Drivetrain\s*[:\n\r\t ]+"
        r"(FF|FR|MR|RR|4WD|AWD)",
        text,
        re.IGNORECASE
    )


    if match:

        return normalize_drivetrain(
            match.group(1)
        )


    # --------------------------------------------------------
    # Method 3:
    # Regex over raw HTML.
    # --------------------------------------------------------

    match = re.search(
        r"Drivetrain.{0,300}?"
        r"(FF|FR|MR|RR|4WD|AWD)",
        html,
        re.IGNORECASE
        | re.DOTALL
    )


    if match:

        return normalize_drivetrain(
            match.group(1)
        )


    return None


# ============================================================
# REQUEST OFFICIAL CAR PAGE
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


        status_code = (
            response.status_code
        )


        response.raise_for_status()


        html = response.text


        soup = BeautifulSoup(
            html,
            "html.parser"
        )


        name = extract_car_name(
            soup
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
                status_code,

            "name":
                name,

            "drivetrain":
                drivetrain,

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


    print(
        "=" * 86
    )

    print(
        "GT7 OFFICIAL DRIVETRAIN AUDIT"
    )

    print(
        "=" * 86
    )


    for index, (
        car_code,
        current
    ) in enumerate(
        BRAKE_INFO.items(),
        start=1
    ):

        current_layout = normalize_drivetrain(
            current[
                "layout"
            ]
        )


        local_name = car_names.get(
            car_code,
            f"Unknown car ({car_code})"
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


        results.append(
            {

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

                "error":
                    official[
                        "error"
                    ]
            }
        )


        # Be polite to the official site.
        time.sleep(
            0.20
        )


    # ========================================================
    # JSON REPORT
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
    # TEXT REPORT
    # ========================================================

    lines = []


    lines.append(
        "GT7 OFFICIAL DRIVETRAIN AUDIT"
    )


    lines.append(
        "=" * 86
    )


    lines.append(
        "Source              : "
        "Official Gran Turismo 7 Car List"
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


    # ========================================================
    # ALL RESULTS
    # ========================================================

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


    # ========================================================
    # MISMATCHES
    # ========================================================

    lines.append("")


    lines.append(
        "LAYOUT MISMATCHES REQUIRING CORRECTION"
    )


    lines.append(
        "-" * 86
    )


    mismatch_items = [
        item
        for item
        in results
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


    # ========================================================
    # UNRESOLVED
    # ========================================================

    lines.append("")


    lines.append(
        "UNRESOLVED / REQUEST FAILURES"
    )


    lines.append(
        "-" * 86
    )


    problematic = [
        item
        for item
        in results
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
                f"{item['status']} | "
                f"{item['error'] or 'No drivetrain parsed'}"
            )


    else:

        lines.append(
            "None."
        )


    # ========================================================
    # IMPORTANT
    # ========================================================

    lines.append("")


    lines.append(
        "INTERPRETATION"
    )


    lines.append(
        "-" * 86
    )


    lines.append(
        "MATCH means the drivetrain currently used by our "
        "Brake Bias model agrees with the official GT7 page."
    )


    lines.append(
        "MISMATCH means our drivetrain metadata should be "
        "corrected before recalculating Brake Bias."
    )


    lines.append(
        "This audit validates drivetrain only. It does NOT "
        "validate the actual Qualifying or Race Brake Bias values."
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