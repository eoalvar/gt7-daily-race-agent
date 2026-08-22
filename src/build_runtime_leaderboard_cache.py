from __future__ import annotations

import json
from pathlib import Path

import requests

SNAPSHOT_FILE = Path("data/latest_snapshot.json")
CACHE_FILE = Path(".cache/current_leaderboard.json")


def main():
    snapshot = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    leaderboard_url = (snapshot.get("race") or {}).get("leaderboard_url")
    if not leaderboard_url:
        raise RuntimeError("Leaderboard URL missing from latest snapshot")

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
                    server_total = int(payload[key])
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
    print(f"Shared runtime leaderboard cache built: {len(result):,} entries")


if __name__ == "__main__":
    main()
