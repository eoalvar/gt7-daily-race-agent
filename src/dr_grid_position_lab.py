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
TARGET_VALID = 100
MAX_PROFILE_ATTEMPTS = 600
MIN_LOCAL_N = 30
START_WINDOW = 5.0
MAX_WINDOW = 20.0
WINDOW_STEP = 2.5
GRID_SIZE = 16
BOOTSTRAPS = 5000
SLEEP_BETWEEN_PROFILES = 0.06
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


def prioritized_candidates(same_dr, my_score):
    """Probe likely peers first, then expand outwards through the DR population.

    Leaderboard position is not the target variable, but qualifying-time proximity increases
    the chance of collecting a dense local competitive sample before broadening coverage.
    """
    if not same_dr:
        return []

    by_distance = sorted(same_dr, key=lambda x: abs(x["score"] - my_score))
    selected = []
    seen = set()

    # First 250 closest in qualifying pace.
    for item in by_distance[:250]:
        key = item["psn_id"].lower()
        if key not in seen:
            seen.add(key)
            selected.append(item)

    # Then interleave the full DR distribution to prevent local pace-selection bias.
    n = len(same_dr)
    stride_count = min(n, MAX_PROFILE_ATTEMPTS)
    if stride_count > 1:
        for i in range(stride_count):
            idx = round(i * (n - 1) / (stride_count - 1))
            item = same_dr[idx]
            key = item["psn_id"].lower()
            if key not in seen:
                seen.add(key)
                selected.append(item)

    # Finally fill remaining attempts from the full sorted population.
    for item in same_dr:
        if len(selected) >= MAX_PROFILE_ATTEMPTS:
            break
        key = item["psn_id"].lower()
        if key not in seen:
            seen.add(key)
            selected.append(item)

    return selected[:MAX_PROFILE_ATTEMPTS]


def choose_local(clean, my_pct):
    for window in [5.0, 7.5, 10.0, 12.5, 15.0, 17.5, 20.0]:
        local = [o for o in clean if abs(o["dr_percentage"] - my_pct) <= window]
        if len(local) >= MIN_LOCAL_N:
            return local, window, "fixed_window"

    # If the GTSH hit rate still prevents 30 observations inside +/-20, use nearest neighbors.
    nearest = sorted(clean, key=lambda o: abs(o["dr_percentage"] - my_pct))[:MIN_LOCAL_N]
    effective_window = max((abs(o["dr_percentage"] - my_pct) for o in nearest), default=None)
    return nearest, effective_window, "nearest_30_fallback"


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
    my_score = float(my_score)

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (GT7 DR Grid Position Lab V0.3)"})

    entries = leaderboard_entries(session, leaderboard_url)
    same_dr = []
    for entry in entries:
        user = entry.get("user") or {}
        dr = user.get("driver_rating")
        score = entry.get("score")
        psn = user.get("np_online_id")
        if isinstance(dr, (int, float)) and int(dr) == my_dr:
            if isinstance(score, (int, float)) and isinstance(psn, str) and psn:
                same_dr.append({
                    "psn_id": psn,
                    "score": float(score),
                    "rank": entry.get("display_rank"),
                })

    same_dr.sort(key=lambda x: x["score"])
    candidates = prioritized_candidates(same_dr, my_score)

    observations = []
    attempts = 0
    failures = 0
    for item in candidates:
        if len(observations) >= TARGET_VALID:
            break
        attempts += 1
        profile = gtsh_profile(session, item["psn_id"])
        if profile and profile["driver_rating"] == my_dr:
            observations.append({
                **item,
                "dr_percentage": profile["dr_percentage"],
                "dr_points": profile.get("dr_points"),
            })
        else:
            failures += 1
        print(f"Profile {attempts}/{len(candidates)} | valid={len(observations)}/{TARGET_VALID} | failures={failures}")
        time.sleep(SLEEP_BETWEEN_PROFILES)

    clean, removed_outliers = robust_filter(observations)
    points = [(o["dr_percentage"], o["score"]) for o in clean]
    model = ols(points) if len(points) >= 12 else None

    all_same_scores = [x["score"] for x in same_dr]
    dr_mean = statistics.mean(all_same_scores) if all_same_scores else None
    dr_sd = statistics.pstdev(all_same_scores) if len(all_same_scores) >= 2 else None
    dr_median = statistics.median(all_same_scores) if all_same_scores else None
    dr_mad = median_abs_deviation(all_same_scores) if all_same_scores else None

    local, effective_window, local_method = choose_local(clean, my_pct) if clean else ([], None, "none")
    local_scores = [o["score"] for o in local]
    local_median = statistics.median(local_scores) if local_scores else None
    local_mean = statistics.mean(local_scores) if local_scores else None
    local_mad = median_abs_deviation(local_scores) if local_scores else None
    local_sd = statistics.pstdev(local_scores) if len(local_scores) >= 2 else None
    local_iqr = None
    if len(local_scores) >= 4:
        qs = statistics.quantiles(local_scores, n=4, method="inclusive")
        local_iqr = qs[2] - qs[0]

    empirical_q = empirical_faster_probability(local, my_score) if local else None
    empirical_pos = grid_position(empirical_q) if empirical_q is not None else None
    empirical_range = bootstrap_empirical_range(local, my_score) if local else None

    regression = None
    if model:
        alpha, beta, residual_sd, corr = model
        mu = alpha + beta * my_pct
        robust_local_sigma = 1.4826 * local_mad if local_mad and local_mad > 0 else None
        sigma = max(750.0, robust_local_sigma or residual_sd)
        z = (my_score - mu) / sigma
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
        # Empirical result dominates once a genuine local set reaches 30+ drivers.
        if len(local) >= 50 and local_method == "fixed_window":
            empirical_weight = 0.90
        elif len(local) >= 30 and local_method == "fixed_window":
            empirical_weight = 0.85
        else:
            empirical_weight = 0.75
        regression_weight = 1.0 - empirical_weight
        q = empirical_weight * empirical_q + regression_weight * regression["faster_probability"]
        hybrid = {
            "empirical_weight": empirical_weight,
            "regression_weight": regression_weight,
            "faster_probability": q,
            "expected_grid_position": grid_position(q),
        }

    production_ready = (
        len(local) >= 30
        and local_method == "fixed_window"
        and effective_window is not None
        and effective_window <= 10.0
        and empirical_range is not None
    )

    output = {
        "status": "STUDY_ONLY",
        "version": "0.3",
        "production_modified": False,
        "production_ready": production_ready,
        "my_dr": my_dr,
        "my_dr_label": DR_LABELS.get(my_dr),
        "my_dr_percentage": my_pct,
        "my_score": my_score,
        "same_dr_leaderboard_n": len(same_dr),
        "profile_target_valid": TARGET_VALID,
        "profile_max_attempts": MAX_PROFILE_ATTEMPTS,
        "profile_attempts": attempts,
        "valid_profile_sample": len(observations),
        "profile_failures": failures,
        "clean_profile_sample": len(clean),
        "outliers_removed": removed_outliers,
        "dr_full_mean_ms": dr_mean,
        "dr_full_sd_ms": dr_sd,
        "dr_full_median_ms": dr_median,
        "dr_full_mad_ms": dr_mad,
        "local_peer_set": {
            "selection_method": local_method,
            "window_pct": effective_window,
            "n": len(local),
            "mean_ms": local_mean,
            "median_ms": local_median,
            "sd_ms": local_sd,
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
        "GT7 DR GRID POSITION LAB V0.3",
        "=" * 104,
        "Status: STUDY ONLY - production report formula not modified.",
        f"Driver: {PSN_ID} | DR {DR_LABELS.get(my_dr)} | DR progress {my_pct:.0f}%",
        f"Your qualifying time: {score_to_laptime(my_score)}",
        f"Same-DR leaderboard population: {len(same_dr):,}",
        f"GTSH collection: {len(observations)} valid | {attempts} attempts | target {TARGET_VALID} | max {MAX_PROFILE_ATTEMPTS}",
        f"Clean sample: {len(clean)} | outliers removed: {removed_outliers}",
        f"Full DR mean: {score_to_laptime(dr_mean)} | SD {dr_sd/1000:.3f}s" if dr_sd is not None else "Full DR stats unavailable",
        f"Full DR median: {score_to_laptime(dr_median)} | MAD {dr_mad/1000:.3f}s" if dr_mad is not None else "Full DR robust stats unavailable",
        "",
        "LOCAL PEER SET",
        f"Method: {local_method}",
        f"Effective DR% window: +/-{effective_window:.1f}" if effective_window is not None else "Effective DR% window: N/A",
        f"Peer sample: n={len(local)}",
        f"Peer mean: {score_to_laptime(local_mean)} | SD {local_sd/1000:.3f}s" if local_sd is not None else "Peer mean/SD: N/A",
        f"Peer median: {score_to_laptime(local_median)} | MAD {local_mad/1000:.3f}s" if local_mad is not None else "Peer median/MAD: N/A",
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
        lines.append("Unavailable")

    lines.extend(["", "MODEL 2 - REGRESSION / NORMAL DIAGNOSTIC"])
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
        lines.append("Unavailable")

    lines.extend(["", "MODEL 3 - HYBRID"])
    if hybrid:
        lines.extend([
            f"Weights: empirical {100*hybrid['empirical_weight']:.0f}% | regression {100*hybrid['regression_weight']:.0f}%",
            f"Similar-DR peer faster probability: {100*hybrid['faster_probability']:.1f}%",
            f"Expected grid position: P{hybrid['expected_grid_position']:.1f} of {GRID_SIZE}",
        ])
    else:
        lines.append("Unavailable")

    lines.extend([
        "",
        "PRODUCTION READINESS",
        f"Ready: {'YES' if production_ready else 'NO'}",
        "Criteria: >=30 clean peers inside a true fixed DR% window of +/-10 or narrower, plus bootstrap interval.",
        "Primary estimator if ready: empirical local percentile. Hybrid remains secondary diagnostic.",
    ])

    OUT_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"Saved: {OUT_JSON}")
    print(f"Saved: {OUT_TXT}")


if __name__ == "__main__":
    main()
