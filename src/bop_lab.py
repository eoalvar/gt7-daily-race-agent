import json
import re
import time
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from bop_database import (
    load_database,
    save_database,
    database_stats,
    validate_database,
    normalize_group,
)

VERSION = "1.3"

DG_EDGE_BASE_URL = "https://www.dg-edge.com"
DG_EDGE_BOP_URL = f"{DG_EDGE_BASE_URL}/database/bop"

DATA_DIR = Path("data") / "bop_lab"
REPORT_DIR = Path("reports")
RAW_DIR = DATA_DIR / "raw"
JS_DIR = RAW_DIR / "js"

REPORT_FILE = REPORT_DIR / "bop_lab.txt"
MECHANISM_FILE = DATA_DIR / "speed_switch_mechanism.json"

GROUP = "GR.3"

REQUEST_TIMEOUT = 60
REQUEST_DELAY_SECONDS = 0.20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}

SEP = "=" * 100
SUB = "-" * 100

SEARCH_TERMS = [
    "speed-0",
    "speed-1",
    "speed-2",
    'name="speed"',
    "High",
    "Low",
    "Mid",
    "localStorage",
    "sessionStorage",
    "document.cookie",
    "cookie",
    "fetch(",
    "XMLHttpRequest",
    "axios",
    "htmx",
    "location.href",
    "window.location",
    "URLSearchParams",
    "FormData",
    "change",
    "onclick",
    "onchange",
    "/database/bop",
]


def now_iso():
    return datetime.now().astimezone().isoformat()


def clean_text(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\xa0", " ")).strip()


def safe_filename(value):
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value))
    return text.strip("_") or "script.js"


def version_key(version):
    try:
        return tuple(int(part) for part in str(version).split("."))
    except Exception:
        return (0,)


def fetch_text(session, url, params=None, raise_for_status=True):
    response = session.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT,
    )

    result = {
        "requested_url": url,
        "url": response.url,
        "status": response.status_code,
        "text": response.text,
        "bytes": len(response.content),
        "content_type": response.headers.get("Content-Type", ""),
        "headers": dict(response.headers),
    }

    if raise_for_status:
        response.raise_for_status()

    return result


def build_group_url(group, version):
    group = normalize_group(group)
    if not group:
        raise ValueError(f"Invalid group: {group}")
    return f"{DG_EDGE_BOP_URL}/{group}/{version}"


def extract_versions(html):
    soup = BeautifulSoup(html, "html.parser")
    versions = set()

    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        match = re.search(
            r"/database/bop/(?:GR\.[1234]|GR\.B)/(\d+\.\d+)",
            href,
            flags=re.IGNORECASE,
        )
        if match:
            versions.add(match.group(1))

    if not versions:
        text = soup.get_text(" ", strip=True)
        for match in re.finditer(
            r"\b(?:Update|Version)\s+(\d+\.\d+)\b",
            text,
            flags=re.IGNORECASE,
        ):
            versions.add(match.group(1))

    return sorted(versions, key=version_key, reverse=True)


def looks_like_valid_bop_page(html, group):
    if not html:
        return False

    soup = BeautifulSoup(html, "html.parser")
    text = clean_text(soup.get_text(" ", strip=True)).lower()
    group_text = (normalize_group(group) or "").lower()

    signals = [
        "max power",
        "max torque",
        "power/weight",
        "weight balance",
        "drivetrain",
    ]

    signal_count = sum(1 for signal in signals if signal in text)

    return group_text in text and signal_count >= 3


def probe_versions(session, group, versions):
    probes = []

    for version in versions:
        url = build_group_url(group, version)
        result = fetch_text(
            session,
            url,
            raise_for_status=False,
        )

        valid = (
            result["status"] == 200
            and looks_like_valid_bop_page(result["text"], group)
        )

        probes.append(
            {
                "version": version,
                "url": url,
                "status": result["status"],
                "bytes": result["bytes"],
                "valid": valid,
            }
        )

        print(
            f"Probe {group} {version:<6}: "
            f"HTTP {result['status']} | "
            f"{result['bytes']:,} bytes | "
            f"{'VALID' if valid else 'UNUSABLE'}"
        )

        if valid:
            return version, result, probes

        time.sleep(REQUEST_DELAY_SECONDS)

    return None, None, probes


def save_raw_page(group, version, html):
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    group_safe = group.replace(".", "").lower()

    path = RAW_DIR / (
        f"{group_safe}_{version}_mechanism.html"
    )

    path.write_text(html, encoding="utf-8")
    return path


def save_script(index, source_url, text):
    JS_DIR.mkdir(parents=True, exist_ok=True)

    parsed = urlparse(source_url)
    basename = Path(parsed.path).name or f"script_{index:02d}.js"

    filename = f"{index:02d}_{safe_filename(basename)}"
    path = JS_DIR / filename
    path.write_text(text, encoding="utf-8")
    return path


def element_attributes(tag):
    output = {}

    for key, value in tag.attrs.items():
        if isinstance(value, list):
            value = " ".join(str(item) for item in value)
        output[key] = str(value)

    return output


def inspect_speed_controls(html):
    soup = BeautifulSoup(html, "html.parser")
    controls = []

    for input_tag in soup.find_all(
        "input",
        attrs={"name": "speed"},
    ):
        identifier = input_tag.get("id")
        label = None

        if identifier:
            label_tag = soup.find(
                "label",
                attrs={"for": identifier},
            )
            if label_tag:
                label = clean_text(
                    label_tag.get_text(" ", strip=True)
                )

        parent = input_tag.parent

        parent_info = None
        if parent:
            parent_info = {
                "tag": parent.name,
                "attributes": element_attributes(parent),
                "text": clean_text(
                    parent.get_text(" ", strip=True)
                )[:500],
            }

        form = input_tag.find_parent("form")

        form_info = None
        if form:
            form_info = {
                "attributes": element_attributes(form),
                "text": clean_text(
                    form.get_text(" ", strip=True)
                )[:1000],
            }

        controls.append(
            {
                "label": label,
                "attributes": element_attributes(input_tag),
                "parent": parent_info,
                "form": form_info,
            }
        )

    return controls


def extract_script_inventory(html, page_url):
    soup = BeautifulSoup(html, "html.parser")
    scripts = []

    for index, tag in enumerate(
        soup.find_all("script"),
        start=1,
    ):
        src = tag.get("src")

        if src:
            scripts.append(
                {
                    "index": index,
                    "kind": "external",
                    "src": urljoin(page_url, src),
                    "attributes": element_attributes(tag),
                    "inline_text": "",
                }
            )
        else:
            text = tag.string
            if text is None:
                text = tag.get_text("\n")

            scripts.append(
                {
                    "index": index,
                    "kind": "inline",
                    "src": None,
                    "attributes": element_attributes(tag),
                    "inline_text": text or "",
                }
            )

    return scripts


def context_snippet(text, start, end, radius=240):
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    return text[left:right].replace("\r", " ").strip()


def find_terms(text, source_name):
    findings = []

    if not text:
        return findings

    for term in SEARCH_TERMS:
        pattern = re.compile(
            re.escape(term),
            flags=re.IGNORECASE,
        )

        for match in list(pattern.finditer(text))[:20]:
            findings.append(
                {
                    "source": source_name,
                    "term": term,
                    "position": match.start(),
                    "snippet": context_snippet(
                        text,
                        match.start(),
                        match.end(),
                    ),
                }
            )

    return findings


def inspect_interactive_attributes(html):
    soup = BeautifulSoup(html, "html.parser")
    results = []

    interesting_prefixes = (
        "on",
        "hx-",
        "data-",
        "x-",
        "wire:",
        "@",
        "v-",
    )

    for tag in soup.find_all(True):
        attrs = element_attributes(tag)
        interesting = {}

        for key, value in attrs.items():
            lowered = key.lower()

            if (
                lowered.startswith(interesting_prefixes)
                or "speed" in lowered
                or "bop" in lowered
                or "ajax" in lowered
            ):
                interesting[key] = value

        if not interesting:
            continue

        combined = (
            clean_text(tag.get_text(" ", strip=True))
            + " "
            + " ".join(
                f"{key}={value}"
                for key, value in interesting.items()
            )
        ).lower()

        if any(
            token in combined
            for token in [
                "speed",
                "bop",
                "high",
                "low",
                "mid",
            ]
        ):
            results.append(
                {
                    "tag": tag.name,
                    "attributes": interesting,
                    "text": clean_text(
                        tag.get_text(" ", strip=True)
                    )[:400],
                }
            )

    return results[:200]


def fetch_external_scripts(session, inventory):
    fetched = []

    for item in inventory:
        if item["kind"] != "external":
            continue

        url = item["src"]
        result = fetch_text(
            session,
            url,
            raise_for_status=False,
        )

        text = (
            result["text"]
            if result["status"] == 200
            else ""
        )

        path = None
        if text:
            path = save_script(
                item["index"],
                url,
                text,
            )

        fetched.append(
            {
                "index": item["index"],
                "url": url,
                "status": result["status"],
                "bytes": result["bytes"],
                "content_type": result["content_type"],
                "saved_path": str(path) if path else None,
                "text": text,
            }
        )

        time.sleep(REQUEST_DELAY_SECONDS)

    return fetched


def classify_mechanism(
    html_findings,
    script_findings,
    controls,
    interactive,
):
    all_findings = html_findings + script_findings
    combined = "\n".join(
        finding["snippet"]
        for finding in all_findings
    ).lower()

    evidence = []

    if "localstorage" in combined:
        evidence.append("localStorage")

    if "sessionstorage" in combined:
        evidence.append("sessionStorage")

    if (
        "document.cookie" in combined
        or re.search(r"\bcookie\b", combined)
    ):
        evidence.append("cookie")

    if (
        "fetch(" in combined
        or "xmlhttprequest" in combined
        or "axios" in combined
    ):
        evidence.append("ajax")

    if (
        "urlsearchparams" in combined
        or "location.href" in combined
        or "window.location" in combined
    ):
        evidence.append("url_navigation")

    form_actions = []

    for control in controls:
        form = control.get("form")

        if not form:
            continue

        attrs = form.get("attributes", {})

        action = attrs.get("action")
        method = attrs.get("method")

        if action or method:
            form_actions.append(
                {
                    "action": action,
                    "method": method,
                }
            )

    if form_actions:
        evidence.append("form_submission")

    if interactive:
        evidence.append("interactive_attributes")

    if not evidence:
        mode = "UNRESOLVED"
    elif "ajax" in evidence:
        mode = "CLIENT_AJAX_OR_SCRIPT"
    elif (
        "localStorage" in evidence
        or "sessionStorage" in evidence
    ):
        mode = "CLIENT_STORAGE"
    elif "cookie" in evidence:
        mode = "COOKIE_OR_CLIENT_STATE"
    elif "form_submission" in evidence:
        mode = "FORM_SUBMISSION"
    elif "url_navigation" in evidence:
        mode = "URL_NAVIGATION"
    else:
        mode = "CLIENT_SIDE_UNKNOWN"

    return {
        "mode": mode,
        "evidence": evidence,
        "form_actions": form_actions,
    }


def build_report(
    selected_version,
    probes,
    raw_path,
    controls,
    inventory,
    fetched_scripts,
    html_findings,
    script_findings,
    interactive,
    classification,
    stats,
    validation,
):
    lines = []

    lines.append(
        "GT7 BOP LAB V1.3 - SPEED SWITCH MECHANISM DIAGNOSTIC"
    )
    lines.append(SEP)
    lines.append(
        f"Generated           : {now_iso()}"
    )
    lines.append(
        f"Group               : {GROUP}"
    )
    lines.append(
        f"Selected version    : {selected_version}"
    )
    lines.append(
        "Production modified : NO"
    )
    lines.append(
        f"Raw HTML            : {raw_path}"
    )

    lines.append("")
    lines.append("VERSION PROBES")
    lines.append(SUB)

    for probe in probes:
        lines.append(
            f"{probe['version']:<8} | "
            f"HTTP {probe['status']:<3} | "
            f"{probe['bytes']:>8,} bytes | "
            f"{'VALID' if probe['valid'] else 'UNUSABLE'}"
        )

    lines.append("")
    lines.append("SPEED CONTROLS")
    lines.append(SUB)
    lines.append(
        f"Controls found      : {len(controls)}"
    )

    for index, control in enumerate(
        controls,
        start=1,
    ):
        lines.append(f"Control {index}")
        lines.append(
            f"  Label             : "
            f"{control.get('label')}"
        )
        lines.append(
            f"  Attributes        : "
            f"{control.get('attributes')}"
        )
        lines.append(
            f"  Parent            : "
            f"{control.get('parent')}"
        )
        lines.append(
            f"  Form              : "
            f"{control.get('form')}"
        )

    lines.append("")
    lines.append("SCRIPT INVENTORY")
    lines.append(SUB)
    lines.append(
        f"Scripts found       : {len(inventory)}"
    )

    for item in inventory:
        if item["kind"] == "external":
            lines.append(
                f"#{item['index']:02d} EXTERNAL | "
                f"{item['src']}"
            )
        else:
            lines.append(
                f"#{item['index']:02d} INLINE   | "
                f"{len(item['inline_text']):,} chars"
            )

    lines.append("")
    lines.append("EXTERNAL SCRIPT FETCH")
    lines.append(SUB)

    for item in fetched_scripts:
        lines.append(
            f"#{item['index']:02d} | "
            f"HTTP {item['status']} | "
            f"{item['bytes']:,} bytes | "
            f"{item['url']} | "
            f"saved={item['saved_path']}"
        )

    lines.append("")
    lines.append("INTERACTIVE ATTRIBUTES")
    lines.append(SUB)
    lines.append(
        f"Relevant elements   : {len(interactive)}"
    )

    for item in interactive[:80]:
        lines.append(str(item))

    lines.append("")
    lines.append("HTML FINDINGS")
    lines.append(SUB)
    lines.append(
        f"Matches             : {len(html_findings)}"
    )

    for finding in html_findings[:120]:
        lines.append(
            f"[{finding['term']}] "
            f"pos={finding['position']}"
        )
        lines.append(
            finding["snippet"]
        )
        lines.append("")

    lines.append("SCRIPT FINDINGS")
    lines.append(SUB)
    lines.append(
        f"Matches             : {len(script_findings)}"
    )

    for finding in script_findings[:180]:
        lines.append(
            f"[{finding['source']}] "
            f"[{finding['term']}] "
            f"pos={finding['position']}"
        )
        lines.append(
            finding["snippet"]
        )
        lines.append("")

    lines.append("MECHANISM CLASSIFICATION")
    lines.append(SUB)
    lines.append(
        f"Mode                : "
        f"{classification['mode']}"
    )
    lines.append(
        f"Evidence            : "
        f"{', '.join(classification['evidence']) or 'none'}"
    )
    lines.append(
        f"Form actions        : "
        f"{classification['form_actions']}"
    )

    lines.append("")
    lines.append("DATABASE")
    lines.append(SUB)
    lines.append(
        f"Records             : {stats['records']}"
    )
    lines.append(
        f"Validation          : "
        f"{'PASSED' if validation['valid'] else 'FAILED'}"
    )

    lines.append("")
    lines.append("IMPORTANT")
    lines.append(SUB)
    lines.append(
        "V1.3 does NOT write BoP car records."
    )
    lines.append(
        "Its purpose is to discover how DG EDGE switches "
        "between HIGH / LOW / MID."
    )
    lines.append(
        "After the mechanism is identified, the next version "
        "will fetch the three real tables and validate that "
        "their car fingerprints differ."
    )
    lines.append(SEP)

    return "\n".join(lines)


def main():
    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )
    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )
    RAW_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )
    JS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    print()
    print(f"GT7 BOP LAB V{VERSION}")
    print(SEP)
    print("Experimental pipeline.")
    print(
        "The production Daily Race C agent "
        "is NOT modified."
    )
    print()

    session = requests.Session()
    session.headers.update(HEADERS)

    print("READING DG EDGE BOP INDEX")
    print(SUB)

    index_result = fetch_text(
        session,
        DG_EDGE_BOP_URL,
    )

    print(
        f"HTTP status        : "
        f"{index_result['status']}"
    )
    print(
        f"Response bytes     : "
        f"{index_result['bytes']:,}"
    )

    versions = extract_versions(
        index_result["text"]
    )

    print(
        f"Versions detected  : "
        f"{', '.join(versions)}"
    )

    if not versions:
        raise RuntimeError(
            "No BoP versions discovered."
        )

    print()
    print("PROBING GR.3 VERSIONS")
    print(SUB)

    (
        selected_version,
        source,
        probes,
    ) = probe_versions(
        session,
        GROUP,
        versions,
    )

    if not selected_version:
        raise RuntimeError(
            "No usable DG EDGE GR.3 BoP page was found."
        )

    page_url = build_group_url(
        GROUP,
        selected_version,
    )

    html = source["text"]

    raw_path = save_raw_page(
        GROUP,
        selected_version,
        html,
    )

    print()
    print("SELECTED BOP PAGE")
    print(SUB)
    print(
        f"Group              : {GROUP}"
    )
    print(
        f"Version            : {selected_version}"
    )
    print(
        f"URL                : {page_url}"
    )
    print(
        f"Raw HTML           : {raw_path}"
    )

    print()
    print("INSPECTING SPEED CONTROLS")
    print(SUB)

    controls = inspect_speed_controls(
        html
    )

    print(
        f"Controls found     : {len(controls)}"
    )

    for control in controls:
        print(
            f"{control.get('label')} | "
            f"{control.get('attributes')}"
        )

    print()
    print("DISCOVERING SCRIPTS")
    print(SUB)

    inventory = extract_script_inventory(
        html,
        page_url,
    )

    external_count = sum(
        1
        for item in inventory
        if item["kind"] == "external"
    )
    inline_count = sum(
        1
        for item in inventory
        if item["kind"] == "inline"
    )

    print(
        f"Scripts total      : {len(inventory)}"
    )
    print(
        f"External           : {external_count}"
    )
    print(
        f"Inline             : {inline_count}"
    )

    print()
    print("FETCHING EXTERNAL SCRIPTS")
    print(SUB)

    fetched_scripts = fetch_external_scripts(
        session,
        inventory,
    )

    for item in fetched_scripts:
        print(
            f"#{item['index']:02d} | "
            f"HTTP {item['status']} | "
            f"{item['bytes']:,} bytes | "
            f"{item['url']}"
        )

    html_findings = find_terms(
        html,
        "PAGE_HTML",
    )

    script_findings = []

    for item in inventory:
        if item["kind"] != "inline":
            continue

        script_findings.extend(
            find_terms(
                item["inline_text"],
                f"INLINE_SCRIPT_{item['index']:02d}",
            )
        )

    for item in fetched_scripts:
        script_findings.extend(
            find_terms(
                item["text"],
                f"EXTERNAL_SCRIPT_{item['index']:02d}",
            )
        )

    interactive = inspect_interactive_attributes(
        html
    )

    classification = classify_mechanism(
        html_findings,
        script_findings,
        controls,
        interactive,
    )

    print()
    print("MECHANISM CLASSIFICATION")
    print(SUB)
    print(
        f"Mode               : "
        f"{classification['mode']}"
    )
    print(
        f"Evidence           : "
        f"{', '.join(classification['evidence']) or 'none'}"
    )

    database = load_database()
    save_database(database)

    stats = database_stats()
    validation = validate_database()

    payload = {
        "generated_at": now_iso(),
        "lab_version": VERSION,
        "group": GROUP,
        "selected_version": selected_version,
        "page_url": page_url,
        "controls": controls,
        "scripts": [
            {
                key: value
                for key, value in item.items()
                if key != "inline_text"
            }
            for item in inventory
        ],
        "external_scripts": [
            {
                key: value
                for key, value in item.items()
                if key != "text"
            }
            for item in fetched_scripts
        ],
        "interactive_attributes": interactive,
        "html_findings": html_findings,
        "script_findings": script_findings,
        "classification": classification,
        "production_pipeline_modified": False,
    }

    MECHANISM_FILE.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    report = build_report(
        selected_version=selected_version,
        probes=probes,
        raw_path=raw_path,
        controls=controls,
        inventory=inventory,
        fetched_scripts=fetched_scripts,
        html_findings=html_findings,
        script_findings=script_findings,
        interactive=interactive,
        classification=classification,
        stats=stats,
        validation=validation,
    )

    REPORT_FILE.write_text(
        report,
        encoding="utf-8",
    )

    print()
    print(report)

    print()
    print("FILES CREATED")
    print(SUB)
    print(
        f"Report             : {REPORT_FILE}"
    )
    print(
        f"Mechanism JSON     : {MECHANISM_FILE}"
    )
    print(
        f"Raw HTML           : {raw_path}"
    )
    print(
        f"Saved JS directory : {JS_DIR}"
    )
    print(SEP)


if __name__ == "__main__":
    main()