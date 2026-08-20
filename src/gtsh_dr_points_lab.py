from __future__ import annotations

import base64
import json
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

PSN_ID = "crazy_rooster74"
PROFILE_URL = f"https://gtsh-rank.com/profile/?id={PSN_ID}"
OUT_JSON = Path("data/gtsh_dr_points_lab.json")
OUT_TXT = Path("reports/gtsh_dr_points_lab.txt")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (GT7 Daily Race Agent DR Lab V5)",
    "Accept": "text/html,application/xhtml+xml,application/json,*/*;q=0.8",
}

DR_MAP = {1: "E", 2: "D", 3: "C", 4: "B", 5: "A", 6: "A+", 7: "S"}


def compact(text: str, n: int = 1400) -> str:
    return re.sub(r"\s+", " ", text or "").strip()[:n]


def xor_decrypt(data: bytes, key: str) -> str:
    if not key:
        raise ValueError("empty XOR key")
    key_bytes = key.encode("utf-8")
    decoded = bytes(b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(data))
    return decoded.decode("utf-8")


def recursively_find_user(obj):
    if isinstance(obj, dict):
        if any(k in obj for k in ("dr_points", "dr_percentage", "driver_rating")):
            return obj
        for value in obj.values():
            found = recursively_find_user(value)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = recursively_find_user(value)
            if found is not None:
                return found
    return None


def main():
    session = requests.Session()
    session.headers.update(HEADERS)

    # 1) Load the exact public profile page used by the browser client.
    page = session.get(PROFILE_URL, timeout=30)
    page.raise_for_status()
    html = page.text
    soup = BeautifulSoup(html, "html.parser")

    # V4 established that the client reads the XOR key from document.body.getAttribute('header').
    body = soup.find("body")
    xor_key = body.get("header") if body else None

    # Keep forensic evidence of where the key came from without printing the key itself.
    body_attrs = dict(body.attrs) if body else {}
    body_attr_names = sorted(body_attrs.keys())

    # 2) Reproduce getProfile() exactly:
    #    POST window.location.href
    #    Content-Type: application/x-www-form-urlencoded
    #    body: psnid=<PSN>
    post_headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": PROFILE_URL,
        "Origin": "https://gtsh-rank.com",
        "Accept": "application/json,text/plain,*/*",
    }

    post = session.post(
        PROFILE_URL,
        headers=post_headers,
        data={"psnid": PSN_ID},
        timeout=60,
    )

    response_content_type = post.headers.get("content-type", "")
    response_preview = compact(post.text, 1800)

    wrapper = None
    wrapper_error = None
    try:
        wrapper = post.json()
    except Exception as exc:
        wrapper_error = str(exc)

    decrypted_payload = None
    decrypt_error = None
    resolved_user = None

    if isinstance(wrapper, dict):
        # If GTSH ever decides to return plain JSON, support that too.
        direct_user = recursively_find_user(wrapper)
        if direct_user is not None:
            resolved_user = direct_user
            decrypted_payload = wrapper
        else:
            encrypted_b64 = wrapper.get("data")
            if isinstance(encrypted_b64, str):
                if not xor_key:
                    decrypt_error = "Encrypted payload returned, but body header XOR key was not found."
                else:
                    try:
                        encrypted_bytes = base64.b64decode(encrypted_b64)
                        plaintext = xor_decrypt(encrypted_bytes, xor_key)
                        decrypted_payload = json.loads(plaintext)
                        resolved_user = recursively_find_user(decrypted_payload)
                    except Exception as exc:
                        decrypt_error = str(exc)

    dr_summary = None
    if isinstance(resolved_user, dict):
        dr_code = resolved_user.get("driver_rating")
        try:
            dr_code_int = int(dr_code) if dr_code is not None else None
        except Exception:
            dr_code_int = None

        dr_label = resolved_user.get("dr_level") or DR_MAP.get(dr_code_int)
        dr_points = resolved_user.get("dr_points")
        dr_percentage = resolved_user.get("dr_percentage")

        dr_summary = {
            "driver_rating": dr_code_int,
            "dr_label": dr_label,
            "dr_points": dr_points,
            "dr_percentage": dr_percentage,
            "np_online_id": resolved_user.get("np_online_id"),
            "sportsmanship_rating": resolved_user.get("sportsmanship_rating"),
        }

    report = {
        "version": "V5",
        "psn_id": PSN_ID,
        "profile_url": PROFILE_URL,
        "profile_status": page.status_code,
        "body_attribute_names": body_attr_names,
        "xor_key_present": bool(xor_key),
        "post_status": post.status_code,
        "post_content_type": response_content_type,
        "post_response_preview": response_preview,
        "wrapper_json": wrapper,
        "wrapper_json_error": wrapper_error,
        "decrypt_error": decrypt_error,
        "resolved_user": resolved_user,
        "dr_summary": dr_summary,
        "decrypted_payload": decrypted_payload,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_TXT.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "GTSH DR POINTS DISCOVERY LAB V5",
        "=" * 104,
        f"PSN ID: {PSN_ID}",
        "Scope: public GTSH web client only; no official GT7 API.",
        "",
        "REQUEST REPRODUCTION",
        f"GET profile status : {page.status_code}",
        f"Body header key    : {'FOUND' if xor_key else 'NOT FOUND'}",
        f"Body attrs         : {', '.join(body_attr_names) if body_attr_names else 'none'}",
        f"POST status        : {post.status_code}",
        f"POST content-type  : {response_content_type}",
        "POST method/body  : application/x-www-form-urlencoded | psnid=<PSN>",
        "",
        "RESOLVED DR DATA",
    ]

    if dr_summary:
        lines.extend([
            f"- np_online_id: {dr_summary.get('np_online_id')}",
            f"- driver_rating: {dr_summary.get('driver_rating')}",
            f"- dr_label: {dr_summary.get('dr_label')}",
            f"- dr_points: {dr_summary.get('dr_points')}",
            f"- dr_percentage: {dr_summary.get('dr_percentage')}",
            f"- sportsmanship_rating: {dr_summary.get('sportsmanship_rating')}",
        ])
    else:
        lines.append("- not resolved yet")

    lines.extend([
        "",
        "DECRYPTION",
        f"- wrapper JSON parsed: {'YES' if isinstance(wrapper, dict) else 'NO'}",
        f"- wrapper contains data: {'YES' if isinstance(wrapper, dict) and isinstance(wrapper.get('data'), str) else 'NO'}",
        f"- XOR key present: {'YES' if xor_key else 'NO'}",
        f"- decrypt error: {decrypt_error or 'none'}",
        "",
        "RESPONSE PREVIEW",
        response_preview or "- empty",
    ])

    OUT_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n".join(lines))
    print(f"Saved: {OUT_JSON}")
    print(f"Saved: {OUT_TXT}")


if __name__ == "__main__":
    main()
