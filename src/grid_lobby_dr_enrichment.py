from __future__ import annotations

import base64
import json
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
            headers={"Content-Type": "application/x-www-form-urlencoded", "Referer": url,
                     "Origin": "https://gtsh-rank.com", "Accept": "application/json,text/plain,*/*"},
            data={"psnid": psn_id}, timeout=60,
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
        dr = user.get("driver_rating")
        dr = int(dr) if isinstance(dr, (int, float)) else None
        return {
            "psn_id": user.get("np_online_id") or psn_id,
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


def main():
    if not HISTORY.exists():
        print("No grid calibration history")
        return
    history = json.loads(HISTORY.read_text(encoding="utf-8"))
    session = requests.Session()
    changed = False
    for race in history:
        drivers = race.get("visible_drivers") or []
        if not drivers:
            continue
        for driver in drivers:
            psn = driver.get("psn_id")
            if not psn or driver.get("dr_points") is not None:
                continue
            profile = fetch_profile(session, psn)
            if profile:
                driver["profile_dr"] = profile
                driver["dr_points"] = profile.get("dr_points")
                changed = True
        if drivers:
            points = [d.get("dr_points") for d in drivers if isinstance(d.get("dr_points"), (int, float))]
            mine = next((d.get("dr_points") for d in drivers if d.get("psn_id") == race.get("psn_id")), None)
            race["lobby_dr_points_summary"] = {
                "profiles_resolved": len(points), "visible_drivers": len(drivers),
                "min": min(points) if points else None, "max": max(points) if points else None,
                "average": round(sum(points) / len(points), 1) if points else None,
                "user_dr_points": mine,
            }
            changed = True
    if changed:
        HISTORY.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Grid calibration DR enrichment updated")
    else:
        print("No grid DR enrichment changes")


if __name__ == "__main__":
    main()
