"""Run the Daily C agent while caching GTSH page_data responses for later steps.

The main agent already downloads the complete live leaderboard.  Historically the
workflow downloaded the same ~40k-entry leaderboard a second time immediately
afterwards to build the shared runtime cache.  This wrapper records those JSON
responses so build_runtime_leaderboard_cache.py can reuse them without another
network scan.
"""
from __future__ import annotations

import hashlib
import json
import runpy
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

CACHE_DIR = Path(".cache/page_data")
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


requests.Session.get = _cached_get
try:
    runpy.run_path("src/test_race_detector.py", run_name="__main__")
finally:
    requests.Session.get = _original_get
