import json
import math
import re
import time
from pathlib import Path
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from bop_database import (
    build_record,
    database_stats,
    load_database,
    normalize_group,
    save_database,
    upsert_record,
    validate_database,
)

# ============================================================
# CONFIG
# ============================================================

VERSION = "1.7"

DG_EDGE_BASE_URL = "https://www.dg-edge.com"
DG_EDGE_BOP_URL = f"{DG_EDGE_BASE_URL}/database/bop"

DATA_DIR = Path("data") / "bop_lab"
REPORT_DIR = Path("reports")
STATE_DIR = DATA_DIR / "raw" / "state"

REPORT_FILE = REPORT_DIR / "bop_lab.txt"
EXTRACTED_FILE = DATA_DIR / "extracted_bop.json"
NUXT_RAW_FILE = STATE_DIR / "09_NUXT_DATA.json"

GROUP = "GR.3"
SPEED_ORDER = ["HIGH", "MID", "LOW"]
MIN_EXPECTED_CARS_PER_CLASS = 40

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

SPECIAL_REFS = {
    -1: None,
    -2: float("nan"),
    -3: float("inf"),
    -4: float("-inf"),
    -5: -0.0,
}


# ============================================================
# BASIC HELPERS
# ============================================================

def now_iso():
    return datetime.now().astimezone().isoformat()


def clean_text(value):
    if value is None:
        return None

    text = re.sub(
        r"\s+",
        " ",
        str(value).replace("\xa0", " "),
    ).strip()

    return text or None


def safe_float(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        try:
            number = float(value)
        except Exception:
            return None

        if math.isnan(number):
            return None

        return number

    text = clean_text(value)

    if not text:
        return None

    text = text.replace(",", "")

    match = re.search(
        r"[-+]?\d+(?:\.\d+)?",
        text,
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


def normalize_speed(value):
    text = clean_text(value)

    if not text:
        return None

    aliases = {
        "HIGH": "HIGH",
        "MID": "MID",
        "MEDIUM": "MID",
        "LOW": "LOW",
    }

    return aliases.get(text.upper())


# ============================================================
# HTTP / VERSION DISCOVERY
# ============================================================

def fetch_text(session, url, raise_for_status=True):
    response = session.get(
        url,
        timeout=REQUEST_TIMEOUT,
    )

    result = {
        "url": response.url,
        "status": response.status_code,
        "text": response.text,
        "bytes": len(response.content),
        "content_type": response.headers.get(
            "Content-Type",
            "",
        ),
    }

    if raise_for_status:
        response.raise_for_status()

    return result


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
        "html.parser",
    )

    versions = set()

    for link in soup.find_all(
        "a",
        href=True,
    ):
        href = link.get(
            "href",
            "",
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
            strip=True,
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


def looks_like_valid_bop_page(html, group):
    if not html:
        return False

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    text = soup.get_text(
        " ",
        strip=True,
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


def probe_versions(session, group, versions):
    probes = []

    for version in versions:
        url = build_group_url(
            group,
            version,
        )

        result = fetch_text(
            session,
            url,
            raise_for_status=False,
        )

        valid = (
            result["status"] == 200
            and looks_like_valid_bop_page(
                result["text"],
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
# NUXT DATA
# ============================================================

def extract_nuxt_data_text(html):
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    tag = soup.find(
        "script",
        id="__NUXT_DATA__",
    )

    if tag is None:
        return None

    if tag.string is not None:
        return tag.string

    return tag.get_text("\n")


def save_nuxt_data(text):
    STATE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    NUXT_RAW_FILE.write_text(
        text,
        encoding="utf-8",
    )


def resolve_ref(raw_state, ref):
    if not isinstance(ref, int):
        return ref

    if ref < 0:
        return SPECIAL_REFS.get(ref)

    if ref >= len(raw_state):
        return None

    return raw_state[ref]


def resolve_scalar(raw_state, ref):
    value = resolve_ref(
        raw_state,
        ref,
    )

    if isinstance(value, (dict, list)):
        return None

    return value


def resolve_car_name(raw_state, car_ref):
    car_node = resolve_ref(
        raw_state,
        car_ref,
    )

    if isinstance(car_node, str):
        return clean_text(car_node)

    if not isinstance(car_node, dict):
        return None

    for key in [
        "fullName",
        "name",
        "alias",
    ]:
        if key not in car_node:
            continue

        value = resolve_scalar(
            raw_state,
            car_node[key],
        )

        text = clean_text(value)

        if text:
            return text

    return None


def find_bop_speed_map(raw_state):
    """
    Locate the structured Nuxt object shaped like:

        {"High": <list ref>, "Low": <list ref>, "Mid": <list ref>}

    This is substantially safer than scanning every dictionary and
    guessing which records belong to which speed class.
    """

    for index, node in enumerate(raw_state):
        if not isinstance(node, dict):
            continue

        keys = set(node.keys())

        if not {
            "High",
            "Low",
            "Mid",
        }.issubset(keys):
            continue

        resolved = {}
        valid = True

        for source_key, speed in [
            ("High", "HIGH"),
            ("Mid", "MID"),
            ("Low", "LOW"),
        ]:
            value = resolve_ref(
                raw_state,
                node[source_key],
            )

            if not isinstance(value, list):
                valid = False
                break

            resolved[speed] = value

        if valid:
            return index, resolved

    return None, None


def decode_record(raw_state, record_ref, expected_speed):
    node = resolve_ref(
        raw_state,
        record_ref,
    )

    if not isinstance(node, dict):
        return None

    car = resolve_car_name(
        raw_state,
        node.get("car"),
    )

    speed = normalize_speed(
        resolve_scalar(
            raw_state,
            node.get("speed"),
        )
    )

    if not speed:
        speed = expected_speed

    if (
        not car
        or speed != expected_speed
    ):
        return None

    decoded = {
        "car": car,
        "speed": speed,
    }

    scalar_keys = [
        "carId",
        "version",
        "PP",
        "powerType",
        "drivetrain",
        "aspiration",
        "displacement",
        "engineModel",
        "ICEmaxPowerHP",
        "HYBmaxPowerHP",
        "maxTorqueNM",
        "weightKG",
        "weightBalanceFront",
        "weightBalanceRear",
        "acc0-400m",
        "acc0-1000m",
        "acc100-150kmh",
        "stabilityLowInd",
        "stabilityLowBehaviour",
        "stabilityHighInd",
        "stabilityHighBehaviour",
        "rotG60kmh",
        "rotG120kmh",
        "rotG240kmh",
    ]

    for key in scalar_keys:
        if key not in node:
            continue

        decoded[key] = resolve_scalar(
            raw_state,
            node[key],
        )

    return decoded


def extract_speed_records(raw_state):
    speed_map_index, speed_lists = find_bop_speed_map(
        raw_state
    )

    if speed_lists is None:
        raise RuntimeError(
            "Could not locate the High/Low/Mid BoP map in __NUXT_DATA__."
        )

    decoded = {
        speed: []
        for speed in SPEED_ORDER
    }

    rejected = {
        speed: 0
        for speed in SPEED_ORDER
    }

    for speed in SPEED_ORDER:
        for record_ref in speed_lists[speed]:
            record = decode_record(
                raw_state,
                record_ref,
                speed,
            )

            if record is None:
                rejected[speed] += 1
                continue

            decoded[speed].append(record)

    return {
        "speed_map_index": speed_map_index,
        "raw_counts": {
            speed: len(speed_lists[speed])
            for speed in SPEED_ORDER
        },
        "decoded": decoded,
        "rejected": rejected,
    }


# ============================================================
# DATABASE RECORD BUILDING
# ============================================================

def choose_power_hp(data):
    ice = safe_float(
        data.get("ICEmaxPowerHP")
    )

    hybrid = safe_float(
        data.get("HYBmaxPowerHP")
    )

    if ice is not None and ice > 0:
        return ice

    if hybrid is not None and hybrid > 0:
        return hybrid

    return None


def format_stability(index_value, behaviour):
    index_text = clean_text(
        index_value
    )

    behaviour_text = clean_text(
        behaviour
    )

    if index_text and behaviour_text:
        return (
            f"{index_text} | "
            f"{behaviour_text}"
        )

    return (
        index_text
        or behaviour_text
    )


def build_database_record(
    data,
    selected_version,
    page_url,
):
    record_version = clean_text(
        data.get("version")
    )

    if (
        not record_version
        or not re.fullmatch(
            r"\d+\.\d+",
            record_version,
        )
    ):
        record_version = selected_version

    front = safe_float(
        data.get("weightBalanceFront")
    )

    rear = safe_float(
        data.get("weightBalanceRear")
    )

    weight_balance = None

    if (
        front is not None
        and rear is not None
    ):
        weight_balance = (
            f"{front:g}:{rear:g}"
        )

    return build_record(
        car=data.get("car"),
        group=GROUP,
        bop_version=record_version,
        speed_class=data.get("speed"),
        power_hp=choose_power_hp(data),
        torque_nm=safe_float(
            data.get("maxTorqueNM")
        ),
        weight_kg=safe_float(
            data.get("weightKG")
        ),
        pp=safe_float(
            data.get("PP")
        ),
        weight_balance=weight_balance,
        drivetrain=clean_text(
            data.get("drivetrain")
        ),
        aspiration=clean_text(
            data.get("aspiration")
        ),
        displacement=clean_text(
            data.get("displacement")
        ),
        engine_model=clean_text(
            data.get("engineModel")
        ),
        powertrain=clean_text(
            data.get("powerType")
        ),
        acceleration_0_400=safe_float(
            data.get("acc0-400m")
        ),
        acceleration_0_1000=safe_float(
            data.get("acc0-1000m")
        ),
        acceleration_100_150=safe_float(
            data.get("acc100-150kmh")
        ),
        rotational_g_60=safe_float(
            data.get("rotG60kmh")
        ),
        rotational_g_120=safe_float(
            data.get("rotG120kmh")
        ),
        rotational_g_240=safe_float(
            data.get("rotG240kmh")
        ),
        stability_low_speed=format_stability(
            data.get("stabilityLowInd"),
            data.get("stabilityLowBehaviour"),
        ),
        stability_high_speed=format_stability(
            data.get("stabilityHighInd"),
            data.get("stabilityHighBehaviour"),
        ),
        source="DG EDGE __NUXT_DATA__",
        source_url=page_url,
        source_confidence="STRUCTURED_STATE_VALIDATED",
    )


# ============================================================
# VALIDATION / COMPARISON
# ============================================================

def validate_extraction(records_by_speed, raw_counts, rejected):
    errors = []

    decoded_counts = {
        speed: len(records_by_speed[speed])
        for speed in SPEED_ORDER
    }

    for speed in SPEED_ORDER:
        if raw_counts[speed] < MIN_EXPECTED_CARS_PER_CLASS:
            errors.append(
                f"{speed}: suspiciously small raw class: "
                f"{raw_counts[speed]} cars."
            )

        if rejected[speed] != 0:
            errors.append(
                f"{speed}: {rejected[speed]} records could not be decoded."
            )

        if decoded_counts[speed] != raw_counts[speed]:
            errors.append(
                f"{speed}: raw count {raw_counts[speed]} != "
                f"decoded count {decoded_counts[speed]}."
            )

    if len(set(raw_counts.values())) != 1:
        errors.append(
            f"Raw High/Mid/Low counts differ: {raw_counts}."
        )

    car_sets = {
        speed: {
            record["car"]
            for record in records_by_speed[speed]
        }
        for speed in SPEED_ORDER
    }

    reference = car_sets["HIGH"]

    for speed in ["MID", "LOW"]:
        if car_sets[speed] != reference:
            missing = sorted(
                reference - car_sets[speed]
            )
            extra = sorted(
                car_sets[speed] - reference
            )

            errors.append(
                f"Car set differs for {speed}. "
                f"Missing={missing}; Extra={extra}"
            )

    for speed in SPEED_ORDER:
        names = [
            record["car"]
            for record in records_by_speed[speed]
        ]

        if len(names) != len(set(names)):
            errors.append(
                f"{speed}: duplicate car names detected."
            )

        for record in records_by_speed[speed]:
            if choose_power_hp(record) is None:
                errors.append(
                    f"Missing power: {record['car']} / {speed}"
                )

            if safe_float(record.get("weightKG")) is None:
                errors.append(
                    f"Missing weight: {record['car']} / {speed}"
                )

    return {
        "valid": not errors,
        "errors": errors,
        "raw_counts": raw_counts,
        "decoded_counts": decoded_counts,
        "rejected": rejected,
        "unique_cars": len(reference),
    }


def record_signature(record):
    return (
        record.get("power_hp"),
        record.get("weight_kg"),
        record.get("pp"),
    )


def compare_speed_classes(records):
    lookup = {
        (
            record["car"],
            record["speed_class"],
        ): record
        for record in records
    }

    cars = sorted(
        {
            record["car"]
            for record in records
        }
    )

    changed = []
    unchanged = []

    for car in cars:
        signatures = {}

        for speed in SPEED_ORDER:
            record = lookup.get(
                (
                    car,
                    speed,
                )
            )

            if record:
                signatures[speed] = record_signature(
                    record
                )

        if len(signatures) != 3:
            continue

        item = {
            "car": car,
            "HIGH": signatures["HIGH"],
            "MID": signatures["MID"],
            "LOW": signatures["LOW"],
            "distinct_signatures": len(
                set(signatures.values())
            ),
        }

        if item["distinct_signatures"] > 1:
            changed.append(item)
        else:
            unchanged.append(item)

    return {
        "changed": changed,
        "unchanged": unchanged,
        "changed_count": len(changed),
        "unchanged_count": len(unchanged),
    }


# ============================================================
# SAVE / DATABASE WRITE
# ============================================================

def save_extracted_data(
    selected_version,
    page_url,
    extraction_meta,
    records,
    validation,
    comparison,
):
    payload = {
        "generated_at": now_iso(),
        "lab_version": VERSION,
        "group": GROUP,
        "selected_version": selected_version,
        "source_url": page_url,
        "speed_map_index": extraction_meta["speed_map_index"],
        "validation": validation,
        "speed_comparison": comparison,
        "records": records,
    }

    EXTRACTED_FILE.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def write_database(records):
    database = load_database()

    status_counts = {}

    for record in records:
        result = upsert_record(
            database,
            record,
        )

        status = str(
            result.get("status")
            or "UNKNOWN"
        )

        status_counts[status] = (
            status_counts.get(status, 0)
            + 1
        )

    save_database(database)

    return {
        "status_counts": status_counts,
        "total_written": len(records),
    }


def format_signature(signature):
    power, weight, pp = signature

    power_text = (
        f"{power:g}"
        if power is not None
        else "N/A"
    )

    weight_text = (
        f"{weight:g}"
        if weight is not None
        else "N/A"
    )

    pp_text = (
        f"{pp:g}"
        if pp is not None
        else "N/A"
    )

    return (
        f"{power_text} HP / "
        f"{weight_text} kg / "
        f"PP {pp_text}"
    )


# ============================================================
# REPORT
# ============================================================

def build_report(
    selected_version,
    probes,
    raw_state_size,
    extraction_meta,
    extraction_validation,
    comparison,
    write_result,
    db_stats,
    db_validation,
    elapsed_seconds,
):
    lines = []

    lines.append(
        "GT7 BOP LAB V1.7 - DIRECT NUXT BOP EXTRACTION"
    )
    lines.append(SEP)
    lines.append(
        f"Generated           : {now_iso()}"
    )
    lines.append(
        f"Group               : {GROUP}"
    )
    lines.append(
        f"Selected version    : {selected_version}"
    )
    lines.append(
        "Production modified : NO"
    )
    lines.append(
        f"Elapsed             : {elapsed_seconds:.2f}s"
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
    lines.append("NUXT STRUCTURED EXTRACTION")
    lines.append(SUB)
    lines.append(
        f"Flat state entries  : {raw_state_size:,}"
    )
    lines.append(
        f"Speed map index     : {extraction_meta['speed_map_index']}"
    )

    for speed in SPEED_ORDER:
        lines.append(
            f"{speed:<19}: raw "
            f"{extraction_validation['raw_counts'][speed]} | "
            f"decoded {extraction_validation['decoded_counts'][speed]} | "
            f"rejected {extraction_validation['rejected'][speed]}"
        )

    lines.append(
        f"Unique cars         : "
        f"{extraction_validation['unique_cars']}"
    )
    lines.append(
        f"Extraction valid    : "
        f"{'YES' if extraction_validation['valid'] else 'NO'}"
    )

    if extraction_validation["errors"]:
        lines.append("")
        lines.append("EXTRACTION ERRORS")
        lines.append(SUB)

        for error in extraction_validation["errors"]:
            lines.append(
                f"- {error}"
            )

    lines.append("")
    lines.append("HIGH / MID / LOW COMPARISON")
    lines.append(SUB)
    lines.append(
        f"Cars changing BoP   : {comparison['changed_count']}"
    )
    lines.append(
        f"Cars unchanged      : {comparison['unchanged_count']}"
    )

    lines.append("")
    lines.append("FIRST 12 CARS WITH DIFFERENT SPEED-CLASS BOP")
    lines.append(SUB)

    for item in comparison["changed"][:12]:
        lines.append(item["car"])
        lines.append(
            "  HIGH : "
            + format_signature(item["HIGH"])
        )
        lines.append(
            "  MID  : "
            + format_signature(item["MID"])
        )
        lines.append(
            "  LOW  : "
            + format_signature(item["LOW"])
        )

    lines.append("")
    lines.append("DATABASE WRITE")
    lines.append(SUB)

    if write_result:
        lines.append(
            f"Written this run    : {write_result['total_written']}"
        )
        lines.append(
            f"Write statuses      : {write_result['status_counts']}"
        )
    else:
        lines.append(
            "Write skipped       : extraction validation failed"
        )

    lines.append(
        f"Database records    : {db_stats['records']}"
    )
    lines.append(
        f"Database cars       : {db_stats['cars']}"
    )
    lines.append(
        f"Database speeds     : "
        f"{', '.join(db_stats['speed_classes'])}"
    )
    lines.append(
        f"Database validation : "
        f"{'PASSED' if db_validation['valid'] else 'FAILED'}"
    )

    lines.append("")
    lines.append("RESULT")
    lines.append(SUB)

    if (
        extraction_validation["valid"]
        and write_result
        and db_validation["valid"]
    ):
        lines.append(
            "SUCCESS: DG EDGE High / Mid / Low BoP records "
            "were extracted directly from __NUXT_DATA__."
        )
        lines.append(
            "No browser radio-button simulation was required."
        )
    else:
        lines.append(
            "FAILED: extraction/database validation was not accepted."
        )

    lines.append(SEP)

    return "\n".join(lines)


# ============================================================
# MAIN
# ============================================================

def main():
    started = time.perf_counter()

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )
    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )
    STATE_DIR.mkdir(
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
        "Production Daily Race C remains untouched."
    )
    print()

    session = requests.Session()
    session.headers.update(
        HEADERS
    )

    print(
        "READING DG EDGE BOP INDEX"
    )
    print(SUB)

    index_result = fetch_text(
        session,
        DG_EDGE_BOP_URL,
    )

    print(
        f"HTTP status        : {index_result['status']}"
    )
    print(
        f"Response bytes     : {index_result['bytes']:,}"
    )

    versions = extract_versions(
        index_result["text"]
    )

    print(
        f"Versions detected  : {', '.join(versions)}"
    )

    if not versions:
        raise RuntimeError(
            "No BoP versions discovered."
        )

    print()
    print(
        "PROBING GR.3 VERSIONS"
    )
    print(SUB)

    selected_version, source, probes = probe_versions(
        session,
        GROUP,
        versions,
    )

    if not selected_version:
        raise RuntimeError(
            "No usable DG EDGE GR.3 BoP page was found."
        )

    page_url = build_group_url(
        GROUP,
        selected_version,
    )

    print()
    print(
        "SELECTED BOP PAGE"
    )
    print(SUB)
    print(
        f"Version            : {selected_version}"
    )
    print(
        f"URL                : {page_url}"
    )

    nuxt_text = extract_nuxt_data_text(
        source["text"]
    )

    if not nuxt_text:
        raise RuntimeError(
            "__NUXT_DATA__ script not found."
        )

    save_nuxt_data(
        nuxt_text
    )

    try:
        raw_state = json.loads(
            nuxt_text
        )
    except Exception as error:
        raise RuntimeError(
            "Could not parse __NUXT_DATA__ JSON: "
            f"{error}"
        ) from error

    print()
    print(
        "EXTRACTING DIRECT HIGH / MID / LOW LISTS"
    )
    print(SUB)
    print(
        f"Flat state entries : {len(raw_state):,}"
    )

    extraction_meta = extract_speed_records(
        raw_state
    )

    print(
        f"Speed map index    : {extraction_meta['speed_map_index']}"
    )

    for speed in SPEED_ORDER:
        print(
            f"{speed:<18}: raw "
            f"{extraction_meta['raw_counts'][speed]} | "
            f"decoded {len(extraction_meta['decoded'][speed])} | "
            f"rejected {extraction_meta['rejected'][speed]}"
        )

    extraction_validation = validate_extraction(
        extraction_meta["decoded"],
        extraction_meta["raw_counts"],
        extraction_meta["rejected"],
    )

    decoded_flat = []

    for speed in SPEED_ORDER:
        decoded_flat.extend(
            extraction_meta["decoded"][speed]
        )

    database_records = [
        build_database_record(
            data,
            selected_version,
            page_url,
        )
        for data in decoded_flat
    ]

    comparison = compare_speed_classes(
        database_records
    )

    print(
        f"Unique cars        : {extraction_validation['unique_cars']}"
    )
    print(
        f"Changing BoP       : {comparison['changed_count']}"
    )
    print(
        f"Unchanged BoP      : {comparison['unchanged_count']}"
    )
    print(
        f"Extraction valid   : "
        f"{'YES' if extraction_validation['valid'] else 'NO'}"
    )

    save_extracted_data(
        selected_version,
        page_url,
        extraction_meta,
        database_records,
        extraction_validation,
        comparison,
    )

    write_result = None

    if extraction_validation["valid"]:
        write_result = write_database(
            database_records
        )

    db_stats = database_stats()
    db_validation = validate_database()

    elapsed_seconds = (
        time.perf_counter()
        - started
    )

    report = build_report(
        selected_version=selected_version,
        probes=probes,
        raw_state_size=len(raw_state),
        extraction_meta=extraction_meta,
        extraction_validation=extraction_validation,
        comparison=comparison,
        write_result=write_result,
        db_stats=db_stats,
        db_validation=db_validation,
        elapsed_seconds=elapsed_seconds,
    )

    REPORT_FILE.write_text(
        report,
        encoding="utf-8",
    )

    print()
    print(report)
    print()
    print(
        f"Saved report       : {REPORT_FILE}"
    )
    print(
        f"Saved extraction   : {EXTRACTED_FILE}"
    )
    print(
        f"Saved raw Nuxt     : {NUXT_RAW_FILE}"
    )
    print(SEP)

    if not extraction_validation["valid"]:
        raise RuntimeError(
            "BoP extraction failed strict validation. "
            "Database was not modified."
        )

    if not db_validation["valid"]:
        raise RuntimeError(
            "BoP database failed validation."
        )


if __name__ == "__main__":
    main()
