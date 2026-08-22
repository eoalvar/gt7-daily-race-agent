from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

TARGET = "crazy_rooster74"
SAMPLE_PSNS = ["crazy_rooster74", "BSCOMP_Aphe", "Didico__15", "SFE_BRacer"]
BASE = "https://gtsh-rank.com"
PROFILE = f"{BASE}/profile/?id={TARGET}"
RANKING = f"{BASE}/ranking/"
OUT_JSON = Path("data/gtsh_dr_batch_distribution_lab.json")
OUT_TXT = Path("reports/gtsh_dr_batch_distribution_lab.txt")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (GT7 Daily Race Agent DR Batch Lab)",
    "Accept": "text/html,application/json,text/plain,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def compact(text, n=1200):
    return re.sub(r"\s+", " ", text or "").strip()[:n]


def xor_decrypt(data: bytes, key: str) -> str:
    kb = key.encode("utf-8")
    return bytes(b ^ kb[i % len(kb)] for i, b in enumerate(data)).decode("utf-8")


def response_summary(r, target=TARGET):
    out = {
        "url": r.url,
        "status": r.status_code,
        "content_type": r.headers.get("content-type", ""),
        "bytes": len(r.content),
        "contains_target": target.casefold() in r.text.casefold(),
        "preview": compact(r.text),
    }
    try:
        payload = r.json()
        out["json_type"] = type(payload).__name__
        if isinstance(payload, dict):
            out["json_keys"] = sorted(payload.keys())[:40]
            for k in ("total", "count", "recordsTotal", "total_players", "totalPlayers", "total_records"):
                if isinstance(payload.get(k), (int, float)):
                    out["total_key"] = k
                    out["total"] = int(payload[k])
        out["json_contains_target"] = target.casefold() in json.dumps(payload, ensure_ascii=False).casefold()
    except Exception:
        pass
    return out


def extract_urls_and_tokens(html):
    soup = BeautifulSoup(html, "html.parser")
    candidates = set()
    tokens = []
    for tag in soup.find_all(["script", "a", "form"]):
        src = tag.get("src") or tag.get("href") or tag.get("action")
        if src:
            candidates.add(urljoin(BASE, src))
        txt = tag.get_text(" ", strip=True)
        if txt and any(t in txt.lower() for t in ("api", "ajax", "fetch", "ranking", "profile", "batch", "json")):
            tokens.append(compact(txt, 2500))
    # Raw URL-ish strings and PHP/API paths in source.
    patterns = [
        r"https?://[^\"'\s<>]+",
        r"/[A-Za-z0-9_./-]*(?:api|ajax|ranking|profile|stats|user|driver)[A-Za-z0-9_?=&./-]*",
        r"[A-Za-z0-9_./-]+\.php(?:\?[^\"'\s<>]*)?",
    ]
    for pat in patterns:
        for m in re.findall(pat, html, flags=re.I):
            candidates.add(urljoin(BASE, m))
    return sorted(candidates), tokens


def main():
    s = requests.Session()
    s.headers.update(HEADERS)

    profile_page = s.get(PROFILE, timeout=30)
    profile_page.raise_for_status()
    ranking_page = s.get(RANKING, timeout=30)
    ranking_page.raise_for_status()

    profile_soup = BeautifulSoup(profile_page.text, "html.parser")
    body = profile_soup.find("body")
    xor_key = body.get("header") if body else None

    urls1, tokens1 = extract_urls_and_tokens(profile_page.text)
    urls2, tokens2 = extract_urls_and_tokens(ranking_page.text)
    discovered_urls = sorted(set(urls1 + urls2))

    # Inspect same-origin JS/resources that look relevant.
    resource_inspection = []
    for u in discovered_urls:
        if not u.startswith(BASE):
            continue
        if not any(x in u.lower() for x in (".js", "api", "ajax", "ranking", "profile", ".php")):
            continue
        if u in (PROFILE, RANKING):
            continue
        try:
            r = s.get(u, timeout=20)
            text = r.text
            hits = [line.strip() for line in text.splitlines() if any(k in line.lower() for k in ("fetch(", "ajax", "xmlhttprequest", "psnid", "dr_points", "ranking", "profile"))]
            resource_inspection.append({
                "url": u,
                "status": r.status_code,
                "content_type": r.headers.get("content-type", ""),
                "bytes": len(r.content),
                "interesting_lines": [compact(x, 500) for x in hits[:40]],
            })
        except Exception as exc:
            resource_inspection.append({"url": u, "error": str(exc)})

    probes = []
    post_headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": PROFILE,
        "Origin": BASE,
        "Accept": "application/json,text/plain,*/*",
    }

    # Batch-shape probes against the profile POST endpoint.
    batch_payloads = [
        {"psnid": ",".join(SAMPLE_PSNS)},
        {"psnid": "|".join(SAMPLE_PSNS)},
        {"psnid": json.dumps(SAMPLE_PSNS)},
        {"psnids": ",".join(SAMPLE_PSNS)},
        {"psnids": json.dumps(SAMPLE_PSNS)},
        {"players": json.dumps(SAMPLE_PSNS)},
        {"ids": json.dumps(SAMPLE_PSNS)},
    ]
    for data in batch_payloads:
        try:
            r = s.post(PROFILE, headers=post_headers, data=data, timeout=45)
            item = {"kind": "profile_batch_form", "request_data": data, **response_summary(r)}
            # If encrypted, decrypt enough to know whether multiple users came back.
            try:
                wrapper = r.json()
                if xor_key and isinstance(wrapper, dict) and isinstance(wrapper.get("data"), str):
                    plain = xor_decrypt(base64.b64decode(wrapper["data"]), xor_key)
                    item["decrypted_preview"] = compact(plain, 2500)
                    item["sample_psn_hits"] = {p: p.casefold() in plain.casefold() for p in SAMPLE_PSNS}
            except Exception as exc:
                item["decrypt_probe_error"] = str(exc)
            probes.append(item)
        except Exception as exc:
            probes.append({"kind": "profile_batch_form", "request_data": data, "error": str(exc)})

    # JSON batch variants.
    for payload in (
        {"psnid": SAMPLE_PSNS},
        {"psnids": SAMPLE_PSNS},
        {"players": SAMPLE_PSNS},
        {"ids": SAMPLE_PSNS},
    ):
        try:
            r = s.post(PROFILE, headers={**post_headers, "Content-Type": "application/json"}, json=payload, timeout=45)
            probes.append({"kind": "profile_batch_json", "request_json": payload, **response_summary(r)})
        except Exception as exc:
            probes.append({"kind": "profile_batch_json", "request_json": payload, "error": str(exc)})

    # Ranking/distribution probes: common server-side query names and threshold semantics.
    ranking_params = [
        {"region": "Global", "history": "1day", "country": "all", "split": "all"},
        {"region": "Global", "history": "1day", "country": "all", "split": "2"},
        {"region": "Global", "history": "1day", "country": "all", "limit": "1000"},
        {"region": "Global", "history": "1day", "country": "all", "offset": "80", "limit": "80"},
        {"region": "Global", "history": "1day", "country": "all", "page": "2"},
        {"region": "Global", "history": "1day", "country": "all", "min_dr": "21079"},
        {"region": "Global", "history": "1day", "country": "all", "dr_points": "21079"},
        {"region": "Global", "history": "1day", "country": "all", "threshold": "21079"},
        {"region": "Global", "history": "1day", "country": "all", "format": "json"},
        {"region": "Global", "history": "1day", "country": "all", "ajax": "1"},
        {"region": "Global", "history": "1day", "country": "all", "page_data": "1"},
    ]
    for params in ranking_params:
        try:
            r = s.get(RANKING, params=params, timeout=30)
            soup = BeautifulSoup(r.text, "html.parser")
            rows = soup.select(".ranking-table .data-row, .ranking-row")
            ranks = []
            for node in soup.select(".col-rank-number"):
                m = re.search(r"\d+", node.get_text(" ", strip=True))
                if m:
                    ranks.append(int(m.group()))
            probes.append({
                "kind": "ranking_query",
                "params": params,
                **response_summary(r),
                "parsed_rows": len(rows),
                "parsed_rank_count": len(ranks),
                "min_rank": min(ranks) if ranks else None,
                "max_rank": max(ranks) if ranks else None,
            })
        except Exception as exc:
            probes.append({"kind": "ranking_query", "params": params, "error": str(exc)})

    report = {
        "version": "V1",
        "target": TARGET,
        "sample_psns": SAMPLE_PSNS,
        "xor_key_present": bool(xor_key),
        "discovered_urls": discovered_urls,
        "source_tokens": (tokens1 + tokens2)[:80],
        "resource_inspection": resource_inspection,
        "probes": probes,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_TXT.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "GTSH DR BATCH / DISTRIBUTION DISCOVERY LAB V1",
        "=" * 106,
        f"Target: {TARGET}",
        f"Sample PSNs: {', '.join(SAMPLE_PSNS)}",
        f"XOR key present: {'YES' if xor_key else 'NO'}",
        "",
        "DISCOVERED SAME-ORIGIN RESOURCES / ENDPOINT CLUES",
    ]
    for item in resource_inspection:
        lines.append(f"- {item.get('url')} | status={item.get('status')} | bytes={item.get('bytes')} | error={item.get('error')}")
        for hit in item.get("interesting_lines", [])[:8]:
            lines.append(f"    {hit}")
    lines.extend(["", "PROBES"])
    for i, p in enumerate(probes, 1):
        lines.append(f"[{i}] {p.get('kind')}")
        if p.get("request_data") is not None:
            lines.append(f"    data={p['request_data']}")
        if p.get("request_json") is not None:
            lines.append(f"    json={p['request_json']}")
        if p.get("params") is not None:
            lines.append(f"    params={p['params']}")
        if p.get("error"):
            lines.append(f"    ERROR: {p['error']}")
            continue
        lines.append(f"    status={p.get('status')} type={p.get('content_type')} bytes={p.get('bytes')} target={p.get('contains_target')}")
        if p.get("sample_psn_hits"):
            lines.append(f"    sample hits={p['sample_psn_hits']}")
        if p.get("decrypted_preview"):
            lines.append(f"    decrypted={p['decrypted_preview'][:1200]}")
        if p.get("kind") == "ranking_query":
            lines.append(f"    ranks={p.get('min_rank')}..{p.get('max_rank')} count={p.get('parsed_rank_count')} rows={p.get('parsed_rows')}")
        if p.get("total") is not None:
            lines.append(f"    total={p.get('total')} via {p.get('total_key')}")
    lines.extend(["", "INTERPRETATION", "- Any batch probe returning >1 sample PSN is a viable path to dynamic DR collection.", "- Any ranking probe extending beyond the public Top 80 or exposing a total/threshold count is a viable path to absolute DR rank.", "=" * 106])
    OUT_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"Saved: {OUT_JSON}")
    print(f"Saved: {OUT_TXT}")


if __name__ == "__main__":
    main()
