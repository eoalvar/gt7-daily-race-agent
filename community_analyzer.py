from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# =============================================================================
# CONFIGURATION
# =============================================================================

VERSION = "V5.1"

DATA_DIR = Path("data")

LATEST_SNAPSHOT = DATA_DIR / "latest_snapshot.json"

TRANSCRIPT_DIR = DATA_DIR / "community_transcripts"

# Primary sources fixed by project policy
DIGIT_VIDEO_ID = "O-AfZNXuGBg"
GNC_VIDEO_ID = "qHfm2RjbRjI"

DIGIT_TRANSCRIPT = TRANSCRIPT_DIR / f"{DIGIT_VIDEO_ID}_digit_racing.json"
GNC_TRANSCRIPT = TRANSCRIPT_DIR / f"{GNC_VIDEO_ID}_gnc_racing.json"

OUTPUT_DIR = DATA_DIR / "community_intelligence"
OUTPUT_JSON = OUTPUT_DIR / "community_intelligence.json"
OUTPUT_TXT = OUTPUT_DIR / "community_intelligence.txt"


# =============================================================================
# GENERIC HELPERS
# =============================================================================

def load_json(path: Path) -> Any:
    if not path.exists():
        return None

    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        print(f"WARNING: unable to load {path}: {exc}")
        return None


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2,
        )


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def shorten(text: str, length: int = 360) -> str:
    text = normalize_space(text)

    if len(text) <= length:
        return text

    return text[: length - 3].rstrip() + "..."


def fmt_mult(value: Any) -> str:
    if value is None:
        return "unknown"

    text = str(value).strip()

    if text.lower() in {
        "",
        "none",
        "null",
        "unknown",
        "n/a",
    }:
        return "unknown"

    if text.lower().startswith("x"):
        return text

    try:
        number = int(float(text))
        return f"x{number}"
    except Exception:
        return text


def format_seconds(seconds: int | float | None) -> str:
    if seconds is None:
        return "?"

    try:
        total = int(seconds)
    except Exception:
        return "?"

    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60

    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"

    return f"{minutes}:{secs:02d}"


def is_nonempty(value: Any) -> bool:
    """
    Safe replacement for comparisons such as:

        value not in {None, "", [], {}}

    Lists and dictionaries are unhashable and cannot be placed inside a set.
    """

    if value is None:
        return False

    if isinstance(value, str):
        return bool(value.strip())

    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0

    return True


# =============================================================================
# TEXT EXTRACTION
# =============================================================================

TEXT_KEYS = {
    "text",
    "transcript",
    "content",
    "selected_text",
    "extracted_text",
    "raw_text",
    "clean_text",
}


def collect_strings(value: Any, key_hint: str = "") -> list[str]:
    """
    Recursively extracts plausible transcript text from different versions of
    the transcript database, without depending on a single JSON schema.
    """

    strings: list[str] = []

    if isinstance(value, str):
        if len(value.strip()) >= 20:
            strings.append(value)
        return strings

    if isinstance(value, list):
        for item in value:
            strings.extend(
                collect_strings(
                    item,
                    key_hint,
                )
            )
        return strings

    if isinstance(value, dict):
        priority_found = False

        # Prefer known transcript text keys.
        for key, item in value.items():
            key_lower = str(key).lower()

            if key_lower in TEXT_KEYS:
                priority_found = True
                strings.extend(
                    collect_strings(
                        item,
                        key_lower,
                    )
                )

        # If none of the known keys exists at this level, recurse normally.
        if not priority_found:
            for key, item in value.items():
                if str(key).lower() in {
                    "title",
                    "channel",
                    "url",
                    "video_id",
                    "provider",
                    "status",
                    "role",
                }:
                    continue

                strings.extend(
                    collect_strings(
                        item,
                        str(key).lower(),
                    )
                )

    return strings


def extract_transcript_text(data: Any) -> str:
    if data is None:
        return ""

    candidates = collect_strings(data)

    if not candidates:
        return ""

    # Remove exact duplicates while preserving order.
    unique: list[str] = []
    seen: set[str] = set()

    for text in candidates:
        normalized = normalize_space(text)

        if not normalized:
            continue

        if normalized in seen:
            continue

        seen.add(normalized)
        unique.append(text)

    if not unique:
        return ""

    # Usually the longest field is the actual selected transcript.
    unique.sort(
        key=len,
        reverse=True,
    )

    return unique[0]


# =============================================================================
# SENTENCE / EVIDENCE HELPERS
# =============================================================================

def split_sentences(text: str) -> list[str]:
    """
    Works with ordinary transcript text and timestamped transcript text.
    """

    if not text:
        return []

    text = text.replace(
        "\r",
        "\n",
    )

    # Preserve timestamp starts as natural boundaries.
    text = re.sub(
        r"(?=\[\d{1,2}:\d{2}(?::\d{2})?\])",
        "\n",
        text,
    )

    raw_parts = re.split(
        r"(?<=[.!?])\s+|\n+",
        text,
    )

    result: list[str] = []

    for part in raw_parts:
        part = normalize_space(part)

        if len(part) < 15:
            continue

        result.append(part)

    return result


def find_evidence(
    sentences: list[str],
    patterns: list[str],
    max_results: int = 5,
) -> list[str]:

    results: list[str] = []
    seen: set[str] = set()

    regexes = [
        re.compile(
            pattern,
            re.I,
        )
        for pattern in patterns
    ]

    for sentence in sentences:
        if any(
            regex.search(sentence)
            for regex in regexes
        ):
            normalized = normalize_space(
                sentence
            )

            if normalized in seen:
                continue

            seen.add(normalized)
            results.append(normalized)

            if len(results) >= max_results:
                break

    return results


def find_last_evidence(
    sentences: list[str],
    patterns: list[str],
) -> str | None:

    regexes = [
        re.compile(
            pattern,
            re.I,
        )
        for pattern in patterns
    ]

    for sentence in reversed(sentences):
        if any(
            regex.search(sentence)
            for regex in regexes
        ):
            return normalize_space(
                sentence
            )

    return None


def contains_any(
    text: str,
    patterns: list[str],
) -> bool:

    return any(
        re.search(
            pattern,
            text,
            re.I,
        )
        for pattern in patterns
    )


# =============================================================================
# LIVE SNAPSHOT EXTRACTION
# =============================================================================

def recursive_find_first(
    value: Any,
    candidate_keys: list[str],
) -> Any:
    """
    Recursively finds the first non-empty value associated with any candidate
    key.

    V5.1 fixes the previous unhashable-list bug.
    """

    candidate_keys_lower = {
        str(key).lower()
        for key in candidate_keys
    }

    if isinstance(value, dict):

        # First inspect keys at the current level.
        for key, item in value.items():
            key_lower = str(key).lower()

            if (
                key_lower in candidate_keys_lower
                and is_nonempty(item)
            ):
                return item

        # Then recurse through child values.
        for item in value.values():
            found = recursive_find_first(
                item,
                candidate_keys,
            )

            if is_nonempty(found):
                return found

    elif isinstance(value, list):

        for item in value:
            found = recursive_find_first(
                item,
                candidate_keys,
            )

            if is_nonempty(found):
                return found

    return None


def normalize_compounds(
    compounds_raw: Any,
) -> list[str]:

    compounds: list[str] = []

    if isinstance(compounds_raw, str):

        for item in re.split(
            r"[,;/|]+",
            compounds_raw,
        ):
            item = item.strip()

            if item:
                compounds.append(item)

    elif isinstance(compounds_raw, list):

        for item in compounds_raw:

            if isinstance(item, str):
                item = item.strip()

                if item:
                    compounds.append(item)

            elif isinstance(item, dict):

                name = (
                    item.get("name")
                    or item.get("compound")
                    or item.get("tyre")
                    or item.get("tire")
                )

                if isinstance(name, str):
                    name = name.strip()

                    if name:
                        compounds.append(name)

    # Remove duplicates while preserving order.
    result: list[str] = []
    seen: set[str] = set()

    for compound in compounds:
        normalized = compound.strip()

        if not normalized:
            continue

        if normalized.lower() in seen:
            continue

        seen.add(
            normalized.lower()
        )
        result.append(normalized)

    return result


def extract_live_config(
    snapshot: Any,
) -> dict[str, Any]:

    if not isinstance(
        snapshot,
        (dict, list),
    ):
        return {
            "week": None,
            "track": None,
            "race_class": None,
            "direction": None,
            "fuel_multiplier": None,
            "tyre_multiplier": None,
            "compounds": [],
        }

    week = recursive_find_first(
        snapshot,
        [
            "race_week",
            "week",
            "week_start",
            "start_date",
        ],
    )

    track = recursive_find_first(
        snapshot,
        [
            "track",
            "track_name",
            "circuit",
            "circuit_name",
        ],
    )

    race_class = recursive_find_first(
        snapshot,
        [
            "race_class",
            "class",
            "car_class",
            "category",
        ],
    )

    direction = recursive_find_first(
        snapshot,
        [
            "direction",
            "layout_direction",
        ],
    )

    fuel = recursive_find_first(
        snapshot,
        [
            "fuel_multiplier",
            "fuel_rate",
            "fuel_consumption",
            "fuel",
        ],
    )

    tyres = recursive_find_first(
        snapshot,
        [
            "tyre_multiplier",
            "tire_multiplier",
            "tyre_wear",
            "tire_wear",
            "tyre_wear_rate",
            "tire_wear_rate",
        ],
    )

    compounds_raw = recursive_find_first(
        snapshot,
        [
            "compounds",
            "tyres",
            "tires",
            "available_tyres",
            "available_tires",
        ],
    )

    compounds = normalize_compounds(
        compounds_raw
    )

    return {
        "week": week,
        "track": track,
        "race_class": race_class,
        "direction": direction,
        "fuel_multiplier": fuel,
        "tyre_multiplier": tyres,
        "compounds": compounds,
    }


# =============================================================================
# DIGIT RACING — STRATEGY ANALYSIS
# =============================================================================

def analyse_digit_strategy(
    text: str,
) -> dict[str, Any]:

    sentences = split_sentences(
        text
    )

    full = " ".join(
        sentences
    )

    evidence: dict[
        str,
        list[str],
    ] = {}

    evidence["pit_window"] = find_evidence(
        sentences,
        [
            r"\blap\s*(?:four|4)\b.*\blap\s*(?:five|5)\b",
            r"\blap\s*(?:4|four)[\s/-]*(?:5|five)\b",
            r"\bpit\b.*\blap\s*(?:four|4|five|5)\b",
        ],
        8,
    )

    evidence["overcut"] = find_evidence(
        sentences,
        [
            r"\bovercut\b",
            r"\bstayed out\b",
            r"\bstay out\b",
            r"\bpitted earlier\b",
            r"\bpit(?:ted)? earlier\b",
        ],
        10,
    )

    evidence["undercut"] = find_evidence(
        sentences,
        [
            r"\bundercut\b",
        ],
        5,
    )

    evidence["tyre_saving"] = find_evidence(
        sentences,
        [
            r"\btire saving\b",
            r"\btyre saving\b",
            r"\bsaving tires\b",
            r"\bsaving tyres\b",
            r"\bsave the tires\b",
            r"\bsave the tyres\b",
            r"\bgentle\b.*\btire",
            r"\bgentle\b.*\btyre",
        ],
        8,
    )

    evidence["mandatory_change"] = find_evidence(
        sentences,
        [
            r"\brequired tire change\b",
            r"\brequired tyre change\b",
            r"\bmandatory\b.*\btire",
            r"\bmandatory\b.*\btyre",
            r"\bpit stop is required\b",
            r"\bneed to change the tires\b",
            r"\bneed to change the tyres\b",
        ],
        6,
    )

    evidence["compounds"] = find_evidence(
        sentences,
        [
            r"\bracing mediums?\b",
            r"\bracing softs?\b",
            r"\bmediums? and soft\b",
            r"\bmedium.*soft\b",
        ],
        6,
    )

    evidence["citroen"] = find_evidence(
        sentences,
        [
            r"\bcitro[eë]n\b",
            r"\bcitroen\b",
        ],
        8,
    )

    evidence["meta"] = find_evidence(
        sentences,
        [
            r"\bmeta\b",
            r"\bcitroen cup\b",
            r"\bcar to go with\b",
        ],
        6,
    )

    evidence["track_limits"] = find_evidence(
        sentences,
        [
            r"\btrack limits?\b",
            r"\bpenalt(?:y|ies)\b",
        ],
        6,
    )

    # -------------------------------------------------------------------------
    # Strategy conclusion:
    #
    # later race-tested conclusions have greater value than initial prediction.
    # -------------------------------------------------------------------------

    latest_overcut_statement = find_last_evidence(
        sentences,
        [
            r"\bovercut\b",
            r"\bshould have stayed out\b",
            r"\bpitted earlier\b.*\blost\b",
        ],
    )

    overcut_supported = contains_any(
        full,
        [
            r"\bovercut\b",
            r"\bshould have stayed out\b",
        ],
    )

    early_pit_supported = bool(
        evidence["pit_window"]
    )

    tyre_saving_supported = bool(
        evidence["tyre_saving"]
    )

    mandatory_change_supported = bool(
        evidence["mandatory_change"]
    )

    citroen_supported = bool(
        evidence["citroen"]
    )

    strategy_summary: list[str] = []

    if mandatory_change_supported:
        strategy_summary.append(
            "A tyre change is required during the race."
        )

    if (
        early_pit_supported
        and overcut_supported
    ):
        strategy_summary.append(
            "Digit initially considered roughly lap 4-5 as the pit window, "
            "but his later race-tested conclusion favoured extending the stint."
        )

    elif early_pit_supported:
        strategy_summary.append(
            "Digit identified approximately lap 4-5 as a possible pit window."
        )

    if overcut_supported:
        strategy_summary.append(
            "The later evidence favours the overcut: staying out longer "
            "performed better than stopping early."
        )

    if tyre_saving_supported:
        strategy_summary.append(
            "Tyre preservation is an important component of race pace."
        )

    if citroen_supported:
        strategy_summary.append(
            "Digit identifies the GT by Citroën Gr.4 as particularly strong "
            "for this race, including tyre performance."
        )

    confidence = (
        "HIGH"
        if (
            overcut_supported
            and mandatory_change_supported
        )
        else "MEDIUM"
    )

    return {
        "source": "Digit Racing",
        "role": "RACE_STRATEGY",
        "video_id": DIGIT_VIDEO_ID,
        "confidence": confidence,
        "pit_window_initial": (
            "approximately laps 4-5"
            if early_pit_supported
            else None
        ),
        "preferred_pit_logic": (
            "OVERCUT / EXTEND FIRST STINT"
            if overcut_supported
            else (
                "LAP 4-5 WINDOW"
                if early_pit_supported
                else None
            )
        ),
        "tyre_saving": tyre_saving_supported,
        "mandatory_tyre_change": mandatory_change_supported,
        "citroen_recommended": citroen_supported,
        "latest_strategy_statement": latest_overcut_statement,
        "summary": strategy_summary,
        "evidence": evidence,
    }


# =============================================================================
# GNC RACING — LAP GUIDE ANALYSIS
# =============================================================================

def analyse_gnc_lap_guide(
    text: str,
) -> dict[str, Any]:

    sentences = split_sentences(
        text
    )

    braking = find_evidence(
        sentences,
        [
            r"\bbrak",
            r"\bbreak\b",
            r"\b100 board\b",
            r"\b200 board\b",
            r"\b300\b",
            r"\b350 m\b",
            r"\b50 m\b",
        ],
        16,
    )

    gears = find_evidence(
        sentences,
        [
            r"\b(?:first|second|third|fourth|fifth|sixth) gear\b",
            r"\bshift(?:ing)? down\b",
            r"\bshift(?:ing)? up\b",
        ],
        12,
    )

    throttle = find_evidence(
        sentences,
        [
            r"\baccelerat",
            r"\bfull throttle\b",
            r"\bget on the power\b",
            r"\bpower down\b",
        ],
        14,
    )

    line = find_evidence(
        sentences,
        [
            r"\btight line\b",
            r"\binside line\b",
            r"\bwhite line\b",
            r"\bleft side\b",
            r"\bright side\b",
            r"\bturn in\b",
            r"\bapex\b",
        ],
        16,
    )

    kerbs = find_evidence(
        sentences,
        [
            r"\bcurb\b",
            r"\bkerb\b",
            r"\bbollard",
            r"\bwhite line\b",
            r"\btrack limit",
        ],
        12,
    )

    markers: list[str] = []

    marker_patterns = [
        r"\b(?:100|200|300|350|400)\s*(?:m|meter|metre|board)?\b",
        r"\barrow sign\b",
        r"\bbridge\b",
        r"\btunnel\b",
        r"\breflective post\b",
        r"\brock",
        r"\byellow signs?\b",
        r"\bGran Turismo logo\b",
        r"\bpower line\b",
    ]

    for sentence in sentences:
        if contains_any(
            sentence,
            marker_patterns,
        ):
            markers.append(
                sentence
            )

    # Deduplicate preserving order.
    unique_markers: list[str] = []
    seen: set[str] = set()

    for item in markers:
        item_norm = normalize_space(
            item
        )

        if item_norm in seen:
            continue

        seen.add(item_norm)
        unique_markers.append(
            item_norm
        )

    # Build compact sequence from transcript order.
    sequential: list[
        dict[str, Any]
    ] = []

    for sentence in sentences:

        categories: list[str] = []

        lower = sentence.lower()

        if re.search(
            r"\bbrak|\bbreak\b",
            lower,
        ):
            categories.append(
                "BRAKING"
            )

        if re.search(
            r"\bsecond gear\b|\bshift",
            lower,
        ):
            categories.append(
                "GEAR"
            )

        if re.search(
            r"\baccelerat|\bpower\b|\bfull throttle\b",
            lower,
        ):
            categories.append(
                "THROTTLE"
            )

        if re.search(
            r"\bcurb\b|\bkerb\b|\bwhite line\b|\bbollard",
            lower,
        ):
            categories.append(
                "TRACK_LIMIT"
            )

        if not categories:
            continue

        if len(sentence) < 35:
            continue

        sequential.append(
            {
                "categories": categories,
                "instruction": sentence,
            }
        )

        if len(sequential) >= 18:
            break

    return {
        "source": "GnC Racing",
        "role": "QUALIFYING_LAP_GUIDE",
        "video_id": GNC_VIDEO_ID,
        "confidence": "HIGH",
        "braking_points": braking,
        "gears": gears,
        "throttle": throttle,
        "racing_line": line,
        "kerbs_track_limits": kerbs,
        "reference_markers": unique_markers[:16],
        "sequential_guide": sequential,
    }


# =============================================================================
# LIVE LEADERBOARD META
# =============================================================================

def extract_car_entries(
    value: Any,
) -> list[tuple[str, int]]:

    """
    Tries to recover car-use statistics from changing snapshot schemas.

    Returns:
        [(car_name, count), ...]
    """

    entries: list[
        tuple[str, int]
    ] = []

    if isinstance(value, list):

        for item in value:
            entries.extend(
                extract_car_entries(
                    item
                )
            )

    elif isinstance(value, dict):

        name = None
        count = None

        for key in [
            "car",
            "car_name",
            "vehicle",
            "model",
        ]:

            if (
                key in value
                and isinstance(
                    value[key],
                    str,
                )
            ):
                name = value[key]
                break

        for key in [
            "count",
            "drivers",
            "usage_count",
            "entries",
        ]:

            if key in value:

                try:
                    count = int(
                        value[key]
                    )
                except Exception:
                    pass

                if count is not None:
                    break

        if (
            name
            and count is not None
        ):
            entries.append(
                (
                    normalize_space(
                        name
                    ),
                    count,
                )
            )

        for item in value.values():
            entries.extend(
                extract_car_entries(
                    item
                )
            )

    return entries


def build_live_meta(
    snapshot: Any,
) -> list[dict[str, Any]]:

    entries = extract_car_entries(
        snapshot
    )

    if not entries:
        return []

    totals: Counter[str] = Counter()

    for car, count in entries:
        totals[car] += count

    ranked = totals.most_common(
        10
    )

    overall = sum(
        count
        for _, count in ranked
    )

    result: list[
        dict[str, Any]
    ] = []

    for car, count in ranked:

        pct = (
            count / overall * 100
            if overall
            else 0
        )

        result.append(
            {
                "car": car,
                "drivers": count,
                "percentage": round(
                    pct,
                    1,
                ),
            }
        )

    return result


# =============================================================================
# TEXT REPORT
# =============================================================================

def make_text_report(
    report: dict[str, Any],
) -> str:

    lines: list[str] = []

    width = 100

    def heading(
        title: str,
    ) -> None:

        lines.append("")
        lines.append(title)
        lines.append(
            "-" * width
        )

    race = report["race"]
    strategy = report["strategy"]
    lap = report["lap_guide"]
    meta = report["live_car_meta"]

    lines.append(
        "=" * width
    )

    lines.append(
        f"GT7 COMMUNITY INTELLIGENCE {VERSION}"
    )

    lines.append(
        "=" * width
    )

    lines.append(
        f"Race week        : {race.get('week') or 'unknown'}"
    )

    lines.append(
        f"Track            : {race.get('track') or 'unknown'}"
    )

    lines.append(
        f"Class            : {race.get('race_class') or 'unknown'}"
    )

    lines.append(
        f"Direction        : {race.get('direction') or 'unknown'}"
    )

    lines.append(
        f"Fuel             : {fmt_mult(race.get('fuel_multiplier'))}"
    )

    lines.append(
        f"Tyre wear        : {fmt_mult(race.get('tyre_multiplier'))}"
    )

    compounds = (
        race.get("compounds")
        or []
    )

    lines.append(
        "Compounds        : "
        + (
            ", ".join(compounds)
            if compounds
            else "unknown"
        )
    )

    heading(
        "SOURCE POLICY"
    )

    lines.append(
        "Race strategy    : Digit Racing only"
    )

    lines.append(
        "Qualifying guide : GnC Racing only"
    )

    lines.append(
        "Race regulations : live GT7/GTSH snapshot"
    )

    lines.append(
        "Car meta         : live leaderboard"
    )

    heading(
        "RACE STRATEGY — DIGIT RACING"
    )

    lines.append(
        f"Confidence       : {strategy['confidence']}"
    )

    pit_logic = (
        strategy.get(
            "preferred_pit_logic"
        )
        or "No supported conclusion"
    )

    lines.append(
        f"Preferred logic  : {pit_logic}"
    )

    if strategy.get(
        "pit_window_initial"
    ):

        lines.append(
            "Initial estimate : "
            + strategy[
                "pit_window_initial"
            ]
        )

    lines.append(
        "Tyre saving      : "
        + (
            "IMPORTANT"
            if strategy.get(
                "tyre_saving"
            )
            else "not explicitly established"
        )
    )

    lines.append(
        "Tyre change      : "
        + (
            "REQUIRED"
            if strategy.get(
                "mandatory_tyre_change"
            )
            else "not established from Digit transcript"
        )
    )

    lines.append(
        "Citroën          : "
        + (
            "SUPPORTED BY DIGIT"
            if strategy.get(
                "citroen_recommended"
            )
            else "not explicitly supported"
        )
    )

    lines.append("")

    for index, item in enumerate(
        strategy.get(
            "summary",
            [],
        ),
        start=1,
    ):
        lines.append(
            f"{index}. {item}"
        )

    if strategy.get(
        "latest_strategy_statement"
    ):

        lines.append("")

        lines.append(
            "Latest race-tested strategy evidence:"
        )

        lines.append(
            "  "
            + shorten(
                strategy[
                    "latest_strategy_statement"
                ],
                650,
            )
        )

    heading(
        "STRATEGY EVIDENCE"
    )

    evidence_order = [
        (
            "Overcut / stay out",
            "overcut",
        ),
        (
            "Pit window",
            "pit_window",
        ),
        (
            "Tyre saving",
            "tyre_saving",
        ),
        (
            "Mandatory change",
            "mandatory_change",
        ),
        (
            "Compounds",
            "compounds",
        ),
        (
            "Citroën / meta",
            "citroen",
        ),
    ]

    for title, key in evidence_order:

        values = (
            strategy
            .get(
                "evidence",
                {},
            )
            .get(
                key,
                [],
            )
        )

        if not values:
            continue

        lines.append("")
        lines.append(
            f"{title}:"
        )

        for value in values[:4]:
            lines.append(
                "  - "
                + shorten(
                    value,
                    520,
                )
            )

    heading(
        "QUALIFYING / FAST LAP — GNC RACING"
    )

    lines.append(
        f"Confidence       : {lap['confidence']}"
    )

    guide = lap.get(
        "sequential_guide",
        [],
    )

    if not guide:
        lines.append(
            "No structured lap-guide evidence found."
        )

    for index, item in enumerate(
        guide,
        start=1,
    ):

        cats = "/".join(
            item["categories"]
        )

        lines.append(
            f"{index:2d}. [{cats}] "
            + shorten(
                item[
                    "instruction"
                ],
                580,
            )
        )

    heading(
        "BRAKING REFERENCES — GNC"
    )

    braking = lap.get(
        "braking_points",
        [],
    )

    if not braking:

        lines.append(
            "No braking references extracted."
        )

    else:

        for item in braking[:12]:
            lines.append(
                "- "
                + shorten(
                    item,
                    560,
                )
            )

    heading(
        "GEARS / SHIFTING — GNC"
    )

    gears = lap.get(
        "gears",
        [],
    )

    if not gears:

        lines.append(
            "No gear references extracted."
        )

    else:

        for item in gears[:10]:
            lines.append(
                "- "
                + shorten(
                    item,
                    560,
                )
            )

    heading(
        "TRACK LIMITS / KERBS — GNC"
    )

    kerbs = lap.get(
        "kerbs_track_limits",
        [],
    )

    if not kerbs:

        lines.append(
            "No kerb/track-limit guidance extracted."
        )

    else:

        for item in kerbs[:10]:
            lines.append(
                "- "
                + shorten(
                    item,
                    560,
                )
            )

    heading(
        "LIVE CAR META"
    )

    if not meta:

        lines.append(
            "Live leaderboard car distribution "
            "was not found in the snapshot."
        )

    else:

        for index, item in enumerate(
            meta[:10],
            start=1,
        ):

            lines.append(
                f"{index:2d}. "
                f"{item['car']} | "
                f"{item['drivers']} drivers | "
                f"{item['percentage']:.1f}%"
            )

    heading(
        "PRACTICAL RACE PLAN"
    )

    practical = report.get(
        "practical_plan",
        [],
    )

    for index, item in enumerate(
        practical,
        start=1,
    ):

        lines.append(
            f"{index}. {item}"
        )

    heading(
        "ANALYSIS POLICY"
    )

    lines.append(
        "1. Digit Racing is the sole community source for race strategy."
    )

    lines.append(
        "2. GnC Racing is the sole community source for qualifying/lap guidance."
    )

    lines.append(
        "3. Live GT7/GTSH data overrides any conflicting community statement."
    )

    lines.append(
        "4. Later race-tested Digit conclusions override earlier speculative strategy comments."
    )

    lines.append(
        "5. Live leaderboard usage is authoritative for current car meta."
    )

    lines.append(
        "6. Transcript evidence is never used to invent missing braking points, gears or strategy."
    )

    lines.append("")
    lines.append(
        "=" * width
    )

    return "\n".join(
        lines
    )


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:

    print(
        "=" * 100
    )

    print(
        f"GT7 COMMUNITY ANALYZER {VERSION}"
    )

    print(
        "=" * 100
    )

    snapshot = load_json(
        LATEST_SNAPSHOT
    )

    digit_data = load_json(
        DIGIT_TRANSCRIPT
    )

    gnc_data = load_json(
        GNC_TRANSCRIPT
    )

    print(
        f"Digit transcript : "
        f"{'FOUND' if digit_data else 'MISSING'}"
    )

    print(
        f"GnC transcript   : "
        f"{'FOUND' if gnc_data else 'MISSING'}"
    )

    if digit_data is None:

        raise SystemExit(
            f"ERROR: missing Digit transcript: "
            f"{DIGIT_TRANSCRIPT}"
        )

    if gnc_data is None:

        raise SystemExit(
            f"ERROR: missing GnC transcript: "
            f"{GNC_TRANSCRIPT}"
        )

    digit_text = extract_transcript_text(
        digit_data
    )

    gnc_text = extract_transcript_text(
        gnc_data
    )

    print(
        f"Digit characters : "
        f"{len(digit_text):,}"
    )

    print(
        f"GnC characters   : "
        f"{len(gnc_text):,}"
    )

    if not digit_text:

        raise SystemExit(
            "ERROR: Digit transcript JSON exists "
            "but no usable transcript text was found."
        )

    if not gnc_text:

        raise SystemExit(
            "ERROR: GnC transcript JSON exists "
            "but no usable transcript text was found."
        )

    # -------------------------------------------------------------------------
    # Live race configuration
    # -------------------------------------------------------------------------

    race = extract_live_config(
        snapshot
    )

    print()
    print(
        "LIVE CONFIGURATION"
    )
    print(
        "-" * 100
    )

    print(
        f"Week             : "
        f"{race.get('week') or 'unknown'}"
    )

    print(
        f"Track            : "
        f"{race.get('track') or 'unknown'}"
    )

    print(
        f"Class            : "
        f"{race.get('race_class') or 'unknown'}"
    )

    print(
        f"Direction        : "
        f"{race.get('direction') or 'unknown'}"
    )

    print(
        f"Fuel             : "
        f"{fmt_mult(race.get('fuel_multiplier'))}"
    )

    print(
        f"Tyre wear        : "
        f"{fmt_mult(race.get('tyre_multiplier'))}"
    )

    print(
        "Compounds        : "
        + (
            ", ".join(
                race.get(
                    "compounds",
                    [],
                )
            )
            if race.get(
                "compounds"
            )
            else "unknown"
        )
    )

    # -------------------------------------------------------------------------
    # Community analysis
    # -------------------------------------------------------------------------

    strategy = analyse_digit_strategy(
        digit_text
    )

    lap_guide = analyse_gnc_lap_guide(
        gnc_text
    )

    live_meta = build_live_meta(
        snapshot
    )

    practical_plan: list[str] = []

    practical_plan.append(
        "Use the official/live race configuration as the regulatory baseline."
    )

    if strategy.get(
        "mandatory_tyre_change"
    ):

        practical_plan.append(
            "Plan the race around the required tyre change."
        )

    if strategy.get(
        "tyre_saving"
    ):

        practical_plan.append(
            "Protect the tyres during the opening stint; "
            "unnecessary sliding and steering input can compromise the later laps."
        )

    if (
        strategy.get(
            "preferred_pit_logic"
        )
        == "OVERCUT / EXTEND FIRST STINT"
    ):

        practical_plan.append(
            "Do not treat laps 4-5 as a rigid pit window. "
            "Digit's later race-tested conclusion favours staying out longer "
            "and using the overcut rather than stopping early."
        )

    elif strategy.get(
        "pit_window_initial"
    ):

        practical_plan.append(
            "Use approximately laps 4-5 as the currently supported pit reference."
        )

    if strategy.get(
        "citroen_recommended"
    ):

        practical_plan.append(
            "The GT by Citroën Gr.4 is supported by Digit's race experience; "
            "compare that recommendation with the live leaderboard before choosing the car."
        )

    practical_plan.append(
        "Use the GnC guide for braking references, gears, line and throttle technique; "
        "do not mix lap instructions from other community sources."
    )

    report = {
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "version": VERSION,
        "race": race,
        "sources": {
            "strategy": {
                "channel": "Digit Racing",
                "video_id": DIGIT_VIDEO_ID,
                "role": "RACE_STRATEGY",
            },
            "lap_guide": {
                "channel": "GnC Racing",
                "video_id": GNC_VIDEO_ID,
                "role": "QUALIFYING_LAP_GUIDE",
            },
        },
        "strategy": strategy,
        "lap_guide": lap_guide,
        "live_car_meta": live_meta,
        "practical_plan": practical_plan,
        "policy": {
            "strategy_source_count": 1,
            "lap_guide_source_count": 1,
            "strategy_source": "Digit Racing",
            "lap_guide_source": "GnC Racing",
            "regulation_authority": "LIVE_GT7_GTSH",
            "car_meta_authority": "LIVE_LEADERBOARD",
            "later_race_tested_strategy_overrides_early_prediction": True,
        },
    }

    text_report = make_text_report(
        report
    )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    save_json(
        OUTPUT_JSON,
        report,
    )

    OUTPUT_TXT.write_text(
        text_report,
        encoding="utf-8",
    )

    print()
    print(
        text_report
    )

    print()
    print(
        f"JSON report      : "
        f"{OUTPUT_JSON}"
    )

    print(
        f"Text report      : "
        f"{OUTPUT_TXT}"
    )

    print()
    print(
        "=" * 100
    )

    print(
        "COMMUNITY INTELLIGENCE COMPLETE"
    )

    print(
        "=" * 100
    )


if __name__ == "__main__":
    main()