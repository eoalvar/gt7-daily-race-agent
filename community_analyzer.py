#!/usr/bin/env python3

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ======================================================================================
# CONFIGURATION
# ======================================================================================

VERSION = "6.0"

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
        return json.loads(
            path.read_text(encoding="utf-8")
        )
    except Exception:
        return None


def save_json(path: Path, data: Any) -> None:
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


def normalize_space(text: str) -> str:
    return re.sub(
        r"\s+",
        " ",
        text or "",
    ).strip()


def normalize_key(text: str) -> str:
    text = normalize_space(text).lower()

    text = re.sub(
        r"[^a-z0-9à-ÿ ]",
        "",
        text,
        flags=re.IGNORECASE,
    )

    return normalize_space(text)


def unique_preserve_order(
    items: List[str],
) -> List[str]:
    seen = set()
    result = []

    for item in items:
        cleaned = normalize_space(item)
        key = normalize_key(cleaned)

        if not key:
            continue

        if key in seen:
            continue

        seen.add(key)
        result.append(cleaned)

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


def text_has_all(
    text: str,
    phrases: List[str],
) -> bool:
    low = text.lower()

    return all(
        phrase.lower() in low
        for phrase in phrases
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


def remove_noise_tokens(text: str) -> str:
    result = text or ""

    for pattern in NOISE_PATTERNS:
        result = re.sub(
            pattern,
            " ",
            result,
            flags=re.IGNORECASE,
        )

    return normalize_space(result)


def collapse_repeated_word_runs(
    text: str,
) -> str:
    """
    Removes ASR repetition such as:

        Yeah. Yeah. Yeah.
        tires tires tires
        stayed out stayed out stayed out
        lap four, lap four, lap four

    Handles blocks from 1 to 8 words.
    """

    result = normalize_space(text)

    for block_size in range(8, 0, -1):

        pattern = re.compile(
            r"\b("
            + r"\S+(?:\s+\S+){"
            + str(block_size - 1)
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

    return normalize_space(result)


def remove_adjacent_duplicate_phrases(
    text: str,
) -> str:
    """
    More aggressive cleanup for transcript providers which duplicate
    3-12 word phrase fragments without punctuation.
    """

    words = normalize_space(text).split()

    if not words:
        return ""

    changed = True

    while changed:
        changed = False

        for size in range(
            min(12, len(words) // 2),
            2,
            -1,
        ):
            i = 0

            while i + (2 * size) <= len(words):

                left = [
                    normalize_key(word)
                    for word in words[
                        i:i + size
                    ]
                ]

                right = [
                    normalize_key(word)
                    for word in words[
                        i + size:i + 2 * size
                    ]
                ]

                if left == right:
                    del words[
                        i + size:
                        i + 2 * size
                    ]

                    changed = True
                else:
                    i += 1

    return normalize_space(
        " ".join(words)
    )


def collapse_repeated_sentences(
    text: str,
) -> str:
    text = normalize_space(text)

    parts = re.split(
        r"(?<=[.!?])\s+",
        text,
    )

    cleaned: List[str] = []
    recent_keys: List[str] = []

    for part in parts:
        part = normalize_space(part)

        if not part:
            continue

        key = normalize_key(part)

        if not key:
            continue

        # Prevent exact sentence repetition even if separated by
        # one or two neighbouring sentences.
        if key in recent_keys[-3:]:
            continue

        cleaned.append(part)
        recent_keys.append(key)

    return normalize_space(
        " ".join(cleaned)
    )


def remove_filler_fragments(
    text: str,
) -> str:
    parts = re.split(
        r"(?<=[.!?])\s+",
        normalize_space(text),
    )

    result = []

    for part in parts:
        cleaned = normalize_space(part)

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

        result.append(cleaned)

    return normalize_space(
        " ".join(result)
    )


def clean_transcript_text(
    text: str,
) -> str:
    text = remove_noise_tokens(text)

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

    return normalize_space(text)


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
        TIMESTAMP_RE.finditer(text)
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

    chunks: List[Dict[str, str]] = []

    for index, match in enumerate(matches):

        start = match.end()

        if index + 1 < len(matches):
            end = matches[
                index + 1
            ].start()
        else:
            end = len(text)

        timestamp = match.group(
            "time"
        )

        body = text[start:end]

        body = clean_transcript_text(
            body
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
            for part in timestamp.split(":")
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
    required = set(
        required_keys
    )

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

    # Generic fallback:
    #
    # "... Daily Race C 16:48 TRACK Driver - Car ..."
    #
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

    value = match.group(0)

    value = re.sub(
        r"\s+",
        "",
        value,
    )

    return value


def extract_live_config(
    snapshot: Any,
) -> Dict[str, Any]:
    race = None

    if isinstance(snapshot, dict):
        race = snapshot.get("race")

    if not isinstance(race, dict):
        race = recursive_find_dict_with_keys(
            snapshot,
            [
                "fuel_multiplier",
                "tyre_multiplier",
            ],
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
            [
                "start_date",
                "week",
                "race_week",
            ],
        )
    )

    track = (
        race.get("track")
        or race.get("track_name")
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
        race.get("class")
        or race.get("race_class")
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

    if not isinstance(
        compounds,
        list,
    ):
        compounds = [compounds]

    compounds = [
        safe_str(item, "")
        for item in compounds
        if safe_str(item, "")
    ]

    description_low = (
        description.lower()
    )

    pit_required = bool(
        re.search(
            r"\bpit\b",
            description_low,
        )
    )

    return {
        "week": safe_str(start_date),
        "track": safe_str(track),
        "class": safe_str(race_class),
        "direction": safe_str(
            direction,
            "NORMAL",
        ),
        "fuel_multiplier": fuel,
        "tyre_multiplier": tyres,
        "compounds": compounds,
        "description": description,
        "pit_reference_present": pit_required,
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

    for path in TRANSCRIPT_DIR.glob(
        "*.json"
    ):
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

    data = load_json(path)

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


def evidence_score_text(
    text: str,
) -> str:
    return normalize_key(
        clean_transcript_text(text)
    )


def evidence_is_near_duplicate(
    a: str,
    b: str,
) -> bool:
    a_key = evidence_score_text(a)
    b_key = evidence_score_text(b)

    if not a_key or not b_key:
        return False

    if a_key == b_key:
        return True

    if len(a_key) >= 30 and a_key in b_key:
        return True

    if len(b_key) >= 30 and b_key in a_key:
        return True

    a_words = set(a_key.split())
    b_words = set(b_key.split())

    if not a_words or not b_words:
        return False

    overlap = len(
        a_words & b_words
    )

    union = len(
        a_words | b_words
    )

    if union == 0:
        return False

    similarity = overlap / union

    return similarity >= 0.88


def deduplicate_evidence(
    evidence: List[Dict[str, str]],
) -> List[Dict[str, str]]:
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

        duplicate = False

        for existing in result:

            if evidence_is_near_duplicate(
                text,
                existing["text"],
            ):
                duplicate = True
                break

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
        for phrase in bad_contexts
    )


def strategy_relevance_score(
    text: str,
) -> int:
    low = text.lower()

    score = 0

    weights = {
        "overcut": 8,
        "undercut": 5,
        "should have stayed out": 10,
        "pitted earlier": 8,
        "pit later": 7,
        "lap four": 6,
        "lap five": 6,
        "required tire change": 8,
        "required tyre change": 8,
        "need to change the tires": 8,
        "need to change the tyres": 8,
        "mediums and soft": 7,
        "racing mediums": 5,
        "racing soft": 5,
        "tire saving": 6,
        "tyre saving": 6,
        "saving tires": 6,
        "saving tyres": 6,
        "gentle with my tires": 6,
        "gentle with my tyres": 6,
        "citroen": 3,
        "citroën": 3,
        "tire wear": 3,
        "tyre wear": 3,
        "fuel": 2,
    }

    for phrase, weight in (
        weights.items()
    ):
        if phrase in low:
            score += weight

    if is_bad_strategy_context(
        text
    ):
        score -= 15

    return score


def best_evidence(
    evidence: List[Dict[str, str]],
    limit: int,
    prefer_late: bool = False,
) -> List[Dict[str, str]]:
    items = deduplicate_evidence(
        evidence
    )

    if prefer_late:
        items = sorted(
            items,
            key=lambda item: (
                timestamp_seconds(
                    item["timestamp"]
                ),
                strategy_relevance_score(
                    item["text"]
                ),
            ),
            reverse=True,
        )
    else:
        items = sorted(
            items,
            key=lambda item: (
                strategy_relevance_score(
                    item["text"]
                ),
                timestamp_seconds(
                    item["timestamp"]
                ),
            ),
            reverse=True,
        )

    return items[:limit]


def detect_compound_plan(
    evidence: Dict[
        str,
        List[Dict[str, str]],
    ],
    live_compounds: List[str],
) -> Dict[str, Any]:
    combined = " ".join(
        item["text"]
        for group in evidence.values()
        for item in group
    ).lower()

    permitted = [
        item.upper()
        for item in live_compounds
    ]

    has_rm = (
        "RM" in permitted
        or text_has_any(
            combined,
            [
                "racing medium",
                "racing mediums",
                "mediums",
            ],
        )
    )

    has_rs = (
        "RS" in permitted
        or text_has_any(
            combined,
            [
                "racing soft",
                "racing softs",
                "soft tires",
                "soft tyres",
                "softs",
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
            "sequence": "RM → RS",
            "confidence": "HIGH",
            "reason": (
                "Digit explicitly discusses starting on the mediums, "
                "changing tyres, and using medium/soft compounds; "
                "the live configuration confirms RM and RS."
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
            "sequence": "RM / RS — order not fully established",
            "confidence": "MEDIUM",
            "reason": (
                "Both compounds and the tyre-change requirement are supported, "
                "but the transcript does not establish the order strongly enough."
            ),
        }

    return {
        "established": False,
        "start_compound": None,
        "finish_compound": None,
        "sequence": "NOT ESTABLISHED",
        "confidence": "LOW",
        "reason": (
            "The available evidence is insufficient to establish a compound sequence."
        ),
    }


def determine_pit_strategy(
    evidence: Dict[
        str,
        List[Dict[str, str]],
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
            key=lambda item: (
                timestamp_seconds(
                    item["timestamp"]
                )
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
                "Later race-tested evidence favours staying out longer "
                "than the initial Lap 4-5 reference when tyre condition "
                "and traffic allow."
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
                "No later race-tested evidence overrides this reference."
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
        List[Dict[str, str]],
    ] = {
        "overcut": [],
        "tyre_saving": [],
        "tyre_change": [],
        "compounds": [],
        "citroen": [],
        "pit_window": [],
    }

    for chunk in chunks:

        text = chunk["text"]
        low = text.lower()

        # --------------------------------------------------------------
        # Overcut / stay out
        # --------------------------------------------------------------

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
                evidence_record(chunk)
            )

        # --------------------------------------------------------------
        # Tyre saving
        # --------------------------------------------------------------

        tyre_saving_signal = (
            text_has_any(
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
            raw_evidence[
                "tyre_change"
            ].append(
                evidence_record(chunk)
            )

        # --------------------------------------------------------------
        # Compounds
        # --------------------------------------------------------------

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
                "tires are better",
                "tyres are better",
            ],
        ):
            raw_evidence[
                "citroen"
            ].append(
                evidence_record(chunk)
            )

        # --------------------------------------------------------------
        # Pit window
        # --------------------------------------------------------------

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
                evidence_record(chunk)
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

    if evidence["overcut"]:
        confidence_score += 3

    if evidence["tyre_saving"]:
        confidence_score += 2

    if evidence["tyre_change"]:
        confidence_score += 2

    if evidence["compounds"]:
        confidence_score += 1

    if evidence["citroen"]:
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

    if evidence["overcut"]:
        recommendations.append(
            "The later race-tested evidence favours the overcut: "
            "staying out longer performed better than stopping early."
        )

    if evidence["tyre_saving"]:
        recommendations.append(
            "Tyre preservation is strategically important. "
            "Minimise unnecessary steering input, sliding and front-tyre overload."
        )

    if evidence["tyre_change"]:
        recommendations.append(
            "The race requires the tyre-change rule to be satisfied."
        )

    if compound_plan[
        "established"
    ]:
        recommendations.append(
            "Digit's usable race evidence supports RM → RS: "
            "start on Racing Medium and switch to Racing Soft."
        )

    if evidence["citroen"]:
        recommendations.append(
            "Digit identifies the GT by Citroën Gr.4 as particularly strong, "
            "including tyre-life performance."
        )

    return {
        "confidence": confidence,
        "preferred_logic": (
            pit_strategy["mode"]
        ),
        "pit_strategy": pit_strategy,
        "compound_plan": compound_plan,
        "tyre_saving_supported": bool(
            evidence["tyre_saving"]
        ),
        "tyre_change_supported": bool(
            evidence["tyre_change"]
        ),
        "citroen_supported": bool(
            evidence["citroen"]
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

    result = []

    for piece in pieces:
        piece = normalize_space(
            piece
        )

        if not piece:
            continue

        result.append(piece)

    return result


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
        "video",
    ]

    if any(
        phrase in low
        for phrase in bad_fragments
    ):
        return False

    if len(sentence) < 18:
        return False

    return True


def extract_brake_reference(
    text: str,
) -> Optional[str]:
    low = text.lower()

    patterns = [
        (
            r"around\s+350\s*m",
            "around 350 m",
        ),
        (
            r"\b350\s*m\b",
            "350 m",
        ),
        (
            r"\b200\s+board\b",
            "200 board",
        ),
        (
            r"\b100\s+board\b",
            "100 board",
        ),
        (
            r"\b50\s*m\b",
            "around 50 m",
        ),
        (
            r"after we pass under this bridge",
            "after the bridge",
        ),
        (
            r"exit the tunnel",
            "tunnel exit",
        ),
        (
            r"dark mark in the sand",
            "dark mark in the sand",
        ),
    ]

    for pattern, label in patterns:

        if re.search(
            pattern,
            low,
            flags=re.IGNORECASE,
        ):
            return label

    return None


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


def build_gnc_guide_steps(
    sentences: List[str],
) -> List[Dict[str, Any]]:
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

        duplicate = False

        for previous in seen:
            if evidence_is_near_duplicate(
                sentence,
                previous,
            ):
                duplicate = True
                break

        if duplicate:
            continue

        seen.append(sentence)

        steps.append(
            {
                "sequence": (
                    len(steps) + 1
                ),
                "tags": tags,
                "brake_reference": (
                    extract_brake_reference(
                        sentence
                    )
                ),
                "gear": extract_gear(
                    sentence
                ),
                "instruction": sentence,
            }
        )

    return steps


def extract_gnc_lap_guide(
    raw_text: str,
) -> Dict[str, Any]:
    sentences = sentence_split(
        raw_text
    )

    steps = build_gnc_guide_steps(
        sentences
    )

    braking = []
    gears = []
    track_limits = []
    throttle = []
    racing_line = []

    for step in steps:

        instruction = step[
            "instruction"
        ]

        tags = step["tags"]

        if "BRAKING" in tags:
            braking.append(
                instruction
            )

        if "GEAR" in tags:
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

        if "THROTTLE" in tags:
            throttle.append(
                instruction
            )

        if "LINE" in tags:
            racing_line.append(
                instruction
            )

    confidence = (
        "HIGH"
        if len(steps) >= 20
        else (
            "MEDIUM"
            if len(steps) >= 8
            else "LOW"
        )
    )

    return {
        "confidence": confidence,
        "mapping_mode": (
            "SEQUENTIAL_TRANSCRIPT_ORDER"
        ),
        "official_corner_numbers": False,
        "steps": steps,
        "braking_references": (
            unique_preserve_order(
                braking
            )
        ),
        "gears": (
            unique_preserve_order(
                gears
            )
        ),
        "track_limits": (
            unique_preserve_order(
                track_limits
            )
        ),
        "throttle_references": (
            unique_preserve_order(
                throttle
            )
        ),
        "racing_line": (
            unique_preserve_order(
                racing_line
            )
        ),
    }


# ======================================================================================
# LIVE CAR META
# ======================================================================================

def extract_live_car_meta(
    snapshot: Any,
) -> List[Dict[str, Any]]:
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
            ["top5_used_cars"],
        )

    if not isinstance(
        raw,
        list,
    ):
        return []

    result = []

    for item in raw:

        if not isinstance(
            item,
            dict,
        ):
            continue

        car = safe_str(
            item.get("car"),
            "",
        )

        count = item.get(
            "count"
        )

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
                "layout": item.get(
                    "layout"
                ),
            }
        )

    return result[:5]


# ======================================================================================
# PERSONAL / LEADERBOARD CONTEXT
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

    return {
        "my_result": {
            "psn_id": my_result.get(
                "psn_id"
            ),
            "rank": my_result.get(
                "rank"
            ),
            "laptime": my_result.get(
                "laptime"
            ),
            "car": my_result.get(
                "car"
            ),
            "top_percent": my_result.get(
                "top_percent"
            ),
            "percentile_ahead": my_result.get(
                "percentile_ahead"
            ),
            "pace_band": my_result.get(
                "pace_band"
            ),
            "gap_to_wr_ms": my_result.get(
                "gap_to_wr_ms"
            ),
        },
        "world_record": {
            "laptime": world_record.get(
                "laptime"
            ),
            "driver": world_record.get(
                "driver"
            ),
            "car": world_record.get(
                "car"
            ),
        },
        "next_targets": (
            next_targets[:4]
        ),
        "car_comparison": comparison,
    }


# ======================================================================================
# FINAL RACE PLAN
# ======================================================================================

def build_practical_plan(
    strategy: Dict[str, Any],
    meta: List[Dict[str, Any]],
) -> List[str]:
    practical: List[str] = []

    practical.append(
        "Use the official/live race configuration as the regulatory baseline."
    )

    pit = strategy[
        "pit_strategy"
    ]

    if pit[
        "mode"
    ] == "OVERCUT / EXTEND FIRST STINT":

        practical.append(
            "Treat Lap 4-5 only as the initial reference, not a mandatory pit window. "
            "If tyre condition and traffic remain favourable, extend the first stint "
            "and exploit the overcut."
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
            "Prioritise tyre preservation in the opening stint: minimise sliding, "
            "excess steering angle and unnecessary front-axle load."
        )

    compound_plan = strategy[
        "compound_plan"
    ]

    if compound_plan[
        "established"
    ]:
        practical.append(
            "Use RM → RS: start on Racing Medium, preserve the tyre, "
            "then switch to Racing Soft for the second stint."
        )

    elif strategy[
        "tyre_change_supported"
    ]:
        practical.append(
            "Complete the required tyre change and use the permitted compounds "
            "consistently with the live race regulations."
        )

    if strategy[
        "citroen_supported"
    ]:

        meta_confirms = bool(
            meta
            and meta[0][
                "car"
            ].lower().startswith(
                "gt by citro"
            )
        )

        if meta_confirms:
            practical.append(
                "Prefer the GT by Citroën Gr.4 as the reference meta car: "
                "Digit's race-tested assessment and the live Top-1000 usage agree."
            )
        else:
            practical.append(
                "Digit supports the GT by Citroën Gr.4; compare it with the "
                "current live leaderboard before selecting the car."
            )

    practical.append(
        "For qualifying, use only the GnC Racing guide for braking points, "
        "gear selection, racing line, throttle references and track limits."
    )

    return practical


# ======================================================================================
# EXECUTIVE SUMMARY
# ======================================================================================

def build_executive_summary(
    live: Dict[str, Any],
    strategy: Dict[str, Any],
    meta: List[Dict[str, Any]],
    personal: Dict[str, Any],
) -> Dict[str, Any]:
    meta_car = (
        meta[0]["car"]
        if meta
        else None
    )

    meta_share = (
        meta[0].get(
            "percentage"
        )
        if meta
        else None
    )

    my_result = personal.get(
        "my_result",
        {},
    )

    return {
        "race": (
            f"{live['track']} | "
            f"{live['class']} | "
            f"Fuel x{live['fuel_multiplier']} | "
            f"Tyres x{live['tyre_multiplier']} | "
            f"{fmt_compounds(live['compounds'])}"
        ),
        "recommended_strategy": (
            strategy[
                "pit_strategy"
            ][
                "mode"
            ]
        ),
        "compound_sequence": (
            strategy[
                "compound_plan"
            ][
                "sequence"
            ]
        ),
        "tyre_saving": (
            strategy[
                "tyre_saving_supported"
            ]
        ),
        "recommended_car": (
            meta_car
        ),
        "recommended_car_top1000_share": (
            meta_share
        ),
        "my_current_car": (
            my_result.get(
                "car"
            )
        ),
        "my_current_laptime": (
            my_result.get(
                "laptime"
            )
        ),
        "my_current_rank": (
            my_result.get(
                "rank"
            )
        ),
        "my_top_percent": (
            my_result.get(
                "top_percent"
            )
        ),
    }


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
        return (
            f"[{timestamp}] {text}"
        )

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

    return ", ".join(
        compounds
    )


def build_report(
    live: Dict[str, Any],
    strategy: Dict[str, Any],
    lap_guide: Dict[str, Any],
    meta: List[Dict[str, Any]],
    personal: Dict[str, Any],
    practical: List[str],
    executive: Dict[str, Any],
) -> str:
    lines: List[str] = []

    # ==================================================================================
    # Header
    # ==================================================================================

    lines.append(
        SEPARATOR
    )

    lines.append(
        f"GT7 COMMUNITY INTELLIGENCE V{VERSION}"
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

    # ==================================================================================
    # Executive summary
    # ==================================================================================

    lines.append("")
    lines.append(
        "EXECUTIVE RACE SUMMARY"
    )
    lines.append(
        SUB_SEPARATOR
    )

    lines.append(
        f"Strategy         : {executive['recommended_strategy']}"
    )

    lines.append(
        f"Tyre sequence    : {executive['compound_sequence']}"
    )

    lines.append(
        "Tyre saving      : "
        + (
            "YES"
            if executive[
                "tyre_saving"
            ]
            else "NOT ESTABLISHED"
        )
    )

    if executive[
        "recommended_car"
    ]:
        share = executive[
            "recommended_car_top1000_share"
        ]

        share_text = (
            f"{share:.1f}%"
            if isinstance(
                share,
                (int, float),
            )
            else "unknown"
        )

        lines.append(
            "Meta car         : "
            f"{executive['recommended_car']} "
            f"({share_text} of Top 1000)"
        )

    if executive[
        "my_current_laptime"
    ]:
        lines.append(
            "My current pace  : "
            f"{executive['my_current_laptime']} | "
            f"Rank {executive['my_current_rank']} | "
            f"Top {executive['my_top_percent']:.2f}%"
            if isinstance(
                executive[
                    "my_top_percent"
                ],
                (int, float),
            )
            else (
                "My current pace  : "
                f"{executive['my_current_laptime']} | "
                f"Rank {executive['my_current_rank']}"
            )
        )

    # ==================================================================================
    # Source policy
    # ==================================================================================

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

    # ==================================================================================
    # Strategy
    # ==================================================================================

    lines.append("")
    lines.append(
        "RACE STRATEGY — DIGIT RACING"
    )
    lines.append(
        SUB_SEPARATOR
    )

    lines.append(
        f"Confidence       : {strategy['confidence']}"
    )

    lines.append(
        "Preferred logic  : "
        f"{strategy['preferred_logic']}"
    )

    lines.append(
        "Tyre saving      : "
        + (
            "SUPPORTED BY DIGIT"
            if strategy[
                "tyre_saving_supported"
            ]
            else "NOT ESTABLISHED"
        )
    )

    lines.append(
        "Tyre change      : "
        + (
            "SUPPORTED BY DIGIT"
            if strategy[
                "tyre_change_supported"
            ]
            else "NOT ESTABLISHED"
        )
    )

    lines.append(
        "Citroën          : "
        + (
            "SUPPORTED BY DIGIT"
            if strategy[
                "citroen_supported"
            ]
            else "NOT ESTABLISHED"
        )
    )

    compound_plan = strategy[
        "compound_plan"
    ]

    lines.append(
        f"Compound plan    : {compound_plan['sequence']}"
    )

    lines.append(
        f"Compound conf.   : {compound_plan['confidence']}"
    )

    lines.append("")

    for index, recommendation in enumerate(
        strategy[
            "recommendations"
        ],
        start=1,
    ):
        lines.append(
            f"{index}. {recommendation}"
        )

    # ==================================================================================
    # Pit strategy reconciliation
    # ==================================================================================

    pit = strategy[
        "pit_strategy"
    ]

    lines.append("")
    lines.append(
        "PIT STRATEGY RECONCILIATION"
    )
    lines.append(
        SUB_SEPARATOR
    )

    lines.append(
        f"Final logic      : {pit['mode']}"
    )

    lines.append(
        f"Confidence       : {pit['confidence']}"
    )

    if pit[
        "initial_reference"
    ]:
        lines.append(
            "Initial evidence : "
            f"{pit['initial_reference']}"
        )

    lines.append(
        "Final evidence   : "
        f"{pit['final_conclusion']}"
    )

    # ==================================================================================
    # Evidence
    # ==================================================================================

    evidence = strategy[
        "evidence"
    ]

    lines.append("")
    lines.append(
        "STRATEGY EVIDENCE — CLEANED"
    )
    lines.append(
        SUB_SEPARATOR
    )

    evidence_sections = [
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
            "Initial pit-window discussion",
            evidence["pit_window"],
        ),
    ]

    for (
        title,
        items,
    ) in evidence_sections:

        if not items:
            continue

        lines.append("")
        lines.append(
            f"{title}:"
        )

        for item in items:
            lines.append(
                "  - "
                + evidence_line(
                    item
                )
            )

    # ==================================================================================
    # GnC guide
    # ==================================================================================

    lines.append("")
    lines.append(
        "QUALIFYING / FAST LAP — GNC RACING"
    )
    lines.append(
        SUB_SEPARATOR
    )

    lines.append(
        f"Confidence       : {lap_guide['confidence']}"
    )

    lines.append(
        "Mapping          : sequential transcript order; "
        "official corner numbers are not inferred"
    )

    lines.append("")

    for step in lap_guide[
        "steps"
    ]:

        tags = "/".join(
            step["tags"]
        )

        suffix_parts = []

        if step[
            "brake_reference"
        ]:
            suffix_parts.append(
                "Brake: "
                + step[
                    "brake_reference"
                ]
            )

        if step["gear"]:
            suffix_parts.append(
                "Gear: "
                + step["gear"]
            )

        suffix = ""

        if suffix_parts:
            suffix = (
                " | "
                + " | ".join(
                    suffix_parts
                )
            )

        lines.append(
            f"{step['sequence']:2d}. "
            f"[{tags}] "
            f"{step['instruction']}"
            f"{suffix}"
        )

    # ==================================================================================
    # Braking summary
    # ==================================================================================

    lines.append("")
    lines.append(
        "BRAKING REFERENCES — GNC"
    )
    lines.append(
        SUB_SEPARATOR
    )

    for item in lap_guide[
        "braking_references"
    ]:
        lines.append(
            f"- {item}"
        )

    # ==================================================================================
    # Gear summary
    # ==================================================================================

    lines.append("")
    lines.append(
        "GEARS / SHIFTING — GNC"
    )
    lines.append(
        SUB_SEPARATOR
    )

    for item in lap_guide[
        "gears"
    ]:
        lines.append(
            f"- {item}"
        )

    # ==================================================================================
    # Track limits
    # ==================================================================================

    lines.append("")
    lines.append(
        "TRACK LIMITS / KERBS — GNC"
    )
    lines.append(
        SUB_SEPARATOR
    )

    for item in lap_guide[
        "track_limits"
    ]:
        lines.append(
            f"- {item}"
        )

    # ==================================================================================
    # Meta
    # ==================================================================================

    lines.append("")
    lines.append(
        "LIVE CAR META — TOP 1000"
    )
    lines.append(
        SUB_SEPARATOR
    )

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
                percentage_text = (
                    "unknown"
                )

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

    # ==================================================================================
    # Personal context
    # ==================================================================================

    my_result = personal.get(
        "my_result",
        {},
    )

    if my_result.get(
        "laptime"
    ):

        lines.append("")
        lines.append(
            "PERSONAL PERFORMANCE"
        )
        lines.append(
            SUB_SEPARATOR
        )

        lines.append(
            f"Driver           : {my_result.get('psn_id')}"
        )

        lines.append(
            f"Current car      : {my_result.get('car')}"
        )

        lines.append(
            f"Lap time         : {my_result.get('laptime')}"
        )

        lines.append(
            f"Overall rank     : {my_result.get('rank')}"
        )

        if isinstance(
            my_result.get(
                "top_percent"
            ),
            (int, float),
        ):
            lines.append(
                "Top percentage   : "
                f"{my_result['top_percent']:.2f}%"
            )

        if my_result.get(
            "pace_band"
        ):
            lines.append(
                f"Pace band        : {my_result.get('pace_band')}"
            )

        comparison = personal.get(
            "car_comparison",
            {},
        )

        if comparison:

            lines.append(
                "Same-car best    : "
                f"{comparison.get('my_car_best_laptime', 'unknown')}"
            )

            lines.append(
                "Meta-car best    : "
                f"{comparison.get('meta_car_best_laptime', 'unknown')}"
            )

            theoretical = comparison.get(
                "theoretical_car_gap_ms"
            )

            if isinstance(
                theoretical,
                (int, float),
            ):
                lines.append(
                    "Theoretical car  : "
                    f"{theoretical:.0f} ms "
                    "between best same-car and meta-car laps"
                )

        targets = personal.get(
            "next_targets",
            [],
        )

        if targets:

            lines.append("")
            lines.append(
                "Next targets:"
            )

            for target in targets:

                gain = target.get(
                    "gain_needed_ms"
                )

                gain_text = (
                    f"{gain} ms"
                    if gain is not None
                    else "unknown"
                )

                lines.append(
                    "  - "
                    f"{target.get('label')} | "
                    f"{target.get('laptime')} | "
                    f"gain needed {gain_text}"
                )

    # ==================================================================================
    # Practical plan
    # ==================================================================================

    lines.append("")
    lines.append(
        "PRACTICAL RACE PLAN"
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

    # ==================================================================================
    # Policy
    # ==================================================================================

    lines.append("")
    lines.append(
        "ANALYSIS POLICY"
    )
    lines.append(
        SUB_SEPARATOR
    )

    policies = [
        (
            "Digit Racing is the sole community source "
            "for race strategy."
        ),
        (
            "GnC Racing is the sole community source "
            "for qualifying/lap guidance."
        ),
        (
            "Live GT7/GTSH data overrides any conflicting "
            "community statement."
        ),
        (
            "Later race-tested Digit conclusions override "
            "earlier speculative strategy comments."
        ),
        (
            "Live leaderboard usage is authoritative for "
            "current car meta."
        ),
        (
            "Snapshot Top-1000 percentages are used directly "
            "and are never renormalized."
        ),
        (
            "Transcript evidence is aggressively cleaned for "
            "ASR/provider duplication before analysis."
        ),
        (
            "Irrelevant tyre references, controller discussion, "
            "stream chatter and unrelated conversation are excluded."
        ),
        (
            "Compound order is only asserted when both community "
            "evidence and live race configuration support it."
        ),
        (
            "GnC instructions remain in transcript sequence; "
            "official corner numbers are never invented."
        ),
        (
            "Missing braking points, gears, pit windows or strategy "
            "details are never fabricated."
        ),
    ]

    for index, text in enumerate(
        policies,
        start=1,
    ):
        lines.append(
            f"{index}. {text}"
        )

    return "\n".join(
        lines
    )


# ======================================================================================
# VALIDATION
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
    warnings = []

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

    print("")
    print(
        "LIVE CONFIGURATION"
    )
    print(
        SUB_SEPARATOR
    )

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

    if warnings:

        print("")
        print(
            "LIVE DATA WARNINGS"
        )
        print(
            SUB_SEPARATOR
        )

        for warning in warnings:
            print(
                f"- {warning}"
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
    )

    executive = build_executive_summary(
        live,
        strategy,
        meta,
        personal,
    )

    report = build_report(
        live,
        strategy,
        lap_guide,
        meta,
        personal,
        practical,
        executive,
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

        "executive_summary": (
            executive
        ),

        "race_strategy": (
            strategy
        ),

        "lap_guide": (
            lap_guide
        ),

        "live_car_meta": (
            meta
        ),

        "personal_context": (
            personal
        ),

        "practical_race_plan": (
            practical
        ),
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
    print(
        report
    )

    print("")
    print(
        SEPARATOR
    )

    print(
        f"JSON report      : {OUTPUT_JSON}"
    )

    print(
        f"Text report      : {OUTPUT_REPORT}"
    )

    print("")
    print(
        SEPARATOR
    )

    print(
        "COMMUNITY INTELLIGENCE COMPLETE"
    )

    print(
        SEPARATOR
    )


if __name__ == "__main__":
    main()