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
    r"dr[_\- ]?percentage",
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
        r'(?i)(?:dr[_\- ]?points?|dr[_\- ]?percentage|driver[_\- ]?rating[_\- ]?points?|rating[_\- ]?points?)\s*[":=]\s*"?(\d{1,6}(?:\.\d+)?)',
        r'(?i)"(?:drPoints|dr_points|drPercentage|dr_percentage|driverRatingPoints|driver_rating_points|ratingPoints)"\s*:\s*(\d{1,6}(?:\.\d+)?)',
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
            snippet = compact(text[max(0, match.start()-160):match.end()+220], 420)
            if snippet and snippet not in snippets:
                snippets.append(snippet)
            if len(snippets) >= 60:
                return snippets
    return snippets


def same_host(url: str, base: str) -> bool:
    return urlparse(url).netloc == urlparse(base).netloc


def fetch(session, url):
    try:
        r = session.get(url, timeout=30)
        ctype = r.headers.get("content-type", "")
        textual = any(token in ctype for token in ("text", "javascript", "json"))
        return {
            "url": url,
            "status": r.status_code,
            "final_url": r.url,
            "content_type": ctype,
            "text": r.text if textual else "",
        }
    except Exception as exc:
        return {"url": url, "error": str(exc), "text": ""}


def discover_endpoints(text: str, source_url: str, base: str):
    candidates = []

    # Quoted strings that look endpoint-like.
    for match in re.finditer(r'["\']([^"\']*(?:profile|player|user|rating|dr|ajax|api|stats|search)[^"\']*)["\']', text, flags=re.IGNORECASE):
        candidate = match.group(1).strip()
        if not candidate or len(candidate) > 260 or " " in candidate:
            continue
        if candidate.startswith("http") and not same_host(candidate, base):
            continue
        full = urljoin(source_url, candidate)
        if same_host(full, base):
            candidates.append(full)

    # Explicit fetch()/axios URLs, including template literals.
    call_patterns = [
        r"fetch\(\s*([`\"'])(.+?)\1",
        r"axios\.(?:get|post)\(\s*([`\"'])(.+?)\1",
        r"\.open\(\s*[`\"'](?:GET|POST)[`\"']\s*,\s*([`\"'])(.+?)\1",
    ]
    for pattern in call_patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE | re.DOTALL):
            candidate = match.group(2).strip()
            if len(candidate) > 300:
                continue
            # Resolve the PSN template variables commonly used by the page.
            candidate = candidate.replace("${onlineId}", PSN_ID).replace("${id}", PSN_ID).replace("${psnId}", PSN_ID).replace("${psn_id}", PSN_ID)
            candidate = candidate.replace("${encodeURIComponent(onlineId)}", PSN_ID).replace("${encodeURIComponent(id)}", PSN_ID)
            if "${" in candidate:
                continue
            full = urljoin(source_url, candidate)
            if same_host(full, base):
                candidates.append(full)

    return list(dict.fromkeys(candidates))


def parse_json_user(payload):
    if isinstance(payload, dict):
        if isinstance(payload.get("user"), dict):
            return payload.get("user"), payload
        if isinstance(payload.get("result"), dict):
            result = payload["result"]
            if isinstance(result.get("user"), dict):
                return result.get("user"), payload
        if any(key in payload for key in ("dr_points", "dr_percentage", "driver_rating")):
            return payload, payload
    return None, payload


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
        "endpoint_probes": [],
        "resolved_user": None,
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

        # Crucial: the GTSH profile logic is inline, so inspect endpoint calls here too.
        for endpoint in discover_endpoints(text, profile_url, base):
            if endpoint not in report["endpoint_candidates"]:
                report["endpoint_candidates"].append(endpoint)

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
                for endpoint in discover_endpoints(inline, profile_url, base):
                    if endpoint not in report["endpoint_candidates"]:
                        report["endpoint_candidates"].append(endpoint)

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
            for endpoint in discover_endpoints(stext, script_url, base):
                if endpoint not in report["endpoint_candidates"]:
                    report["endpoint_candidates"].append(endpoint)

    # Probe only plausible same-site URLs, prioritizing paths that include the PSN.
    prioritized = sorted(
        list(dict.fromkeys(report["endpoint_candidates"])),
        key=lambda u: (PSN_ID.lower() not in u.lower(), "profile" not in u.lower(), len(u)),
    )[:80]

    for endpoint in prioritized:
        if endpoint.endswith((".js", ".css", ".png", ".jpg", ".svg")):
            continue
        res = fetch(session, endpoint)
        probe = {k: v for k, v in res.items() if k != "text"}
        body = res.get("text", "")
        probe["body_preview"] = compact(body, 500)
        if body:
            try:
                payload = json.loads(body)
                user, _ = parse_json_user(payload)
                probe["json"] = True
                if isinstance(user, dict):
                    probe["user_fields"] = {
                        key: user.get(key)
                        for key in ("np_online_id", "driver_rating", "dr_level", "dr_points", "dr_percentage")
                        if key in user
                    }
                    if any(key in user for key in ("dr_points", "dr_percentage")):
                        report["resolved_user"] = probe["user_fields"]
            except Exception:
                probe["json"] = False
        report["endpoint_probes"].append(probe)
        if report["resolved_user"]:
            break

    # Deduplicate concise outputs.
    seen = set()
    dedup_snips = []
    for item in report["keyword_snippets"]:
        key = (item["source"], item["snippet"])
        if key not in seen:
            seen.add(key)
            dedup_snips.append(item)
    report["keyword_snippets"] = dedup_snips[:120]
    report["endpoint_candidates"] = list(dict.fromkeys(report["endpoint_candidates"]))[:120]

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_TXT.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "GTSH DR POINTS DISCOVERY LAB V2",
        "=" * 88,
        f"PSN ID: {PSN_ID}",
        "Scope: GTSH public web sources only; no official GT7 API.",
        "",
        "CONFIRMED PROFILE SCHEMA",
        "- user.dr_points exists in GTSH profile code",
        "- user.dr_percentage exists in GTSH profile code",
        "- mapping: 1=E, 2=D, 3=C, 4=B, 5=A, 6=A+, 7=S",
        "",
        "RESOLVED USER DATA",
    ]

    if report["resolved_user"]:
        for key, value in report["resolved_user"].items():
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- not resolved yet")

    lines.extend(["", "PROFILE REQUESTS"])
    for src in report["sources"]:
        lines.append(f"- {src.get('url')} | status={src.get('status')} | final={src.get('final_url')} | error={src.get('error')}")

    lines.extend(["", "DISCOVERED ENDPOINTS"])
    for url in prioritized[:50]:
        lines.append(f"- {url}")

    lines.extend(["", "ENDPOINT PROBES"])
    if report["endpoint_probes"]:
        for item in report["endpoint_probes"][:50]:
            lines.append(f"- {item.get('url')} | status={item.get('status')} | type={item.get('content_type')} | user={item.get('user_fields')} | preview={item.get('body_preview')}")
    else:
        lines.append("- none")

    lines.extend(["", "KEY PROFILE CODE EVIDENCE"])
    for item in report["keyword_snippets"][:30]:
        lines.append(f"- {item['source']} | {item['snippet']}")

    OUT_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"Saved: {OUT_JSON}")
    print(f"Saved: {OUT_TXT}")


if __name__ == "__main__":
    main()
