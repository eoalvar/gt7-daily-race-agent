from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

PSN_ID = "crazy_rooster74"
PROFILE_URL = f"https://gtsh-rank.com/profile/?id={PSN_ID}"
OUT_JSON = Path("data/gtsh_dr_points_lab.json")
OUT_TXT = Path("reports/gtsh_dr_points_lab.txt")
HEADERS = {"User-Agent": "Mozilla/5.0 (GT7 Daily Race Agent DR Lab V3)"}


def compact(text: str, n: int = 1000) -> str:
    return re.sub(r"\s+", " ", text or "").strip()[:n]


def extract_balanced_context(text: str, marker: str, radius: int = 1800) -> str:
    pos = text.find(marker)
    if pos < 0:
        return ""
    return text[max(0, pos - radius): min(len(text), pos + radius)]


def resolve_template(expr: str) -> str | None:
    expr = expr.strip()
    replacements = {
        "${onlineId}": PSN_ID,
        "${id}": PSN_ID,
        "${psnId}": PSN_ID,
        "${psn_id}": PSN_ID,
        "${encodeURIComponent(onlineId)}": PSN_ID,
        "${encodeURIComponent(id)}": PSN_ID,
        "${encodeURIComponent(psnId)}": PSN_ID,
        "${encodeURIComponent(psn_id)}": PSN_ID,
    }
    for old, new in replacements.items():
        expr = expr.replace(old, new)
    if "${" in expr:
        return None
    return urljoin(PROFILE_URL, expr)


def extract_fetch_calls(text: str):
    calls = []

    patterns = [
        r"fetch\(\s*([`'\"])(.+?)\1\s*(?:,\s*(\{.*?\}))?\)",
        r"axios\.(get|post)\(\s*([`'\"])(.+?)\2",
    ]

    for match in re.finditer(patterns[0], text, flags=re.DOTALL | re.IGNORECASE):
        raw = match.group(2)
        url = resolve_template(raw)
        if url:
            calls.append({"kind": "fetch", "raw": raw, "url": url, "options": compact(match.group(3) or "", 1200)})

    for match in re.finditer(patterns[1], text, flags=re.DOTALL | re.IGNORECASE):
        raw = match.group(3)
        url = resolve_template(raw)
        if url:
            calls.append({"kind": f"axios.{match.group(1).lower()}", "raw": raw, "url": url, "options": ""})

    dedup = []
    seen = set()
    for item in calls:
        key = (item["kind"], item["url"])
        if key not in seen:
            seen.add(key)
            dedup.append(item)
    return dedup


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


def probe(session, item):
    url = item["url"]
    method = "POST" if item["kind"].endswith("post") else "GET"
    try:
        response = session.request(method, url, timeout=30)
        result = {
            "kind": item["kind"],
            "url": url,
            "method": method,
            "status": response.status_code,
            "content_type": response.headers.get("content-type", ""),
            "preview": compact(response.text, 1400),
        }
        try:
            payload = response.json()
            result["json"] = True
            user = recursively_find_user(payload)
            if isinstance(user, dict):
                result["user"] = {
                    key: user.get(key)
                    for key in (
                        "np_online_id",
                        "driver_rating",
                        "dr_level",
                        "dr_points",
                        "dr_percentage",
                        "sportsmanship_rating",
                    )
                    if key in user
                }
            return result, payload
        except Exception:
            result["json"] = False
            return result, None
    except Exception as exc:
        return {"kind": item["kind"], "url": url, "method": method, "error": str(exc)}, None


def main():
    session = requests.Session()
    session.headers.update(HEADERS)

    response = session.get(PROFILE_URL, timeout=30)
    response.raise_for_status()
    html = response.text
    soup = BeautifulSoup(html, "html.parser")

    inline_scripts = [script.get_text(" ", strip=False) for script in soup.find_all("script") if not script.get("src")]
    combined = "\n".join(inline_scripts)

    key_contexts = {
        "monthly_stats": extract_balanced_context(combined, "monthly_stats"),
        "getProfile": extract_balanced_context(combined, "getProfile"),
        "dr_percentage": extract_balanced_context(combined, "dr_percentage"),
        "dr_points": extract_balanced_context(combined, "dr_points"),
    }

    fetch_calls = extract_fetch_calls(combined)

    # Also inspect short contexts around monthly_stats/getProfile for URL-like literals
    context_blob = "\n".join(v for v in key_contexts.values() if v)
    for match in re.finditer(r"([`'\"])(/[^`'\"]*(?:profile|stats|player|user|search|monthly|api)[^`'\"]*)\1", context_blob, flags=re.IGNORECASE):
        url = resolve_template(match.group(2))
        if url:
            fetch_calls.append({"kind": "literal", "raw": match.group(2), "url": url, "options": ""})

    # Deduplicate and prioritize true calls plus anything mentioning stats/profile/user.
    unique = []
    seen = set()
    for item in fetch_calls:
        key = item["url"]
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    unique.sort(key=lambda x: (
        x["kind"] == "literal",
        not any(token in x["url"].lower() for token in ("stats", "profile", "user", "player", "monthly")),
        len(x["url"]),
    ))

    probes = []
    resolved_user = None
    resolved_payload = None

    for item in unique[:40]:
        result, payload = probe(session, item)
        probes.append(result)
        if isinstance(result.get("user"), dict) and any(k in result["user"] for k in ("dr_points", "dr_percentage")):
            resolved_user = result["user"]
            resolved_payload = payload
            break

    report = {
        "version": "V3",
        "psn_id": PSN_ID,
        "profile_url": PROFILE_URL,
        "confirmed_schema": {
            "dr_points": "user.dr_points",
            "dr_percentage": "user.dr_percentage",
            "driver_rating_mapping": {"1": "E", "2": "D", "3": "C", "4": "B", "5": "A", "6": "A+", "7": "S"},
        },
        "key_contexts": {k: compact(v, 5000) for k, v in key_contexts.items()},
        "network_candidates": unique[:60],
        "probes": probes,
        "resolved_user": resolved_user,
        "resolved_payload": resolved_payload if resolved_user else None,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_TXT.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "GTSH DR POINTS DISCOVERY LAB V3",
        "=" * 96,
        f"PSN ID: {PSN_ID}",
        "Scope: GTSH public web sources only; no official GT7 API.",
        "",
        "CONFIRMED SCHEMA",
        "- user.dr_points",
        "- user.dr_percentage",
        "- mapping 1=E, 2=D, 3=C, 4=B, 5=A, 6=A+, 7=S",
        "",
        "RESOLVED USER DATA",
    ]

    if resolved_user:
        for key, value in resolved_user.items():
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- not resolved yet")

    lines.extend(["", "NETWORK CANDIDATES"])
    if unique:
        for item in unique[:40]:
            lines.append(f"- {item['kind']} | {item['url']} | raw={item['raw']}")
    else:
        lines.append("- none")

    lines.extend(["", "PROBES"])
    if probes:
        for item in probes:
            lines.append(
                f"- {item.get('method')} {item.get('url')} | status={item.get('status')} | "
                f"type={item.get('content_type')} | user={item.get('user')} | preview={item.get('preview')}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "KEY CODE CONTEXT: monthly_stats"])
    lines.append(compact(key_contexts["monthly_stats"], 5000) or "- not found")
    lines.extend(["", "KEY CODE CONTEXT: getProfile"])
    lines.append(compact(key_contexts["getProfile"], 5000) or "- not found")

    OUT_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"Saved: {OUT_JSON}")
    print(f"Saved: {OUT_TXT}")


if __name__ == "__main__":
    main()
