from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

PSN_ID = "crazy_rooster74"
OUT_JSON = Path("data/gtsh_dr_points_lab.json")
OUT_TXT = Path("reports/gtsh_dr_points_lab.txt")

BASES = [
    "https://gtsh-rank.com",
    "https://gt7.gtsh-rank.com",
]

HEADERS = {"User-Agent": "Mozilla/5.0 (GT7 Daily Race Agent DR Lab)"}

KEY_PATTERNS = [
    r"dr[_\- ]?points?",
    r"driver[_\- ]?rating",
    r"driver[_\- ]?rating[_\- ]?points?",
    r"dr[_\- ]?point[_\- ]?ratio",
    r"rating[_\- ]?points?",
    r"progress",
]


def compact(text: str, n: int = 240) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:n]


def extract_numeric_candidates(text: str):
    found = []
    patterns = [
        r'(?i)(?:dr[_\- ]?points?|driver[_\- ]?rating[_\- ]?points?|rating[_\- ]?points?)\s*[":=]\s*"?(\d{2,6}(?:\.\d+)?)',
        r'(?i)"(?:drPoints|dr_points|driverRatingPoints|driver_rating_points|ratingPoints)"\s*:\s*(\d{2,6}(?:\.\d+)?)',
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            found.append({
                "value": float(match.group(1)),
                "context": compact(text[max(0, match.start()-120):match.end()+120], 320),
            })
    return found


def keyword_snippets(text: str):
    snippets = []
    for pat in KEY_PATTERNS:
        for match in re.finditer(pat, text, flags=re.IGNORECASE):
            snippet = compact(text[max(0, match.start()-140):match.end()+180], 360)
            if snippet and snippet not in snippets:
                snippets.append(snippet)
            if len(snippets) >= 40:
                return snippets
    return snippets


def same_host(url: str, base: str) -> bool:
    return urlparse(url).netloc == urlparse(base).netloc


def fetch(session, url):
    try:
        r = session.get(url, timeout=30)
        return {
            "url": url,
            "status": r.status_code,
            "final_url": r.url,
            "content_type": r.headers.get("content-type", ""),
            "text": r.text if "text" in r.headers.get("content-type", "") or "javascript" in r.headers.get("content-type", "") or "json" in r.headers.get("content-type", "") else "",
        }
    except Exception as exc:
        return {"url": url, "error": str(exc), "text": ""}


def main():
    session = requests.Session()
    session.headers.update(HEADERS)

    report = {
        "psn_id": PSN_ID,
        "sources": [],
        "numeric_candidates": [],
        "keyword_snippets": [],
        "forms": [],
        "script_urls": [],
        "endpoint_candidates": [],
    }

    for base in BASES:
        profile_url = f"{base}/profile/?id={PSN_ID}"
        result = fetch(session, profile_url)
        text = result.get("text", "")
        report["sources"].append({k: v for k, v in result.items() if k != "text"})

        if not text:
            continue

        for item in extract_numeric_candidates(text):
            item["source"] = profile_url
            report["numeric_candidates"].append(item)

        for snippet in keyword_snippets(text):
            report["keyword_snippets"].append({"source": profile_url, "snippet": snippet})

        soup = BeautifulSoup(text, "html.parser")

        for form in soup.find_all("form"):
            action = urljoin(profile_url, form.get("action") or "")
            method = (form.get("method") or "GET").upper()
            inputs = []
            for inp in form.find_all("input"):
                inputs.append({
                    "name": inp.get("name"),
                    "type": inp.get("type"),
                    "value": inp.get("value"),
                    "placeholder": inp.get("placeholder"),
                })
            report["forms"].append({"source": profile_url, "action": action, "method": method, "inputs": inputs})

        scripts = []
        for script in soup.find_all("script"):
            src = script.get("src")
            if src:
                full = urljoin(profile_url, src)
                if same_host(full, base):
                    scripts.append(full)
            else:
                inline = script.get_text(" ", strip=False)
                for snippet in keyword_snippets(inline):
                    report["keyword_snippets"].append({"source": profile_url + "#inline-script", "snippet": snippet})
                for item in extract_numeric_candidates(inline):
                    item["source"] = profile_url + "#inline-script"
                    report["numeric_candidates"].append(item)

        for script_url in list(dict.fromkeys(scripts))[:40]:
            report["script_urls"].append(script_url)
            sres = fetch(session, script_url)
            stext = sres.get("text", "")
            if not stext:
                continue

            for snippet in keyword_snippets(stext):
                report["keyword_snippets"].append({"source": script_url, "snippet": snippet})

            for item in extract_numeric_candidates(stext):
                item["source"] = script_url
                report["numeric_candidates"].append(item)

            # Discover likely same-site endpoint strings without guessing external APIs.
            for match in re.finditer(r'["\']([^"\']*(?:profile|player|user|rating|dr|ajax|api)[^"\']*)["\']', stext, flags=re.IGNORECASE):
                candidate = match.group(1)
                if len(candidate) > 220 or " " in candidate or candidate.startswith("http") and not same_host(candidate, base):
                    continue
                full = urljoin(script_url, candidate)
                if same_host(full, base) and full not in report["endpoint_candidates"]:
                    report["endpoint_candidates"].append(full)

    # Keep output concise and deduplicated.
    seen = set()
    dedup_snips = []
    for item in report["keyword_snippets"]:
        key = (item["source"], item["snippet"])
        if key not in seen:
            seen.add(key)
            dedup_snips.append(item)
    report["keyword_snippets"] = dedup_snips[:100]
    report["endpoint_candidates"] = report["endpoint_candidates"][:100]

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_TXT.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "GTSH DR POINTS DISCOVERY LAB",
        "=" * 88,
        f"PSN ID: {PSN_ID}",
        "Scope: GTSH public web sources only; no official GT7 API.",
        "",
        "PROFILE REQUESTS",
    ]
    for src in report["sources"]:
        lines.append(f"- {src.get('url')} | status={src.get('status')} | final={src.get('final_url')} | error={src.get('error')}")

    lines.extend(["", "NUMERIC DR/RATING CANDIDATES"])
    if report["numeric_candidates"]:
        for item in report["numeric_candidates"][:30]:
            lines.append(f"- {item['value']} | {item['source']} | {item['context']}")
    else:
        lines.append("- none found directly in fetched HTML/JS")

    lines.extend(["", "DISCOVERED FORMS"])
    if report["forms"]:
        for form in report["forms"][:20]:
            lines.append(f"- {form['method']} {form['action']} | inputs={form['inputs']}")
    else:
        lines.append("- none")

    lines.extend(["", "KEYWORD SNIPPETS"])
    for item in report["keyword_snippets"][:40]:
        lines.append(f"- {item['source']} | {item['snippet']}")

    lines.extend(["", "LIKELY SAME-SITE ENDPOINT STRINGS"])
    if report["endpoint_candidates"]:
        for url in report["endpoint_candidates"][:50]:
            lines.append(f"- {url}")
    else:
        lines.append("- none")

    OUT_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"Saved: {OUT_JSON}")
    print(f"Saved: {OUT_TXT}")


if __name__ == "__main__":
    main()
