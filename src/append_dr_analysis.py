from __future__ import annotations

import base64
import json
import re
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SNAPSHOT_FILE = Path("data/latest_snapshot.json")
REPORT_FILE = Path("reports/latest.txt")
DR_HISTORY_FILE = Path("data/dr_progress_history.json")

PSN_ID = "crazy_rooster74"
GTSH_PROFILE_URL = f"https://gtsh-rank.com/profile/?id={PSN_ID}"
DR_LABELS = {1: "E", 2: "D", 3: "C", 4: "B", 5: "A", 6: "A+", 7: "S"}


def score_to_laptime(score):
    if not isinstance(score, (int, float)):
        return "N/A"
    score = int(round(score))
    return f"{score // 60000}:{(score % 60000) // 1000:02d}.{score % 1000:03d}"


def seconds_text(ms):
    if not isinstance(ms, (int, float)):
        return "N/A"
    return f"{ms / 1000:.3f}s"


def xor_decrypt(data: bytes, key: str) -> str:
    key_bytes = key.encode("utf-8")
    decoded = bytes(b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(data))
    return decoded.decode("utf-8")


def robust_clean_scores(scores):
    """Remove only extreme lap-time outliers using a conservative MAD fence.

    The Daily C report keeps the same compact format; diagnostics stay in the
    snapshot only. A 5-sigma robust fence is deliberately conservative so
    legitimate slow laps remain in the DR distribution while pathological
    entries no longer dominate mean/SD.
    """
    values = [float(x) for x in scores if isinstance(x, (int, float))]
    if len(values) < 12:
        return values, {
            "raw_n": len(values),
            "clean_n": len(values),
            "excluded_n": 0,
            "median_ms": statistics.median(values) if values else None,
            "mad_ms": None,
            "lower_fence_ms": None,
            "upper_fence_ms": None,
        }

    median = statistics.median(values)
    abs_dev = [abs(x - median) for x in values]
    mad = statistics.median(abs_dev)

    if not mad or mad <= 0:
        return values, {
            "raw_n": len(values),
            "clean_n": len(values),
            "excluded_n": 0,
            "median_ms": median,
            "mad_ms": mad,
            "lower_fence_ms": None,
            "upper_fence_ms": None,
        }

    robust_sigma = 1.4826 * mad
    lower = median - 5.0 * robust_sigma
    upper = median + 5.0 * robust_sigma
    clean = [x for x in values if lower <= x <= upper]

    # Safety valve: never let the robust filter discard an implausibly large
    # fraction of a DR group. If that happens, retain the raw distribution.
    if len(clean) < 0.90 * len(values):
        clean = values
        lower = None
        upper = None

    return clean, {
        "raw_n": len(values),
        "clean_n": len(clean),
        "excluded_n": len(values) - len(clean),
        "median_ms": median,
        "mad_ms": mad,
        "lower_fence_ms": lower,
        "upper_fence_ms": upper,
    }


def fetch_gtsh_dr_profile(session):
    try:
        page = session.get(GTSH_PROFILE_URL, timeout=30)
        page.raise_for_status()
        soup = BeautifulSoup(page.text, "html.parser")
        body = soup.find("body")
        key = body.get("header") if body else None
        if not key:
            return None

        response = session.post(
            GTSH_PROFILE_URL,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": GTSH_PROFILE_URL,
                "Origin": "https://gtsh-rank.com",
                "Accept": "application/json,text/plain,*/*",
            },
            data={"psnid": PSN_ID},
            timeout=60,
        )
        response.raise_for_status()
        wrapper = response.json()
        encrypted = wrapper.get("data") if isinstance(wrapper, dict) else None
        if not isinstance(encrypted, str):
            return None

        payload = json.loads(xor_decrypt(base64.b64decode(encrypted), key))
        user = (
            payload.get("monthly_stats", {})
            .get("result", {})
            .get("user")
        )
        if not isinstance(user, dict):
            return None

        dr_code = user.get("driver_rating")
        dr_code = int(dr_code) if isinstance(dr_code, (int, float)) else None
        return {
            "psn_id": user.get("np_online_id") or PSN_ID,
            "driver_rating": dr_code,
            "dr_label": user.get("dr_level") or DR_LABELS.get(dr_code),
            "dr_points": user.get("dr_points"),
            "dr_percentage": user.get("dr_percentage"),
            "sportsmanship_rating": user.get("sportsmanship_rating"),
            "source": "GTSH public profile",
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        print(f"GTSH DR profile unavailable: {exc}")
        return None


def update_dr_history(profile):
    if not profile:
        return
    history = []
    if DR_HISTORY_FILE.exists():
        try:
            loaded = json.loads(DR_HISTORY_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                history = loaded
        except Exception:
            history = []

    entry = {
        "captured_at": profile.get("captured_at"),
        "driver_rating": profile.get("driver_rating"),
        "dr_label": profile.get("dr_label"),
        "dr_points": profile.get("dr_points"),
        "dr_percentage": profile.get("dr_percentage"),
    }
    history.append(entry)
    history = history[-500:]
    DR_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    DR_HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    if not SNAPSHOT_FILE.exists() or not REPORT_FILE.exists():
        raise RuntimeError("Required snapshot/report not found")

    snapshot = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    race = snapshot.get("race", {})
    leaderboard_url = race.get("leaderboard_url")
    if not leaderboard_url:
        raise RuntimeError("Leaderboard URL missing from latest snapshot")

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
        raw_scores = groups.get(dr, [])
        scores, diagnostics = robust_clean_scores(raw_scores)
        mean = statistics.mean(scores) if scores else None
        std = statistics.pstdev(scores) if len(scores) >= 2 else None
        stats[str(dr)] = {
            "dr": dr,
            "label": DR_LABELS[dr],
            "drivers": len(scores),
            "average_score": mean,
            "average_laptime": score_to_laptime(mean) if mean is not None else "N/A",
            "stddev_ms": std,
            "stddev_seconds": (std / 1000) if std is not None else None,
            "diagnostics": diagnostics,
        }

    dr_profile = fetch_gtsh_dr_profile(session)
    if dr_profile:
        snapshot["dr_profile"] = dr_profile
        update_dr_history(dr_profile)

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

    if isinstance(my_dr, (int, float)):
        code = int(my_dr)
        label = DR_LABELS.get(code)
        if label:
            report = re.sub(
                rf"DR rank\s*:\s*(#[^\n]+?)\s*\(DR\s+{code}\)",
                rf"DR {label} rank     : \1",
                report,
            )

    if dr_profile:
        progress_line = (
            f"DR progress      : DR {dr_profile.get('dr_label')} | "
            f"{dr_profile.get('dr_points'):,} pts | "
            f"{dr_profile.get('dr_percentage')}% toward next DR"
            if isinstance(dr_profile.get("dr_points"), (int, float))
            else f"DR progress      : DR {dr_profile.get('dr_label')} | {dr_profile.get('dr_percentage')}% toward next DR"
        )
        if "DR progress      :" in report:
            report = re.sub(r"^DR progress\s*:.*$", progress_line, report, flags=re.MULTILINE)
        else:
            match = re.search(r"^DR [A-Z+]+ rank\s*:.*$", report, flags=re.MULTILINE)
            if match:
                insert_at = match.end()
                report = report[:insert_at] + "\n" + progress_line + report[insert_at:]

    block = [
        "DR LAP-TIME BENCHMARKS - FULL LEADERBOARD",
        "Average qualifying lap time and population standard deviation by Driver Rating.",
    ]
    for dr in sorted(DR_LABELS, reverse=True):
        item = stats[str(dr)]
        block.append(
            f"DR {item['label']:<2} : {item['average_laptime']} average | "
            f"SD {seconds_text(item['stddev_ms'])} | {item['drivers']:,} drivers"
        )
    block_text = "\n".join(block)

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
    if dr_profile:
        print(
            f"DR profile: {dr_profile.get('dr_label')} | {dr_profile.get('dr_points')} pts | "
            f"{dr_profile.get('dr_percentage')}%"
        )
    print(f"Leaderboard entries sampled: {sum(len(v) for v in groups.values()):,}")
    for dr in sorted(DR_LABELS, reverse=True):
        item = stats[str(dr)]
        print(
            f"DR {item['label']}: {item['average_laptime']} | "
            f"SD {seconds_text(item['stddev_ms'])} | n={item['drivers']:,}"
        )


if __name__ == "__main__":
    main()
