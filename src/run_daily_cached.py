"""Run the Daily C agent and build the shared leaderboard cache in memory.

The main agent already downloads the complete live leaderboard. Older versions of
this wrapper serialized every page_data response to an individual file and a
second workflow step parsed all of those files again to assemble
.cache/current_leaderboard.json. This version keeps the responses in memory and
writes the consolidated cache once, after the agent finishes.

This removes dozens of JSON writes/reads per Daily C run while preserving the
single-network-scan design used by downstream DR, Expected Start and Sleeper
analysis.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

CACHE_FILE = Path(".cache/current_leaderboard.json")
SNAPSHOT_FILE = Path("data/latest_snapshot.json")
AGENT_FILE = Path("src/test_race_detector.py")
_original_get = requests.Session.get
_captured_pages: list[tuple[str, object]] = []


def _cached_get(self, url, *args, **kwargs):
    response = _original_get(self, url, *args, **kwargs)
    try:
        parsed = urlparse(str(url))
        query = parse_qs(parsed.query)
        if query.get("page_data") == ["1"] and response.ok:
            _captured_pages.append((str(url), response.json()))
    except Exception as exc:
        print(f"WARNING: page-data capture skipped: {exc}")
    return response


def _extract(payload):
    entries = None
    total = None
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
    return entries, total


def _write_runtime_cache():
    if not SNAPSHOT_FILE.exists():
        print("WARNING: latest snapshot missing; shared runtime cache not written")
        return

    snapshot = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    leaderboard_url = (snapshot.get("race") or {}).get("leaderboard_url")
    if not leaderboard_url:
        print("WARNING: leaderboard URL missing; shared runtime cache not written")
        return

    target_event = parse_qs(urlparse(leaderboard_url).query).get("event")
    matching = []
    for url, payload in _captured_pages:
        query = parse_qs(urlparse(url).query)
        if query.get("event") != target_event or query.get("page_data") != ["1"]:
            continue
        try:
            offset = int(query.get("offset", [0])[0])
        except Exception:
            offset = 0
        matching.append((offset, payload))

    result = []
    seen_ranks = set()
    server_total = None
    for _, payload in sorted(matching, key=lambda item: item[0]):
        entries, total = _extract(payload)
        if total is not None:
            server_total = total
        if not entries:
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            rank = entry.get("display_rank")
            if isinstance(rank, (int, float)):
                rank = int(rank)
                if rank in seen_ranks:
                    continue
                seen_ranks.add(rank)
            result.append(entry)

    result.sort(key=lambda item: item.get("display_rank", 999999999))
    complete = len(result) >= 1000 and (server_total is None or len(result) >= server_total)
    if not complete:
        raise RuntimeError(
            f"Captured leaderboard incomplete: {len(result):,}/{server_total or '?'} entries"
        )

    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(
        json.dumps(
            {
                "leaderboard_url": leaderboard_url,
                "server_total": server_total,
                "entries": result,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"Shared runtime leaderboard cache built in memory: {len(result):,} entries")


def _run_daily_agent():
    source = AGENT_FILE.read_text(encoding="utf-8")

    date_marker = '''        selected[\n            "detection_mode"\n        ] = "explicit_running_local_block"\n'''
    date_replacement = '''        # GTSH may omit the date from the compact RUNNING block.\n        # An explicitly running Daily Race is the current weekly event, whose\n        # GT7 week starts on the current Sao Paulo Monday.\n        if selected.get("date") is None:\n            selected["date"] = monday_of_week(now)\n            selected["date_inferred"] = True\n\n        selected[\n            "detection_mode"\n        ] = "explicit_running_local_block"\n'''
    if date_marker not in source:
        raise RuntimeError("Daily C date-inference patch marker not found; refusing silent fallback.")
    source = source.replace(date_marker, date_replacement, 1)

    history_sort_marker = '''            item.get(\n                "week_start",\n                ""\n            )\n'''
    history_sort_replacement = '''            (item.get(\n                "week_start"\n            ) or "")\n'''
    if history_sort_marker not in source:
        raise RuntimeError("Weekly-history sort patch marker not found; refusing silent fallback.")
    source = source.replace(history_sort_marker, history_sort_replacement, 1)

    namespace = {
        "__name__": "__main__",
        "__file__": str(AGENT_FILE),
        "__package__": None,
    }
    exec(compile(source, str(AGENT_FILE), "exec"), namespace)


requests.Session.get = _cached_get
try:
    _run_daily_agent()
    _write_runtime_cache()
finally:
    requests.Session.get = _original_get
