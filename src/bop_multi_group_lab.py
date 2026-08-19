import json
import time
from pathlib import Path
from datetime import datetime

import requests

import bop_lab
from bop_database import load_database, save_database, upsert_record, validate_database

VERSION = "2.0"
GROUPS = ["GR.1", "GR.2", "GR.3", "GR.4", "GR.B"]
SPEEDS = ["HIGH", "MID", "LOW"]

DATA_DIR = Path("data") / "bop_lab"
REPORT_DIR = Path("reports")
REPORT_FILE = REPORT_DIR / "bop_multi_group_lab.txt"
SUMMARY_FILE = DATA_DIR / "bop_multi_group_summary.json"

SEP = "=" * 100
SUB = "-" * 100


def now_iso():
    return datetime.now().astimezone().isoformat()


def validate_group(records_by_speed, raw_counts, rejected):
    errors = []
    decoded_counts = {speed: len(records_by_speed.get(speed, [])) for speed in SPEEDS}

    for speed in SPEEDS:
        raw = raw_counts.get(speed, 0)
        decoded = decoded_counts.get(speed, 0)
        if raw <= 0:
            errors.append(f"{speed}: no records found")
        if rejected.get(speed, 0):
            errors.append(f"{speed}: {rejected[speed]} records rejected")
        if raw != decoded:
            errors.append(f"{speed}: raw {raw} != decoded {decoded}")

    nonzero = [raw_counts.get(speed, 0) for speed in SPEEDS if raw_counts.get(speed, 0) > 0]
    if nonzero and len(set(nonzero)) != 1:
        errors.append(f"High/Mid/Low counts differ: {raw_counts}")

    car_sets = {
        speed: {record.get("car") for record in records_by_speed.get(speed, []) if record.get("car")}
        for speed in SPEEDS
    }
    if car_sets["HIGH"]:
        for speed in ["MID", "LOW"]:
            if car_sets[speed] != car_sets["HIGH"]:
                errors.append(f"Car set differs for {speed}")

    return {
        "valid": not errors,
        "errors": errors,
        "raw_counts": raw_counts,
        "decoded_counts": decoded_counts,
        "rejected": rejected,
        "unique_cars": len(car_sets["HIGH"]),
    }


def process_group(session, versions, group):
    print()
    print(f"PROCESSING {group}")
    print(SUB)

    selected_version, source, probes = bop_lab.probe_versions(session, group, versions)
    if not selected_version:
        return {
            "group": group,
            "status": "NO_USABLE_PAGE",
            "version": None,
            "probes": probes,
            "records": 0,
        }

    nuxt_text = bop_lab.extract_nuxt_data_text(source["text"])
    if not nuxt_text:
        return {
            "group": group,
            "status": "NO_NUXT_DATA",
            "version": selected_version,
            "probes": probes,
            "records": 0,
        }

    raw_state = json.loads(nuxt_text)
    extraction = bop_lab.extract_speed_records(raw_state)
    validation = validate_group(
        extraction["decoded"],
        extraction["raw_counts"],
        extraction["rejected"],
    )

    old_group = bop_lab.GROUP
    bop_lab.GROUP = group
    try:
        records = []
        page_url = bop_lab.build_group_url(group, selected_version)
        for speed in SPEEDS:
            for raw_record in extraction["decoded"][speed]:
                records.append(
                    bop_lab.build_database_record(
                        raw_record,
                        selected_version,
                        page_url,
                    )
                )
    finally:
        bop_lab.GROUP = old_group

    group_file = DATA_DIR / f"extracted_bop_{group.replace('.', '').lower()}.json"
    group_file.write_text(
        json.dumps(
            {
                "generated_at": now_iso(),
                "lab_version": VERSION,
                "group": group,
                "selected_version": selected_version,
                "source_url": page_url,
                "validation": validation,
                "records": records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Version             : {selected_version}")
    for speed in SPEEDS:
        print(f"{speed:<19}: {validation['decoded_counts'][speed]} cars")
    print(f"Unique cars         : {validation['unique_cars']}")
    print(f"Validation          : {'PASSED' if validation['valid'] else 'FAILED'}")

    return {
        "group": group,
        "status": "VALID" if validation["valid"] else "INVALID",
        "version": selected_version,
        "probes": probes,
        "validation": validation,
        "records": records,
        "records_count": len(records),
        "output_file": str(group_file),
    }


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    print()
    print(f"GT7 MULTI-GROUP BOP LAB V{VERSION}")
    print(SEP)
    print("Groups: " + ", ".join(GROUPS))
    print("Production Daily Race C remains untouched.")

    session = requests.Session()
    session.headers.update(bop_lab.HEADERS)

    index = bop_lab.fetch_text(session, bop_lab.DG_EDGE_BOP_URL)
    versions = bop_lab.extract_versions(index["text"])
    if not versions:
        raise RuntimeError("No DG EDGE BoP versions discovered.")

    database = load_database()
    results = []
    total_written = 0

    for group in GROUPS:
        try:
            result = process_group(session, versions, group)
        except Exception as exc:
            result = {
                "group": group,
                "status": "ERROR",
                "error": f"{type(exc).__name__}: {exc}",
                "records_count": 0,
            }
        results.append(result)

        if result.get("status") == "VALID":
            for record in result.get("records", []):
                upsert_record(database, record)
                total_written += 1

        time.sleep(bop_lab.REQUEST_DELAY_SECONDS)

    save_database(database)
    db_validation = validate_database()

    serializable_results = []
    for result in results:
        clean = dict(result)
        clean.pop("records", None)
        serializable_results.append(clean)

    summary = {
        "generated_at": now_iso(),
        "version": VERSION,
        "groups_requested": GROUPS,
        "groups": serializable_results,
        "records_written_this_run": total_written,
        "database_validation": db_validation,
    }
    SUMMARY_FILE.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"GT7 MULTI-GROUP BOP LAB V{VERSION}",
        SEP,
        f"Generated            : {summary['generated_at']}",
        f"Groups requested     : {', '.join(GROUPS)}",
        f"Records written      : {total_written}",
        f"Database validation  : {'PASSED' if db_validation.get('valid') else 'FAILED'}",
        "",
        "GROUP RESULTS",
        SUB,
    ]

    for result in results:
        group = result["group"]
        status = result.get("status")
        version = result.get("version") or "N/A"
        validation = result.get("validation") or {}
        counts = validation.get("decoded_counts") or {}
        lines.append(
            f"{group:<5} | {status:<14} | version {version:<6} | "
            f"HIGH {counts.get('HIGH', 0):>3} | MID {counts.get('MID', 0):>3} | "
            f"LOW {counts.get('LOW', 0):>3} | unique {validation.get('unique_cars', 0):>3}"
        )
        if result.get("error"):
            lines.append(f"      ERROR: {result['error']}")
        for error in validation.get("errors", []):
            lines.append(f"      validation: {error}")

    lines += [
        "",
        "POLICY",
        SUB,
        "Each group is validated independently.",
        "A failed group is not written, while valid groups are preserved.",
        "The shared database keeps group + BoP version + speed class as separate dimensions.",
        SEP,
    ]

    report = "\n".join(lines)
    REPORT_FILE.write_text(report, encoding="utf-8")
    print("\n" + report)

    valid_groups = [r for r in results if r.get("status") == "VALID"]
    if not valid_groups:
        raise RuntimeError("No group produced a validated BoP table.")


if __name__ == "__main__":
    main()
