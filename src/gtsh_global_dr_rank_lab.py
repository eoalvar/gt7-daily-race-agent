from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

PSN_ID = "crazy_rooster74"
RANKING_URL = "https://gtsh-rank.com/ranking/"
OUT_JSON = Path("data/gtsh_global_dr_rank_lab.json")
OUT_TXT = Path("reports/gtsh_global_dr_rank_lab.txt")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/json,text/plain,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def compact(text: str, n: int = 1800) -> str:
    return re.sub(r"\s+", " ", text or "").strip()[:n]


def inspect_payload(payload):
    info = {"type": type(payload).__name__}
    if isinstance(payload, dict):
        info["keys"] = sorted(str(k) for k in payload.keys())[:80]
        for key in ("total", "count", "recordsTotal", "total_players", "totalPlayers", "records", "total_records"):
            if isinstance(payload.get(key), (int, float)):
                info["total_key"] = key
                info["total"] = int(payload[key])
                break
        for key in ("board", "ranking", "data", "entries", "results", "drivers", "users", "rows"):
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


def describe_form(form):
    out = {
        "method": (form.get("method") or "GET").upper(),
        "action": form.get("action"),
        "inputs": [],
        "selects": [],
    }
    for inp in form.find_all("input"):
        out["inputs"].append({
            "type": inp.get("type"),
            "name": inp.get("name"),
            "value": inp.get("value"),
            "id": inp.get("id"),
        })
    for sel in form.find_all("select"):
        options = []
        for opt in sel.find_all("option"):
            options.append({
                "value": opt.get("value"),
                "text": compact(opt.get_text(" ", strip=True), 120),
                "selected": opt.has_attr("selected"),
            })
        out["selects"].append({
            "name": sel.get("name"),
            "id": sel.get("id"),
            "options": options[:100],
        })
    return out


def request_probe(session, method, url, data=None, params=None, headers=None):
    try:
        if method == "POST":
            r = session.post(url, data=data, params=params, headers=headers, timeout=30)
        else:
            r = session.get(url, params=params, headers=headers, timeout=30)
        ct = r.headers.get("content-type", "")
        item = {
            "method": method,
            "url": r.url,
            "status": r.status_code,
            "content_type": ct,
            "bytes": len(r.content),
            "contains_psn": PSN_ID.casefold() in r.text.casefold(),
            "preview": compact(r.text),
        }
        try:
            payload = r.json()
            item["json"] = inspect_payload(payload)
            item["contains_psn"] = PSN_ID.casefold() in json.dumps(payload, ensure_ascii=False).casefold()
        except Exception:
            pass
        return item
    except Exception as exc:
        return {"method": method, "url": url, "error": str(exc)}


def main():
    session = requests.Session()
    session.headers.update(HEADERS)

    page = session.get(RANKING_URL, timeout=30)
    page.raise_for_status()
    soup = BeautifulSoup(page.text, "html.parser")

    forms = [describe_form(f) for f in soup.find_all("form")]

    selects = []
    for sel in soup.find_all("select"):
        selects.append({
            "name": sel.get("name"),
            "id": sel.get("id"),
            "class": sel.get("class"),
            "options": [
                {
                    "value": o.get("value"),
                    "text": compact(o.get_text(" ", strip=True), 100),
                    "selected": o.has_attr("selected"),
                }
                for o in sel.find_all("option")[:100]
            ],
        })

    links = []
    for a in soup.find_all("a", href=True):
        href = a.get("href")
        text = compact(a.get_text(" ", strip=True), 160)
        if any(token in (href or "").lower() for token in ("rank", "page", "country", "date", "split", "profile")) or any(
            token in text.lower() for token in ("next", "previous", "global", "split", "ranking")
        ):
            links.append({"text": text, "href": href})

    attrs_of_interest = []
    for tag in soup.find_all(True):
        attrs = dict(tag.attrs)
        serialized = json.dumps(attrs, ensure_ascii=False).lower()
        if any(token in serialized for token in ("rank", "country", "date", "split", "page", "offset", "limit", "ajax", "api")):
            attrs_of_interest.append({"tag": tag.name, "attrs": attrs, "text": compact(tag.get_text(" ", strip=True), 160)})
            if len(attrs_of_interest) >= 250:
                break

    scripts = []
    for tag in soup.find_all("script"):
        src = tag.get("src")
        text = tag.get_text(" ", strip=True)
        if src or text:
            scripts.append({"src": src, "text": compact(text, 6000)})

    # Generic URL/query probes plus variants inferred from common select names.
    probes = []
    generic = [
        ("GET", RANKING_URL, None, {"page": 2}),
        ("GET", RANKING_URL, None, {"p": 2}),
        ("GET", RANKING_URL, None, {"split": 2}),
        ("GET", RANKING_URL, None, {"top_split": 2}),
        ("GET", RANKING_URL, None, {"country": "br"}),
        ("GET", RANKING_URL, None, {"region": "br"}),
        ("GET", RANKING_URL, None, {"search": PSN_ID}),
        ("GET", RANKING_URL, None, {"psnid": PSN_ID}),
        ("POST", RANKING_URL, {"search": PSN_ID}, None),
        ("POST", RANKING_URL, {"psnid": PSN_ID}, None),
    ]
    for method, url, data, params in generic:
        probes.append(request_probe(session, method, url, data=data, params=params))

    # Probe each discovered form with its selected/default values, then substitute PSN in likely search fields.
    for form in forms:
        action = urljoin(RANKING_URL, form.get("action") or RANKING_URL)
        method = form.get("method") or "GET"
        base_data = {}
        for inp in form.get("inputs", []):
            name = inp.get("name")
            if name:
                base_data[name] = inp.get("value") or ""
        for sel in form.get("selects", []):
            name = sel.get("name")
            if not name:
                continue
            selected = next((o for o in sel.get("options", []) if o.get("selected")), None)
            first = next((o for o in sel.get("options", []) if o.get("value") not in (None, "")), None)
            chosen = selected or first
            if chosen:
                base_data[name] = chosen.get("value")

        if base_data:
            if method == "POST":
                probes.append(request_probe(session, "POST", action, data=base_data))
            else:
                probes.append(request_probe(session, "GET", action, params=base_data))

        for candidate in ("search", "psnid", "psn", "player", "driver", "query", "q"):
            names = {i.get("name") for i in form.get("inputs", []) if i.get("name")}
            if candidate in names:
                payload = dict(base_data)
                payload[candidate] = PSN_ID
                if method == "POST":
                    probes.append(request_probe(session, "POST", action, data=payload))
                else:
                    probes.append(request_probe(session, "GET", action, params=payload))

    report = {
        "version": "V2",
        "psn_id": PSN_ID,
        "ranking_url": RANKING_URL,
        "page_status": page.status_code,
        "page_bytes": len(page.content),
        "page_contains_psn": PSN_ID.casefold() in page.text.casefold(),
        "forms": forms,
        "selects": selects,
        "links": links[:250],
        "attributes_of_interest": attrs_of_interest,
        "scripts": scripts,
        "probes": probes,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_TXT.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "GTSH GLOBAL DR RANK DISCOVERY LAB V2",
        "=" * 104,
        f"PSN: {PSN_ID}",
        f"Ranking page: status {page.status_code} | {len(page.content):,} bytes",
        f"PSN directly present in HTML: {'YES' if report['page_contains_psn'] else 'NO'}",
        f"Forms found: {len(forms)} | Selects found: {len(selects)} | relevant links: {len(links)}",
        "",
        "FORMS",
    ]
    for i, form in enumerate(forms, 1):
        lines.append(f"[{i}] {form['method']} action={form.get('action')}")
        for inp in form.get("inputs", []):
            lines.append(f"    input name={inp.get('name')} type={inp.get('type')} value={inp.get('value')}")
        for sel in form.get("selects", []):
            vals = [f"{o.get('value')}:{o.get('text')}" for o in sel.get("options", [])[:30]]
            lines.append(f"    select name={sel.get('name')} id={sel.get('id')} options={' | '.join(vals)}")

    lines.extend(["", "STANDALONE SELECTS"])
    for sel in selects:
        vals = [f"{o.get('value')}:{o.get('text')}" for o in sel.get("options", [])[:30]]
        lines.append(f"- name={sel.get('name')} id={sel.get('id')} class={sel.get('class')} | {' | '.join(vals)}")

    lines.extend(["", "RELEVANT LINKS"])
    for link in links[:120]:
        lines.append(f"- {link.get('text')} -> {link.get('href')}")

    lines.extend(["", "ATTRIBUTES OF INTEREST"])
    for item in attrs_of_interest[:120]:
        lines.append(f"- <{item['tag']}> {json.dumps(item['attrs'], ensure_ascii=False)} | {item['text']}")

    lines.extend(["", "PROBES"])
    for i, p in enumerate(probes, 1):
        lines.append(f"[{i}] {p.get('method')} {p.get('url')}")
        if p.get("error"):
            lines.append(f"    ERROR: {p['error']}")
            continue
        lines.append(
            f"    status={p.get('status')} | type={p.get('content_type')} | bytes={p.get('bytes'):,} | contains PSN={p.get('contains_psn')}"
        )
        if p.get("json"):
            lines.append(f"    json={json.dumps(p['json'], ensure_ascii=False)[:1800]}")
        else:
            lines.append(f"    preview={p.get('preview')}")

    lines.extend(["", "SCRIPT SOURCES"])
    for s in scripts:
        if s.get("src"):
            lines.append(f"- {s['src']}")
        elif any(token in (s.get("text") or "").lower() for token in ("fetch", "ajax", "ranking", "offset", "limit", "country", "split")):
            lines.append(f"- inline: {s['text']}")

    OUT_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"Saved: {OUT_JSON}")
    print(f"Saved: {OUT_TXT}")


if __name__ == "__main__":
    main()
