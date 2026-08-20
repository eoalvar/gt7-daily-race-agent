from __future__ import annotations

import base64
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
HEADERS = {
    "User-Agent": "Mozilla/5.0 (GT7 Daily Race Agent DR Lab V4)",
    "Accept": "text/html,application/xhtml+xml,application/json,*/*;q=0.8",
}


def compact(text: str, n: int = 1500) -> str:
    return re.sub(r"\s+", " ", text or "").strip()[:n]


def extract_function(text: str, name: str) -> str:
    """Extract a named JS function using brace balancing."""
    patterns = [
        rf"function\s+{re.escape(name)}\s*\([^)]*\)\s*\{{",
        rf"(?:const|let|var)\s+{re.escape(name)}\s*=\s*(?:async\s*)?\([^)]*\)\s*=>\s*\{{",
        rf"(?:const|let|var)\s+{re.escape(name)}\s*=\s*(?:async\s*)?function\s*\([^)]*\)\s*\{{",
    ]
    start = -1
    brace = -1
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            start = match.start()
            brace = text.find("{", match.start(), match.end() + 1)
            break
    if start < 0 or brace < 0:
        return ""

    depth = 0
    quote = None
    escaped = False
    template_expr_depth = 0
    i = brace
    while i < len(text):
        ch = text[i]
        if escaped:
            escaped = False
            i += 1
            continue
        if ch == "\\":
            escaped = True
            i += 1
            continue

        if quote:
            if quote == "`" and ch == "$" and i + 1 < len(text) and text[i + 1] == "{":
                template_expr_depth += 1
                i += 2
                continue
            if quote == "`" and template_expr_depth > 0:
                if ch == "{":
                    template_expr_depth += 1
                elif ch == "}":
                    template_expr_depth -= 1
                i += 1
                continue
            if ch == quote:
                quote = None
            i += 1
            continue

        if ch in ("'", '"', "`"):
            quote = ch
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
        i += 1
    return text[start:]


def extract_literal_assignments(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    pattern = re.compile(
        r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*([`'\"])(.*?)\2\s*;",
        flags=re.DOTALL,
    )
    for match in pattern.finditer(text):
        values[match.group(1)] = match.group(3)
    return values


def substitute_js_template(value: str, variables: dict[str, str]) -> str | None:
    value = value.replace("${encodeURIComponent(psnid)}", PSN_ID)
    value = value.replace("${encodeURIComponent(psnId)}", PSN_ID)
    value = value.replace("${encodeURIComponent(id)}", PSN_ID)
    value = value.replace("${psnid}", PSN_ID)
    value = value.replace("${psnId}", PSN_ID)
    value = value.replace("${id}", PSN_ID)

    for key, val in variables.items():
        value = value.replace("${" + key + "}", val)

    if "${" in value:
        return None
    return value


def extract_fetch_details(function_text: str, all_text: str) -> list[dict]:
    local_vars = extract_literal_assignments(function_text)
    global_vars = extract_literal_assignments(all_text)
    variables = {**global_vars, **local_vars}
    calls = []

    # Direct quoted/template fetch URL.
    for match in re.finditer(r"fetch\s*\(\s*([`'\"])(.*?)\1\s*(?:,\s*(\{.*?\}))?\s*\)", function_text, flags=re.DOTALL):
        raw = match.group(2)
        resolved = substitute_js_template(raw, variables)
        calls.append({
            "expression": raw,
            "resolved": urljoin(PROFILE_URL, resolved) if resolved else None,
            "options": compact(match.group(3) or "", 3000),
        })

    # fetch(variable, ...)
    for match in re.finditer(r"fetch\s*\(\s*([A-Za-z_$][\w$]*)\s*(?:,\s*(\{.*?\}))?\s*\)", function_text, flags=re.DOTALL):
        var = match.group(1)
        raw = variables.get(var)
        resolved = substitute_js_template(raw, variables) if raw else None
        calls.append({
            "expression": var,
            "variable_value": raw,
            "resolved": urljoin(PROFILE_URL, resolved) if resolved else None,
            "options": compact(match.group(2) or "", 3000),
        })

    # More tolerant: capture the first argument line even if options are complex.
    for match in re.finditer(r"fetch\s*\(\s*([^,\n\)]+)", function_text, flags=re.DOTALL):
        expr = match.group(1).strip()
        if any(item.get("expression") == expr.strip("`'\"") for item in calls):
            continue
        resolved = None
        if expr in variables:
            raw = variables[expr]
            val = substitute_js_template(raw, variables)
            resolved = urljoin(PROFILE_URL, val) if val else None
        elif len(expr) >= 2 and expr[0] in "`'\"" and expr[-1] == expr[0]:
            val = substitute_js_template(expr[1:-1], variables)
            resolved = urljoin(PROFILE_URL, val) if val else None
        calls.append({"expression": expr, "resolved": resolved, "options": ""})

    dedup = []
    seen = set()
    for item in calls:
        key = (item.get("expression"), item.get("resolved"))
        if key not in seen:
            seen.add(key)
            dedup.append(item)
    return dedup


def extract_key_candidates(function_text: str, all_text: str) -> list[dict]:
    combined = function_text + "\n" + all_text
    results = []

    # Locate xorDecrypt(..., keyExpression).
    for match in re.finditer(r"xorDecrypt\s*\(\s*[^,]+,\s*([^\)]+)\)", function_text, flags=re.DOTALL):
        expr = match.group(1).strip()
        item = {"expression": expr}
        if re.fullmatch(r"[`'\"].*?[`'\"]", expr, flags=re.DOTALL):
            item["literal"] = expr[1:-1]
        else:
            assign = re.search(
                rf"(?:const|let|var)\s+{re.escape(expr)}\s*=\s*([`'\"])(.*?)\1",
                combined,
                flags=re.DOTALL,
            )
            if assign:
                item["literal"] = assign.group(2)
        results.append(item)

    return results


def xor_decrypt_bytes(data: bytes, key: str) -> str:
    key_bytes = key.encode("utf-8")
    if not key_bytes:
        raise ValueError("Empty XOR key")
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


def infer_request(function_text: str, fetch_item: dict) -> dict:
    options = fetch_item.get("options") or ""
    context = function_text
    method = "POST" if re.search(r"method\s*:\s*['\"]POST['\"]", options + context, flags=re.IGNORECASE) else "GET"

    headers = {}
    if "application/json" in options + context:
        headers["Content-Type"] = "application/json"

    body = None
    # Common GTSH profile payload patterns.
    body_match = re.search(r"body\s*:\s*JSON\.stringify\s*\(\s*\{(.*?)\}\s*\)", context, flags=re.DOTALL)
    if body_match:
        body_source = body_match.group(1)
        payload = {}
        # Interpret keys that clearly refer to PSN id.
        for key, value in re.findall(r"([A-Za-z_$][\w$]*)\s*:\s*([^,}\n]+)", body_source):
            val = value.strip()
            if any(token in val.lower() for token in ("psnid", "psn_id", "onlineid", "online_id")):
                payload[key] = PSN_ID
            elif re.fullmatch(r"[`'\"].*?[`'\"]", val):
                payload[key] = val[1:-1]
        if payload:
            body = payload

    # Handle shorthand { psnid } in JSON.stringify.
    short_match = re.search(r"body\s*:\s*JSON\.stringify\s*\(\s*\{\s*(psnid|psnId|psn_id|onlineId|online_id)\s*\}\s*\)", context)
    if short_match:
        body = {short_match.group(1): PSN_ID}

    return {"method": method, "headers": headers, "json_body": body}


def probe_request(session: requests.Session, url: str, request_info: dict, key_candidates: list[dict]) -> dict:
    result = {
        "url": url,
        "request": request_info,
        "status": None,
        "content_type": None,
        "preview": None,
        "resolved_user": None,
        "decrypt_attempts": [],
    }
    try:
        kwargs = {"timeout": 45, "headers": request_info.get("headers") or {}}
        if request_info.get("json_body") is not None:
            kwargs["json"] = request_info["json_body"]
        response = session.request(request_info.get("method", "GET"), url, **kwargs)
        result["status"] = response.status_code
        result["content_type"] = response.headers.get("content-type", "")
        result["preview"] = compact(response.text, 1200)

        try:
            payload = response.json()
        except Exception:
            payload = None

        if payload is not None:
            user = recursively_find_user(payload)
            if isinstance(user, dict):
                result["resolved_user"] = user
                return result

            # Expected GTSH wrapper: { data: <base64 encrypted> }
            encrypted_b64 = payload.get("data") if isinstance(payload, dict) else None
            if isinstance(encrypted_b64, str):
                for item in key_candidates:
                    key = item.get("literal")
                    if not key:
                        continue
                    attempt = {"key_expression": item.get("expression"), "key_length": len(key)}
                    try:
                        raw = base64.b64decode(encrypted_b64)
                        decrypted = xor_decrypt_bytes(raw, key)
                        attempt["preview"] = compact(decrypted, 1000)
                        decoded_payload = json.loads(decrypted)
                        user = recursively_find_user(decoded_payload)
                        if isinstance(user, dict):
                            attempt["success"] = True
                            result["resolved_user"] = user
                            result["decoded_payload"] = decoded_payload
                            result["decrypt_attempts"].append(attempt)
                            return result
                        attempt["success"] = False
                    except Exception as exc:
                        attempt["success"] = False
                        attempt["error"] = str(exc)
                    result["decrypt_attempts"].append(attempt)
    except Exception as exc:
        result["error"] = str(exc)
    return result


def main():
    session = requests.Session()
    session.headers.update(HEADERS)

    response = session.get(PROFILE_URL, timeout=30)
    response.raise_for_status()
    html = response.text
    soup = BeautifulSoup(html, "html.parser")
    inline_scripts = [script.get_text(" ", strip=False) for script in soup.find_all("script") if not script.get("src")]
    combined = "\n".join(inline_scripts)

    get_profile = extract_function(combined, "getProfile")
    xor_decrypt = extract_function(combined, "xorDecrypt")

    fetch_calls = extract_fetch_details(get_profile, combined) if get_profile else []
    key_candidates = extract_key_candidates(get_profile, combined) if get_profile else []

    probes = []
    resolved_user = None

    for item in fetch_calls:
        url = item.get("resolved")
        if not url:
            continue
        request_info = infer_request(get_profile, item)
        probe = probe_request(session, url, request_info, key_candidates)
        probes.append(probe)
        if isinstance(probe.get("resolved_user"), dict):
            resolved_user = probe["resolved_user"]
            break

    report = {
        "version": "V4",
        "psn_id": PSN_ID,
        "profile_url": PROFILE_URL,
        "confirmed_schema": {
            "dr_points": "data.monthly_stats.result.user.dr_points",
            "dr_percentage": "data.monthly_stats.result.user.dr_percentage",
            "driver_rating": "data.monthly_stats.result.user.driver_rating",
            "mapping": {"1": "E", "2": "D", "3": "C", "4": "B", "5": "A", "6": "A+", "7": "S"},
        },
        "get_profile_function": get_profile,
        "xor_decrypt_function": xor_decrypt,
        "fetch_calls": fetch_calls,
        "key_candidates": key_candidates,
        "probes": probes,
        "resolved_user": resolved_user,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_TXT.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "GTSH DR POINTS DISCOVERY LAB V4",
        "=" * 104,
        f"PSN ID: {PSN_ID}",
        "Scope: public GTSH web client only; no official GT7 API.",
        "",
        "RESOLVED USER DATA",
    ]

    if resolved_user:
        for key in ("np_online_id", "driver_rating", "dr_level", "dr_points", "dr_percentage", "sportsmanship_rating"):
            if key in resolved_user:
                lines.append(f"- {key}: {resolved_user.get(key)}")
    else:
        lines.append("- not resolved yet")

    lines.extend(["", "FETCH CALLS RECONSTRUCTED"])
    if fetch_calls:
        for item in fetch_calls:
            lines.append(
                f"- expr={item.get('expression')} | resolved={item.get('resolved')} | options={item.get('options')}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "XOR KEY CANDIDATES"])
    if key_candidates:
        for item in key_candidates:
            lines.append(
                f"- expression={item.get('expression')} | literal_found={'YES' if item.get('literal') else 'NO'}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "REQUEST / DECRYPT PROBES"])
    if probes:
        for probe in probes:
            lines.append(
                f"- {probe.get('request', {}).get('method')} {probe.get('url')} | "
                f"status={probe.get('status')} | type={probe.get('content_type')} | "
                f"user_found={'YES' if probe.get('resolved_user') else 'NO'} | preview={probe.get('preview')}"
            )
            for attempt in probe.get("decrypt_attempts", []):
                lines.append(
                    f"  decrypt key={attempt.get('key_expression')} | success={attempt.get('success')} | "
                    f"preview={attempt.get('preview')} | error={attempt.get('error')}"
                )
    else:
        lines.append("- none")

    lines.extend(["", "FULL getProfile() FUNCTION", "-" * 104])
    lines.append(get_profile or "- not found")
    lines.extend(["", "FULL xorDecrypt() FUNCTION", "-" * 104])
    lines.append(xor_decrypt or "- not found")

    OUT_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:120]))
    print(f"Saved: {OUT_JSON}")
    print(f"Saved: {OUT_TXT}")


if __name__ == "__main__":
    main()
