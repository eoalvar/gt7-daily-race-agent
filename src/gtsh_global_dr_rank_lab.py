from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

PSN_ID = "crazy_rooster74"
RANKING_URL = "https://gtsh-rank.com/ranking/"
PROFILE_URL = f"https://gtsh-rank.com/profile/?id={PSN_ID}"
OUT_JSON = Path("data/gtsh_global_dr_rank_lab.json")
OUT_TXT = Path("reports/gtsh_global_dr_rank_lab.txt")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/json,text/plain,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def compact(text: str, n: int = 1800) -> str:
    return re.sub(r"\s+", " ", text or "").strip()[:n]


def xor_decrypt(data: bytes, key: str) -> str:
    key_bytes = key.encode("utf-8")
    return bytes(b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(data)).decode("utf-8")


def walk_rankish(obj, path=""):
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else str(k)
            lk = str(k).lower()
            if any(token in lk for token in ("rank", "position", "place", "global", "percentile", "points")):
                if not isinstance(v, (dict, list)):
                    hits.append((p, v))
            hits.extend(walk_rankish(v, p))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits.extend(walk_rankish(v, f"{path}[{i}]"))
    return hits


def parse_ranking_page(html: str):
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for link in soup.select("a.driver-link"):
        href = link.get("href") or ""
        m = re.search(r"[?&]id=([^&]+)", href)
        psn = m.group(1) if m else None
        row = link.find_parent(class_=lambda c: c and "ranking-row" in c if isinstance(c, str) else False)
        if row is None:
            row = link.parent
            for _ in range(4):
                if row is None:
                    break
                rank_el = row.find(attrs={"data-label": "#"}) if hasattr(row, "find") else None
                if rank_el:
                    break
                row = row.parent
        rank = None
        dr = None
        if row is not None:
            rank_el = row.find(attrs={"data-label": "#"})
            dr_el = row.find(attrs={"data-label": "DR / Avg Rank"})
            if rank_el:
                mm = re.search(r"(\d+)", rank_el.get_text(" ", strip=True))
                if mm:
                    rank = int(mm.group(1))
            if dr_el:
                mm = re.search(r"(\d{3,})", dr_el.get_text(" ", strip=True))
                if mm:
                    dr = int(mm.group(1))
        rows.append({"rank": rank, "psn": psn, "dr_points": dr})
    ranks = [r["rank"] for r in rows if isinstance(r.get("rank"), int)]
    return {
        "rows": rows,
        "row_count": len(rows),
        "min_rank": min(ranks) if ranks else None,
        "max_rank": max(ranks) if ranks else None,
        "contains_target": any((r.get("psn") or "").casefold() == PSN_ID.casefold() for r in rows),
    }


def main():
    session = requests.Session()
    session.headers.update(HEADERS)

    page = session.get(RANKING_URL, timeout=30)
    page.raise_for_status()
    soup = BeautifulSoup(page.text, "html.parser")

    # Exact client-side URL behavior discovered in V2.
    update_url_script = ""
    for tag in soup.find_all("script"):
        text = tag.get_text(" ", strip=True)
        if "function updateUrl" in text:
            update_url_script = compact(text, 8000)
            break

    ranking_variants = []
    variants = [
        {"region": "Global", "history": "1day", "country": "all"},
        {"region": "Global", "history": "2days", "country": "all"},
        {"region": "Global", "history": "1week", "country": "all"},
        {"region": "Central and South America", "history": "1day", "country": "br"},
        {"region": "Central and South America", "history": "2days", "country": "br"},
    ]
    for params in variants:
        r = session.get(RANKING_URL, params=params, timeout=30)
        parsed = parse_ranking_page(r.text)
        ranking_variants.append({"url": r.url, "status": r.status_code, **parsed})

    # Search HTML for pagination/total clues.
    html_lower = page.text.lower()
    pagination_clues = []
    for token in ("pagination", "next", "previous", "total", "records", "split", "page=", "offset", "limit"):
        if token in html_lower:
            pagination_clues.append(token)

    # Decrypt target profile and inspect every rank-/position-like scalar.
    profile = session.get(PROFILE_URL, timeout=30)
    profile.raise_for_status()
    psoup = BeautifulSoup(profile.text, "html.parser")
    body = psoup.find("body")
    xor_key = body.get("header") if body else None
    decrypted = None
    profile_rankish = []
    profile_error = None
    try:
        resp = session.post(
            PROFILE_URL,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": PROFILE_URL,
                "Origin": "https://gtsh-rank.com",
                "Accept": "application/json,text/plain,*/*",
            },
            data={"psnid": PSN_ID},
            timeout=60,
        )
        wrapper = resp.json()
        raw = base64.b64decode(wrapper["data"])
        decrypted = json.loads(xor_decrypt(raw, xor_key))
        profile_rankish = walk_rankish(decrypted)
    except Exception as exc:
        profile_error = str(exc)

    report = {
        "version": "V3",
        "psn_id": PSN_ID,
        "ranking_url": RANKING_URL,
        "update_url_script": update_url_script,
        "pagination_clues": pagination_clues,
        "ranking_variants": ranking_variants,
        "profile_rankish": profile_rankish,
        "profile_error": profile_error,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_TXT.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "GTSH GLOBAL DR RANK DISCOVERY LAB V3",
        "=" * 104,
        f"PSN: {PSN_ID}",
        "",
        "CLIENT-SIDE FILTER LOGIC",
        update_url_script or "- updateUrl() not found",
        "",
        "GLOBAL/REGIONAL RANKING VARIANTS",
    ]
    for item in ranking_variants:
        lines.append(
            f"- {item['url']} | rows={item['row_count']} | min_rank={item['min_rank']} | max_rank={item['max_rank']} | target={item['contains_target']}"
        )
    lines.extend([
        "",
        "PAGINATION/TOTAL CLUES",
        "- " + ", ".join(pagination_clues) if pagination_clues else "- none",
        "",
        "PROFILE RANK/POSITION-LIKE FIELDS",
    ])
    if profile_error:
        lines.append(f"- ERROR: {profile_error}")
    elif not profile_rankish:
        lines.append("- none")
    else:
        for path, value in profile_rankish[:300]:
            lines.append(f"- {path} = {value}")

    OUT_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"Saved: {OUT_JSON}")
    print(f"Saved: {OUT_TXT}")


if __name__ == "__main__":
    main()
