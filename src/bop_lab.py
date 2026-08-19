import json
import re
import time
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from bop_database import (
    load_database,
    save_database,
    database_stats,
    validate_database,
    normalize_group,
)

# ============================================================
# CONFIG
# ============================================================

VERSION = "1.4"

DG_EDGE_BASE_URL = "https://www.dg-edge.com"
DG_EDGE_BOP_URL = f"{DG_EDGE_BASE_URL}/database/bop"

DATA_DIR = Path("data") / "bop_lab"
REPORT_DIR = Path("reports")
RAW_DIR = DATA_DIR / "raw"
STATE_DIR = RAW_DIR / "state"
JS_DIR = RAW_DIR / "js"

REPORT_FILE = REPORT_DIR / "bop_lab.txt"
STATE_ANALYSIS_FILE = DATA_DIR / "nuxt_state_analysis.json"

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

# Strings that are especially useful for this investigation.
EXACT_VALUES = {
    "high",
    "low",
    "mid",
}

KEY_TERMS = (
    "speed",
    "bop",
    "power",
    "weight",
    "torque",
    "pp",
    "car",
    "current",
    "previous",
    "group",
)

JS_SEARCH_TERMS = [
    "speed-0",
    "speed-1",
    "speed-2",
    'name:"speed"',
    "name:'speed'",
    'name="speed"',
    "localStorage",
    "sessionStorage",
    "fetch(",
    "$fetch",
    "useFetch",
    "useAsyncData",
    "watch(",
    "watchEffect",
    "addEventListener",
    "/database/bop",
    "High",
    "Low",
    "Mid",
]


# ============================================================
# BASIC HELPERS
# ============================================================

def now_iso():
    return datetime.now().astimezone().isoformat()


def clean_text(value):
    if value is None:
        return ""

    text = str(value).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def version_key(version):
    try:
        return tuple(
            int(part)
            for part in str(version).split(".")
        )
    except Exception:
        return (0,)


def safe_filename(value):
    text = re.sub(
        r"[^A-Za-z0-9._-]+",
        "_",
        str(value),
    )
    return text.strip("_") or "file"


# ============================================================
# HTTP
# ============================================================

def fetch_text(
    session,
    url,
    params=None,
    raise_for_status=True,
):
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
        "content_type": response.headers.get(
            "Content-Type",
            ""
        ),
    }

    if raise_for_status:
        response.raise_for_status()

    return result


# ============================================================
# VERSION DISCOVERY
# ============================================================

def build_group_url(
    group,
    version,
):
    group = normalize_group(
        group
    )

    if not group:
        raise ValueError(
            f"Invalid group: {group}"
        )

    return (
        f"{DG_EDGE_BOP_URL}/"
        f"{group}/"
        f"{version}"
    )


def extract_versions(
    html,
):
    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    versions = set()

    for link in soup.find_all(
        "a",
        href=True
    ):
        href = link.get(
            "href",
            ""
        )

        match = re.search(
            r"/database/bop/"
            r"(?:GR\.[1234]|GR\.B)"
            r"/(\d+\.\d+)",
            href,
            flags=re.IGNORECASE,
        )

        if match:
            versions.add(
                match.group(1)
            )

    if not versions:
        text = soup.get_text(
            " ",
            strip=True
        )

        for match in re.finditer(
            r"\b(?:Update|Version)\s+"
            r"(\d+\.\d+)\b",
            text,
            flags=re.IGNORECASE,
        ):
            versions.add(
                match.group(1)
            )

    return sorted(
        versions,
        key=version_key,
        reverse=True,
    )


def looks_like_valid_bop_page(
    html,
    group,
):
    if not html:
        return False

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    text = clean_text(
        soup.get_text(
            " ",
            strip=True
        )
    ).lower()

    group_text = (
        normalize_group(
            group
        )
        or ""
    ).lower()

    signals = [
        "max power",
        "max torque",
        "power/weight",
        "weight balance",
        "drivetrain",
    ]

    signal_count = sum(
        1
        for signal in signals
        if signal in text
    )

    return (
        group_text in text
        and signal_count >= 3
    )


def probe_versions(
    session,
    group,
    versions,
):
    probes = []

    for version in versions:
        url = build_group_url(
            group,
            version
        )

        result = fetch_text(
            session,
            url,
            raise_for_status=False,
        )

        valid = (
            result["status"] == 200
            and looks_like_valid_bop_page(
                result["text"],
                group,
            )
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
            return (
                version,
                result,
                probes,
            )

        time.sleep(
            REQUEST_DELAY_SECONDS
        )

    return (
        None,
        None,
        probes,
    )


# ============================================================
# SCRIPT INVENTORY
# ============================================================

def get_script_text(
    tag,
):
    if tag.string is not None:
        return tag.string

    return tag.get_text(
        "\n"
    ) or ""


def script_inventory(
    html,
    page_url,
):
    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    result = []

    for index, tag in enumerate(
        soup.find_all(
            "script"
        ),
        start=1,
    ):
        src = tag.get(
            "src"
        )

        attributes = {
            key:
                (
                    " ".join(
                        str(item)
                        for item in value
                    )
                    if isinstance(
                        value,
                        list
                    )
                    else str(
                        value
                    )
                )
            for key, value
            in tag.attrs.items()
        }

        item = {
            "index":
                index,

            "id":
                tag.get(
                    "id"
                ),

            "type":
                tag.get(
                    "type"
                ),

            "src":
                urljoin(
                    page_url,
                    src
                )
                if src
                else None,

            "attributes":
                attributes,

            "text":
                ""
                if src
                else get_script_text(
                    tag
                ),
        }

        result.append(
            item
        )

    return result


def save_inline_scripts(
    inventory,
):
    STATE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    saved = []

    for item in inventory:
        if item[
            "src"
        ]:
            continue

        text = item[
            "text"
        ]

        if not text.strip():
            continue

        identifier = (
            item.get(
                "id"
            )
            or (
                f"inline_"
                f"{item['index']:02d}"
            )
        )

        suffix = (
            ".json"
            if (
                item.get(
                    "type"
                )
                == "application/json"
            )
            else ".txt"
        )

        path = (
            STATE_DIR
            / (
                f"{item['index']:02d}_"
                f"{safe_filename(identifier)}"
                f"{suffix}"
            )
        )

        path.write_text(
            text,
            encoding="utf-8",
        )

        saved.append(
            {
                "index":
                    item[
                        "index"
                    ],

                "id":
                    item.get(
                        "id"
                    ),

                "type":
                    item.get(
                        "type"
                    ),

                "path":
                    str(
                        path
                    ),

                "chars":
                    len(
                        text
                    ),
            }
        )

    return saved


# ============================================================
# EXTERNAL JS
# ============================================================

def fetch_external_scripts(
    session,
    inventory,
):
    JS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    fetched = []

    for item in inventory:
        url = item.get(
            "src"
        )

        if not url:
            continue

        response = fetch_text(
            session,
            url,
            raise_for_status=False,
        )

        path = None

        if (
            response[
                "status"
            ] == 200
            and response[
                "text"
            ]
        ):
            basename = (
                Path(
                    url.split(
                        "?",
                        1
                    )[0]
                ).name
                or (
                    f"script_"
                    f"{item['index']:02d}.js"
                )
            )

            path = (
                JS_DIR
                / (
                    f"{item['index']:02d}_"
                    f"{safe_filename(basename)}"
                )
            )

            path.write_text(
                response[
                    "text"
                ],
                encoding="utf-8",
            )

        fetched.append(
            {
                "index":
                    item[
                        "index"
                    ],

                "url":
                    url,

                "status":
                    response[
                        "status"
                    ],

                "bytes":
                    response[
                        "bytes"
                    ],

                "path":
                    str(
                        path
                    )
                    if path
                    else None,

                "text":
                    response[
                        "text"
                    ]
                    if response[
                        "status"
                    ] == 200
                    else "",
            }
        )

        time.sleep(
            REQUEST_DELAY_SECONDS
        )

    return fetched


# ============================================================
# JSON / NUXT STATE ANALYSIS
# ============================================================

def try_json_loads(
    text,
):
    try:
        return {
            "ok":
                True,

            "value":
                json.loads(
                    text
                ),

            "error":
                None,
        }

    except Exception as error:
        return {
            "ok":
                False,

            "value":
                None,

            "error":
                str(
                    error
                ),
        }


def shorten_value(
    value,
    max_chars=250,
):
    if isinstance(
        value,
        (
            dict,
            list,
        )
    ):
        try:
            text = json.dumps(
                value,
                ensure_ascii=False,
            )
        except Exception:
            text = str(
                value
            )

    else:
        text = str(
            value
        )

    if len(
        text
    ) > max_chars:
        return (
            text[
                :max_chars
            ]
            + "..."
        )

    return text


def walk_json(
    value,
    path="$",
    depth=0,
    max_depth=20,
):
    if depth > max_depth:
        return

    yield (
        path,
        value
    )

    if isinstance(
        value,
        dict
    ):
        for key, child in value.items():
            child_path = (
                f"{path}."
                f"{key}"
            )

            yield from walk_json(
                child,
                child_path,
                depth + 1,
                max_depth,
            )

    elif isinstance(
        value,
        list
    ):
        for index, child in enumerate(
            value
        ):
            child_path = (
                f"{path}[{index}]"
            )

            yield from walk_json(
                child,
                child_path,
                depth + 1,
                max_depth,
            )


def json_findings(
    value,
):
    exact_values = []
    interesting_keys = []
    interesting_objects = []

    for path, node in walk_json(
        value
    ):
        # ----------------------------------------------------
        # Exact High / Low / Mid values
        # ----------------------------------------------------

        if isinstance(
            node,
            str
        ):
            if (
                node
                .strip()
                .lower()
                in EXACT_VALUES
            ):
                exact_values.append(
                    {
                        "path":
                            path,

                        "value":
                            node,
                    }
                )

        # ----------------------------------------------------
        # Interesting dictionaries
        # ----------------------------------------------------

        if isinstance(
            node,
            dict
        ):
            keys = [
                str(
                    key
                )
                for key in node.keys()
            ]

            lower_keys = [
                key.lower()
                for key in keys
            ]

            matched_keys = [
                key
                for key in keys
                if any(
                    term in key.lower()
                    for term in KEY_TERMS
                )
            ]

            if matched_keys:
                interesting_keys.append(
                    {
                        "path":
                            path,

                        "matched_keys":
                            matched_keys,

                        "all_keys":
                            keys[
                                :80
                            ],
                    }
                )

            # Candidate object if it looks like BoP/car data.
            score = 0

            for key in lower_keys:
                if (
                    "power"
                    in key
                ):
                    score += 1

                if (
                    "weight"
                    in key
                ):
                    score += 1

                if (
                    "torque"
                    in key
                ):
                    score += 1

                if (
                    "car"
                    in key
                    or "name"
                    == key
                ):
                    score += 1

                if (
                    "speed"
                    in key
                    or "bop"
                    in key
                ):
                    score += 1

            if score >= 3:
                interesting_objects.append(
                    {
                        "path":
                            path,

                        "score":
                            score,

                        "keys":
                            keys,

                        "preview":
                            shorten_value(
                                node,
                                max_chars=700,
                            ),
                    }
                )

    return {
        "exact_speed_values":
            exact_values,

        "interesting_keys":
            interesting_keys[
                :500
            ],

        "interesting_objects":
            sorted(
                interesting_objects,
                key=lambda item:
                    item[
                        "score"
                    ],
                reverse=True,
            )[
                :300
            ],
    }


def analyze_inline_state(
    inventory,
):
    analyses = []

    for item in inventory:
        if item[
            "src"
        ]:
            continue

        text = item[
            "text"
        ]

        if not text.strip():
            continue

        parsed = try_json_loads(
            text
        )

        lower_text = text.lower()

        likely_state = (
            item.get(
                "id"
            )
            in {
                "__NUXT_DATA__",
                "__NEXT_DATA__",
            }
            or item.get(
                "type"
            )
            == "application/json"
            or "pinia"
            in lower_text
            or "serverrendered"
            in lower_text
            or "__nuxt"
            in lower_text
        )

        analysis = {
            "index":
                item[
                    "index"
                ],

            "id":
                item.get(
                    "id"
                ),

            "type":
                item.get(
                    "type"
                ),

            "chars":
                len(
                    text
                ),

            "likely_state":
                likely_state,

            "json_parse_ok":
                parsed[
                    "ok"
                ],

            "json_error":
                parsed[
                    "error"
                ],

            "findings":
                None,
        }

        if parsed[
            "ok"
        ]:
            analysis[
                "findings"
            ] = json_findings(
                parsed[
                    "value"
                ]
            )

        analyses.append(
            analysis
        )

    return analyses


# ============================================================
# RAW TEXT CONTEXT SEARCH
# ============================================================

def context_snippet(
    text,
    match_start,
    match_end,
    radius=350,
):
    left = max(
        0,
        match_start
        - radius
    )

    right = min(
        len(
            text
        ),
        match_end
        + radius
    )

    return (
        text[
            left:right
        ]
        .replace(
            "\r",
            " "
        )
        .strip()
    )


def search_text(
    text,
    source_name,
    terms,
    max_per_term=12,
):
    findings = []

    if not text:
        return findings

    for term in terms:
        pattern = re.compile(
            re.escape(
                term
            ),
            flags=re.IGNORECASE,
        )

        matches = list(
            pattern.finditer(
                text
            )
        )

        for match in matches[
            :max_per_term
        ]:
            findings.append(
                {
                    "source":
                        source_name,

                    "term":
                        term,

                    "position":
                        match.start(),

                    "snippet":
                        context_snippet(
                            text,
                            match.start(),
                            match.end(),
                        ),
                }
            )

    return findings


def focused_inline_findings(
    inventory,
):
    findings = []

    for item in inventory:
        if item[
            "src"
        ]:
            continue

        source_name = (
            item.get(
                "id"
            )
            or (
                f"INLINE_"
                f"{item['index']:02d}"
            )
        )

        findings.extend(
            search_text(
                item[
                    "text"
                ],
                source_name,
                [
                    "speed",
                    '"High"',
                    '"Low"',
                    '"Mid"',
                    "pinia",
                    "serverRendered",
                    "__NUXT",
                ],
                max_per_term=20,
            )
        )

    return findings


def focused_external_findings(
    fetched_scripts,
):
    findings = []

    for item in fetched_scripts:
        source_name = (
            f"JS_"
            f"{item['index']:02d}"
        )

        findings.extend(
            search_text(
                item[
                    "text"
                ],
                source_name,
                JS_SEARCH_TERMS,
                max_per_term=10,
            )
        )

    return findings


# ============================================================
# REPORT
# ============================================================

def build_report(
    selected_version,
    probes,
    inventory,
    saved_inline,
    state_analyses,
    inline_findings,
    fetched_scripts,
    external_findings,
    stats,
    validation,
):
    lines = []

    lines.append(
        "GT7 BOP LAB V1.4 - NUXT/PINIA STATE ANALYSIS"
    )

    lines.append(
        SEP
    )

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

    lines.append("")

    lines.append(
        "VERSION PROBES"
    )

    lines.append(
        SUB
    )

    for probe in probes:
        lines.append(
            f"{probe['version']:<8} | "
            f"HTTP {probe['status']:<3} | "
            f"{probe['bytes']:>8,} bytes | "
            f"{'VALID' if probe['valid'] else 'UNUSABLE'}"
        )

    lines.append("")

    lines.append(
        "INLINE SCRIPT / STATE INVENTORY"
    )

    lines.append(
        SUB
    )

    for item in saved_inline:
        lines.append(
            f"#{item['index']:02d} | "
            f"id={item['id']} | "
            f"type={item['type']} | "
            f"{item['chars']:,} chars | "
            f"{item['path']}"
        )

    lines.append("")

    lines.append(
        "STRUCTURED STATE ANALYSIS"
    )

    lines.append(
        SUB
    )

    for analysis in state_analyses:
        if not (
            analysis[
                "likely_state"
            ]
            or analysis[
                "json_parse_ok"
            ]
        ):
            continue

        lines.append(
            f"SCRIPT #{analysis['index']:02d}"
        )

        lines.append(
            f"  id              : "
            f"{analysis['id']}"
        )

        lines.append(
            f"  type            : "
            f"{analysis['type']}"
        )

        lines.append(
            f"  chars           : "
            f"{analysis['chars']:,}"
        )

        lines.append(
            f"  likely_state    : "
            f"{analysis['likely_state']}"
        )

        lines.append(
            f"  JSON parse      : "
            f"{'PASSED' if analysis['json_parse_ok'] else 'FAILED'}"
        )

        if (
            not analysis[
                "json_parse_ok"
            ]
        ):
            lines.append(
                f"  JSON error      : "
                f"{analysis['json_error']}"
            )

        findings = analysis.get(
            "findings"
        )

        if findings:
            speed_values = findings[
                "exact_speed_values"
            ]

            lines.append(
                f"  HIGH/LOW/MID    : "
                f"{len(speed_values)} exact values"
            )

            for item in speed_values[
                :80
            ]:
                lines.append(
                    f"    {item['path']} "
                    f"= {item['value']}"
                )

            lines.append(
                f"  Candidate objs  : "
                f"{len(findings['interesting_objects'])}"
            )

            for item in findings[
                "interesting_objects"
            ][
                :30
            ]:
                lines.append(
                    f"    PATH  : "
                    f"{item['path']}"
                )

                lines.append(
                    f"    SCORE : "
                    f"{item['score']}"
                )

                lines.append(
                    f"    KEYS  : "
                    f"{item['keys']}"
                )

                lines.append(
                    f"    DATA  : "
                    f"{item['preview']}"
                )

                lines.append("")

        lines.append("")

    lines.append(
        "FOCUSED INLINE FINDINGS"
    )

    lines.append(
        SUB
    )

    lines.append(
        f"Matches             : "
        f"{len(inline_findings)}"
    )

    for finding in inline_findings[
        :160
    ]:
        lines.append(
            f"[{finding['source']}] "
            f"[{finding['term']}] "
            f"pos={finding['position']}"
        )

        lines.append(
            finding[
                "snippet"
            ]
        )

        lines.append("")

    lines.append(
        "EXTERNAL SCRIPT INVENTORY"
    )

    lines.append(
        SUB
    )

    for item in fetched_scripts:
        lines.append(
            f"#{item['index']:02d} | "
            f"HTTP {item['status']} | "
            f"{item['bytes']:,} bytes | "
            f"{item['url']} | "
            f"saved={item['path']}"
        )

    lines.append("")

    lines.append(
        "FOCUSED EXTERNAL JS FINDINGS"
    )

    lines.append(
        SUB
    )

    lines.append(
        f"Matches             : "
        f"{len(external_findings)}"
    )

    for finding in external_findings[
        :180
    ]:
        lines.append(
            f"[{finding['source']}] "
            f"[{finding['term']}] "
            f"pos={finding['position']}"
        )

        lines.append(
            finding[
                "snippet"
            ]
        )

        lines.append("")

    # --------------------------------------------------------
    # Summary decision
    # --------------------------------------------------------

    parsed_states = [
        item
        for item in state_analyses
        if item[
            "json_parse_ok"
        ]
    ]

    exact_speed_count = sum(
        len(
            (
                item.get(
                    "findings"
                )
                or {}
            ).get(
                "exact_speed_values",
                []
            )
        )
        for item in parsed_states
    )

    candidate_object_count = sum(
        len(
            (
                item.get(
                    "findings"
                )
                or {}
            ).get(
                "interesting_objects",
                []
            )
        )
        for item in parsed_states
    )

    lines.append(
        "V1.4 RESULT"
    )

    lines.append(
        SUB
    )

    lines.append(
        f"JSON state scripts : "
        f"{len(parsed_states)}"
    )

    lines.append(
        f"Exact speed values : "
        f"{exact_speed_count}"
    )

    lines.append(
        f"Candidate objects  : "
        f"{candidate_object_count}"
    )

    if (
        exact_speed_count >= 3
        and candidate_object_count > 0
    ):
        lines.append(
            "Assessment          : "
            "PROMISING - structured page state contains "
            "speed-class and BoP-like data."
        )

    elif (
        len(
            external_findings
        )
        > 0
    ):
        lines.append(
            "Assessment          : "
            "SCRIPT PATH - speed switching is more likely "
            "implemented in external JavaScript."
        )

    else:
        lines.append(
            "Assessment          : "
            "UNRESOLVED - additional browser-level inspection "
            "may be required."
        )

    lines.append("")

    lines.append(
        "DATABASE"
    )

    lines.append(
        SUB
    )

    lines.append(
        f"Records             : "
        f"{stats['records']}"
    )

    lines.append(
        f"Validation          : "
        f"{'PASSED' if validation['valid'] else 'FAILED'}"
    )

    lines.append("")

    lines.append(
        "IMPORTANT"
    )

    lines.append(
        SUB
    )

    lines.append(
        "V1.4 remains diagnostic only."
    )

    lines.append(
        "No BoP records are inserted yet."
    )

    lines.append(
        SEP
    )

    return "\n".join(
        lines
    )


# ============================================================
# MAIN
# ============================================================

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

    STATE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    JS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    print()

    print(
        f"GT7 BOP LAB V{VERSION}"
    )

    print(
        SEP
    )

    print(
        "Experimental pipeline."
    )

    print(
        "The production Daily Race C agent "
        "is NOT modified."
    )

    print()

    session = requests.Session()

    session.headers.update(
        HEADERS
    )

    # ========================================================
    # INDEX + VERSION
    # ========================================================

    print(
        "READING DG EDGE BOP INDEX"
    )

    print(
        SUB
    )

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
        index_result[
            "text"
        ]
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

    print(
        "PROBING GR.3 VERSIONS"
    )

    print(
        SUB
    )

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

    html = source[
        "text"
    ]

    print()

    print(
        "SELECTED BOP PAGE"
    )

    print(
        SUB
    )

    print(
        f"Group              : "
        f"{GROUP}"
    )

    print(
        f"Version            : "
        f"{selected_version}"
    )

    print(
        f"URL                : "
        f"{page_url}"
    )

    # ========================================================
    # INVENTORY
    # ========================================================

    inventory = script_inventory(
        html,
        page_url,
    )

    print()

    print(
        "INLINE STATE INVENTORY"
    )

    print(
        SUB
    )

    print(
        f"Scripts total      : "
        f"{len(inventory)}"
    )

    saved_inline = save_inline_scripts(
        inventory
    )

    print(
        f"Inline saved       : "
        f"{len(saved_inline)}"
    )

    # ========================================================
    # ANALYZE INLINE STATE
    # ========================================================

    state_analyses = analyze_inline_state(
        inventory
    )

    likely_states = [
        item
        for item in state_analyses
        if item[
            "likely_state"
        ]
    ]

    parsed_states = [
        item
        for item in state_analyses
        if item[
            "json_parse_ok"
        ]
    ]

    print(
        f"Likely state       : "
        f"{len(likely_states)}"
    )

    print(
        f"JSON parsed        : "
        f"{len(parsed_states)}"
    )

    # ========================================================
    # FOCUSED INLINE SEARCH
    # ========================================================

    inline_findings = focused_inline_findings(
        inventory
    )

    print(
        f"Inline findings    : "
        f"{len(inline_findings)}"
    )

    # ========================================================
    # EXTERNAL JS
    # ========================================================

    print()

    print(
        "FETCHING EXTERNAL JAVASCRIPT"
    )

    print(
        SUB
    )

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

    external_findings = focused_external_findings(
        fetched_scripts
    )

    print(
        f"Focused JS matches : "
        f"{len(external_findings)}"
    )

    # ========================================================
    # DATABASE - STILL READ-ONLY
    # ========================================================

    database = load_database()

    save_database(
        database
    )

    stats = database_stats()

    validation = validate_database()

    # ========================================================
    # SAVE STATE ANALYSIS JSON
    # ========================================================

    state_payload = {
        "generated_at":
            now_iso(),

        "lab_version":
            VERSION,

        "group":
            GROUP,

        "selected_version":
            selected_version,

        "page_url":
            page_url,

        "saved_inline_scripts":
            saved_inline,

        "state_analyses":
            state_analyses,

        "inline_findings":
            inline_findings,

        "external_script_summary":
            [
                {
                    key:
                        value
                    for key, value
                    in item.items()
                    if key != "text"
                }
                for item
                in fetched_scripts
            ],

        "external_findings":
            external_findings,

        "production_pipeline_modified":
            False,
    }

    STATE_ANALYSIS_FILE.write_text(
        json.dumps(
            state_payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # ========================================================
    # REPORT
    # ========================================================

    report = build_report(
        selected_version=selected_version,
        probes=probes,
        inventory=inventory,
        saved_inline=saved_inline,
        state_analyses=state_analyses,
        inline_findings=inline_findings,
        fetched_scripts=fetched_scripts,
        external_findings=external_findings,
        stats=stats,
        validation=validation,
    )

    REPORT_FILE.write_text(
        report,
        encoding="utf-8",
    )

    print()

    print(
        report
    )

    print()

    print(
        "FILES CREATED"
    )

    print(
        SUB
    )

    print(
        f"Report             : "
        f"{REPORT_FILE}"
    )

    print(
        f"State analysis     : "
        f"{STATE_ANALYSIS_FILE}"
    )

    print(
        f"Inline state dir   : "
        f"{STATE_DIR}"
    )

    print(
        f"External JS dir    : "
        f"{JS_DIR}"
    )

    print(
        SEP
    )


if __name__ == "__main__":
    main()