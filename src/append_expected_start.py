from __future__ import annotations

import base64
import json
import math
import re
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from statistics import NormalDist
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

SNAPSHOT_FILE = Path("data/latest_snapshot.json")
REPORT_FILE = Path("reports/latest.txt")
CACHE_FILE = Path(".cache/current_leaderboard.json")
PSN_ID = "crazy_rooster74"
SAMPLE_SIZE = 60
GRID_SIZE = 16
LOCAL_WINDOW = 10.0
MIN_LOCAL = 8
# Each sampled profile is an independent GTSH request pair.  Six workers made
# this step the dominant runtime (~62s for 60 profiles).  Twelve keeps the same
# statistical sample while roughly halving wall-clock time without changing the
# model or reducing data quality.
PROFILE_WORKERS = 12
DR_LABELS = {1: "E", 2: "D", 3: "C", 4: "B", 5: "A", 6: "A+", 7: "S"}


def xor_decrypt(data: bytes, key: str) -> str:
    kb = key.encode("utf-8")
    return bytes(b ^ kb[i % len(kb)] for i, b in enumerate(data)).decode("utf-8")


def gtsh_profile(psn_id: str):
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (GT7 Expected Start Hybrid)"})
    url = f"https://gtsh-rank.com/profile/?id={quote(psn_id)}"
    try:
        page = session.get(url, timeout=20)
        page.raise_for_status()
        body = BeautifulSoup(page.text, "html.parser").find("body")
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
            timeout=35,
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
        dr = user.get("driver_rating")
        pct = user.get("dr_percentage")
        if not isinstance(dr, (int, float)) or not isinstance(pct, (int, float)):
            return None
        return {"driver_rating": int(dr), "dr_percentage": float(pct)}
    except Exception:
        return None
    finally:
        session.close()


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


def stratified_sample(items, n):
    if len(items) <= n:
        return items[:]
    return [items[round(i * (len(items) - 1) / (n - 1))] for i in range(n)]


def ols(points):
    if len(points) < 8:
        return None
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    xb = statistics.mean(xs)
    yb = statistics.mean(ys)
    sxx = sum((x - xb) ** 2 for x in xs)
    syy = sum((y - yb) ** 2 for y in ys)
    if sxx <= 0:
        return None
    beta = sum((x - xb) * (y - yb) for x, y in points) / sxx
    alpha = yb - beta * xb
    residuals = [y - (alpha + beta * x) for x, y in points]
    sigma = math.sqrt(sum(r * r for r in residuals) / max(1, len(points) - 2))
    corr = sum((x - xb) * (y - yb) for x, y in points) / math.sqrt(sxx * syy) if syy > 0 else 0.0
    return alpha, beta, sigma, corr


def empirical_q(peers, my_score):
    faster = sum(1 for p in peers if p["score"] < my_score)
    equal = sum(1 for p in peers if p["score"] == my_score)
    return (faster + 0.5 * equal) / len(peers)


def start_band(position):
    if position <= 3.0:
        return "1 to 3"
    if position <= 6.0:
        return "4 to 6"
    if position <= 9.0:
        return "7 to 9"
    if position <= 12.0:
        return "10 to 12"
    return "13 to 16"


def band_index(label):
    return ["1 to 3", "4 to 6", "7 to 9", "10 to 12", "13 to 16"].index(label)


def main():
    snapshot = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    race = snapshot.get("race") or {}
    me = snapshot.get("my_result") or {}
    dr_profile = snapshot.get("dr_profile") or {}

    leaderboard_url = race.get("leaderboard_url")
    my_score = me.get("score")
    my_dr = me.get("driver_rating")
    my_pct = dr_profile.get("dr_percentage")

    if not leaderboard_url or not isinstance(my_score, (int, float)) or not isinstance(my_dr, (int, float)) or not isinstance(my_pct, (int, float)):
        print("Expected-start estimate skipped: required data unavailable.")
        return

    my_dr = int(my_dr)
    my_pct = float(my_pct)
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (GT7 Expected Start Hybrid)"})

    entries = leaderboard_entries(session, leaderboard_url)
    same_dr = []
    for entry in entries:
        user = entry.get("user") or {}
        dr = user.get("driver_rating")
        psn = user.get("np_online_id")
        score = entry.get("score")
        if isinstance(dr, (int, float)) and int(dr) == my_dr and isinstance(psn, str) and isinstance(score, (int, float)):
            same_dr.append({"psn_id": psn, "score": float(score)})
    same_dr.sort(key=lambda x: x["score"])

    sampled = stratified_sample(same_dr, SAMPLE_SIZE)
    observations = []

    with ThreadPoolExecutor(max_workers=PROFILE_WORKERS) as executor:
        future_map = {executor.submit(gtsh_profile, item["psn_id"]): item for item in sampled}
        completed = 0
        for future in as_completed(future_map):
            completed += 1
            item = future_map[future]
            profile = future.result()
            if profile and profile["driver_rating"] == my_dr:
                observations.append({**item, "dr_percentage": profile["dr_percentage"]})
            print(f"Expected-start profile {completed}/{len(sampled)} | valid={len(observations)}")

    if len(observations) < 8:
        print("Expected-start estimate skipped: insufficient valid GTSH profiles.")
        return

    local = [o for o in observations if abs(o["dr_percentage"] - my_pct) <= LOCAL_WINDOW]
    local_method = f"+/-{LOCAL_WINDOW:.0f} DR%"
    if len(local) < MIN_LOCAL:
        local = sorted(observations, key=lambda o: abs(o["dr_percentage"] - my_pct))[:MIN_LOCAL]
        local_method = f"nearest {len(local)} DR% peers"

    q_emp = empirical_q(local, float(my_score))
    pos_emp = 1 + (GRID_SIZE - 1) * q_emp

    model = ols([(o["dr_percentage"], o["score"]) for o in observations])
    q_reg = q_emp
    pos_reg = pos_emp
    corr = 0.0
    if model:
        alpha, beta, residual_sd, corr = model
        mu = alpha + beta * my_pct
        sigma = max(1000.0, residual_sd)
        q_reg = NormalDist().cdf((float(my_score) - mu) / sigma)
        pos_reg = 1 + (GRID_SIZE - 1) * q_reg

    emp_weight = 0.75 if len(local) >= 8 else 0.65
    if abs(corr) < 0.15:
        emp_weight = min(0.85, emp_weight + 0.10)
    q_hybrid = emp_weight * q_emp + (1 - emp_weight) * q_reg
    pos_hybrid = 1 + (GRID_SIZE - 1) * q_hybrid
    band = start_band(pos_hybrid)

    empirical_band = start_band(pos_emp)
    regression_band = start_band(pos_reg)
    separation = abs(band_index(empirical_band) - band_index(regression_band))
    if len(observations) >= 20 and len(local) >= 8 and separation == 0:
        confidence = "HIGH"
    elif len(observations) >= 12 and separation <= 1:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    estimate = {
        "model": "FAST_HYBRID_V1_PARALLEL",
        "grid_size": GRID_SIZE,
        "dr": my_dr,
        "dr_label": DR_LABELS.get(my_dr),
        "dr_percentage": my_pct,
        "profiles_requested": len(sampled),
        "profiles_valid": len(observations),
        "local_method": local_method,
        "local_n": len(local),
        "empirical_position": pos_emp,
        "regression_position": pos_reg,
        "hybrid_position": pos_hybrid,
        "expected_start_range": band,
        "confidence": confidence,
        "empirical_weight": emp_weight,
        "regression_weight": 1 - emp_weight,
        "correlation": corr,
        "profile_workers": PROFILE_WORKERS,
    }
    snapshot["expected_start"] = estimate
    SNAPSHOT_FILE.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    report = REPORT_FILE.read_text(encoding="utf-8")
    report = re.sub(r"\nEXPECTED START\n.*?(?=\n\n[A-Z][A-Z &/0-9-]+\n|\Z)", "", report, flags=re.DOTALL)
    block = (
        "EXPECTED START\n"
        f"Projected grid range : {band}\n"
        f"Confidence           : {confidence}\n"
        f"Model basis          : DR {DR_LABELS.get(my_dr)} {my_pct:.0f}% | {len(observations)} valid profiles | {local_method}\n"
    )
    marker = "\nDR LAP-TIME BENCHMARKS - FULL LEADERBOARD\n"
    if marker in report:
        report = report.replace(marker, "\n" + block + "\nDR LAP-TIME BENCHMARKS - FULL LEADERBOARD\n", 1)
    else:
        report = report.rstrip() + "\n\n" + block
    REPORT_FILE.write_text(report, encoding="utf-8")

    print(f"Expected Start: {band} | Confidence: {confidence} | hybrid P{pos_hybrid:.1f}")


if __name__ == "__main__":
    main()
