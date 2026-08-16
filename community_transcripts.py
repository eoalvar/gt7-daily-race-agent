import json
import os
import re
import time
from datetime import datetime, UTC
from pathlib import Path

import requests


# =============================================================================
# GT7 COMMUNITY TRANSCRIPT COLLECTOR V6.1
# =============================================================================
#
# SOURCE POLICY
#
# Strategy:
#   Digit Racing
#
# Qualifying / lap guide:
#   GnC Racing
#
#
# DIGIT STRATEGY EXTRACTION
#
# The full Digit Racing livestream is analysed as timestamped rolling windows.
#
# A window is accepted ONLY when:
#
#   1. It contains evidence identifying the current Daily Race C;
#   2. It contains substantive race/strategy information;
#   3. It reaches the minimum positive score;
#   4. It is not dominated by intro/chat/other-race discussion.
#
# There is NO weak fallback.
#
# V6.1 additionally prints diagnostic transcript windows at:
#
#   10:00 -> 30:00
#   2:30:00 -> 2:50:00
#   3:50:00 -> 4:10:00
#
# =============================================================================


# =============================================================================
# PATHS
# =============================================================================

DATA_DIR = Path("data")

COMMUNITY_SOURCES_FILE = DATA_DIR / "community_sources.json"

TRANSCRIPT_DB_FILE = DATA_DIR / "community_transcripts.json"

TRANSCRIPT_DIR = DATA_DIR / "community_transcripts"

RAW_TRANSCRIPT_DIR = DATA_DIR / "community_transcripts_raw"


LEGACY_TRANSCRIPT_DIRS = [
    DATA_DIR / "community_supadata_test" / "transcripts",
    DATA_DIR / "community_transcript_test" / "transcripts",
    DATA_DIR / "community_youtube_transcript_test",
]


# =============================================================================
# PROVIDERS
# =============================================================================

SUPADATA_BASE_URL = "https://api.supadata.ai/v1"

SUPADATA_API_KEY = os.environ.get(
    "SUPADATA_API_KEY",
    ""
)

YOUTUBE_TRANSCRIPT_BASE_URL = (
    "https://youtube-transcript.ai/transcript"
)

REQUEST_TIMEOUT = 120

POLL_INTERVAL_SECONDS = 3
MAX_POLL_ATTEMPTS = 40


# =============================================================================
# PRIMARY SOURCES
# =============================================================================

STRATEGY_CHANNEL = "Digit Racing"
LAP_GUIDE_CHANNEL = "GnC Racing"


# =============================================================================
# DIGIT ROLLING WINDOW CONFIGURATION
# =============================================================================

DIGIT_WINDOW_SECONDS = 300

DIGIT_WINDOW_STEP_SECONDS = 60

DIGIT_CONTEXT_BEFORE_SECONDS = 60
DIGIT_CONTEXT_AFTER_SECONDS = 120

DIGIT_MAX_SEGMENTS = 3

DIGIT_MAX_TOTAL_SECONDS = 1800

DIGIT_MIN_SCORE = 15

DIGIT_MIN_STRATEGY_HITS = 3


# =============================================================================
# RACE IDENTITY TERMS
# =============================================================================

RACE_IDENTITY_TERMS = {

    "daily race c": 18,
    "race c": 10,

    "grand valley": 15,
    "highway 1": 8,
    "highway one": 8,

    "group 4": 6,
    "gr.4": 6,
    "gr4": 6,
    "group four": 6,
}


# =============================================================================
# STRATEGY TERMS
# =============================================================================

STRATEGY_TERMS = {

    "strategy": 8,

    "pit stop": 8,
    "pitstop": 8,
    "pit lane": 6,
    "pit": 4,

    "mandatory": 8,
    "required": 4,

    "fuel": 5,
    "fuel map": 7,
    "fuel saving": 7,
    "save fuel": 7,
    "consumption": 5,

    "tire": 4,
    "tires": 4,
    "tyre": 4,
    "tyres": 4,

    "tire wear": 6,
    "tyre wear": 6,

    "save tires": 6,
    "save tyres": 6,

    "racing soft": 6,
    "racing medium": 6,
    "racing hard": 6,

    "soft tire": 5,
    "soft tyre": 5,

    "medium tire": 5,
    "medium tyre": 5,

    "hard tire": 5,
    "hard tyre": 5,

    "softs": 4,
    "mediums": 4,
    "hards": 4,

    "lap": 1,
    "laps": 2,
    "stint": 6,

    "race pace": 7,
    "pace": 2,

    "short shift": 6,
    "short-shift": 6,

    "undercut": 7,
    "overcut": 7,
    "one stop": 7,
    "one-stop": 7,
    "no stop": 7,
    "no-stop": 7,

    "slipstream": 3,
    "draft": 3,

    "overtake": 3,
    "overtaking": 3,

    "track limits": 5,
    "penalty": 3,
    "penalties": 3,

    "meta": 5,
    "car choice": 6,

    "citroen": 2,
    "citroën": 2,

    "genesis": 2,
    "g70": 2,

    "gt-r": 2,
    "gtr": 2,

    "silvia": 2,
}


# =============================================================================
# INTRO / CHAT PENALTIES
# =============================================================================

INTRO_CHAT_TERMS = {

    "welcome back": 5,
    "hello everyone": 6,
    "hello to everyone": 6,

    "welcome to": 3,

    "chat": 3,

    "subscriber": 3,
    "subscribe": 3,

    "like the stream": 4,

    "copyright": 5,

    "theme song": 6,

    "pedal cam": 6,

    "suno": 8,

    "mechanic": 3,

    "air conditioning": 3,

    "lose power": 3,

    "disconnected": 2,
}


# =============================================================================
# OTHER RACES / DISTRACTOR PENALTIES
# =============================================================================

OTHER_RACE_TERMS = {

    "daily race a": 10,
    "race a": 6,

    "daily race b": 10,
    "race b": 6,

    "route x": 8,
    "special stage route x": 12,

    "fuji": 6,
}


# =============================================================================
# BASIC HELPERS
# =============================================================================

def load_json(path, default=None):

    if not path.exists():
        return default

    try:
        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

    except Exception:
        return default


def save_json(path, data):

    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    path.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


def normalize_space(text):

    return re.sub(
        r"\s+",
        " ",
        text or ""
    ).strip()


def safe_filename(text):

    value = (
        text
        or "unknown"
    ).lower()

    value = re.sub(
        r"[^a-z0-9]+",
        "_",
        value
    )

    return value.strip("_")


def timestamp_to_seconds(timestamp):

    if not timestamp:
        return None

    parts = timestamp.split(":")

    try:

        if len(parts) == 2:

            minutes = int(parts[0])
            seconds = int(parts[1])

            return minutes * 60 + seconds

        if len(parts) == 3:

            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = int(parts[2])

            return (
                hours * 3600
                + minutes * 60
                + seconds
            )

    except Exception:
        return None

    return None


def seconds_to_timestamp(total_seconds):

    total_seconds = max(
        0,
        int(total_seconds)
    )

    hours = total_seconds // 3600

    minutes = (
        total_seconds
        % 3600
    ) // 60

    seconds = total_seconds % 60

    if hours:
        return (
            f"{hours}:"
            f"{minutes:02d}:"
            f"{seconds:02d}"
        )

    return (
        f"{minutes}:"
        f"{seconds:02d}"
    )


# =============================================================================
# TRANSCRIPT PAYLOAD EXTRACTION
# =============================================================================

def transcript_text_from_payload(payload):

    if payload is None:
        return None

    if isinstance(payload, str):

        value = normalize_space(
            payload
        )

        return value if value else None

    if isinstance(payload, list):

        parts = []

        for item in payload:

            if isinstance(item, str):

                value = normalize_space(
                    item
                )

            elif isinstance(item, dict):

                value = normalize_space(
                    item.get("text")
                    or item.get("content")
                    or item.get("transcript")
                    or ""
                )

            else:
                value = ""

            if value:
                parts.append(value)

        if parts:
            return normalize_space(
                " ".join(parts)
            )

        return None

    if not isinstance(payload, dict):
        return None

    for key in [
        "transcript",
        "text",
    ]:

        value = payload.get(key)

        if isinstance(value, str):

            value = normalize_space(
                value
            )

            if value:
                return value

    content = payload.get("content")

    value = transcript_text_from_payload(
        content
    )

    if value:
        return value

    for key in [
        "result",
        "payload",
        "data",
        "response",
    ]:

        nested = payload.get(key)

        value = transcript_text_from_payload(
            nested
        )

        if value:
            return value

    return None


# =============================================================================
# DATABASE
# =============================================================================

def normalize_database(database):

    if not isinstance(
        database,
        dict
    ):
        database = {}

    database.setdefault(
        "version",
        6
    )

    database.setdefault(
        "videos",
        {}
    )

    return database


def get_existing_record(
    database,
    video_id
):

    return (
        database
        .get("videos", {})
        .get(video_id)
    )


# =============================================================================
# FILE PATHS
# =============================================================================

def transcript_file_path(video):

    video_id = (
        video.get("video_id")
        or "unknown"
    )

    channel = safe_filename(
        video.get("channel")
    )

    return (
        TRANSCRIPT_DIR
        / f"{video_id}_{channel}.json"
    )


def raw_transcript_file_path(video):

    video_id = (
        video.get("video_id")
        or "unknown"
    )

    channel = safe_filename(
        video.get("channel")
    )

    return (
        RAW_TRANSCRIPT_DIR
        / f"{video_id}_{channel}.txt"
    )


# =============================================================================
# CURRENT WEEK
# =============================================================================

def get_current_week(
    source_database
):

    weeks = source_database.get(
        "weeks",
        {}
    )

    if not weeks:

        raise RuntimeError(
            "No weeks found in "
            "data/community_sources.json"
        )

    week_keys = sorted(
        weeks.keys()
    )

    week_key = week_keys[-1]

    return (
        week_key,
        weeks[week_key]
    )


# =============================================================================
# PRIMARY SOURCE SELECTION
# =============================================================================

def select_primary_sources(
    week_data
):

    selected_sources = (
        week_data.get(
            "selected_sources",
            {}
        )
    )

    strategy = selected_sources.get(
        "strategy_primary"
    )

    lap_guide = selected_sources.get(
        "lap_guide_primary"
    )

    output = []

    if (
        strategy
        and strategy.get("channel")
        == STRATEGY_CHANNEL
    ):

        item = dict(strategy)

        item["purpose"] = "STRATEGY"

        output.append(item)

    if (
        lap_guide
        and lap_guide.get("channel")
        == LAP_GUIDE_CHANNEL
    ):

        item = dict(lap_guide)

        item["purpose"] = "LAP_GUIDE"

        output.append(item)

    return output


# =============================================================================
# LEGACY CACHE
# =============================================================================

def find_legacy_transcript(
    video_id
):

    if not video_id:
        return None

    for directory in LEGACY_TRANSCRIPT_DIRS:

        if not directory.exists():
            continue

        patterns = [
            f"{video_id}_*.json",
            f"{video_id}.json",
            f"{video_id}_*.txt",
            f"{video_id}.txt",
        ]

        matches = []

        for pattern in patterns:

            matches.extend(
                directory.glob(
                    pattern
                )
            )

        for path in matches:

            if path.suffix.lower() == ".txt":

                try:

                    raw_text = path.read_text(
                        encoding="utf-8"
                    )

                except Exception:
                    continue

                text = normalize_space(
                    raw_text
                )

                if text:

                    return {
                        "text": text,
                        "raw_text": raw_text,
                        "source": str(path),
                    }

            payload = load_json(
                path
            )

            if not payload:
                continue

            text = transcript_text_from_payload(
                payload
            )

            if text:

                return {
                    "text": text,
                    "raw_text": text,
                    "source": str(path),
                }

    return None


# =============================================================================
# WORD DE-DUPLICATION
# =============================================================================

def dedupe_consecutive_words(
    text
):

    text = normalize_space(
        text
    )

    if not text:
        return ""

    words = text.split()

    output = []

    index = 0
    total = len(words)

    while index < total:

        best_size = 0
        best_repeats = 1

        max_size = min(
            40,
            (
                total
                - index
            )
            // 2
        )

        for size in range(
            max_size,
            2,
            -1
        ):

            first = words[
                index:
                index + size
            ]

            second = words[
                index + size:
                index + size * 2
            ]

            if first != second:
                continue

            repeats = 2

            while True:

                start = (
                    index
                    + repeats * size
                )

                end = start + size

                if end > total:
                    break

                candidate = words[
                    start:end
                ]

                if candidate != first:
                    break

                repeats += 1

            best_size = size
            best_repeats = repeats

            break

        if best_size > 0:

            output.extend(
                words[
                    index:
                    index + best_size
                ]
            )

            index += (
                best_size
                * best_repeats
            )

        else:

            output.append(
                words[index]
            )

            index += 1

    return normalize_space(
        " ".join(output)
    )


# =============================================================================
# TIMESTAMPED MARKDOWN PARSER
# =============================================================================

def parse_timestamped_markdown(
    raw_text
):

    chunks = []

    if not raw_text:
        return chunks

    pattern = re.compile(
        r"^\[(\d{1,2}:\d{2}"
        r"(?::\d{2})?)\]\s*(.*)$"
    )

    current = None

    for raw_line in raw_text.splitlines():

        line = raw_line.strip()

        match = pattern.match(
            line
        )

        if match:

            if current:

                current["text"] = normalize_space(
                    " ".join(
                        current["text_parts"]
                    )
                )

                current.pop(
                    "text_parts",
                    None
                )

                chunks.append(
                    current
                )

            timestamp = match.group(1)

            current = {

                "timestamp":
                    timestamp,

                "seconds":
                    timestamp_to_seconds(
                        timestamp
                    ),

                "text_parts": [
                    match.group(2)
                ],
            }

        else:

            if (
                current
                and line
                and not line.startswith("#")
            ):

                current[
                    "text_parts"
                ].append(line)

    if current:

        current["text"] = normalize_space(
            " ".join(
                current["text_parts"]
            )
        )

        current.pop(
            "text_parts",
            None
        )

        chunks.append(current)

    return chunks


def clean_timestamp_chunks(
    chunks
):

    cleaned = []

    previous_text = None

    for chunk in chunks:

        text = dedupe_consecutive_words(
            chunk.get(
                "text",
                ""
            )
        )

        text = normalize_space(
            text
        )

        if not text:
            continue

        compare = re.sub(
            r"[^a-z0-9]+",
            " ",
            text.lower()
        ).strip()

        if (
            previous_text
            and compare == previous_text
        ):
            continue

        previous_text = compare

        cleaned.append({

            "timestamp":
                chunk.get("timestamp"),

            "seconds":
                chunk.get("seconds"),

            "text":
                text,
        })

    return cleaned


# =============================================================================
# TERM SCORING
# =============================================================================

def weighted_term_score(
    text,
    terms
):

    text_lower = (
        text
        or ""
    ).lower()

    score = 0
    hits = []

    for term, weight in terms.items():

        if term in text_lower:

            score += weight
            hits.append(term)

    return score, hits


# =============================================================================
# TRACK MATCH
# =============================================================================

def calculate_track_bonus(
    text,
    track
):

    if not track:
        return 0

    text_lower = text.lower()

    tokens = [
        token
        for token in re.findall(
            r"[a-z0-9]+",
            track.lower()
        )
        if len(token) >= 4
    ]

    matches = sum(
        1
        for token in tokens
        if token in text_lower
    )

    if matches >= 4:
        return 10

    if matches == 3:
        return 8

    if matches == 2:
        return 5

    if matches == 1:
        return 2

    return 0


# =============================================================================
# DIGIT WINDOW SCORING
# =============================================================================

def score_digit_window(
    text,
    track
):

    race_score, race_hits = (
        weighted_term_score(
            text,
            RACE_IDENTITY_TERMS
        )
    )

    strategy_score, strategy_hits = (
        weighted_term_score(
            text,
            STRATEGY_TERMS
        )
    )

    intro_score, intro_hits = (
        weighted_term_score(
            text,
            INTRO_CHAT_TERMS
        )
    )

    other_score, other_hits = (
        weighted_term_score(
            text,
            OTHER_RACE_TERMS
        )
    )

    track_bonus = calculate_track_bonus(
        text,
        track
    )

    total_score = (
        race_score
        + strategy_score
        + track_bonus
        - intro_score
        - other_score
    )

    strong_identity = (

        "daily race c" in race_hits

        or (
            "grand valley" in race_hits
            and (
                "race c" in race_hits
                or "group 4" in race_hits
                or "gr.4" in race_hits
                or "gr4" in race_hits
                or "group four" in race_hits
            )
        )
    )

    enough_strategy = (
        len(
            set(strategy_hits)
        )
        >= DIGIT_MIN_STRATEGY_HITS
    )

    positive_score = (
        total_score
        >= DIGIT_MIN_SCORE
    )

    valid = (
        strong_identity
        and enough_strategy
        and positive_score
    )

    rejection_reasons = []

    if not strong_identity:

        rejection_reasons.append(
            "NO_STRONG_RACE_IDENTITY"
        )

    if not enough_strategy:

        rejection_reasons.append(
            "INSUFFICIENT_STRATEGY_EVIDENCE"
        )

    if not positive_score:

        rejection_reasons.append(
            "SCORE_BELOW_THRESHOLD"
        )

    if intro_score >= 10:

        rejection_reasons.append(
            "INTRO_CHAT_HEAVY"
        )

    if other_score >= 10:

        rejection_reasons.append(
            "OTHER_RACE_HEAVY"
        )

    return {

        "valid":
            valid,

        "score":
            total_score,

        "race_score":
            race_score,

        "strategy_score":
            strategy_score,

        "track_bonus":
            track_bonus,

        "intro_penalty":
            intro_score,

        "other_race_penalty":
            other_score,

        "race_hits":
            sorted(
                set(race_hits)
            ),

        "strategy_hits":
            sorted(
                set(strategy_hits)
            ),

        "intro_hits":
            sorted(
                set(intro_hits)
            ),

        "other_hits":
            sorted(
                set(other_hits)
            ),

        "rejection_reasons":
            rejection_reasons,
    }


# =============================================================================
# ROLLING WINDOWS
# =============================================================================

def build_digit_windows(
    chunks
):

    seconds_values = [
        chunk["seconds"]
        for chunk in chunks
        if chunk.get("seconds") is not None
    ]

    if not seconds_values:
        return []

    max_seconds = max(
        seconds_values
    )

    windows = []

    start = 0

    while start <= max_seconds:

        end = (
            start
            + DIGIT_WINDOW_SECONDS
        )

        window_chunks = [

            chunk

            for chunk in chunks

            if (
                chunk.get("seconds")
                is not None
                and start
                <= chunk["seconds"]
                < end
            )
        ]

        if window_chunks:

            text = normalize_space(
                " ".join(
                    chunk["text"]
                    for chunk in window_chunks
                )
            )

            windows.append({

                "start":
                    start,

                "end":
                    end,

                "text":
                    text,

                "chunks":
                    window_chunks,
            })

        start += (
            DIGIT_WINDOW_STEP_SECONDS
        )

    return windows


# =============================================================================
# WINDOW ANALYSIS
# =============================================================================

def analyse_digit_windows(
    chunks,
    track
):

    windows = build_digit_windows(
        chunks
    )

    analysed = []

    for window in windows:

        scoring = score_digit_window(
            window["text"],
            track
        )

        analysed.append({

            "start":
                window["start"],

            "end":
                window["end"],

            "text":
                window["text"],

            **scoring,
        })

    analysed.sort(
        key=lambda item:
            item["score"],
        reverse=True
    )

    return analysed


# =============================================================================
# PRINT CANDIDATES
# =============================================================================

def print_digit_candidates(
    analysed,
    limit=15
):

    print(
        "TOP DIGIT STRATEGY CANDIDATES"
    )

    print(
        "-" * 96
    )

    if not analysed:

        print(
            "No timestamped windows found."
        )

        print("")

        return

    for index, item in enumerate(
        analysed[:limit],
        start=1
    ):

        status = (
            "ACCEPT"
            if item["valid"]
            else "REJECT"
        )

        print(
            f"{index:2d}. "
            f"{seconds_to_timestamp(item['start'])} "
            f"-> "
            f"{seconds_to_timestamp(item['end'])} "
            f"| score "
            f"{item['score']} "
            f"| {status}"
        )

        print(
            "    Race     : "
            + (
                ", ".join(
                    item["race_hits"]
                )
                if item["race_hits"]
                else "-"
            )
        )

        print(
            "    Strategy : "
            + (
                ", ".join(
                    item["strategy_hits"]
                )
                if item["strategy_hits"]
                else "-"
            )
        )

        if item["intro_hits"]:

            print(
                "    Intro/chat: "
                + ", ".join(
                    item["intro_hits"]
                )
            )

        if item["other_hits"]:

            print(
                "    Other race: "
                + ", ".join(
                    item["other_hits"]
                )
            )

        if not item["valid"]:

            print(
                "    Reject   : "
                + ", ".join(
                    item["rejection_reasons"]
                )
            )

    print("")


# =============================================================================
# DIAGNOSTIC WINDOWS
# =============================================================================

def print_digit_diagnostic_windows(
    raw_text
):

    print(
        "DIGIT DIAGNOSTIC WINDOWS"
    )

    print(
        "-" * 96
    )

    diagnostic_ranges = [
        (600, 1800),
        (9000, 10200),
        (13800, 15000),
    ]

    diagnostic_chunks = (
        clean_timestamp_chunks(
            parse_timestamped_markdown(
                raw_text
            )
        )
    )

    for (
        range_start,
        range_end
    ) in diagnostic_ranges:

        print("")

        print(
            f"### "
            f"{seconds_to_timestamp(range_start)} "
            f"-> "
            f"{seconds_to_timestamp(range_end)}"
        )

        found = False

        for chunk in diagnostic_chunks:

            seconds = chunk.get(
                "seconds"
            )

            if (
                seconds is not None
                and range_start
                <= seconds
                <= range_end
            ):

                found = True

                print(
                    f"[{chunk.get('timestamp')}] "
                    f"{chunk.get('text')}"
                )

        if not found:

            print(
                "No transcript chunks "
                "in this interval."
            )

    print("")


# =============================================================================
# MERGE VALID WINDOWS
# =============================================================================

def merge_valid_windows(
    valid_windows
):

    if not valid_windows:
        return []

    windows = sorted(
        valid_windows,
        key=lambda item:
            item["start"]
    )

    merged = []

    for window in windows:

        start = max(
            0,
            window["start"]
            - DIGIT_CONTEXT_BEFORE_SECONDS
        )

        end = (
            window["end"]
            + DIGIT_CONTEXT_AFTER_SECONDS
        )

        candidate = {

            "start":
                start,

            "end":
                end,

            "score":
                window["score"],

            "evidence": [
                {
                    "original_start":
                        window["start"],

                    "original_end":
                        window["end"],

                    "score":
                        window["score"],

                    "race_hits":
                        window["race_hits"],

                    "strategy_hits":
                        window["strategy_hits"],
                }
            ],
        }

        if not merged:

            merged.append(
                candidate
            )

            continue

        previous = merged[-1]

        if (
            candidate["start"]
            <= previous["end"]
        ):

            previous["end"] = max(
                previous["end"],
                candidate["end"]
            )

            previous["score"] = max(
                previous["score"],
                candidate["score"]
            )

            previous[
                "evidence"
            ].extend(
                candidate["evidence"]
            )

        else:

            merged.append(
                candidate
            )

    return merged


# =============================================================================
# SELECT BEST SEGMENTS
# =============================================================================

def select_best_segments(
    merged_segments
):

    ranked = sorted(
        merged_segments,
        key=lambda item:
            item["score"],
        reverse=True
    )

    selected = []
    total_duration = 0

    for segment in ranked:

        duration = max(
            0,
            segment["end"]
            - segment["start"]
        )

        if (
            total_duration + duration
            > DIGIT_MAX_TOTAL_SECONDS
        ):
            continue

        selected.append(
            segment
        )

        total_duration += duration

        if (
            len(selected)
            >= DIGIT_MAX_SEGMENTS
        ):
            break

    selected.sort(
        key=lambda item:
            item["start"]
    )

    return selected


# =============================================================================
# EXTRACT DIGIT STRATEGY
# =============================================================================

def extract_digit_strategy(
    raw_text,
    track
):

    raw_chunks = parse_timestamped_markdown(
        raw_text
    )

    chunks = clean_timestamp_chunks(
        raw_chunks
    )

    if not chunks:

        return {

            "success":
                False,

            "text":
                "",

            "mode":
                "NO_TIMESTAMPED_TRANSCRIPT",

            "segments":
                [],

            "raw_chunks":
                0,

            "candidate_windows":
                0,

            "valid_windows":
                0,

            "selected_chunks":
                0,

            "analysed":
                [],
        }

    analysed = analyse_digit_windows(
        chunks,
        track
    )

    valid_windows = [
        item
        for item in analysed
        if item["valid"]
    ]

    merged_segments = (
        merge_valid_windows(
            valid_windows
        )
    )

    selected_segments = (
        select_best_segments(
            merged_segments
        )
    )

    selected_chunks = []
    seen = set()

    for segment in selected_segments:

        for chunk in chunks:

            seconds = chunk.get(
                "seconds"
            )

            if seconds is None:
                continue

            if (
                segment["start"]
                <= seconds
                <= segment["end"]
            ):

                key = (
                    seconds,
                    chunk["text"]
                )

                if key in seen:
                    continue

                seen.add(key)

                selected_chunks.append(
                    chunk
                )

    selected_chunks.sort(
        key=lambda item:
            item.get(
                "seconds",
                0
            )
    )

    lines = []

    for chunk in selected_chunks:

        lines.append(
            f"[{chunk['timestamp']}] "
            f"{chunk['text']}"
        )

    text = "\n".join(
        lines
    ).strip()

    segment_metadata = []

    for segment in selected_segments:

        segment_metadata.append({

            "start_seconds":
                segment["start"],

            "end_seconds":
                segment["end"],

            "start":
                seconds_to_timestamp(
                    segment["start"]
                ),

            "end":
                seconds_to_timestamp(
                    segment["end"]
                ),

            "score":
                segment["score"],

            "evidence":
                segment["evidence"],
        })

    return {

        "success":
            bool(text),

        "text":
            text,

        "mode":
            (
                "STRATEGY_ROLLING_WINDOWS_V6_1"
                if text
                else
                "NO_VALID_STRATEGY_SEGMENT"
            ),

        "segments":
            segment_metadata,

        "raw_chunks":
            len(chunks),

        "candidate_windows":
            len(analysed),

        "valid_windows":
            len(valid_windows),

        "selected_chunks":
            len(selected_chunks),

        "analysed":
            analysed,
    }


# =============================================================================
# YOUTUBE-TRANSCRIPT.AI
# =============================================================================

def request_youtube_transcript_ai(
    video_id
):

    endpoint = (
        f"{YOUTUBE_TRANSCRIPT_BASE_URL}/"
        f"{video_id}.txt"
        f"?lang=en"
    )

    headers = {

        "User-Agent":
            (
                "Mozilla/5.0 "
                "(X11; Linux x86_64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/127.0 Safari/537.36"
            ),

        "Accept":
            (
                "text/markdown,"
                "text/plain;q=0.9,"
                "*/*;q=0.8"
            ),
    }

    try:

        response = requests.get(
            endpoint,
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )

    except requests.Timeout:

        return {

            "success":
                False,

            "status":
                "YTTAI_TIMEOUT",

            "provider":
                "youtube-transcript.ai",
        }

    except requests.RequestException as exc:

        return {

            "success":
                False,

            "status":
                "YTTAI_REQUEST_ERROR",

            "provider":
                "youtube-transcript.ai",

            "error":
                str(exc),
        }

    http_status = response.status_code

    raw_text = (
        response.text
        or ""
    ).strip()

    if http_status != 200:

        return {

            "success":
                False,

            "status":
                f"YTTAI_HTTP_{http_status}",

            "provider":
                "youtube-transcript.ai",

            "http_status":
                http_status,

            "payload":
                raw_text[:2000],
        }

    if not raw_text:

        return {

            "success":
                False,

            "status":
                "YTTAI_EMPTY",

            "provider":
                "youtube-transcript.ai",

            "http_status":
                http_status,
        }

    lower = raw_text.lower()

    error_indicators = [
        "transcript unavailable",
        "video unavailable",
        "captions unavailable",
        "no transcript",
        "failed to fetch",
    ]

    for indicator in error_indicators:

        if indicator in lower:

            return {

                "success":
                    False,

                "status":
                    "YTTAI_PROVIDER_ERROR",

                "provider":
                    "youtube-transcript.ai",

                "http_status":
                    http_status,

                "payload":
                    raw_text[:2000],
            }

    return {

        "success":
            True,

        "status":
            "YTTAI_SUCCESS",

        "provider":
            "youtube-transcript.ai",

        "delivery_mode":
            "IMMEDIATE",

        "http_status":
            http_status,

        "raw_text":
            raw_text,
    }


# =============================================================================
# SUPADATA
# =============================================================================

def supadata_headers():

    return {

        "x-api-key":
            SUPADATA_API_KEY,

        "Accept":
            "application/json",
    }


def poll_supadata_job(
    job_id
):

    endpoint = (
        f"{SUPADATA_BASE_URL}/"
        f"transcript/{job_id}"
    )

    for attempt in range(
        1,
        MAX_POLL_ATTEMPTS + 1
    ):

        print(
            f"Polling Supadata : "
            f"{attempt}/"
            f"{MAX_POLL_ATTEMPTS}"
        )

        try:

            response = requests.get(
                endpoint,
                headers=supadata_headers(),
                timeout=REQUEST_TIMEOUT
            )

        except Exception as exc:

            return {

                "success":
                    False,

                "status":
                    "SUPADATA_POLL_ERROR",

                "provider":
                    "Supadata",

                "error":
                    str(exc),
            }

        try:
            payload = response.json()

        except Exception:

            payload = {
                "raw":
                    response.text[:2000]
            }

        if response.status_code == 429:

            return {

                "success":
                    False,

                "status":
                    "SUPADATA_PLAN_LIMIT",

                "provider":
                    "Supadata",

                "http_status":
                    429,

                "payload":
                    payload,
            }

        if response.status_code != 200:

            return {

                "success":
                    False,

                "status":
                    (
                        "SUPADATA_HTTP_"
                        f"{response.status_code}"
                    ),

                "provider":
                    "Supadata",

                "http_status":
                    response.status_code,

                "payload":
                    payload,
            }

        text = transcript_text_from_payload(
            payload
        )

        if text:

            return {

                "success":
                    True,

                "status":
                    "SUPADATA_ASYNC_SUCCESS",

                "provider":
                    "Supadata",

                "delivery_mode":
                    "ASYNC",

                "text":
                    text,

                "raw_text":
                    text,
            }

        status = normalize_space(
            payload.get(
                "status",
                ""
            )
        ).lower()

        if status in {
            "failed",
            "error",
        }:

            return {

                "success":
                    False,

                "status":
                    "SUPADATA_ASYNC_FAILED",

                "provider":
                    "Supadata",
            }

        time.sleep(
            POLL_INTERVAL_SECONDS
        )

    return {

        "success":
            False,

        "status":
            "SUPADATA_ASYNC_TIMEOUT",

        "provider":
            "Supadata",
    }


def request_supadata_transcript(
    video_url
):

    if not SUPADATA_API_KEY:

        return {

            "success":
                False,

            "status":
                "SUPADATA_API_KEY_MISSING",

            "provider":
                "Supadata",
        }

    endpoint = (
        f"{SUPADATA_BASE_URL}/"
        "transcript"
    )

    try:

        response = requests.get(
            endpoint,
            headers=supadata_headers(),
            params={
                "url":
                    video_url,

                "text":
                    "true",
            },
            timeout=REQUEST_TIMEOUT
        )

    except Exception as exc:

        return {

            "success":
                False,

            "status":
                "SUPADATA_REQUEST_ERROR",

            "provider":
                "Supadata",

            "error":
                str(exc),
        }

    try:
        payload = response.json()

    except Exception:

        payload = {
            "raw":
                response.text[:2000]
        }

    if response.status_code == 429:

        return {

            "success":
                False,

            "status":
                "SUPADATA_PLAN_LIMIT",

            "provider":
                "Supadata",

            "http_status":
                429,

            "payload":
                payload,
        }

    if response.status_code == 202:

        job_id = (
            payload.get("jobId")
            or payload.get("job_id")
        )

        if not job_id:

            return {

                "success":
                    False,

                "status":
                    "SUPADATA_NO_JOB_ID",

                "provider":
                    "Supadata",
            }

        return poll_supadata_job(
            job_id
        )

    if response.status_code != 200:

        return {

            "success":
                False,

            "status":
                (
                    "SUPADATA_HTTP_"
                    f"{response.status_code}"
                ),

            "provider":
                "Supadata",
        }

    text = transcript_text_from_payload(
        payload
    )

    if not text:

        return {

            "success":
                False,

            "status":
                "SUPADATA_NO_CONTENT",

            "provider":
                "Supadata",
        }

    return {

        "success":
            True,

        "status":
            "SUPADATA_IMMEDIATE_SUCCESS",

        "provider":
            "Supadata",

        "delivery_mode":
            "IMMEDIATE",

        "text":
            text,

        "raw_text":
            text,
    }


# =============================================================================
# RAW CACHE
# =============================================================================

def load_existing_raw_transcript(
    video
):

    path = raw_transcript_file_path(
        video
    )

    if not path.exists():
        return None

    try:

        raw_text = path.read_text(
            encoding="utf-8"
        )

    except Exception:
        return None

    if not raw_text.strip():
        return None

    return raw_text


def save_raw_transcript(
    video,
    raw_text
):

    if not raw_text:
        return None

    RAW_TRANSCRIPT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    path = raw_transcript_file_path(
        video
    )

    path.write_text(
        raw_text,
        encoding="utf-8"
    )

    return path


# =============================================================================
# RECORD CREATION
# =============================================================================

def create_available_record(
    week_key,
    video,
    provider,
    text,
    api_status,
    extraction=None,
    raw_file=None,
    cache_source=None
):

    text = (
        text
        or ""
    ).strip()

    record = {

        "week":
            week_key,

        "video_id":
            video.get("video_id"),

        "channel":
            video.get("channel"),

        "purpose":
            video.get("purpose"),

        "content_type":
            video.get("content_type"),

        "title":
            video.get("title"),

        "url":
            video.get("url"),

        "status":
            "AVAILABLE",

        "provider":
            provider,

        "api_status":
            api_status,

        "cache_source":
            cache_source,

        "raw_transcript_file":
            (
                str(raw_file)
                if raw_file
                else None
            ),

        "word_count":
            len(text.split()),

        "character_count":
            len(text),

        "transcript":
            text,

        "updated_at":
            datetime.now(
                UTC
            ).isoformat(),
    }

    if extraction:

        record[
            "strategy_extraction"
        ] = {

            "mode":
                extraction.get(
                    "mode"
                ),

            "segments":
                extraction.get(
                    "segments",
                    []
                ),

            "raw_chunks":
                extraction.get(
                    "raw_chunks"
                ),

            "candidate_windows":
                extraction.get(
                    "candidate_windows"
                ),

            "valid_windows":
                extraction.get(
                    "valid_windows"
                ),

            "selected_chunks":
                extraction.get(
                    "selected_chunks"
                ),
        }

    return record


def create_unavailable_record(
    week_key,
    video,
    status,
    provider=None
):

    return {

        "week":
            week_key,

        "video_id":
            video.get("video_id"),

        "channel":
            video.get("channel"),

        "purpose":
            video.get("purpose"),

        "content_type":
            video.get("content_type"),

        "title":
            video.get("title"),

        "url":
            video.get("url"),

        "status":
            status,

        "provider":
            provider,

        "word_count":
            0,

        "character_count":
            0,

        "transcript":
            None,

        "updated_at":
            datetime.now(
                UTC
            ).isoformat(),
    }


# =============================================================================
# SAVE TRANSCRIPT RECORD
# =============================================================================

def save_transcript_file(
    record
):

    video = {

        "video_id":
            record.get("video_id"),

        "channel":
            record.get("channel"),
    }

    path = transcript_file_path(
        video
    )

    save_json(
        path,
        record
    )

    return path


# =============================================================================
# PRINT PRIMARY SOURCE
# =============================================================================

def print_source(
    index,
    video
):

    print(
        f"{index}. "
        f"{video.get('channel')} "
        f"| "
        f"{video.get('purpose')} "
        f"| "
        f"[{video.get('content_type')}]"
    )

    print(
        f"   {video.get('title')}"
    )

    print(
        f"   {video.get('url')}"
    )


# =============================================================================
# PROCESS DIGIT
# =============================================================================

def process_digit_strategy(
    week_key,
    video,
    track
):

    video_id = video.get(
        "video_id"
    )

    raw_text = (
        load_existing_raw_transcript(
            video
        )
    )

    provider = None
    api_status = None
    raw_path = None
    source_mode = None

    # -------------------------------------------------------------------------
    # 1. RAW CACHE
    # -------------------------------------------------------------------------

    if raw_text:

        print(
            "Raw cache        : FOUND"
        )

        print(
            f"Raw file         : "
            f"{raw_transcript_file_path(video)}"
        )

        provider = (
            "youtube-transcript.ai"
        )

        api_status = (
            "RAW_CACHE_REUSED"
        )

        raw_path = (
            raw_transcript_file_path(
                video
            )
        )

        source_mode = (
            "RAW_CACHE"
        )

    # -------------------------------------------------------------------------
    # 2. youtube-transcript.ai
    # -------------------------------------------------------------------------

    else:

        print(
            "Raw cache        : NOT FOUND"
        )

        print(
            "Provider         : "
            "youtube-transcript.ai"
        )

        result = (
            request_youtube_transcript_ai(
                video_id
            )
        )

        print(
            f"Provider status  : "
            f"{result.get('status')}"
        )

        if not result.get(
            "success"
        ):

            return (
                create_unavailable_record(
                    week_key,
                    video,
                    result.get(
                        "status",
                        "YTTAI_FAILED"
                    ),
                    provider=(
                        "youtube-transcript.ai"
                    )
                ),
                None
            )

        raw_text = result.get(
            "raw_text"
        )

        provider = (
            "youtube-transcript.ai"
        )

        api_status = result.get(
            "status"
        )

        raw_path = (
            save_raw_transcript(
                video,
                raw_text
            )
        )

        source_mode = (
            "DOWNLOADED"
        )

    # -------------------------------------------------------------------------
    # ANALYSE
    # -------------------------------------------------------------------------

    extraction = (
        extract_digit_strategy(
            raw_text,
            track
        )
    )

    print("")

    print_digit_candidates(
        extraction.get(
            "analysed",
            []
        ),
        limit=15
    )

    # -------------------------------------------------------------------------
    # V6.1 DIAGNOSTIC OUTPUT
    # -------------------------------------------------------------------------

    print_digit_diagnostic_windows(
        raw_text
    )

    print(
        "DIGIT STRATEGY EXTRACTION"
    )

    print(
        "-" * 96
    )

    print(
        f"Source mode      : "
        f"{source_mode}"
    )

    print(
        f"Extraction mode  : "
        f"{extraction.get('mode')}"
    )

    print(
        f"Raw chunks       : "
        f"{extraction.get('raw_chunks')}"
    )

    print(
        f"Candidate windows: "
        f"{extraction.get('candidate_windows')}"
    )

    print(
        f"Valid windows    : "
        f"{extraction.get('valid_windows')}"
    )

    print(
        f"Selected chunks  : "
        f"{extraction.get('selected_chunks')}"
    )

    print(
        f"Segments         : "
        f"{len(extraction.get('segments', []))}"
    )

    for index, segment in enumerate(
        extraction.get(
            "segments",
            []
        ),
        start=1
    ):

        print(
            f"  Segment {index}: "
            f"{segment.get('start')} "
            f"-> "
            f"{segment.get('end')} "
            f"| score "
            f"{segment.get('score')}"
        )

        for evidence in (
            segment.get(
                "evidence",
                []
            )[:3]
        ):

            print(
                "    Race     : "
                + ", ".join(
                    evidence.get(
                        "race_hits",
                        []
                    )
                )
            )

            print(
                "    Strategy : "
                + ", ".join(
                    evidence.get(
                        "strategy_hits",
                        []
                    )
                )
            )

    # -------------------------------------------------------------------------
    # STRICT FAILURE
    # -------------------------------------------------------------------------

    if not extraction.get(
        "success"
    ):

        print("")

        print(
            "No valid Digit Racing "
            "strategy segment found."
        )

        record = (
            create_unavailable_record(
                week_key,
                video,
                "NO_VALID_STRATEGY_SEGMENT",
                provider=provider
            )
        )

        record[
            "strategy_extraction"
        ] = {

            "mode":
                extraction.get(
                    "mode"
                ),

            "raw_chunks":
                extraction.get(
                    "raw_chunks"
                ),

            "candidate_windows":
                extraction.get(
                    "candidate_windows"
                ),

            "valid_windows":
                extraction.get(
                    "valid_windows"
                ),

            "selected_chunks":
                extraction.get(
                    "selected_chunks"
                ),
        }

        return (
            record,
            raw_path
        )

    # -------------------------------------------------------------------------
    # SUCCESS
    # -------------------------------------------------------------------------

    text = extraction.get(
        "text",
        ""
    )

    record = (
        create_available_record(
            week_key=week_key,
            video=video,
            provider=provider,
            text=text,
            api_status=api_status,
            extraction=extraction,
            raw_file=raw_path,
            cache_source=(
                str(raw_path)
                if source_mode
                == "RAW_CACHE"
                else None
            )
        )
    )

    print("")

    print(
        "STRATEGY TRANSCRIPT PREVIEW"
    )

    print(
        "-" * 96
    )

    print(
        text[:5000]
    )

    if len(text) > 5000:

        print(
            "[... preview truncated ...]"
        )

    print("")

    return (
        record,
        raw_path
    )


# =============================================================================
# PROCESS GNC
# =============================================================================

def process_gnc_lap_guide(
    week_key,
    video,
    database
):

    video_id = video.get(
        "video_id"
    )

    existing = (
        get_existing_record(
            database,
            video_id
        )
    )

    if (
        existing
        and existing.get("status")
        == "AVAILABLE"
        and existing.get("transcript")
    ):

        record = dict(
            existing
        )

        record["purpose"] = (
            "LAP_GUIDE"
        )

        record["channel"] = (
            LAP_GUIDE_CHANNEL
        )

        record["provider"] = (
            record.get("provider")
            or "LOCAL_DATABASE"
        )

        print(
            "Result           : "
            "REUSED_DATABASE"
        )

        return record

    legacy = (
        find_legacy_transcript(
            video_id
        )
    )

    if legacy:

        text = (
            dedupe_consecutive_words(
                legacy["text"]
            )
        )

        print(
            "Result           : "
            "REUSED_LEGACY_CACHE"
        )

        print(
            f"Legacy source    : "
            f"{legacy['source']}"
        )

        return (
            create_available_record(
                week_key=week_key,
                video=video,
                provider="LEGACY_CACHE",
                text=text,
                api_status="LEGACY_CACHE",
                cache_source=(
                    legacy["source"]
                )
            )
        )

    print(
        "Supadata         : REQUESTING"
    )

    result = (
        request_supadata_transcript(
            video.get("url")
        )
    )

    print(
        f"Supadata status  : "
        f"{result.get('status')}"
    )

    if not result.get(
        "success"
    ):

        print(
            "Fallback         : "
            "youtube-transcript.ai"
        )

        result = (
            request_youtube_transcript_ai(
                video_id
            )
        )

        print(
            f"Fallback status  : "
            f"{result.get('status')}"
        )

    if not result.get(
        "success"
    ):

        return (
            create_unavailable_record(
                week_key,
                video,
                result.get(
                    "status",
                    "TRANSCRIPT_UNAVAILABLE"
                ),
                provider=result.get(
                    "provider"
                )
            )
        )

    raw_text = (
        result.get("raw_text")
        or result.get("text")
        or ""
    )

    text = (
        result.get("text")
        or dedupe_consecutive_words(
            raw_text
        )
    )

    raw_path = (
        save_raw_transcript(
            video,
            raw_text
        )
    )

    return (
        create_available_record(
            week_key=week_key,
            video=video,
            provider=result.get(
                "provider"
            ),
            text=text,
            api_status=result.get(
                "status"
            ),
            raw_file=raw_path
        )
    )


# =============================================================================
# MAIN
# =============================================================================

def main():

    TRANSCRIPT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    RAW_TRANSCRIPT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    source_database = (
        load_json(
            COMMUNITY_SOURCES_FILE
        )
    )

    if not source_database:

        raise RuntimeError(
            "data/community_sources.json "
            "not found or invalid."
        )

    week_key, week_data = (
        get_current_week(
            source_database
        )
    )

    selected_sources = (
        select_primary_sources(
            week_data
        )
    )

    database = (
        normalize_database(
            load_json(
                TRANSCRIPT_DB_FILE,
                {}
            )
        )
    )

    track = (
        week_data.get("track")
        or ""
    )

    race_class = (
        week_data.get(
            "race_class"
        )
    )

    print(
        "=" * 96
    )

    print(
        "GT7 COMMUNITY TRANSCRIPT COLLECTOR V6.1"
    )

    print(
        "=" * 96
    )

    print(
        f"Week             : "
        f"{week_key}"
    )

    print(
        f"Track            : "
        f"{track}"
    )

    print(
        f"Race class       : "
        f"{race_class}"
    )

    print(
        f"Selected sources : "
        f"{len(selected_sources)}"
    )

    print(
        "Strategy source  : "
        "Digit Racing"
    )

    print(
        "Lap guide source : "
        "GnC Racing"
    )

    print("")

    print(
        "PRIMARY SOURCES"
    )

    print(
        "-" * 96
    )

    for index, source in enumerate(
        selected_sources,
        start=1
    ):

        print_source(
            index,
            source
        )

    print("")

    run_records = []

    for index, video in enumerate(
        selected_sources,
        start=1
    ):

        print(
            "=" * 96
        )

        print(
            f"[{index}/"
            f"{len(selected_sources)}] "
            f"{video.get('channel')} "
            f"- "
            f"{video.get('purpose')}"
        )

        print(
            "=" * 96
        )

        print(
            f"Title            : "
            f"{video.get('title')}"
        )

        print(
            f"Video ID         : "
            f"{video.get('video_id')}"
        )

        print(
            f"URL              : "
            f"{video.get('url')}"
        )

        print("")

        if (
            video.get("purpose")
            == "STRATEGY"
            and video.get("channel")
            == STRATEGY_CHANNEL
        ):

            record, _ = (
                process_digit_strategy(
                    week_key,
                    video,
                    track
                )
            )

        elif (
            video.get("purpose")
            == "LAP_GUIDE"
            and video.get("channel")
            == LAP_GUIDE_CHANNEL
        ):

            record = (
                process_gnc_lap_guide(
                    week_key,
                    video,
                    database
                )
            )

        else:

            record = (
                create_unavailable_record(
                    week_key,
                    video,
                    "SOURCE_NOT_ALLOWED"
                )
            )

        database[
            "videos"
        ][
            video.get("video_id")
        ] = record

        run_records.append(
            record
        )

        transcript_path = (
            save_transcript_file(
                record
            )
        )

        print(
            f"Final status     : "
            f"{record.get('status')}"
        )

        print(
            f"Provider         : "
            f"{record.get('provider')}"
        )

        if (
            record.get("status")
            == "AVAILABLE"
        ):

            print(
                f"Words            : "
                f"{record.get('word_count', 0):,}"
            )

            print(
                f"Characters       : "
                f"{record.get('character_count', 0):,}"
            )

        print(
            f"Saved file       : "
            f"{transcript_path}"
        )

        print("")

    database[
        "version"
    ] = "6.1"

    database[
        "updated_at"
    ] = datetime.now(
        UTC
    ).isoformat()

    database[
        "current_week"
    ] = week_key

    database[
        "source_policy"
    ] = {

        "strategy":
            STRATEGY_CHANNEL,

        "lap_guide":
            LAP_GUIDE_CHANNEL,

        "digit_provider_order": [
            "RAW_CACHE",
            "youtube-transcript.ai",
        ],

        "lap_guide_provider_order": [
            "DATABASE_CACHE",
            "LEGACY_CACHE",
            "Supadata",
            "youtube-transcript.ai",
        ],

        "digit_extractor":
            "STRATEGY_ROLLING_WINDOWS_V6_1",

        "minimum_digit_score":
            DIGIT_MIN_SCORE,

        "minimum_strategy_hits":
            DIGIT_MIN_STRATEGY_HITS,

        "weak_fallback":
            False,
    }

    save_json(
        TRANSCRIPT_DB_FILE,
        database
    )

    strategy_record = None
    lap_record = None

    for record in run_records:

        if (
            record.get("purpose")
            == "STRATEGY"
        ):
            strategy_record = record

        if (
            record.get("purpose")
            == "LAP_GUIDE"
        ):
            lap_record = record

    strategy_ready = (
        strategy_record is not None
        and strategy_record.get("status")
        == "AVAILABLE"
    )

    lap_ready = (
        lap_record is not None
        and lap_record.get("status")
        == "AVAILABLE"
    )

    print(
        "=" * 96
    )

    print(
        "FINAL SUMMARY"
    )

    print(
        "=" * 96
    )

    print(
        f"Primary sources    : "
        f"{len(selected_sources)}"
    )

    print("")

    print(
        "PRIMARY TRANSCRIPT STATUS"
    )

    print(
        "-" * 96
    )

    if strategy_record:

        print(
            f"STRATEGY  : "
            f"{strategy_record.get('status')}"
        )

        print(
            f"  Channel : "
            f"{strategy_record.get('channel')}"
        )

        print(
            f"  Video   : "
            f"{strategy_record.get('title')}"
        )

        if strategy_ready:

            print(
                f"  Words   : "
                f"{strategy_record.get('word_count', 0):,}"
            )

            extraction = (
                strategy_record.get(
                    "strategy_extraction",
                    {}
                )
            )

            print(
                f"  Extract : "
                f"{extraction.get('mode')}"
            )

            print(
                f"  Segments: "
                f"{len(extraction.get('segments', []))}"
            )

    else:

        print(
            "STRATEGY  : NOT SELECTED"
        )

    if lap_record:

        print(
            f"LAP_GUIDE : "
            f"{lap_record.get('status')}"
        )

        print(
            f"  Channel : "
            f"{lap_record.get('channel')}"
        )

        print(
            f"  Video   : "
            f"{lap_record.get('title')}"
        )

        if lap_ready:

            print(
                f"  Words   : "
                f"{lap_record.get('word_count', 0):,}"
            )

            print(
                f"  Provider: "
                f"{lap_record.get('provider')}"
            )

    else:

        print(
            "LAP_GUIDE : NOT SELECTED"
        )

    print("")

    print(
        "COMMUNITY INTELLIGENCE READINESS"
    )

    print(
        "-" * 96
    )

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

    print("")

    print(
        f"Database file      : "
        f"{TRANSCRIPT_DB_FILE}"
    )

    print(
        f"Transcript dir     : "
        f"{TRANSCRIPT_DIR}"
    )

    print(
        f"Raw transcript dir : "
        f"{RAW_TRANSCRIPT_DIR}"
    )

    print(
        "=" * 96
    )


if __name__ == "__main__":
    main()