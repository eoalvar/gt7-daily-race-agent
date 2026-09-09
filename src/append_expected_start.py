from __future__ import annotations

import json
import math
import re
import statistics
from pathlib import Path

import requests

SNAPSHOT_FILE = Path("data/latest_snapshot.json")
REPORT_FILE = Path("reports/latest.txt")
CACHE_FILE = Path(".cache/current_leaderboard.json")
GRID_SIZE = 16
DR_LABELS = {1: "E", 2: "D", 3: "C", 4: "B", 5: "A", 6: "A+", 7: "S"}


def cached_leaderboard_entries(url: str):
    if not CACHE_FILE.exists():
        return None
    try:
        cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        entries = cache.get("entries")
        if cache.get("leaderboard_url") == url and isinstance(entries, list) and len(entries) >= 1000:
            print(f"Expected-start using shared runtime leaderboard cache: {len(entries):,} entries")
            return entries
    except Exception as exc:
        print(f"Shared leaderboard cache unavailable for expected start: {exc}")
    return None


def leaderboard_entries(session: requests.Session, url: str):
    cached = cached_leaderboard_entries(url)
    if cached is not None:
        return cached

    result = []
    seen = set()
    offset = 0
    limit = 1000
    total = None
    for _ in range(1000):
        sep = "&" if "?" in url else "?"
        r = session.get(f"{url}{sep}page_data=1&offset={offset}&limit={limit}", timeout=60)
        r.raise_for_status()
        payload = r.json()
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
                    total = int(payload[key])
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
                if rank in seen:
                    continue
                seen.add(rank)
            result.append(entry)
            added += 1
        if added == 0:
            break
        if total is not None and len(seen) >= total:
            break
        offset += len(entries)
    return result


def normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def binomial_probabilities(n: int, p: float):
    return [math.comb(n, k) * (p ** k) * ((1.0 - p) ** (n - k)) for k in range(n + 1)]


def binomial_quantile(probs, q: float) -> int:
    cumulative = 0.0
    for k, prob in enumerate(probs):
        cumulative += prob
        if cumulative >= q:
            return k
    return len(probs) - 1


def score_to_laptime(score_ms: float) -> str:
    score = int(round(score_ms))
    return f"{score // 60000}:{(score % 60000) // 1000:02d}.{score % 1000:03d}"


def main():
    snapshot = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    race = snapshot.get("race") or {}
    me = snapshot.get("my_result") or {}

    leaderboard_url = race.get("leaderboard_url")
    my_score = me.get("score")
    my_dr = me.get("driver_rating")

    if not leaderboard_url or not isinstance(my_score, (int, float)) or not isinstance(my_dr, (int, float)):
        print("Expected-start estimate skipped: required data unavailable.")
        return

    my_dr = int(my_dr)
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (GT7 Expected Start Normal Random Grid)"})
    try:
        entries = leaderboard_entries(session, leaderboard_url)
    finally:
        session.close()

    scores = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        user = entry.get("user") or {}
        dr = user.get("driver_rating")
        score = entry.get("score")
        if isinstance(dr, (int, float)) and int(dr) == my_dr and isinstance(score, (int, float)):
            scores.append(float(score))

    if len(scores) < 2:
        print("Expected-start estimate skipped: insufficient same-DR qualifying population.")
        return

    my_score = float(my_score)
    mean_score = statistics.mean(scores)
    std_score = statistics.pstdev(scores)
    if std_score <= 0:
        print("Expected-start estimate skipped: same-DR standard deviation is zero.")
        return

    # Model assumption requested by user:
    # 1) same-DR qualifying lap times follow a Normal(mean, std) distribution;
    # 2) the other 15 drivers in a 16-car lobby are random draws from that same DR;
    # 3) grid order is then determined only by qualifying lap time.
    z_score = (my_score - mean_score) / std_score
    p_random_opponent_faster = normal_cdf(z_score)

    opponents = GRID_SIZE - 1
    expected_faster = opponents * p_random_opponent_faster
    expected_position = 1.0 + expected_faster

    probs = binomial_probabilities(opponents, p_random_opponent_faster)
    most_likely_faster = max(range(len(probs)), key=lambda k: probs[k])
    most_likely_position = 1 + most_likely_faster
    low_position = 1 + binomial_quantile(probs, 0.025)
    high_position = 1 + binomial_quantile(probs, 0.975)

    estimate = {
        "model": "DR_NORMAL_RANDOM_GRID_V1",
        "grid_size": GRID_SIZE,
        "dr": my_dr,
        "dr_label": DR_LABELS.get(my_dr),
        "same_dr_population": len(scores),
        "my_score_ms": my_score,
        "same_dr_mean_ms": mean_score,
        "same_dr_std_ms": std_score,
        "z_score": z_score,
        "probability_random_same_dr_opponent_faster": p_random_opponent_faster,
        "expected_position": expected_position,
        "most_likely_position": most_likely_position,
        "random_grid_interval_95": [low_position, high_position],
        "basis": "Normal distribution fitted from mean/std of same-DR qualifying times; 15 random same-DR opponents",
    }
    snapshot["expected_start"] = estimate
    SNAPSHOT_FILE.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    report = REPORT_FILE.read_text(encoding="utf-8")
    report = re.sub(r"\nEXPECTED START\n.*?(?=\n\n[A-Z][A-Z &/0-9-]+\n|\Z)", "", report, flags=re.DOTALL)
    block = (
        "EXPECTED START\n"
        f"Expected position     : P{expected_position:.1f}\n"
        f"Most likely position  : P{most_likely_position}\n"
        f"95% random-grid range : P{low_position} to P{high_position}\n"
        f"Your qualifying time  : {score_to_laptime(my_score)}\n"
        f"DR {DR_LABELS.get(my_dr)} mean time       : {score_to_laptime(mean_score)}\n"
        f"DR {DR_LABELS.get(my_dr)} std deviation   : {std_score / 1000.0:.3f}s\n"
        f"Z-score               : {z_score:+.2f}\n"
        f"Random opponent faster: {p_random_opponent_faster * 100.0:.1f}%\n"
        f"Population            : {len(scores):,} DR {DR_LABELS.get(my_dr)} drivers\n"
        f"Model                 : Normal lap-time distribution + random {GRID_SIZE}-driver same-DR grid\n"
    )
    marker = "\nDR LAP-TIME BENCHMARKS - FULL LEADERBOARD\n"
    if marker in report:
        report = report.replace(marker, "\n" + block + "\nDR LAP-TIME BENCHMARKS - FULL LEADERBOARD\n", 1)
    else:
        report = report.rstrip() + "\n\n" + block
    REPORT_FILE.write_text(report, encoding="utf-8")

    print(
        f"Expected Start: P{expected_position:.1f} | mode=P{most_likely_position} | "
        f"95% P{low_position}-P{high_position} | DR {DR_LABELS.get(my_dr)} n={len(scores):,} | "
        f"mean={score_to_laptime(mean_score)} | std={std_score / 1000.0:.3f}s | z={z_score:+.2f} | "
        f"random opponent faster={p_random_opponent_faster * 100.0:.1f}%"
    )


if __name__ == "__main__":
    main()
