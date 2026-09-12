"""Run the Daily C agent with parallel GTSH leaderboard pagination.

The Daily C agent needs the complete live qualifying leaderboard for the report,
DR benchmarks, Expected Start and car statistics. GTSH serves that leaderboard in
paged page_data responses. The original agent fetched those pages sequentially,
which made network latency dominate runtime as the weekly population grew.

This wrapper patches only the live page-data collection block at runtime. It:
- fetches page 0 synchronously to learn the real server page size and population;
- fetches the remaining offsets concurrently with a conservative worker limit;
- retries failed offsets sequentially before allowing the agent's own fallbacks;
- captures the exact page_data responses and writes one shared runtime cache for
  downstream analysis.

All report calculations remain unchanged.
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
            server_total = max(server_total or 0, total)
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
    print(f"Shared runtime leaderboard cache built: {len(result):,} entries")


def _parallel_page_data_block() -> str:
    return r'''    # --------------------------------------------------------
    # 1. PRIMARY SOURCE: LIVE page_data=1 (parallel pagination)
    # --------------------------------------------------------

    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        live_ranking = []
        seen_ranks = set()
        requested_limit = 1000
        max_workers = 6

        separator = (
            "&"
            if "?" in race_c_link
            else "?"
        )

        def build_page_url(offset):
            return (
                race_c_link
                + separator
                + "page_data=1"
                + f"&offset={offset}"
                + f"&limit={requested_limit}"
            )

        # Fetch page zero synchronously. Its returned size is the authoritative
        # paging stride even if GTSH caps/ignores limit=1000.
        first_response = session.get(
            build_page_url(0),
            timeout=60
        )
        first_response.raise_for_status()
        first_payload = first_response.json()
        (
            first_entries,
            first_total,
            _first_offset,
            _first_limit,
            _first_has_more
        ) = extract_page_data_payload(first_payload)

        if not isinstance(first_entries, list):
            raise RuntimeError(
                "page_data response did not contain a ranking list."
            )
        if not first_entries:
            raise RuntimeError(
                "page_data returned an empty first page."
            )

        page_stride = len(first_entries)
        live_total_drivers = first_total or page_stride

        def add_entries(entries):
            added = 0
            for driver in entries:
                if not isinstance(driver, dict):
                    continue
                rank = driver.get("display_rank")
                if isinstance(rank, (int, float)):
                    rank_key = int(rank)
                    if rank_key in seen_ranks:
                        continue
                    seen_ranks.add(rank_key)
                live_ranking.append(driver)
                added += 1
            return added

        add_entries(first_entries)

        def fetch_offset(offset):
            # requests.Session is not shared across worker threads.
            worker_session = requests.Session()
            worker_session.headers.update(HEADERS)
            response = worker_session.get(
                build_page_url(offset),
                timeout=60
            )
            response.raise_for_status()
            payload = response.json()
            parsed = extract_page_data_payload(payload)
            entries, total, _returned_offset, _returned_limit, _has_more = parsed
            if not isinstance(entries, list):
                raise RuntimeError(
                    f"page_data offset {offset} did not contain a ranking list."
                )
            return offset, entries, total

        next_offset = page_stride
        parallel_round = 0

        # Usually one round is sufficient. Extra rounds cover drivers added to
        # the leaderboard while this scan is running.
        while next_offset < live_total_drivers and parallel_round < 4:
            parallel_round += 1
            round_end = live_total_drivers
            offsets = list(range(next_offset, round_end, page_stride))
            if not offsets:
                break

            print(
                f"Parallel leaderboard round {parallel_round}: "
                f"{len(offsets)} pages | workers={max_workers} | "
                f"target={round_end:,}"
            )

            page_results = {}
            failed_offsets = []

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(fetch_offset, offset): offset
                    for offset in offsets
                }
                for future in as_completed(futures):
                    offset = futures[future]
                    try:
                        returned_offset, entries, total = future.result()
                        page_results[returned_offset] = entries
                        if isinstance(total, (int, float)):
                            live_total_drivers = max(
                                live_total_drivers,
                                int(total)
                            )
                    except Exception as exc:
                        print(
                            f"WARNING: parallel page failed at offset {offset}: {exc}"
                        )
                        failed_offsets.append(offset)

            # Retry only failed pages sequentially. This avoids discarding an
            # otherwise complete parallel scan because of a transient request.
            for offset in failed_offsets:
                last_error = None
                for attempt in range(2):
                    try:
                        returned_offset, entries, total = fetch_offset(offset)
                        page_results[returned_offset] = entries
                        if isinstance(total, (int, float)):
                            live_total_drivers = max(
                                live_total_drivers,
                                int(total)
                            )
                        last_error = None
                        break
                    except Exception as exc:
                        last_error = exc
                        print(
                            f"WARNING: retry {attempt + 1}/2 failed at "
                            f"offset {offset}: {exc}"
                        )
                if last_error is not None:
                    raise RuntimeError(
                        f"Unable to fetch leaderboard offset {offset}: {last_error}"
                    )

            for offset in sorted(page_results):
                entries = page_results[offset]
                if not entries and offset < round_end:
                    raise RuntimeError(
                        f"Leaderboard returned zero entries at offset {offset}."
                    )
                add_entries(entries)

            next_offset = offsets[-1] + page_stride

        if live_total_drivers is not None and len(live_ranking) < live_total_drivers:
            raise RuntimeError(
                f"Parallel leaderboard incomplete: "
                f"{len(live_ranking):,}/{live_total_drivers:,}"
            )

        if live_ranking:
            ranking = live_ranking
            source_mode = "live_page_data_parallel"
            print(
                f"Leaderboard source: LIVE page_data PARALLEL | "
                f"entries={len(ranking):,} | "
                f"server_total={live_total_drivers} | workers={max_workers}"
            )

    except Exception as exc:
        print(
            "WARNING: parallel live page_data leaderboard failed: "
            f"{exc}"
        )
        ranking = None

'''


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

    primary_start_marker = '''    # --------------------------------------------------------\n    # 1. PRIMARY SOURCE: LIVE page_data=1\n    # --------------------------------------------------------\n'''
    fallback_marker = '''    # --------------------------------------------------------\n    # 2. FALLBACK: initialRanking embedded in HTML\n    # --------------------------------------------------------\n'''
    primary_start = source.find(primary_start_marker)
    fallback_start = source.find(fallback_marker, primary_start + 1)
    if primary_start < 0 or fallback_start < 0:
        raise RuntimeError(
            "Daily C primary leaderboard block markers not found; refusing silent fallback."
        )
    source = (
        source[:primary_start]
        + _parallel_page_data_block()
        + source[fallback_start:]
    )

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
