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


def extract_total(payload):
    if not isinstance(payload, dict):
        return None
    for key in ("total", "total_drivers", "totalDrivers", "count", "recordsTotal"):
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return None


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
    """Probe GTSH 100-row pages around the previously stored rank."""
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
        off = (off // PAGE_SIZE) * PAGE_SIZE
        if off < 0 or off in seen:
            continue
        seen.add(off)
        ordered.append(off)
    return ordered


def page_url(leaderboard_url: str, offset: int) -> str:
    sep = "&" if "?" in leaderboard_url else "?"
    return f"{leaderboard_url}{sep}page_data=1&offset={offset}&limit={PAGE_SIZE}"


def fetch_page(session, leaderboard_url: str, offset: int):
    response = session.get(page_url(leaderboard_url, offset), timeout=30)
    response.raise_for_status()
    payload = response.json()
    return payload, extract_entries(payload)


def find_first_weekly_pb(session, leaderboard_url: str):
    """Find the driver's first qualifying time when no stored baseline exists.

    With no previous rank there is no useful anchor, so scan the live ranking
    in 100-row pages until the PSN is found or the server total is exhausted.
    This path is only used before the first Daily C time of a new week has
    been captured; after that, normal rank-centered probing resumes.
    """
    offset = 0
    requests_used = 0
    server_total = None

    while True:
        payload, entries = fetch_page(session, leaderboard_url, offset)
        requests_used += 1

        if server_total is None:
            server_total = extract_total(payload)

        found = find_driver(entries)
        if found:
            return found, requests_used, server_total

        if not entries:
            return None, requests_used, server_total

        offset += len(entries)
        offset = (offset // PAGE_SIZE) * PAGE_SIZE

        if server_total is not None and offset >= server_total:
            return None, requests_used, server_total

        # Safety valve against a malformed endpoint that never terminates.
        if requests_used >= 1000:
            return None, requests_used, server_total


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

    if not leaderboard_url:
        raise RuntimeError("Snapshot lacks leaderboard URL")

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (GT7 PB Watch)"})

    has_baseline = (
        isinstance(baseline_score, (int, float))
        and isinstance(last_rank, (int, float))
    )

    # FIRST PB OF WEEK MODE
    # A Monday/new-week snapshot can legitimately have my_result=null. In
    # that case, the first appearance of the PSN in the live leaderboard is
    # itself the event that must trigger a full Daily Race C refresh.
    if not has_baseline:
        found, requests_used, server_total = find_first_weekly_pb(
            session, leaderboard_url
        )

        if not found:
            total_text = f"/{server_total:,}" if isinstance(server_total, int) else ""
            print(
                f"PB Watch: no stored weekly baseline and {PSN_ID} not yet found "
                f"in live leaderboard after {requests_used} page requests{total_text}; no trigger."
            )
            set_output("improved", "false")
            set_output("found", "false")
            set_output("mode", "first_pb_wait")
            return

        live_score = found.get("score")
        live_rank = found.get("display_rank")

        if not isinstance(live_score, (int, float)):
            print("PB Watch: first weekly entry found but score missing; no trigger.")
            set_output("improved", "false")
            set_output("found", "true")
            set_output("mode", "first_pb_invalid")
            return

        print(
            f"PB Watch: FIRST PB OF WEEK detected for {PSN_ID}: "
            f"{score_to_laptime(live_score)} at "
            f"#{int(live_rank):,} | requests={requests_used}. Trigger Daily Race C."
            if isinstance(live_rank, (int, float))
            else (
                f"PB Watch: FIRST PB OF WEEK detected for {PSN_ID}: "
                f"{score_to_laptime(live_score)} | requests={requests_used}. "
                "Trigger Daily Race C."
            )
        )

        set_output("improved", "true")
        set_output("found", "true")
        set_output("mode", "first_pb")
        set_output("live_score", str(int(live_score)))
        set_output(
            "live_rank",
            str(int(live_rank)) if isinstance(live_rank, (int, float)) else "",
        )
        set_output("gain_ms", "0")
        return

    # NORMAL PB MODE
    found = None
    requests_used = 0
    checked_offsets = []
    for offset in candidate_offsets(int(last_rank)):
        _, entries = fetch_page(session, leaderboard_url, offset)
        requests_used += 1
        checked_offsets.append(offset)
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
        set_output("mode", "baseline")
        return

    live_score = found.get("score")
    live_rank = found.get("display_rank")
    if not isinstance(live_score, (int, float)):
        print("PB Watch: driver found but score missing; no trigger.")
        set_output("improved", "false")
        set_output("found", "true")
        set_output("mode", "baseline")
        return

    improved = float(live_score) < float(baseline_score)
    gain_ms = int(round(float(baseline_score) - float(live_score))) if improved else 0

    print(
        f"PB Watch: baseline {score_to_laptime(baseline_score)} at #{int(last_rank):,} | "
        f"live {score_to_laptime(live_score)} at "
        f"#{int(live_rank):,} | requests={requests_used} | "
        f"improved={'YES' if improved else 'NO'}"
        if isinstance(live_rank, (int, float))
        else (
            f"PB Watch: baseline {score_to_laptime(baseline_score)} at #{int(last_rank):,} | "
            f"live {score_to_laptime(live_score)} | requests={requests_used} | "
            f"improved={'YES' if improved else 'NO'}"
        )
    )
    if improved:
        print(f"New PB detected: {gain_ms} ms faster. Trigger Daily Race C.")

    set_output("improved", "true" if improved else "false")
    set_output("found", "true")
    set_output("mode", "baseline")
    set_output("live_score", str(int(live_score)))
    set_output("live_rank", str(int(live_rank)) if isinstance(live_rank, (int, float)) else "")
    set_output("gain_ms", str(gain_ms))


if __name__ == "__main__":
    main()
