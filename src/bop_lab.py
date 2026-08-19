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

VERSION = "1.5"

DG_EDGE_BASE_URL = "https://www.dg-edge.com"
DG_EDGE_BOP_URL = f"{DG_EDGE_BASE_URL}/database/bop"

DATA_DIR = Path("data") / "bop_lab"
REPORT_DIR = Path("reports")
RAW_DIR = DATA_DIR / "raw"
STATE_DIR = RAW_DIR / "state"

REPORT_FILE = REPORT_DIR / "bop_lab.txt"
EXTRACTED_FILE = DATA_DIR / "extracted_bop.json"
NUXT_RAW_FILE = STATE_DIR / "09_NUXT_DATA.json"

GROUP = "GR.3"

EXPECTED_SPEED_CLASSES = {"HIGH", "MID", "LOW"}
EXPECTED_CARS_PER_CLASS = 48
EXPECTED_TOTAL_RECORDS = EXPECTED_CARS_PER_CLASS * len(EXPECTED_SPEED_CLASSES)

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
        return None
    text = re.sub(r"\s+", " ", str(value).replace("\xa0", " ")).strip()
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
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except Exception:
        return None


def version_key(version):
    try:
        return tuple(int(part) for part in str(version).split("."))
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


def fetch_text(session, url, raise_for_status=True):
    response = session.get(url, timeout=REQUEST_TIMEOUT)
    result = {
        "url": response.url,
        "status": response.status_code,
        "text": response.text,
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
    return sorted(versions, key=version_key, reverse=True)


def looks_like_valid_bop_page(html, group):
    if not html:
        return False
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True).lower()
    group_text = (normalize_group(group) or "").lower()
    signals = [
        "max power",
        "max torque",
        "power/weight",
        "weight balance",
        "drivetrain",
    ]
    signal_count = sum(1 for signal in signals if signal in text)
    return group_text in text and signal_count >= 3


def probe_versions(session, group, versions):
    probes = []
    for version in versions:
        url = build_group_url(group, version)
        result = fetch_text(session, url, raise_for_status=False)
        valid = (
            result["status"] == 200
            and looks_like_valid_bop_page(result["text"], group)
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
        time.sleep(REQUEST_DELAY_SECONDS)
    return None, None, probes


def extract_nuxt_data_text(html):
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("script", id="__NUXT_DATA__")
    if tag is None:
        return None
    if tag.string is not None:
        return tag.string
    return tag.get_text("\n")


def save_nuxt_data(text):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    NUXT_RAW_FILE.write_text(text, encoding="utf-8")


SPECIAL_REFS = {
    -1: None,
    -2: float("nan"),
    -3: float("inf"),
    -4: float("-inf"),
    -5: -0.0,
}


class NuxtFlatDecoder:
    def __init__(self, raw):
        if not isinstance(raw, list):
            raise RuntimeError("__NUXT_DATA__ root is not a list.")
        self.raw = raw
        self.cache = {}
        self.resolving = set()

    def decode_ref(self, ref):
        if isinstance(ref, int):
            if ref < 0:
                return SPECIAL_REFS.get(ref)
            if ref >= len(self.raw):
                return ref
            return self.decode_index(ref)
        return ref

    def decode_index(self, index):
        if index in self.cache:
            return self.cache[index]
        if index in self.resolving:
            return f"<circular:{index}>"
        self.resolving.add(index)
        node = self.raw[index]

        if isinstance(node, dict):
            decoded = {}
            self.cache[index] = decoded
            for key, value_ref in node.items():
                decoded[key] = self.decode_ref(value_ref)
        elif isinstance(node, list):
            decoded = []
            self.cache[index] = decoded
            for value_ref in node:
                decoded.append(self.decode_ref(value_ref))
        else:
            decoded = node
            self.cache[index] = decoded

        self.resolving.discard(index)
        return decoded


REQUIRED_RAW_KEYS = {
    "car",
    "carId",
    "version",
    "speed",
    "PP",
    "ICEmaxPowerHP",
    "maxTorqueNM",
    "weightKG",
    "drivetrain",
}


def is_raw_bop_record(node):
    return (
        isinstance(node, dict)
        and REQUIRED_RAW_KEYS.issubset(set(node.keys()))
    )


def decode_bop_candidates(raw_state):
    decoder = NuxtFlatDecoder(raw_state)
    candidates = []
    for index, node in enumerate(raw_state):
        if not is_raw_bop_record(node):
            continue
        decoded = decoder.decode_index(index)
        if not isinstance(decoded, dict):
            continue
        speed = normalize_speed(decoded.get("speed"))
        car = clean_text(decoded.get("car"))
        if speed not in EXPECTED_SPEED_CLASSES or not car:
            continue
        candidates.append({"raw_index": index, "data": decoded})
    return candidates


def choose_power_hp(data):
    ice = safe_float(data.get("ICEmaxPowerHP"))
    hybrid = safe_float(data.get("HYBmaxPowerHP"))
    if ice is not None and ice > 0:
        return ice
    if hybrid is not None and hybrid > 0:
        return hybrid
    return None


def format_stability(index_value, behaviour):
    index_text = clean_text(index_value)
    behaviour_text = clean_text(behaviour)
    if index_text and behaviour_text:
        return f"{index_text} | {behaviour_text}"
    return index_text or behaviour_text


def build_database_record(data, selected_version, page_url):
    car = clean_text(data.get("car"))
    speed = normalize_speed(data.get("speed"))

    record_version = clean_text(data.get("version"))
    if (
        not record_version
        or not re.fullmatch(r"\d+\.\d+", record_version)
    ):
        record_version = selected_version

    front = safe_float(data.get("weightBalanceFront"))
    rear = safe_float(data.get("weightBalanceRear"))

    weight_balance = None
    if front is not None and rear is not None:
        weight_balance = f"{front:g}:{rear:g}"

    return build_record(
        car=car,
        group=GROUP,
        bop_version=record_version,
        speed_class=speed,
        power_hp=choose_power_hp(data),
        torque_nm=safe_float(data.get("maxTorqueNM")),
        weight_kg=safe_float(data.get("weightKG")),
        pp=safe_float(data.get("PP")),
        weight_balance=weight_balance,
        drivetrain=clean_text(data.get("drivetrain")),
        aspiration=clean_text(data.get("aspiration")),
        displacement=clean_text(data.get("displacement")),
        engine_model=clean_text(data.get("engineModel")),
        powertrain=clean_text(data.get("powerType")),
        acceleration_0_400=safe_float(data.get("acc0-400m")),
        acceleration_0_1000=safe_float(data.get("acc0-1000m")),
        acceleration_100_150=safe_float(data.get("acc100-150kmh")),
        rotational_g_60=safe_float(data.get("rotG60kmh")),
        rotational_g_120=safe_float(data.get("rotG120kmh")),
        rotational_g_240=safe_float(data.get("rotG240kmh")),
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


def validate_extraction(records):
    errors = []
    by_speed = {speed: [] for speed in EXPECTED_SPEED_CLASSES}
    seen = set()

    for record in records:
        speed = record.get("speed_class")
        car = record.get("car")

        if speed not in by_speed:
            errors.append(f"Unexpected speed class: {speed}")
            continue

        key = (car, speed)

        if key in seen:
            errors.append(f"Duplicate record: {car} / {speed}")

        seen.add(key)
        by_speed[speed].append(record)

        if record.get("power_hp") is None:
            errors.append(f"Missing power: {car} / {speed}")

        if record.get("weight_kg") is None:
            errors.append(f"Missing weight: {car} / {speed}")

    counts = {
        speed: len(items)
        for speed, items in by_speed.items()
    }

    if len(records) != EXPECTED_TOTAL_RECORDS:
        errors.append(
            f"Expected {EXPECTED_TOTAL_RECORDS} records, "
            f"found {len(records)}."
        )

    for speed in sorted(EXPECTED_SPEED_CLASSES):
        if counts[speed] != EXPECTED_CARS_PER_CLASS:
            errors.append(
                f"{speed}: expected {EXPECTED_CARS_PER_CLASS} cars, "
                f"found {counts[speed]}."
            )

    car_sets = {
        speed: {record["car"] for record in items}
        for speed, items in by_speed.items()
    }

    reference = car_sets.get("HIGH", set())

    for speed in ["MID", "LOW"]:
        if car_sets.get(speed, set()) != reference:
            missing = sorted(reference - car_sets.get(speed, set()))
            extra = sorted(car_sets.get(speed, set()) - reference)
            errors.append(
                f"Car set differs for {speed}. "
                f"Missing={missing}; Extra={extra}"
            )

    return {
        "valid": not errors,
        "errors": errors,
        "counts": counts,
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
        (record["car"], record["speed_class"]): record
        for record in records
    }

    cars = sorted({record["car"] for record in records})

    changed = []
    unchanged = []

    for car in cars:
        signatures = {
            speed: record_signature(lookup[(car, speed)])
            for speed in EXPECTED_SPEED_CLASSES
            if (car, speed) in lookup
        }

        if len(signatures) != 3:
            continue

        item = {
            "car": car,
            "HIGH": signatures["HIGH"],
            "MID": signatures["MID"],
            "LOW": signatures["LOW"],
            "distinct_signatures": len(set(signatures.values())),
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


def save_extracted_data(
    selected_version,
    page_url,
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
    added = 0
    updated = 0

    for record in records:
        result = upsert_record(database, record)
        if result["status"] == "ADDED":
            added += 1
        else:
            updated += 1

    save_database(database)

    return {
        "added": added,
        "updated": updated,
        "total_written": len(records),
    }


def format_signature(signature):
    power, weight, pp = signature
    return f"{power:g} HP / {weight:g} kg / PP {pp:g}"


def build_report(
    selected_version,
    probes,
    raw_candidate_count,
    records,
    extraction_validation,
    comparison,
    write_result,
    db_stats,
    db_validation,
):
    lines = []

    lines.append("GT7 BOP LAB V1.5 - STRUCTURED BOP EXTRACTION")
    lines.append(SEP)
    lines.append(f"Generated           : {now_iso()}")
    lines.append(f"Group               : {GROUP}")
    lines.append(f"Selected version    : {selected_version}")
    lines.append("Production modified : NO")

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
    lines.append(f"Raw BoP objects     : {raw_candidate_count}")
    lines.append(f"Decoded records     : {len(records)}")

    for speed in ["HIGH", "MID", "LOW"]:
        lines.append(
            f"{speed:<19}: "
            f"{extraction_validation['counts'].get(speed, 0)} cars"
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
        for error in extraction_validation["errors"]:
            lines.append(f"- {error}")

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
            "  HIGH : " + format_signature(item["HIGH"])
        )
        lines.append(
            "  MID  : " + format_signature(item["MID"])
        )
        lines.append(
            "  LOW  : " + format_signature(item["LOW"])
        )

    lines.append("")
    lines.append("DATABASE WRITE")
    lines.append(SUB)

    if write_result:
        lines.append(f"Added               : {write_result['added']}")
        lines.append(f"Updated             : {write_result['updated']}")
        lines.append(
            f"Written this run    : {write_result['total_written']}"
        )
    else:
        lines.append(
            "Write skipped       : extraction validation failed"
        )

    lines.append(f"Database records    : {db_stats['records']}")
    lines.append(f"Database cars       : {db_stats['cars']}")
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
            "SUCCESS: DG EDGE __NUXT_DATA__ directly contains "
            "the three GR.3 BoP speed classes."
        )
        lines.append(
            "HIGH / MID / LOW have been decoded without "
            "simulating the website radio buttons."
        )
        lines.append(
            "The experimental BoP database is now populated."
        )
    else:
        lines.append(
            "FAILED: database was not accepted as validated."
        )

    lines.append(SEP)
    return "\n".join(lines)


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    print()
    print(f"GT7 BOP LAB V{VERSION}")
    print(SEP)
    print("Experimental pipeline.")
    print("Production Daily Race C remains untouched.")
    print()

    session = requests.Session()
    session.headers.update(HEADERS)

    print("READING DG EDGE BOP INDEX")
    print(SUB)

    index_result = fetch_text(
        session,
        DG_EDGE_BOP_URL,
    )

    print(f"HTTP status        : {index_result['status']}")
    print(f"Response bytes     : {index_result['bytes']:,}")

    versions = extract_versions(index_result["text"])

    print(f"Versions detected  : {', '.join(versions)}")

    if not versions:
        raise RuntimeError("No BoP versions discovered.")

    print()
    print("PROBING GR.3 VERSIONS")
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
    print("SELECTED BOP PAGE")
    print(SUB)
    print(f"Version            : {selected_version}")
    print(f"URL                : {page_url}")

    nuxt_text = extract_nuxt_data_text(source["text"])

    if not nuxt_text:
        raise RuntimeError("__NUXT_DATA__ script not found.")

    save_nuxt_data(nuxt_text)

    try:
        raw_state = json.loads(nuxt_text)
    except Exception as error:
        raise RuntimeError(
            "Could not parse __NUXT_DATA__ JSON: "
            f"{error}"
        ) from error

    print()
    print("DECODING NUXT FLAT STATE")
    print(SUB)
    print(f"Flat state entries : {len(raw_state):,}")

    candidates = decode_bop_candidates(raw_state)

    print(f"BoP candidates     : {len(candidates)}")

    records = [
        build_database_record(
            candidate["data"],
            selected_version,
            page_url,
        )
        for candidate in candidates
    ]

    extraction_validation = validate_extraction(records)
    comparison = compare_speed_classes(records)

    print(f"Decoded records    : {len(records)}")

    for speed in ["HIGH", "MID", "LOW"]:
        print(
            f"{speed:<18}: "
            f"{extraction_validation['counts'].get(speed, 0)}"
        )

    print(
        f"Unique cars        : "
        f"{extraction_validation['unique_cars']}"
    )
    print(
        f"Changing BoP       : "
        f"{comparison['changed_count']}"
    )
    print(
        f"Unchanged BoP      : "
        f"{comparison['unchanged_count']}"
    )
    print(
        f"Extraction valid   : "
        f"{'YES' if extraction_validation['valid'] else 'NO'}"
    )

    save_extracted_data(
        selected_version,
        page_url,
        records,
        extraction_validation,
        comparison,
    )

    write_result = None

    if extraction_validation["valid"]:
        write_result = write_database(records)

    db_stats = database_stats()
    db_validation = validate_database()

    report = build_report(
        selected_version=selected_version,
        probes=probes,
        raw_candidate_count=len(candidates),
        records=records,
        extraction_validation=extraction_validation,
        comparison=comparison,
        write_result=write_result,
        db_stats=db_stats,
        db_validation=db_validation,
    )

    REPORT_FILE.write_text(report, encoding="utf-8")

    print()
    print(report)
    print()
    print(f"Saved report       : {REPORT_FILE}")
    print(f"Saved extraction   : {EXTRACTED_FILE}")
    print(f"Saved raw Nuxt     : {NUXT_RAW_FILE}")
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
