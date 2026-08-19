import json
from pathlib import Path

import sleeper_history_backfill as base

CATALOG_FILE = Path("data/race_c_archive_catalog.json")
MERGED_FILE = Path("data/bop_lab/_sleeper_backfill_merged_history.json")


def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def main():
    weekly = load_json(base.WEEKLY_HISTORY_FILE, []) or []
    catalog = load_json(CATALOG_FILE, []) or []

    merged = []
    seen = set()

    # Existing personal/history records first; they remain authoritative if duplicated.
    for item in weekly:
        url = item.get("leaderboard_url")
        key = url or f"weekly:{item.get('week_start')}:{item.get('race_description') or item.get('race')}"
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)

    for item in catalog:
        url = item.get("leaderboard_url")
        if not url or url in seen:
            continue
        seen.add(url)
        merged.append({
            "week_start": item.get("week_start"),
            "date": item.get("date"),
            "race_description": item.get("race_description"),
            "leaderboard_url": url,
            "participated": False,
            "catalog_only": True,
            "source": item.get("source") or "GTSH_RANK_ARCHIVE",
        })

    MERGED_FILE.parent.mkdir(parents=True, exist_ok=True)
    MERGED_FILE.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")

    print("GT7 SLEEPER HISTORY BACKFILL V0.5")
    print("=" * 100)
    print(f"Existing weekly/history rows : {len(weekly)}")
    print(f"Full archive catalog rows    : {len(catalog)}")
    print(f"Merged candidate rows        : {len(merged)}")
    print("Only the few rows matching the current group + speed class are allowed to download full leaderboards.")
    print("=" * 100)

    # Reuse the already-tested V0.4 training logic, but feed it the complete catalog.
    base.WEEKLY_HISTORY_FILE = MERGED_FILE
    base.VERSION = "0.5"
    base.main()

    # The merged candidate file is transient and should not become persistent project data.
    try:
        MERGED_FILE.unlink()
    except FileNotFoundError:
        pass


if __name__ == "__main__":
    main()
