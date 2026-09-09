from __future__ import annotations

import json
import math
import re
from pathlib import Path

SNAPSHOT_FILE = Path("data/latest_snapshot.json")
REPORT_FILE = Path("reports/latest.txt")
GRID_SIZE = 16
DR_LABELS = {1: "E", 2: "D", 3: "C", 4: "B", 5: "A", 6: "A+", 7: "S"}


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
    me = snapshot.get("my_result") or {}

    my_score = me.get("score")
    my_dr = me.get("driver_rating")
    if not isinstance(my_score, (int, float)) or not isinstance(my_dr, (int, float)):
        print("Expected-start estimate skipped: required driver data unavailable.")
        return

    my_dr = int(my_dr)
    dr_stats_all = snapshot.get("dr_laptime_stats") or {}
    dr_stats = dr_stats_all.get(str(my_dr)) or dr_stats_all.get(my_dr)
    if not isinstance(dr_stats, dict):
        print("Expected-start estimate skipped: DR lap-time benchmark stats unavailable.")
        return

    mean_score = dr_stats.get("average_score")
    std_score = dr_stats.get("stddev_ms")
    population = dr_stats.get("drivers")
    if not isinstance(mean_score, (int, float)) or not isinstance(std_score, (int, float)) or std_score <= 0:
        print("Expected-start estimate skipped: invalid DR mean/std benchmark data.")
        return

    my_score = float(my_score)
    mean_score = float(mean_score)
    std_score = float(std_score)
    population = int(population) if isinstance(population, (int, float)) else None

    # Single source of truth: use exactly the same cleaned DR population,
    # mean and population standard deviation already reported in
    # DR LAP-TIME BENCHMARKS. This avoids a second, inconsistent raw-data fit.
    z_score = (my_score - mean_score) / std_score
    p_random_opponent_faster = normal_cdf(z_score)

    opponents = GRID_SIZE - 1
    expected_position = 1.0 + opponents * p_random_opponent_faster

    probs = binomial_probabilities(opponents, p_random_opponent_faster)
    most_likely_faster = max(range(len(probs)), key=lambda k: probs[k])
    most_likely_position = 1 + most_likely_faster
    low_position = 1 + binomial_quantile(probs, 0.025)
    high_position = 1 + binomial_quantile(probs, 0.975)

    estimate = {
        "model": "DR_NORMAL_RANDOM_GRID_V2",
        "grid_size": GRID_SIZE,
        "dr": my_dr,
        "dr_label": DR_LABELS.get(my_dr),
        "same_dr_population": population,
        "my_score_ms": my_score,
        "same_dr_mean_ms": mean_score,
        "same_dr_std_ms": std_score,
        "z_score": z_score,
        "probability_random_same_dr_opponent_faster": p_random_opponent_faster,
        "expected_position": expected_position,
        "most_likely_position": most_likely_position,
        "random_grid_interval_95": [low_position, high_position],
        "basis": "Normal distribution using the same cleaned DR mean/std shown in DR LAP-TIME BENCHMARKS; 15 random same-DR opponents",
    }
    snapshot["expected_start"] = estimate
    SNAPSHOT_FILE.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    report = REPORT_FILE.read_text(encoding="utf-8")
    report = re.sub(r"\nEXPECTED START\n.*?(?=\n\n[A-Z][A-Z &/0-9-]+\n|\Z)", "", report, flags=re.DOTALL)
    population_text = f"{population:,}" if population is not None else "N/A"
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
        f"Population            : {population_text} DR {DR_LABELS.get(my_dr)} drivers\n"
        f"Model                 : Normal fit from DR benchmark mean/SD + random {GRID_SIZE}-driver same-DR grid\n"
    )
    marker = "\nDR LAP-TIME BENCHMARKS - FULL LEADERBOARD\n"
    if marker in report:
        report = report.replace(marker, "\n" + block + "\nDR LAP-TIME BENCHMARKS - FULL LEADERBOARD\n", 1)
    else:
        report = report.rstrip() + "\n\n" + block
    REPORT_FILE.write_text(report, encoding="utf-8")

    print(
        f"Expected Start: P{expected_position:.1f} | mode=P{most_likely_position} | "
        f"95% P{low_position}-P{high_position} | DR {DR_LABELS.get(my_dr)} n={population_text} | "
        f"mean={score_to_laptime(mean_score)} | std={std_score / 1000.0:.3f}s | z={z_score:+.2f} | "
        f"random opponent faster={p_random_opponent_faster * 100.0:.1f}%"
    )


if __name__ == "__main__":
    main()
