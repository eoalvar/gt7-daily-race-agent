from __future__ import annotations

import json
import math
import re
from pathlib import Path

import requests

SNAPSHOT_FILE = Path("data/latest_snapshot.json")
REPORT_FILE = Path("reports/latest.txt")
CACHE_FILE = Path(".cache/current_leaderboard.json")
GRID_SIZE = 16
DR_LABELS = {1: "E", 2: "D", 3: "C", 4: "B", 5: "A", 6: "A+", 7: "S"}


def cached_leaderboard_entries(url: str):
    if not CACHE_FILE.exists():
        return None
    try:
        cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        entries = cache.get("entries")
        if cache.get("leaderboard_url") == url and isinstance(entries, list) and len(entries) >= 1000:
            print(f"Expected-start using shared runtime leaderboard cache: {len(entries):,} entries")
            return entries
    except Exception as exc:
        print(f"Shared leaderboard cache unavailable for expected start: {exc}")
    return None


def leaderboard_entries(session: requests.Session, url: str):
    cached = cached_leaderboard_entries(url)
    if cached is not None:
        return cached

    result = []
    seen = set()
    offset = 0
    limit = 1000
    total = None
    for _ in range(1000):
        sep = "&" if "?" in url else "?"
        r = session.get(f"{url}{sep}page_data=1&offset={offset}&limit={limit}", timeout=60)
        r.raise_for_status()
        payload = r.json()
        entries = None
        if isinstance(payload, list):
            entries = payload
        elif isinstance(payload, dict):
            for key in ("board", "ranking", "data", "entries", "results", "drivers"):
                if isinstance(payload.get(key), list):
                    entries = payload[key]
                    break
            for key in ("total", "total_drivers", "totalDrivers", "count", "recordsTotal"):
                if isinstance(payload.get(key), (int, float)):
                    total = int(payload[key])
                    break
        if not entries:
            break
        added = 0
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            rank = entry.get("display_rank")
            if isinstance(rank, (int, float)):
                rank = int(rank)
                if rank in seen:
                    continue
                seen.add(rank)
            result.append(entry)
            added += 1
        if added == 0:
            break
        if total is not None and len(seen) >= total:
            break
        offset += len(entries)
    return result


def start_band(position: float) -> str:
    if position <= 3.0:
        return "1 to 3"
    if position <= 6.0:
        return "4 to 6"
    if position <= 9.0:
        return "7 to 9"
    if position <= 12.0:
        return "10 to 12"
    return "13 to 16"


def wilson_interval(faster: int, total: int, z: float = 1.96):
    if total <= 0:
        return None, None
    p = faster / total
    denominator = 1.0 + z * z / total
    centre = (p + z * z / (2.0 * total)) / denominator
    margin = z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * total)) / total) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)


def main():
    snapshot = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    race = snapshot.get("race") or {}
    me = snapshot.get("my_result") or {}

    leaderboard_url = race.get("leaderboard_url")
    my_score = me.get("score")
    my_dr = me.get("driver_rating")

    if not leaderboard_url or not isinstance(my_score, (int, float)) or not isinstance(my_dr, (int, float)):
        print("Expected-start estimate skipped: required data unavailable.")
        return

    my_dr = int(my_dr)
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (GT7 Expected Start DR Percentile)"})
    try:
        entries = leaderboard_entries(session, leaderboard_url)
    finally:
        session.close()

    scores = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        user = entry.get("user") or {}
        dr = user.get("driver_rating")
        score = entry.get("score")
        if isinstance(dr, (int, float)) and int(dr) == my_dr and isinstance(score, (int, float)):
            scores.append(float(score))

    if not scores:
        print("Expected-start estimate skipped: no same-DR qualifying population.")
        return

    my_score = float(my_score)
    faster = sum(1 for score in scores if score < my_score)
    equal = sum(1 for score in scores if score == my_score)
    # Half-credit ties avoids systematically pushing an equal-time driver backward.
    q = (faster + 0.5 * equal) / len(scores)
    expected_position = 1.0 + (GRID_SIZE - 1) * q
    band = start_band(expected_position)

    low_q, high_q = wilson_interval(faster, len(scores))
    low_position = 1.0 + (GRID_SIZE - 1) * low_q if low_q is not None else expected_position
    high_position = 1.0 + (GRID_SIZE - 1) * high_q if high_q is not None else expected_position

    # This is deliberately a matchmaking approximation, not a claim that the
    # global leaderboard itself is the lobby. GT7 forms the lobby first; the
    # qualifying times of those matched drivers then determine grid order.
    # Same-DR qualifying percentile is therefore used as the population prior.
    confidence = "HIGH" if len(scores) >= 1000 else "MEDIUM" if len(scores) >= 250 else "LOW"

    estimate = {
        "model": "DR_QUALIFYING_PERCENTILE_V2",
        "grid_size": GRID_SIZE,
        "dr": my_dr,
        "dr_label": DR_LABELS.get(my_dr),
        "same_dr_population": len(scores),
        "faster_same_dr": faster,
        "equal_same_dr": equal,
        "qualifying_percentile_faster": q * 100.0,
        "expected_position": expected_position,
        "expected_start_range": band,
        "confidence": confidence,
        "sampling_interval_position_95": [low_position, high_position],
        "basis": "qualifying percentile within current DR population",
    }
    snapshot["expected_start"] = estimate
    SNAPSHOT_FILE.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    report = REPORT_FILE.read_text(encoding="utf-8")
    report = re.sub(r"\nEXPECTED START\n.*?(?=\n\n[A-Z][A-Z &/0-9-]+\n|\Z)", "", report, flags=re.DOTALL)
    block = (
        "EXPECTED START\n"
        f"Projected grid range : {band}\n"
        f"Expected position    : P{expected_position:.1f}\n"
        f"Confidence           : {confidence}\n"
        f"Model basis          : DR {DR_LABELS.get(my_dr)} qualifying percentile | {len(scores):,} drivers | {q * 100:.1f}% faster\n"
    )
    marker = "\nDR LAP-TIME BENCHMARKS - FULL LEADERBOARD\n"
    if marker in report:
        report = report.replace(marker, "\n" + block + "\nDR LAP-TIME BENCHMARKS - FULL LEADERBOARD\n", 1)
    else:
        report = report.rstrip() + "\n\n" + block
    REPORT_FILE.write_text(report, encoding="utf-8")

    print(
        f"Expected Start: {band} | Confidence: {confidence} | "
        f"P{expected_position:.1f} | DR {DR_LABELS.get(my_dr)} population={len(scores):,} | "
        f"faster={q * 100:.1f}%"
    )


if __name__ == "__main__":
    main()
