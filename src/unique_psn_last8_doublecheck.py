from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import requests

import recover_historical_race as recovery
from unique_psn_last8 import load_latest_races, norm_psn, extract_psn

OUT_JSON = Path("data/unique_psn_last8_doublecheck.json")
OUT_REPORT = Path("reports/unique_psn_last8_doublecheck.txt")


def extract_user_id(driver):
    if not isinstance(driver, dict):
        return None
    user = driver.get("user") or {}
    value = user.get("user_id") or user.get("account_id") or user.get("id")
    if value in (None, ""):
        return None
    return str(value).strip().casefold()


def main():
    races = load_latest_races()
    if len(races) != 8:
        raise RuntimeError(f"Expected 8 races, found {len(races)}")

    session = requests.Session()
    session.headers.update(recovery.HEADERS)

    psn_sets = []
    uid_sets = []
    per_race = []

    for idx, race in enumerate(races, 1):
        label = race.get("week_start") or f"race_{idx}"
        print(f"[{idx}/8] Reloading {label}")
        result = recovery.get_full_event_ranking(session, race["leaderboard_url"])
        ranking = result.get("ranking") or []

        psns = set()
        uids = set()
        missing_uid = 0
        for driver in ranking:
            psn = norm_psn(extract_psn(driver))
            if psn:
                psns.add(psn)
            uid = extract_user_id(driver)
            if uid:
                uids.add(uid)
            else:
                missing_uid += 1

        psn_sets.append(psns)
        uid_sets.append(uids)
        per_race.append({
            "week_start": race.get("week_start"),
            "rows": len(ranking),
            "unique_psn": len(psns),
            "unique_user_id": len(uids),
            "missing_user_id_rows": missing_uid,
        })
        print(f"  PSN={len(psns):,} | user_id={len(uids):,} | missing user_id rows={missing_uid:,}")

    # Independent direct set intersection, not Counter frequency logic.
    psn_all8 = set.intersection(*psn_sets)
    uid_all8 = set.intersection(*uid_sets) if all(uid_sets) else set()
    psn_union = set.union(*psn_sets)
    uid_union = set.union(*uid_sets) if any(uid_sets) else set()

    # Recompute frequency independently as a cross-check.
    psn_freq = Counter()
    for s in psn_sets:
        psn_freq.update(s)
    uid_freq = Counter()
    for s in uid_sets:
        uid_freq.update(s)

    # Sequential intersection: how quickly the common cohort shrinks as races are added.
    sequential = []
    running_psn = None
    running_uid = None
    for idx, (race, pset, uset) in enumerate(zip(races, psn_sets, uid_sets), 1):
        running_psn = set(pset) if running_psn is None else running_psn & pset
        running_uid = set(uset) if running_uid is None else running_uid & uset
        sequential.append({
            "through_week": race.get("week_start"),
            "races_in_intersection": idx,
            "common_psn": len(running_psn),
            "common_user_id": len(running_uid),
        })

    # Reverse sequential intersection anchored on the latest/current race.
    reverse = []
    running_psn = None
    running_uid = None
    for depth, (race, pset, uset) in enumerate(zip(reversed(races), reversed(psn_sets), reversed(uid_sets)), 1):
        running_psn = set(pset) if running_psn is None else running_psn & pset
        running_uid = set(uset) if running_uid is None else running_uid & uset
        reverse.append({
            "oldest_week_included": race.get("week_start"),
            "latest_races_in_intersection": depth,
            "common_psn": len(running_psn),
            "common_user_id": len(running_uid),
        })

    payload = {
        "method": "independent direct set intersection + stable user_id cross-check",
        "psn": {
            "union": len(psn_union),
            "all_8_direct_intersection": len(psn_all8),
            "all_8_frequency_recheck": sum(1 for n in psn_freq.values() if n == 8),
        },
        "user_id": {
            "union": len(uid_union),
            "all_8_direct_intersection": len(uid_all8),
            "all_8_frequency_recheck": sum(1 for n in uid_freq.values() if n == 8),
        },
        "per_race": per_race,
        "sequential_oldest_to_latest": sequential,
        "sequential_latest_to_oldest": reverse,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "GT7 UNIQUE PSN LAST 8 - DOUBLE CHECK",
        "=" * 90,
        f"PSN union                           : {len(psn_union):,}",
        f"PSN all-8 direct intersection      : {len(psn_all8):,}",
        f"PSN all-8 frequency recheck        : {sum(1 for n in psn_freq.values() if n == 8):,}",
        f"Stable user_id union               : {len(uid_union):,}",
        f"Stable user_id all-8 intersection  : {len(uid_all8):,}",
        f"Stable user_id frequency recheck   : {sum(1 for n in uid_freq.values() if n == 8):,}",
        "",
        "LATEST-RACE-ANCHORED INTERSECTION",
    ]
    for item in reverse:
        lines.append(
            f"Latest {item['latest_races_in_intersection']} race(s): "
            f"{item['common_psn']:,} PSN | {item['common_user_id']:,} user_id"
        )
    lines.extend(["", "PER-RACE IDENTIFIER CHECK"])
    for item in per_race:
        lines.append(
            f"{item['week_start']} | rows {item['rows']:,} | PSN {item['unique_psn']:,} | "
            f"user_id {item['unique_user_id']:,} | missing user_id {item['missing_user_id_rows']:,}"
        )
    lines.append("=" * 90)
    report = "\n".join(lines) + "\n"
    OUT_REPORT.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
