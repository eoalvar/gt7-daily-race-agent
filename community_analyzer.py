#!/usr/bin/env python3

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ======================================================================================
# CONFIGURATION
# ======================================================================================

VERSION = "7.1"

DATA_DIR = Path("data")

LATEST_SNAPSHOT = DATA_DIR / "latest_snapshot.json"

TRANSCRIPT_DB = DATA_DIR / "community_transcripts.json"
TRANSCRIPT_DIR = DATA_DIR / "community_transcripts"

OUTPUT_DIR = DATA_DIR / "community_intelligence"

OUTPUT_JSON = OUTPUT_DIR / "community_intelligence.json"
OUTPUT_REPORT = OUTPUT_DIR / "community_intelligence.txt"
OUTPUT_AUDIT = OUTPUT_DIR / "community_intelligence_audit.txt"

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
        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except Exception:
        return None


def save_json(
    path: Path,
    data: Any,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def safe_str(
    value: Any,
    default: str = "unknown",
) -> str:
    if value is None:
        return default

    text = str(value).strip()

    return text if text else default


def normalize_space(
    text: str,
) -> str:
    return re.sub(
        r"\s+",
        " ",
        text or "",
    ).strip()


def normalize_key(
    text: str,
) -> str:
    text = normalize_space(
        text
    ).lower()

    text = re.sub(
        r"[^a-z0-9à-ÿ ]",
        "",
        text,
        flags=re.IGNORECASE,
    )

    return normalize_space(
        text
    )


def unique_preserve_order(
    items: List[str],
) -> List[str]:
    seen = set()
    result: List[str] = []

    for item in items:
        cleaned = normalize_space(
            item
        )

        key = normalize_key(
            cleaned
        )

        if not key:
            continue

        if key in seen:
            continue

        seen.add(key)
        result.append(
            cleaned
        )

    return result


def text_has_any(
    text: str,
    phrases: List[str],
) -> bool:
    low = text.lower()

    return any(
        phrase.lower() in low
        for phrase in phrases
    )


def ascii_console(
    text: Any,
) -> str:
    """
    Console-safe representation.

    GitHub Actions sometimes renders punctuation such as:
        em dash
        right arrow
        accented Citroen
    incorrectly depending on the UI/encoding chain.

    The JSON and TXT files remain UTF-8. Console output uses
    conservative ASCII equivalents.
    """

    value = str(
        text
    )

    replacements = {
        "→": "->",
        "—": "-",
        "–": "-",
        "-": "-",
        "Citroën": "Citroen",
        "citroën": "citroen",
        "ë": "e",
        "Ë": "E",
        "’": "'",
        "“": '"',
        "”": '"',
        "…": "...",
    }

    for old, new in replacements.items():
        value = value.replace(
            old,
            new,
        )

    return value


def console_print(
    text: Any = "",
) -> None:
    print(
        ascii_console(
            text
        )
    )


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

    return ", ".join(
        compounds
    )


def fmt_percentage(
    value: Any,
    decimals: int = 2,
) -> str:
    if not isinstance(
        value,
        (int, float),
    ):
        return "unknown"

    return (
        f"{value:.{decimals}f}%"
    )


# ======================================================================================
# TRANSCRIPT CLEANING
# ======================================================================================

NOISE_PATTERNS = [
    r"\[music\]",
    r"\[applause\]",
    r"\[laughter\]",
    r"\[foreign\]",
    r"\[snorts?\]",
    r"&gt;&gt;",
    r">>",
]


FILLER_ONLY_PATTERNS = [
    r"^(yeah|okay|ok|well|so|um|uh|huh|right|yes|no)[.!?, ]*$",
    r"^(thank you|thanks)[.!?, ]*$",
]


def remove_noise_tokens(
    text: str,
) -> str:
    result = text or ""

    for pattern in NOISE_PATTERNS:
        result = re.sub(
            pattern,
            " ",
            result,
            flags=re.IGNORECASE,
        )

    return normalize_space(
        result
    )


def collapse_repeated_word_runs(
    text: str,
) -> str:
    """
    Removes repeated ASR blocks such as:

        Yeah. Yeah. Yeah.
        tires tires tires
        stayed out stayed out stayed out
        lap four lap four lap four
    """

    result = normalize_space(
        text
    )

    for block_size in range(
        8,
        0,
        -1,
    ):

        pattern = re.compile(
            r"\b("
            + r"\S+(?:\s+\S+){"
            + str(
                block_size - 1
            )
            + r"})"
            + r"(?:[\s,.;:!?-]+\1){1,6}\b",
            flags=re.IGNORECASE,
        )

        previous = None

        while previous != result:
            previous = result

            result = pattern.sub(
                r"\1",
                result,
            )

    return normalize_space(
        result
    )


def remove_adjacent_duplicate_phrases(
    text: str,
) -> str:
    words = normalize_space(
        text
    ).split()

    if not words:
        return ""

    changed = True

    while changed:
        changed = False

        max_size = min(
            12,
            len(words) // 2,
        )

        for size in range(
            max_size,
            2,
            -1,
        ):
            i = 0

            while (
                i + (2 * size)
                <= len(words)
            ):

                left = [
                    normalize_key(
                        word
                    )
                    for word in words[
                        i:i + size
                    ]
                ]

                right = [
                    normalize_key(
                        word
                    )
                    for word in words[
                        i + size:
                        i + (2 * size)
                    ]
                ]

                if left == right:
                    del words[
                        i + size:
                        i + (2 * size)
                    ]

                    changed = True
                else:
                    i += 1

    return normalize_space(
        " ".join(
            words
        )
    )


def collapse_repeated_sentences(
    text: str,
) -> str:
    text = normalize_space(
        text
    )

    parts = re.split(
        r"(?<=[.!?])\s+",
        text,
    )

    cleaned: List[str] = []
    recent_keys: List[str] = []

    for part in parts:
        part = normalize_space(
            part
        )

        if not part:
            continue

        key = normalize_key(
            part
        )

        if not key:
            continue

        if key in recent_keys[-3:]:
            continue

        cleaned.append(
            part
        )

        recent_keys.append(
            key
        )

    return normalize_space(
        " ".join(
            cleaned
        )
    )


def remove_filler_fragments(
    text: str,
) -> str:
    parts = re.split(
        r"(?<=[.!?])\s+",
        normalize_space(
            text
        ),
    )

    result: List[str] = []

    for part in parts:
        cleaned = normalize_space(
            part
        )

        if not cleaned:
            continue

        filler = False

        for pattern in FILLER_ONLY_PATTERNS:
            if re.match(
                pattern,
                cleaned,
                flags=re.IGNORECASE,
            ):
                filler = True
                break

        if filler:
            continue

        result.append(
            cleaned
        )

    return normalize_space(
        " ".join(
            result
        )
    )


def clean_transcript_text(
    text: str,
) -> str:
    text = remove_noise_tokens(
        text
    )

    text = collapse_repeated_word_runs(
        text
    )

    text = remove_adjacent_duplicate_phrases(
        text
    )

    text = collapse_repeated_sentences(
        text
    )

    text = remove_filler_fragments(
        text
    )

    return normalize_space(
        text
    )


# ======================================================================================
# TIMESTAMP HANDLING
# ======================================================================================

TIMESTAMP_RE = re.compile(
    r"\[(?P<time>(?:\d+:)?\d{1,2}:\d{2})\]"
)


def split_timestamped_chunks(
    text: str,
) -> List[Dict[str, str]]:
    matches = list(
        TIMESTAMP_RE.finditer(
            text
        )
    )

    if not matches:
        cleaned = clean_transcript_text(
            text
        )

        if not cleaned:
            return []

        return [
            {
                "timestamp": "",
                "text": cleaned,
            }
        ]

    chunks: List[
        Dict[str, str]
    ] = []

    for index, match in enumerate(
        matches
    ):
        start = match.end()

        if (
            index + 1
            < len(matches)
        ):
            end = matches[
                index + 1
            ].start()
        else:
            end = len(text)

        timestamp = match.group(
            "time"
        )

        body = clean_transcript_text(
            text[start:end]
        )

        if not body:
            continue

        chunks.append(
            {
                "timestamp": timestamp,
                "text": body,
            }
        )

    return chunks


def timestamp_seconds(
    timestamp: str,
) -> int:
    if not timestamp:
        return 0

    try:
        parts = [
            int(part)
            for part
            in timestamp.split(":")
        ]
    except Exception:
        return 0

    if len(parts) == 2:
        minutes, seconds = parts

        return (
            minutes * 60
            + seconds
        )

    if len(parts) == 3:
        hours, minutes, seconds = parts

        return (
            hours * 3600
            + minutes * 60
            + seconds
        )

    return 0


# ======================================================================================
# RECURSIVE JSON HELPERS
# ======================================================================================

def recursive_find_first(
    data: Any,
    keys: List[str],
) -> Any:
    key_set = set(
        keys
    )

    if isinstance(
        data,
        dict,
    ):

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

    elif isinstance(
        data,
        list,
    ):

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
    required = set(
        required_keys
    )

    if isinstance(
        data,
        dict,
    ):

        if required.issubset(
            set(
                data.keys()
            )
        ):
            return data

        for value in data.values():
            found = recursive_find_dict_with_keys(
                value,
                required_keys,
            )

            if found is not None:
                return found

    elif isinstance(
        data,
        list,
    ):

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
        (
            r"Grand Valley\s*-\s*Highway\s*1",
            "Grand Valley - Highway 1",
        ),
        (
            r"Grand Valley Highway\s*1",
            "Grand Valley - Highway 1",
        ),
    ]

    for pattern, name in known_patterns:
        if re.search(
            pattern,
            description,
            re.IGNORECASE,
        ):
            return name

    match = re.search(
        r"Daily Race C.*?"
        r"\d{1,2}:\d{2}\s+"
        r"(.+?)\s+"
        r"[A-Z]\.\s+[A-Za-zÀ-ÿ]",
        description,
        re.IGNORECASE,
    )

    if match:
        return normalize_space(
            match.group(1)
        )

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

    if not match:
        return "unknown"

    return re.sub(
        r"\s+",
        "",
        match.group(0),
    )


def extract_live_config(
    snapshot: Any,
) -> Dict[str, Any]:
    race = None

    if isinstance(
        snapshot,
        dict,
    ):
        race = snapshot.get(
            "race"
        )

    if not isinstance(
        race,
        dict,
    ):
        race = recursive_find_dict_with_keys(
            snapshot,
            [
                "fuel_multiplier",
                "tyre_multiplier",
            ],
        )

    if not isinstance(
        race,
        dict,
    ):
        race = {}

    description = safe_str(
        race.get(
            "description"
        ),
        "",
    )

    start_date = (
        race.get(
            "start_date"
        )
        or recursive_find_first(
            snapshot,
            [
                "start_date",
                "week",
                "race_week",
            ],
        )
    )

    track = (
        race.get(
            "track"
        )
        or race.get(
            "track_name"
        )
        or recursive_find_first(
            race,
            [
                "track",
                "track_name",
            ],
        )
    )

    if not track:
        track = extract_track_from_description(
            description
        )

    race_class = (
        race.get(
            "class"
        )
        or race.get(
            "race_class"
        )
        or recursive_find_first(
            race,
            [
                "class",
                "race_class",
            ],
        )
    )

    if not race_class:
        race_class = extract_class_from_description(
            description
        )

    direction = (
        race.get(
            "direction"
        )
        or "NORMAL"
    )

    fuel = (
        race.get(
            "fuel_multiplier"
        )
        or recursive_find_first(
            race,
            [
                "fuel_multiplier"
            ],
        )
    )

    tyres = (
        race.get(
            "tyre_multiplier"
        )
        or race.get(
            "tire_multiplier"
        )
        or recursive_find_first(
            race,
            [
                "tyre_multiplier",
                "tire_multiplier",
            ],
        )
    )

    compounds = (
        race.get(
            "compounds"
        )
        or recursive_find_first(
            race,
            [
                "compounds"
            ],
        )
        or []
    )

    if not isinstance(
        compounds,
        list,
    ):
        compounds = [
            compounds
        ]

    compounds = [
        safe_str(
            item,
            "",
        )
        for item
        in compounds
        if safe_str(
            item,
            "",
        )
    ]

    return {
        "week": safe_str(
            start_date
        ),
        "track": safe_str(
            track
        ),
        "class": safe_str(
            race_class
        ),
        "direction": safe_str(
            direction,
            "NORMAL",
        ),
        "fuel_multiplier": fuel,
        "tyre_multiplier": tyres,
        "compounds": compounds,
        "description": description,
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
        .replace(
            " ",
            "_",
        )
    )

    if not TRANSCRIPT_DIR.exists():
        return None

    candidates: List[
        Path
    ] = []

    for path in TRANSCRIPT_DIR.glob(
        "*.json"
    ):
        name = path.name.lower()

        if fragment in name:
            candidates.append(
                path
            )

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

    if isinstance(
        data,
        str,
    ):
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

    if isinstance(
        possible,
        str,
    ):
        return possible

    return ""


def load_channel_transcript(
    channel: str,
) -> Tuple[
    Optional[Path],
    str,
]:
    path = find_transcript_file(
        channel
    )

    if path is None:
        return None, ""

    data = load_json(
        path
    )

    text = extract_transcript_text(
        data
    )

    return path, text


# ======================================================================================
# EVIDENCE HELPERS
# ======================================================================================

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


def evidence_is_near_duplicate(
    a: str,
    b: str,
) -> bool:
    a_key = normalize_key(
        clean_transcript_text(
            a
        )
    )

    b_key = normalize_key(
        clean_transcript_text(
            b
        )
    )

    if not a_key or not b_key:
        return False

    if a_key == b_key:
        return True

    if (
        len(a_key) >= 30
        and a_key in b_key
    ):
        return True

    if (
        len(b_key) >= 30
        and b_key in a_key
    ):
        return True

    a_words = set(
        a_key.split()
    )

    b_words = set(
        b_key.split()
    )

    union = len(
        a_words | b_words
    )

    if union == 0:
        return False

    overlap = len(
        a_words & b_words
    )

    return (
        overlap / union
        >= 0.88
    )


def deduplicate_evidence(
    evidence: List[
        Dict[str, str]
    ],
) -> List[
    Dict[str, str]
]:
    result: List[
        Dict[str, str]
    ] = []

    for item in evidence:
        text = clean_transcript_text(
            item.get(
                "text",
                "",
            )
        )

        if not text:
            continue

        duplicate = any(
            evidence_is_near_duplicate(
                text,
                existing[
                    "text"
                ],
            )
            for existing
            in result
        )

        if duplicate:
            continue

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


# ======================================================================================
# DIGIT RACING STRATEGY
# ======================================================================================

def is_bad_strategy_context(
    text: str,
) -> bool:
    low = text.lower()

    bad_contexts = [
        "switched to wheel",
        "controller versus",
        "endurance championship",
        "difficult to get used to the wheel",
        "setup video",
        "pedal cam",
        "theme song",
        "copyright",
        "nickname",
        "mechanic",
        "new brakes",
        "power outage",
        "air conditioning",
        "package",
    ]

    return any(
        phrase in low
        for phrase
        in bad_contexts
    )


def strategy_relevance_score(
    text: str,
) -> int:
    low = text.lower()

    score = 0

    weights = {
        "overcut": 10,
        "undercut": 6,
        "should have stayed out": 12,
        "pitted earlier": 10,
        "pit later": 8,
        "lap four": 6,
        "lap five": 6,
        "required tire change": 10,
        "required tyre change": 10,
        "need to change the tires": 10,
        "need to change the tyres": 10,
        "mediums and soft": 8,
        "racing mediums": 5,
        "racing soft": 5,
        "tire saving": 7,
        "tyre saving": 7,
        "saving tires": 7,
        "saving tyres": 7,
        "gentle with my tires": 7,
        "gentle with my tyres": 7,
        "citroen": 4,
        "citroën": 4,
        "tire wear": 3,
        "tyre wear": 3,
        "fuel": 2,
    }

    for phrase, weight in weights.items():
        if phrase in low:
            score += weight

    if is_bad_strategy_context(
        text
    ):
        score -= 20

    return score


def best_evidence(
    evidence: List[
        Dict[str, str]
    ],
    limit: int,
    prefer_late: bool = False,
) -> List[
    Dict[str, str]
]:
    items = deduplicate_evidence(
        evidence
    )

    if prefer_late:
        items = sorted(
            items,
            key=lambda item: (
                timestamp_seconds(
                    item[
                        "timestamp"
                    ]
                ),
                strategy_relevance_score(
                    item[
                        "text"
                    ]
                ),
            ),
            reverse=True,
        )
    else:
        items = sorted(
            items,
            key=lambda item: (
                strategy_relevance_score(
                    item[
                        "text"
                    ]
                ),
                timestamp_seconds(
                    item[
                        "timestamp"
                    ]
                ),
            ),
            reverse=True,
        )

    return items[:limit]


def detect_compound_plan(
    evidence: Dict[
        str,
        List[
            Dict[str, str]
        ],
    ],
    live_compounds: List[str],
) -> Dict[str, Any]:
    combined = " ".join(
        item[
            "text"
        ]
        for group
        in evidence.values()
        for item
        in group
    ).lower()

    permitted = [
        str(
            item
        ).upper()
        for item
        in live_compounds
    ]

    has_rm = (
        "RM" in permitted
        and text_has_any(
            combined,
            [
                "mediums",
                "racing medium",
                "racing mediums",
            ],
        )
    )

    has_rs = (
        "RS" in permitted
        and text_has_any(
            combined,
            [
                "soft",
                "softs",
                "racing soft",
                "soft tires",
                "soft tyres",
            ],
        )
    )

    starts_medium = text_has_any(
        combined,
        [
            "starting on the mediums",
            "typically starting on the mediums",
            "start on the mediums",
            "starting on mediums",
        ],
    )

    change_rule = bool(
        evidence.get(
            "tyre_change"
        )
    )

    if (
        has_rm
        and has_rs
        and starts_medium
        and change_rule
    ):
        return {
            "established": True,
            "start_compound": "RM",
            "finish_compound": "RS",
            "sequence": "RM -> RS",
            "confidence": "HIGH",
            "reason": (
                "Digit explicitly discusses starting on Racing Medium, "
                "changing tyres and using the RM/RS combination. "
                "The live race configuration also confirms RM and RS."
            ),
        }

    if (
        has_rm
        and has_rs
        and change_rule
    ):
        return {
            "established": False,
            "start_compound": None,
            "finish_compound": None,
            "sequence": "RM / RS - order not fully established",
            "confidence": "MEDIUM",
            "reason": (
                "Both compounds and the tyre-change requirement are supported, "
                "but the order is not established strongly enough."
            ),
        }

    return {
        "established": False,
        "start_compound": None,
        "finish_compound": None,
        "sequence": "NOT ESTABLISHED",
        "confidence": "LOW",
        "reason": (
            "Available evidence is insufficient to establish a compound sequence."
        ),
    }


def determine_pit_strategy(
    evidence: Dict[
        str,
        List[
            Dict[str, str]
        ],
    ],
) -> Dict[str, Any]:
    early = evidence.get(
        "pit_window",
        [],
    )

    late = evidence.get(
        "overcut",
        [],
    )

    if late:
        latest = max(
            late,
            key=lambda item: timestamp_seconds(
                item[
                    "timestamp"
                ]
            ),
        )

        return {
            "mode": "OVERCUT / EXTEND FIRST STINT",
            "rigid_window": False,
            "initial_reference": (
                "Lap 4-5 was discussed initially."
                if early
                else None
            ),
            "final_conclusion": (
                "Later race-tested evidence favours staying out longer than "
                "the initial Lap 4-5 reference when tyre condition and traffic allow."
            ),
            "latest_timestamp": latest.get(
                "timestamp"
            ),
            "confidence": "HIGH",
        }

    if early:
        return {
            "mode": "LAP 4-5 REFERENCE",
            "rigid_window": False,
            "initial_reference": (
                "Digit discusses approximately Lap 4-5."
            ),
            "final_conclusion": (
                "No later race-tested evidence overrides this initial reference."
            ),
            "latest_timestamp": None,
            "confidence": "MEDIUM",
        }

    return {
        "mode": "NOT ESTABLISHED",
        "rigid_window": False,
        "initial_reference": None,
        "final_conclusion": (
            "No reliable pit timing conclusion could be extracted."
        ),
        "latest_timestamp": None,
        "confidence": "LOW",
    }


def extract_digit_strategy(
    raw_text: str,
    live: Dict[str, Any],
) -> Dict[str, Any]:
    chunks = split_timestamped_chunks(
        raw_text
    )

    raw_evidence: Dict[
        str,
        List[
            Dict[str, str]
        ],
    ] = {
        "overcut": [],
        "tyre_saving": [],
        "tyre_change": [],
        "compounds": [],
        "citroen": [],
        "pit_window": [],
    }

    for chunk in chunks:
        text = chunk[
            "text"
        ]

        low = text.lower()

        if text_has_any(
            low,
            [
                "overcut",
                "should have stayed out",
                "pitted earlier",
                "pit later",
                "stayed out",
            ],
        ):
            raw_evidence[
                "overcut"
            ].append(
                evidence_record(
                    chunk
                )
            )

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
                "dont want to get too much on the front",
            ],
        )

        if (
            tyre_saving_signal
            and not is_bad_strategy_context(
                text
            )
        ):
            raw_evidence[
                "tyre_saving"
            ].append(
                evidence_record(
                    chunk
                )
            )

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
            raw_evidence[
                "tyre_change"
            ].append(
                evidence_record(
                    chunk
                )
            )

        has_medium = text_has_any(
            low,
            [
                "mediums",
                "medium tire",
                "medium tyre",
                "racing medium",
            ],
        )

        has_soft = text_has_any(
            low,
            [
                "soft tires",
                "soft tyres",
                "softs",
                "racing soft",
                "mediums and soft",
            ],
        )

        if (
            has_medium
            and has_soft
        ):
            raw_evidence[
                "compounds"
            ].append(
                evidence_record(
                    chunk
                )
            )

        if (
            (
                "citroen" in low
                or "citroën" in low
            )
            and text_has_any(
                low,
                [
                    "meta",
                    "cup",
                    "strong",
                    "tire wear",
                    "tyre wear",
                    "faster overall",
                    "tires are better",
                    "tyres are better",
                ],
            )
        ):
            raw_evidence[
                "citroen"
            ].append(
                evidence_record(
                    chunk
                )
            )

        has_lap_window = text_has_any(
            low,
            [
                "lap four",
                "lap five",
                "lap 4",
                "lap 5",
            ],
        )

        has_pit_context = text_has_any(
            low,
            [
                "pit",
                "change the tires",
                "change the tyres",
            ],
        )

        if (
            has_lap_window
            and has_pit_context
        ):
            raw_evidence[
                "pit_window"
            ].append(
                evidence_record(
                    chunk
                )
            )

    evidence = {
        "overcut": best_evidence(
            raw_evidence[
                "overcut"
            ],
            limit=4,
            prefer_late=True,
        ),
        "tyre_saving": best_evidence(
            raw_evidence[
                "tyre_saving"
            ],
            limit=3,
        ),
        "tyre_change": best_evidence(
            raw_evidence[
                "tyre_change"
            ],
            limit=2,
        ),
        "compounds": best_evidence(
            raw_evidence[
                "compounds"
            ],
            limit=2,
        ),
        "citroen": best_evidence(
            raw_evidence[
                "citroen"
            ],
            limit=2,
            prefer_late=True,
        ),
        "pit_window": best_evidence(
            raw_evidence[
                "pit_window"
            ],
            limit=2,
        ),
    }

    pit_strategy = determine_pit_strategy(
        evidence
    )

    compound_plan = detect_compound_plan(
        evidence,
        live.get(
            "compounds",
            [],
        ),
    )

    confidence_score = 0

    if evidence[
        "overcut"
    ]:
        confidence_score += 3

    if evidence[
        "tyre_saving"
    ]:
        confidence_score += 2

    if evidence[
        "tyre_change"
    ]:
        confidence_score += 2

    if evidence[
        "compounds"
    ]:
        confidence_score += 1

    if evidence[
        "citroen"
    ]:
        confidence_score += 1

    if compound_plan[
        "established"
    ]:
        confidence_score += 1

    if confidence_score >= 8:
        confidence = "HIGH"
    elif confidence_score >= 4:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    recommendations: List[str] = []

    if evidence[
        "overcut"
    ]:
        recommendations.append(
            "Later race-tested evidence favours the overcut: "
            "staying out longer performed better than stopping early."
        )

    if evidence[
        "tyre_saving"
    ]:
        recommendations.append(
            "Tyre preservation is strategically important. "
            "Minimise unnecessary steering input, sliding and front-tyre overload."
        )

    if evidence[
        "tyre_change"
    ]:
        recommendations.append(
            "The race requires the tyre-change rule to be satisfied."
        )

    if compound_plan[
        "established"
    ]:
        recommendations.append(
            "Usable Digit evidence supports RM -> RS: "
            "start on Racing Medium and switch to Racing Soft."
        )

    if evidence[
        "citroen"
    ]:
        recommendations.append(
            "Digit identifies the GT by Citroen Gr.4 as particularly strong, "
            "including tyre-life performance."
        )

    return {
        "confidence": confidence,
        "preferred_logic": pit_strategy[
            "mode"
        ],
        "pit_strategy": pit_strategy,
        "compound_plan": compound_plan,
        "tyre_saving_supported": bool(
            evidence[
                "tyre_saving"
            ]
        ),
        "tyre_change_supported": bool(
            evidence[
                "tyre_change"
            ]
        ),
        "citroen_supported": bool(
            evidence[
                "citroen"
            ]
        ),
        "recommendations": recommendations,
        "evidence": evidence,
    }


# ======================================================================================
# GNC LAP GUIDE
# ======================================================================================

def classify_gnc_line(
    text: str,
) -> List[str]:
    low = text.lower()

    tags: List[str] = []

    braking_verbs = text_has_any(
        low,
        [
            "brake",
            "braking",
            "break",
            "hit the brakes",
            "get on the brakes",
        ],
    )

    brake_markers = text_has_any(
        low,
        [
            "100 board",
            "200 board",
            "350 m",
            "50 m",
        ],
    )

    if (
        braking_verbs
        or brake_markers
    ):
        tags.append(
            "BRAKING"
        )

    if text_has_any(
        low,
        [
            "second gear",
            "third gear",
            "fourth gear",
            "fifth gear",
            "shift",
            "shifting",
            "gear",
        ],
    ):
        tags.append(
            "GEAR"
        )

    if text_has_any(
        low,
        [
            "accelerate",
            "power",
            "throttle",
            "full throttle",
        ],
    ):
        tags.append(
            "THROTTLE"
        )

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
            "drift over",
        ],
    ):
        tags.append(
            "LINE"
        )

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
        ],
    ):
        tags.append(
            "TRACK_LIMIT"
        )

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
        normalize_space(
            piece
        )
        for piece
        in pieces
        if normalize_space(
            piece
        )
    ]


def is_useful_gnc_sentence(
    sentence: str,
    tags: List[str],
) -> bool:
    low = sentence.lower()

    if not tags:
        return False

    bad_fragments = [
        "welcome",
        "subscribe",
        "leaderboard",
        "at the time of this recording",
        "today's lap",
        "todays lap",
        "hello",
    ]

    if any(
        phrase in low
        for phrase
        in bad_fragments
    ):
        return False

    if len(
        sentence
    ) < 18:
        return False

    return True


def extract_gear(
    text: str,
) -> Optional[str]:
    low = text.lower()

    gear_patterns = [
        (
            "second gear",
            "2nd",
        ),
        (
            "third gear",
            "3rd",
        ),
        (
            "fourth gear",
            "4th",
        ),
        (
            "fifth gear",
            "5th",
        ),
    ]

    for phrase, gear in gear_patterns:
        if phrase in low:
            return gear

    return None


def extract_brake_marker(
    text: str,
) -> Optional[str]:
    low = text.lower()

    if re.search(
        r"around\s+350\s*m",
        low,
    ):
        return "around 350 m"

    if re.search(
        r"\b350\s*m\b",
        low,
    ):
        return "350 m"

    if (
        "dark mark in the sand"
        in low
    ):
        return "dark mark in the sand"

    if (
        "after we pass under this bridge"
        in low
        or "just after we pass under this bridge"
        in low
    ):
        return "after the bridge"

    if (
        "exit the tunnel"
        in low
        and text_has_any(
            low,
            [
                "brake",
                "brakes",
                "braking",
                "break",
            ],
        )
    ):
        return "tunnel exit"

    if re.search(
        r"\b50\s*m\b",
        low,
    ):
        return "around 50 m"

    if (
        "200 board"
        in low
    ):
        return "200 board"

    if (
        "100 board"
        in low
    ):
        return "100 board"

    return None


def build_gnc_steps(
    raw_text: str,
) -> List[
    Dict[str, Any]
]:
    sentences = sentence_split(
        raw_text
    )

    steps: List[
        Dict[str, Any]
    ] = []

    seen: List[str] = []

    for sentence in sentences:
        tags = classify_gnc_line(
            sentence
        )

        if not is_useful_gnc_sentence(
            sentence,
            tags,
        ):
            continue

        duplicate = any(
            evidence_is_near_duplicate(
                sentence,
                previous,
            )
            for previous
            in seen
        )

        if duplicate:
            continue

        seen.append(
            sentence
        )

        steps.append(
            {
                "sequence": (
                    len(steps)
                    + 1
                ),
                "tags": tags,
                "instruction": sentence,
                "gear": extract_gear(
                    sentence
                ),
                "brake_marker": extract_brake_marker(
                    sentence
                ),
            }
        )

    return steps


def build_braking_events(
    steps: List[
        Dict[str, Any]
    ],
) -> List[
    Dict[str, Any]
]:
    """
    Groups sequential transcript instructions into braking events.

    This avoids treating:
        "look for the 200 board"
        "brake before it"
        "turn in..."
    as three independent corners/events.

    We still do NOT invent official corner numbers.
    """

    events: List[
        Dict[str, Any]
    ] = []

    current: Optional[
        Dict[str, Any]
    ] = None

    for index, step in enumerate(
        steps
    ):
        tags = step[
            "tags"
        ]

        if (
            "BRAKING"
            not in tags
        ):
            continue

        instruction = step[
            "instruction"
        ]

        low = instruction.lower()

        marker = step.get(
            "brake_marker"
        )

        gear = step.get(
            "gear"
        )

        is_marker_setup = (
            marker is not None
            and not text_has_any(
                low,
                [
                    "brake",
                    "brakes",
                    "braking",
                    "break",
                ],
            )
        )

        is_braking_action = text_has_any(
            low,
            [
                "brake",
                "brakes",
                "braking",
                "break",
                "hit the brakes",
                "get on the brakes",
            ],
        )

        if (
            is_marker_setup
            and current is None
        ):
            current = {
                "marker": marker,
                "gear": gear,
                "source_steps": [
                    step[
                        "sequence"
                    ]
                ],
                "evidence": [
                    instruction
                ],
            }

            continue

        if current is not None:
            current[
                "source_steps"
            ].append(
                step[
                    "sequence"
                ]
            )

            current[
                "evidence"
            ].append(
                instruction
            )

            if (
                current.get(
                    "marker"
                )
                is None
                and marker is not None
            ):
                current[
                    "marker"
                ] = marker

            if (
                current.get(
                    "gear"
                )
                is None
                and gear is not None
            ):
                current[
                    "gear"
                ] = gear

            if is_braking_action:
                events.append(
                    current
                )

                current = None

            continue

        if is_braking_action:
            event = {
                "marker": marker,
                "gear": gear,
                "source_steps": [
                    step[
                        "sequence"
                    ]
                ],
                "evidence": [
                    instruction
                ],
            }

            # Search the next two useful steps for a gear reference
            # belonging to the same braking manoeuvre.
            if event[
                "gear"
            ] is None:

                for future in steps[
                    index + 1:
                    index + 3
                ]:

                    future_tags = future[
                        "tags"
                    ]

                    if (
                        "BRAKING"
                        in future_tags
                        and future.get(
                            "brake_marker"
                        )
                        is not None
                    ):
                        break

                    future_gear = future.get(
                        "gear"
                    )

                    if future_gear:
                        event[
                            "gear"
                        ] = future_gear

                        event[
                            "source_steps"
                        ].append(
                            future[
                                "sequence"
                            ]
                        )

                        event[
                            "evidence"
                        ].append(
                            future[
                                "instruction"
                            ]
                        )

                        break

            events.append(
                event
            )

    if current is not None:
        events.append(
            current
        )

    cleaned_events: List[
        Dict[str, Any]
    ] = []

    for event in events:
        marker = event.get(
            "marker"
        )

        evidence_text = " ".join(
            event.get(
                "evidence",
                [],
            )
        )

        if (
            marker is None
            and not text_has_any(
                evidence_text,
                [
                    "brake",
                    "brakes",
                    "braking",
                    "break",
                ],
            )
        ):
            continue

        cleaned_events.append(
            {
                "event": (
                    len(
                        cleaned_events
                    )
                    + 1
                ),
                "marker": (
                    marker
                    or "marker not explicit"
                ),
                "gear": (
                    event.get(
                        "gear"
                    )
                    or "gear not explicit"
                ),
                "source_steps": event.get(
                    "source_steps",
                    [],
                ),
                "evidence": event.get(
                    "evidence",
                    [],
                ),
            }
        )

    return cleaned_events


def extract_gnc_lap_guide(
    raw_text: str,
) -> Dict[str, Any]:
    steps = build_gnc_steps(
        raw_text
    )

    braking_events = build_braking_events(
        steps
    )

    braking_references: List[str] = []
    gears: List[str] = []
    track_limits: List[str] = []
    throttle: List[str] = []
    racing_line: List[str] = []

    for step in steps:
        instruction = step[
            "instruction"
        ]

        tags = step[
            "tags"
        ]

        if (
            "BRAKING"
            in tags
        ):
            braking_references.append(
                instruction
            )

        if (
            "GEAR"
            in tags
        ):
            gears.append(
                instruction
            )

        if (
            "TRACK_LIMIT"
            in tags
        ):
            track_limits.append(
                instruction
            )

        if (
            "THROTTLE"
            in tags
        ):
            throttle.append(
                instruction
            )

        if (
            "LINE"
            in tags
        ):
            racing_line.append(
                instruction
            )

    if (
        len(steps) >= 20
        and len(
            braking_events
        ) >= 6
    ):
        confidence = "HIGH"
    elif (
        len(steps) >= 8
        and len(
            braking_events
        ) >= 3
    ):
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    return {
        "confidence": confidence,
        "mapping_mode": (
            "SEQUENTIAL_TRANSCRIPT_ORDER"
        ),
        "official_corner_numbers": False,
        "steps": steps,
        "braking_events": braking_events,
        "braking_references": unique_preserve_order(
            braking_references
        ),
        "gears": unique_preserve_order(
            gears
        ),
        "track_limits": unique_preserve_order(
            track_limits
        ),
        "throttle_references": unique_preserve_order(
            throttle
        ),
        "racing_line": unique_preserve_order(
            racing_line
        ),
    }


# ======================================================================================
# LIVE CAR META
# ======================================================================================

def extract_live_car_meta(
    snapshot: Any,
) -> List[
    Dict[str, Any]
]:
    if not isinstance(
        snapshot,
        dict,
    ):
        return []

    raw = snapshot.get(
        "top5_used_cars"
    )

    if not isinstance(
        raw,
        list,
    ):
        raw = recursive_find_first(
            snapshot,
            [
                "top5_used_cars"
            ],
        )

    if not isinstance(
        raw,
        list,
    ):
        return []

    result: List[
        Dict[str, Any]
    ] = []

    for item in raw:
        if not isinstance(
            item,
            dict,
        ):
            continue

        car = safe_str(
            item.get(
                "car"
            ),
            "",
        )

        if not car:
            continue

        result.append(
            {
                "car": car,
                "car_code": item.get(
                    "car_code"
                ),
                "count": item.get(
                    "count"
                ),
                "percentage": item.get(
                    "percentage"
                ),
                "layout": item.get(
                    "layout"
                ),
            }
        )

    return result[:5]


# ======================================================================================
# PERSONAL PERFORMANCE
# ======================================================================================

def extract_personal_context(
    snapshot: Any,
) -> Dict[str, Any]:
    if not isinstance(
        snapshot,
        dict,
    ):
        return {}

    my_result = snapshot.get(
        "my_result"
    )

    if not isinstance(
        my_result,
        dict,
    ):
        my_result = {}

    world_record = snapshot.get(
        "world_record"
    )

    if not isinstance(
        world_record,
        dict,
    ):
        world_record = {}

    next_targets = snapshot.get(
        "next_targets"
    )

    if not isinstance(
        next_targets,
        list,
    ):
        next_targets = []

    comparison = snapshot.get(
        "car_comparison"
    )

    if not isinstance(
        comparison,
        dict,
    ):
        comparison = {}

    brake_bias = snapshot.get(
        "my_brake_bias"
    )

    if not isinstance(
        brake_bias,
        dict,
    ):
        brake_bias = {}

    same_car = snapshot.get(
        "same_car_stats"
    )

    if not isinstance(
        same_car,
        dict,
    ):
        same_car = {}

    country_stats = snapshot.get(
        "country_stats"
    )

    if not isinstance(
        country_stats,
        dict,
    ):
        country_stats = {}

    dr_stats = snapshot.get(
        "dr_stats"
    )

    if not isinstance(
        dr_stats,
        dict,
    ):
        dr_stats = {}

    return {
        "my_result": my_result,
        "world_record": world_record,
        "next_targets": next_targets[:4],
        "car_comparison": comparison,
        "brake_bias": brake_bias,
        "same_car_stats": same_car,
        "country_stats": country_stats,
        "dr_stats": dr_stats,
    }


# ======================================================================================
# HEALTH / VALIDATION
# ======================================================================================

def validate_inputs(
    snapshot: Any,
    digit_text: str,
    gnc_text: str,
) -> None:
    if snapshot is None:
        raise RuntimeError(
            "latest_snapshot.json not found or invalid."
        )

    if not digit_text:
        raise RuntimeError(
            "Digit Racing transcript not found."
        )

    if not gnc_text:
        raise RuntimeError(
            "GnC Racing transcript not found."
        )


def validate_live_config(
    live: Dict[str, Any],
) -> List[str]:
    warnings: List[str] = []

    if live[
        "track"
    ] == "unknown":
        warnings.append(
            "Track could not be identified."
        )

    if live[
        "class"
    ] == "unknown":
        warnings.append(
            "Race class could not be identified."
        )

    if live[
        "fuel_multiplier"
    ] is None:
        warnings.append(
            "Fuel multiplier unavailable."
        )

    if live[
        "tyre_multiplier"
    ] is None:
        warnings.append(
            "Tyre multiplier unavailable."
        )

    if not live[
        "compounds"
    ]:
        warnings.append(
            "Race compounds unavailable."
        )

    return warnings


def build_health(
    warnings: List[str],
    strategy: Dict[str, Any],
    lap_guide: Dict[str, Any],
    meta: List[
        Dict[str, Any]
    ],
    personal: Dict[str, Any],
) -> Dict[str, Any]:
    issues: List[str] = list(
        warnings
    )

    if strategy[
        "confidence"
    ] == "LOW":
        issues.append(
            "Low confidence in strategy extraction."
        )

    if lap_guide[
        "confidence"
    ] == "LOW":
        issues.append(
            "Low confidence in GnC lap-guide extraction."
        )

    if not meta:
        issues.append(
            "Live Top-1000 car meta unavailable."
        )

    my_result = personal.get(
        "my_result",
        {},
    )

    if not my_result.get(
        "laptime"
    ):
        issues.append(
            "Personal leaderboard result unavailable."
        )

    return {
        "status": (
            "OK"
            if not issues
            else "WARNING"
        ),
        "issues": issues,
        "strategy_confidence": strategy[
            "confidence"
        ],
        "lap_guide_confidence": lap_guide[
            "confidence"
        ],
        "gnc_useful_steps": len(
            lap_guide[
                "steps"
            ]
        ),
        "gnc_braking_events": len(
            lap_guide[
                "braking_events"
            ]
        ),
    }


# ======================================================================================
# PRACTICAL PLAN
# ======================================================================================

def build_practical_plan(
    strategy: Dict[str, Any],
    meta: List[
        Dict[str, Any]
    ],
    personal: Dict[str, Any],
) -> List[str]:
    practical: List[str] = []

    practical.append(
        "Use the live GT7/GTSH race configuration as the regulatory baseline."
    )

    pit = strategy[
        "pit_strategy"
    ]

    if pit[
        "mode"
    ] == "OVERCUT / EXTEND FIRST STINT":
        practical.append(
            "Treat Lap 4-5 only as the initial reference. "
            "If tyre condition and traffic remain favourable, "
            "extend the first stint and exploit the overcut."
        )

    elif pit[
        "mode"
    ] == "LAP 4-5 REFERENCE":
        practical.append(
            "Use approximately Lap 4-5 as the current pit reference, "
            "while adapting to traffic and tyre condition."
        )

    if strategy[
        "tyre_saving_supported"
    ]:
        practical.append(
            "Protect the tyres in the opening stint: minimise sliding, "
            "excess steering angle and unnecessary front-axle load."
        )

    compound_plan = strategy[
        "compound_plan"
    ]

    if compound_plan[
        "established"
    ]:
        practical.append(
            "Use RM -> RS: start on Racing Medium, preserve the tyre, "
            "then switch to Racing Soft for the second stint."
        )

    elif strategy[
        "tyre_change_supported"
    ]:
        practical.append(
            "Complete the required tyre change and use the permitted compounds "
            "consistently with the live race regulations."
        )

    meta_confirms_citroen = bool(
        meta
        and normalize_key(
            meta[0][
                "car"
            ]
        ).startswith(
            "gt by citroen"
        )
    )

    if (
        strategy[
            "citroen_supported"
        ]
        and meta_confirms_citroen
    ):
        practical.append(
            "Use the GT by Citroen Gr.4 as the reference meta car: "
            "Digit's race-tested assessment and live Top-1000 usage agree."
        )

    elif strategy[
        "citroen_supported"
    ]:
        practical.append(
            "Digit supports the GT by Citroen Gr.4; compare it with the "
            "current live leaderboard before selecting the car."
        )

    comparison = personal.get(
        "car_comparison",
        {},
    )

    theoretical = comparison.get(
        "theoretical_car_gap_ms"
    )

    if isinstance(
        theoretical,
        (int, float),
    ):
        practical.append(
            "The best Citroen lap is "
            f"{theoretical:.0f} ms faster than the best lap in your current car "
            "in this snapshot. Treat this as a car benchmark delta, "
            "not a guaranteed personal gain."
        )

    practical.append(
        "For qualifying, use only the GnC Racing guide for braking, "
        "gears, line, throttle references and track limits."
    )

    return practical


# ======================================================================================
# EXECUTIVE SUMMARY
# ======================================================================================

def build_executive_summary(
    live: Dict[str, Any],
    strategy: Dict[str, Any],
    meta: List[
        Dict[str, Any]
    ],
    personal: Dict[str, Any],
) -> Dict[str, Any]:
    my_result = personal.get(
        "my_result",
        {},
    )

    comparison = personal.get(
        "car_comparison",
        {},
    )

    brake_bias = personal.get(
        "brake_bias",
        {},
    )

    return {
        "race": (
            f"{live['track']} | "
            f"{live['class']}"
        ),
        "regulations": (
            f"Fuel {fmt_multiplier(live['fuel_multiplier'])} | "
            f"Tyres {fmt_multiplier(live['tyre_multiplier'])} | "
            f"{fmt_compounds(live['compounds'])}"
        ),
        "recommended_strategy": strategy[
            "pit_strategy"
        ][
            "mode"
        ],
        "compound_sequence": strategy[
            "compound_plan"
        ][
            "sequence"
        ],
        "tyre_saving": strategy[
            "tyre_saving_supported"
        ],
        "meta_car": (
            meta[0][
                "car"
            ]
            if meta
            else None
        ),
        "meta_car_share": (
            meta[0].get(
                "percentage"
            )
            if meta
            else None
        ),
        "my_current_laptime": my_result.get(
            "laptime"
        ),
        "my_current_rank": my_result.get(
            "rank"
        ),
        "my_top_percent": my_result.get(
            "top_percent"
        ),
        "my_current_car": my_result.get(
            "car"
        ),
        "same_car_best": comparison.get(
            "my_car_best_laptime"
        ),
        "meta_car_best": comparison.get(
            "meta_car_best_laptime"
        ),
        "theoretical_car_gap_ms": comparison.get(
            "theoretical_car_gap_ms"
        ),
        "brake_bias": brake_bias,
    }


# ======================================================================================
# COMPACT REPORT
# ======================================================================================

def build_compact_report(
    live: Dict[str, Any],
    strategy: Dict[str, Any],
    lap_guide: Dict[str, Any],
    meta: List[
        Dict[str, Any]
    ],
    personal: Dict[str, Any],
    practical: List[str],
    health: Dict[str, Any],
) -> str:
    lines: List[str] = []

    my_result = personal.get(
        "my_result",
        {},
    )

    comparison = personal.get(
        "car_comparison",
        {},
    )

    brake_bias = personal.get(
        "brake_bias",
        {},
    )

    targets = personal.get(
        "next_targets",
        [],
    )

    lines.append(
        SEPARATOR
    )

    lines.append(
        f"GT7 DAILY RACE C - COMMUNITY INTELLIGENCE V{VERSION}"
    )

    lines.append(
        SEPARATOR
    )

    lines.append(
        f"Race             : {live['track']} | {live['class']}"
    )

    lines.append(
        "Regulations      : "
        f"Fuel {fmt_multiplier(live['fuel_multiplier'])} | "
        f"Tyres {fmt_multiplier(live['tyre_multiplier'])} | "
        f"{fmt_compounds(live['compounds'])}"
    )

    lines.append("")
    lines.append(
        "EXECUTIVE SUMMARY"
    )
    lines.append(
        SUB_SEPARATOR
    )

    lines.append(
        "Strategy         : "
        f"{strategy['pit_strategy']['mode']}"
    )

    lines.append(
        "Tyre sequence    : "
        f"{strategy['compound_plan']['sequence']}"
    )

    lines.append(
        "Tyre saving      : "
        + (
            "YES"
            if strategy[
                "tyre_saving_supported"
            ]
            else "NOT ESTABLISHED"
        )
    )

    if meta:
        percentage = meta[
            0
        ].get(
            "percentage"
        )

        percentage_text = (
            f"{percentage:.1f}%"
            if isinstance(
                percentage,
                (int, float),
            )
            else "unknown"
        )

        lines.append(
            "Meta car         : "
            f"{meta[0]['car']} "
            f"({percentage_text} of Top 1000)"
        )

    if my_result.get(
        "laptime"
    ):
        pace_line = (
            "My current pace  : "
            f"{my_result.get('laptime')} | "
            f"Rank {my_result.get('rank')}"
        )

        top_percent = my_result.get(
            "top_percent"
        )

        if isinstance(
            top_percent,
            (int, float),
        ):
            pace_line += (
                f" | Top {top_percent:.2f}%"
            )

        lines.append(
            pace_line
        )

    if comparison.get(
        "my_car_best_laptime"
    ):
        lines.append(
            "Same-car best    : "
            f"{comparison.get('my_car_best_laptime')}"
        )

    if comparison.get(
        "meta_car_best_laptime"
    ):
        lines.append(
            "Meta-car best    : "
            f"{comparison.get('meta_car_best_laptime')}"
        )

    theoretical = comparison.get(
        "theoretical_car_gap_ms"
    )

    if isinstance(
        theoretical,
        (int, float),
    ):
        lines.append(
            "Car benchmark    : "
            f"{theoretical:.0f} ms between best same-car "
            "and meta-car laps"
        )

    if targets:
        lines.append("")
        lines.append(
            "NEXT TARGETS"
        )
        lines.append(
            SUB_SEPARATOR
        )

        for target in targets:
            gain = target.get(
                "gain_needed_ms"
            )

            lines.append(
                "- "
                f"{target.get('label')} | "
                f"{target.get('laptime')} | "
                f"gain {gain} ms"
            )

    if brake_bias:
        lines.append("")
        lines.append(
            "BRAKE BIAS - CURRENT CAR"
        )
        lines.append(
            SUB_SEPARATOR
        )

        lines.append(
            "Qualifying start : "
            f"{brake_bias.get('qualifying_start', 'unknown')}"
        )

        lines.append(
            "Race start       : "
            f"{brake_bias.get('race_start', 'unknown')}"
        )

        lines.append(
            "Confidence       : "
            f"{brake_bias.get('confidence', 'unknown')}"
        )

    lines.append("")
    lines.append(
        "RACE PLAN"
    )
    lines.append(
        SUB_SEPARATOR
    )

    for index, item in enumerate(
        practical,
        start=1,
    ):
        lines.append(
            f"{index}. {item}"
        )

    lines.append("")
    lines.append(
        "QUALIFYING - GNC BRAKING EVENTS"
    )
    lines.append(
        SUB_SEPARATOR
    )

    lines.append(
        "Order is transcript sequence; official corner numbers are not invented."
    )

    for event in lap_guide[
        "braking_events"
    ]:
        lines.append(
            f"{event['event']:2d}. "
            f"Brake: {event['marker']} | "
            f"Gear: {event['gear']}"
        )

    lines.append("")
    lines.append(
        "TOP-1000 CAR META"
    )
    lines.append(
        SUB_SEPARATOR
    )

    if meta:
        for index, item in enumerate(
            meta,
            start=1,
        ):
            percentage = item.get(
                "percentage"
            )

            percentage_text = (
                f"{percentage:.1f}%"
                if isinstance(
                    percentage,
                    (int, float),
                )
                else "unknown"
            )

            lines.append(
                f"{index}. "
                f"{item['car']} | "
                f"{item.get('count')} drivers | "
                f"{percentage_text}"
            )
    else:
        lines.append(
            "No live car meta available."
        )

    lines.append("")
    lines.append(
        "HEALTH"
    )
    lines.append(
        SUB_SEPARATOR
    )

    lines.append(
        f"Status           : {health['status']}"
    )

    lines.append(
        "Strategy conf.   : "
        f"{health['strategy_confidence']}"
    )

    lines.append(
        "Lap guide conf.  : "
        f"{health['lap_guide_confidence']}"
    )

    lines.append(
        "GnC events       : "
        f"{health['gnc_braking_events']} braking events "
        f"from {health['gnc_useful_steps']} useful steps"
    )

    if health[
        "issues"
    ]:
        lines.append("")

        for issue in health[
            "issues"
        ]:
            lines.append(
                f"WARNING          : {issue}"
            )

    return "\n".join(
        lines
    )


# ======================================================================================
# AUDIT REPORT
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
        return (
            f"[{timestamp}] {text}"
        )

    return text


def build_audit_report(
    live: Dict[str, Any],
    strategy: Dict[str, Any],
    lap_guide: Dict[str, Any],
    meta: List[
        Dict[str, Any]
    ],
    personal: Dict[str, Any],
    warnings: List[str],
) -> str:
    lines: List[str] = []

    lines.append(
        SEPARATOR
    )

    lines.append(
        f"GT7 COMMUNITY INTELLIGENCE AUDIT V{VERSION}"
    )

    lines.append(
        SEPARATOR
    )

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
        f"Fuel             : {fmt_multiplier(live['fuel_multiplier'])}"
    )

    lines.append(
        f"Tyre wear        : {fmt_multiplier(live['tyre_multiplier'])}"
    )

    lines.append(
        f"Compounds        : {fmt_compounds(live['compounds'])}"
    )

    lines.append("")
    lines.append(
        "SOURCE POLICY"
    )
    lines.append(
        SUB_SEPARATOR
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

    lines.append("")
    lines.append(
        "STRATEGY ANALYSIS"
    )
    lines.append(
        SUB_SEPARATOR
    )

    lines.append(
        f"Confidence       : {strategy['confidence']}"
    )

    lines.append(
        f"Final strategy   : {strategy['pit_strategy']['mode']}"
    )

    lines.append(
        f"Compound plan    : {strategy['compound_plan']['sequence']}"
    )

    lines.append(
        f"Compound conf.   : {strategy['compound_plan']['confidence']}"
    )

    lines.append(
        f"Tyre saving      : {strategy['tyre_saving_supported']}"
    )

    lines.append(
        f"Tyre change      : {strategy['tyre_change_supported']}"
    )

    lines.append(
        f"Citroen meta     : {strategy['citroen_supported']}"
    )

    lines.append("")
    lines.append(
        "PIT STRATEGY RECONCILIATION"
    )
    lines.append(
        SUB_SEPARATOR
    )

    pit = strategy[
        "pit_strategy"
    ]

    lines.append(
        f"Mode             : {pit['mode']}"
    )

    lines.append(
        f"Confidence       : {pit['confidence']}"
    )

    if pit.get(
        "initial_reference"
    ):
        lines.append(
            "Initial          : "
            f"{pit['initial_reference']}"
        )

    lines.append(
        "Final            : "
        f"{pit['final_conclusion']}"
    )

    evidence = strategy[
        "evidence"
    ]

    sections = [
        (
            "OVERCUT / STAY OUT",
            evidence[
                "overcut"
            ],
        ),
        (
            "TYRE SAVING",
            evidence[
                "tyre_saving"
            ],
        ),
        (
            "TYRE CHANGE",
            evidence[
                "tyre_change"
            ],
        ),
        (
            "COMPOUNDS",
            evidence[
                "compounds"
            ],
        ),
        (
            "CITROEN / META",
            evidence[
                "citroen"
            ],
        ),
        (
            "INITIAL PIT WINDOW",
            evidence[
                "pit_window"
            ],
        ),
    ]

    for title, items in sections:
        if not items:
            continue

        lines.append("")
        lines.append(
            title
        )
        lines.append(
            SUB_SEPARATOR
        )

        for item in items:
            lines.append(
                "- "
                + evidence_line(
                    item
                )
            )

    lines.append("")
    lines.append(
        "GNC USEFUL TRANSCRIPT STEPS"
    )
    lines.append(
        SUB_SEPARATOR
    )

    for step in lap_guide[
        "steps"
    ]:
        tags = "/".join(
            step[
                "tags"
            ]
        )

        lines.append(
            f"{step['sequence']:2d}. "
            f"[{tags}] "
            f"{step['instruction']}"
        )

    lines.append("")
    lines.append(
        "GNC BRAKING EVENTS"
    )
    lines.append(
        SUB_SEPARATOR
    )

    for event in lap_guide[
        "braking_events"
    ]:
        lines.append(
            f"Event {event['event']}: "
            f"Brake={event['marker']} | "
            f"Gear={event['gear']} | "
            f"Steps={event['source_steps']}"
        )

        for evidence_text in event[
            "evidence"
        ]:
            lines.append(
                f"  - {evidence_text}"
            )

    lines.append("")
    lines.append(
        "LIVE CAR META"
    )
    lines.append(
        SUB_SEPARATOR
    )

    for index, item in enumerate(
        meta,
        start=1,
    ):
        lines.append(
            f"{index}. "
            f"{item.get('car')} | "
            f"{item.get('count')} | "
            f"{item.get('percentage')}%"
        )

    lines.append("")
    lines.append(
        "VALIDATION"
    )
    lines.append(
        SUB_SEPARATOR
    )

    if warnings:
        for warning in warnings:
            lines.append(
                f"- {warning}"
            )
    else:
        lines.append(
            "No live-configuration warnings."
        )

    lines.append("")
    lines.append(
        "ANALYSIS POLICY"
    )
    lines.append(
        SUB_SEPARATOR
    )

    policies = [
        "Digit Racing is the sole community source for race strategy.",
        "GnC Racing is the sole community source for qualifying/lap guidance.",
        "Live GT7/GTSH data overrides conflicting community information.",
        "Later race-tested Digit conclusions override earlier speculative comments.",
        "Live leaderboard usage is authoritative for current car meta.",
        "Top-1000 percentages are used directly and are not renormalized.",
        "Transcript evidence is cleaned for provider/ASR duplication.",
        "Stream chatter and unrelated discussion are excluded from strategy evidence.",
        "Compound order is asserted only when transcript and live configuration support it.",
        "GnC guidance remains in transcript sequence.",
        "Official corner numbers are never invented.",
        "Missing braking points, gears, pit timing or strategy details are never fabricated.",
        "Car benchmark delta is not represented as guaranteed personal lap-time gain.",
    ]

    for index, policy in enumerate(
        policies,
        start=1,
    ):
        lines.append(
            f"{index}. {policy}"
        )

    return "\n".join(
        lines
    )


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

    digit_path, digit_text = load_channel_transcript(
        STRATEGY_CHANNEL
    )

    gnc_path, gnc_text = load_channel_transcript(
        LAP_GUIDE_CHANNEL
    )

    console_print(
        SEPARATOR
    )

    console_print(
        f"GT7 COMMUNITY ANALYZER V{VERSION}"
    )

    console_print(
        SEPARATOR
    )

    console_print(
        "Digit transcript : "
        + (
            "FOUND"
            if digit_text
            else "NOT FOUND"
        )
    )

    console_print(
        "GnC transcript   : "
        + (
            "FOUND"
            if gnc_text
            else "NOT FOUND"
        )
    )

    console_print(
        f"Digit characters : {len(digit_text):,}"
    )

    console_print(
        f"GnC characters   : {len(gnc_text):,}"
    )

    validate_inputs(
        snapshot,
        digit_text,
        gnc_text,
    )

    live = extract_live_config(
        snapshot
    )

    warnings = validate_live_config(
        live
    )

    strategy = extract_digit_strategy(
        digit_text,
        live,
    )

    lap_guide = extract_gnc_lap_guide(
        gnc_text
    )

    meta = extract_live_car_meta(
        snapshot
    )

    personal = extract_personal_context(
        snapshot
    )

    practical = build_practical_plan(
        strategy,
        meta,
        personal,
    )

    executive = build_executive_summary(
        live,
        strategy,
        meta,
        personal,
    )

    health = build_health(
        warnings,
        strategy,
        lap_guide,
        meta,
        personal,
    )

    compact_report = build_compact_report(
        live,
        strategy,
        lap_guide,
        meta,
        personal,
        practical,
        health,
    )

    audit_report = build_audit_report(
        live,
        strategy,
        lap_guide,
        meta,
        personal,
        warnings,
    )

    output = {
        "version": VERSION,

        "live_configuration": live,

        "validation": {
            "warnings": warnings,
        },

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
                str(
                    digit_path
                )
                if digit_path
                else None
            ),
            "gnc_transcript": (
                str(
                    gnc_path
                )
                if gnc_path
                else None
            ),
        },

        "executive_summary": executive,

        "race_strategy": strategy,

        "lap_guide": lap_guide,

        "live_car_meta": meta,

        "personal_context": personal,

        "practical_race_plan": practical,

        "health": health,
    }

    save_json(
        OUTPUT_JSON,
        output,
    )

    OUTPUT_REPORT.write_text(
        compact_report,
        encoding="utf-8",
    )

    OUTPUT_AUDIT.write_text(
        audit_report,
        encoding="utf-8",
    )

    console_print("")
    console_print(
        compact_report
    )

    console_print("")
    console_print(
        SEPARATOR
    )

    console_print(
        f"JSON report      : {OUTPUT_JSON}"
    )

    console_print(
        f"Compact report   : {OUTPUT_REPORT}"
    )

    console_print(
        f"Audit report     : {OUTPUT_AUDIT}"
    )

    console_print(
        SEPARATOR
    )

    console_print(
        "COMMUNITY INTELLIGENCE COMPLETE"
    )

    console_print(
        SEPARATOR
    )


if __name__ == "__main__":
    main()