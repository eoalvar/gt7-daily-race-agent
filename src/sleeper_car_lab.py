import json
import math
import time
import traceback
from collections import defaultdict
from pathlib import Path
from datetime import datetime

import requests

from debug_current_race import (
    PAGE_SIZE,
    HEADERS,
    REQUEST_DELAY_SECONDS,
    fetch_page_data,
    get_car_code,
    get_rank,
    get_score,
)
from car_database import load_car_database, get_car_name
from bop_track_classifier import (
    load_json,
    detect_group,
    records_for_car,
    latest_version,
    compact_bop,
)

VERSION = "0.1"

LATEST_SNAPSHOT_FILE = Path("data/latest_snapshot.json")
TRACK_CLASSIFICATION_FILE = Path("data/bop_lab/current_track_bop.json")
BOP_DATABASE_FILE = Path("data/bop_lab/bop_database.json")
REPORT_FILE = Path("reports/sleeper_car_lab.txt")
RESULT_FILE = Path("data/bop_lab/sleeper_car_index.json")
ERROR_FILE = Path("data/bop_lab/sleeper_car_lab_error.txt")

SEP = "=" * 100
SUB = "-" * 100

MIN_CAR_SAMPLE = 20
PRIOR_STRENGTH = 150.0

TIER_WEIGHTS = {
    100: 0.20,
    500: 0.30,
    1000: 0.50,
}


def now_iso():
    return datetime.now().astimezone().isoformat()


def clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def safe_int(value):
    try:
        return int(value)
    except Exception:
        return None


def score_to_laptime(score):
    if score is None:
        return "N/A"
    score = int(round(float(score)))
    minutes = score // 60000
    seconds = (score % 60000) // 1000
    milliseconds = score % 1000
    return f"{minutes}:{seconds:02d}.{milliseconds:03d}"


def canonical_car_name(car_code, database):
    if car_code is None:
        return "Unknown car"
    return get_car_name(car_code, database)


def load_complete_leaderboard(event_url):
    session = requests.Session()
    session.headers.update(HEADERS)

    first = fetch_page_data(
        session,
        event_url,
        0,
        PAGE_SIZE,
    )

    total = safe_int(first.get("total")) or len(first["board"])
    ranking = list(first["board"])

    offset = len(first["board"])

    print(
        f"Page 1              : {len(first['board'])} drivers | "
        f"{len(ranking):,}/{total:,}"
    )

    page_number = 1

    while offset < total:
        page_number += 1

        page = fetch_page_data(
            session,
            event_url,
            offset,
            PAGE_SIZE,
        )

        board = page["board"]

        if not board:
            raise RuntimeError(
                f"Leaderboard pagination returned zero entries at offset {offset}."
            )

        ranking.extend(board)
        offset += len(board)

        if page_number <= 5 or page_number % 25 == 0 or offset >= total:
            print(
                f"Page {page_number:<12}: +{len(board):<3} | "
                f"{len(ranking):,}/{total:,}"
            )

        if not page.get("has_more") and len(ranking) < total:
            raise RuntimeError(
                "Leaderboard ended before the advertised total was reached."
            )

        time.sleep(REQUEST_DELAY_SECONDS)

    ranking.sort(
        key=lambda item: (
            safe_int(get_rank(item)) or 10**9,
            safe_int(get_score(item)) or 10**9,
        )
    )

    return ranking, total


def bayesian_lift(k, n, tier_size, total):
    if n <= 0 or total <= 0 or tier_size <= 0:
        return 1.0

    base_rate = min(tier_size, total) / total

    posterior_rate = (
        k + PRIOR_STRENGTH * base_rate
    ) / (
        n + PRIOR_STRENGTH
    )

    if base_rate <= 0:
        return 1.0

    return posterior_rate / base_rate


def quality_component(efficiency_lift):
    if efficiency_lift <= 0:
        return 0.0

    x = math.log(efficiency_lift)
    return 1.0 / (1.0 + math.exp(-2.2 * x))


def confidence_label(sample):
    if sample >= 500:
        return "HIGH"
    if sample >= 150:
        return "MEDIUM"
    if sample >= 50:
        return "LOW-MEDIUM"
    return "LOW"


def sleeper_label(score, share, sample):
    if sample < MIN_CAR_SAMPLE:
        return "INSUFFICIENT SAMPLE"
    if share >= 0.20:
        return "META / PROVEN"
    if score >= 68:
        return "STRONG SLEEPER"
    if score >= 60:
        return "SLEEPER CANDIDATE"
    if score >= 54:
        return "WATCHLIST"
    return "NO SLEEPER SIGNAL"


def active_bop_for_car(all_bop_records, car, group, speed_class):
    records, match = records_for_car(
        all_bop_records,
        car,
        group,
    )

    if not records:
        return None, match

    version = latest_version(records)

    selected = next(
        (
            record
            for record in records
            if str(record.get("bop_version") or "") == str(version)
            and str(record.get("speed_class") or "").upper() == speed_class
        ),
        None,
    )

    return compact_bop(selected), match


def build_car_statistics(ranking, total, car_database):
    stats = defaultdict(
        lambda: {
            "car_code": None,
            "car": None,
            "all_count": 0,
            "top100": 0,
            "top500": 0,
            "top1000": 0,
            "best_rank": None,
            "best_score": None,
        }
    )

    for driver in ranking:
        code = get_car_code(driver)

        try:
            code = int(code)
        except Exception:
            continue

        rank = safe_int(get_rank(driver))
        score = safe_int(get_score(driver))

        item = stats[code]
        item["car_code"] = code
        item["car"] = canonical_car_name(code, car_database)
        item["all_count"] += 1

        if rank is not None:
            if rank <= 100:
                item["top100"] += 1
            if rank <= 500:
                item["top500"] += 1
            if rank <= 1000:
                item["top1000"] += 1

            if item["best_rank"] is None or rank < item["best_rank"]:
                item["best_rank"] = rank

        if score is not None:
            if item["best_score"] is None or score < item["best_score"]:
                item["best_score"] = score

    return list(stats.values())


def calculate_index(
    car_stats,
    total,
    wr_score,
    top500_score,
    all_bop_records,
    group,
    speed_class,
):
    results = []

    elite_scale = max(
        1.0,
        float(top500_score - wr_score),
    )

    for item in car_stats:
        n = item["all_count"]

        lifts = {
            100: bayesian_lift(item["top100"], n, 100, total),
            500: bayesian_lift(item["top500"], n, 500, total),
            1000: bayesian_lift(item["top1000"], n, 1000, total),
        }

        weighted_log_lift = sum(
            TIER_WEIGHTS[tier] * math.log(max(lifts[tier], 1e-9))
            for tier in TIER_WEIGHTS
        )

        efficiency_lift = math.exp(weighted_log_lift)
        quality = quality_component(efficiency_lift)

        share = n / total if total else 0.0
        rarity = 1.0 - math.sqrt(clamp(share))

        best_score = item.get("best_score")

        if best_score is None:
            elite_proximity = 0.0
        else:
            elite_gap = max(0.0, float(best_score - wr_score))
            elite_proximity = math.exp(-elite_gap / elite_scale)

        evidence = min(1.0, math.sqrt(n / 250.0))

        raw_score = 100.0 * (
            0.55 * quality
            + 0.25 * elite_proximity
            + 0.20 * rarity
        )

        sleeper_score = 50.0 + evidence * (raw_score - 50.0)
        sleeper_score = max(0.0, min(100.0, sleeper_score))

        bop, match = active_bop_for_car(
            all_bop_records,
            item["car"],
            group,
            speed_class,
        )

        result = {
            **item,
            "share": share,
            "share_percent": share * 100.0,
            "lift_top100": lifts[100],
            "lift_top500": lifts[500],
            "lift_top1000": lifts[1000],
            "efficiency_lift": efficiency_lift,
            "quality_component": quality,
            "rarity_component": rarity,
            "elite_proximity": elite_proximity,
            "evidence_factor": evidence,
            "sleeper_score": sleeper_score,
            "sleeper_label": sleeper_label(sleeper_score, share, n),
            "confidence": confidence_label(n),
            "active_bop": bop,
            "bop_match": match,
        }

        results.append(result)

    results.sort(
        key=lambda item: (
            item["sleeper_score"],
            item["efficiency_lift"],
            item["all_count"],
        ),
        reverse=True,
    )

    return results


def fmt(value, decimals=2):
    if isinstance(value, (int, float)):
        return f"{value:.{decimals}f}"
    return "N/A"


def format_bop(record):
    if not record:
        return "BoP N/A"

    power = record.get("power_hp")
    weight = record.get("weight_kg")
    pp = record.get("pp")
    drivetrain = record.get("drivetrain") or "?"

    power_text = f"{power:g} HP" if isinstance(power, (int, float)) else "HP N/A"
    weight_text = f"{weight:g} kg" if isinstance(weight, (int, float)) else "kg N/A"
    pp_text = f"PP {pp:g}" if isinstance(pp, (int, float)) else "PP N/A"

    return f"{power_text} / {weight_text} / {pp_text} / {drivetrain}"


def run_lab():
    started = time.time()

    snapshot = load_json(LATEST_SNAPSHOT_FILE)
    track_classification = load_json(TRACK_CLASSIFICATION_FILE)
    bop_database = load_json(BOP_DATABASE_FILE)

    race = snapshot.get("race") or {}
    event_url = race.get("leaderboard_url")

    if not event_url:
        raise RuntimeError("latest_snapshot.json has no leaderboard URL.")

    description = race.get("description") or ""
    group = track_classification.get("group") or detect_group(description)
    track = track_classification.get("track")
    speed_class = str(track_classification.get("speed_class") or "").upper()

    if speed_class not in {"HIGH", "MID", "LOW"}:
        raise RuntimeError(f"Invalid active BoP speed class: {speed_class}")

    all_bop_records = bop_database.get("records") or []

    print()
    print(f"GT7 SLEEPER CAR LAB V{VERSION}")
    print(SEP)
    print(f"Track               : {track}")
    print(f"Group               : {group}")
    print(f"Active BoP          : {speed_class}")
    print("Production modified : NO")
    print()
    print("LOADING COMPLETE LIVE LEADERBOARD")
    print(SUB)

    ranking, total = load_complete_leaderboard(event_url)

    if len(ranking) != total:
        raise RuntimeError(
            f"Leaderboard completeness failed: loaded {len(ranking)}, expected {total}."
        )

    wr_score = safe_int(get_score(ranking[0]))

    if wr_score is None:
        raise RuntimeError("Could not determine world-record score.")

    top500_index = min(499, len(ranking) - 1)
    top500_score = safe_int(get_score(ranking[top500_index]))

    if top500_score is None:
        raise RuntimeError("Could not determine Top 500 benchmark.")

    car_database = load_car_database()
    car_stats = build_car_statistics(
        ranking,
        total,
        car_database,
    )

    results = calculate_index(
        car_stats=car_stats,
        total=total,
        wr_score=wr_score,
        top500_score=top500_score,
        all_bop_records=all_bop_records,
        group=group,
        speed_class=speed_class,
    )

    eligible = [
        item
        for item in results
        if item["all_count"] >= MIN_CAR_SAMPLE
    ]

    payload = {
        "generated_at": now_iso(),
        "version": VERSION,
        "snapshot_timestamp": snapshot.get("timestamp"),
        "track": track,
        "group": group,
        "speed_class": speed_class,
        "total_drivers": total,
        "world_record_score": wr_score,
        "world_record_laptime": score_to_laptime(wr_score),
        "top500_score": top500_score,
        "top500_laptime": score_to_laptime(top500_score),
        "method": {
            "name": "Bayesian representation efficiency + elite proximity + rarity",
            "prior_strength": PRIOR_STRENGTH,
            "tier_weights": {str(k): v for k, v in TIER_WEIGHTS.items()},
            "minimum_car_sample": MIN_CAR_SAMPLE,
            "score_weights": {
                "representation_quality": 0.55,
                "elite_proximity": 0.25,
                "rarity": 0.20,
            },
            "evidence_shrinkage": "Score is shrunk toward neutral 50 for small car samples.",
            "bop_role": (
                "BoP-aware: all technical descriptors use the active speed-class table. "
                "Technical values are not yet assigned arbitrary performance weights."
            ),
        },
        "cars_total": len(results),
        "cars_eligible": len(eligible),
        "ranking": eligible,
        "production_pipeline_modified": False,
    }

    RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)

    RESULT_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    elapsed = time.time() - started

    lines = [
        f"GT7 SLEEPER CAR LAB V{VERSION}",
        SEP,
        f"Generated            : {payload['generated_at']}",
        f"Track                : {track}",
        f"Group                : {group}",
        f"Active BoP           : {speed_class}",
        f"Total drivers        : {total:,}",
        f"Cars observed        : {len(results)}",
        f"Cars eligible (n>={MIN_CAR_SAMPLE}) : {len(eligible)}",
        f"WR                   : {score_to_laptime(wr_score)}",
        f"Top 500              : {score_to_laptime(top500_score)}",
        f"Elapsed              : {elapsed:.1f}s",
        "Production modified  : NO",
        "",
        "METHOD",
        SUB,
        "Sleeper Score is NOT simple car popularity or the old overperformance index.",
        "It combines Bayesian-shrunk representation efficiency in Top 100/500/1000,",
        "best-car elite proximity, rarity, and sample-size evidence strength.",
        "Active BoP technical data is attached using the circuit speed class; technical",
        "fields are intentionally not given arbitrary weights in V0.1.",
        "",
        "TOP SLEEPER CANDIDATES",
        SUB,
    ]

    for index, item in enumerate(eligible[:15], start=1):
        lines.append(
            f"{index:>2}. {item['car']} | SCI {item['sleeper_score']:.1f} | "
            f"{item['sleeper_label']} | n={item['all_count']} ({item['share_percent']:.2f}%) | "
            f"Eff {item['efficiency_lift']:.2f}x | "
            f"T100 {item['top100']} / T500 {item['top500']} / T1000 {item['top1000']} | "
            f"Best #{item['best_rank']} {score_to_laptime(item['best_score'])} | "
            f"Conf {item['confidence']}"
        )
        lines.append(
            f"    Active {speed_class} BoP: {format_bop(item.get('active_bop'))}"
        )

    lines += [
        "",
        "META VS SLEEPER INTERPRETATION",
        SUB,
        "A high SCI means the car is producing disproportionately strong leaderboard results",
        "despite relatively low adoption, with Bayesian shrinkage to reduce small-sample noise.",
        "A dominant meta car can still be objectively excellent, but its rarity component is low,",
        "so it will not automatically be called a sleeper simply because elite drivers use it.",
        "",
        "NEXT MODEL STEP",
        SUB,
        "V0.2 should learn circuit-specific technical weights from multiple finalized races.",
        "That is where power/weight, weight balance, acceleration, rotational G and stability",
        "can become explanatory/predictive variables instead of hand-picked assumptions.",
        SEP,
    ]

    report = "\n".join(lines)
    REPORT_FILE.write_text(report, encoding="utf-8")

    if ERROR_FILE.exists():
        ERROR_FILE.unlink()

    print()
    print(report)
    print()
    print(f"Saved report         : {REPORT_FILE}")
    print(f"Saved result         : {RESULT_FILE}")


def main():
    try:
        run_lab()
    except Exception as error:
        ERROR_FILE.parent.mkdir(parents=True, exist_ok=True)
        REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)

        diagnostic = (
            f"GT7 SLEEPER CAR LAB V{VERSION} - ERROR\n"
            f"{SEP}\n"
            f"Generated: {now_iso()}\n"
            f"Error: {type(error).__name__}: {error}\n\n"
            f"TRACEBACK\n{SUB}\n{traceback.format_exc()}\n"
            f"{SEP}\n"
        )

        ERROR_FILE.write_text(diagnostic, encoding="utf-8")
        REPORT_FILE.write_text(diagnostic, encoding="utf-8")
        print(diagnostic)
        raise


if __name__ == "__main__":
    main()
