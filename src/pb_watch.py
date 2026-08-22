from __future__ import annotations

import json
import os
from pathlib import Path

import requests

SNAPSHOT_FILE = Path("data/latest_snapshot.json")
PSN_ID = "crazy_rooster74"
PAGE_SIZE = 1000


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
    """Search near the prior rank first, then progressively farther upward.

    A new PB can only make the driver's own qualifying rank better relative to
    the same leaderboard snapshot, while new entrants can push the stored rank
    slightly downward. This usually finds the user in only a handful of 1000-row
    requests instead of downloading the full leaderboard.
    """
    center = max(0, ((max(1, last_rank) - 1) // PAGE_SIZE) * PAGE_SIZE)
    offsets = [center, center + PAGE_SIZE, center + 2 * PAGE_SIZE]

    step = PAGE_SIZE
    while center - step >= 0:
        offsets.append(center - step)
        step *= 2

    # Fill gaps between exponential probes for moderate PB jumps.
    for off in range(max(0, center - 5000), center, PAGE_SIZE):
        offsets.append(off)

    # Always include the first page as a final cheap safety check.
    offsets.append(0)

    seen = set()
    ordered = []
    for off in offsets:
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
    for offset in candidate_offsets(int(last_rank)):
        sep = "&" if "?" in leaderboard_url else "?"
        url = f"{leaderboard_url}{sep}page_data=1&offset={offset}&limit={PAGE_SIZE}"
        response = session.get(url, timeout=30)
        response.raise_for_status()
        requests_used += 1
        entries = extract_entries(response.json())
        found = find_driver(entries)
        if found:
            break

    if not found:
        print(f"PB Watch: {PSN_ID} not found near stored rank after {requests_used} requests; no trigger.")
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
