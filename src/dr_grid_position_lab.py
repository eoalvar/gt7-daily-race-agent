from __future__ import annotations

import base64
import json
import math
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
SAMPLE_SIZE = 60
LOCAL_WINDOW = 10.0
GRID_SIZE = 16
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
    r = (
        sum((x - xbar) * (y - ybar) for x, y in points) / math.sqrt(sxx * syy)
        if syy > 0
        else 0.0
    )
    return alpha, beta, sigma, r


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
        raise RuntimeError("Current DR percentage is missing. Run Daily Race C after DR integration first.")

    my_dr = int(my_dr)
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (GT7 DR Grid Position Lab)"})

    entries = leaderboard_entries(session, leaderboard_url)
    same_dr = []
    for entry in entries:
        user = entry.get("user") or {}
        dr = user.get("driver_rating")
        score = entry.get("score")
        psn = user.get("np_online_id")
        if int(dr) == my_dr if isinstance(dr, (int, float)) else False:
            if isinstance(score, (int, float)) and isinstance(psn, str) and psn:
                same_dr.append({"psn_id": psn, "score": float(score), "rank": entry.get("display_rank")})

    same_dr.sort(key=lambda x: x["score"])
    sampled = stratified_sample(same_dr, SAMPLE_SIZE)

    observations = []
    for i, item in enumerate(sampled, start=1):
        profile = gtsh_profile(session, item["psn_id"])
        if profile and profile["driver_rating"] == my_dr:
            observations.append({
                **item,
                "dr_percentage": profile["dr_percentage"],
                "dr_points": profile.get("dr_points"),
            })
        print(f"Profile {i}/{len(sampled)} | valid={len(observations)}")
        time.sleep(0.10)

    points = [(o["dr_percentage"], o["score"]) for o in observations]
    model = ols(points) if len(points) >= 12 else None

    all_same_scores = [x["score"] for x in same_dr]
    dr_mean = statistics.mean(all_same_scores) if all_same_scores else None
    dr_sd = statistics.pstdev(all_same_scores) if len(all_same_scores) >= 2 else None

    theoretical_mu = None
    if dr_mean is not None and dr_sd is not None:
        q = min(0.999, max(0.001, 1.0 - float(my_pct) / 100.0))
        theoretical_mu = dr_mean + dr_sd * NormalDist().inv_cdf(q)

    estimate = None
    if model:
        alpha, beta, residual_sd, corr = model
        mu = alpha + beta * float(my_pct)
        local = [o["score"] for o in observations if abs(o["dr_percentage"] - float(my_pct)) <= LOCAL_WINDOW]
        local_sd = statistics.pstdev(local) if len(local) >= 10 else residual_sd
        local_mean_observed = statistics.mean(local) if local else None
        sigma = max(1.0, local_sd)
        z = (float(my_score) - mu) / sigma
        faster_probability = NormalDist().cdf(z)
        expected_position = 1.0 + (GRID_SIZE - 1) * faster_probability
        pos_sd = math.sqrt((GRID_SIZE - 1) * faster_probability * (1.0 - faster_probability))
        low = max(1.0, expected_position - 1.28 * pos_sd)
        high = min(float(GRID_SIZE), expected_position + 1.28 * pos_sd)
        estimate = {
            "alpha_ms": alpha,
            "beta_ms_per_dr_pct": beta,
            "correlation": corr,
            "regression_residual_sd_ms": residual_sd,
            "my_dr_percentage": my_pct,
            "expected_peer_mean_ms": mu,
            "expected_peer_mean_laptime": score_to_laptime(mu),
            "local_window_pct": LOCAL_WINDOW,
            "local_sample_n": len(local),
            "local_observed_mean_ms": local_mean_observed,
            "local_sd_ms": local_sd,
            "my_score": my_score,
            "my_laptime": score_to_laptime(my_score),
            "z_vs_similar_dr": z,
            "probability_random_peer_faster": faster_probability,
            "grid_size": GRID_SIZE,
            "expected_grid_position": expected_position,
            "grid_position_80pct_range": [low, high],
            "hypothesis_direction_supported": beta < 0,
        }

    output = {
        "status": "STUDY_ONLY",
        "production_modified": False,
        "my_dr": my_dr,
        "my_dr_label": DR_LABELS.get(my_dr),
        "my_dr_percentage": my_pct,
        "same_dr_leaderboard_n": len(same_dr),
        "requested_profile_sample": len(sampled),
        "valid_profile_sample": len(observations),
        "dr_full_mean_ms": dr_mean,
        "dr_full_sd_ms": dr_sd,
        "theoretical_quantile_mean_ms": theoretical_mu,
        "observations": observations,
        "estimate": estimate,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_TXT.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "GT7 DR GRID POSITION LAB V0.1",
        "=" * 96,
        "Status: STUDY ONLY - production report formula not modified.",
        f"Driver: {PSN_ID} | DR {DR_LABELS.get(my_dr)} | DR progress {my_pct}%",
        f"Same-DR leaderboard population: {len(same_dr):,}",
        f"GTSH profiles sampled: {len(observations)} valid of {len(sampled)} requested",
        f"Full DR mean: {score_to_laptime(dr_mean)} | SD {dr_sd/1000:.3f}s" if dr_sd is not None else "Full DR stats unavailable",
        f"Theoretical quantile baseline at {my_pct}%: {score_to_laptime(theoretical_mu)}" if theoretical_mu is not None else "Theoretical baseline unavailable",
        "",
        "MODEL",
        "For similar DR progress p, model qualifying time as T ~ Normal(mu(p), sigma_local).",
        "mu(p) = alpha + beta * p, calibrated from sampled GTSH profiles in the same DR.",
        "q = P(peer is faster) = Phi((T_my - mu(p)) / sigma_local).",
        f"Expected grid position on a {GRID_SIZE}-car grid = 1 + ({GRID_SIZE}-1) * q.",
        "",
    ]

    if estimate:
        lines.extend([
            f"beta: {estimate['beta_ms_per_dr_pct']:.2f} ms per DR percentage point",
            f"correlation: {estimate['correlation']:.3f}",
            f"hypothesis supported (higher DR% -> faster): {'YES' if estimate['hypothesis_direction_supported'] else 'NO'}",
            f"Expected peer mean at DR {my_pct}%: {estimate['expected_peer_mean_laptime']}",
            f"Local sample within +/-{LOCAL_WINDOW:.0f} DR points: n={estimate['local_sample_n']}",
            f"Local/residual SD used: {estimate['local_sd_ms']/1000:.3f}s",
            f"Your qualifying time: {estimate['my_laptime']}",
            f"z vs similar-DR peers: {estimate['z_vs_similar_dr']:.3f}",
            f"Probability a similar-DR peer is faster: {100*estimate['probability_random_peer_faster']:.1f}%",
            f"Estimated grid position: P{estimate['expected_grid_position']:.1f} of {GRID_SIZE}",
            f"Approx. 80% range: P{estimate['grid_position_80pct_range'][0]:.1f} to P{estimate['grid_position_80pct_range'][1]:.1f}",
        ])
    else:
        lines.append("Insufficient valid GTSH profile sample for regression.")

    OUT_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"Saved: {OUT_JSON}")
    print(f"Saved: {OUT_TXT}")


if __name__ == "__main__":
    main()
