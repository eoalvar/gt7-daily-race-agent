#!/usr/bin/env python3

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ======================================================================================
# CONFIGURATION
# ======================================================================================

VERSION = "5.4"

DATA_DIR = Path("data")

LATEST_SNAPSHOT = DATA_DIR / "latest_snapshot.json"

TRANSCRIPT_DB = DATA_DIR / "community_transcripts.json"
TRANSCRIPT_DIR = DATA_DIR / "community_transcripts"

OUTPUT_DIR = DATA_DIR / "community_intelligence"
OUTPUT_JSON = OUTPUT_DIR / "community_intelligence.json"
OUTPUT_REPORT = OUTPUT_DIR / "community_intelligence.txt"

STRATEGY_CHANNEL = "Digit Racing"
LAP_GUIDE_CHANNEL = "GnC Racing"

SEPARATOR = "=" * 100
SUB_SEPARATOR = "-" * 100


# ======================================================================================
# GENERIC HELPERS
# ======================================================================================

def load_json(path: Path) -> Any:
    if not path.exists():
        return None

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def safe_str(value: Any, default: str = "unknown") -> str:
    if value is None:
        return default

    text = str(value).strip()

    return text if text else default


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def unique_preserve_order(items: List[str]) -> List[str]:
    seen = set()
    result = []

    for item in items:
        key = normalize_space(item).lower()

        if not key:
            continue

        if key in seen:
            continue

        seen.add(key)
        result.append(normalize_space(item))

    return result


# ======================================================================================
# TRANSCRIPT CLEANING
# ======================================================================================

NOISE_TOKENS = [
    "[music]",
    "[applause]",
    "[laughter]",
    "[foreign]",
    "&gt;&gt;",
    ">>",
]


def remove_noise_tokens(text: str) -> str:
    result = text

    for token in NOISE_TOKENS:
        result = re.sub(
            re.escape(token),
            " ",
            result,
            flags=re.IGNORECASE,
        )

    return normalize_space(result)


def collapse_adjacent_repeated_words(text: str) -> str:
    """
    Collapses obvious ASR duplication such as:

        "yeah yeah yeah"
        "stayed out stayed out stayed out"
        "tires tires"

    Conservatively allows up to 6-word repeated blocks.
    """

    result = normalize_space(text)

    for block_size in range(6, 0, -1):

        pattern = re.compile(
            r"\b("
            + r"\S+(?:\s+\S+){" + str(block_size - 1) + r"}"
            + r")"
            + r"(?:\s+\1){1,5}\b",
            flags=re.IGNORECASE,
        )

        previous = None

        while previous != result:
            previous = result
            result = pattern.sub(r"\1", result)

    return normalize_space(result)


def collapse_repeated_sentences(text: str) -> str:
    """
    Removes repeated adjacent or near-identical sentences generated
    by transcript providers.
    """

    text = normalize_space(text)

    parts = re.split(
        r"(?<=[.!?])\s+",
        text,
    )

    cleaned: List[str] = []
    previous_key = None

    for part in parts:
        part = normalize_space(part)

        if not part:
            continue

        key = re.sub(
            r"[^a-z0-9 ]",
            "",
            part.lower(),
        )

        key = normalize_space(key)

        if key == previous_key:
            continue

        cleaned.append(part)
        previous_key = key

    return " ".join(cleaned)


def clean_transcript_text(text: str) -> str:
    text = remove_noise_tokens(text)
    text = collapse_adjacent_repeated_words(text)
    text = collapse_repeated_sentences(text)

    return normalize_space(text)


# ======================================================================================
# TIMESTAMP HANDLING
# ======================================================================================

TIMESTAMP_RE = re.compile(
    r"\[(?P<time>(?:\d+:)?\d{1,2}:\d{2})\]"
)


def split_timestamped_chunks(text: str) -> List[Dict[str, str]]:
    """
    Converts:

        [19:30] text...
        [20:01] text...

    into structured chunks.

    If no timestamps exist, returns one chunk.
    """

    matches = list(TIMESTAMP_RE.finditer(text))

    if not matches:
        cleaned = clean_transcript_text(text)

        return [
            {
                "timestamp": "",
                "text": cleaned,
            }
        ] if cleaned else []

    chunks: List[Dict[str, str]] = []

    for index, match in enumerate(matches):

        start = match.end()

        if index + 1 < len(matches):
            end = matches[index + 1].start()
        else:
            end = len(text)

        timestamp = match.group("time")
        body = text[start:end]

        body = clean_transcript_text(body)

        if body:
            chunks.append(
                {
                    "timestamp": timestamp,
                    "text": body,
                }
            )

    return chunks


def timestamp_seconds(timestamp: str) -> int:
    if not timestamp:
        return 0

    parts = [
        int(part)
        for part in timestamp.split(":")
    ]

    if len(parts) == 2:
        minutes, seconds = parts
        return minutes * 60 + seconds

    if len(parts) == 3:
        hours, minutes, seconds = parts
        return hours * 3600 + minutes * 60 + seconds

    return 0


# ======================================================================================
# RECURSIVE JSON HELPERS
# ======================================================================================

def recursive_find_first(
    data: Any,
    keys: List[str],
) -> Any:

    key_set = set(keys)

    if isinstance(data, dict):

        for key, value in data.items():
            if key in key_set:
                return value

        for value in data.values():
            found = recursive_find_first(
                value,
                keys,
            )

            if found is not None:
                return found

    elif isinstance(data, list):

        for value in data:
            found = recursive_find_first(
                value,
                keys,
            )

            if found is not None:
                return found

    return None


def recursive_find_dict_with_keys(
    data: Any,
    required_keys: List[str],
) -> Optional[dict]:

    required = set(required_keys)

    if isinstance(data, dict):

        if required.issubset(
            set(data.keys())
        ):
            return data

        for value in data.values():
            found = recursive_find_dict_with_keys(
                value,
                required_keys,
            )

            if found is not None:
                return found

    elif isinstance(data, list):

        for value in data:
            found = recursive_find_dict_with_keys(
                value,
                required_keys,
            )

            if found is not None:
                return found

    return None


# ======================================================================================
# LIVE CONFIGURATION
# ======================================================================================

def extract_track_from_description(
    description: str,
) -> str:

    description = safe_str(
        description,
        "",
    )

    if not description:
        return "unknown"

    known_patterns = [
        r"Grand Valley\s*-\s*Highway\s*1",
        r"Grand Valley Highway\s*1",
    ]

    for pattern in known_patterns:
        match = re.search(
            pattern,
            description,
            re.IGNORECASE,
        )

        if match:
            return "Grand Valley - Highway 1"

    # Generic fallback.
    match = re.search(
        r"Daily Race C.*?\d{1,2}:\d{2}\s+(.+?)\s+[A-Z]\.\s+[A-Za-z]",
        description,
        re.IGNORECASE,
    )

    if match:
        track = normalize_space(
            match.group(1)
        )

        return track

    return "unknown"


def extract_class_from_description(
    description: str,
) -> str:

    description = safe_str(
        description,
        "",
    )

    match = re.search(
        r"\bGr\.\s*\d+\b",
        description,
        re.IGNORECASE,
    )

    if match:
        value = match.group(0)

        value = re.sub(
            r"\s+",
            "",
            value,
        )

        return value

    return "unknown"


def extract_live_config(
    snapshot: Any,
) -> Dict[str, Any]:

    race = None

    if isinstance(snapshot, dict):
        race = snapshot.get("race")

    if not isinstance(race, dict):
        race = recursive_find_dict_with_keys(
            snapshot,
            ["fuel_multiplier", "tyre_multiplier"],
        )

    if not isinstance(race, dict):
        race = {}

    description = safe_str(
        race.get("description"),
        "",
    )

    start_date = (
        race.get("start_date")
        or recursive_find_first(
            snapshot,
            ["start_date", "week", "race_week"],
        )
    )

    track = (
        race.get("track")
        or race.get("track_name")
        or recursive_find_first(
            race,
            ["track", "track_name"],
        )
    )

    if not track:
        track = extract_track_from_description(
            description
        )

    race_class = (
        race.get("class")
        or race.get("race_class")
        or recursive_find_first(
            race,
            ["class", "race_class"],
        )
    )

    if not race_class:
        race_class = extract_class_from_description(
            description
        )

    direction = (
        race.get("direction")
        or "NORMAL"
    )

    fuel = (
        race.get("fuel_multiplier")
        or recursive_find_first(
            race,
            ["fuel_multiplier"],
        )
    )

    tyres = (
        race.get("tyre_multiplier")
        or race.get("tire_multiplier")
        or recursive_find_first(
            race,
            [
                "tyre_multiplier",
                "tire_multiplier",
            ],
        )
    )

    compounds = (
        race.get("compounds")
        or recursive_find_first(
            race,
            ["compounds"],
        )
        or []
    )

    if not isinstance(compounds, list):
        compounds = [compounds]

    compounds = [
        safe_str(item, "")
        for item in compounds
        if safe_str(item, "")
    ]

    return {
        "week": safe_str(start_date),
        "track": safe_str(track),
        "class": safe_str(race_class),
        "direction": safe_str(direction, "NORMAL"),
        "fuel_multiplier": fuel,
        "tyre_multiplier": tyres,
        "compounds": compounds,
    }


# ======================================================================================
# TRANSCRIPT LOADING
# ======================================================================================

def find_transcript_file(
    channel_fragment: str,
) -> Optional[Path]:

    fragment = (
        channel_fragment
        .lower()
        .replace(" ", "_")
    )

    if not TRANSCRIPT_DIR.exists():
        return None

    candidates = []

    for path in TRANSCRIPT_DIR.glob("*.json"):

        name = path.name.lower()

        if fragment in name:
            candidates.append(path)

    if not candidates:
        return None

    return sorted(
        candidates,
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[0]


def extract_transcript_text(
    data: Any,
) -> str:

    if data is None:
        return ""

    if isinstance(data, str):
        return data

    possible = recursive_find_first(
        data,
        [
            "transcript",
            "text",
            "content",
            "selected_text",
            "extracted_text",
        ],
    )

    if isinstance(possible, str):
        return possible

    return ""


def load_channel_transcript(
    channel: str,
) -> Tuple[Optional[Path], str]:

    path = find_transcript_file(
        channel
    )

    if path is None:
        return None, ""

    data = load_json(path)

    text = extract_transcript_text(
        data
    )

    return path, text


# ======================================================================================
# STRATEGY EVIDENCE — DIGIT RACING
# ======================================================================================

def text_has_any(
    text: str,
    phrases: List[str],
) -> bool:

    low = text.lower()

    return any(
        phrase.lower() in low
        for phrase in phrases
    )


def evidence_record(
    chunk: Dict[str, str],
) -> Dict[str, str]:

    return {
        "timestamp": chunk.get(
            "timestamp",
            "",
        ),
        "text": clean_transcript_text(
            chunk.get(
                "text",
                "",
            )
        ),
    }


def deduplicate_evidence(
    evidence: List[Dict[str, str]],
) -> List[Dict[str, str]]:

    result = []
    seen = set()

    for item in evidence:

        text = clean_transcript_text(
            item.get("text", "")
        )

        key = re.sub(
            r"[^a-z0-9 ]",
            "",
            text.lower(),
        )

        key = normalize_space(key)

        if not key:
            continue

        if key in seen:
            continue

        seen.add(key)

        result.append(
            {
                "timestamp": item.get(
                    "timestamp",
                    "",
                ),
                "text": text,
            }
        )

    return result


def is_bad_tyre_evidence(
    text: str,
) -> bool:

    low = text.lower()

    bad_contexts = [
        "switched to wheel",
        "controller",
        "endurance championship",
        "difficult to get used to the wheel",
        "setup video",
        "pedal cam",
        "mechanic",
        "power",
        "copyright",
        "theme song",
        "nickname",
    ]

    return any(
        phrase in low
        for phrase in bad_contexts
    )


def extract_digit_strategy(
    raw_text: str,
) -> Dict[str, Any]:

    chunks = split_timestamped_chunks(
        raw_text
    )

    overcut: List[Dict[str, str]] = []
    tyre_saving: List[Dict[str, str]] = []
    tyre_change: List[Dict[str, str]] = []
    compounds: List[Dict[str, str]] = []
    citroen: List[Dict[str, str]] = []
    pit_window: List[Dict[str, str]] = []

    for chunk in chunks:

        text = chunk["text"]
        low = text.lower()

        # --------------------------------------------------------------
        # Overcut / stay-out evidence
        # --------------------------------------------------------------

        if text_has_any(
            low,
            [
                "overcut",
                "should have stayed out",
                "pitted earlier",
                "pit later",
                "stay out",
            ],
        ):
            overcut.append(
                evidence_record(chunk)
            )

        # --------------------------------------------------------------
        # Tyre saving evidence
        # --------------------------------------------------------------

        tyre_saving_signal = text_has_any(
            low,
            [
                "tire saving",
                "tyre saving",
                "saving tires",
                "saving tyres",
                "gentle with my tires",
                "gentle with my tyres",
                "very gentle with my tires",
                "very gentle with my tyres",
                "tire wear is going to be significantly less",
                "tyre wear is going to be significantly less",
                "don't want to get too much on the front",
            ],
        )

        if (
            tyre_saving_signal
            and not is_bad_tyre_evidence(text)
        ):
            tyre_saving.append(
                evidence_record(chunk)
            )

        # --------------------------------------------------------------
        # Required tyre change
        # --------------------------------------------------------------

        if text_has_any(
            low,
            [
                "required tire change",
                "required tyre change",
                "need to change the tires",
                "need to change the tyres",
                "strategy is to change the tires",
                "strategy is to change the tyres",
            ],
        ):
            tyre_change.append(
                evidence_record(chunk)
            )

        # --------------------------------------------------------------
        # Compounds
        # --------------------------------------------------------------

        if (
            text_has_any(
                low,
                [
                    "mediums and soft",
                    "medium and soft",
                    "racing mediums",
                    "racing medium",
                ],
            )
            and text_has_any(
                low,
                [
                    "soft",
                    "softs",
                    "racing soft",
                ],
            )
        ):
            compounds.append(
                evidence_record(chunk)
            )

        # --------------------------------------------------------------
        # Citroën / meta
        # --------------------------------------------------------------

        if (
            "citroen" in low
            or "citroën" in low
        ) and text_has_any(
            low,
            [
                "meta",
                "cup",
                "strong",
                "tire wear",
                "tyre wear",
                "faster overall",
            ],
        ):
            citroen.append(
                evidence_record(chunk)
            )

        # --------------------------------------------------------------
        # Pit-window discussion
        # --------------------------------------------------------------

        if (
            text_has_any(
                low,
                [
                    "lap four",
                    "lap five",
                    "lap 4",
                    "lap 5",
                ],
            )
            and text_has_any(
                low,
                [
                    "pit",
                    "change the tires",
                    "change the tyres",
                ],
            )
        ):
            pit_window.append(
                evidence_record(chunk)
            )

    overcut = deduplicate_evidence(
        overcut
    )

    tyre_saving = deduplicate_evidence(
        tyre_saving
    )

    tyre_change = deduplicate_evidence(
        tyre_change
    )

    compounds = deduplicate_evidence(
        compounds
    )

    citroen = deduplicate_evidence(
        citroen
    )

    pit_window = deduplicate_evidence(
        pit_window
    )

    # Prefer later race-tested evidence for strategy conclusions.
    overcut.sort(
        key=lambda item: timestamp_seconds(
            item["timestamp"]
        )
    )

    # Limit console/report noise.
    overcut = overcut[-4:]
    tyre_saving = tyre_saving[:4]
    tyre_change = tyre_change[:3]
    compounds = compounds[:3]
    citroen = citroen[-3:]
    pit_window = pit_window[:3]

    preferred_logic = (
        "OVERCUT / EXTEND FIRST STINT"
        if overcut
        else "NOT ESTABLISHED"
    )

    confidence_score = 0

    if overcut:
        confidence_score += 3

    if tyre_saving:
        confidence_score += 1

    if tyre_change:
        confidence_score += 1

    if compounds:
        confidence_score += 1

    if citroen:
        confidence_score += 1

    if confidence_score >= 5:
        confidence = "HIGH"
    elif confidence_score >= 2:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    recommendations = []

    if overcut:
        recommendations.append(
            "The later race-tested evidence favours the overcut: "
            "staying out longer performed better than stopping early."
        )

    if tyre_saving:
        recommendations.append(
            "Tyre preservation is strategically important; minimise "
            "unnecessary sliding, steering input and front-tyre overload."
        )

    if tyre_change:
        recommendations.append(
            "Digit confirms that the race requires the tyre-change rule "
            "to be satisfied."
        )

    if citroen:
        recommendations.append(
            "Digit identifies the GT by Citroën Gr.4 as particularly "
            "strong for this race, including tyre performance."
        )

    return {
        "confidence": confidence,
        "preferred_logic": preferred_logic,
        "tyre_saving_supported": bool(
            tyre_saving
        ),
        "tyre_change_supported": bool(
            tyre_change
        ),
        "citroen_supported": bool(
            citroen
        ),
        "recommendations": recommendations,
        "evidence": {
            "overcut": overcut,
            "tyre_saving": tyre_saving,
            "tyre_change": tyre_change,
            "compounds": compounds,
            "citroen": citroen,
            "pit_window": pit_window,
        },
    }


# ======================================================================================
# GNC LAP GUIDE
# ======================================================================================

def classify_gnc_line(
    text: str,
) -> List[str]:

    low = text.lower()

    tags = []

    if text_has_any(
        low,
        [
            "brake",
            "braking",
            "break",
            "100 board",
            "200 board",
            "350 m",
            "50 m",
        ],
    ):
        tags.append("BRAKING")

    if text_has_any(
        low,
        [
            "second gear",
            "third gear",
            "fourth gear",
            "shift",
            "shifting",
            "gear",
        ],
    ):
        tags.append("GEAR")

    if text_has_any(
        low,
        [
            "accelerate",
            "power",
            "throttle",
            "full throttle",
        ],
    ):
        tags.append("THROTTLE")

    if text_has_any(
        low,
        [
            "line",
            "inside",
            "outside",
            "left side",
            "right side",
            "turn in",
            "turning in",
            "hug",
            "apex",
        ],
    ):
        tags.append("LINE")

    if text_has_any(
        low,
        [
            "curb",
            "kerb",
            "white line",
            "bollard",
            "bolard",
            "track side",
            "track limit",
            "bridge",
        ],
    ):
        tags.append("TRACK_LIMIT")

    return tags


def sentence_split(
    text: str,
) -> List[str]:

    text = clean_transcript_text(
        text
    )

    pieces = re.split(
        r"(?<=[.!?])\s+",
        text,
    )

    return [
        normalize_space(piece)
        for piece in pieces
        if normalize_space(piece)
    ]


def extract_gnc_lap_guide(
    raw_text: str,
) -> Dict[str, Any]:

    sentences = sentence_split(
        raw_text
    )

    sequential = []

    braking = []
    gears = []
    track_limits = []

    seen = set()

    for sentence in sentences:

        tags = classify_gnc_line(
            sentence
        )

        if not tags:
            continue

        key = re.sub(
            r"[^a-z0-9 ]",
            "",
            sentence.lower(),
        )

        key = normalize_space(key)

        if key in seen:
            continue

        seen.add(key)

        record = {
            "tags": tags,
            "text": sentence,
        }

        sequential.append(record)

        if "BRAKING" in tags:
            braking.append(sentence)

        if "GEAR" in tags:
            gears.append(sentence)

        if "TRACK_LIMIT" in tags:
            track_limits.append(sentence)

    braking = unique_preserve_order(
        braking
    )

    gears = unique_preserve_order(
        gears
    )

    track_limits = unique_preserve_order(
        track_limits
    )

    return {
        "confidence": (
            "HIGH"
            if len(sequential) >= 10
            else "MEDIUM"
        ),
        "sequential": sequential,
        "braking_references": braking,
        "gears": gears,
        "track_limits": track_limits,
    }


# ======================================================================================
# LIVE CAR META
# ======================================================================================

def extract_live_car_meta(
    snapshot: Any,
) -> List[Dict[str, Any]]:

    if not isinstance(snapshot, dict):
        return []

    raw = snapshot.get(
        "top5_used_cars"
    )

    if not isinstance(raw, list):
        raw = recursive_find_first(
            snapshot,
            ["top5_used_cars"],
        )

    if not isinstance(raw, list):
        return []

    result = []

    for item in raw:

        if not isinstance(item, dict):
            continue

        car = safe_str(
            item.get("car"),
            "",
        )

        count = item.get("count")
        percentage = item.get(
            "percentage"
        )

        if not car:
            continue

        result.append(
            {
                "car": car,
                "count": count,
                "percentage": percentage,
            }
        )

    return result[:5]


# ======================================================================================
# REPORT FORMATTING
# ======================================================================================

def evidence_line(
    item: Dict[str, str],
) -> str:

    timestamp = item.get(
        "timestamp",
        "",
    )

    text = item.get(
        "text",
        "",
    )

    if timestamp:
        return f"[{timestamp}] {text}"

    return text


def fmt_multiplier(
    value: Any,
) -> str:

    if value is None:
        return "unknown"

    return f"x{value}"


def fmt_compounds(
    compounds: List[str],
) -> str:

    if not compounds:
        return "unknown"

    return ", ".join(compounds)


def build_report(
    live: Dict[str, Any],
    strategy: Dict[str, Any],
    lap_guide: Dict[str, Any],
    meta: List[Dict[str, Any]],
) -> str:

    lines: List[str] = []

    lines.append(SEPARATOR)
    lines.append(
        f"GT7 COMMUNITY INTELLIGENCE V{VERSION}"
    )
    lines.append(SEPARATOR)

    lines.append(
        f"Race week        : {live['week']}"
    )
    lines.append(
        f"Track            : {live['track']}"
    )
    lines.append(
        f"Class            : {live['class']}"
    )
    lines.append(
        f"Direction        : {live['direction']}"
    )
    lines.append(
        f"Fuel             : {fmt_multiplier(live['fuel_multiplier'])}"
    )
    lines.append(
        f"Tyre wear        : {fmt_multiplier(live['tyre_multiplier'])}"
    )
    lines.append(
        f"Compounds        : {fmt_compounds(live['compounds'])}"
    )

    lines.append("")
    lines.append("SOURCE POLICY")
    lines.append(SUB_SEPARATOR)

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

    # ------------------------------------------------------------------
    # Strategy
    # ------------------------------------------------------------------

    lines.append("")
    lines.append(
        "RACE STRATEGY — DIGIT RACING"
    )
    lines.append(SUB_SEPARATOR)

    lines.append(
        f"Confidence       : {strategy['confidence']}"
    )

    lines.append(
        f"Preferred logic  : {strategy['preferred_logic']}"
    )

    lines.append(
        "Tyre saving      : "
        + (
            "SUPPORTED BY DIGIT"
            if strategy[
                "tyre_saving_supported"
            ]
            else "not explicitly established"
        )
    )

    lines.append(
        "Tyre change      : "
        + (
            "SUPPORTED BY DIGIT"
            if strategy[
                "tyre_change_supported"
            ]
            else "not established from Digit transcript"
        )
    )

    lines.append(
        "Citroën          : "
        + (
            "SUPPORTED BY DIGIT"
            if strategy[
                "citroen_supported"
            ]
            else "not explicitly established"
        )
    )

    lines.append("")

    for index, recommendation in enumerate(
        strategy["recommendations"],
        start=1,
    ):
        lines.append(
            f"{index}. {recommendation}"
        )

    evidence = strategy[
        "evidence"
    ]

    lines.append("")
    lines.append(
        "STRATEGY EVIDENCE — CLEANED"
    )
    lines.append(SUB_SEPARATOR)

    sections = [
        (
            "Overcut / stay out",
            evidence["overcut"],
        ),
        (
            "Tyre saving",
            evidence["tyre_saving"],
        ),
        (
            "Tyre change",
            evidence["tyre_change"],
        ),
        (
            "Compounds",
            evidence["compounds"],
        ),
        (
            "Citroën / meta",
            evidence["citroen"],
        ),
        (
            "Pit-window discussion",
            evidence["pit_window"],
        ),
    ]

    for title, items in sections:

        if not items:
            continue

        lines.append("")
        lines.append(
            f"{title}:"
        )

        for item in items:
            lines.append(
                "  - "
                + evidence_line(item)
            )

    # ------------------------------------------------------------------
    # GnC
    # ------------------------------------------------------------------

    lines.append("")
    lines.append(
        "QUALIFYING / FAST LAP — GNC RACING"
    )
    lines.append(SUB_SEPARATOR)

    lines.append(
        f"Confidence       : {lap_guide['confidence']}"
    )

    for index, item in enumerate(
        lap_guide["sequential"],
        start=1,
    ):

        tags = "/".join(
            item["tags"]
        )

        lines.append(
            f"{index:2d}. [{tags}] {item['text']}"
        )

    lines.append("")
    lines.append(
        "BRAKING REFERENCES — GNC"
    )
    lines.append(SUB_SEPARATOR)

    for item in lap_guide[
        "braking_references"
    ]:
        lines.append(
            f"- {item}"
        )

    lines.append("")
    lines.append(
        "GEARS / SHIFTING — GNC"
    )
    lines.append(SUB_SEPARATOR)

    for item in lap_guide[
        "gears"
    ]:
        lines.append(
            f"- {item}"
        )

    lines.append("")
    lines.append(
        "TRACK LIMITS / KERBS — GNC"
    )
    lines.append(SUB_SEPARATOR)

    for item in lap_guide[
        "track_limits"
    ]:
        lines.append(
            f"- {item}"
        )

    # ------------------------------------------------------------------
    # Meta
    # ------------------------------------------------------------------

    lines.append("")
    lines.append(
        "LIVE CAR META — TOP 1000"
    )
    lines.append(SUB_SEPARATOR)

    if meta:

        for index, item in enumerate(
            meta,
            start=1,
        ):

            count = item.get(
                "count"
            )

            percentage = item.get(
                "percentage"
            )

            if isinstance(
                percentage,
                (int, float),
            ):
                percentage_text = (
                    f"{percentage:.1f}%"
                )
            else:
                percentage_text = "unknown"

            lines.append(
                f"{index:2d}. "
                f"{item['car']} | "
                f"{count} drivers | "
                f"{percentage_text}"
            )

    else:
        lines.append(
            "No live car meta available."
        )

    # ------------------------------------------------------------------
    # Practical plan
    # ------------------------------------------------------------------

    lines.append("")
    lines.append(
        "PRACTICAL RACE PLAN"
    )
    lines.append(SUB_SEPARATOR)

    practical = []

    practical.append(
        "Use the official/live race configuration as the regulatory baseline."
    )

    if strategy[
        "preferred_logic"
    ] == "OVERCUT / EXTEND FIRST STINT":

        practical.append(
            "Do not treat laps 4-5 as a rigid pit window. "
            "Digit's later race-tested conclusion favours staying "
            "out longer and using the overcut rather than stopping early."
        )

    if strategy[
        "tyre_saving_supported"
    ]:
        practical.append(
            "Protect the tyres during the first stint; excessive steering, "
            "sliding and front-tyre overload reduce the benefit of the overcut."
        )

    if strategy[
        "tyre_change_supported"
    ]:
        practical.append(
            "Complete the required tyre change and ensure both permitted "
            "race compounds are handled consistently with the live regulations."
        )

    if strategy[
        "citroen_supported"
    ]:

        if meta and meta[0][
            "car"
        ].lower().startswith(
            "gt by citro"
        ):
            practical.append(
                "The GT by Citroën Gr.4 is supported independently by "
                "both Digit's race experience and the live leaderboard meta."
            )
        else:
            practical.append(
                "Digit supports the GT by Citroën Gr.4; compare that "
                "recommendation against the live leaderboard before choosing the car."
            )

    practical.append(
        "Use the GnC guide for braking references, gears, racing line "
        "and throttle technique; do not mix lap instructions from other "
        "community sources."
    )

    for index, text in enumerate(
        practical,
        start=1,
    ):
        lines.append(
            f"{index}. {text}"
        )

    # ------------------------------------------------------------------
    # Policy
    # ------------------------------------------------------------------

    lines.append("")
    lines.append(
        "ANALYSIS POLICY"
    )
    lines.append(SUB_SEPARATOR)

    policies = [
        "Digit Racing is the sole community source for race strategy.",
        "GnC Racing is the sole community source for qualifying/lap guidance.",
        "Live GT7/GTSH data overrides any conflicting community statement.",
        "Later race-tested Digit conclusions override earlier speculative strategy comments.",
        "Live leaderboard usage is authoritative for current car meta.",
        "Snapshot Top-1000 car percentages are used directly and are never renormalized.",
        "Transcript evidence is cleaned for ASR duplication before analysis.",
        "Irrelevant tyre references such as controller/wheel discussion are excluded from strategy evidence.",
        "Transcript evidence is never used to invent missing braking points, gears or strategy.",
    ]

    for index, text in enumerate(
        policies,
        start=1,
    ):
        lines.append(
            f"{index}. {text}"
        )

    return "\n".join(lines)


# ======================================================================================
# MAIN
# ======================================================================================

def main() -> None:

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    snapshot = load_json(
        LATEST_SNAPSHOT
    )

    digit_path, digit_text = (
        load_channel_transcript(
            STRATEGY_CHANNEL
        )
    )

    gnc_path, gnc_text = (
        load_channel_transcript(
            LAP_GUIDE_CHANNEL
        )
    )

    print(SEPARATOR)
    print(
        f"GT7 COMMUNITY ANALYZER V{VERSION}"
    )
    print(SEPARATOR)

    print(
        "Digit transcript : "
        + (
            "FOUND"
            if digit_text
            else "NOT FOUND"
        )
    )

    print(
        "GnC transcript   : "
        + (
            "FOUND"
            if gnc_text
            else "NOT FOUND"
        )
    )

    print(
        f"Digit characters : {len(digit_text):,}"
    )

    print(
        f"GnC characters   : {len(gnc_text):,}"
    )

    live = extract_live_config(
        snapshot
    )

    print("")
    print("LIVE CONFIGURATION")
    print(SUB_SEPARATOR)

    print(
        f"Week             : {live['week']}"
    )

    print(
        f"Track            : {live['track']}"
    )

    print(
        f"Class            : {live['class']}"
    )

    print(
        f"Direction        : {live['direction']}"
    )

    print(
        f"Fuel             : {fmt_multiplier(live['fuel_multiplier'])}"
    )

    print(
        f"Tyre wear        : {fmt_multiplier(live['tyre_multiplier'])}"
    )

    print(
        f"Compounds        : {fmt_compounds(live['compounds'])}"
    )

    if not digit_text:
        raise RuntimeError(
            "Digit Racing transcript not found."
        )

    if not gnc_text:
        raise RuntimeError(
            "GnC Racing transcript not found."
        )

    strategy = extract_digit_strategy(
        digit_text
    )

    lap_guide = extract_gnc_lap_guide(
        gnc_text
    )

    meta = extract_live_car_meta(
        snapshot
    )

    report = build_report(
        live,
        strategy,
        lap_guide,
        meta,
    )

    output = {
        "version": VERSION,
        "live_configuration": live,
        "source_policy": {
            "race_strategy": (
                "Digit Racing only"
            ),
            "qualifying_guide": (
                "GnC Racing only"
            ),
            "race_regulations": (
                "live GT7/GTSH snapshot"
            ),
            "car_meta": (
                "live leaderboard"
            ),
        },
        "sources": {
            "digit_transcript": (
                str(digit_path)
                if digit_path
                else None
            ),
            "gnc_transcript": (
                str(gnc_path)
                if gnc_path
                else None
            ),
        },
        "race_strategy": strategy,
        "lap_guide": lap_guide,
        "live_car_meta": meta,
    }

    save_json(
        OUTPUT_JSON,
        output,
    )

    OUTPUT_REPORT.write_text(
        report,
        encoding="utf-8",
    )

    print("")
    print(report)

    print("")
    print(SEPARATOR)

    print(
        f"JSON report      : {OUTPUT_JSON}"
    )

    print(
        f"Text report      : {OUTPUT_REPORT}"
    )

    print("")
    print(SEPARATOR)

    print(
        "COMMUNITY INTELLIGENCE COMPLETE"
    )

    print(SEPARATOR)


if __name__ == "__main__":
    main()