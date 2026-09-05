"""Run the Daily C agent while caching GTSH page_data responses for later steps.

The main agent already downloads the complete live leaderboard. Historically the
workflow downloaded the same leaderboard a second time immediately afterwards to
build the shared runtime cache. This wrapper records those JSON responses so
build_runtime_leaderboard_cache.py can reuse them without another network scan.

GTSH's compact RUNNING block does not always contain the weekly event date. When
that happens the detector correctly identifies the live Race C, but its date is
None. Daily Races are weekly events starting on Monday, so for an explicitly
RUNNING Race C we infer the current Sao Paulo Monday. This restores start_date for
the Sunday forecast and other enrichments without changing race selection.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

CACHE_DIR = Path(".cache/page_data")
AGENT_FILE = Path("src/test_race_detector.py")
_original_get = requests.Session.get


def _cache_path(url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{digest}.json"


def _cached_get(self, url, *args, **kwargs):
    response = _original_get(self, url, *args, **kwargs)
    try:
        parsed = urlparse(str(url))
        query = parse_qs(parsed.query)
        if query.get("page_data") == ["1"] and response.ok:
            payload = response.json()
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            _cache_path(str(url)).write_text(
                json.dumps({"url": str(url), "payload": payload}, ensure_ascii=False),
                encoding="utf-8",
            )
    except Exception as exc:
        print(f"WARNING: page-data cache write skipped: {exc}")
    return response


def _run_daily_agent():
    source = AGENT_FILE.read_text(encoding="utf-8")
    marker = '''        selected[\n            "detection_mode"\n        ] = "explicit_running_local_block"\n'''
    replacement = '''        # GTSH may omit the date from the compact RUNNING block.\n        # An explicitly running Daily Race is the current weekly event, whose\n        # GT7 week starts on the current Sao Paulo Monday.\n        if selected.get("date") is None:\n            selected["date"] = monday_of_week(now)\n            selected["date_inferred"] = True\n\n        selected[\n            "detection_mode"\n        ] = "explicit_running_local_block"\n'''
    if marker not in source:
        raise RuntimeError("Daily C date-inference patch marker not found; refusing silent fallback.")
    source = source.replace(marker, replacement, 1)
    namespace = {
        "__name__": "__main__",
        "__file__": str(AGENT_FILE),
        "__package__": None,
    }
    exec(compile(source, str(AGENT_FILE), "exec"), namespace)


requests.Session.get = _cached_get
try:
    _run_daily_agent()
finally:
    requests.Session.get = _original_get
