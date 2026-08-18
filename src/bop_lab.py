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

VERSION = "1.1"

DG_EDGE_BOP_URL = "https://www.dg-edge.com/database/bop"

DATA_DIR = Path("data") / "bop_lab"
REPORT_DIR = Path("reports")
RAW_DIR = DATA_DIR / "raw"

REPORT_FILE = REPORT_DIR / "bop_lab.txt"

GROUP = "GR.3"

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


def now_iso():
    return datetime.now().astimezone().isoformat()


def clean_text(value):
    if value is None:
        return ""
    text = str(value).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def version_key(version):
    try:
        return tuple(int(x) for x in str(version).split("."))
    except Exception:
        return (0,)


def fetch_html(session, url, raise_for_status=True):
    response = session.get(url, timeout=REQUEST_TIMEOUT)

    result = {
        "url": response.url,
        "status": response.status_code,
        "html": response.text,
        "bytes": len(response.content),
        "content_type": response.headers.get("Content-Type", ""),
    }

    if raise_for_status:
        response.raise_for_status()

    return result


def build_group_url(group, version):
    group = normalize_group(group)

    if not group:
        raise ValueError(f"Invalid group: {group}")

    return f"{DG_EDGE_BOP_URL}/{group}/{version}"


def extract_versions(html):
    soup = BeautifulSoup(html, "html.parser")
    versions = set()

    for link in soup.find_all("a", href=True):
        href = link.get("href", "")

        match = re.search(
            r"/database/bop/(?:GR\.[1234]|GR\.B)/(\d+\.\d+)",
            href,
            flags=re.IGNORECASE,
        )

        if match:
            versions.add(match.group(1))

    if not versions:
        text = soup.get_text(" ", strip=True)

        for match in re.finditer(
            r"\b(?:Update|Version)\s+(\d+\.\d+)\b",
            text,
            flags=re.IGNORECASE,
        ):
            versions.add(match.group(1))

    return sorted(
        versions,
        key=version_key,
        reverse=True,
    )


def looks_like_valid_bop_page(html, group):
    if not html:
        return False

    soup = BeautifulSoup(html, "html.parser")
    text = clean_text(
        soup.get_text(" ", strip=True)
    ).lower()

    group_text = normalize_group(group).lower()

    signals = [
        "full bop table",
        "max power",
        "max torque",
        "power/weight",
        "weight balance",
    ]

    count = sum(
        1
        for signal in signals
        if signal in text
    )

    return (
        group_text in text
        and count >= 2
    )


def probe_versions(session, group, versions):
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


def detect_speed_controls(html):
    soup = BeautifulSoup(html, "html.parser")
    controls = []

    for tag in soup.find_all(
        ["input", "button", "option", "label", "a"]
    ):
        text = clean_text(
            tag.get_text(" ", strip=True)
        )

        value = clean_text(
            tag.get("value", "")
        )

        name = clean_text(
            tag.get("name", "")
        )

        identifier = clean_text(
            tag.get("id", "")
        )

        combined = (
            f"{text} {value} {name} {identifier}"
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
                    "tag": tag.name,
                    "text": text,
                    "value": value,
                    "name": name,
                    "id": identifier,
                    "type": tag.get("type"),
                }
            )

    return controls


def score_table(table):
    text = clean_text(
        table.get_text(" ", strip=True)
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
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")

    if not tables:
        return None

    scored = sorted(
        (
            (score_table(table), table)
            for table in tables
        ),
        key=lambda item: item[0],
        reverse=True,
    )

    if not scored or scored[0][0] < 10:
        return None

    return scored[0][1]


def extract_rows(table):
    rows = []

    for tr in table.find_all("tr"):
        cells = [
            clean_text(
                cell.get_text(" ", strip=True)
            )
            for cell in tr.find_all(
                ["th", "td"]
            )
        ]

        if cells:
            rows.append(cells)

    return rows


def looks_like_car_name(value):
    text = clean_text(value)

    if not text:
        return False

    lowered = text.lower()

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

    if text in {"Car", "PP", "Î"}:
        return False

    return bool(
        re.search(r"[A-Za-z]", text)
    )


def candidate_car_rows(rows):
    output = []

    for index, row in enumerate(rows):
        if len(row) < 10:
            continue

        first = clean_text(row[0])

        if looks_like_car_name(first):
            output.append(
                {
                    "row_index": index,
                    "car": first,
                    "cells": row,
                }
            )

    return output


def save_raw_html(group, version, html):
    RAW_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    group_safe = (
        group.replace(".", "").lower()
    )

    path = RAW_DIR / (
        f"{group_safe}_{version}.html"
    )

    path.write_text(
        html,
        encoding="utf-8",
    )

    return path


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
    print(f"GT7 BOP LAB V{VERSION}")
    print(SEP)
    print("Experimental pipeline.")
    print(
        "The production Daily Race C agent "
        "is NOT modified."
    )
    print()

    session = requests.Session()
    session.headers.update(HEADERS)

    print("READING DG EDGE BOP INDEX")
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
        index_result["html"]
    )

    print(
        f"Versions detected : "
        f"{', '.join(versions)}"
    )

    if not versions:
        raise RuntimeError(
            "No BoP versions discovered."
        )

    print()
    print("PROBING GR.3 VERSIONS")
    print(SUB)

    selected_version, source, probes = (
        probe_versions(
            session,
            GROUP,
            versions,
        )
    )

    if not selected_version:
        raise RuntimeError(
            "No usable DG EDGE GR.3 "
            "BoP page was found."
        )

    print()
    print("SELECTED BOP PAGE")
    print(SUB)
    print(
        f"Group             : {GROUP}"
    )
    print(
        f"Version           : "
        f"{selected_version}"
    )
    print(
        f"URL               : "
        f"{source['url']}"
    )
    print(
        f"HTTP status       : "
        f"{source['status']}"
    )
    print(
        f"Response bytes    : "
        f"{source['bytes']:,}"
    )

    raw_path = save_raw_html(
        GROUP,
        selected_version,
        source["html"],
    )

    print(
        f"Saved raw HTML    : "
        f"{raw_path}"
    )

    controls = detect_speed_controls(
        source["html"]
    )

    table = find_bop_table(
        source["html"]
    )

    if table is None:
        raise RuntimeError(
            "Could not identify the "
            "Full BoP table."
        )

    rows = extract_rows(table)
    cars = candidate_car_rows(rows)

    print(
        f"Table rows        : {len(rows)}"
    )
    print(
        f"Candidate cars    : {len(cars)}"
    )
    print(
        f"Speed controls    : "
        f"{len(controls)}"
    )

    database = load_database()
    save_database(database)

    stats = database_stats()
    validation = validate_database()

    lines = []

    lines.append(
        "GT7 BOP LAB - STRUCTURE DIAGNOSTIC"
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
        "Selection rule     : "
        "newest working GR.3 page"
    )
    lines.append("")

    lines.append("VERSION PROBES")
    lines.append(SUB)

    for probe in probes:
        lines.append(
            f"{probe['version']:<8} | "
            f"HTTP {probe['status']:<3} | "
            f"{probe['bytes']:>8,} bytes | "
            f"{'VALID' if probe['valid'] else 'UNUSABLE'}"
        )

    lines.append("")
    lines.append("SPEED CONTROLS FOUND")
    lines.append(SUB)
    lines.append(
        f"Controls           : "
        f"{len(controls)}"
    )

    for control in controls[:30]:
        lines.append(str(control))

    lines.append("")
    lines.append("TABLE STRUCTURE")
    lines.append(SUB)
    lines.append(
        f"Rows               : {len(rows)}"
    )
    lines.append(
        f"Candidate cars     : {len(cars)}"
    )

    lines.append("")
    lines.append("FIRST 8 RAW ROWS")
    lines.append(SUB)

    for index, row in enumerate(rows[:8]):
        lines.append(
            f"ROW {index:02d} "
            f"({len(row)} cells)"
        )

        for cell_index, value in enumerate(row):
            lines.append(
                f"  [{cell_index:02d}] {value}"
            )

    lines.append("")
    lines.append("FIRST 5 CAR CANDIDATES")
    lines.append(SUB)

    for candidate in cars[:5]:
        lines.append(
            f"ROW {candidate['row_index']} | "
            f"{candidate['car']} | "
            f"{len(candidate['cells'])} cells"
        )

        for cell_index, value in enumerate(
            candidate["cells"]
        ):
            lines.append(
                f"  [{cell_index:02d}] {value}"
            )

    lines.append("")
    lines.append("IMPORTANT")
    lines.append(SUB)
    lines.append(
        "V1.1 still does NOT insert "
        "BoP car records."
    )
    lines.append(
        "It resolves the newest working "
        "GR.3 version first."
    )
    lines.append(
        "Production Daily Race C remains untouched."
    )
    lines.append(SEP)

    report = "\n".join(lines)

    REPORT_FILE.write_text(
        report,
        encoding="utf-8",
    )

    print()
    print(report)

    print()
    print("DATABASE")
    print(SUB)
    print(
        f"Records            : "
        f"{stats['records']}"
    )
    print(
        f"Validation         : "
        f"{'PASSED' if validation['valid'] else 'FAILED'}"
    )
    print(SEP)


if __name__ == "__main__":
    main()
    