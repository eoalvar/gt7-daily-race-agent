from __future__ import annotations

import json
import os
from pathlib import Path

import requests

SNAPSHOT_FILE = Path("data/latest_snapshot.json")
PSN_ID = "crazy_rooster74"
# GTSH page_data is paginated in 100-row pages. Asking for 1000 does not
# guarantee 1000 returned rows, so offsets must be aligned to the actual
# server page size or the stored rank can fall between probes.
PAGE_SIZE = 100


def score_to_laptime(score):
    if not isinstance(score, (int, float)):
        return "N/A"
    score = int(round(score))
    return f"{score // 60000}:{(score % 60000) // 1000:02d}.{score % 1000:03d}"


def extract_entries(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("board", "ranking", "data", "entries", "results", "drivers"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def find_driver(entries):
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        user = entry.get("user") or {}
        psn = user.get("np_online_id") or user.get("nick_name")
        if isinstance(psn, str) and psn.casefold() == PSN_ID.casefold():
            return entry
    return None


def candidate_offsets(last_rank: int):
    """Probe GTSH 100-row pages around the previously stored rank.

    The exact stored-rank page is checked first. We then check a compact set
    around it, biased upward because a new PB normally improves rank, while
    still allowing leaderboard growth to push the driver downward.
    """
    center = max(0, ((max(1, last_rank) - 1) // PAGE_SIZE) * PAGE_SIZE)

    deltas = [
        0,
        -100, 100,
        -200, 200,
        -300, 300,
        -500, 500,
        -800, 800,
        -1200, 1200,
        -2000, 2000,
    ]

    offsets = [max(0, center + d) for d in deltas]
    offsets.append(0)

    seen = set()
    ordered = []
    for off in offsets:
        # Keep page boundaries aligned to GTSH's 100-row pagination.
        off = (off // PAGE_SIZE) * PAGE_SIZE
        if off < 0 or off in seen:
            continue
        seen.add(off)
        ordered.append(off)
    return ordered


def set_output(name: str, value: str):
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as fh:
            fh.write(f"{name}={value}\n")


def main():
    if not SNAPSHOT_FILE.exists():
        raise RuntimeError("latest_snapshot.json not found; run Daily Race C first")

    snapshot = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    race = snapshot.get("race") or {}
    me = snapshot.get("my_result") or {}
    leaderboard_url = race.get("leaderboard_url")
    baseline_score = me.get("score")
    last_rank = me.get("rank")

    if not leaderboard_url or not isinstance(baseline_score, (int, float)) or not isinstance(last_rank, (int, float)):
        raise RuntimeError("Snapshot lacks leaderboard URL, baseline score, or rank")

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (GT7 PB Watch)"})

    found = None
    requests_used = 0
    checked_offsets = []
    for offset in candidate_offsets(int(last_rank)):
        sep = "&" if "?" in leaderboard_url else "?"
        url = f"{leaderboard_url}{sep}page_data=1&offset={offset}&limit={PAGE_SIZE}"
        response = session.get(url, timeout=30)
        response.raise_for_status()
        requests_used += 1
        checked_offsets.append(offset)
        entries = extract_entries(response.json())
        found = find_driver(entries)
        if found:
            break

    if not found:
        print(
            f"PB Watch: {PSN_ID} not found after {requests_used} page probes "
            f"around stored rank #{int(last_rank):,}; no trigger. "
            f"Offsets checked: {checked_offsets}"
        )
        set_output("improved", "false")
        set_output("found", "false")
        return

    live_score = found.get("score")
    live_rank = found.get("display_rank")
    if not isinstance(live_score, (int, float)):
        print("PB Watch: driver found but score missing; no trigger.")
        set_output("improved", "false")
        set_output("found", "true")
        return

    improved = float(live_score) < float(baseline_score)
    gain_ms = int(round(float(baseline_score) - float(live_score))) if improved else 0

    print(
        f"PB Watch: baseline {score_to_laptime(baseline_score)} at #{int(last_rank):,} | "
        f"live {score_to_laptime(live_score)} at #{int(live_rank):,} | "
        f"requests={requests_used} | improved={'YES' if improved else 'NO'}"
    )
    if improved:
        print(f"New PB detected: {gain_ms} ms faster. Trigger Daily Race C.")

    set_output("improved", "true" if improved else "false")
    set_output("found", "true")
    set_output("live_score", str(int(live_score)))
    set_output("live_rank", str(int(live_rank)) if isinstance(live_rank, (int, float)) else "")
    set_output("gain_ms", str(gain_ms))


if __name__ == "__main__":
    main()
