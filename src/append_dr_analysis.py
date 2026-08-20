from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

SNAPSHOT_FILE = Path("data/latest_snapshot.json")
REPORT_FILE = Path("reports/latest.txt")

DR_LABELS = {1: "E", 2: "D", 3: "C", 4: "B", 5: "A", 6: "A+"}


def score_to_laptime(score):
    if not isinstance(score, (int, float)):
        return "N/A"
    score = int(round(score))
    return f"{score // 60000}:{(score % 60000) // 1000:02d}.{score % 1000:03d}"


def main():
    if not SNAPSHOT_FILE.exists() or not REPORT_FILE.exists():
        raise RuntimeError("Required snapshot/report not found")

    snapshot = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    race = snapshot.get("race", {})
    leaderboard_url = race.get("leaderboard_url")
    if not leaderboard_url:
        raise RuntimeError("Leaderboard URL missing from latest snapshot")

    # Import the production collector so this analysis uses the same GTSH schema.
    import requests

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (GT7 Daily Race Agent)"})

    groups = defaultdict(list)
    offset = 0
    limit = 1000
    seen = set()
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
        for driver in entries:
            if not isinstance(driver, dict):
                continue
            rank = driver.get("display_rank")
            if isinstance(rank, (int, float)):
                rank = int(rank)
                if rank in seen:
                    continue
                seen.add(rank)
            user = driver.get("user") or {}
            dr = user.get("driver_rating")
            score = driver.get("score")
            if isinstance(dr, (int, float)) and isinstance(score, (int, float)):
                dr = int(dr)
                if dr in DR_LABELS:
                    groups[dr].append(float(score))
            added += 1

        if added == 0:
            break
        if server_total is not None and len(seen) >= server_total:
            break
        offset += len(entries)

    stats = {}
    for dr in sorted(DR_LABELS):
        scores = groups.get(dr, [])
        stats[str(dr)] = {
            "dr": dr,
            "label": DR_LABELS[dr],
            "drivers": len(scores),
            "average_score": (sum(scores) / len(scores)) if scores else None,
            "average_laptime": score_to_laptime(sum(scores) / len(scores)) if scores else "N/A",
        }

    snapshot["dr_laptime_stats"] = stats
    my = snapshot.get("my_result") or {}
    my_dr = my.get("driver_rating")
    if isinstance(my_dr, (int, float)):
        my["driver_rating_label"] = DR_LABELS.get(int(my_dr), f"DR {int(my_dr)}")
    dr_stats = snapshot.get("dr_stats") or {}
    if isinstance(dr_stats.get("dr"), (int, float)):
        dr_stats["label"] = DR_LABELS.get(int(dr_stats["dr"]), f"DR {int(dr_stats['dr'])}")

    SNAPSHOT_FILE.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    report = REPORT_FILE.read_text(encoding="utf-8")

    # Convert the user's DR code in the existing line to its human-readable class.
    if isinstance(my_dr, (int, float)):
        code = int(my_dr)
        label = DR_LABELS.get(code)
        if label:
            report = re.sub(
                rf"DR rank\s*:\s*(#[^\n]+?)\s*\(DR\s+{code}\)",
                rf"DR {label} rank     : \1",
                report,
            )

    block = [
        "DR LAP-TIME BENCHMARKS - FULL LEADERBOARD",
        "Average qualifying lap time by Driver Rating across the complete current sample.",
    ]
    for dr in sorted(DR_LABELS, reverse=True):
        item = stats[str(dr)]
        block.append(
            f"DR {item['label']:<2} : {item['average_laptime']} average | {item['drivers']:,} drivers"
        )
    block_text = "\n".join(block)

    # Replace an existing block if this step is ever run twice.
    report = re.sub(
        r"\nDR LAP-TIME BENCHMARKS - FULL LEADERBOARD\n.*?(?=\n\n[A-Z][A-Z &/0-9-]+\n|\Z)",
        "",
        report,
        flags=re.DOTALL,
    )

    marker = "\nWORLD RECORD & BENCHMARKS\n"
    if marker in report:
        report = report.replace(marker, "\n" + block_text + "\n\nWORLD RECORD & BENCHMARKS\n", 1)
    else:
        report = report.rstrip() + "\n\n" + block_text + "\n"

    REPORT_FILE.write_text(report, encoding="utf-8")
    print("DR analysis appended to final report.")
    print(f"Leaderboard entries sampled: {sum(len(v) for v in groups.values()):,}")
    for dr in sorted(DR_LABELS, reverse=True):
        item = stats[str(dr)]
        print(f"DR {item['label']}: {item['average_laptime']} | n={item['drivers']:,}")


if __name__ == "__main__":
    main()
