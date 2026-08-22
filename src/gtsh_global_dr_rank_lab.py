from __future__ import annotations

import json
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

PSN_ID = "crazy_rooster74"
RANKING_URL = "https://gtsh-rank.com/ranking/"
OUT_JSON = Path("data/gtsh_global_dr_rank_lab.json")
OUT_TXT = Path("reports/gtsh_global_dr_rank_lab.txt")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (GT7 Daily Race Agent Global DR Rank Lab)",
    "Accept": "text/html,application/json,text/plain,*/*;q=0.8",
}


def compact(text: str, n: int = 1800) -> str:
    return re.sub(r"\s+", " ", text or "").strip()[:n]


def inspect_payload(payload):
    info = {"type": type(payload).__name__}
    if isinstance(payload, dict):
        info["keys"] = sorted(str(k) for k in payload.keys())[:50]
        for key in ("total", "count", "recordsTotal", "total_players", "totalPlayers"):
            if isinstance(payload.get(key), (int, float)):
                info["total_key"] = key
                info["total"] = int(payload[key])
                break
        for key in ("board", "ranking", "data", "entries", "results", "drivers", "users"):
            if isinstance(payload.get(key), list):
                info["list_key"] = key
                info["list_n"] = len(payload[key])
                if payload[key]:
                    info["first_item"] = payload[key][0]
                break
    elif isinstance(payload, list):
        info["list_n"] = len(payload)
        if payload:
            info["first_item"] = payload[0]
    return info


def main():
    session = requests.Session()
    session.headers.update(HEADERS)

    page = session.get(RANKING_URL, timeout=30)
    page.raise_for_status()
    soup = BeautifulSoup(page.text, "html.parser")

    scripts = []
    for tag in soup.find_all("script"):
        src = tag.get("src")
        text = tag.get_text(" ", strip=True)
        if src or text:
            scripts.append({"src": src, "text": compact(text, 2500)})

    probes = []
    candidates = [
        ("GET", RANKING_URL + "?page_data=1&offset=0&limit=1000", None),
        ("GET", RANKING_URL + "?offset=0&limit=1000", None),
        ("GET", RANKING_URL + f"?search={PSN_ID}", None),
        ("GET", RANKING_URL + f"?psnid={PSN_ID}", None),
        ("POST", RANKING_URL, {"psnid": PSN_ID}),
        ("POST", RANKING_URL, {"search": PSN_ID}),
    ]

    for method, url, data in candidates:
        try:
            if method == "POST":
                r = session.post(url, data=data, timeout=30)
            else:
                r = session.get(url, timeout=30)
            ct = r.headers.get("content-type", "")
            item = {
                "method": method,
                "url": url,
                "status": r.status_code,
                "content_type": ct,
                "bytes": len(r.content),
                "preview": compact(r.text),
            }
            try:
                payload = r.json()
                item["json"] = inspect_payload(payload)
                item["contains_psn"] = PSN_ID.casefold() in json.dumps(payload, ensure_ascii=False).casefold()
            except Exception:
                item["contains_psn"] = PSN_ID.casefold() in r.text.casefold()
            probes.append(item)
        except Exception as exc:
            probes.append({"method": method, "url": url, "error": str(exc)})

    report = {
        "psn_id": PSN_ID,
        "ranking_url": RANKING_URL,
        "page_status": page.status_code,
        "page_bytes": len(page.content),
        "page_contains_psn": PSN_ID.casefold() in page.text.casefold(),
        "scripts": scripts,
        "probes": probes,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_TXT.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "GTSH GLOBAL DR RANK DISCOVERY LAB",
        "=" * 96,
        f"PSN: {PSN_ID}",
        f"Ranking page: status {page.status_code} | {len(page.content):,} bytes",
        f"PSN directly present in HTML: {'YES' if report['page_contains_psn'] else 'NO'}",
        "",
        "PROBES",
    ]
    for i, p in enumerate(probes, 1):
        lines.append(f"[{i}] {p.get('method')} {p.get('url')}")
        if p.get("error"):
            lines.append(f"    ERROR: {p['error']}")
            continue
        lines.append(f"    status={p.get('status')} | type={p.get('content_type')} | bytes={p.get('bytes'):,} | contains PSN={p.get('contains_psn')}")
        if p.get("json"):
            lines.append(f"    json={json.dumps(p['json'], ensure_ascii=False)[:1800]}")
        else:
            lines.append(f"    preview={p.get('preview')}")
    lines.extend(["", "SCRIPT SOURCES"])
    for s in scripts:
        if s.get("src"):
            lines.append(f"- {s['src']}")
        elif any(token in (s.get("text") or "").lower() for token in ("fetch", "ajax", "ranking", "offset", "limit")):
            lines.append(f"- inline: {s['text']}")

    OUT_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"Saved: {OUT_JSON}")
    print(f"Saved: {OUT_TXT}")


if __name__ == "__main__":
    main()
