from __future__ import annotations

import base64
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

HISTORY = Path("data/grid_calibration_history.json")
DR_LABELS = {1: "E", 2: "D", 3: "C", 4: "B", 5: "A", 6: "A+", 7: "S"}


def xor_decrypt(data: bytes, key: str) -> str:
    kb = key.encode("utf-8")
    return bytes(b ^ kb[i % len(kb)] for i, b in enumerate(data)).decode("utf-8")


def fetch_profile(session: requests.Session, psn_id: str):
    url = f"https://gtsh-rank.com/profile/?id={psn_id}"
    try:
        page = session.get(url, timeout=30)
        page.raise_for_status()
        soup = BeautifulSoup(page.text, "html.parser")
        body = soup.find("body")
        key = body.get("header") if body else None
        if not key:
            return None
        r = session.post(
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
        r.raise_for_status()
        wrapper = r.json()
        encrypted = wrapper.get("data") if isinstance(wrapper, dict) else None
        if not isinstance(encrypted, str):
            return None
        payload = json.loads(xor_decrypt(base64.b64decode(encrypted), key))
        user = payload.get("monthly_stats", {}).get("result", {}).get("user")
        if not isinstance(user, dict):
            return None
        resolved_psn = user.get("np_online_id")
        if not resolved_psn or resolved_psn.casefold() != psn_id.casefold():
            return None
        dr = user.get("driver_rating")
        dr = int(dr) if isinstance(dr, (int, float)) else None
        return {
            "psn_id": resolved_psn,
            "driver_rating": dr,
            "driver_rating_label": user.get("dr_level") or DR_LABELS.get(dr),
            "dr_points": user.get("dr_points"),
            "dr_percentage": user.get("dr_percentage"),
            "sportsmanship_rating": user.get("sportsmanship_rating"),
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        print(f"profile unavailable {psn_id}: {exc}")
        return None


def percentile_rank(points, value):
    if not points or value is None:
        return None
    below = sum(1 for p in points if p < value)
    equal = sum(1 for p in points if p == value)
    return round(100.0 * (below + 0.5 * equal) / len(points), 1)


def main():
    if not HISTORY.exists():
        print("No grid calibration history")
        return

    history = json.loads(HISTORY.read_text(encoding="utf-8"))
    session = requests.Session()
    changed = False

    for race in history:
        drivers = race.get("visible_grid") or race.get("visible_drivers") or []
        if not drivers:
            continue

        for driver in drivers:
            if driver.get("dr_points") is not None:
                continue
            candidate = driver.get("psn_id") or driver.get("display_name")
            if not candidate:
                continue
            profile = fetch_profile(session, candidate)
            if not profile:
                driver["profile_lookup_status"] = "not_resolved_exactly"
                continue
            driver["psn_id"] = profile["psn_id"]
            driver["profile_dr"] = profile
            driver["dr_points"] = profile.get("dr_points")
            driver["dr_percentage"] = profile.get("dr_percentage")
            driver["profile_lookup_status"] = "resolved_exactly"
            changed = True

        points = [
            float(d["dr_points"])
            for d in drivers
            if isinstance(d.get("dr_points"), (int, float))
        ]
        user_driver = next(
            (
                d
                for d in drivers
                if (d.get("psn_id") or d.get("display_name", "")).casefold()
                == str(race.get("psn_id", "")).casefold()
            ),
            None,
        )
        mine = user_driver.get("dr_points") if user_driver else None
        summary = {
            "profiles_resolved": len(points),
            "visible_drivers": len(drivers),
            "min": min(points) if points else None,
            "max": max(points) if points else None,
            "average": round(sum(points) / len(points), 1) if points else None,
            "median": round(statistics.median(points), 1) if points else None,
            "user_dr_points": mine,
            "user_percentile_within_resolved_grid": percentile_rank(points, mine),
            "drivers_above_user": sum(1 for p in points if mine is not None and p > mine) if mine is not None else None,
            "drivers_below_user": sum(1 for p in points if mine is not None and p < mine) if mine is not None else None,
        }
        if race.get("lobby_dr_points_summary") != summary:
            race["lobby_dr_points_summary"] = summary
            changed = True

    if changed:
        HISTORY.write_text(
            json.dumps(history, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print("Grid calibration DR enrichment updated")
    else:
        print("No grid DR enrichment changes")


if __name__ == "__main__":
    main()
