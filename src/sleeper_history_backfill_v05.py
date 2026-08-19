import json
from pathlib import Path

import sleeper_history_backfill_v04 as base
from backfill_history import get_full_event_ranking as get_full_event_ranking_raw

CATALOG_FILE = Path("data/race_c_archive_catalog.json")
MERGED_FILE = Path("data/bop_lab/_sleeper_backfill_merged_history.json")
VERSION = "0.6"


def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def leaderboard_adapter(session, event_url):
    """
    V0.4 expects (ranking, total), while the current historical reader
    returns a dictionary containing ranking/total_records/mode.
    Keep the tested V0.4 model logic and adapt only the interface here.
    """
    result = get_full_event_ranking_raw(session, event_url)

    if isinstance(result, dict):
        ranking = result.get("ranking") or []
        total = result.get("total_records") or len(ranking)
        return ranking, int(total or 0)

    if isinstance(result, (tuple, list)) and len(result) >= 2:
        return result[0], int(result[1] or 0)

    raise RuntimeError("Historical leaderboard reader returned an unsupported result.")


def main():
    weekly = load_json(base.WEEKLY_HISTORY_FILE, []) or []
    catalog = load_json(CATALOG_FILE, []) or []

    merged = []
    seen = set()

    # Existing personal/history records remain authoritative if duplicated.
    for item in weekly:
        url = item.get("leaderboard_url")
        key = url or (
            f"weekly:{item.get('week_start')}:"
            f"{item.get('race_description') or item.get('description') or item.get('race')}"
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)

    # Catalog rows are discovery metadata. Participation is irrelevant here:
    # the Sleeper model needs the complete archived leaderboard, not the user's
    # personal presence in that historical race.
    catalog_added = 0
    for item in catalog:
        url = item.get("leaderboard_url")
        if not url or url in seen:
            continue

        description = (
            item.get("race_description")
            or item.get("description")
            or item.get("race")
            or ""
        )
        week_start = item.get("week_start") or item.get("date")

        if not description or not week_start:
            continue

        seen.add(url)
        catalog_added += 1
        merged.append({
            "week_start": week_start,
            "date": item.get("date") or week_start,
            "race_description": description,
            "leaderboard_url": url,
            "catalog_only": True,
            "source": item.get("source") or "GTSH_RANK_ARCHIVE",
        })

    MERGED_FILE.parent.mkdir(parents=True, exist_ok=True)
    MERGED_FILE.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"GT7 SLEEPER HISTORY BACKFILL V{VERSION}")
    print("=" * 100)
    print(f"Existing weekly/history rows : {len(weekly)}")
    print(f"Full archive catalog rows    : {len(catalog)}")
    print(f"Usable catalog rows added    : {catalog_added}")
    print(f"Merged candidate rows        : {len(merged)}")
    print("Classification uses explicit event text first, then group-specific track map, then track default.")
    print("Only matching group + speed-class weeks may download full leaderboards.")
    print("=" * 100)

    # V0.4 has the group-aware speed resolver. The previous V0.5 wrapper
    # accidentally reused V0.3, whose old speed_for_track() could not read the
    # newer group-specific mapping schema; that reduced the 694-row catalog to
    # zero eligible rows.
    base.WEEKLY_HISTORY_FILE = MERGED_FILE
    base.VERSION = VERSION
    base.get_full_event_ranking = leaderboard_adapter
    base.main()

    # Transient merge file should never become persistent project data.
    try:
        MERGED_FILE.unlink()
    except FileNotFoundError:
        pass


if __name__ == "__main__":
    main()
