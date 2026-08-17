import html as html_lib
import json
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIG
# ============================================================

VERSION = "3.0"

DATA_DIR = Path("data")

CAR_NAMES_FILE = (
    DATA_DIR
    / "car_names.json"
)

OUTPUT_FILE = (
    DATA_DIR
    / "car_technical.json"
)

UNRESOLVED_FILE = (
    DATA_DIR
    / "car_technical_unresolved.json"
)

OFFICIAL_PAGE_TEMPLATES = [
    "https://www.gran-turismo.com/us/gt7/carlist/id/car{}",
    "https://www.gran-turismo.com/au/gt7/carlist/id/car{}",
    "https://www.gran-turismo.com/gb/gt7/carlist/id/car{}",
    "https://www.gran-turismo.com/pt/gt7/carlist/id/car{}",
]

REQUEST_DELAY_SECONDS = 0.08

REQUEST_TIMEOUT = 30

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}

VALID_LAYOUTS = {
    "FF",
    "FR",
    "MR",
    "RR",
    "4WD",
}

SEPARATOR = "=" * 78
SUB_SEPARATOR = "-" * 78


# ============================================================
# BASIC HELPERS
# ============================================================

def normalize_space(value):

    if value is None:
        return ""

    value = str(value)

    value = html_lib.unescape(
        value
    )

    value = re.sub(
        r"\s+",
        " ",
        value
    )

    return value.strip()


def normalize_name(value):

    value = normalize_space(
        value
    )

    value = (
        value
        .replace("’", "'")
        .replace("‘", "'")
        .replace("´", "'")
        .replace("`", "'")
        .replace("･", " ")
    )

    value = value.lower()

    value = re.sub(
        r"[^a-z0-9à-ÿ']+",
        " ",
        value,
        flags=re.IGNORECASE
    )

    value = re.sub(
        r"\s+",
        " ",
        value
    )

    return value.strip()


def extract_first_number(value):

    if not value:
        return None

    clean = (
        normalize_space(value)
        .replace(",", "")
    )

    match = re.search(
        r"[-+]?\d+(?:\.\d+)?",
        clean
    )

    if not match:
        return None

    try:

        return float(
            match.group(0)
        )

    except Exception:

        return None


def normalize_layout(value):

    if not value:
        return None

    value = normalize_space(
        value
    ).upper()

    aliases = {
        "AWD": "4WD",
        "4X4": "4WD",
        "FOUR WHEEL DRIVE": "4WD",
        "FOUR-WHEEL DRIVE": "4WD",
        "ALL WHEEL DRIVE": "4WD",
        "ALL-WHEEL DRIVE": "4WD",
    }

    if value in aliases:
        return aliases[value]

    for layout in (
        "4WD",
        "FF",
        "FR",
        "MR",
        "RR",
    ):

        if re.search(
            rf"\b{re.escape(layout)}\b",
            value
        ):

            return layout

    for alias, result in aliases.items():

        if alias in value:
            return result

    return None


# ============================================================
# JSON FILE HELPERS
# ============================================================

def load_json_file(
    path,
    default
):

    if not path.exists():
        return default

    try:

        data = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        return data

    except Exception:

        return default


def save_json_file(
    path,
    data
):

    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    path.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


# ============================================================
# LOAD GTSH CAR DATABASE
# ============================================================

def load_gtsh_car_names():

    data = load_json_file(
        CAR_NAMES_FILE,
        {}
    )

    if not isinstance(
        data,
        dict
    ):

        raise RuntimeError(
            "data/car_names.json is not a JSON object."
        )

    result = {}

    for raw_code, raw_name in data.items():

        try:

            car_code = int(
                raw_code
            )

        except Exception:

            continue

        if (
            not isinstance(
                raw_name,
                str
            )
            or not raw_name.strip()
        ):

            continue

        result[
            car_code
        ] = raw_name.strip()

    if not result:

        raise RuntimeError(
            "No cars were loaded from data/car_names.json."
        )

    return result


# ============================================================
# LOAD EXISTING TECHNICAL DATABASE
# ============================================================

def load_existing_database():

    data = load_json_file(
        OUTPUT_FILE,
        {}
    )

    if not isinstance(
        data,
        dict
    ):

        return {}

    return data


# ============================================================
# HTML / PAGE HELPERS
# ============================================================

def page_is_probably_valid(
    response,
    expected_code
):

    if response.status_code != 200:
        return False

    body = response.text or ""

    if len(body) < 1000:
        return False

    low = body.lower()

    negative_signals = [
        "page not found",
        "404 not found",
        "the requested page could not be found",
    ]

    if any(
        signal in low
        for signal in negative_signals
    ):

        return False

    code_signals = [
        f"car{expected_code}",
        f"/car{expected_code}",
        str(expected_code),
    ]

    if any(
        signal.lower() in low
        for signal in code_signals
    ):

        return True

    # Some localized/rendered pages may not expose the ID
    # in body text, so allow a sufficiently large GT7 page
    # for the extraction stage to judge it.

    return (
        "gran turismo" in low
        and "gt7" in low
    )


def soup_visible_text(
    html
):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    for tag in soup(
        [
            "script",
            "style",
            "noscript",
            "svg",
        ]
    ):

        tag.decompose()

    return normalize_space(
        soup.get_text(
            " ",
            strip=True
        )
    )


def extract_title_name(
    html
):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    h1 = soup.find(
        "h1"
    )

    if h1:

        text = normalize_space(
            h1.get_text(
                " ",
                strip=True
            )
        )

        if (
            text
            and "gran turismo" not in text.lower()
        ):

            return text

    og_title = soup.find(
        "meta",
        attrs={
            "property": "og:title"
        }
    )

    if (
        og_title
        and og_title.get(
            "content"
        )
    ):

        text = normalize_space(
            og_title.get(
                "content"
            )
        )

        text = re.sub(
            r"\s*[-|]\s*Gran Turismo.*$",
            "",
            text,
            flags=re.IGNORECASE
        )

        if text:
            return text

    title = soup.find(
        "title"
    )

    if title:

        text = normalize_space(
            title.get_text(
                " ",
                strip=True
            )
        )

        text = re.sub(
            r"\s*[-|]\s*Gran Turismo.*$",
            "",
            text,
            flags=re.IGNORECASE
        )

        if text:
            return text

    return None


# ============================================================
# GENERIC LABEL EXTRACTION
# ============================================================

def extract_label_value_from_text(
    text,
    labels,
    value_pattern=None
):

    if not text:
        return None

    for label in labels:

        escaped = re.escape(
            label
        )

        if value_pattern:

            pattern = (
                rf"{escaped}\s*[:\-]?\s*"
                rf"({value_pattern})"
            )

        else:

            pattern = (
                rf"{escaped}\s*[:\-]?\s*"
                r"([^|<>]{1,80})"
            )

        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE
        )

        if match:

            return normalize_space(
                match.group(1)
            )

    return None


# ============================================================
# RAW HTML EXTRACTION
# ============================================================

def extract_layout_from_raw_html(
    html
):

    decoded = html_lib.unescape(
        html or ""
    )

    candidates = [
        (
            [
                "Drivetrain",
                "Drive Train",
                "Drive Type",
                "Sistema de tração",
                "Sistema de tracao",
                "Trasmissione",
                "Transmission",
            ],
            r"(?:4WD|AWD|4X4|FF|FR|MR|RR)"
        )
    ]

    for labels, value_pattern in candidates:

        value = extract_label_value_from_text(
            decoded,
            labels,
            value_pattern
        )

        layout = normalize_layout(
            value
        )

        if layout:
            return layout

    # JSON-like structures.

    json_patterns = [
        r'["\'](?:drivetrain|drive_train|driveType|drive_type|layout)["\']'
        r'\s*:\s*["\']([^"\']+)["\']',

        r'["\'](?:Drivetrain|Drive Type)["\']'
        r'\s*:\s*["\']([^"\']+)["\']',
    ]

    for pattern in json_patterns:

        for match in re.finditer(
            pattern,
            decoded,
            flags=re.IGNORECASE
        ):

            layout = normalize_layout(
                match.group(1)
            )

            if layout:
                return layout

    return None


def extract_spec_from_raw_html(
    html,
    labels
):

    decoded = html_lib.unescape(
        html or ""
    )

    visible = re.sub(
        r"<[^>]+>",
        " ",
        decoded
    )

    visible = normalize_space(
        visible
    )

    for label in labels:

        match = re.search(
            rf"{re.escape(label)}"
            r"\s*[:\-]?\s*"
            r"([^|]{1,90})",
            visible,
            flags=re.IGNORECASE
        )

        if match:

            value = normalize_space(
                match.group(1)
            )

            # Stop when another known specification label
            # starts appearing in the captured text.

            value = re.split(
                (
                    r"\b(?:"
                    r"Drivetrain|"
                    r"Drive Type|"
                    r"Max\.?\s*Power|"
                    r"Maximum Power|"
                    r"Weight|"
                    r"Displacement|"
                    r"Aspiration|"
                    r"Length|"
                    r"Width|"
                    r"Height"
                    r")\b"
                ),
                value,
                maxsplit=1,
                flags=re.IGNORECASE
            )[0]

            value = normalize_space(
                value
            )

            if value:
                return value

    return None


# ============================================================
# SCRIPT / JSON RECURSIVE SEARCH
# ============================================================

def recursive_find_values(
    obj,
    interesting_keys,
    found
):

    if isinstance(
        obj,
        dict
    ):

        for key, value in obj.items():

            key_norm = (
                str(key)
                .strip()
                .lower()
                .replace("-", "_")
                .replace(" ", "_")
            )

            if key_norm in interesting_keys:

                found.append(
                    value
                )

            recursive_find_values(
                value,
                interesting_keys,
                found
            )

    elif isinstance(
        obj,
        list
    ):

        for value in obj:

            recursive_find_values(
                value,
                interesting_keys,
                found
            )


def extract_json_objects_from_scripts(
    html
):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    objects = []

    for script in soup.find_all(
        "script"
    ):

        raw = script.string

        if not raw:

            raw = script.get_text(
                " ",
                strip=True
            )

        raw = (
            raw or ""
        ).strip()

        if not raw:
            continue

        script_type = (
            script.get(
                "type",
                ""
            )
            .lower()
        )

        if (
            script_type
            in {
                "application/json",
                "application/ld+json",
            }
            or raw.startswith(
                "{"
            )
            or raw.startswith(
                "["
            )
        ):

            try:

                obj = json.loads(
                    raw
                )

                objects.append(
                    obj
                )

            except Exception:

                pass

        # Search for JSON object fragments after common
        # assignment markers.

        assignment_patterns = [
            r"__NEXT_DATA__\s*=\s*",
            r"__NUXT__\s*=\s*",
            r"window\.__INITIAL_STATE__\s*=\s*",
            r"window\.__DATA__\s*=\s*",
        ]

        for pattern in assignment_patterns:

            match = re.search(
                pattern,
                raw
            )

            if not match:
                continue

            tail = raw[
                match.end():
            ].lstrip()

            try:

                decoder = json.JSONDecoder()

                obj, _ = decoder.raw_decode(
                    tail
                )

                objects.append(
                    obj
                )

            except Exception:

                pass

    return objects


def extract_layout_from_script_json(
    html
):

    keys = {
        "drivetrain",
        "drive_train",
        "drive_type",
        "drivetype",
        "layout",
    }

    for obj in extract_json_objects_from_scripts(
        html
    ):

        values = []

        recursive_find_values(
            obj,
            keys,
            values
        )

        for value in values:

            layout = normalize_layout(
                value
            )

            if layout:
                return layout

    return None


# ============================================================
# FULL TECHNICAL EXTRACTION
# ============================================================

def extract_official_record(
    html,
    car_code,
    url,
    gtsh_name
):

    visible_text = soup_visible_text(
        html
    )

    name = extract_title_name(
        html
    )

    layout = (
        extract_layout_from_raw_html(
            html
        )
        or extract_layout_from_script_json(
            html
        )
    )

    # Final fallback against visible text.

    if not layout:

        layout = extract_label_value_from_text(
            visible_text,
            [
                "Drivetrain",
                "Drive Train",
                "Drive Type",
                "Sistema de tração",
                "Sistema de tracao",
                "Trasmissione",
            ],
            r"(?:4WD|AWD|4X4|FF|FR|MR|RR)"
        )

        layout = normalize_layout(
            layout
        )

    if not layout:

        return None

    power_raw = extract_spec_from_raw_html(
        html,
        [
            "Max. Power",
            "Max Power",
            "Maximum Power",
            "Potência Máx.",
            "Potencia Max.",
            "Potenza max.",
        ]
    )

    weight_raw = extract_spec_from_raw_html(
        html,
        [
            "Weight",
            "Peso",
        ]
    )

    displacement_raw = extract_spec_from_raw_html(
        html,
        [
            "Displacement",
            "Cilindrada",
            "Cilindrata",
        ]
    )

    aspiration_raw = extract_spec_from_raw_html(
        html,
        [
            "Aspiration",
            "Aspiração",
            "Aspiracao",
            "Aspirazione",
        ]
    )

    official_name = (
        name
        or gtsh_name
    )

    return {
        "name":
            gtsh_name,

        "official_name":
            official_name,

        "official_id":
            car_code,

        "layout":
            layout,

        "max_power_raw":
            power_raw,

        "weight_raw":
            weight_raw,

        "displacement_raw":
            displacement_raw,

        "aspiration":
            aspiration_raw,

        "max_power":
            extract_first_number(
                power_raw
            ),

        "weight":
            extract_first_number(
                weight_raw
            ),

        "displacement":
            extract_first_number(
                displacement_raw
            ),

        "validated":
            True,

        "source":
            "gran_turismo_official",

        "source_url":
            url,
    }


# ============================================================
# FETCH ONE CAR
# ============================================================

def fetch_official_car(
    session,
    car_code,
    gtsh_name
):

    diagnostics = []

    for template in OFFICIAL_PAGE_TEMPLATES:

        url = template.format(
            car_code
        )

        try:

            response = session.get(
                url,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True
            )

        except Exception as error:

            diagnostics.append(
                {
                    "url":
                        url,

                    "status":
                        "REQUEST_ERROR",

                    "error":
                        str(error),
                }
            )

            continue

        diagnostics.append(
            {
                "url":
                    response.url,

                "status":
                    response.status_code,

                "bytes":
                    len(
                        response.content
                    ),
            }
        )

        if not page_is_probably_valid(
            response,
            car_code
        ):

            continue

        record = extract_official_record(
            response.text,
            car_code,
            response.url,
            gtsh_name
        )

        if record:

            return {
                "record":
                    record,

                "diagnostics":
                    diagnostics,
            }

    return {
        "record":
            None,

        "diagnostics":
            diagnostics,
    }


# ============================================================
# SAFETY CHECK AGAINST NAME
# ============================================================

def name_match_confidence(
    gtsh_name,
    official_name
):

    if not gtsh_name:
        return "UNKNOWN"

    if not official_name:
        return "UNKNOWN"

    a = normalize_name(
        gtsh_name
    )

    b = normalize_name(
        official_name
    )

    if not a or not b:
        return "UNKNOWN"

    if a == b:
        return "EXACT"

    if (
        len(a) >= 8
        and a in b
    ):
        return "STRONG"

    if (
        len(b) >= 8
        and b in a
    ):
        return "STRONG"

    a_words = set(
        a.split()
    )

    b_words = set(
        b.split()
    )

    if not a_words or not b_words:
        return "WEAK"

    overlap = len(
        a_words
        & b_words
    )

    union = len(
        a_words
        | b_words
    )

    similarity = (
        overlap
        / union
        if union
        else 0
    )

    if similarity >= 0.65:
        return "STRONG"

    if similarity >= 0.40:
        return "MEDIUM"

    return "WEAK"


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print(
        f"GT7 TECHNICAL CAR DATABASE BUILDER V{VERSION}"
    )
    print(
        SEPARATOR
    )

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    session = requests.Session()

    session.headers.update(
        HEADERS
    )

    gtsh_names = load_gtsh_car_names()

    existing = load_existing_database()

    print(
        f"GTSH car names       : "
        f"{len(gtsh_names)}"
    )

    print(
        f"Existing tech records: "
        f"{len(existing)}"
    )

    print()
    print(
        "READING OFFICIAL CAR PAGES"
    )
    print(
        SUB_SEPARATOR
    )

    database = dict(
        existing
    )

    unresolved = {}

    checked = 0
    resolved = 0
    unresolved_count = 0
    exact_names = 0
    strong_names = 0
    weak_names = 0
    request_error_count = 0

    layout_counts = {
        "FF": 0,
        "FR": 0,
        "MR": 0,
        "RR": 0,
        "4WD": 0,
    }

    total_cars = len(
        gtsh_names
    )

    for index, (
        car_code,
        gtsh_name
    ) in enumerate(
        sorted(
            gtsh_names.items()
        ),
        start=1
    ):

        checked += 1

        result = fetch_official_car(
            session,
            car_code,
            gtsh_name
        )

        record = result[
            "record"
        ]

        diagnostics = result[
            "diagnostics"
        ]

        request_errors = sum(
            1
            for item in diagnostics
            if item.get(
                "status"
            )
            == "REQUEST_ERROR"
        )

        request_error_count += (
            request_errors
        )

        if record:

            name_confidence = (
                name_match_confidence(
                    gtsh_name,
                    record.get(
                        "official_name"
                    )
                )
            )

            record[
                "name_match_confidence"
            ] = name_confidence

            # The car page is directly keyed by the GTSH
            # car code. A weak title/name comparison is logged
            # but does not discard otherwise valid official
            # drivetrain data.

            database[
                str(car_code)
            ] = record

            resolved += 1

            layout = record[
                "layout"
            ]

            if layout in layout_counts:

                layout_counts[
                    layout
                ] += 1

            if name_confidence == "EXACT":

                exact_names += 1

            elif name_confidence == "STRONG":

                strong_names += 1

            elif name_confidence in (
                "WEAK",
                "MEDIUM",
                "UNKNOWN",
            ):

                weak_names += 1

            print(
                f"[{index:03d}/{total_cars:03d}] "
                f"{car_code:4d} | "
                f"{layout:>3} | "
                f"{name_confidence:<6} | "
                f"{gtsh_name}"
            )

        else:

            unresolved_count += 1

            unresolved[
                str(car_code)
            ] = {
                "name":
                    gtsh_name,

                "reason":
                    "No drivetrain extracted from official page.",

                "requests":
                    diagnostics,
            }

            if (
                index <= 15
                or index % 25 == 0
            ):

                status_text = ", ".join(
                    str(
                        item.get(
                            "status"
                        )
                    )
                    for item
                    in diagnostics
                )

                print(
                    f"[{index:03d}/{total_cars:03d}] "
                    f"{car_code:4d} | "
                    f"??? | "
                    f"{gtsh_name} | "
                    f"HTTP {status_text}"
                )

        if index % 25 == 0:

            save_json_file(
                OUTPUT_FILE,
                database
            )

            save_json_file(
                UNRESOLVED_FILE,
                unresolved
            )

        time.sleep(
            REQUEST_DELAY_SECONDS
        )

    # ========================================================
    # REMOVE INVALID TECHNICAL RECORDS
    # ========================================================

    clean_database = {}

    for raw_code, record in database.items():

        if not isinstance(
            record,
            dict
        ):
            continue

        layout = normalize_layout(
            record.get(
                "layout"
            )
        )

        if layout not in VALID_LAYOUTS:
            continue

        record = dict(
            record
        )

        record[
            "layout"
        ] = layout

        record[
            "validated"
        ] = True

        clean_database[
            str(
                int(
                    raw_code
                )
            )
        ] = record

    clean_database = dict(
        sorted(
            clean_database.items(),
            key=lambda item:
                int(
                    item[0]
                )
        )
    )

    unresolved = dict(
        sorted(
            unresolved.items(),
            key=lambda item:
                int(
                    item[0]
                )
        )
    )

    save_json_file(
        OUTPUT_FILE,
        clean_database
    )

    save_json_file(
        UNRESOLVED_FILE,
        unresolved
    )

    # ========================================================
    # KNOWN CURRENT-WEEK SANITY CHECK
    # ========================================================

    sanity_codes = [
        3405,
        3588,
        3600,
    ]

    print()
    print(
        "SANITY CHECK"
    )
    print(
        SUB_SEPARATOR
    )

    for car_code in sanity_codes:

        item = clean_database.get(
            str(
                car_code
            )
        )

        if item:

            print(
                f"{car_code} | "
                f"{item.get('layout')} | "
                f"{item.get('name')}"
            )

        else:

            print(
                f"{car_code} | "
                f"NOT RESOLVED"
            )

    # ========================================================
    # SUMMARY
    # ========================================================

    coverage = (
        resolved
        / checked
        * 100
        if checked
        else 0
    )

    print()
    print(
        SEPARATOR
    )

    print(
        f"GTSH cars checked       : "
        f"{checked}"
    )

    print(
        f"Technical records found : "
        f"{resolved}"
    )

    print(
        f"Unresolved cars         : "
        f"{unresolved_count}"
    )

    print(
        f"Coverage                : "
        f"{coverage:.2f}%"
    )

    print(
        f"HTTP request errors     : "
        f"{request_error_count}"
    )

    print(
        f"Exact name matches      : "
        f"{exact_names}"
    )

    print(
        f"Strong name matches     : "
        f"{strong_names}"
    )

    print(
        f"Other name matches      : "
        f"{weak_names}"
    )

    print(
        f"FF                      : "
        f"{layout_counts['FF']}"
    )

    print(
        f"FR                      : "
        f"{layout_counts['FR']}"
    )

    print(
        f"MR                      : "
        f"{layout_counts['MR']}"
    )

    print(
        f"RR                      : "
        f"{layout_counts['RR']}"
    )

    print(
        f"4WD                     : "
        f"{layout_counts['4WD']}"
    )

    print(
        f"Saved technical DB      : "
        f"{OUTPUT_FILE}"
    )

    print(
        f"Saved unresolved DB     : "
        f"{UNRESOLVED_FILE}"
    )

    print(
        SEPARATOR
    )


if __name__ == "__main__":
    main()