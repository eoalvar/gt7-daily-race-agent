import re
import time
from pathlib import Path
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from bop_database import (
    load_database,
    save_database,
    database_stats,
    validate_database,
    normalize_group,
)

# ============================================================
# CONFIG
# ============================================================

VERSION = "1.2"

DG_EDGE_BOP_URL = "https://www.dg-edge.com/database/bop"

DATA_DIR = Path("data") / "bop_lab"
REPORT_DIR = Path("reports")
RAW_DIR = DATA_DIR / "raw"

REPORT_FILE = REPORT_DIR / "bop_lab.txt"

GROUP = "GR.3"

SPEED_CLASSES = {
    "HIGH": "High",
    "LOW": "Low",
    "MID": "Mid",
}

REQUEST_TIMEOUT = 60
REQUEST_DELAY_SECONDS = 0.20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}

SEP = "=" * 100
SUB = "-" * 100


# ============================================================
# BASIC HELPERS
# ============================================================

def now_iso():
    return datetime.now().astimezone().isoformat()


def clean_text(value):
    if value is None:
        return ""

    text = str(value).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def safe_float(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    text = clean_text(value)

    if not text or text in {"-", "N", "U"}:
        return None

    text = text.replace(",", "")

    match = re.search(
        r"[-+]?\d+(?:\.\d+)?",
        text
    )

    if not match:
        return None

    try:
        return float(match.group(0))
    except Exception:
        return None


def version_key(version):
    try:
        return tuple(
            int(part)
            for part in str(version).split(".")
        )
    except Exception:
        return (0,)


# ============================================================
# HTTP
# ============================================================

def fetch_html(
    session,
    url,
    params=None,
    raise_for_status=True,
):
    response = session.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT,
    )

    result = {
        "url": response.url,
        "status": response.status_code,
        "html": response.text,
        "bytes": len(response.content),
        "content_type": response.headers.get(
            "Content-Type",
            ""
        ),
    }

    if raise_for_status:
        response.raise_for_status()

    return result


# ============================================================
# VERSION DISCOVERY
# ============================================================

def build_group_url(group, version):
    group = normalize_group(group)

    if not group:
        raise ValueError(
            f"Invalid group: {group}"
        )

    return (
        f"{DG_EDGE_BOP_URL}/"
        f"{group}/"
        f"{version}"
    )


def extract_versions(html):
    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    versions = set()

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
            flags=re.IGNORECASE,
        )

        if match:
            versions.add(
                match.group(1)
            )

    if not versions:
        text = soup.get_text(
            " ",
            strip=True
        )

        for match in re.finditer(
            r"\b(?:Update|Version)\s+"
            r"(\d+\.\d+)\b",
            text,
            flags=re.IGNORECASE,
        ):
            versions.add(
                match.group(1)
            )

    return sorted(
        versions,
        key=version_key,
        reverse=True,
    )


def looks_like_valid_bop_page(
    html,
    group,
):
    if not html:
        return False

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    text = clean_text(
        soup.get_text(
            " ",
            strip=True
        )
    ).lower()

    group_text = (
        normalize_group(group)
        or ""
    ).lower()

    signals = [
        "max power",
        "max torque",
        "power/weight",
        "weight balance",
        "drivetrain",
    ]

    signal_count = sum(
        1
        for signal in signals
        if signal in text
    )

    return (
        group_text in text
        and signal_count >= 3
    )


def probe_versions(
    session,
    group,
    versions,
):
    probes = []

    for version in versions:
        url = build_group_url(
            group,
            version
        )

        result = fetch_html(
            session,
            url,
            raise_for_status=False,
        )

        valid = (
            result["status"] == 200
            and looks_like_valid_bop_page(
                result["html"],
                group,
            )
        )

        probes.append(
            {
                "version": version,
                "url": url,
                "status": result["status"],
                "bytes": result["bytes"],
                "valid": valid,
            }
        )

        print(
            f"Probe {group} {version:<6}: "
            f"HTTP {result['status']} | "
            f"{result['bytes']:,} bytes | "
            f"{'VALID' if valid else 'UNUSABLE'}"
        )

        if valid:
            return version, result, probes

        time.sleep(
            REQUEST_DELAY_SECONDS
        )

    return None, None, probes


# ============================================================
# SPEED CONTROLS
# ============================================================

def detect_speed_controls(html):
    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    controls = []

    for input_tag in soup.find_all(
        "input",
        attrs={
            "name": "speed"
        }
    ):
        controls.append(
            {
                "value": clean_text(
                    input_tag.get(
                        "value",
                        ""
                    )
                ),
                "id": clean_text(
                    input_tag.get(
                        "id",
                        ""
                    )
                ),
                "checked": (
                    input_tag.has_attr(
                        "checked"
                    )
                ),
            }
        )

    return controls


def selected_speed_from_html(html):
    controls = detect_speed_controls(
        html
    )

    for control in controls:
        if control["checked"]:
            return (
                control["value"]
                .strip()
                .upper()
            )

    return None


# ============================================================
# TABLE DISCOVERY
# ============================================================

def score_table(table):
    text = clean_text(
        table.get_text(
            " ",
            strip=True
        )
    ).lower()

    signals = [
        ("max power", 5),
        ("max torque", 5),
        ("weight", 5),
        ("power/weight", 4),
        ("weight balance", 4),
        ("drivetrain", 4),
        ("aspiration", 3),
        ("engine model", 3),
        ("acc. 0-400", 2),
        ("rot. g", 2),
    ]

    return sum(
        weight
        for signal, weight in signals
        if signal in text
    )


def find_bop_table(html):
    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    tables = soup.find_all(
        "table"
    )

    if not tables:
        return None

    scored = sorted(
        (
            (
                score_table(table),
                table,
            )
            for table in tables
        ),
        key=lambda item: item[0],
        reverse=True,
    )

    if (
        not scored
        or scored[0][0] < 10
    ):
        return None

    return scored[0][1]


def extract_rows(table):
    rows = []

    if table is None:
        return rows

    for tr in table.find_all(
        "tr"
    ):
        cells = [
            clean_text(
                cell.get_text(
                    " ",
                    strip=True
                )
            )
            for cell in tr.find_all(
                [
                    "th",
                    "td",
                ]
            )
        ]

        if cells:
            rows.append(
                cells
            )

    return rows


# ============================================================
# CAR PARSER
#
# V1.1 discovery:
# [00] blank
# [01] car name
# [03] current PP
# [06] current power HP
# [09] current torque Nm
# [12] current weight KG
# [15] current HP/T
# [18] current KG/HP
# [21] current weight balance
# [23] current 0-400
# [26] current 0-1000
# [29] current 100-150
# [32] current low-speed stability
# [35] current high-speed stability
# [37] current Rot G 60
# [40] current Rot G 120
# [42] current Rot G 240
# [50] powertrain
# [51] aspiration
# [52] drivetrain
# [53] displacement
# [54] engine model
# ============================================================

def looks_like_car_name(value):
    text = clean_text(
        value
    )

    if not text:
        return False

    lowered = text.lower()

    exclusions = [
        "car",
        "prev.",
        "curr.",
        "max power",
        "max torque",
        "weight",
        "power/weight",
        "weight balance",
        "stability",
        "rot. g",
        "powertrain",
        "aspiration",
        "drivetrain",
        "engine model",
    ]

    if any(
        lowered == term
        or term in lowered
        for term in exclusions
    ):
        return False

    return bool(
        re.search(
            r"[A-Za-z]",
            text
        )
    )


def parse_current_car_row(row):
    if len(row) < 55:
        return None

    car = clean_text(
        row[1]
    )

    if not looks_like_car_name(
        car
    ):
        return None

    return {
        "car": car,
        "pp": safe_float(row[3]),
        "power_hp": safe_float(row[6]),
        "torque_nm": safe_float(row[9]),
        "weight_kg": safe_float(row[12]),
        "power_weight_hp_t": safe_float(row[15]),
        "weight_power_kg_hp": safe_float(row[18]),
        "weight_balance": clean_text(row[21]),
        "acceleration_0_400": safe_float(row[23]),
        "acceleration_0_1000": safe_float(row[26]),
        "acceleration_100_150": safe_float(row[29]),
        "stability_low": clean_text(row[32]),
        "stability_high": clean_text(row[35]),
        "rotational_g_60": safe_float(row[37]),
        "rotational_g_120": safe_float(row[40]),
        "rotational_g_240": safe_float(row[42]),
        "powertrain": clean_text(row[50]),
        "aspiration": clean_text(row[51]),
        "drivetrain": clean_text(row[52]),
        "displacement": clean_text(row[53]),
        "engine_model": clean_text(row[54]),
    }


def parse_current_cars(rows):
    cars = []

    for row in rows:
        parsed = parse_current_car_row(
            row
        )

        if parsed:
            cars.append(
                parsed
            )

    return cars


def build_signature(cars):
    return [
        (
            car["car"],
            car["pp"],
            car["power_hp"],
            car["weight_kg"],
        )
        for car in cars[:5]
    ]


# ============================================================
# RAW HTML
# ============================================================

def save_raw_html(
    group,
    version,
    speed,
    html,
):
    RAW_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    group_safe = (
        group
        .replace(".", "")
        .lower()
    )

    path = (
        RAW_DIR
        / (
            f"{group_safe}_"
            f"{version}_"
            f"{speed.lower()}.html"
        )
    )

    path.write_text(
        html,
        encoding="utf-8",
    )

    return path


# ============================================================
# HIGH / LOW / MID TEST
# ============================================================

def collect_speed_variant(
    session,
    base_url,
    version,
    speed_key,
    speed_value,
):
    result = fetch_html(
        session,
        base_url,
        params={
            "speed": speed_value
        },
        raise_for_status=False,
    )

    selected_speed = None
    rows = []
    cars = []
    raw_path = None

    if result["status"] == 200:
        selected_speed = (
            selected_speed_from_html(
                result["html"]
            )
        )

        table = find_bop_table(
            result["html"]
        )

        if table is not None:
            rows = extract_rows(
                table
            )

            cars = parse_current_cars(
                rows
            )

        raw_path = save_raw_html(
            GROUP,
            version,
            speed_key,
            result["html"],
        )

    return {
        "requested_speed": speed_key,
        "requested_value": speed_value,
        "selected_speed": selected_speed,
        "status": result["status"],
        "url": result["url"],
        "bytes": result["bytes"],
        "rows": len(rows),
        "cars": cars,
        "car_count": len(cars),
        "signature": build_signature(cars),
        "raw_path": (
            str(raw_path)
            if raw_path
            else None
        ),
    }


# ============================================================
# MAIN
# ============================================================

def main():
    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    RAW_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    print()
    print(
        f"GT7 BOP LAB V{VERSION}"
    )
    print(SEP)
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
    # INDEX
    # ========================================================

    print(
        "READING DG EDGE BOP INDEX"
    )
    print(SUB)

    index_result = fetch_html(
        session,
        DG_EDGE_BOP_URL,
    )

    print(
        f"HTTP status       : "
        f"{index_result['status']}"
    )
    print(
        f"Response bytes    : "
        f"{index_result['bytes']:,}"
    )

    versions = extract_versions(
        index_result[
            "html"
        ]
    )

    print(
        f"Versions detected : "
        f"{', '.join(versions)}"
    )

    if not versions:
        raise RuntimeError(
            "No BoP versions discovered."
        )

    # ========================================================
    # VERSION PROBE
    # ========================================================

    print()
    print(
        "PROBING GR.3 VERSIONS"
    )
    print(SUB)

    (
        selected_version,
        source,
        probes,
    ) = probe_versions(
        session,
        GROUP,
        versions,
    )

    if not selected_version:
        raise RuntimeError(
            "No usable DG EDGE GR.3 "
            "BoP page was found."
        )

    base_url = build_group_url(
        GROUP,
        selected_version
    )

    print()
    print(
        "SELECTED BOP VERSION"
    )
    print(SUB)
    print(
        f"Group             : {GROUP}"
    )
    print(
        f"Version           : "
        f"{selected_version}"
    )
    print(
        f"Base URL          : "
        f"{base_url}"
    )

    # ========================================================
    # SPEED VARIANTS
    # ========================================================

    variants = []

    print()
    print(
        "TESTING SPEED VARIANTS"
    )
    print(SUB)

    for (
        speed_key,
        speed_value,
    ) in SPEED_CLASSES.items():

        variant = collect_speed_variant(
            session=session,
            base_url=base_url,
            version=selected_version,
            speed_key=speed_key,
            speed_value=speed_value,
        )

        variants.append(
            variant
        )

        print(
            f"{speed_key:<4} | "
            f"HTTP {variant['status']} | "
            f"selected={variant['selected_speed']} | "
            f"rows={variant['rows']} | "
            f"cars={variant['car_count']} | "
            f"{variant['url']}"
        )

        time.sleep(
            REQUEST_DELAY_SECONDS
        )

    # ========================================================
    # DATABASE STILL READ-ONLY
    # ========================================================

    database = load_database()
    save_database(
        database
    )

    stats = database_stats()
    validation = validate_database()

    # ========================================================
    # REPORT
    # ========================================================

    lines = []

    lines.append(
        "GT7 BOP LAB V1.2 - SPEED CLASS DIAGNOSTIC"
    )
    lines.append(SEP)
    lines.append(
        f"Generated          : {now_iso()}"
    )
    lines.append(
        f"Group              : {GROUP}"
    )
    lines.append(
        f"Selected version   : "
        f"{selected_version}"
    )
    lines.append(
        "Production modified: NO"
    )

    lines.append("")
    lines.append(
        "VERSION PROBES"
    )
    lines.append(SUB)

    for probe in probes:
        lines.append(
            f"{probe['version']:<8} | "
            f"HTTP {probe['status']:<3} | "
            f"{probe['bytes']:>8,} bytes | "
            f"{'VALID' if probe['valid'] else 'UNUSABLE'}"
        )

    lines.append("")
    lines.append(
        "SPEED VARIANT TEST"
    )
    lines.append(SUB)

    for variant in variants:
        lines.append(
            f"{variant['requested_speed']:<4} | "
            f"HTTP {variant['status']:<3} | "
            f"selected={variant['selected_speed']} | "
            f"rows={variant['rows']} | "
            f"cars={variant['car_count']}"
        )
        lines.append(
            f"URL: {variant['url']}"
        )
        lines.append(
            f"Raw: {variant['raw_path']}"
        )
        lines.append(
            "Signature:"
        )

        for item in variant[
            "signature"
        ]:
            lines.append(
                f"  {item[0]} | "
                f"PP {item[1]} | "
                f"HP {item[2]} | "
                f"KG {item[3]}"
            )

        lines.append("")

    lines.append(
        "FIRST 5 PARSED CARS BY SPEED"
    )
    lines.append(SUB)

    for variant in variants:
        lines.append(
            f"[{variant['requested_speed']}]"
        )

        for car in variant[
            "cars"
        ][:5]:
            lines.append(
                f"{car['car']} | "
                f"PP {car['pp']} | "
                f"HP {car['power_hp']} | "
                f"Torque {car['torque_nm']} | "
                f"KG {car['weight_kg']} | "
                f"Balance {car['weight_balance']} | "
                f"{car['drivetrain']} | "
                f"{car['aspiration']}"
            )

        lines.append("")

    signatures = [
        tuple(
            variant[
                "signature"
            ]
        )
        for variant in variants
    ]

    unique_signatures = len(
        set(
            signatures
        )
    )

    lines.append(
        "SPEED-SWITCH VALIDATION"
    )
    lines.append(SUB)
    lines.append(
        f"Distinct signatures: "
        f"{unique_signatures} / "
        f"{len(variants)}"
    )

    if unique_signatures == 3:
        lines.append(
            "Result             : PASSED - "
            "HIGH/LOW/MID returned distinct tables."
        )
    elif unique_signatures > 1:
        lines.append(
            "Result             : PARTIAL - "
            "some speed variants differ."
        )
    else:
        lines.append(
            "Result             : FAILED/INCONCLUSIVE - "
            "all speed requests returned the same table."
        )

    lines.append("")
    lines.append(
        "DATABASE"
    )
    lines.append(SUB)
    lines.append(
        f"Records            : "
        f"{stats['records']}"
    )
    lines.append(
        f"Validation         : "
        f"{'PASSED' if validation['valid'] else 'FAILED'}"
    )

    lines.append("")
    lines.append(
        "IMPORTANT"
    )
    lines.append(SUB)
    lines.append(
        "V1.2 intentionally does not write "
        "BoP car records yet."
    )
    lines.append(
        "Once HIGH/LOW/MID switching is proven, "
        "V1.3 will persist all three tables."
    )
    lines.append(SEP)

    report = "\n".join(
        lines
    )

    REPORT_FILE.write_text(
        report,
        encoding="utf-8",
    )

    print()
    print(report)
    print()
    print(
        f"Saved report      : "
        f"{REPORT_FILE}"
    )
    print(SEP)


if __name__ == "__main__":
    main()