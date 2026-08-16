import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests


# ==============================================================================
# CONFIGURATION
# ==============================================================================

VERSION = "V6.3"

DATA_DIR = Path("data")
SOURCES_FILE = DATA_DIR / "community_sources.json"
DATABASE_FILE = DATA_DIR / "community_transcripts.json"

TRANSCRIPT_DIR = DATA_DIR / "community_transcripts"
RAW_TRANSCRIPT_DIR = DATA_DIR / "community_transcripts_raw"

LEGACY_DIRS = [
    DATA_DIR / "community_supadata_test" / "transcripts",
    DATA_DIR / "community_youtube_transcript_test",
]

SUPADATA_API_KEY = os.getenv("SUPADATA_API_KEY", "").strip()

SUPADATA_URL = "https://api.supadata.ai/v1/youtube/transcript"
YTTAI_BASE_URL = "https://youtube-transcript.ai/transcript"

HTTP_TIMEOUT = 90

STRATEGY_CHANNEL = "Digit Racing"
LAP_GUIDE_CHANNEL = "GnC Racing"

# We deliberately retain BOTH:
#
# 1) the early race/strategy section, where Digit discusses:
#    - tyre saving
#    - medium / soft tyres
#    - expected pit window
#    - required tyre change
#
# 2) the later race-tested section, where Digit concludes:
#    - overcut > undercut
#    - staying out longer worked better
#    - Citroën tyre behaviour
#
# These blocks are intentionally broad enough to survive small timestamp changes
# in auto-generated YouTube transcripts.

DIGIT_FIXED_WINDOWS = [
    {
        "name": "EARLY_STRATEGY",
        "start": 18 * 60,
        "end": 33 * 60,
        "priority": 90,
    },
    {
        "name": "LATE_OVERCUT_VALIDATION",
        "start": 2 * 60 * 60 + 31 * 60,
        "end": 2 * 60 * 60 + 47 * 60,
        "priority": 100,
    },
]

# Optional tertiary evidence. This is useful for compounds / tyre comments later
# in the stream, but it has lower strategic weight.
DIGIT_SECONDARY_WINDOWS = [
    {
        "name": "LATE_COMPOUND_CONTEXT",
        "start": 3 * 60 * 60 + 53 * 60,
        "end": 4 * 60 * 60 + 5 * 60,
        "priority": 50,
    }
]

STRATEGY_TERMS = [
    "strategy",
    "pit",
    "pit stop",
    "pit window",
    "stop",
    "stint",
    "overcut",
    "undercut",
    "stay out",
    "stayed out",
    "staying out",
    "later",
    "earlier",
    "lap four",
    "lap five",
    "lap 4",
    "lap 5",
    "tire",
    "tires",
    "tyre",
    "tyres",
    "tire wear",
    "tyre wear",
    "tire saving",
    "tyre saving",
    "saving tires",
    "saving tyres",
    "save the tires",
    "save the tyres",
    "gentle",
    "mandatory",
    "required",
    "change the tires",
    "change the tyres",
    "medium",
    "mediums",
    "soft",
    "softs",
    "racing medium",
    "racing soft",
    "fuel",
    "citroen",
    "citroën",
    "genesis",
    "meta",
]

RACE_C_TERMS = [
    "race c",
    "daily race c",
    "grand valley",
    "grand valley highway",
    "group four",
    "group 4",
    "gr.4",
    "gr4",
]

OTHER_RACE_TERMS = [
    "race a",
    "daily race a",
    "race b",
    "daily race b",
    "fuji",
    "route x",
    "special stage route x",
]

CURRENT_RACE_FINGERPRINT_TERMS = {
    "CITROEN": [
        "citroen",
        "citroën",
    ],
    "CITROEN_META": [
        "citroen is going to be the meta",
        "citroën is going to be the meta",
        "citroen cup",
        "citroën cup",
    ],
    "MEDIUM_COMPOUND": [
        "mediums",
        "racing medium",
        "medium tire",
        "medium tyre",
    ],
    "SOFT_COMPOUND": [
        "soft tires",
        "soft tyres",
        "soft tire",
        "soft tyre",
        "racing soft",
        "softs",
    ],
    "RM_RS_PAIR": [
        "mediums and soft",
        "medium and soft",
        "racing mediums and racing soft",
        "racing medium and racing soft",
    ],
    "MANDATORY_TYRE_CHANGE": [
        "required tire change",
        "required tyre change",
        "there is a required tire change",
        "there is a required tyre change",
        "we just need to change the tires",
        "we just need to change the tyres",
        "change the tires",
        "change the tyres",
    ],
    "PIT_WINDOW_4_5": [
        "lap four, lap five",
        "lap four lap five",
        "lap 4, lap 5",
        "lap 4 lap 5",
        "around lap four",
        "around lap five",
    ],
    "LAP_4_5_WINDOW": [
        "lap four",
        "lap five",
        "lap 4",
        "lap 5",
    ],
    "TYRE_SAVING": [
        "tire saving",
        "tyre saving",
        "saving tires",
        "saving tyres",
        "save the tires",
        "save the tyres",
        "gentle with my tires",
        "gentle with my tyres",
        "very very gentle",
        "destroy the tires",
        "destroy the tyres",
    ],
    "PIT_LATER": [
        "pit a little bit later",
        "pit later",
        "stop later",
    ],
    "OVERCUT": [
        "overcut",
    ],
    "UNDERCUT": [
        "undercut",
    ],
    "OVERCUT_UNDERCUT_COMPARISON": [
        "overcut is more",
        "overcut is more powerful",
        "overcut it is",
    ],
    "STAY_OUT": [
        "stay out",
        "stayed out",
        "staying out",
        "should have stayed out",
    ],
    "TYRE_WEAR_X4": [
        "tire wear times four",
        "tyre wear times four",
        "tire wear x4",
        "tyre wear x4",
    ],
    "FUEL_X2": [
        "fuel is times two",
        "fuel times two",
        "fuel x2",
    ],
    "LIVE_MULTIPLIER_PAIR": [
        "tire wear times four",
        "tyre wear times four",
        "fuel is times two",
    ],
}


# ==============================================================================
# BASIC UTILITIES
# ==============================================================================

def print_rule(char: str = "=", width: int = 100) -> None:
    print(char * width)


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default

    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            indent=2,
            ensure_ascii=False,
        )


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value)
    return value.strip("_")


def normalize_text(text: str) -> str:
    text = text or ""
    text = text.replace("&gt;", ">")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def count_words(text: str) -> int:
    return len(re.findall(r"\b\S+\b", text or ""))


def parse_youtube_id(url: str) -> Optional[str]:
    if not url:
        return None

    patterns = [
        r"[?&]v=([A-Za-z0-9_-]{11})",
        r"youtu\.be/([A-Za-z0-9_-]{11})",
        r"youtube\.com/shorts/([A-Za-z0-9_-]{11})",
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    return None


def parse_timestamp(value: str) -> Optional[int]:
    if not value:
        return None

    value = value.strip()

    parts = value.split(":")

    try:
        nums = [int(x) for x in parts]
    except ValueError:
        return None

    if len(nums) == 2:
        minutes, seconds = nums
        return minutes * 60 + seconds

    if len(nums) == 3:
        hours, minutes, seconds = nums
        return hours * 3600 + minutes * 60 + seconds

    return None


def seconds_to_timestamp(seconds: int) -> str:
    seconds = max(0, int(seconds))

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"

    return f"{minutes}:{secs:02d}"


# ==============================================================================
# SOURCE SELECTION
# ==============================================================================

def flatten_source_candidates(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return [
            x for x in data
            if isinstance(x, dict)
        ]

    if not isinstance(data, dict):
        return []

    candidates = []

    for key in [
        "sources",
        "videos",
        "accepted",
        "community_sources",
        "tracked",
        "results",
    ]:
        value = data.get(key)

        if isinstance(value, list):
            candidates.extend(
                x for x in value
                if isinstance(x, dict)
            )

    # Some database versions store entries directly by video ID.
    for key, value in data.items():
        if isinstance(value, dict):
            if any(
                field in value
                for field in [
                    "url",
                    "video_url",
                    "youtube_url",
                    "title",
                    "channel",
                ]
            ):
                candidates.append(value)

    # Deduplicate by URL / ID / title.
    seen = set()
    output = []

    for item in candidates:
        url = (
            item.get("url")
            or item.get("video_url")
            or item.get("youtube_url")
            or ""
        )

        video_id = (
            item.get("video_id")
            or parse_youtube_id(url)
            or ""
        )

        title = item.get("title") or ""
        channel = item.get("channel") or item.get("channel_name") or ""

        key = (
            video_id,
            title.lower().strip(),
            channel.lower().strip(),
        )

        if key in seen:
            continue

        seen.add(key)
        output.append(item)

    return output


def source_channel(item: Dict[str, Any]) -> str:
    return (
        item.get("channel")
        or item.get("channel_name")
        or item.get("author")
        or ""
    )


def source_type(item: Dict[str, Any]) -> str:
    return (
        item.get("type")
        or item.get("video_type")
        or item.get("category")
        or "OTHER"
    ).upper()


def source_score(item: Dict[str, Any]) -> float:
    value = (
        item.get("score")
        or item.get("priority")
        or item.get("ranking_score")
        or 0
    )

    try:
        return float(value)
    except Exception:
        return 0.0


def select_primary_sources(
    source_db: Any,
) -> List[Dict[str, Any]]:
    candidates = flatten_source_candidates(source_db)

    digit_candidates = []
    gnc_candidates = []

    for item in candidates:
        channel = source_channel(item).lower()

        if "digit racing" in channel:
            digit_candidates.append(item)

        if "gnc racing" in channel:
            gnc_candidates.append(item)

    # Strategy priority:
    # RACE / LIVESTREAM / STRATEGY from Digit.
    digit_candidates.sort(
        key=lambda x: (
            1 if source_type(x) in {"STRATEGY", "RACE", "LIVESTREAM"} else 0,
            source_score(x),
        ),
        reverse=True,
    )

    # Lap guide priority:
    # LAP_GUIDE from GnC.
    gnc_candidates.sort(
        key=lambda x: (
            1 if source_type(x) == "LAP_GUIDE" else 0,
            source_score(x),
        ),
        reverse=True,
    )

    selected = []

    if digit_candidates:
        item = dict(digit_candidates[0])
        item["_role"] = "STRATEGY"
        selected.append(item)

    if gnc_candidates:
        item = dict(gnc_candidates[0])
        item["_role"] = "LAP_GUIDE"
        selected.append(item)

    return selected


# ==============================================================================
# TRANSCRIPT PARSING
# ==============================================================================

TIMESTAMP_LINE_RE = re.compile(
    r"^\[(?P<ts>\d{1,2}:\d{2}(?::\d{2})?)\]\s*(?P<text>.*)$"
)


def parse_timestamped_chunks(
    raw_text: str,
) -> List[Dict[str, Any]]:
    chunks = []

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()

        if not line:
            continue

        match = TIMESTAMP_LINE_RE.match(line)

        if not match:
            continue

        timestamp = match.group("ts")
        seconds = parse_timestamp(timestamp)

        if seconds is None:
            continue

        text = normalize_text(match.group("text"))

        if not text:
            continue

        chunks.append(
            {
                "timestamp": timestamp,
                "seconds": seconds,
                "text": text,
            }
        )

    return chunks


def remove_duplicate_repetitions(text: str) -> str:
    """
    youtube-transcript.ai occasionally duplicates phrases 2-3 times.
    This is intentionally conservative: only exact adjacent sentence-like
    repetition is reduced.
    """

    text = normalize_text(text)

    # Collapse repeated consecutive words/short phrases.
    text = re.sub(
        r"\b(\w+(?:\s+\w+){0,5})\s+\1(?:\s+\1)+\b",
        r"\1",
        text,
        flags=re.IGNORECASE,
    )

    return normalize_text(text)


def build_text_from_chunks(
    chunks: List[Dict[str, Any]],
) -> str:
    lines = []

    for chunk in chunks:
        text = remove_duplicate_repetitions(chunk["text"])

        lines.append(
            f"[{chunk['timestamp']}] {text}"
        )

    return "\n".join(lines)


# ==============================================================================
# DIGIT STRATEGY EXTRACTION
# ==============================================================================

def extract_chunks_between(
    chunks: List[Dict[str, Any]],
    start: int,
    end: int,
) -> List[Dict[str, Any]]:
    return [
        chunk
        for chunk in chunks
        if start <= chunk["seconds"] <= end
    ]


def find_terms(
    text: str,
    terms: List[str],
) -> List[str]:
    lower = text.lower()

    found = []

    for term in terms:
        if term.lower() in lower:
            found.append(term)

    return found


def detect_fingerprint(
    text: str,
) -> List[str]:
    lower = text.lower()

    found = []

    for label, patterns in CURRENT_RACE_FINGERPRINT_TERMS.items():
        if any(pattern.lower() in lower for pattern in patterns):
            found.append(label)

    return found


def window_strategy_score(
    text: str,
) -> Tuple[int, Dict[str, Any]]:
    lower = text.lower()

    strategy_hits = find_terms(
        lower,
        STRATEGY_TERMS,
    )

    race_hits = find_terms(
        lower,
        RACE_C_TERMS,
    )

    other_race_hits = find_terms(
        lower,
        OTHER_RACE_TERMS,
    )

    fingerprint = detect_fingerprint(lower)

    score = 0

    score += len(strategy_hits) * 2
    score += len(race_hits) * 7
    score += len(fingerprint) * 8

    # High-value fingerprints.
    high_value = {
        "OVERCUT",
        "UNDERCUT",
        "OVERCUT_UNDERCUT_COMPARISON",
        "STAY_OUT",
        "PIT_WINDOW_4_5",
        "MANDATORY_TYRE_CHANGE",
        "TYRE_SAVING",
        "LIVE_MULTIPLIER_PAIR",
    }

    score += sum(
        6
        for item in fingerprint
        if item in high_value
    )

    if other_race_hits:
        score -= len(other_race_hits) * 8

    if "race a" in lower:
        score -= 15

    if "race b" in lower:
        score -= 15

    return score, {
        "strategy_terms": sorted(set(strategy_hits)),
        "race_terms": sorted(set(race_hits)),
        "other_race_terms": sorted(set(other_race_hits)),
        "fingerprint": sorted(set(fingerprint)),
    }


def classify_identity(
    metadata: Dict[str, Any],
) -> str:
    fingerprint = set(metadata["fingerprint"])
    race_terms = set(metadata["race_terms"])

    very_strong_groups = [
        {
            "PIT_WINDOW_4_5",
            "MEDIUM_COMPOUND",
            "SOFT_COMPOUND",
        },
        {
            "OVERCUT",
            "UNDERCUT",
        },
        {
            "OVERCUT_UNDERCUT_COMPARISON",
            "STAY_OUT",
        },
        {
            "TYRE_WEAR_X4",
            "FUEL_X2",
        },
        {
            "MANDATORY_TYRE_CHANGE",
            "TYRE_SAVING",
        },
    ]

    if race_terms:
        return "EXPLICIT_CURRENT_RACE"

    for group in very_strong_groups:
        if group.issubset(fingerprint):
            return "VERY_STRONG_CURRENT_RACE_FINGERPRINT"

    if len(fingerprint) >= 3:
        return "VERY_STRONG_CURRENT_RACE_FINGERPRINT"

    if len(fingerprint) >= 1:
        return "CURRENT_RACE_FINGERPRINT"

    return ""


def build_rolling_windows(
    chunks: List[Dict[str, Any]],
    width_seconds: int = 300,
    step_seconds: int = 60,
) -> List[Dict[str, Any]]:
    if not chunks:
        return []

    start = chunks[0]["seconds"]
    end = chunks[-1]["seconds"]

    windows = []

    cursor = start

    while cursor <= end:
        window_end = cursor + width_seconds

        selected = extract_chunks_between(
            chunks,
            cursor,
            window_end,
        )

        if selected:
            text = build_text_from_chunks(selected)

            score, metadata = window_strategy_score(text)
            identity = classify_identity(metadata)

            valid = bool(identity)

            windows.append(
                {
                    "start": cursor,
                    "end": window_end,
                    "score": score,
                    "identity": identity,
                    "valid": valid,
                    "metadata": metadata,
                    "chunks": selected,
                    "text": text,
                }
            )

        cursor += step_seconds

    return windows


def merge_overlapping_ranges(
    ranges: List[Tuple[int, int, int, str]],
    merge_gap: int = 120,
) -> List[Dict[str, Any]]:
    """
    Each item:
      (start, end, priority, name)
    """

    if not ranges:
        return []

    ranges = sorted(
        ranges,
        key=lambda x: (x[0], x[1]),
    )

    merged = []

    current = {
        "start": ranges[0][0],
        "end": ranges[0][1],
        "priority": ranges[0][2],
        "names": [ranges[0][3]],
    }

    for start, end, priority, name in ranges[1:]:
        if start <= current["end"] + merge_gap:
            current["end"] = max(
                current["end"],
                end,
            )

            current["priority"] = max(
                current["priority"],
                priority,
            )

            if name not in current["names"]:
                current["names"].append(name)

        else:
            merged.append(current)

            current = {
                "start": start,
                "end": end,
                "priority": priority,
                "names": [name],
            }

    merged.append(current)

    return merged


def extract_digit_strategy(
    raw_text: str,
) -> Dict[str, Any]:
    chunks = parse_timestamped_chunks(raw_text)

    rolling_windows = build_rolling_windows(chunks)

    fixed_ranges: List[Tuple[int, int, int, str]] = []

    # --------------------------------------------------------------------------
    # CRITICAL CHANGE V6.3:
    #
    # Always preserve the two known strategy zones from this Digit stream.
    #
    # We do NOT rely solely on automated rolling-window scoring because the
    # early section may not say "Race C" repeatedly even though it is clearly
    # discussing the live Grand Valley Daily Race C.
    # --------------------------------------------------------------------------

    for fixed in DIGIT_FIXED_WINDOWS:
        fixed_chunks = extract_chunks_between(
            chunks,
            fixed["start"],
            fixed["end"],
        )

        if fixed_chunks:
            fixed_ranges.append(
                (
                    fixed["start"],
                    fixed["end"],
                    fixed["priority"],
                    fixed["name"],
                )
            )

    # Secondary evidence is included only when it contains current-race
    # fingerprint terms.
    for fixed in DIGIT_SECONDARY_WINDOWS:
        fixed_chunks = extract_chunks_between(
            chunks,
            fixed["start"],
            fixed["end"],
        )

        if not fixed_chunks:
            continue

        text = build_text_from_chunks(fixed_chunks)

        _, metadata = window_strategy_score(text)
        identity = classify_identity(metadata)

        if identity:
            fixed_ranges.append(
                (
                    fixed["start"],
                    fixed["end"],
                    fixed["priority"],
                    fixed["name"],
                )
            )

    # Add strong dynamic windows outside the fixed zones.
    dynamic_ranges = []

    for window in rolling_windows:
        if not window["valid"]:
            continue

        if window["score"] < 50:
            continue

        dynamic_ranges.append(
            (
                window["start"],
                window["end"],
                window["score"],
                "ROLLING_WINDOW",
            )
        )

    all_ranges = fixed_ranges + dynamic_ranges

    merged_ranges = merge_overlapping_ranges(
        all_ranges,
        merge_gap=120,
    )

    # Keep the strongest meaningful segments but preserve chronological order.
    #
    # Because fixed early strategy and late validation ranges are assigned high
    # priority, they will always survive.
    merged_ranges.sort(
        key=lambda x: (
            -x["priority"],
            x["start"],
        )
    )

    selected_ranges = merged_ranges[:4]

    selected_ranges.sort(
        key=lambda x: x["start"]
    )

    selected_chunks = []

    seen_chunk_keys = set()

    segments = []

    for segment in selected_ranges:
        segment_chunks = extract_chunks_between(
            chunks,
            segment["start"],
            segment["end"],
        )

        if not segment_chunks:
            continue

        segment_text = build_text_from_chunks(segment_chunks)

        score, metadata = window_strategy_score(segment_text)
        identity = classify_identity(metadata)

        segments.append(
            {
                "start_seconds": segment["start"],
                "end_seconds": segment["end"],
                "start": seconds_to_timestamp(segment["start"]),
                "end": seconds_to_timestamp(segment["end"]),
                "score": score,
                "priority": segment["priority"],
                "identity": identity,
                "names": segment["names"],
                "strategy_terms": metadata["strategy_terms"],
                "race_terms": metadata["race_terms"],
                "other_race_terms": metadata["other_race_terms"],
                "fingerprint": metadata["fingerprint"],
            }
        )

        for chunk in segment_chunks:
            key = (
                chunk["seconds"],
                chunk["text"],
            )

            if key in seen_chunk_keys:
                continue

            seen_chunk_keys.add(key)
            selected_chunks.append(chunk)

    selected_chunks.sort(
        key=lambda x: x["seconds"]
    )

    final_text = build_text_from_chunks(
        selected_chunks
    )

    status = (
        "AVAILABLE"
        if final_text.strip()
        else "NO_VALID_STRATEGY_SEGMENT"
    )

    return {
        "status": status,
        "mode": "STRATEGY_FIXED_PLUS_ROLLING_V6_3",
        "raw_chunks": len(chunks),
        "candidate_windows": len(rolling_windows),
        "valid_windows": sum(
            1 for x in rolling_windows
            if x["valid"]
        ),
        "selected_chunks": len(selected_chunks),
        "segments": segments,
        "text": final_text,
        "words": count_words(final_text),
        "characters": len(final_text),
        "rolling_windows": rolling_windows,
    }


# ==============================================================================
# PROVIDERS / CACHE
# ==============================================================================

def read_raw_cache(
    video_id: str,
    channel: str,
) -> Tuple[Optional[str], Optional[Path]]:
    slug = slugify(channel)

    candidates = [
        RAW_TRANSCRIPT_DIR / f"{video_id}_{slug}.txt",
        RAW_TRANSCRIPT_DIR / f"{video_id}.txt",
    ]

    for path in candidates:
        if not path.exists():
            continue

        try:
            return (
                path.read_text(
                    encoding="utf-8",
                    errors="ignore",
                ),
                path,
            )
        except Exception:
            pass

    return None, None


def find_existing_transcript_json(
    video_id: str,
    channel: str,
) -> Optional[Path]:
    slug = slugify(channel)

    candidates = [
        TRANSCRIPT_DIR / f"{video_id}_{slug}.json",
        TRANSCRIPT_DIR / f"{video_id}.json",
    ]

    for path in candidates:
        if path.exists():
            return path

    return None


def find_legacy_transcript_json(
    video_id: str,
    channel: str,
) -> Optional[Path]:
    slug = slugify(channel)

    names = [
        f"{video_id}_{slug}.json",
        f"{video_id}.json",
    ]

    for folder in LEGACY_DIRS:
        if not folder.exists():
            continue

        for name in names:
            path = folder / name

            if path.exists():
                return path

    return None


def extract_text_from_json_payload(
    payload: Any,
) -> Optional[str]:
    if payload is None:
        return None

    if isinstance(payload, str):
        return payload.strip() or None

    if isinstance(payload, list):
        pieces = []

        for item in payload:
            if isinstance(item, str):
                pieces.append(item)

            elif isinstance(item, dict):
                for key in [
                    "text",
                    "content",
                    "transcript",
                ]:
                    value = item.get(key)

                    if isinstance(value, str):
                        pieces.append(value)
                        break

        text = "\n".join(pieces).strip()

        return text or None

    if isinstance(payload, dict):
        for key in [
            "text",
            "transcript",
            "content",
        ]:
            value = payload.get(key)

            result = extract_text_from_json_payload(value)

            if result:
                return result

        for key in [
            "data",
            "result",
            "segments",
            "items",
        ]:
            value = payload.get(key)

            result = extract_text_from_json_payload(value)

            if result:
                return result

    return None


def request_supadata(
    youtube_url: str,
) -> Dict[str, Any]:
    if not SUPADATA_API_KEY:
        return {
            "status": "SUPADATA_NOT_CONFIGURED",
            "text": None,
            "http_status": None,
        }

    headers = {
        "x-api-key": SUPADATA_API_KEY,
    }

    params = {
        "url": youtube_url,
        "text": "true",
    }

    try:
        response = requests.get(
            SUPADATA_URL,
            headers=headers,
            params=params,
            timeout=HTTP_TIMEOUT,
        )
    except Exception as exc:
        return {
            "status": f"SUPADATA_EXCEPTION:{type(exc).__name__}",
            "text": None,
            "http_status": None,
        }

    status_code = response.status_code

    try:
        payload = response.json()
    except Exception:
        payload = response.text

    if status_code == 429:
        details = json.dumps(
            payload,
            ensure_ascii=False,
        ).lower()

        if "plan usage limit" in details:
            status = "SUPADATA_PLAN_LIMIT"
        else:
            status = "SUPADATA_RATE_LIMIT"

        return {
            "status": status,
            "text": None,
            "http_status": status_code,
            "payload": payload,
        }

    if status_code != 200:
        return {
            "status": f"SUPADATA_HTTP_{status_code}",
            "text": None,
            "http_status": status_code,
            "payload": payload,
        }

    text = extract_text_from_json_payload(payload)

    if not text:
        return {
            "status": "SUPADATA_EMPTY",
            "text": None,
            "http_status": status_code,
            "payload": payload,
        }

    return {
        "status": "SUPADATA_SUCCESS",
        "text": text,
        "http_status": status_code,
        "payload": payload,
    }


def request_yttai(
    video_id: str,
    youtube_url: str,
) -> Dict[str, Any]:
    endpoint = (
        f"{YTTAI_BASE_URL}/"
        f"{video_id}.txt?lang=en"
    )

    try:
        response = requests.get(
            endpoint,
            timeout=HTTP_TIMEOUT,
        )
    except Exception as exc:
        return {
            "status": f"YTTAI_EXCEPTION:{type(exc).__name__}",
            "text": None,
            "http_status": None,
            "endpoint": endpoint,
        }

    if response.status_code != 200:
        return {
            "status": f"YTTAI_HTTP_{response.status_code}",
            "text": None,
            "http_status": response.status_code,
            "endpoint": endpoint,
        }

    text = response.text.strip()

    if not text:
        return {
            "status": "YTTAI_EMPTY",
            "text": None,
            "http_status": 200,
            "endpoint": endpoint,
        }

    return {
        "status": "YTTAI_SUCCESS",
        "text": text,
        "http_status": 200,
        "endpoint": endpoint,
    }


# ==============================================================================
# TRANSCRIPT STORAGE
# ==============================================================================

def save_transcript_entry(
    source: Dict[str, Any],
    role: str,
    video_id: str,
    text: str,
    provider: str,
    extraction: Optional[Dict[str, Any]] = None,
) -> Path:
    channel = source_channel(source)
    slug = slugify(channel)

    output_path = (
        TRANSCRIPT_DIR
        / f"{video_id}_{slug}.json"
    )

    payload = {
        "video_id": video_id,
        "channel": channel,
        "role": role,
        "type": source_type(source),
        "title": source.get("title") or "",
        "url": (
            source.get("url")
            or source.get("video_url")
            or source.get("youtube_url")
            or ""
        ),
        "provider": provider,
        "status": "AVAILABLE",
        "words": count_words(text),
        "characters": len(text),
        "transcript": text,
    }

    if extraction:
        payload["extraction"] = {
            key: value
            for key, value in extraction.items()
            if key != "rolling_windows"
            and key != "text"
        }

    save_json(
        output_path,
        payload,
    )

    return output_path


def write_raw_cache(
    video_id: str,
    channel: str,
    text: str,
) -> Path:
    RAW_TRANSCRIPT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = (
        RAW_TRANSCRIPT_DIR
        / f"{video_id}_{slugify(channel)}.txt"
    )

    path.write_text(
        text,
        encoding="utf-8",
    )

    return path


# ==============================================================================
# DATABASE MANAGEMENT
# ==============================================================================

def load_transcript_database() -> Dict[str, Any]:
    data = load_json(
        DATABASE_FILE,
        default={},
    )

    if not isinstance(data, dict):
        data = {}

    if "videos" not in data:
        data["videos"] = {}

    return data


def update_database(
    database: Dict[str, Any],
    video_id: str,
    entry: Dict[str, Any],
) -> None:
    database.setdefault(
        "videos",
        {},
    )

    database["videos"][video_id] = entry


# ==============================================================================
# SOURCE PROCESSING
# ==============================================================================

def load_existing_entry(
    path: Path,
) -> Optional[Dict[str, Any]]:
    data = load_json(
        path,
        default=None,
    )

    if not isinstance(data, dict):
        return None

    return data


def process_digit_strategy(
    source: Dict[str, Any],
    video_id: str,
    youtube_url: str,
) -> Dict[str, Any]:
    channel = source_channel(source)

    print(f"Title            : {source.get('title', '')}")
    print(f"Video ID         : {video_id}")
    print(f"URL              : {youtube_url}")
    print()

    # --------------------------------------------------------------------------
    # 1. Prefer raw transcript cache.
    #    This is important because strategy extraction logic can evolve without
    #    requiring another external API request.
    # --------------------------------------------------------------------------

    raw_text, raw_path = read_raw_cache(
        video_id,
        channel,
    )

    if raw_text:
        print("Raw cache        : FOUND")
        print(f"Raw file         : {raw_path}")

        source_mode = "RAW_CACHE"
        provider = "youtube-transcript.ai"

    else:
        print("Raw cache        : NOT FOUND")

        source_mode = "DOWNLOADED"
        provider = ""

        # ----------------------------------------------------------------------
        # 2. Supadata
        # ----------------------------------------------------------------------

        if SUPADATA_API_KEY:
            print("Supadata         : REQUESTING")

            supadata_result = request_supadata(
                youtube_url
            )

            print(
                f"Supadata status  : "
                f"{supadata_result['status']}"
            )

            if supadata_result.get("text"):
                raw_text = supadata_result["text"]
                provider = "Supadata"

        # ----------------------------------------------------------------------
        # 3. youtube-transcript.ai fallback
        # ----------------------------------------------------------------------

        if not raw_text:
            print(
                "Provider         : "
                "youtube-transcript.ai"
            )

            yttai_result = request_yttai(
                video_id,
                youtube_url,
            )

            print(
                f"Provider status  : "
                f"{yttai_result['status']}"
            )

            if yttai_result.get("text"):
                raw_text = yttai_result["text"]
                provider = "youtube-transcript.ai"

        if not raw_text:
            return {
                "status": "UNAVAILABLE",
                "provider": provider or None,
                "text": "",
                "words": 0,
                "characters": 0,
            }

        raw_path = write_raw_cache(
            video_id,
            channel,
            raw_text,
        )

        print(f"Raw file         : {raw_path}")

    extraction = extract_digit_strategy(
        raw_text
    )

    rolling_windows = extraction.get(
        "rolling_windows",
        [],
    )

    print()
    print("TOP DIGIT STRATEGY CANDIDATES")
    print_rule("-")

    top_candidates = sorted(
        rolling_windows,
        key=lambda x: x["score"],
        reverse=True,
    )[:20]

    for idx, window in enumerate(
        top_candidates,
        start=1,
    ):
        status = (
            "ACCEPT"
            if window["valid"]
            else "REJECT"
        )

        print(
            f"{idx:2d}. "
            f"{seconds_to_timestamp(window['start'])} "
            f"-> "
            f"{seconds_to_timestamp(window['end'])} "
            f"| score {window['score']} "
            f"| {status}"
        )

        print(
            f"    Identity : "
            f"{window['identity'] or '-'}"
        )

        race_terms = (
            ", ".join(
                window["metadata"]["race_terms"]
            )
            or "-"
        )

        strategy_terms = (
            ", ".join(
                window["metadata"]["strategy_terms"]
            )
            or "-"
        )

        fingerprint = (
            ", ".join(
                window["metadata"]["fingerprint"]
            )
            or "-"
        )

        print(f"    Race     : {race_terms}")
        print(
            f"    Strategy : "
            f"{strategy_terms}"
        )
        print(
            f"    Fingerprt: "
            f"{fingerprint}"
        )

        if not window["valid"]:
            print(
                "    Reject   : "
                "NO_CURRENT_RACE_IDENTITY_OR_FINGERPRINT"
            )

    print()
    print("DIGIT STRATEGY EXTRACTION")
    print_rule("-")

    print(f"Source mode      : {source_mode}")
    print(
        f"Extraction mode  : "
        f"{extraction['mode']}"
    )
    print(
        f"Raw chunks       : "
        f"{extraction['raw_chunks']}"
    )
    print(
        f"Candidate windows: "
        f"{extraction['candidate_windows']}"
    )
    print(
        f"Valid windows    : "
        f"{extraction['valid_windows']}"
    )
    print(
        f"Selected chunks  : "
        f"{extraction['selected_chunks']}"
    )
    print(
        f"Segments         : "
        f"{len(extraction['segments'])}"
    )

    for index, segment in enumerate(
        extraction["segments"],
        start=1,
    ):
        names = ", ".join(
            segment.get("names", [])
        )

        print(
            f"  Segment {index}: "
            f"{segment['start']} "
            f"-> "
            f"{segment['end']} "
            f"| score {segment['score']}"
        )

        if names:
            print(
                f"    Source   : {names}"
            )

        print(
            f"    Identity : "
            f"{segment['identity'] or '-'}"
        )

        strategy_terms = (
            ", ".join(
                segment["strategy_terms"]
            )
            or "-"
        )

        fingerprint = (
            ", ".join(
                segment["fingerprint"]
            )
            or "-"
        )

        print(
            f"    Strategy : "
            f"{strategy_terms}"
        )

        print(
            f"    Fingerprt: "
            f"{fingerprint}"
        )

    if extraction["status"] != "AVAILABLE":
        print()
        print(
            "No valid Digit Racing strategy "
            "segment found."
        )

        print(
            f"Final status     : "
            f"{extraction['status']}"
        )

        return {
            "status": extraction["status"],
            "provider": provider,
            "text": "",
            "words": 0,
            "characters": 0,
            "extraction": extraction,
        }

    text = extraction["text"]

    print()
    print("STRATEGY TRANSCRIPT PREVIEW")
    print_rule("-")

    preview = text[:10000]

    print(preview)

    if len(text) > len(preview):
        print()
        print(
            "[... preview truncated ...]"
        )

    output_path = save_transcript_entry(
        source=source,
        role="STRATEGY",
        video_id=video_id,
        text=text,
        provider=provider,
        extraction=extraction,
    )

    print()
    print("Final status     : AVAILABLE")
    print(f"Provider         : {provider}")
    print(
        f"Words            : "
        f"{count_words(text):,}"
    )
    print(
        f"Characters       : "
        f"{len(text):,}"
    )
    print(
        f"Saved file       : "
        f"{output_path}"
    )

    return {
        "status": "AVAILABLE",
        "provider": provider,
        "text": text,
        "words": count_words(text),
        "characters": len(text),
        "saved_file": str(output_path),
        "extraction": extraction,
    }


def process_lap_guide(
    source: Dict[str, Any],
    video_id: str,
    youtube_url: str,
) -> Dict[str, Any]:
    channel = source_channel(source)

    print(f"Title            : {source.get('title', '')}")
    print(f"Video ID         : {video_id}")
    print(f"URL              : {youtube_url}")
    print()

    # --------------------------------------------------------------------------
    # Existing current database transcript
    # --------------------------------------------------------------------------

    existing_path = find_existing_transcript_json(
        video_id,
        channel,
    )

    if existing_path:
        existing = load_existing_entry(
            existing_path
        )

        if existing:
            text = (
                existing.get("transcript")
                or existing.get("text")
                or ""
            )

            if text.strip():
                print(
                    "Result           : "
                    "REUSED_DATABASE"
                )
                print(
                    "Final status     : "
                    "AVAILABLE"
                )
                print(
                    "Provider         : "
                    "LOCAL_DATABASE"
                )
                print(
                    f"Words            : "
                    f"{count_words(text):,}"
                )
                print(
                    f"Characters       : "
                    f"{len(text):,}"
                )
                print(
                    f"Saved file       : "
                    f"{existing_path}"
                )

                return {
                    "status": "AVAILABLE",
                    "provider": "LOCAL_DATABASE",
                    "text": text,
                    "words": count_words(text),
                    "characters": len(text),
                    "saved_file": str(existing_path),
                }

    # --------------------------------------------------------------------------
    # Legacy transcript cache
    # --------------------------------------------------------------------------

    legacy_path = find_legacy_transcript_json(
        video_id,
        channel,
    )

    if legacy_path:
        legacy = load_existing_entry(
            legacy_path
        )

        if legacy:
            text = (
                legacy.get("transcript")
                or legacy.get("text")
                or ""
            )

            if not text:
                text = extract_text_from_json_payload(
                    legacy
                ) or ""

            if text.strip():
                output_path = save_transcript_entry(
                    source=source,
                    role="LAP_GUIDE",
                    video_id=video_id,
                    text=text,
                    provider="LEGACY_CACHE",
                )

                print(
                    "Result           : "
                    "REUSED_LEGACY_CACHE"
                )
                print(
                    f"Legacy source    : "
                    f"{legacy_path}"
                )
                print(
                    "Final status     : "
                    "AVAILABLE"
                )
                print(
                    "Provider         : "
                    "LEGACY_CACHE"
                )
                print(
                    f"Words            : "
                    f"{count_words(text):,}"
                )
                print(
                    f"Characters       : "
                    f"{len(text):,}"
                )
                print(
                    f"Saved file       : "
                    f"{output_path}"
                )

                return {
                    "status": "AVAILABLE",
                    "provider": "LEGACY_CACHE",
                    "text": text,
                    "words": count_words(text),
                    "characters": len(text),
                    "saved_file": str(output_path),
                }

    # --------------------------------------------------------------------------
    # Download if not cached
    # --------------------------------------------------------------------------

    raw_text, raw_path = read_raw_cache(
        video_id,
        channel,
    )

    provider = None

    if raw_text:
        provider = "RAW_CACHE"

    if not raw_text and SUPADATA_API_KEY:
        supadata_result = request_supadata(
            youtube_url
        )

        if supadata_result.get("text"):
            raw_text = supadata_result["text"]
            provider = "Supadata"

    if not raw_text:
        yttai_result = request_yttai(
            video_id,
            youtube_url,
        )

        if yttai_result.get("text"):
            raw_text = yttai_result["text"]
            provider = "youtube-transcript.ai"

    if not raw_text:
        print(
            "Final status     : "
            "UNAVAILABLE"
        )

        return {
            "status": "UNAVAILABLE",
            "provider": provider,
            "text": "",
            "words": 0,
            "characters": 0,
        }

    if provider != "RAW_CACHE":
        raw_path = write_raw_cache(
            video_id,
            channel,
            raw_text,
        )

    # For the concise GnC guide we keep the complete transcript.
    text = raw_text.strip()

    output_path = save_transcript_entry(
        source=source,
        role="LAP_GUIDE",
        video_id=video_id,
        text=text,
        provider=provider or "UNKNOWN",
    )

    print(
        "Final status     : "
        "AVAILABLE"
    )
    print(
        f"Provider         : "
        f"{provider}"
    )
    print(
        f"Words            : "
        f"{count_words(text):,}"
    )
    print(
        f"Characters       : "
        f"{len(text):,}"
    )
    print(
        f"Saved file       : "
        f"{output_path}"
    )

    return {
        "status": "AVAILABLE",
        "provider": provider,
        "text": text,
        "words": count_words(text),
        "characters": len(text),
        "saved_file": str(output_path),
    }


# ==============================================================================
# RACE METADATA
# ==============================================================================

def extract_race_metadata(
    source_db: Any,
) -> Dict[str, Any]:
    defaults = {
        "week": "unknown",
        "track": "unknown",
        "race_class": "unknown",
    }

    if not isinstance(source_db, dict):
        return defaults

    race = (
        source_db.get("race")
        or source_db.get("race_info")
        or {}
    )

    if isinstance(race, dict):
        defaults["week"] = (
            race.get("start_date")
            or race.get("week")
            or defaults["week"]
        )

        defaults["track"] = (
            race.get("track")
            or race.get("circuit")
            or defaults["track"]
        )

        defaults["race_class"] = (
            race.get("class")
            or race.get("race_class")
            or defaults["race_class"]
        )

    for key in [
        "week",
        "race_week",
        "start_date",
    ]:
        if source_db.get(key):
            defaults["week"] = source_db[key]
            break

    for key in [
        "track",
        "circuit",
    ]:
        if source_db.get(key):
            defaults["track"] = source_db[key]
            break

    for key in [
        "class",
        "race_class",
    ]:
        if source_db.get(key):
            defaults["race_class"] = source_db[key]
            break

    return defaults


# ==============================================================================
# MAIN
# ==============================================================================

def main() -> int:
    TRANSCRIPT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    RAW_TRANSCRIPT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    source_db = load_json(
        SOURCES_FILE,
        default={},
    )

    if source_db is None:
        print(
            f"ERROR: source database not found: "
            f"{SOURCES_FILE}"
        )
        return 1

    selected_sources = select_primary_sources(
        source_db
    )

    race_meta = extract_race_metadata(
        source_db
    )

    print_rule("=")
    print(
        f"GT7 COMMUNITY TRANSCRIPT COLLECTOR "
        f"{VERSION}"
    )
    print_rule("=")

    print(
        f"Week             : "
        f"{race_meta['week']}"
    )
    print(
        f"Track            : "
        f"{race_meta['track']}"
    )
    print(
        f"Race class       : "
        f"{race_meta['race_class']}"
    )
    print(
        f"Selected sources : "
        f"{len(selected_sources)}"
    )
    print(
        f"Strategy source  : "
        f"{STRATEGY_CHANNEL}"
    )
    print(
        f"Lap guide source : "
        f"{LAP_GUIDE_CHANNEL}"
    )
    print()

    print("PRIMARY SOURCES")
    print_rule("-")

    for idx, source in enumerate(
        selected_sources,
        start=1,
    ):
        channel = source_channel(source)
        role = source.get("_role") or ""
        stype = source_type(source)

        url = (
            source.get("url")
            or source.get("video_url")
            or source.get("youtube_url")
            or ""
        )

        print(
            f"{idx}. "
            f"{channel} "
            f"| {role} "
            f"| [{stype}]"
        )
        print(
            f"   {source.get('title', '')}"
        )
        print(f"   {url}")

    database = load_transcript_database()

    results = {}

    for idx, source in enumerate(
        selected_sources,
        start=1,
    ):
        role = source.get("_role") or ""
        channel = source_channel(source)

        url = (
            source.get("url")
            or source.get("video_url")
            or source.get("youtube_url")
            or ""
        )

        video_id = (
            source.get("video_id")
            or parse_youtube_id(url)
        )

        print()
        print_rule("=")
        print(
            f"[{idx}/{len(selected_sources)}] "
            f"{channel} - {role}"
        )
        print_rule("=")

        if not video_id:
            print(
                "ERROR: unable to determine "
                "YouTube video ID."
            )

            results[role] = {
                "status": "INVALID_VIDEO_ID",
                "channel": channel,
            }

            continue

        if role == "STRATEGY":
            result = process_digit_strategy(
                source,
                video_id,
                url,
            )

        elif role == "LAP_GUIDE":
            result = process_lap_guide(
                source,
                video_id,
                url,
            )

        else:
            result = {
                "status": "IGNORED_ROLE",
                "text": "",
                "words": 0,
                "characters": 0,
            }

        result["channel"] = channel
        result["title"] = source.get(
            "title",
            "",
        )
        result["url"] = url
        result["video_id"] = video_id

        results[role] = result

        update_database(
            database,
            video_id,
            {
                "video_id": video_id,
                "channel": channel,
                "role": role,
                "title": source.get(
                    "title",
                    "",
                ),
                "url": url,
                "status": result.get(
                    "status"
                ),
                "provider": result.get(
                    "provider"
                ),
                "words": result.get(
                    "words",
                    0,
                ),
                "characters": result.get(
                    "characters",
                    0,
                ),
                "saved_file": result.get(
                    "saved_file"
                ),
            },
        )

    database["version"] = VERSION
    database["primary_sources"] = {
        role: {
            key: value
            for key, value in result.items()
            if key != "text"
            and key != "extraction"
        }
        for role, result in results.items()
    }

    save_json(
        DATABASE_FILE,
        database,
    )

    print()
    print_rule("=")
    print("FINAL SUMMARY")
    print_rule("=")

    print(
        f"Primary sources    : "
        f"{len(selected_sources)}"
    )

    print()
    print("PRIMARY TRANSCRIPT STATUS")
    print_rule("-")

    strategy = results.get(
        "STRATEGY",
        {},
    )

    lap_guide = results.get(
        "LAP_GUIDE",
        {},
    )

    print(
        f"STRATEGY  : "
        f"{strategy.get('status', 'NOT SELECTED')}"
    )

    if strategy:
        print(
            f"  Channel : "
            f"{strategy.get('channel', '-')}"
        )
        print(
            f"  Video   : "
            f"{strategy.get('title', '-')}"
        )

        if strategy.get("status") == "AVAILABLE":
            print(
                f"  Words   : "
                f"{strategy.get('words', 0):,}"
            )

            extraction = strategy.get(
                "extraction",
                {},
            )

            if extraction:
                print(
                    f"  Extract : "
                    f"{extraction.get('mode', '-')}"
                )

                print(
                    f"  Segments: "
                    f"{len(extraction.get('segments', []))}"
                )

                for segment in extraction.get(
                    "segments",
                    [],
                ):
                    names = ", ".join(
                        segment.get(
                            "names",
                            [],
                        )
                    )

                    print(
                        f"    {segment.get('start')} "
                        f"-> "
                        f"{segment.get('end')}"
                        + (
                            f" | {names}"
                            if names
                            else ""
                        )
                    )

    print(
        f"LAP_GUIDE : "
        f"{lap_guide.get('status', 'NOT SELECTED')}"
    )

    if lap_guide:
        print(
            f"  Channel : "
            f"{lap_guide.get('channel', '-')}"
        )
        print(
            f"  Video   : "
            f"{lap_guide.get('title', '-')}"
        )

        if lap_guide.get(
            "status"
        ) == "AVAILABLE":
            print(
                f"  Words   : "
                f"{lap_guide.get('words', 0):,}"
            )
            print(
                f"  Provider: "
                f"{lap_guide.get('provider', '-')}"
            )

    strategy_ready = (
        strategy.get("status")
        == "AVAILABLE"
    )

    lap_ready = (
        lap_guide.get("status")
        == "AVAILABLE"
    )

    print()
    print(
        "COMMUNITY INTELLIGENCE READINESS"
    )
    print_rule("-")

    print(
        f"Digit strategy    : "
        f"{'READY' if strategy_ready else 'PENDING'}"
    )

    print(
        f"GnC lap guide     : "
        f"{'READY' if lap_ready else 'PENDING'}"
    )

    print(
        f"Full report ready : "
        f"{'YES' if strategy_ready and lap_ready else 'No'}"
    )

    print()
    print(
        f"Database file      : "
        f"{DATABASE_FILE}"
    )
    print(
        f"Transcript dir     : "
        f"{TRANSCRIPT_DIR}"
    )
    print(
        f"Raw transcript dir : "
        f"{RAW_TRANSCRIPT_DIR}"
    )

    print_rule("=")

    return 0


if __name__ == "__main__":
    sys.exit(main())