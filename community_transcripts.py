import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests


# ==============================================================================
# CONFIGURATION
# ==============================================================================

VERSION = "V6.4"

DATA_DIR = Path("data")

SOURCES_FILE = DATA_DIR / "community_sources.json"
SNAPSHOT_FILE = DATA_DIR / "latest_snapshot.json"
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


# ==============================================================================
# PRIMARY SOURCES
# ==============================================================================

STRATEGY_SOURCE = {
    "channel": "Digit Racing",
    "role": "STRATEGY",
    "type": "RACE",
    "title": "🔴 GT7 | Grand Valley - New Week Of Daily Racing! | Live 🔴",
    "video_id": "O-AfZNXuGBg",
    "url": "https://www.youtube.com/watch?v=O-AfZNXuGBg",
}

LAP_GUIDE_SOURCE = {
    "channel": "GnC Racing",
    "role": "LAP_GUIDE",
    "type": "LAP_GUIDE",
    "title": "Gran Turismo 7: Grand Valley Highway 1 | Lap Guide | Group 4 | Daily Race C",
    "video_id": "qHfm2RjbRjI",
    "url": "https://www.youtube.com/watch?v=qHfm2RjbRjI",
}


# ==============================================================================
# DIGIT STRATEGY WINDOWS
# ==============================================================================

# Early part:
# - tyre saving
# - RM / RS
# - pit around lap 4-5
# - mandatory tyre change
#
# Later part:
# - actual race-tested conclusion
# - overcut > undercut
# - staying out longer
# - Citroën tyre advantage

DIGIT_FIXED_WINDOWS = [
    {
        "name": "EARLY_STRATEGY",
        "start": 18 * 60,
        "end": 33 * 60,
        "priority": 100,
    },
    {
        "name": "LATE_OVERCUT_VALIDATION",
        "start": 2 * 3600 + 31 * 60,
        "end": 2 * 3600 + 47 * 60,
        "priority": 110,
    },
]

DIGIT_SECONDARY_WINDOWS = [
    {
        "name": "LATE_COMPOUND_CONTEXT",
        "start": 3 * 3600 + 53 * 60,
        "end": 4 * 3600 + 5 * 60,
        "priority": 50,
    }
]


# ==============================================================================
# TEXT / STRATEGY TERMS
# ==============================================================================

STRATEGY_TERMS = [
    "strategy",
    "pit",
    "pit stop",
    "pit window",
    "stint",
    "overcut",
    "undercut",
    "stay out",
    "stayed out",
    "staying out",
    "should have stayed out",
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
    "gentle with my tires",
    "gentle with my tyres",
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
}


# ==============================================================================
# BASIC UTILITIES
# ==============================================================================

def print_rule(char="=", width=100):
    print(char * width)


def load_json(path: Path, default=None):
    if not path.exists():
        return default

    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            indent=2,
            ensure_ascii=False,
        )


def slugify(value: str) -> str:
    value = (value or "").lower().strip()
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


def parse_timestamp(value: str) -> Optional[int]:
    if not value:
        return None

    try:
        parts = [int(x) for x in value.strip().split(":")]
    except ValueError:
        return None

    if len(parts) == 2:
        return parts[0] * 60 + parts[1]

    if len(parts) == 3:
        return (
            parts[0] * 3600
            + parts[1] * 60
            + parts[2]
        )

    return None


def seconds_to_timestamp(seconds: int) -> str:
    seconds = max(0, int(seconds))

    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60

    if h:
        return f"{h}:{m:02d}:{s:02d}"

    return f"{m}:{s:02d}"


# ==============================================================================
# RECURSIVE JSON SEARCH
# ==============================================================================

def recursive_dicts(obj: Any):
    """
    Yield every dict contained anywhere in a JSON-compatible structure.
    """

    if isinstance(obj, dict):
        yield obj

        for value in obj.values():
            yield from recursive_dicts(value)

    elif isinstance(obj, list):
        for item in obj:
            yield from recursive_dicts(item)


def find_video_record(
    source_db: Any,
    video_id: str,
) -> Optional[Dict[str, Any]]:

    for item in recursive_dicts(source_db):
        values = [
            str(item.get("video_id", "")),
            str(item.get("id", "")),
            str(item.get("url", "")),
            str(item.get("video_url", "")),
            str(item.get("youtube_url", "")),
        ]

        if any(video_id in value for value in values):
            return item

    return None


def enrich_primary_source(
    fallback: Dict[str, Any],
    source_db: Any,
) -> Dict[str, Any]:

    result = dict(fallback)

    found = find_video_record(
        source_db,
        fallback["video_id"],
    )

    if not found:
        return result

    for source_key, target_key in [
        ("channel", "channel"),
        ("channel_name", "channel"),
        ("title", "title"),
        ("type", "type"),
        ("video_type", "type"),
        ("url", "url"),
        ("video_url", "url"),
        ("youtube_url", "url"),
    ]:
        value = found.get(source_key)

        if value:
            result[target_key] = value

    return result


# ==============================================================================
# RACE METADATA
# ==============================================================================

def infer_track_from_description(description: str) -> str:
    if not description:
        return "unknown"

    if "Grand Valley - Highway 1" in description:
        return "Grand Valley - Highway 1"

    if "Grand Valley Highway 1" in description:
        return "Grand Valley - Highway 1"

    return "unknown"


def infer_class_from_description(description: str) -> str:
    if not description:
        return "unknown"

    lower = description.lower()

    if "gr.4" in lower or "gr4" in lower:
        return "Gr.4"

    if "gr.3" in lower or "gr3" in lower:
        return "Gr.3"

    return "unknown"


def extract_race_metadata(
    source_db: Any,
    snapshot: Any,
) -> Dict[str, Any]:

    result = {
        "week": "unknown",
        "track": "unknown",
        "race_class": "unknown",
    }

    # --------------------------------------------------------------------------
    # Preferred: latest_snapshot.json
    # --------------------------------------------------------------------------

    if isinstance(snapshot, dict):

        race = snapshot.get("race", {})

        if isinstance(race, dict):

            start_date = race.get("start_date")

            if start_date:
                result["week"] = start_date

            description = str(
                race.get("description", "")
            )

            track = (
                race.get("track")
                or race.get("circuit")
            )

            if track:
                result["track"] = str(track)
            else:
                result["track"] = infer_track_from_description(
                    description
                )

            race_class = (
                race.get("class")
                or race.get("race_class")
            )

            if race_class:
                result["race_class"] = str(
                    race_class
                )
            else:
                result["race_class"] = infer_class_from_description(
                    description
                )

    # --------------------------------------------------------------------------
    # Fallback: recursively inspect community_sources.json
    # --------------------------------------------------------------------------

    if source_db is not None:

        for item in recursive_dicts(source_db):

            if result["week"] == "unknown":

                for key in [
                    "start_date",
                    "week",
                    "race_week",
                ]:
                    if item.get(key):
                        result["week"] = str(
                            item[key]
                        )
                        break

            if result["track"] == "unknown":

                for key in [
                    "track",
                    "circuit",
                ]:
                    if item.get(key):
                        result["track"] = str(
                            item[key]
                        )
                        break

            if result["race_class"] == "unknown":

                for key in [
                    "race_class",
                    "class",
                ]:
                    if item.get(key):
                        result["race_class"] = str(
                            item[key]
                        )
                        break

            description = str(
                item.get("description", "")
            )

            if (
                result["track"] == "unknown"
                and description
            ):
                result["track"] = infer_track_from_description(
                    description
                )

            if (
                result["race_class"] == "unknown"
                and description
            ):
                result["race_class"] = infer_class_from_description(
                    description
                )

    return result


# ==============================================================================
# TRANSCRIPT PARSING
# ==============================================================================

TIMESTAMP_RE = re.compile(
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

        match = TIMESTAMP_RE.match(line)

        if not match:
            continue

        timestamp = match.group("ts")

        seconds = parse_timestamp(
            timestamp
        )

        if seconds is None:
            continue

        text = normalize_text(
            match.group("text")
        )

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


def build_text_from_chunks(
    chunks: List[Dict[str, Any]],
) -> str:

    return "\n".join(
        f"[{chunk['timestamp']}] {chunk['text']}"
        for chunk in chunks
    )


def detect_fingerprint(text: str) -> List[str]:

    lower = text.lower()

    found = []

    for label, patterns in CURRENT_RACE_FINGERPRINT_TERMS.items():

        if any(
            pattern.lower() in lower
            for pattern in patterns
        ):
            found.append(label)

    return found


def find_strategy_terms(text: str) -> List[str]:

    lower = text.lower()

    return sorted(
        {
            term
            for term in STRATEGY_TERMS
            if term.lower() in lower
        }
    )


# ==============================================================================
# DIGIT STRATEGY EXTRACTION
# ==============================================================================

def extract_digit_strategy(
    raw_text: str,
) -> Dict[str, Any]:

    chunks = parse_timestamped_chunks(
        raw_text
    )

    selected_chunks = []
    seen = set()
    segments = []

    # --------------------------------------------------------------------------
    # Fixed strategic windows
    # --------------------------------------------------------------------------

    for fixed in DIGIT_FIXED_WINDOWS:

        segment_chunks = extract_chunks_between(
            chunks,
            fixed["start"],
            fixed["end"],
        )

        if not segment_chunks:
            continue

        segment_text = build_text_from_chunks(
            segment_chunks
        )

        fingerprint = detect_fingerprint(
            segment_text
        )

        terms = find_strategy_terms(
            segment_text
        )

        segments.append(
            {
                "name": fixed["name"],
                "start_seconds": fixed["start"],
                "end_seconds": fixed["end"],
                "start": seconds_to_timestamp(
                    fixed["start"]
                ),
                "end": seconds_to_timestamp(
                    fixed["end"]
                ),
                "priority": fixed["priority"],
                "fingerprint": fingerprint,
                "strategy_terms": terms,
            }
        )

        for chunk in segment_chunks:

            key = (
                chunk["seconds"],
                chunk["text"],
            )

            if key in seen:
                continue

            seen.add(key)
            selected_chunks.append(chunk)

    # --------------------------------------------------------------------------
    # Secondary compound context
    # --------------------------------------------------------------------------

    for fixed in DIGIT_SECONDARY_WINDOWS:

        segment_chunks = extract_chunks_between(
            chunks,
            fixed["start"],
            fixed["end"],
        )

        if not segment_chunks:
            continue

        segment_text = build_text_from_chunks(
            segment_chunks
        )

        fingerprint = detect_fingerprint(
            segment_text
        )

        if not fingerprint:
            continue

        terms = find_strategy_terms(
            segment_text
        )

        segments.append(
            {
                "name": fixed["name"],
                "start_seconds": fixed["start"],
                "end_seconds": fixed["end"],
                "start": seconds_to_timestamp(
                    fixed["start"]
                ),
                "end": seconds_to_timestamp(
                    fixed["end"]
                ),
                "priority": fixed["priority"],
                "fingerprint": fingerprint,
                "strategy_terms": terms,
            }
        )

        for chunk in segment_chunks:

            key = (
                chunk["seconds"],
                chunk["text"],
            )

            if key in seen:
                continue

            seen.add(key)
            selected_chunks.append(chunk)

    selected_chunks.sort(
        key=lambda x: x["seconds"]
    )

    segments.sort(
        key=lambda x: x["start_seconds"]
    )

    text = build_text_from_chunks(
        selected_chunks
    )

    status = (
        "AVAILABLE"
        if text.strip()
        else "NO_VALID_STRATEGY_SEGMENT"
    )

    return {
        "status": status,
        "mode": "FIXED_STRATEGY_WINDOWS_V6_4",
        "raw_chunks": len(chunks),
        "selected_chunks": len(selected_chunks),
        "segments": segments,
        "text": text,
        "words": count_words(text),
        "characters": len(text),
    }


# ==============================================================================
# CACHE
# ==============================================================================

def raw_cache_path(
    source: Dict[str, Any],
) -> Path:

    return (
        RAW_TRANSCRIPT_DIR
        / (
            f"{source['video_id']}_"
            f"{slugify(source['channel'])}.txt"
        )
    )


def transcript_json_path(
    source: Dict[str, Any],
) -> Path:

    return (
        TRANSCRIPT_DIR
        / (
            f"{source['video_id']}_"
            f"{slugify(source['channel'])}.json"
        )
    )


def find_legacy_json(
    source: Dict[str, Any],
) -> Optional[Path]:

    names = [
        (
            f"{source['video_id']}_"
            f"{slugify(source['channel'])}.json"
        ),
        f"{source['video_id']}.json",
    ]

    for folder in LEGACY_DIRS:

        for name in names:

            path = folder / name

            if path.exists():
                return path

    return None


def extract_text_from_payload(
    obj: Any,
) -> Optional[str]:

    if isinstance(obj, str):
        return obj.strip() or None

    if isinstance(obj, list):

        pieces = []

        for item in obj:

            found = extract_text_from_payload(
                item
            )

            if found:
                pieces.append(found)

        text = "\n".join(pieces).strip()

        return text or None

    if isinstance(obj, dict):

        for key in [
            "transcript",
            "text",
            "content",
        ]:

            if key in obj:

                found = extract_text_from_payload(
                    obj[key]
                )

                if found:
                    return found

        for value in obj.values():

            found = extract_text_from_payload(
                value
            )

            if found:
                return found

    return None


# ==============================================================================
# YOUTUBE-TRANSCRIPT.AI
# ==============================================================================

def request_yttai(
    source: Dict[str, Any],
) -> Optional[str]:

    endpoint = (
        f"{YTTAI_BASE_URL}/"
        f"{source['video_id']}.txt?lang=en"
    )

    print(
        "Provider         : youtube-transcript.ai"
    )

    try:

        response = requests.get(
            endpoint,
            timeout=HTTP_TIMEOUT,
        )

    except Exception as exc:

        print(
            f"Provider error   : "
            f"{type(exc).__name__}"
        )

        return None

    print(
        f"HTTP status      : "
        f"{response.status_code}"
    )

    if response.status_code != 200:
        return None

    text = response.text.strip()

    if not text:
        return None

    return text


# ==============================================================================
# SAVE TRANSCRIPT
# ==============================================================================

def save_transcript(
    source: Dict[str, Any],
    text: str,
    provider: str,
    extraction: Optional[Dict[str, Any]] = None,
) -> Path:

    path = transcript_json_path(
        source
    )

    payload = {
        "video_id": source["video_id"],
        "channel": source["channel"],
        "role": source["role"],
        "type": source["type"],
        "title": source["title"],
        "url": source["url"],
        "status": "AVAILABLE",
        "provider": provider,
        "words": count_words(text),
        "characters": len(text),
        "transcript": text,
    }

    if extraction:

        payload["extraction"] = {
            key: value
            for key, value in extraction.items()
            if key != "text"
        }

    save_json(
        path,
        payload,
    )

    return path


# ==============================================================================
# DIGIT PROCESSOR
# ==============================================================================

def process_digit(
    source: Dict[str, Any],
) -> Dict[str, Any]:

    print(
        f"Title            : "
        f"{source['title']}"
    )
    print(
        f"Video ID         : "
        f"{source['video_id']}"
    )
    print(
        f"URL              : "
        f"{source['url']}"
    )
    print()

    raw_path = raw_cache_path(
        source
    )

    raw_text = None
    provider = None

    if raw_path.exists():

        print("Raw cache        : FOUND")
        print(
            f"Raw file         : "
            f"{raw_path}"
        )

        raw_text = raw_path.read_text(
            encoding="utf-8",
            errors="ignore",
        )

        provider = "RAW_CACHE"

    else:

        print("Raw cache        : NOT FOUND")

        raw_text = request_yttai(
            source
        )

        if raw_text:

            provider = "youtube-transcript.ai"

            raw_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            raw_path.write_text(
                raw_text,
                encoding="utf-8",
            )

            print(
                f"Raw file         : "
                f"{raw_path}"
            )

    if not raw_text:

        print(
            "Final status     : UNAVAILABLE"
        )

        return {
            "status": "UNAVAILABLE",
            "words": 0,
            "characters": 0,
        }

    extraction = extract_digit_strategy(
        raw_text
    )

    print()
    print("DIGIT STRATEGY EXTRACTION")
    print_rule("-")

    print(
        f"Extraction mode  : "
        f"{extraction['mode']}"
    )
    print(
        f"Raw chunks       : "
        f"{extraction['raw_chunks']}"
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

        print(
            f"  Segment {index}: "
            f"{segment['start']} "
            f"-> "
            f"{segment['end']} "
            f"| {segment['name']}"
        )

        print(
            "    Fingerprt: "
            + (
                ", ".join(
                    segment["fingerprint"]
                )
                or "-"
            )
        )

        print(
            "    Strategy : "
            + (
                ", ".join(
                    segment["strategy_terms"]
                )
                or "-"
            )
        )

    if extraction["status"] != "AVAILABLE":

        print(
            "Final status     : "
            f"{extraction['status']}"
        )

        return {
            "status": extraction["status"],
            "words": 0,
            "characters": 0,
            "extraction": extraction,
        }

    print()
    print("STRATEGY TRANSCRIPT PREVIEW")
    print_rule("-")

    preview = extraction["text"][:12000]

    print(preview)

    if len(extraction["text"]) > 12000:
        print(
            "\n[... preview truncated ...]"
        )

    saved = save_transcript(
        source,
        extraction["text"],
        provider or "UNKNOWN",
        extraction,
    )

    print()
    print("Final status     : AVAILABLE")
    print(
        f"Provider         : "
        f"{provider}"
    )
    print(
        f"Words            : "
        f"{extraction['words']:,}"
    )
    print(
        f"Characters       : "
        f"{extraction['characters']:,}"
    )
    print(
        f"Saved file       : "
        f"{saved}"
    )

    return {
        "status": "AVAILABLE",
        "provider": provider,
        "words": extraction["words"],
        "characters": extraction["characters"],
        "saved_file": str(saved),
        "extraction": extraction,
    }


# ==============================================================================
# GNC PROCESSOR
# ==============================================================================

def process_gnc(
    source: Dict[str, Any],
) -> Dict[str, Any]:

    print(
        f"Title            : "
        f"{source['title']}"
    )
    print(
        f"Video ID         : "
        f"{source['video_id']}"
    )
    print(
        f"URL              : "
        f"{source['url']}"
    )
    print()

    current_path = transcript_json_path(
        source
    )

    if current_path.exists():

        current = load_json(
            current_path,
            {},
        )

        text = (
            current.get("transcript")
            or current.get("text")
            or ""
        )

        if text.strip():

            print(
                "Result           : "
                "REUSED_DATABASE"
            )
            print(
                "Final status     : AVAILABLE"
            )
            print(
                "Provider         : LOCAL_DATABASE"
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
                f"{current_path}"
            )

            return {
                "status": "AVAILABLE",
                "provider": "LOCAL_DATABASE",
                "words": count_words(text),
                "characters": len(text),
                "saved_file": str(current_path),
            }

    legacy_path = find_legacy_json(
        source
    )

    if legacy_path:

        legacy = load_json(
            legacy_path,
            {},
        )

        text = extract_text_from_payload(
            legacy
        )

        if text:

            saved = save_transcript(
                source,
                text,
                "LEGACY_CACHE",
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
                "Final status     : AVAILABLE"
            )
            print(
                "Provider         : LEGACY_CACHE"
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
                f"{saved}"
            )

            return {
                "status": "AVAILABLE",
                "provider": "LEGACY_CACHE",
                "words": count_words(text),
                "characters": len(text),
                "saved_file": str(saved),
            }

    raw_path = raw_cache_path(
        source
    )

    if raw_path.exists():

        text = raw_path.read_text(
            encoding="utf-8",
            errors="ignore",
        )

        provider = "RAW_CACHE"

    else:

        text = request_yttai(
            source
        )

        provider = "youtube-transcript.ai"

        if text:

            raw_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            raw_path.write_text(
                text,
                encoding="utf-8",
            )

    if not text:

        print(
            "Final status     : UNAVAILABLE"
        )

        return {
            "status": "UNAVAILABLE",
            "words": 0,
            "characters": 0,
        }

    saved = save_transcript(
        source,
        text,
        provider,
    )

    print(
        "Final status     : AVAILABLE"
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
        f"{saved}"
    )

    return {
        "status": "AVAILABLE",
        "provider": provider,
        "words": count_words(text),
        "characters": len(text),
        "saved_file": str(saved),
    }


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
        {},
    )

    snapshot = load_json(
        SNAPSHOT_FILE,
        {},
    )

    strategy_source = enrich_primary_source(
        STRATEGY_SOURCE,
        source_db,
    )

    lap_source = enrich_primary_source(
        LAP_GUIDE_SOURCE,
        source_db,
    )

    selected_sources = [
        strategy_source,
        lap_source,
    ]

    race_meta = extract_race_metadata(
        source_db,
        snapshot,
    )

    print_rule()
    print(
        f"GT7 COMMUNITY TRANSCRIPT COLLECTOR "
        f"{VERSION}"
    )
    print_rule()

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
        "Strategy source  : Digit Racing"
    )
    print(
        "Lap guide source : GnC Racing"
    )

    print()
    print("PRIMARY SOURCES")
    print_rule("-")

    for i, source in enumerate(
        selected_sources,
        start=1,
    ):

        print(
            f"{i}. "
            f"{source['channel']} "
            f"| {source['role']} "
            f"| [{source['type']}]"
        )
        print(
            f"   {source['title']}"
        )
        print(
            f"   {source['url']}"
        )

    results = {}

    print()
    print_rule()
    print(
        "[1/2] Digit Racing - STRATEGY"
    )
    print_rule()

    results["STRATEGY"] = process_digit(
        strategy_source
    )

    print()
    print_rule()
    print(
        "[2/2] GnC Racing - LAP_GUIDE"
    )
    print_rule()

    results["LAP_GUIDE"] = process_gnc(
        lap_source
    )

    database = {
        "version": VERSION,
        "race": race_meta,
        "primary_sources": {
            "STRATEGY": {
                **strategy_source,
                "status": results[
                    "STRATEGY"
                ].get("status"),
                "provider": results[
                    "STRATEGY"
                ].get("provider"),
                "words": results[
                    "STRATEGY"
                ].get("words", 0),
                "saved_file": results[
                    "STRATEGY"
                ].get("saved_file"),
            },
            "LAP_GUIDE": {
                **lap_source,
                "status": results[
                    "LAP_GUIDE"
                ].get("status"),
                "provider": results[
                    "LAP_GUIDE"
                ].get("provider"),
                "words": results[
                    "LAP_GUIDE"
                ].get("words", 0),
                "saved_file": results[
                    "LAP_GUIDE"
                ].get("saved_file"),
            },
        },
    }

    save_json(
        DATABASE_FILE,
        database,
    )

    print()
    print_rule()
    print("FINAL SUMMARY")
    print_rule()

    print(
        "Primary sources    : 2"
    )

    print()
    print(
        "PRIMARY TRANSCRIPT STATUS"
    )
    print_rule("-")

    strategy = results["STRATEGY"]
    lap = results["LAP_GUIDE"]

    print(
        f"STRATEGY  : "
        f"{strategy['status']}"
    )
    print(
        "  Channel : Digit Racing"
    )
    print(
        f"  Video   : "
        f"{strategy_source['title']}"
    )

    if strategy["status"] == "AVAILABLE":

        print(
            f"  Words   : "
            f"{strategy['words']:,}"
        )

        extraction = strategy.get(
            "extraction",
            {},
        )

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

            print(
                f"    {segment['start']} "
                f"-> "
                f"{segment['end']} "
                f"| {segment['name']}"
            )

    print(
        f"LAP_GUIDE : "
        f"{lap['status']}"
    )
    print(
        "  Channel : GnC Racing"
    )
    print(
        f"  Video   : "
        f"{lap_source['title']}"
    )

    if lap["status"] == "AVAILABLE":

        print(
            f"  Words   : "
            f"{lap['words']:,}"
        )
        print(
            f"  Provider: "
            f"{lap.get('provider', '-')}"
        )

    strategy_ready = (
        strategy["status"] == "AVAILABLE"
    )

    lap_ready = (
        lap["status"] == "AVAILABLE"
    )

    print()
    print(
        "COMMUNITY INTELLIGENCE READINESS"
    )
    print_rule("-")

    print(
        "Digit strategy    : "
        + (
            "READY"
            if strategy_ready
            else "PENDING"
        )
    )

    print(
        "GnC lap guide     : "
        + (
            "READY"
            if lap_ready
            else "PENDING"
        )
    )

    print(
        "Full report ready : "
        + (
            "YES"
            if strategy_ready
            and lap_ready
            else "No"
        )
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

    print_rule()

    return 0


if __name__ == "__main__":
    sys.exit(main())