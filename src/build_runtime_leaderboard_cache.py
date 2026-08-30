from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

SNAPSHOT_FILE = Path("data/latest_snapshot.json")
CACHE_FILE = Path(".cache/current_leaderboard.json")
PAGE_CACHE_DIR = Path(".cache/page_data")


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


def _assemble(cached_pages):
    result = []
    seen_ranks = set()
    server_total = None
    for _, payload in sorted(cached_pages, key=lambda item: item[0]):
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
    return result, server_total


def _load_agent_page_cache(leaderboard_url):
    pages = []
    if not PAGE_CACHE_DIR.exists():
        return pages
    base_event = parse_qs(urlparse(leaderboard_url).query).get("event")
    for path in PAGE_CACHE_DIR.glob("*.json"):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            url = item.get("url", "")
            query = parse_qs(urlparse(url).query)
            if query.get("event") != base_event or query.get("page_data") != ["1"]:
                continue
            offset = int(query.get("offset", [0])[0])
            pages.append((offset, item.get("payload")))
        except Exception:
            continue
    return pages


def main():
    snapshot = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    leaderboard_url = (snapshot.get("race") or {}).get("leaderboard_url")
    if not leaderboard_url:
        raise RuntimeError("Leaderboard URL missing from latest snapshot")

    # Fast path: the Daily C agent just downloaded these exact pages. Reuse them.
    cached_pages = _load_agent_page_cache(leaderboard_url)
    if cached_pages:
        result, server_total = _assemble(cached_pages)
        complete = len(result) >= 1000 and (
            server_total is None or len(result) >= server_total
        )
        if complete:
            cache = {
                "leaderboard_url": leaderboard_url,
                "server_total": server_total,
                "entries": result,
            }
            CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
            print(f"Shared runtime leaderboard cache reused from Daily C scan: {len(result):,} entries")
            return
        print(
            f"Daily C page cache incomplete ({len(result):,}/{server_total or '?'}); "
            "falling back to live scan."
        )

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (GT7 Daily Race Runtime Cache)"})

    result = []
    seen_ranks = set()
    offset = 0
    limit = 1000
    server_total = None

    for _ in range(1000):
        sep = "&" if "?" in leaderboard_url else "?"
        url = f"{leaderboard_url}{sep}page_data=1&offset={offset}&limit={limit}"
        response = session.get(url, timeout=60)
        response.raise_for_status()
        payload = response.json()
        entries, total = _extract(payload)
        if total is not None:
            server_total = total
        if not entries:
            break

        added = 0
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
            added += 1

        if added == 0:
            break
        if server_total is not None and len(seen_ranks) >= server_total:
            break
        offset += len(entries)

    if len(result) < 1000:
        raise RuntimeError(f"Runtime leaderboard cache unexpectedly small: {len(result)} entries")

    cache = {
        "leaderboard_url": leaderboard_url,
        "server_total": server_total,
        "entries": result,
    }
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    print(f"Shared runtime leaderboard cache built live: {len(result):,} entries")


if __name__ == "__main__":
    main()
