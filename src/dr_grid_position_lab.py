from __future__ import annotations

import base64
import json
import math
import random
import statistics
import time
from pathlib import Path
from statistics import NormalDist
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

SNAPSHOT_FILE = Path("data/latest_snapshot.json")
OUT_JSON = Path("data/dr_grid_position_lab.json")
OUT_TXT = Path("reports/dr_grid_position_lab.txt")

PSN_ID = "crazy_rooster74"
SAMPLE_SIZE = 120
MIN_LOCAL_N = 30
START_WINDOW = 10.0
MAX_WINDOW = 35.0
WINDOW_STEP = 5.0
GRID_SIZE = 16
BOOTSTRAPS = 3000
DR_LABELS = {1: "E", 2: "D", 3: "C", 4: "B", 5: "A", 6: "A+", 7: "S"}


def score_to_laptime(score):
    if not isinstance(score, (int, float)):
        return "N/A"
    score = int(round(score))
    return f"{score // 60000}:{(score % 60000) // 1000:02d}.{score % 1000:03d}"


def xor_decrypt(data: bytes, key: str) -> str:
    key_bytes = key.encode("utf-8")
    decoded = bytes(b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(data))
    return decoded.decode("utf-8")


def gtsh_profile(session, psn_id):
    url = f"https://gtsh-rank.com/profile/?id={quote(psn_id)}"
    try:
        page = session.get(url, timeout=30)
        page.raise_for_status()
        soup = BeautifulSoup(page.text, "html.parser")
        body = soup.find("body")
        key = body.get("header") if body else None
        if not key:
            return None
        response = session.post(
            url,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": url,
                "Origin": "https://gtsh-rank.com",
                "Accept": "application/json,text/plain,*/*",
            },
            data={"psnid": psn_id},
            timeout=60,
        )
        response.raise_for_status()
        wrapper = response.json()
        encrypted = wrapper.get("data") if isinstance(wrapper, dict) else None
        if not isinstance(encrypted, str):
            return None
        payload = json.loads(xor_decrypt(base64.b64decode(encrypted), key))
        user = payload.get("monthly_stats", {}).get("result", {}).get("user")
        if not isinstance(user, dict):
            return None
        pct = user.get("dr_percentage")
        dr = user.get("driver_rating")
        points = user.get("dr_points")
        if not isinstance(pct, (int, float)) or not isinstance(dr, (int, float)):
            return None
        return {
            "psn_id": user.get("np_online_id") or psn_id,
            "driver_rating": int(dr),
            "dr_percentage": float(pct),
            "dr_points": points,
        }
    except Exception:
        return None


def leaderboard_entries(session, url):
    all_entries = []
    seen = set()
    offset = 0
    limit = 1000
    server_total = None
    for _ in range(1000):
        sep = "&" if "?" in url else "?"
        response = session.get(f"{url}{sep}page_data=1&offset={offset}&limit={limit}", timeout=60)
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
                if rank in seen:
                    continue
                seen.add(rank)
            all_entries.append(entry)
            added += 1
        if added == 0:
            break
        if server_total is not None and len(seen) >= server_total:
            break
        offset += len(entries)
    return all_entries


def stratified_sample(items, n):
    if len(items) <= n:
        return items[:]
    result = []
    for i in range(n):
        idx = round(i * (len(items) - 1) / (n - 1))
        result.append(items[idx])
    return result


def ols(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    xbar = statistics.mean(xs)
    ybar = statistics.mean(ys)
    sxx = sum((x - xbar) ** 2 for x in xs)
    if sxx <= 0:
        return None
    beta = sum((x - xbar) * (y - ybar) for x, y in points) / sxx
    alpha = ybar - beta * xbar
    fitted = [alpha + beta * x for x in xs]
    residuals = [y - f for y, f in zip(ys, fitted)]
    sigma = math.sqrt(sum(r * r for r in residuals) / max(1, len(points) - 2))
    syy = sum((y - ybar) ** 2 for y in ys)
    corr = (
        sum((x - xbar) * (y - ybar) for x, y in points) / math.sqrt(sxx * syy)
        if syy > 0 else 0.0
    )
    return alpha, beta, sigma, corr


def median_abs_deviation(values):
    if not values:
        return None
    med = statistics.median(values)
    return statistics.median([abs(x - med) for x in values])


def robust_filter(observations):
    if len(observations) < 8:
        return observations[:], 0
    scores = [o["score"] for o in observations]
    med = statistics.median(scores)
    mad = median_abs_deviation(scores)
    if not mad or mad <= 0:
        return observations[:], 0
    robust_sigma = 1.4826 * mad
    kept = [o for o in observations if abs(o["score"] - med) <= 3.5 * robust_sigma]
    return kept, len(observations) - len(kept)


def adaptive_local(observations, my_pct):
    window = START_WINDOW
    selected = []
    while window <= MAX_WINDOW:
        selected = [o for o in observations if abs(o["dr_percentage"] - my_pct) <= window]
        if len(selected) >= MIN_LOCAL_N:
            break
        window += WINDOW_STEP
    if len(selected) < MIN_LOCAL_N:
        selected = sorted(observations, key=lambda o: abs(o["dr_percentage"] - my_pct))[:MIN_LOCAL_N]
        window = max((abs(o["dr_percentage"] - my_pct) for o in selected), default=MAX_WINDOW)
    return selected, window


def empirical_faster_probability(local, my_score):
    if not local:
        return None
    faster = sum(1 for o in local if o["score"] < my_score)
    equal = sum(1 for o in local if o["score"] == my_score)
    return (faster + 0.5 * equal) / len(local)


def grid_position(q, grid_size=GRID_SIZE):
    return 1.0 + (grid_size - 1) * q


def bootstrap_empirical_range(local, my_score, iterations=BOOTSTRAPS):
    if len(local) < 5:
        return None
    rng = random.Random(20260820)
    positions = []
    n = len(local)
    for _ in range(iterations):
        sample = [local[rng.randrange(n)] for _ in range(n)]
        q = empirical_faster_probability(sample, my_score)
        positions.append(grid_position(q))
    positions.sort()
    lo = positions[int(0.10 * (len(positions) - 1))]
    hi = positions[int(0.90 * (len(positions) - 1))]
    return [lo, hi]


def main():
    if not SNAPSHOT_FILE.exists():
        raise RuntimeError("Run the Daily Race C agent first.")

    snapshot = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    leaderboard_url = snapshot.get("race", {}).get("leaderboard_url")
    my_result = snapshot.get("my_result") or {}
    my_score = my_result.get("score")
    my_dr = my_result.get("driver_rating")
    dr_profile = snapshot.get("dr_profile") or {}
    my_pct = dr_profile.get("dr_percentage")

    if not leaderboard_url or not isinstance(my_score, (int, float)) or not isinstance(my_dr, (int, float)):
        raise RuntimeError("Current leaderboard/user data are incomplete.")
    if not isinstance(my_pct, (int, float)):
        raise RuntimeError("Current DR percentage is missing.")

    my_dr = int(my_dr)
    my_pct = float(my_pct)
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (GT7 DR Grid Position Lab V0.2)"})

    entries = leaderboard_entries(session, leaderboard_url)
    same_dr = []
    for entry in entries:
        user = entry.get("user") or {}
        dr = user.get("driver_rating")
        score = entry.get("score")
        psn = user.get("np_online_id")
        if isinstance(dr, (int, float)) and int(dr) == my_dr:
            if isinstance(score, (int, float)) and isinstance(psn, str) and psn:
                same_dr.append({"psn_id": psn, "score": float(score), "rank": entry.get("display_rank")})

    same_dr.sort(key=lambda x: x["score"])
    sampled = stratified_sample(same_dr, SAMPLE_SIZE)

    observations = []
    for i, item in enumerate(sampled, start=1):
        profile = gtsh_profile(session, item["psn_id"])
        if profile and profile["driver_rating"] == my_dr:
            observations.append({**item, "dr_percentage": profile["dr_percentage"], "dr_points": profile.get("dr_points")})
        print(f"Profile {i}/{len(sampled)} | valid={len(observations)}")
        time.sleep(0.08)

    clean, removed_outliers = robust_filter(observations)
    points = [(o["dr_percentage"], o["score"]) for o in clean]
    model = ols(points) if len(points) >= 12 else None

    all_same_scores = [x["score"] for x in same_dr]
    dr_mean = statistics.mean(all_same_scores) if all_same_scores else None
    dr_sd = statistics.pstdev(all_same_scores) if len(all_same_scores) >= 2 else None
    dr_median = statistics.median(all_same_scores) if all_same_scores else None
    dr_mad = median_abs_deviation(all_same_scores) if all_same_scores else None

    local, adaptive_window = adaptive_local(clean, my_pct) if clean else ([], START_WINDOW)
    local_scores = [o["score"] for o in local]
    local_median = statistics.median(local_scores) if local_scores else None
    local_mad = median_abs_deviation(local_scores) if local_scores else None
    local_iqr = None
    if len(local_scores) >= 4:
        qs = statistics.quantiles(local_scores, n=4, method="inclusive")
        local_iqr = qs[2] - qs[0]

    empirical_q = empirical_faster_probability(local, float(my_score)) if local else None
    empirical_pos = grid_position(empirical_q) if empirical_q is not None else None
    empirical_range = bootstrap_empirical_range(local, float(my_score)) if local else None

    regression = None
    if model:
        alpha, beta, residual_sd, corr = model
        mu = alpha + beta * my_pct
        robust_local_sigma = None
        if local_mad and local_mad > 0:
            robust_local_sigma = 1.4826 * local_mad
        sigma = max(750.0, robust_local_sigma or residual_sd)
        z = (float(my_score) - mu) / sigma
        q = NormalDist().cdf(z)
        regression = {
            "alpha_ms": alpha,
            "beta_ms_per_dr_pct": beta,
            "correlation": corr,
            "residual_sd_ms": residual_sd,
            "expected_peer_mean_ms": mu,
            "expected_peer_mean_laptime": score_to_laptime(mu),
            "sigma_used_ms": sigma,
            "z": z,
            "faster_probability": q,
            "expected_grid_position": grid_position(q),
            "hypothesis_direction_supported": beta < 0,
        }

    hybrid = None
    if empirical_q is not None and regression:
        # Empirical neighborhood gets most weight; regression contributes only as a smoothing prior.
        sample_weight = min(0.85, 0.55 + 0.01 * min(len(local), 30))
        corr_strength = min(1.0, abs(regression["correlation"]) / 0.35)
        empirical_weight = min(0.90, sample_weight + 0.10 * (1.0 - corr_strength))
        regression_weight = 1.0 - empirical_weight
        q = empirical_weight * empirical_q + regression_weight * regression["faster_probability"]
        hybrid = {
            "empirical_weight": empirical_weight,
            "regression_weight": regression_weight,
            "faster_probability": q,
            "expected_grid_position": grid_position(q),
        }

    output = {
        "status": "STUDY_ONLY",
        "version": "0.2",
        "production_modified": False,
        "my_dr": my_dr,
        "my_dr_label": DR_LABELS.get(my_dr),
        "my_dr_percentage": my_pct,
        "my_score": my_score,
        "same_dr_leaderboard_n": len(same_dr),
        "requested_profile_sample": len(sampled),
        "valid_profile_sample": len(observations),
        "clean_profile_sample": len(clean),
        "outliers_removed": removed_outliers,
        "dr_full_mean_ms": dr_mean,
        "dr_full_sd_ms": dr_sd,
        "dr_full_median_ms": dr_median,
        "dr_full_mad_ms": dr_mad,
        "adaptive_local": {
            "window_pct": adaptive_window,
            "n": len(local),
            "median_ms": local_median,
            "mad_ms": local_mad,
            "iqr_ms": local_iqr,
        },
        "empirical_model": {
            "faster_probability": empirical_q,
            "expected_grid_position": empirical_pos,
            "bootstrap_80pct_range": empirical_range,
        } if empirical_q is not None else None,
        "regression_model": regression,
        "hybrid_model": hybrid,
        "observations": observations,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_TXT.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "GT7 DR GRID POSITION LAB V0.2",
        "=" * 100,
        "Status: STUDY ONLY - production report formula not modified.",
        f"Driver: {PSN_ID} | DR {DR_LABELS.get(my_dr)} | DR progress {my_pct:.0f}%",
        f"Your qualifying time: {score_to_laptime(my_score)}",
        f"Same-DR leaderboard population: {len(same_dr):,}",
        f"GTSH profiles: {len(observations)} valid of {len(sampled)} requested | clean={len(clean)} | outliers removed={removed_outliers}",
        f"Full DR mean: {score_to_laptime(dr_mean)} | SD {dr_sd/1000:.3f}s" if dr_sd is not None else "Full DR mean/SD unavailable",
        f"Full DR median: {score_to_laptime(dr_median)} | MAD {dr_mad/1000:.3f}s" if dr_mad is not None else "Full DR median/MAD unavailable",
        "",
        "ADAPTIVE LOCAL PEER SET",
        f"Window around your DR%: +/-{adaptive_window:.1f} points",
        f"Peer sample: n={len(local)}",
        f"Peer median: {score_to_laptime(local_median)}" if local_median is not None else "Peer median: N/A",
        f"Peer MAD: {local_mad/1000:.3f}s" if local_mad is not None else "Peer MAD: N/A",
        f"Peer IQR: {local_iqr/1000:.3f}s" if local_iqr is not None else "Peer IQR: N/A",
        "",
        "MODEL 1 - EMPIRICAL LOCAL PERCENTILE",
    ]

    if empirical_q is not None:
        lines.extend([
            f"Similar-DR peers faster than you: {100*empirical_q:.1f}%",
            f"Expected grid position: P{empirical_pos:.1f} of {GRID_SIZE}",
            f"Bootstrap 80% range: P{empirical_range[0]:.1f} to P{empirical_range[1]:.1f}" if empirical_range else "Bootstrap range unavailable",
        ])
    else:
        lines.append("Insufficient local sample.")

    lines.extend(["", "MODEL 2 - ROBUST REGRESSION / NORMAL"])
    if regression:
        lines.extend([
            f"beta: {regression['beta_ms_per_dr_pct']:.2f} ms per DR percentage point",
            f"correlation: {regression['correlation']:.3f}",
            f"higher DR% -> faster supported: {'YES' if regression['hypothesis_direction_supported'] else 'NO'}",
            f"Expected peer mean at DR {my_pct:.0f}%: {regression['expected_peer_mean_laptime']}",
            f"Similar-DR peer faster probability: {100*regression['faster_probability']:.1f}%",
            f"Expected grid position: P{regression['expected_grid_position']:.1f} of {GRID_SIZE}",
        ])
    else:
        lines.append("Insufficient clean sample for regression.")

    lines.extend(["", "MODEL 3 - HYBRID"])
    if hybrid:
        lines.extend([
            f"Weights: empirical {100*hybrid['empirical_weight']:.0f}% | regression {100*hybrid['regression_weight']:.0f}%",
            f"Similar-DR peer faster probability: {100*hybrid['faster_probability']:.1f}%",
            f"Expected grid position: P{hybrid['expected_grid_position']:.1f} of {GRID_SIZE}",
        ])
    else:
        lines.append("Hybrid unavailable.")

    lines.extend([
        "",
        "DECISION RULE",
        f"Primary candidate is empirical local percentile if peer n >= {MIN_LOCAL_N}; hybrid is the smoothing fallback.",
        "Regression is diagnostic and should not be the primary production estimator unless the DR%-pace relationship strengthens materially.",
    ])

    OUT_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"Saved: {OUT_JSON}")
    print(f"Saved: {OUT_TXT}")


if __name__ == "__main__":
    main()
