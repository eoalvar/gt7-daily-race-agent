import json
import re
import time

from pathlib import Path
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from bop_database import (
    load_database,
    save_database,
    build_record,
    upsert_record,
    database_stats,
    validate_database,
    normalize_group,
    normalize_speed_class,
)


# ============================================================
# CONFIG
# ============================================================

VERSION = "1.0"

DG_EDGE_BASE_URL = (
    "https://www.dg-edge.com"
)

DG_EDGE_BOP_URL = (
    DG_EDGE_BASE_URL
    + "/database/bop"
)

DATA_DIR = (
    Path("data")
    / "bop_lab"
)

REPORT_DIR = Path(
    "reports"
)

RAW_DIR = (
    DATA_DIR
    / "raw"
)

REPORT_FILE = (
    REPORT_DIR
    / "bop_lab.txt"
)

LATEST_CONTEXT_FILE = (
    DATA_DIR
    / "latest_collection.json"
)


# ============================================================
# INITIAL SCOPE
#
# Start with Gr.3 because the current Daily Race C is Gr.3.
# The code is already designed to accept other groups later.
# ============================================================

GROUPS_TO_COLLECT = [
    "GR.3",
]


# ============================================================
# SPEED CLASSES
#
# We deliberately collect all three.
# We are NOT yet deciding which one Yas Marina uses.
# ============================================================

SPEED_CLASSES_TO_COLLECT = [
    "HIGH",
    "MID",
    "LOW",
]


REQUEST_TIMEOUT = 60

REQUEST_DELAY_SECONDS = 0.20


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/151.0.0.0 "
        "Safari/537.36"
    ),

    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),

    "Accept-Language":
        "en-US,en;q=0.9",

    "Cache-Control":
        "no-cache",
}


SEPARATOR = "=" * 100
SUB_SEPARATOR = "-" * 100


# ============================================================
# BASIC HELPERS
# ============================================================

def now_iso():

    return (
        datetime.now()
        .astimezone()
        .isoformat()
    )


def clean_text(
    value
):

    if value is None:
        return ""

    value = str(
        value
    )

    value = value.replace(
        "\xa0",
        " "
    )

    value = re.sub(
        r"\s+",
        " ",
        value
    )

    return value.strip()


def safe_float(
    value
):

    if value is None:
        return None

    if isinstance(
        value,
        (int, float)
    ):
        return float(
            value
        )

    value = clean_text(
        value
    )

    if not value:
        return None

    value = (
        value
        .replace(",", "")
        .replace("−", "-")
    )

    match = re.search(
        r"[-+]?\d+(?:\.\d+)?",
        value
    )

    if not match:
        return None

    try:

        return float(
            match.group(0)
        )

    except Exception:

        return None


def normalize_version(
    value
):

    value = clean_text(
        value
    )

    value = re.sub(
        r"^Update\s+",
        "",
        value,
        flags=re.IGNORECASE
    )

    value = re.sub(
        r"^Version\s+",
        "",
        value,
        flags=re.IGNORECASE
    )

    return value.strip()


# ============================================================
# URL HELPERS
# ============================================================

def group_url_fragment(
    group
):

    group = normalize_group(
        group
    )

    if not group:

        raise ValueError(
            "Invalid group."
        )

    return group


def build_group_url(
    group,
    version=None
):

    fragment = (
        group_url_fragment(
            group
        )
    )

    url = (
        f"{DG_EDGE_BOP_URL}/"
        f"{fragment}"
    )

    if version:

        url += (
            f"/{version}"
        )

    return url


# ============================================================
# FETCH
# ============================================================

def fetch_html(
    session,
    url
):

    response = session.get(
        url,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    return {
        "url":
            response.url,

        "status":
            response.status_code,

        "html":
            response.text,

        "bytes":
            len(
                response.content
            ),

        "content_type":
            response.headers.get(
                "Content-Type",
                ""
            )
    }


# ============================================================
# SAVE RAW HTML
#
# Useful while developing the parser.
# These files do not affect production.
# ============================================================

def save_raw_html(
    group,
    version,
    speed_class,
    html
):

    RAW_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    group_safe = (
        group
        .replace(".", "")
        .lower()
    )

    filename = (
        f"{group_safe}_"
        f"{version}_"
        f"{speed_class.lower()}.html"
    )

    path = (
        RAW_DIR
        / filename
    )

    path.write_text(
        html,
        encoding="utf-8"
    )

    return path


# ============================================================
# VERSION DISCOVERY
# ============================================================

def extract_versions_from_bop_index(
    html
):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    versions = set()

    # --------------------------------------------------------
    # Method 1:
    # links such as /database/bop/GR.3/1.67
    # --------------------------------------------------------

    for link in soup.find_all(
        "a",
        href=True
    ):

        href = link.get(
            "href",
            ""
        )

        match = re.search(
            r"/database/bop/"
            r"(?:GR\.[1234]|GR\.B)"
            r"/(\d+\.\d+)",
            href,
            flags=re.IGNORECASE
        )

        if match:

            versions.add(
                match.group(1)
            )

    # --------------------------------------------------------
    # Method 2:
    # visible strings "Update 1.67"
    # --------------------------------------------------------

    text = soup.get_text(
        " ",
        strip=True
    )

    for match in re.finditer(
        r"\bUpdate\s+"
        r"(\d+\.\d+)\b",
        text,
        flags=re.IGNORECASE
    ):

        versions.add(
            match.group(1)
        )

    def version_key(
        version
    ):

        try:

            major, minor = (
                version.split(
                    ".",
                    1
                )
            )

            return (
                int(major),
                int(minor)
            )

        except Exception:

            return (
                0,
                0
            )

    return sorted(
        versions,
        key=version_key
    )


def latest_version(
    versions
):

    if not versions:
        return None

    return versions[
        -1
    ]


# ============================================================
# TABLE DISCOVERY
# ============================================================

def table_headers(
    table
):

    headers = []

    for cell in table.find_all(
        "th"
    ):

        text = clean_text(
            cell.get_text(
                " ",
                strip=True
            )
        )

        if text:

            headers.append(
                text
            )

    return headers


def score_bop_table(
    table
):

    text = clean_text(
        table.get_text(
            " ",
            strip=True
        )
    ).lower()

    score = 0

    signals = [
        (
            "max power",
            5
        ),
        (
            "max torque",
            5
        ),
        (
            "weight",
            5
        ),
        (
            "power/weight",
            4
        ),
        (
            "weight balance",
            4
        ),
        (
            "drivetrain",
            4
        ),
        (
            "aspiration",
            3
        ),
        (
            "engine model",
            3
        ),
        (
            "acc. 0-400",
            2
        ),
        (
            "rot. g",
            2
        ),
    ]

    for signal, weight in signals:

        if signal in text:

            score += weight

    return score


def find_full_bop_table(
    html
):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    tables = soup.find_all(
        "table"
    )

    if not tables:

        return None

    scored = [
        (
            score_bop_table(
                table
            ),
            table
        )
        for table in tables
    ]

    scored.sort(
        key=lambda item:
            item[
                0
            ],
        reverse=True
    )

    if not scored:

        return None

    score, table = (
        scored[
            0
        ]
    )

    if score < 10:

        return None

    return table


# ============================================================
# SPEED CLASS INPUT DETECTION
#
# DG EDGE exposes High / Low / Mid controls.
# We do not assume yet how their client-side mechanism works.
# This function records what the page exposes for diagnostics.
# ============================================================

def detect_speed_controls(
    html
):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    controls = []

    for input_tag in soup.find_all(
        [
            "input",
            "button",
            "option",
            "label",
            "a",
        ]
    ):

        text = clean_text(
            input_tag.get_text(
                " ",
                strip=True
            )
        )

        value = clean_text(
            input_tag.get(
                "value",
                ""
            )
        )

        name = clean_text(
            input_tag.get(
                "name",
                ""
            )
        )

        identifier = clean_text(
            input_tag.get(
                "id",
                ""
            )
        )

        combined = (
            f"{text} "
            f"{value} "
            f"{name} "
            f"{identifier}"
        ).lower()

        if any(
            token in combined
            for token in [
                "high",
                "mid",
                "medium",
                "low",
            ]
        ):

            controls.append(
                {
                    "tag":
                        input_tag.name,

                    "text":
                        text,

                    "value":
                        value,

                    "name":
                        name,

                    "id":
                        identifier,

                    "type":
                        input_tag.get(
                            "type"
                        )
                }
            )

    return controls


# ============================================================
# FLATTEN TABLE
#
# DG EDGE table has multi-row headers with Prev/Curr/Delta.
# At this stage we keep every textual cell so we can
# empirically validate the exact layout before relying on it.
# ============================================================

def extract_raw_table_rows(
    table
):

    rows = []

    if table is None:
        return rows

    for tr in table.find_all(
        "tr"
    ):

        cells = []

        for cell in tr.find_all(
            [
                "th",
                "td",
            ]
        ):

            value = clean_text(
                cell.get_text(
                    " ",
                    strip=True
                )
            )

            cells.append(
                value
            )

        if cells:

            rows.append(
                cells
            )

    return rows


# ============================================================
# FIND CAR ROWS
#
# We deliberately make this conservative.
# The first version of the Lab should not insert data
# unless we can identify rows reliably.
# ============================================================

def looks_like_car_name(
    value
):

    value = clean_text(
        value
    )

    if not value:
        return False

    lowered = value.lower()

    exclusions = [
        "prev.",
        "curr.",
        "max power",
        "max torque",
        "weight",
        "power/weight",
        "acc.",
        "stability",
        "rot. g",
        "powertrain",
        "aspiration",
        "drivetrain",
        "engine model",
        "full bop table",
        "bop ranking",
    ]

    if any(
        term in lowered
        for term in exclusions
    ):

        return False

    if value in {
        "Car",
        "PP",
        "Δ",
    }:

        return False

    # Car names contain letters.
    if not re.search(
        r"[A-Za-z]",
        value
    ):

        return False

    return True


def candidate_car_rows(
    raw_rows
):

    candidates = []

    for index, row in enumerate(
        raw_rows
    ):

        if len(row) < 10:
            continue

        first = clean_text(
            row[
                0
            ]
        )

        if not looks_like_car_name(
            first
        ):

            continue

        candidates.append(
            {
                "row_index":
                    index,

                "car":
                    first,

                "cells":
                    row,
            }
        )

    return candidates


# ============================================================
# RAW STRUCTURE REPORT
#
# We first want to discover whether requests receives
# a usable server-side table and how its columns are ordered.
# ============================================================

def build_structure_report(
    group,
    version,
    source,
    controls,
    raw_rows,
    car_rows
):

    lines = []

    lines.append(
        "GT7 BOP LAB - STRUCTURE DIAGNOSTIC"
    )

    lines.append(
        SEPARATOR
    )

    lines.append(
        f"Generated       : "
        f"{now_iso()}"
    )

    lines.append(
        f"Group           : "
        f"{group}"
    )

    lines.append(
        f"BoP version     : "
        f"{version}"
    )

    lines.append(
        f"Source URL      : "
        f"{source['url']}"
    )

    lines.append(
        f"HTTP status     : "
        f"{source['status']}"
    )

    lines.append(
        f"Response bytes  : "
        f"{source['bytes']:,}"
    )

    lines.append(
        f"Content-Type    : "
        f"{source['content_type']}"
    )

    lines.append("")

    lines.append(
        "SPEED CONTROLS FOUND"
    )

    lines.append(
        SUB_SEPARATOR
    )

    lines.append(
        f"Controls        : "
        f"{len(controls)}"
    )

    for control in controls[
        :30
    ]:

        lines.append(
            f"{control}"
        )

    lines.append("")

    lines.append(
        "TABLE STRUCTURE"
    )

    lines.append(
        SUB_SEPARATOR
    )

    lines.append(
        f"Rows            : "
        f"{len(raw_rows)}"
    )

    lines.append(
        f"Candidate cars  : "
        f"{len(car_rows)}"
    )

    lines.append("")

    lines.append(
        "FIRST 8 RAW ROWS"
    )

    lines.append(
        SUB_SEPARATOR
    )

    for index, row in enumerate(
        raw_rows[
            :8
        ]
    ):

        lines.append(
            f"ROW {index:02d} "
            f"({len(row)} cells)"
        )

        for cell_index, value in enumerate(
            row
        ):

            lines.append(
                f"  [{cell_index:02d}] "
                f"{value}"
            )

    lines.append("")

    lines.append(
        "FIRST 5 CAR CANDIDATES"
    )

    lines.append(
        SUB_SEPARATOR
    )

    for candidate in car_rows[
        :5
    ]:

        lines.append(
            f"ROW "
            f"{candidate['row_index']} | "
            f"{candidate['car']} | "
            f"{len(candidate['cells'])} cells"
        )

        for cell_index, value in enumerate(
            candidate[
                "cells"
            ]
        ):

            lines.append(
                f"  [{cell_index:02d}] "
                f"{value}"
            )

    lines.append("")

    lines.append(
        "IMPORTANT"
    )

    lines.append(
        SUB_SEPARATOR
    )

    lines.append(
        "No BoP records are inserted yet by V1."
    )

    lines.append(
        "This run verifies the exact DG EDGE HTML/table "
        "structure received by GitHub Actions."
    )

    lines.append(
        "After this structure is confirmed, V2 will map "
        "the Curr. values for High/Mid/Low into bop_database.json."
    )

    lines.append(
        SEPARATOR
    )

    return "\n".join(
        lines
    )


# ============================================================
# SAVE COLLECTION CONTEXT
# ============================================================

def save_collection_context(
    context
):

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    LATEST_CONTEXT_FILE.write_text(
        json.dumps(
            context,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    RAW_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    print()

    print(
        f"GT7 BOP LAB V{VERSION}"
    )

    print(
        SEPARATOR
    )

    print(
        "Experimental pipeline."
    )

    print(
        "The production Daily Race C agent "
        "is NOT modified."
    )

    print()

    session = requests.Session()

    session.headers.update(
        HEADERS
    )

    # ========================================================
    # DISCOVER CURRENT AVAILABLE BOP VERSIONS
    # ========================================================

    print(
        "READING DG EDGE BOP INDEX"
    )

    print(
        SUB_SEPARATOR
    )

    index_response = fetch_html(
        session,
        DG_EDGE_BOP_URL
    )

    versions = (
        extract_versions_from_bop_index(
            index_response[
                "html"
            ]
        )
    )

    current_version = (
        latest_version(
            versions
        )
    )

    print(
        f"HTTP status      : "
        f"{index_response['status']}"
    )

    print(
        f"Response bytes   : "
        f"{index_response['bytes']:,}"
    )

    print(
        f"Versions found   : "
        f"{len(versions)}"
    )

    print(
        f"Versions         : "
        f"{', '.join(versions)}"
    )

    print(
        f"Latest detected  : "
        f"{current_version}"
    )

    if not current_version:

        raise RuntimeError(
            "Could not determine the latest "
            "DG EDGE BoP version."
        )

    # ========================================================
    # INITIAL LAB COLLECTION
    #
    # One group only for the first structural test.
    # ========================================================

    group = (
        GROUPS_TO_COLLECT[
            0
        ]
    )

    url = build_group_url(
        group,
        current_version
    )

    time.sleep(
        REQUEST_DELAY_SECONDS
    )

    print()

    print(
        "READING CURRENT BOP TABLE"
    )

    print(
        SUB_SEPARATOR
    )

    print(
        f"Group            : "
        f"{group}"
    )

    print(
        f"Version          : "
        f"{current_version}"
    )

    print(
        f"URL              : "
        f"{url}"
    )

    source = fetch_html(
        session,
        url
    )

    print(
        f"HTTP status      : "
        f"{source['status']}"
    )

    print(
        f"Response bytes   : "
        f"{source['bytes']:,}"
    )

    raw_path = save_raw_html(
        group,
        current_version,
        "DEFAULT",
        source[
            "html"
        ]
    )

    print(
        f"Saved raw HTML   : "
        f"{raw_path}"
    )

    # ========================================================
    # INSPECT SPEED CONTROL MECHANISM
    # ========================================================

    controls = detect_speed_controls(
        source[
            "html"
        ]
    )

    # ========================================================
    # INSPECT TABLE
    # ========================================================

    table = find_full_bop_table(
        source[
            "html"
        ]
    )

    if table is None:

        raise RuntimeError(
            "Could not find the Full BoP table "
            "in the DG EDGE HTML."
        )

    raw_rows = extract_raw_table_rows(
        table
    )

    car_rows = candidate_car_rows(
        raw_rows
    )

    print(
        f"Table rows       : "
        f"{len(raw_rows)}"
    )

    print(
        f"Candidate cars   : "
        f"{len(car_rows)}"
    )

    print(
        f"Speed controls   : "
        f"{len(controls)}"
    )

    # ========================================================
    # DATABASE IS ONLY INITIALIZED
    #
    # V1 intentionally does not guess table column positions.
    # ========================================================

    database = load_database()

    save_database(
        database
    )

    db_stats = database_stats()

    validation = validate_database()

    # ========================================================
    # REPORT
    # ========================================================

    report = build_structure_report(
        group=group,
        version=current_version,
        source=source,
        controls=controls,
        raw_rows=raw_rows,
        car_rows=car_rows
    )

    REPORT_FILE.write_text(
        report,
        encoding="utf-8"
    )

    # ========================================================
    # SAVE CONTEXT
    # ========================================================

    context = {
        "generated_at":
            now_iso(),

        "lab_version":
            VERSION,

        "source":
            "DG EDGE",

        "source_url":
            source[
                "url"
            ],

        "group":
            group,

        "versions_available":
            versions,

        "latest_version":
            current_version,

        "http_status":
            source[
                "status"
            ],

        "response_bytes":
            source[
                "bytes"
            ],

        "table_rows":
            len(
                raw_rows
            ),

        "candidate_car_rows":
            len(
                car_rows
            ),

        "speed_controls_found":
            controls,

        "database_records":
            db_stats[
                "records"
            ],

        "database_validation":
            validation,

        "production_pipeline_modified":
            False,
    }

    save_collection_context(
        context
    )

    # ========================================================
    # OUTPUT
    # ========================================================

    print()

    print(
        report
    )

    print()

    print(
        "FILES CREATED"
    )

    print(
        SUB_SEPARATOR
    )

    print(
        f"Report           : "
        f"{REPORT_FILE}"
    )

    print(
        f"Context          : "
        f"{LATEST_CONTEXT_FILE}"
    )

    print(
        f"BoP database     : "
        f"{db_stats['database_file']}"
    )

    print(
        f"Database records : "
        f"{db_stats['records']}"
    )

    print(
        f"DB validation    : "
        f"{'PASSED' if validation['valid'] else 'FAILED'}"
    )

    print(
        SEPARATOR
    )


if __name__ == "__main__":
    main()