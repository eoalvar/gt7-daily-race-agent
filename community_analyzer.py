#!/usr/bin/env python3

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


# ======================================================================================
# CONFIGURATION
# ======================================================================================

VERSION = "7.0"

DATA_DIR = Path("data")
LATEST_SNAPSHOT = DATA_DIR / "latest_snapshot.json"

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


def normalize_key(text: str) -> str:
    text = normalize_space(text).lower()
    text = re.sub(r"[^a-z0-9Ã -Ã¿ ]", "", text, flags=re.IGNORECASE)
    return normalize_space(text)


def text_has_any(text: str, phrases: Iterable[str]) -> bool:
    low = (text or "").lower()
    return any(phrase.lower() in low for phrase in phrases)


def unique_preserve_order(items: Iterable[str]) -> List[str]:
    seen = set()
    result: List[str] = []

    for item in items:
        cleaned = normalize_space(item)
        key = normalize_key(cleaned)

        if not key or key in seen:
            continue

        seen.add(key)
        result.append(cleaned)

    return result


def fmt_multiplier(value: Any) -> str:
    return "unknown" if value is None else f"x{value}"


def fmt_compounds(compounds: List[str]) -> str:
    return ", ".join(compounds) if compounds else "unknown"


def fmt_percent(value: Any, digits: int = 2) -> str:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return f"{float(value):.{digits}f}%"
    return "unknown"


def fmt_ms(value: Any) -> str:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return f"{float(value):.0f} ms"
    return "unknown"


# ======================================================================================
# RECURSIVE JSON HELPERS
# ======================================================================================

def recursive_find_first(data: Any, keys: Iterable[str]) -> Any:
    key_set = set(keys)

    if isinstance(data, dict):
        for key, value in data.items():
            if key in key_set:
                return value

        for value in data.values():
            found = recursive_find_first(value, key_set)
            if found is not None:
                return found

    elif isinstance(data, list):
        for value in data:
            found = recursive_find_first(value, key_set)
            if found is not None:
                return found

    return None


def recursive_find_dict_with_keys(
    data: Any,
    required_keys: Iterable[str],
) -> Optional[dict]:
    required = set(required_keys)

    if isinstance(data, dict):
        if required.issubset(set(data.keys())):
            return data

        for value in data.values():
            found = recursive_find_dict_with_keys(value, required)
            if found is not None:
                return found

    elif isinstance(data, list):
        for value in data:
            found = recursive_find_dict_with_keys(value, required)
            if found is not None:
                return found

    return None


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
        result = re.sub(pattern, " ", result, flags=re.IGNORECASE)

    return normalize_space(result)


def collapse_repeated_word_runs(text: str) -> str:
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
            result = pattern.sub(r"\1", result)

    return normalize_space(result)


def remove_adjacent_duplicate_phrases(text: str) -> str:
    words = normalize_space(text).split()

    if not words:
        return ""

    changed = True

    while changed:
        changed = False

        for size in range(min(12, len(words) // 2), 2, -1):
            i = 0

            while i + 2 * size <= len(words):
                left = [normalize_key(word) for word in words[i:i + size]]
                right = [normalize_key(word) for word in words[i + size:i + 2 * size]]

                if left == right:
                    del words[i + size:i + 2 * size]
                    changed = True
                else:
                    i += 1

    return normalize_space(" ".join(words))


def collapse_repeated_sentences(text: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+", normalize_space(text))

    cleaned: List[str] = []
    recent_keys: List[str] = []

    for part in parts:
        part = normalize_space(part)
        key = normalize_key(part)

        if not key:
            continue

        if key in recent_keys[-3:]:
            continue

        cleaned.append(part)
        recent_keys.append(key)

    return normalize_space(" ".join(cleaned))


def remove_filler_fragments(text: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+", normalize_space(text))
    result: List[str] = []

    for part in parts:
        cleaned = normalize_space(part)

        if not cleaned:
            continue

        if any(
            re.match(pattern, cleaned, flags=re.IGNORECASE)
            for pattern in FILLER_ONLY_PATTERNS
        ):
            continue

        result.append(cleaned)

    return normalize_space(" ".join(result))


def clean_transcript_text(text: str) -> str:
    text = remove_noise_tokens(text)
    text = collapse_repeated_word_runs(text)
    text = remove_adjacent_duplicate_phrases(text)
    text = collapse_repeated_sentences(text)
    text = remove_filler_fragments(text)

    return normalize_space(text)


# ======================================================================================
# TIMESTAMP HANDLING
# ======================================================================================

TIMESTAMP_RE = re.compile(r"\[(?P<time>(?:\d+:)?\d{1,2}:\d{2})\]")


def split_timestamped_chunks(text: str) -> List[Dict[str, str]]:
    matches = list(TIMESTAMP_RE.finditer(text))

    if not matches:
        cleaned = clean_transcript_text(text)
        return [{"timestamp": "", "text": cleaned}] if cleaned else []

    chunks: List[Dict[str, str]] = []

    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)

        body = clean_transcript_text(text[start:end])

        if body:
            chunks.append(
                {
                    "timestamp": match.group("time"),
                    "text": body,
                }
            )

    return chunks


def timestamp_seconds(timestamp: str) -> int:
    if not timestamp:
        return 0

    try:
        parts = [int(part) for part in timestamp.split(":")]
    except Exception:
        return 0

    if len(parts) == 2:
        minutes, seconds = parts
        return minutes * 60 + seconds

    if len(parts) == 3:
        hours, minutes, seconds = parts
        return hours * 3600 + minutes * 60 + seconds

    return 0


# ======================================================================================
# LIVE CONFIGURATION
# ======================================================================================

def extract_track_from_description(description: str) -> str:
    description = safe_str(description, "")

    if not description:
        return "unknown"

    known_patterns = [
        (r"Grand Valley\s*-\s*Highway\s*1", "Grand Valley - Highway 1"),
        (r"Grand Valley Highway\s*1", "Grand Valley - Highway 1"),
    ]

    for pattern, name in known_patterns:
        if re.search(pattern, description, re.IGNORECASE):
            return name

    match = re.search(
        r"Daily Race C.*?"
        r"\d{1,2}:\d{2}\s+"
        r"(.+?)\s+"
        r"[A-Z]\.\s+[A-Za-zÃ-Ã¿]",
        description,
        re.IGNORECASE,
    )

    return normalize_space(match.group(1)) if match else "unknown"


def extract_class_from_description(description: str) -> str:
    description = safe_str(description, "")
    match = re.search(r"\bGr\.\s*\d+\b", description, re.IGNORECASE)

    if not match:
        return "unknown"

    return re.sub(r"\s+", "", match.group(0))


def extract_live_config(snapshot: Any) -> Dict[str, Any]:
    race = snapshot.get("race") if isinstance(snapshot, dict) else None

    if not isinstance(race, dict):
        race = recursive_find_dict_with_keys(
            snapshot,
            ["fuel_multiplier", "tyre_multiplier"],
        )

    if not isinstance(race, dict):
        race = {}

    description = safe_str(race.get("description"), "")

    start_date = (
        race.get("start_date")
        or recursive_find_first(snapshot, ["start_date", "week", "race_week"])
    )

    track = (
        race.get("track")
        or race.get("track_name")
        or recursive_find_first(race, ["track", "track_name"])
        or extract_track_from_description(description)
    )

    race_class = (
        race.get("class")
        or race.get("race_class")
        or recursive_find_first(race, ["class", "race_class"])
        or extract_class_from_description(description)
    )

    direction = race.get("direction") or "NORMAL"

    fuel = race.get("fuel_multiplier")
    if fuel is None:
        fuel = recursive_find_first(race, ["fuel_multiplier"])

    tyres = race.get("tyre_multiplier")
    if tyres is None:
        tyres = race.get("tire_multiplier")
    if tyres is None:
        tyres = recursive_find_first(race, ["tyre_multiplier", "tire_multiplier"])

    compounds = (
        race.get("compounds")
        or recursive_find_first(race, ["compounds"])
        or []
    )

    if not isinstance(compounds, list):
        compounds = [compounds]

    compounds = [
        safe_str(item, "").upper()
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
        "description": description,
    }


# ======================================================================================
# TRANSCRIPT LOADING / ALIGNMENT
# ======================================================================================

def find_transcript_file(channel_fragment: str) -> Optional[Path]:
    fragment = channel_fragment.lower().replace(" ", "_")

    if not TRANSCRIPT_DIR.exists():
        return None

    candidates = [
        path
        for path in TRANSCRIPT_DIR.glob("*.json")
        if fragment in path.name.lower()
    ]

    if not candidates:
        return None

    return sorted(
        candidates,
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[0]


def extract_transcript_text(data: Any) -> str:
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

    return possible if isinstance(possible, str) else ""


def extract_transcript_metadata(data: Any) -> Dict[str, str]:
    if not isinstance(data, dict):
        return {
            "week": "unknown",
            "track": "unknown",
            "class": "unknown",
        }

    week = recursive_find_first(
        data,
        ["week", "race_week", "start_date"],
    )

    track = recursive_find_first(
        data,
        ["track", "track_name"],
    )

    race_class = recursive_find_first(
        data,
        ["race_class"],
    )

    return {
        "week": safe_str(week),
        "track": safe_str(track),
        "class": safe_str(race_class),
    }


def load_channel_transcript(
    channel: str,
) -> Tuple[Optional[Path], str, Any, Dict[str, str]]:
    path = find_transcript_file(channel)

    if path is None:
        return None, "", None, {
            "week": "unknown",
            "track": "unknown",
            "class": "unknown",
        }

    data = load_json(path)
    text = extract_transcript_text(data)
    metadata = extract_transcript_metadata(data)

    return path, text, data, metadata


def comparable_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", safe_str(value, "").lower())


def transcript_alignment_warnings(
    live: Dict[str, Any],
    channel: str,
    metadata: Dict[str, str],
) -> List[str]:
    warnings: List[str] = []

    live_track = comparable_text(live.get("track", ""))
    meta_track = comparable_text(metadata.get("track", ""))

    live_class = comparable_text(live.get("class", ""))
    meta_class = comparable_text(metadata.get("class", ""))

    if (
        live_track
        and meta_track
        and live_track != "unknown"
        and meta_track != "unknown"
        and live_track != meta_track
    ):
        warnings.append(
            f"{channel}: transcript track '{metadata.get('track')}' "
            f"does not match live track '{live.get('track')}'."
        )

    if (
        live_class
        and meta_class
        and live_class != "unknown"
        and meta_class != "unknown"
        and live_class != meta_class
    ):
        warnings.append(
            f"{channel}: transcript class '{metadata.get('class')}' "
            f"does not match live class '{live.get('class')}'."
        )

    return warnings


# ======================================================================================
# EVIDENCE HELPERS
# ======================================================================================

def evidence_record(chunk: Dict[str, str]) -> Dict[str, str]:
    return {
        "timestamp": chunk.get("timestamp", ""),
        "text": clean_transcript_text(chunk.get("text", "")),
    }


def evidence_is_near_duplicate(a: str, b: str) -> bool:
    a_key = normalize_key(clean_transcript_text(a))
    b_key = normalize_key(clean_transcript_text(b))

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

    similarity = len(a_words & b_words) / max(1, len(a_words | b_words))

    return similarity >= 0.88


def deduplicate_evidence(
    evidence: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    result: List[Dict[str, str]] = []

    for item in evidence:
        text = clean_transcript_text(item.get("text", ""))

        if not text:
            continue

        if any(
            evidence_is_near_duplicate(text, existing["text"])
            for existing in result
        ):
            continue

        result.append(
            {
                "timestamp": item.get("timestamp", ""),
                "text": text,
            }
        )

    return result


# ======================================================================================
# DIGIT RACING STRATEGY
# ======================================================================================

def is_bad_strategy_context(text: str) -> bool:
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

    return any(phrase in low for phrase in bad_contexts)


def strategy_relevance_score(text: str) -> int:
    low = text.lower()

    weights = {
        "overcut": 10,
        "undercut": 6,
        "should have stayed out": 12,
        "pitted earlier": 9,
        "pit later": 8,
        "lap four": 6,
        "lap five": 6,
        "required tire change": 10,
        "required tyre change": 10,
        "need to change the tires": 10,
        "need to change the tyres": 10,
        "mediums and soft": 7,
        "racing mediums": 5,
        "racing soft": 5,
        "tire saving": 7,
        "tyre saving": 7,
        "saving tires": 7,
        "saving tyres": 7,
        "gentle with my tires": 7,
        "gentle with my tyres": 7,
        "citroen": 3,
        "citroÃ«n": 3,
        "tire wear": 3,
        "tyre wear": 3,
        "fuel": 2,
    }

    score = sum(weight for phrase, weight in weights.items() if phrase in low)

    if is_bad_strategy_context(text):
        score -= 20

    return score


def best_evidence(
    evidence: List[Dict[str, str]],
    limit: int,
    prefer_late: bool = False,
) -> List[Dict[str, str]]:
    items = deduplicate_evidence(evidence)

    if prefer_late:
        items.sort(
            key=lambda item: (
                timestamp_seconds(item["timestamp"]),
                strategy_relevance_score(item["text"]),
            ),
            reverse=True,
        )
    else:
        items.sort(
            key=lambda item: (
                strategy_relevance_score(item["text"]),
                timestamp_seconds(item["timestamp"]),
            ),
            reverse=True,
        )

    return items[:limit]


def detect_compound_plan(
    evidence: Dict[str, List[Dict[str, str]]],
    live_compounds: List[str],
) -> Dict[str, Any]:
    combined = " ".join(
        item["text"]
        for group in evidence.values()
        for item in group
    ).lower()

    permitted = [item.upper() for item in live_compounds]

    has_rm = "RM" in permitted and text_has_any(
        combined,
        [
            "racing medium",
            "racing mediums",
            "mediums",
        ],
    )

    has_rs = "RS" in permitted and text_has_any(
        combined,
        [
            "racing soft",
            "racing softs",
            "soft tires",
            "soft tyres",
            "softs",
            "mediums and soft",
        ],
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

    change_rule = bool(evidence.get("tyre_change"))

    if has_rm and has_rs and starts_medium and change_rule:
        return {
            "established": True,
            "start_compound": "RM",
            "finish_compound": "RS",
            "sequence": "RM â RS",
            "confidence": "HIGH",
            "reason": (
                "Digit explicitly supports starting on Racing Medium, "
                "changing tyres and using RM/RS; the live configuration "
                "confirms both compounds."
            ),
        }

    if has_rm and has_rs and change_rule:
        return {
            "established": False,
            "start_compound": None,
            "finish_compound": None,
            "sequence": "RM / RS â order not fully established",
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
        "reason": "Insufficient evidence to establish a compound sequence.",
    }


def determine_pit_strategy(
    evidence: Dict[str, List[Dict[str, str]]],
) -> Dict[str, Any]:
    early = evidence.get("pit_window", [])
    late = evidence.get("overcut", [])

    if late:
        latest = max(
            late,
            key=lambda item: timestamp_seconds(item["timestamp"]),
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
            "latest_timestamp": latest.get("timestamp"),
            "confidence": "HIGH",
        }

    if early:
        return {
            "mode": "LAP 4-5 REFERENCE",
            "rigid_window": False,
            "initial_reference": "Digit discusses approximately Lap 4-5.",
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
        "final_conclusion": "No reliable pit timing conclusion could be extracted.",
        "latest_timestamp": None,
        "confidence": "LOW",
    }


def extract_digit_strategy(
    raw_text: str,
    live: Dict[str, Any],
) -> Dict[str, Any]:
    chunks = split_timestamped_chunks(raw_text)

    raw_evidence: Dict[str, List[Dict[str, str]]] = {
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
            raw_evidence["overcut"].append(evidence_record(chunk))

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

        if tyre_saving_signal and not is_bad_strategy_context(text):
            raw_evidence["tyre_saving"].append(evidence_record(chunk))

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
            raw_evidence["tyre_change"].append(evidence_record(chunk))

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

        if has_medium and has_soft:
            raw_evidence["compounds"].append(evidence_record(chunk))

        if (
            ("citroen" in low or "citroÃ«n" in low)
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
            raw_evidence["citroen"].append(evidence_record(chunk))

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

        if has_lap_window and has_pit_context:
            raw_evidence["pit_window"].append(evidence_record(chunk))

    evidence = {
        "overcut": best_evidence(
            raw_evidence["overcut"],
            limit=4,
            prefer_late=True,
        ),
        "tyre_saving": best_evidence(
            raw_evidence["tyre_saving"],
            limit=3,
        ),
        "tyre_change": best_evidence(
            raw_evidence["tyre_change"],
            limit=2,
        ),
        "compounds": best_evidence(
            raw_evidence["compounds"],
            limit=2,
        ),
        "citroen": best_evidence(
            raw_evidence["citroen"],
            limit=2,
            prefer_late=True,
        ),
        "pit_window": best_evidence(
            raw_evidence["pit_window"],
            limit=2,
        ),
    }

    pit_strategy = determine_pit_strategy(evidence)
    compound_plan = detect_compound_plan(
        evidence,
        live.get("compounds", []),
    )

    confidence_score = 0
    confidence_score += 3 if evidence["overcut"] else 0
    confidence_score += 2 if evidence["tyre_saving"] else 0
    confidence_score += 2 if evidence["tyre_change"] else 0
    confidence_score += 1 if evidence["compounds"] else 0
    confidence_score += 1 if evidence["citroen"] else 0
    confidence_score += 1 if compound_plan["established"] else 0

    if confidence_score >= 8:
        confidence = "HIGH"
    elif confidence_score >= 4:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    recommendations: List[str] = []

    if evidence["overcut"]:
        recommendations.append(
            "Later race-tested evidence favours the overcut: "
            "staying out longer performed better than stopping early."
        )

    if evidence["tyre_saving"]:
        recommendations.append(
            "Tyre preservation is strategically important: minimise "
            "unnecessary steering input, sliding and front-tyre overload."
        )

    if evidence["tyre_change"]:
        recommendations.append(
            "The tyre-change requirement must be satisfied."
        )

    if compound_plan["established"]:
        recommendations.append(
            "Use RM â RS: start on Racing Medium and switch to Racing Soft."
        )

    if evidence["citroen"]:
        recommendations.append(
            "Digit supports the GT by CitroÃ«n Gr.4 as particularly strong, "
            "including tyre-life performance."
        )

    return {
        "confidence": confidence,
        "preferred_logic": pit_strategy["mode"],
        "pit_strategy": pit_strategy,
        "compound_plan": compound_plan,
        "tyre_saving_supported": bool(evidence["tyre_saving"]),
        "tyre_change_supported": bool(evidence["tyre_change"]),
        "citroen_supported": bool(evidence["citroen"]),
        "recommendations": recommendations,
        "evidence": evidence,
    }


# ======================================================================================
# GNC LAP GUIDE â CONTEXT-AWARE SEQUENTIAL PARSING
# ======================================================================================

BRAKE_VERB_PATTERNS = [
    r"\bbrake\b",
    r"\bbrakes\b",
    r"\bbraking\b",
    r"\bget on the brakes\b",
    r"\bhit the brakes\b",
    r"\bbrake marker\b",
    r"\bwe(?:'re| are)? going to break\b",
    r"\bafter we break\b",
    r"\bimmediately after we break\b",
]

LANDMARK_PATTERNS: List[Tuple[str, str]] = [
    (r"around\s+350\s*m", "around 350 m"),
    (r"\b350\s*m\b", "350 m"),
    (r"\b200\s+board\b", "200 board"),
    (r"\b100\s+board\b", "100 board"),
    (r"\b50\s*m\b", "around 50 m"),
    (r"after we pass under this bridge", "after the bridge"),
    (r"exit the tunnel", "tunnel exit"),
    (r"dark mark in the sand", "dark mark in the sand"),
    (r"tarmac changes shade", "tarmac shade change"),
]


def sentence_split(text: str) -> List[str]:
    text = clean_transcript_text(text)

    return [
        normalize_space(piece)
        for piece in re.split(r"(?<=[.!?])\s+", text)
        if normalize_space(piece)
    ]


def contains_explicit_braking(text: str) -> bool:
    low = text.lower()

    return any(
        re.search(pattern, low, flags=re.IGNORECASE)
        for pattern in BRAKE_VERB_PATTERNS
    )


def extract_landmark(text: str) -> Optional[str]:
    low = text.lower()

    for pattern, label in LANDMARK_PATTERNS:
        if re.search(pattern, low, flags=re.IGNORECASE):
            return label

    return None


def extract_gear(text: str) -> Optional[str]:
    low = text.lower()

    gear_patterns = [
        ("second gear", "2nd"),
        ("third gear", "3rd"),
        ("fourth gear", "4th"),
        ("fifth gear", "5th"),
        ("sixth gear", "6th"),
    ]

    for phrase, gear in gear_patterns:
        if phrase in low:
            return gear

    return None


def classify_gnc_line(text: str) -> List[str]:
    low = text.lower()
    tags: List[str] = []

    if contains_explicit_braking(text):
        tags.append("BRAKING")

    if text_has_any(
        low,
        [
            "second gear",
            "third gear",
            "fourth gear",
            "fifth gear",
            "sixth gear",
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
            "drift over",
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
        ],
    ):
        tags.append("TRACK_LIMIT")

    if extract_landmark(text) and not tags:
        tags.append("REFERENCE")

    return tags


def is_useful_gnc_sentence(sentence: str, tags: List[str]) -> bool:
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

    if any(phrase in low for phrase in bad_fragments):
        return False

    return len(sentence) >= 18


def build_gnc_guide_steps(sentences: List[str]) -> List[Dict[str, Any]]:
    steps: List[Dict[str, Any]] = []
    seen: List[str] = []

    last_landmark: Optional[str] = None

    for sentence in sentences:
        tags = classify_gnc_line(sentence)

        if not is_useful_gnc_sentence(sentence, tags):
            continue

        if any(
            evidence_is_near_duplicate(sentence, previous)
            for previous in seen
        ):
            continue

        seen.append(sentence)

        explicit_braking = "BRAKING" in tags
        current_landmark = extract_landmark(sentence)

        brake_reference: Optional[str] = None

        if explicit_braking:
            brake_reference = current_landmark

            if (
                brake_reference is None
                and text_has_any(
                    sentence,
                    [
                        "reach this",
                        "before we reach this",
                        "as we reach this",
                    ],
                )
            ):
                brake_reference = last_landmark

        if current_landmark:
            last_landmark = current_landmark

        steps.append(
            {
                "sequence": len(steps) + 1,
                "tags": tags,
                "brake_reference": brake_reference,
                "gear": extract_gear(sentence),
                "instruction": sentence,
            }
        )

    return steps


def build_braking_events(
    steps: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []

    for index, step in enumerate(steps):
        if "BRAKING" not in step["tags"]:
            continue

        gear = step.get("gear")

        if not gear and index + 1 < len(steps):
            next_step = steps[index + 1]

            if (
                next_step.get("gear")
                and "THROTTLE" not in next_step.get("tags", [])
            ):
                gear = next_step.get("gear")

        events.append(
            {
                "event": len(events) + 1,
                "brake_reference": step.get("brake_reference"),
                "gear": gear,
                "instruction": step["instruction"],
            }
        )

    return events


def extract_gnc_lap_guide(raw_text: str) -> Dict[str, Any]:
    sentences = sentence_split(raw_text)
    steps = build_gnc_guide_steps(sentences)
    braking_events = build_braking_events(steps)

    track_limits = unique_preserve_order(
        step["instruction"]
        for step in steps
        if "TRACK_LIMIT" in step["tags"]
    )

    throttle = unique_preserve_order(
        step["instruction"]
        for step in steps
        if "THROTTLE" in step["tags"]
    )

    racing_line = unique_preserve_order(
        step["instruction"]
        for step in steps
        if "LINE" in step["tags"]
    )

    if len(steps) >= 20 and len(braking_events) >= 6:
        confidence = "HIGH"
    elif len(steps) >= 8:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    return {
        "confidence": confidence,
        "mapping_mode": "SEQUENTIAL_TRANSCRIPT_ORDER",
        "official_corner_numbers": False,
        "steps": steps,
        "braking_events": braking_events,
        "track_limits": track_limits,
        "throttle_references": throttle,
        "racing_line": racing_line,
    }


# ======================================================================================
# LIVE META / PERSONAL / FORECAST / BRAKE BIAS
# ======================================================================================

def extract_live_car_meta(snapshot: Any) -> List[Dict[str, Any]]:
    if not isinstance(snapshot, dict):
        return []

    raw = snapshot.get("top5_used_cars")

    if not isinstance(raw, list):
        raw = recursive_find_first(snapshot, ["top5_used_cars"])

    if not isinstance(raw, list):
        return []

    result: List[Dict[str, Any]] = []

    for item in raw:
        if not isinstance(item, dict):
            continue

        car = safe_str(item.get("car"), "")

        if not car:
            continue

        result.append(
            {
                "car": car,
                "count": item.get("count"),
                "percentage": item.get("percentage"),
                "layout": item.get("layout"),
                "qualifying_range": item.get("qualifying_range"),
                "race_range": item.get("race_range"),
            }
        )

    return result[:5]


def extract_personal_context(snapshot: Any) -> Dict[str, Any]:
    if not isinstance(snapshot, dict):
        return {}

    def as_dict(name: str) -> Dict[str, Any]:
        value = snapshot.get(name)
        return value if isinstance(value, dict) else {}

    def as_list(name: str) -> List[Any]:
        value = snapshot.get(name)
        return value if isinstance(value, list) else []

    my_result = as_dict("my_result")
    world_record = as_dict("world_record")
    comparison = as_dict("car_comparison")
    brake_bias = as_dict("my_brake_bias")
    forecast = as_dict("forecast_v2")
    same_car = as_dict("same_car_stats")
    country = as_dict("country_stats")
    dr_stats = as_dict("dr_stats")

    return {
        "my_result": {
            "psn_id": my_result.get("psn_id"),
            "rank": my_result.get("rank"),
            "laptime": my_result.get("laptime"),
            "car": my_result.get("car"),
            "top_percent": my_result.get("top_percent"),
            "percentile_ahead": my_result.get("percentile_ahead"),
            "pace_band": my_result.get("pace_band"),
            "gap_to_wr_ms": my_result.get("gap_to_wr_ms"),
            "wr_percentage": my_result.get("wr_percentage"),
        },
        "world_record": {
            "laptime": world_record.get("laptime"),
            "driver": world_record.get("driver"),
            "car": world_record.get("car"),
        },
        "next_targets": as_list("next_targets")[:6],
        "car_comparison": comparison,
        "brake_bias": brake_bias,
        "forecast": forecast,
        "same_car_stats": same_car,
        "country_stats": country,
        "dr_stats": dr_stats,
    }


# ======================================================================================
# PRACTICAL PLAN / EXECUTIVE SUMMARY
# ======================================================================================

def build_practical_plan(
    strategy: Dict[str, Any],
    meta: List[Dict[str, Any]],
    personal: Dict[str, Any],
) -> List[str]:
    practical: List[str] = [
        "Use the live GT7/GTSH race configuration as the regulatory baseline."
    ]

    pit = strategy["pit_strategy"]

    if pit["mode"] == "OVERCUT / EXTEND FIRST STINT":
        practical.append(
            "Treat Lap 4-5 only as the initial reference. If tyre condition and "
            "traffic remain favourable, extend the first stint and exploit the overcut."
        )

    elif pit["mode"] == "LAP 4-5 REFERENCE":
        practical.append(
            "Use approximately Lap 4-5 as the current pit reference, adapting to "
            "traffic and tyre condition."
        )

    if strategy["tyre_saving_supported"]:
        practical.append(
            "Protect the tyres in the opening stint: minimise sliding, excess steering "
            "angle and unnecessary front-axle load."
        )

    compound_plan = strategy["compound_plan"]

    if compound_plan["established"]:
        practical.append(
            "Use RM â RS: start on Racing Medium, preserve the tyre, then switch "
            "to Racing Soft for the second stint."
        )

    elif strategy["tyre_change_supported"]:
        practical.append(
            "Complete the required tyre change and use the permitted compounds "
            "consistently with the live race regulations."
        )

    if strategy["citroen_supported"]:
        meta_confirms = bool(
            meta
            and meta[0]["car"].lower().startswith("gt by citro")
        )

        if meta_confirms:
            practical.append(
                "Use the GT by CitroÃ«n Gr.4 as the reference meta car: Digit's "
                "race-tested assessment and live Top-1000 usage agree."
            )

        else:
            practical.append(
                "Digit supports the GT by CitroÃ«n Gr.4; compare it against the "
                "current live leaderboard before selecting the car."
            )

    comparison = personal.get("car_comparison", {})
    theoretical = comparison.get("theoretical_car_gap_ms")

    if isinstance(theoretical, (int, float)):
        practical.append(
            f"The best CitroÃ«n lap is {float(theoretical):.0f} ms faster than the "
            "best lap in your current car in this snapshot. Treat this as a car "
            "benchmark delta, not a guaranteed personal gain."
        )

    practical.append(
        "For qualifying, use only the GnC Racing guide for braking, gears, line, "
        "throttle references and track limits."
    )

    return practical


def build_executive_summary(
    live: Dict[str, Any],
    strategy: Dict[str, Any],
    meta: List[Dict[str, Any]],
    personal: Dict[str, Any],
) -> Dict[str, Any]:
    my_result = personal.get("my_result", {})

    return {
        "race": (
            f"{live['track']} | {live['class']} | "
            f"Fuel {fmt_multiplier(live['fuel_multiplier'])} | "
            f"Tyres {fmt_multiplier(live['tyre_multiplier'])} | "
            f"{fmt_compounds(live['compounds'])}"
        ),
        "recommended_strategy": strategy["pit_strategy"]["mode"],
        "compound_sequence": strategy["compound_plan"]["sequence"],
        "tyre_saving": strategy["tyre_saving_supported"],
        "recommended_car": meta[0]["car"] if meta else None,
        "recommended_car_top1000_share": (
            meta[0].get("percentage")
            if meta
            else None
        ),
        "my_current_car": my_result.get("car"),
        "my_current_laptime": my_result.get("laptime"),
        "my_current_rank": my_result.get("rank"),
        "my_top_percent": my_result.get("top_percent"),
    }


# ======================================================================================
# VALIDATION / HEALTH
# ======================================================================================

def validate_inputs(
    snapshot: Any,
    digit_text: str,
    gnc_text: str,
) -> None:
    if snapshot is None:
        raise RuntimeError("latest_snapshot.json not found or invalid.")

    if not digit_text:
        raise RuntimeError("Digit Racing transcript not found.")

    if not gnc_text:
        raise RuntimeError("GnC Racing transcript not found.")


def validate_live_config(live: Dict[str, Any]) -> List[str]:
    warnings: List[str] = []

    if live["track"] == "unknown":
        warnings.append("Track could not be identified.")

    if live["class"] == "unknown":
        warnings.append("Race class could not be identified.")

    if live["fuel_multiplier"] is None:
        warnings.append("Fuel multiplier unavailable.")

    if live["tyre_multiplier"] is None:
        warnings.append("Tyre multiplier unavailable.")

    if not live["compounds"]:
        warnings.append("Race compounds unavailable.")

    return warnings


def build_health(
    warnings: List[str],
    digit_text: str,
    gnc_text: str,
    strategy: Dict[str, Any],
    lap_guide: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "status": "OK" if not warnings else "WARNING",
        "warnings": warnings,
        "digit_characters": len(digit_text),
        "gnc_characters": len(gnc_text),
        "strategy_confidence": strategy.get("confidence"),
        "lap_guide_confidence": lap_guide.get("confidence"),
        "gnc_step_count": len(lap_guide.get("steps", [])),
        "gnc_braking_event_count": len(lap_guide.get("braking_events", [])),
    }


# ======================================================================================
# REPORTS
# ======================================================================================

def build_compact_report(
    live: Dict[str, Any],
    strategy: Dict[str, Any],
    lap_guide: Dict[str, Any],
    meta: List[Dict[str, Any]],
    personal: Dict[str, Any],
    practical: List[str],
    executive: Dict[str, Any],
    health: Dict[str, Any],
) -> str:
    lines: List[str] = []

    lines.append(SEPARATOR)
    lines.append(f"GT7 DAILY RACE C â COMMUNITY INTELLIGENCE V{VERSION}")
    lines.append(SEPARATOR)

    lines.append(f"Race             : {live['track']} | {live['class']}")
    lines.append(
        f"Regulations      : Fuel {fmt_multiplier(live['fuel_multiplier'])} | "
        f"Tyres {fmt_multiplier(live['tyre_multiplier'])} | "
        f"{fmt_compounds(live['compounds'])}"
    )

    lines.append("")
    lines.append("EXECUTIVE SUMMARY")
    lines.append(SUB_SEPARATOR)
    lines.append(f"Strategy         : {executive['recommended_strategy']}")
    lines.append(f"Tyre sequence    : {executive['compound_sequence']}")
    lines.append(
        "Tyre saving      : "
        + ("YES" if executive["tyre_saving"] else "NOT ESTABLISHED")
    )

    if executive["recommended_car"]:
        share = executive["recommended_car_top1000_share"]

        lines.append(
            f"Meta car         : {executive['recommended_car']} "
            f"({fmt_percent(share, 1)} of Top 1000)"
        )

    if executive["my_current_laptime"]:
        pace = (
            f"{executive['my_current_laptime']} | "
            f"Rank {executive['my_current_rank']}"
        )

        if isinstance(executive["my_top_percent"], (int, float)):
            pace += f" | Top {executive['my_top_percent']:.2f}%"

        lines.append(f"My current pace  : {pace}")

    comparison = personal.get("car_comparison", {})

    if comparison:
        lines.append(
            f"Same-car best    : {comparison.get('my_car_best_laptime', 'unknown')}"
        )

        lines.append(
            f"Meta-car best    : {comparison.get('meta_car_best_laptime', 'unknown')}"
        )

        theoretical = comparison.get("theoretical_car_gap_ms")

        if isinstance(theoretical, (int, float)):
            lines.append(
                f"Car benchmark    : {float(theoretical):.0f} ms "
                "between best same-car and meta-car laps"
            )

    targets = personal.get("next_targets", [])

    if targets:
        lines.append("")
        lines.append("NEXT TARGETS")
        lines.append(SUB_SEPARATOR)

        for target in targets[:4]:
            lines.append(
                f"- {target.get('label')} | {target.get('laptime')} | "
                f"gain {fmt_ms(target.get('gain_needed_ms'))}"
            )

    brake_bias = personal.get("brake_bias", {})

    if brake_bias:
        lines.append("")
        lines.append("BRAKE BIAS â CURRENT CAR")
        lines.append(SUB_SEPARATOR)
        lines.append(
            f"Qualifying start : {brake_bias.get('qualifying_start', 'unknown')}"
        )
        lines.append(
            f"Race start       : {brake_bias.get('race_start', 'unknown')}"
        )
        lines.append(
            f"Confidence       : {brake_bias.get('confidence', 'unknown')}"
        )

    lines.append("")
    lines.append("RACE PLAN")
    lines.append(SUB_SEPARATOR)

    for index, item in enumerate(practical, start=1):
        lines.append(f"{index}. {item}")

    lines.append("")
    lines.append("QUALIFYING â GNC BRAKING EVENTS")
    lines.append(SUB_SEPARATOR)
    lines.append(
        "Order is transcript sequence; official corner numbers are not invented."
    )

    braking_events = lap_guide.get("braking_events", [])

    if braking_events:
        for event in braking_events:
            marker = event.get("brake_reference") or "marker not explicit"
            gear = event.get("gear") or "gear not explicit"

            lines.append(
                f"{event['event']:2d}. Brake: {marker} | Gear: {gear}"
            )
    else:
        lines.append("No reliable braking events extracted.")

    lines.append("")
    lines.append("TOP-1000 CAR META")
    lines.append(SUB_SEPARATOR)

    for index, item in enumerate(meta[:5], start=1):
        lines.append(
            f"{index}. {item['car']} | {item.get('count')} drivers | "
            f"{fmt_percent(item.get('percentage'), 1)}"
        )

    lines.append("")
    lines.append("HEALTH")
    lines.append(SUB_SEPARATOR)
    lines.append(f"Status           : {health['status']}")
    lines.append(f"Strategy conf.   : {health['strategy_confidence']}")
    lines.append(f"Lap guide conf.  : {health['lap_guide_confidence']}")
    lines.append(
        f"GnC events       : {health['gnc_braking_event_count']} braking events "
        f"from {health['gnc_step_count']} useful steps"
    )

    if health["warnings"]:
        for warning in health["warnings"]:
            lines.append(f"Warning          : {warning}")

    return "\n".join(lines)


def evidence_line(item: Dict[str, str]) -> str:
    timestamp = item.get("timestamp", "")
    text = item.get("text", "")

    return f"[{timestamp}] {text}" if timestamp else text


def build_audit_report(
    live: Dict[str, Any],
    strategy: Dict[str, Any],
    lap_guide: Dict[str, Any],
    meta: List[Dict[str, Any]],
    personal: Dict[str, Any],
    health: Dict[str, Any],
) -> str:
    lines: List[str] = []

    lines.append(SEPARATOR)
    lines.append(f"GT7 COMMUNITY INTELLIGENCE AUDIT V{VERSION}")
    lines.append(SEPARATOR)

    lines.append(f"Race week        : {live['week']}")
    lines.append(f"Track            : {live['track']}")
    lines.append(f"Class            : {live['class']}")
    lines.append(f"Direction        : {live['direction']}")
    lines.append(f"Fuel             : {fmt_multiplier(live['fuel_multiplier'])}")
    lines.append(f"Tyre wear        : {fmt_multiplier(live['tyre_multiplier'])}")
    lines.append(f"Compounds        : {fmt_compounds(live['compounds'])}")

    lines.append("")
    lines.append("SOURCE POLICY")
    lines.append(SUB_SEPARATOR)
    lines.append("Race strategy    : Digit Racing only")
    lines.append("Qualifying guide : GnC Racing only")
    lines.append("Race regulations : live GT7/GTSH snapshot")
    lines.append("Car meta         : live leaderboard")

    lines.append("")
    lines.append("RACE STRATEGY â DIGIT RACING")
    lines.append(SUB_SEPARATOR)
    lines.append(f"Confidence       : {strategy['confidence']}")
    lines.append(f"Preferred logic  : {strategy['preferred_logic']}")
    lines.append(f"Compound plan    : {strategy['compound_plan']['sequence']}")
    lines.append(f"Compound conf.   : {strategy['compound_plan']['confidence']}")

    for index, recommendation in enumerate(
        strategy["recommendations"],
        start=1,
    ):
        lines.append(f"{index}. {recommendation}")

    pit = strategy["pit_strategy"]

    lines.append("")
    lines.append("PIT STRATEGY RECONCILIATION")
    lines.append(SUB_SEPARATOR)
    lines.append(f"Final logic      : {pit['mode']}")
    lines.append(f"Confidence       : {pit['confidence']}")

    if pit.get("initial_reference"):
        lines.append(f"Initial evidence : {pit['initial_reference']}")

    lines.append(f"Final evidence   : {pit['final_conclusion']}")

    lines.append("")
    lines.append("STRATEGY EVIDENCE â CLEANED")
    lines.append(SUB_SEPARATOR)

    evidence_sections = [
        ("Overcut / stay out", strategy["evidence"]["overcut"]),
        ("Tyre saving", strategy["evidence"]["tyre_saving"]),
        ("Tyre change", strategy["evidence"]["tyre_change"]),
        ("Compounds", strategy["evidence"]["compounds"]),
        ("CitroÃ«n / meta", strategy["evidence"]["citroen"]),
        ("Initial pit-window discussion", strategy["evidence"]["pit_window"]),
    ]

    for title, items in evidence_sections:
        if not items:
            continue

        lines.append("")
        lines.append(f"{title}:")

        for item in items:
            lines.append(f"  - {evidence_line(item)}")

    lines.append("")
    lines.append("QUALIFYING / FAST LAP â GNC RACING")
    lines.append(SUB_SEPARATOR)
    lines.append(f"Confidence       : {lap_guide['confidence']}")
    lines.append(
        "Mapping          : sequential transcript order; "
        "official corner numbers are not inferred"
    )

    for step in lap_guide["steps"]:
        tags = "/".join(step["tags"])
        suffix_parts: List[str] = []

        if step.get("brake_reference"):
            suffix_parts.append("Brake: " + step["brake_reference"])

        if step.get("gear"):
            suffix_parts.append("Gear: " + step["gear"])

        suffix = " | " + " | ".join(suffix_parts) if suffix_parts else ""

        lines.append(
            f"{step['sequence']:2d}. [{tags}] {step['instruction']}{suffix}"
        )

    lines.append("")
    lines.append("LIVE CAR META â TOP 1000")
    lines.append(SUB_SEPARATOR)

    for index, item in enumerate(meta[:5], start=1):
        lines.append(
            f"{index:2d}. {item['car']} | {item.get('count')} drivers | "
            f"{fmt_percent(item.get('percentage'), 1)}"
        )

    lines.append("")
    lines.append("PERSONAL CONTEXT")
    lines.append(SUB_SEPARATOR)

    my_result = personal.get("my_result", {})

    for key in [
        "psn_id",
        "car",
        "laptime",
        "rank",
        "top_percent",
        "percentile_ahead",
        "pace_band",
        "gap_to_wr_ms",
        "wr_percentage",
    ]:
        lines.append(f"{key:18s}: {my_result.get(key)}")

    lines.append("")
    lines.append("HEALTH / VALIDATION")
    lines.append(SUB_SEPARATOR)

    for key, value in health.items():
        lines.append(f"{key:24s}: {value}")

    lines.append("")
    lines.append("ANALYSIS POLICY")
    lines.append(SUB_SEPARATOR)

    policies = [
        "Digit Racing is the sole community source for race strategy.",
        "GnC Racing is the sole community source for qualifying/lap guidance.",
        "Live GT7/GTSH data overrides conflicting community statements.",
        "Later race-tested Digit conclusions override earlier speculative comments.",
        "Live leaderboard usage is authoritative for current car meta.",
        "Snapshot Top-1000 percentages are used directly and are never renormalized.",
        "Transcript evidence is cleaned for ASR/provider duplication before analysis.",
        "Irrelevant controller, wheel, stream-chat and unrelated references are excluded.",
        "Compound order is asserted only when transcript evidence and live compounds agree.",
        "GnC instructions remain in transcript sequence; official corner numbers are not invented.",
        "Brake markers are attached only to explicit braking actions; marker-only sentences do not create false braking events.",
        "Missing braking points, gears, pit windows or strategy details are never fabricated.",
    ]

    for index, text in enumerate(policies, start=1):
        lines.append(f"{index}. {text}")

    return "\n".join(lines)


# ======================================================================================
# MAIN
# ======================================================================================

def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    snapshot = load_json(LATEST_SNAPSHOT)

    digit_path, digit_text, _digit_data, digit_meta = load_channel_transcript(
        STRATEGY_CHANNEL
    )

    gnc_path, gnc_text, _gnc_data, gnc_meta = load_channel_transcript(
        LAP_GUIDE_CHANNEL
    )

    print(SEPARATOR)
    print(f"GT7 COMMUNITY ANALYZER V{VERSION}")
    print(SEPARATOR)
    print("Digit transcript : " + ("FOUND" if digit_text else "NOT FOUND"))
    print("GnC transcript   : " + ("FOUND" if gnc_text else "NOT FOUND"))
    print(f"Digit characters : {len(digit_text):,}")
    print(f"GnC characters   : {len(gnc_text):,}")

    validate_inputs(snapshot, digit_text, gnc_text)

    live = extract_live_config(snapshot)

    warnings = validate_live_config(live)

    warnings.extend(
        transcript_alignment_warnings(
            live,
            STRATEGY_CHANNEL,
            digit_meta,
        )
    )

    warnings.extend(
        transcript_alignment_warnings(
            live,
            LAP_GUIDE_CHANNEL,
            gnc_meta,
        )
    )

    strategy = extract_digit_strategy(
        digit_text,
        live,
    )

    lap_guide = extract_gnc_lap_guide(
        gnc_text
    )

    meta = extract_live_car_meta(snapshot)
    personal = extract_personal_context(snapshot)

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
        digit_text,
        gnc_text,
        strategy,
        lap_guide,
    )

    compact_report = build_compact_report(
        live,
        strategy,
        lap_guide,
        meta,
        personal,
        practical,
        executive,
        health,
    )

    audit_report = build_audit_report(
        live,
        strategy,
        lap_guide,
        meta,
        personal,
        health,
    )

    output = {
        "version": VERSION,

        "live_configuration": live,

        "health": health,

        "source_policy": {
            "race_strategy": "Digit Racing only",
            "qualifying_guide": "GnC Racing only",
            "race_regulations": "live GT7/GTSH snapshot",
            "car_meta": "live leaderboard",
        },

        "sources": {
            "digit_transcript": str(digit_path) if digit_path else None,
            "digit_metadata": digit_meta,
            "gnc_transcript": str(gnc_path) if gnc_path else None,
            "gnc_metadata": gnc_meta,
        },

        "executive_summary": executive,

        "race_strategy": strategy,

        "lap_guide": lap_guide,

        "live_car_meta": meta,

        "personal_context": personal,

        "practical_race_plan": practical,
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

    # Keep GitHub Actions readable: print only the compact report.
    print("")
    print(compact_report)

    print("")
    print(SEPARATOR)
    print(f"JSON report      : {OUTPUT_JSON}")
    print(f"Compact report   : {OUTPUT_REPORT}")
    print(f"Audit report     : {OUTPUT_AUDIT}")
    print(SEPARATOR)
    print("COMMUNITY INTELLIGENCE COMPLETE")
    print(SEPARATOR)


if __name__ == "__main__":
    main()