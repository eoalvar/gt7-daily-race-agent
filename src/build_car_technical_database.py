import json
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIG
# ============================================================

CAR_LIST_URL = (
    "https://www.gran-turismo.com/us/gt7/carlist/"
)

CAR_PAGE_TEMPLATE = (
    "https://www.gran-turismo.com/us/gt7/carlist/id/car{}"
)

DATA_DIR = Path("data")

CAR_NAMES_FILE = (
    DATA_DIR
    / "car_names.json"
)

OUTPUT_FILE = (
    DATA_DIR
    / "car_technical.json"
)

REQUEST_DELAY_SECONDS = 0.08

HEADERS = {
    "User-Agent":
        "Mozilla/5.0 "
        "(GT7 Technical Car Database Builder)"
}


# ============================================================
# HELPERS
# ============================================================

def clean_text(value):

    if not isinstance(value, str):
        return None

    value = re.sub(
        r"\s+",
        " ",
        value
    ).strip()

    return value or None


def normalize_name(value):

    value = clean_text(
        value
    )

    if not value:
        return ""

    value = (
        value
        .lower()
        .replace("’", "'")
        .replace("‘", "'")
        .replace("´", "'")
        .replace("`", "'")
    )

    value = re.sub(
        r"[^\w\s']",
        " ",
        value,
        flags=re.UNICODE
    )

    value = re.sub(
        r"\s+",
        " ",
        value
    ).strip()

    return value


def extract_number(value):

    if not value:
        return None

    match = re.search(
        r"[-+]?\d+(?:\.\d+)?",
        value.replace(",", "")
    )

    if not match:
        return None

    try:

        return float(
            match.group(0)
        )

    except Exception:

        return None


# ============================================================
# LOAD GTSH CAR NAME DATABASE
# ============================================================

def load_gtsh_car_names():

    if not CAR_NAMES_FILE.exists():

        raise RuntimeError(
            f"Missing car name database: "
            f"{CAR_NAMES_FILE}"
        )


    data = json.loads(
        CAR_NAMES_FILE.read_text(
            encoding="utf-8"
        )
    )


    if not isinstance(
        data,
        dict
    ):

        raise RuntimeError(
            "car_names.json must contain a JSON object."
        )


    result = {}


    for raw_code, name in data.items():

        try:

            car_code = int(
                raw_code
            )

        except Exception:

            continue


        if (
            isinstance(name, str)
            and name.strip()
        ):

            result[
                car_code
            ] = name.strip()


    return result


# ============================================================
# LOAD EXISTING TECHNICAL DATABASE
# ============================================================

def load_existing_database():

    if not OUTPUT_FILE.exists():
        return {}


    try:

        data = json.loads(
            OUTPUT_FILE.read_text(
                encoding="utf-8"
            )
        )

        if isinstance(
            data,
            dict
        ):

            return data


    except Exception:

        pass


    return {}


# ============================================================
# SAVE DATABASE
# ============================================================

def save_database(database):

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )


    ordered = dict(
        sorted(
            database.items(),
            key=lambda item:
                int(item[0])
        )
    )


    OUTPUT_FILE.write_text(
        json.dumps(
            ordered,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


# ============================================================
# DISCOVER OFFICIAL IDS
# ============================================================

def discover_official_ids(
    session
):

    print(
        "Reading official GT7 car list..."
    )


    response = session.get(
        CAR_LIST_URL,
        timeout=60
    )

    response.raise_for_status()


    html = response.text


    ids = set()


    patterns = [
        r"/gt7/carlist/id/car(\d+)",
        r"carlist/id/car(\d+)",
        r"\bcar(\d{3,5})\b"
    ]


    for pattern in patterns:

        for match in re.finditer(
            pattern,
            html,
            flags=re.IGNORECASE
        ):

            try:

                ids.add(
                    int(
                        match.group(1)
                    )
                )

            except Exception:

                continue


    print(
        f"Official IDs discovered in page HTML: "
        f"{len(ids)}"
    )


    return sorted(
        ids
    )


# ============================================================
# PAGE TEXT EXTRACTION
# ============================================================

def soup_text_lines(
    soup
):

    raw = soup.get_text(
        "\n",
        strip=True
    )


    lines = []


    for part in raw.splitlines():

        text = clean_text(
            part
        )

        if text:

            lines.append(
                text
            )


    return lines


def value_after_label(
    lines,
    label
):

    target = label.lower()


    for index, line in enumerate(
        lines
    ):

        if line.lower() != target:
            continue


        for candidate in lines[
            index + 1:
            index + 5
        ]:

            if not candidate:
                continue

            if candidate.lower() == target:
                continue

            return candidate


    return None


# ============================================================
# EXTRACT CAR NAME
# ============================================================

def extract_car_name(
    soup
):

    h1 = soup.find(
        "h1"
    )


    if h1:

        name = clean_text(
            h1.get_text(
                " ",
                strip=True
            )
        )

        if name:

            return name


    title = soup.find(
        "title"
    )


    if title:

        value = clean_text(
            title.get_text(
                " ",
                strip=True
            )
        )


        if value:

            value = re.sub(
                r"\s*-\s*Gran Turismo.*$",
                "",
                value,
                flags=re.IGNORECASE
            )


            value = re.sub(
                r"\s*\|\s*Gran Turismo.*$",
                "",
                value,
                flags=re.IGNORECASE
            )


            return clean_text(
                value
            )


    return None


# ============================================================
# EXTRACT ONE OFFICIAL CAR PAGE
# ============================================================

def extract_official_car(
    session,
    official_id
):

    url = CAR_PAGE_TEMPLATE.format(
        official_id
    )


    response = session.get(
        url,
        timeout=60
    )


    if response.status_code == 404:

        return None


    response.raise_for_status()


    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )


    lines = soup_text_lines(
        soup
    )


    name = extract_car_name(
        soup
    )


    drivetrain_raw = value_after_label(
        lines,
        "Drivetrain"
    )


    power = value_after_label(
        lines,
        "Max Power"
    )


    weight = value_after_label(
        lines,
        "Weight"
    )


    displacement = value_after_label(
        lines,
        "Displacement"
    )


    aspiration = value_after_label(
        lines,
        "Aspiration"
    )


    layout = None


    if drivetrain_raw:

        match = re.search(
            r"\b(FF|FR|MR|RR|4WD)\b",
            drivetrain_raw.upper()
        )


        if match:

            layout = match.group(1)


    if (
        not name
        or not layout
    ):

        return None


    return {
        "official_id":
            official_id,

        "name":
            name,

        "normalized_name":
            normalize_name(
                name
            ),

        "layout":
            layout,

        "max_power_raw":
            power,

        "weight_raw":
            weight,

        "displacement_raw":
            displacement,

        "aspiration":
            aspiration,

        "max_power":
            extract_number(
                power
            ),

        "weight":
            extract_number(
                weight
            ),

        "displacement":
            extract_number(
                displacement
            ),

        "validated":
            True,

        "source":
            "gran_turismo_official",

        "source_url":
            url
    }


# ============================================================
# NAME MATCH HELPERS
# ============================================================

def simplified_name(
    value
):

    value = normalize_name(
        value
    )


    replacements = [
        ("race car", ""),
        ("racing car", ""),
        ("gran turismo", ""),
        ("group 3", "gr 3"),
        ("group 4", "gr 4")
    ]


    for old, new in replacements:

        value = value.replace(
            old,
            new
        )


    value = re.sub(
        r"\s+",
        " ",
        value
    ).strip()


    return value


def names_match(
    gtsh_name,
    official_name
):

    a = simplified_name(
        gtsh_name
    )

    b = simplified_name(
        official_name
    )


    if not a or not b:
        return False


    if a == b:
        return True


    if (
        len(a) >= 8
        and a in b
    ):
        return True


    if (
        len(b) >= 8
        and b in a
    ):
        return True


    return False


# ============================================================
# BUILD GTSH-KEYED TECHNICAL DATABASE
# ============================================================

def build_gtsh_database(
    gtsh_names,
    official_records,
    existing
):

    result = dict(
        existing
    )


    official_list = list(
        official_records.values()
    )


    matched = 0
    unmatched = []


    for car_code, gtsh_name in gtsh_names.items():

        matches = [
            record
            for record
            in official_list
            if names_match(
                gtsh_name,
                record[
                    "name"
                ]
            )
        ]


        if len(matches) == 1:

            record = dict(
                matches[0]
            )


            result[
                str(car_code)
            ] = {
                "name":
                    gtsh_name,

                "official_name":
                    record[
                        "name"
                    ],

                "official_id":
                    record[
                        "official_id"
                    ],

                "layout":
                    record[
                        "layout"
                    ],

                "max_power_raw":
                    record.get(
                        "max_power_raw"
                    ),

                "weight_raw":
                    record.get(
                        "weight_raw"
                    ),

                "displacement_raw":
                    record.get(
                        "displacement_raw"
                    ),

                "aspiration":
                    record.get(
                        "aspiration"
                    ),

                "max_power":
                    record.get(
                        "max_power"
                    ),

                "weight":
                    record.get(
                        "weight"
                    ),

                "displacement":
                    record.get(
                        "displacement"
                    ),

                "validated":
                    True,

                "source":
                    "gran_turismo_official",

                "source_url":
                    record[
                        "source_url"
                    ]
            }


            matched += 1


        else:

            unmatched.append(
                {
                    "car_code":
                        car_code,

                    "name":
                        gtsh_name,

                    "matches":
                        len(matches)
                }
            )


    return {
        "database":
            result,

        "matched":
            matched,

        "unmatched":
            unmatched
    }


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print(
        "GT7 OFFICIAL TECHNICAL CAR DATABASE BUILDER V2"
    )

    print(
        "=" * 78
    )


    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )


    session = requests.Session()

    session.headers.update(
        HEADERS
    )


    gtsh_names = (
        load_gtsh_car_names()
    )


    existing = (
        load_existing_database()
    )


    print(
        f"GTSH car names       : "
        f"{len(gtsh_names)}"
    )

    print(
        f"Existing tech records: "
        f"{len(existing)}"
    )


    discovered_ids = (
        discover_official_ids(
            session
        )
    )


    # ========================================================
    # FALLBACK ID STRATEGY
    #
    # If the main list does not expose individual IDs in HTML,
    # try IDs already known by GTSH.
    #
    # This is safe because invalid IDs simply return no
    # usable official record.
    # ========================================================

    candidate_ids = set(
        discovered_ids
    )


    candidate_ids.update(
        gtsh_names.keys()
    )


    candidate_ids = sorted(
        candidate_ids
    )


    print(
        f"Candidate official IDs: "
        f"{len(candidate_ids)}"
    )


    official_records = {}


    print()
    print(
        "READING OFFICIAL CAR PAGES"
    )

    print(
        "-" * 78
    )


    checked = 0
    valid = 0
    failed = 0


    for index, official_id in enumerate(
        candidate_ids,
        start=1
    ):

        checked += 1


        try:

            record = extract_official_car(
                session,
                official_id
            )


            if record:

                official_records[
                    official_id
                ] = record


                valid += 1


                print(
                    f"[{index:03d}/{len(candidate_ids):03d}] "
                    f"{official_id:4d} | "
                    f"{record['layout']:>3} | "
                    f"{record['name']}"
                )


            else:

                if (
                    index <= 10
                    or index % 50 == 0
                ):

                    print(
                        f"[{index:03d}/{len(candidate_ids):03d}] "
                        f"{official_id:4d} | "
                        f"NO OFFICIAL MATCH"
                    )


        except Exception as error:

            failed += 1


            print(
                f"[{index:03d}/{len(candidate_ids):03d}] "
                f"{official_id:4d} | ERROR | "
                f"{error}"
            )


        time.sleep(
            REQUEST_DELAY_SECONDS
        )


    print()
    print(
        "MATCHING GTSH CODES TO OFFICIAL DATABASE"
    )

    print(
        "-" * 78
    )


    match_result = build_gtsh_database(
        gtsh_names,
        official_records,
        existing
    )


    database = match_result[
        "database"
    ]


    save_database(
        database
    )


    validated_count = sum(
        1
        for record
        in database.values()
        if (
            isinstance(
                record,
                dict
            )
            and record.get(
                "validated"
            )
            and record.get(
                "layout"
            )
            in {
                "FF",
                "FR",
                "MR",
                "RR",
                "4WD"
            }
        )
    )


    print(
        f"Exact/unique matches : "
        f"{match_result['matched']}"
    )

    print(
        f"Unmatched GTSH cars  : "
        f"{len(match_result['unmatched'])}"
    )


    if match_result[
        "unmatched"
    ]:

        print()
        print(
            "UNMATCHED SAMPLE"
        )

        print(
            "-" * 78
        )


        for item in match_result[
            "unmatched"
        ][
            :20
        ]:

            print(
                f"{item['car_code']} | "
                f"{item['name']} | "
                f"candidate matches: "
                f"{item['matches']}"
            )


    print()
    print(
        "=" * 78
    )

    print(
        f"GTSH cars               : "
        f"{len(gtsh_names)}"
    )

    print(
        f"Candidate IDs checked   : "
        f"{checked}"
    )

    print(
        f"Official records found  : "
        f"{valid}"
    )

    print(
        f"Request failures        : "
        f"{failed}"
    )

    print(
        f"GTSH cars matched       : "
        f"{match_result['matched']}"
    )

    print(
        f"Validated technical     : "
        f"{validated_count}"
    )

    print(
        f"Database records        : "
        f"{len(database)}"
    )

    print(
        f"Saved to                : "
        f"{OUTPUT_FILE}"
    )

    print(
        "=" * 78
    )


if __name__ == "__main__":
    main()