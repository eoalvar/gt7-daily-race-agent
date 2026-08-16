import json
import os
import re
import time
from datetime import datetime, UTC
from pathlib import Path

import requests


# ============================================================
# CONFIG
# ============================================================

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

SUPADATA_BASE_URL = "https://api.supadata.ai/v1"

SUPADATA_API_KEY = os.environ.get(
    "SUPADATA_API_KEY",
    ""
)

YOUTUBE_TRANSCRIPT_BASE_URL = (
    "https://youtube-transcript.ai/transcript"
)

REQUEST_TIMEOUT = 90

POLL_INTERVAL_SECONDS = 2
MAX_POLL_ATTEMPTS = 60


# ============================================================
# SOURCE POLICY
# ============================================================

STRATEGY_CHANNEL = "Digit Racing"
LAP_GUIDE_CHANNEL = "GnC Racing"


# ============================================================
# DIGIT EXTRACTION V5
#
# Important difference from V4:
#
# V4:
#   one mention of "Daily Race C" or "Grand Valley"
#   could create a large extraction window.
#
# V5:
#   evaluates rolling windows.
#
#   A valid strategy window needs BOTH:
#
#   1. race identity evidence
#   2. substantive race/strategy evidence
#
# This prevents introductory phrases such as
# "before we get into Daily Race C" from becoming strategy.
# ============================================================

DIGIT_WINDOW_SECONDS = 300
DIGIT_WINDOW_STEP_SECONDS = 60

DIGIT_CONTEXT_BEFORE_SECONDS = 90
DIGIT_CONTEXT_AFTER_SECONDS = 150

DIGIT_MAX_SEGMENTS = 3
DIGIT_MAX_TOTAL_SECONDS = 2400


RACE_IDENTITY_TERMS = {
    "daily race c": 14,
    "race c": 9,
    "grand valley": 12,
    "highway 1": 8,
    "highway one": 8,
    "group 4": 5,
    "gr.4": 5,
    "gr4": 5,
}


STRATEGY_TERMS = {
    "strategy": 7,

    "pit stop": 7,
    "pitstop": 7,
    "pit": 4,

    "mandatory": 6,

    "fuel": 5,
    "fuel map": 6,
    "consumption": 4,

    "tyre": 4,
    "tire": 4,
    "tyres": 4,
    "tires": 4,
    "wear": 4,

    "medium": 3,
    "soft": 3,
    "hard": 3,

    "racing medium": 5,
    "racing soft": 5,
    "racing hard": 5,

    "lap": 2,
    "laps": 2,

    "race pace": 5,
    "pace": 2,

    "stint": 5,

    "short shift": 5,
    "short-shift": 5,

    "undercut": 6,
    "overcut": 6,

    "save fuel": 5,
    "fuel saving": 5,

    "save tyres": 5,
    "save tires": 5,

    "slipstream": 3,
    "draft": 3,

    "overtake": 2,
    "overtaking": 2,

    "penalty": 2,
    "penalties": 2,

    "track limits": 4,

    "car choice": 5,
    "meta": 4,

    "citroen": 2,
    "genesis": 2,
    "g70": 2,
    "gtr": 2,
    "gt-r": 2,
    "silvia": 2,
}


INTRO_CHAT_TERMS = {
    "welcome back": 3,
    "hello everyone": 4,
    "hello to everyone": 4,
    "chat": 2,
    "subscribe": 2,
    "like the stream": 3,
    "copyright": 3,
    "theme song": 4,
    "pedal cam": 4,
    "suno": 5,
}


OTHER_RACE_TERMS = {
    "daily race a": 8,
    "race a": 5,

    "daily race b": 8,
    "race b": 5,

    "route x": 7,
    "special stage route x": 10,

    "fuji": 5,
}


# ============================================================
# BASIC HELPERS
# ============================================================

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

    text = (
        text
        or "unknown"
    ).lower()

    text = re.sub(
        r"[^a-z0-9]+",
        "_",
        text
    )

    return text.strip("_")


def timestamp_to_seconds(timestamp):

    if not timestamp:
        return None

    parts = timestamp.split(":")

    try:

        if len(parts) == 2:

            minutes = int(parts[0])
            seconds = int(parts[1])

            return (
                minutes * 60
                + seconds
            )

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

    hours = (
        total_seconds
        // 3600
    )

    minutes = (
        total_seconds
        % 3600
    ) // 60

    seconds = (
        total_seconds
        % 60
    )

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


# ============================================================
# GENERIC TRANSCRIPT EXTRACTION
# ============================================================

def transcript_text_from_payload(payload):

    if payload is None:
        return None

    if isinstance(payload, str):

        text = normalize_space(payload)

        return text if text else None

    if isinstance(payload, list):

        pieces = []

        for item in payload:

            if isinstance(item, str):

                text = normalize_space(item)

            elif isinstance(item, dict):

                text = normalize_space(
                    item.get("text")
                    or item.get("content")
                    or item.get("transcript")
                    or ""
                )

            else:

                text = ""

            if text:

                pieces.append(text)

        if pieces:

            return normalize_space(
                " ".join(pieces)
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

            text = normalize_space(value)

            if text:
                return text

    content = payload.get("content")

    text = transcript_text_from_payload(
        content
    )

    if text:
        return text

    for key in [
        "result",
        "payload",
        "data",
        "response",
    ]:

        nested = payload.get(key)

        text = transcript_text_from_payload(
            nested
        )

        if text:
            return text

    return None


# ============================================================
# DATABASE
# ============================================================

def normalize_database(database):

    if not isinstance(database, dict):

        database = {}

    database.setdefault(
        "version",
        5
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


# ============================================================
# CURRENT WEEK
# ============================================================

def get_current_week(source_database):

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


# ============================================================
# PRIMARY SOURCE SELECTION
# ============================================================

def select_primary_sources(week_data):

    selected = week_data.get(
        "selected_sources",
        {}
    )

    strategy = selected.get(
        "strategy_primary"
    )

    lap_guide = selected.get(
        "lap_guide_primary"
    )

    output = []

    if (
        strategy
        and strategy.get("channel")
        == STRATEGY_CHANNEL
    ):

        strategy = dict(strategy)

        strategy["purpose"] = (
            "STRATEGY"
        )

        output.append(strategy)

    if (
        lap_guide
        and lap_guide.get("channel")
        == LAP_GUIDE_CHANNEL
    ):

        lap_guide = dict(lap_guide)

        lap_guide["purpose"] = (
            "LAP_GUIDE"
        )

        output.append(lap_guide)

    return output


# ============================================================
# LEGACY CACHE
# ============================================================

def find_legacy_transcript(video_id):

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
                directory.glob(pattern)
            )

        for path in matches:

            if path.suffix.lower() == ".txt":

                try:

                    raw_text = (
                        path.read_text(
                            encoding="utf-8"
                        )
                    )

                except Exception:

                    continue

                text = normalize_space(
                    raw_text
                )

                if text:

                    return {
                        "text":
                            text,

                        "raw_text":
                            raw_text,

                        "source":
                            str(path),
                    }

            payload = load_json(path)

            if not payload:
                continue

            text = (
                transcript_text_from_payload(
                    payload
                )
            )

            if text:

                return {
                    "text":
                        text,

                    "raw_text":
                        text,

                    "source":
                        str(path),
                }

    return None


# ============================================================
# WORD DE-DUPLICATION
# ============================================================

def dedupe_consecutive_words(text):

    text = normalize_space(text)

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
                    + repeats
                    * size
                )

                end = (
                    start
                    + size
                )

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


# ============================================================
# YOUTUBE-TRANSCRIPT.AI MARKDOWN PARSER
# ============================================================

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

        match = pattern.match(line)

        if match:

            if current:

                current["text"] = (
                    normalize_space(
                        " ".join(
                            current[
                                "text_parts"
                            ]
                        )
                    )
                )

                current.pop(
                    "text_parts",
                    None
                )

                chunks.append(
                    current
                )

            timestamp = (
                match.group(1)
            )

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

        current["text"] = (
            normalize_space(
                " ".join(
                    current[
                        "text_parts"
                    ]
                )
            )
        )

        current.pop(
            "text_parts",
            None
        )

        chunks.append(current)

    return chunks


def clean_timestamp_chunks(chunks):

    cleaned = []

    previous_text = None

    for chunk in chunks:

        text = dedupe_consecutive_words(
            chunk.get(
                "text",
                ""
            )
        )

        text = normalize_space(text)

        if not text:
            continue

        compare = re.sub(
            r"[^a-z0-9]+",
            " ",
            text.lower()
        ).strip()

        if (
            previous_text
            and compare
            == previous_text
        ):

            continue

        previous_text = compare

        cleaned.append({
            "timestamp":
                chunk.get(
                    "timestamp"
                ),

            "seconds":
                chunk.get(
                    "seconds"
                ),

            "text":
                text,
        })

    return cleaned


# ============================================================
# TERM SCORING
# ============================================================

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


# ============================================================
# DIGIT WINDOW SCORING V5
# ============================================================

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

    text_lower = text.lower()

    track_bonus = 0

    if track:

        track_tokens = [
            token
            for token
            in re.findall(
                r"[a-z0-9]+",
                track.lower()
            )
            if len(token) >= 4
        ]

        matches = sum(
            1
            for token
            in track_tokens
            if token in text_lower
        )

        if matches >= 3:

            track_bonus = 8

        elif matches == 2:

            track_bonus = 5

        elif matches == 1:

            track_bonus = 2

    total_score = (
        race_score
        + strategy_score
        + track_bonus
        - intro_score
        - other_score
    )

    # --------------------------------------------------------
    # HARD VALIDATION
    #
    # A segment is not considered strategy merely because
    # "Daily Race C" is mentioned.
    #
    # It needs:
    #
    # - at least one strong race identity signal
    # - several actual race-related concepts
    # --------------------------------------------------------

    strong_race_identity = (
        "daily race c" in race_hits
        or "grand valley" in race_hits
        or (
            "race c" in race_hits
            and (
                "highway 1" in race_hits
                or "highway one" in race_hits
            )
        )
    )

    substantive_strategy = (
        len(strategy_hits) >= 3
        and strategy_score >= 8
    )

    valid = (
        strong_race_identity
        and substantive_strategy
        and total_score >= 15
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

        "intro_penalty":
            intro_score,

        "other_race_penalty":
            other_score,

        "track_bonus":
            track_bonus,

        "race_hits":
            race_hits,

        "strategy_hits":
            strategy_hits,

        "intro_hits":
            intro_hits,

        "other_hits":
            other_hits,
    }


# ============================================================
# BUILD ROLLING WINDOWS
# ============================================================

def build_digit_windows(chunks):

    if not chunks:
        return []

    valid_seconds = [
        chunk["seconds"]
        for chunk in chunks
        if chunk.get("seconds")
        is not None
    ]

    if not valid_seconds:
        return []

    max_seconds = max(
        valid_seconds
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

            text = " ".join(
                chunk["text"]
                for chunk
                in window_chunks
            )

            windows.append({
                "start":
                    start,

                "end":
                    end,

                "chunks":
                    window_chunks,

                "text":
                    normalize_space(text),
            })

        start += (
            DIGIT_WINDOW_STEP_SECONDS
        )

    return windows


# ============================================================
# MERGE WINDOWS
# ============================================================

def merge_strategy_windows(
    windows
):

    if not windows:
        return []

    windows = sorted(
        windows,
        key=lambda item:
            item["start"]
    )

    merged = []

    for window in windows:

        if not merged:

            merged.append(
                dict(window)
            )

            continue

        previous = merged[-1]

        if (
            window["start"]
            <= previous["end"]
        ):

            previous["end"] = max(
                previous["end"],
                window["end"]
            )

            previous["score"] = max(
                previous.get(
                    "score",
                    0
                ),
                window.get(
                    "score",
                    0
                )
            )

            previous.setdefault(
                "evidence",
                []
            )

            previous["evidence"].extend(
                window.get(
                    "evidence",
                    []
                )
            )

        else:

            merged.append(
                dict(window)
            )

    return merged


# ============================================================
# EXTRACT DIGIT STRATEGY V5
# ============================================================

def extract_digit_strategy_segment(
    raw_text,
    track
):

    chunks = (
        parse_timestamped_markdown(
            raw_text
        )
    )

    chunks = clean_timestamp_chunks(
        chunks
    )

    if not chunks:

        return {
            "text":
                dedupe_consecutive_words(
                    raw_text
                ),

            "mode":
                "FULL_TEXT_FALLBACK",

            "segments":
                [],

            "raw_chunks":
                0,

            "selected_chunks":
                0,

            "candidate_windows":
                0,

            "valid_windows":
                0,
        }

    windows = build_digit_windows(
        chunks
    )

    valid_windows = []

    diagnostics = []

    for window in windows:

        scoring = (
            score_digit_window(
                window["text"],
                track
            )
        )

        diagnostics.append({
            "start":
                seconds_to_timestamp(
                    window["start"]
                ),

            "end":
                seconds_to_timestamp(
                    window["end"]
                ),

            "score":
                scoring["score"],

            "valid":
                scoring["valid"],

            "race_hits":
                scoring["race_hits"],

            "strategy_hits":
                scoring[
                    "strategy_hits"
                ],
        })

        if not scoring["valid"]:
            continue

        valid_windows.append({
            "start":
                max(
                    0,
                    window["start"]
                    - DIGIT_CONTEXT_BEFORE_SECONDS
                ),

            "end":
                (
                    window["end"]
                    + DIGIT_CONTEXT_AFTER_SECONDS
                ),

            "score":
                scoring["score"],

            "evidence": [
                {
                    "race_hits":
                        scoring[
                            "race_hits"
                        ],

                    "strategy_hits":
                        scoring[
                            "strategy_hits"
                        ],

                    "score":
                        scoring[
                            "score"
                        ],
                }
            ],
        })

    # --------------------------------------------------------
    # Fallback when no window passes strict validation.
    #
    # We select the best window only if it still has:
    #   - strong race identity
    #   - at least 2 strategy concepts
    #
    # Otherwise we return no strategy segment instead of
    # pretending intro/chat is strategy.
    # --------------------------------------------------------

    if not valid_windows:

        scored_windows = []

        for window in windows:

            scoring = (
                score_digit_window(
                    window["text"],
                    track
                )
            )

            race_hits = (
                scoring["race_hits"]
            )

            strategy_hits = (
                scoring[
                    "strategy_hits"
                ]
            )

            strong_identity = (
                "daily race c"
                in race_hits
                or "grand valley"
                in race_hits
            )

            if (
                strong_identity
                and len(
                    strategy_hits
                ) >= 2
            ):

                scored_windows.append(
                    (
                        scoring[
                            "score"
                        ],
                        window,
                        scoring,
                    )
                )

        if scored_windows:

            scored_windows.sort(
                key=lambda item:
                    item[0],
                reverse=True
            )

            best_score, best_window, scoring = (
                scored_windows[0]
            )

            valid_windows.append({
                "start":
                    max(
                        0,
                        best_window[
                            "start"
                        ]
                        - DIGIT_CONTEXT_BEFORE_SECONDS
                    ),

                "end":
                    (
                        best_window[
                            "end"
                        ]
                        + DIGIT_CONTEXT_AFTER_SECONDS
                    ),

                "score":
                    best_score,

                "evidence": [
                    {
                        "race_hits":
                            scoring[
                                "race_hits"
                            ],

                        "strategy_hits":
                            scoring[
                                "strategy_hits"
                            ],

                        "score":
                            best_score,
                    }
                ],
            })

    merged = merge_strategy_windows(
        valid_windows
    )

    # Rank segments by score.
    ranked = sorted(
        merged,
        key=lambda item:
            item.get(
                "score",
                0
            ),
        reverse=True
    )

    selected_segments = []
    total_duration = 0

    for segment in ranked:

        duration = max(
            0,
            segment["end"]
            - segment["start"]
        )

        if (
            selected_segments
            and total_duration
            + duration
            > DIGIT_MAX_TOTAL_SECONDS
        ):

            continue

        selected_segments.append(
            segment
        )

        total_duration += duration

        if (
            len(selected_segments)
            >= DIGIT_MAX_SEGMENTS
        ):

            break

    selected_segments.sort(
        key=lambda item:
            item["start"]
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
                    chunk.get("text")
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

    output_lines = []

    for chunk in selected_chunks:

        output_lines.append(
            f"[{chunk['timestamp']}] "
            f"{chunk['text']}"
        )

    selected_text = "\n".join(
        output_lines
    ).strip()

    # Do NOT return whole 4-hour stream if no proper
    # strategy segment was found.
    if not selected_text:

        return {
            "text":
                "",

            "mode":
                "NO_STRATEGY_SEGMENT_FOUND",

            "segments":
                [],

            "raw_chunks":
                len(chunks),

            "selected_chunks":
                0,

            "candidate_windows":
                len(windows),

            "valid_windows":
                0,

            "diagnostics":
                sorted(
                    diagnostics,
                    key=lambda item:
                        item["score"],
                    reverse=True
                )[:10],
        }

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
                segment.get(
                    "score",
                    0
                ),

            "evidence":
                segment.get(
                    "evidence",
                    []
                ),
        })

    return {
        "text":
            selected_text,

        "mode":
            "STRATEGY_ROLLING_WINDOWS_V5",

        "segments":
            segment_metadata,

        "raw_chunks":
            len(chunks),

        "selected_chunks":
            len(selected_chunks),

        "candidate_windows":
            len(windows),

        "valid_windows":
            len(valid_windows),

        "diagnostics":
            sorted(
                diagnostics,
                key=lambda item:
                    item["score"],
                reverse=True
            )[:10],
    }


# ============================================================
# YOUTUBE-TRANSCRIPT.AI
# ============================================================

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
                raw_text[:3000],
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
        "error fetching",
        "failed to fetch",
    ]

    detected_errors = [
        indicator
        for indicator
        in error_indicators
        if indicator in lower
    ]

    if detected_errors:

        return {
            "success":
                False,

            "status":
                "YTTAI_PROVIDER_ERROR",

            "provider":
                "youtube-transcript.ai",

            "http_status":
                http_status,

            "errors":
                detected_errors,

            "payload":
                raw_text[:3000],
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


# ============================================================
# SUPADATA
# ============================================================

def supadata_headers():

    return {
        "x-api-key":
            SUPADATA_API_KEY,

        "Accept":
            "application/json",
    }


def poll_supadata_job(job_id):

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

                "job_id":
                    job_id,

                "error":
                    str(exc),
            }

        http_status = (
            response.status_code
        )

        try:

            payload = response.json()

        except Exception:

            payload = {
                "raw":
                    response.text[:2000]
            }

        if http_status == 429:

            return {
                "success":
                    False,

                "status":
                    "SUPADATA_PLAN_LIMIT",

                "provider":
                    "Supadata",

                "job_id":
                    job_id,

                "http_status":
                    http_status,

                "payload":
                    payload,
            }

        if http_status != 200:

            return {
                "success":
                    False,

                "status":
                    f"SUPADATA_HTTP_{http_status}",

                "provider":
                    "Supadata",

                "job_id":
                    job_id,

                "http_status":
                    http_status,

                "payload":
                    payload,
            }

        text = (
            transcript_text_from_payload(
                payload
            )
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

                "job_id":
                    job_id,

                "http_status":
                    http_status,

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

                "job_id":
                    job_id,

                "http_status":
                    http_status,

                "payload":
                    payload,
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

        "job_id":
            job_id,
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
        f"{SUPADATA_BASE_URL}/transcript"
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

    http_status = (
        response.status_code
    )

    try:

        payload = response.json()

    except Exception:

        payload = {
            "raw":
                response.text[:2000]
        }

    if http_status == 200:

        text = (
            transcript_text_from_payload(
                payload
            )
        )

        if text:

            return {
                "success":
                    True,

                "status":
                    "SUPADATA_IMMEDIATE_SUCCESS",

                "provider":
                    "Supadata",

                "delivery_mode":
                    "IMMEDIATE",

                "http_status":
                    http_status,

                "text":
                    text,

                "raw_text":
                    text,
            }

        return {
            "success":
                False,

            "status":
                "SUPADATA_NO_CONTENT",

            "provider":
                "Supadata",

            "http_status":
                http_status,

            "payload":
                payload,
        }

    if http_status == 202:

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

                "http_status":
                    http_status,

                "payload":
                    payload,
            }

        return poll_supadata_job(
            job_id
        )

    if http_status == 429:

        return {
            "success":
                False,

            "status":
                "SUPADATA_PLAN_LIMIT",

            "provider":
                "Supadata",

            "http_status":
                http_status,

            "payload":
                payload,
        }

    return {
        "success":
            False,

        "status":
            f"SUPADATA_HTTP_{http_status}",

        "provider":
            "Supadata",

        "http_status":
            http_status,

        "payload":
            payload,
    }


# ============================================================
# PROVIDER RESULT PROCESSING
# ============================================================

def process_provider_result(
    video,
    result,
    track
):

    if not result.get("success"):
        return result

    raw_text = (
        result.get("raw_text")
        or result.get("text")
        or ""
    )

    channel = video.get("channel")
    purpose = video.get("purpose")

    if (
        channel == STRATEGY_CHANNEL
        and purpose == "STRATEGY"
        and result.get("provider")
        == "youtube-transcript.ai"
    ):

        extracted = (
            extract_digit_strategy_segment(
                raw_text,
                track
            )
        )

        result["text"] = (
            extracted["text"]
        )

        result["extraction"] = (
            extracted
        )

        if not extracted["text"]:

            result["success"] = False

            result["status"] = (
                "YTTAI_NO_VALID_STRATEGY_SEGMENT"
            )

    else:

        result["text"] = (
            dedupe_consecutive_words(
                result.get("text")
                or raw_text
            )
        )

    return result


# ============================================================
# RECORDS
# ============================================================

def create_available_record(
    week_key,
    video,
    result,
    cache_source=None
):

    text = (
        result.get("text", "")
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
            result.get("provider"),

        "api_status":
            result.get("status"),

        "delivery_mode":
            result.get(
                "delivery_mode"
            ),

        "http_status":
            result.get(
                "http_status"
            ),

        "job_id":
            result.get("job_id"),

        "cache_source":
            cache_source,

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

    extraction = result.get(
        "extraction"
    )

    if extraction:

        record[
            "strategy_extraction"
        ] = {
            "mode":
                extraction.get("mode"),

            "segments":
                extraction.get(
                    "segments",
                    []
                ),

            "raw_chunks":
                extraction.get(
                    "raw_chunks"
                ),

            "selected_chunks":
                extraction.get(
                    "selected_chunks"
                ),

            "candidate_windows":
                extraction.get(
                    "candidate_windows"
                ),

            "valid_windows":
                extraction.get(
                    "valid_windows"
                ),

            "diagnostics":
                extraction.get(
                    "diagnostics",
                    []
                ),
        }

    return record


def create_unavailable_record(
    week_key,
    video,
    result
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
            result.get(
                "status",
                "UNAVAILABLE"
            ),

        "provider":
            result.get("provider"),

        "api_status":
            result.get("status"),

        "delivery_mode":
            result.get(
                "delivery_mode"
            ),

        "http_status":
            result.get(
                "http_status"
            ),

        "job_id":
            result.get("job_id"),

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


# ============================================================
# SAVE FILES
# ============================================================

def save_transcript_file(record):

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


# ============================================================
# EXISTING RAW CACHE
# ============================================================

def load_existing_raw_transcript(
    video
):

    path = raw_transcript_file_path(
        video
    )

    if not path.exists():
        return None

    try:

        text = path.read_text(
            encoding="utf-8"
        )

    except Exception:

        return None

    if not text.strip():
        return None

    return text


# ============================================================
# DISPLAY
# ============================================================

def print_source(
    index,
    video
):

    print(
        f"{index}. "
        f"{video.get('channel')} "
        f"| {video.get('purpose')} "
        f"| [{video.get('content_type')}]"
    )

    print(
        f"   {video.get('title')}"
    )

    print(
        f"   {video.get('url')}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    TRANSCRIPT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    RAW_TRANSCRIPT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    source_database = load_json(
        COMMUNITY_SOURCES_FILE
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

    selected = (
        select_primary_sources(
            week_data
        )
    )

    transcript_database = (
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

    print(
        "=" * 96
    )

    print(
        "GT7 COMMUNITY TRANSCRIPT COLLECTOR V5"
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
        f"{week_data.get('race_class')}"
    )

    print(
        f"Selected sources : "
        f"{len(selected)}"
    )

    print(
        "Provider order   : "
        "LOCAL CACHE -> "
        "RAW CACHE -> "
        "SUPADATA -> "
        "youtube-transcript.ai"
    )

    print("")

    print(
        "PRIMARY SOURCES"
    )

    print(
        "-" * 96
    )

    if not selected:

        print(
            "No primary community "
            "sources selected."
        )

    else:

        for index, video in enumerate(
            selected,
            start=1
        ):

            print_source(
                index,
                video
            )

    print("")

    available_count = 0
    unavailable_count = 0

    reused_database_count = 0
    reused_raw_count = 0
    reused_legacy_count = 0

    supadata_requests = 0
    yttai_requests = 0

    supadata_plan_limit = False

    run_results = []

    for index, video in enumerate(
        selected,
        start=1
    ):

        video_id = video.get(
            "video_id"
        )

        print(
            "=" * 96
        )

        print(
            f"[{index}/{len(selected)}] "
            f"{video.get('channel')} "
            f"- {video.get('purpose')}"
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
            f"{video_id}"
        )

        print(
            f"URL              : "
            f"{video.get('url')}"
        )

        # ====================================================
        # IMPORTANT:
        #
        # Digit's V4 database record should NOT simply be reused
        # because its extraction algorithm was wrong.
        #
        # If the raw transcript exists, V5 reprocesses it locally.
        #
        # GnC and all non-Digit records can continue using
        # the existing database normally.
        # ====================================================

        is_digit_strategy = (
            video.get("channel")
            == STRATEGY_CHANNEL
            and video.get("purpose")
            == "STRATEGY"
        )

        existing = (
            get_existing_record(
                transcript_database,
                video_id
            )
        )

        if (
            not is_digit_strategy
            and existing
            and existing.get("status")
            == "AVAILABLE"
            and existing.get("transcript")
        ):

            record = dict(existing)

            record["purpose"] = (
                video.get("purpose")
            )

            record["content_type"] = (
                video.get("content_type")
            )

            transcript_database[
                "videos"
            ][video_id] = record

            path = save_transcript_file(
                record
            )

            print(
                "Result           : "
                "REUSED_DATABASE"
            )

            print(
                "Transcript       : YES"
            )

            print(
                f"Words            : "
                f"{record.get('word_count', 0):,}"
            )

            print(
                f"Provider         : "
                f"{record.get('provider')}"
            )

            print(
                f"Saved file       : "
                f"{path}"
            )

            available_count += 1

            reused_database_count += 1

            run_results.append(
                record
            )

            print("")

            continue

        # ====================================================
        # DIGIT RAW CACHE REPROCESSING
        # ====================================================

        if is_digit_strategy:

            raw_cached = (
                load_existing_raw_transcript(
                    video
                )
            )

            if raw_cached:

                print(
                    "Result           : "
                    "REPROCESSING_RAW_CACHE"
                )

                print(
                    f"Raw cache        : "
                    f"{raw_transcript_file_path(video)}"
                )

                local_result = {
                    "success":
                        True,

                    "status":
                        "RAW_CACHE_REPROCESSED_V5",

                    "provider":
                        "youtube-transcript.ai",

                    "delivery_mode":
                        "LOCAL_RAW_CACHE",

                    "raw_text":
                        raw_cached,
                }

                local_result = (
                    process_provider_result(
                        video,
                        local_result,
                        track
                    )
                )

                if local_result.get(
                    "success"
                ):

                    record = (
                        create_available_record(
                            week_key,
                            video,
                            local_result,
                            cache_source=str(
                                raw_transcript_file_path(
                                    video
                                )
                            )
                        )
                    )

                    transcript_database[
                        "videos"
                    ][video_id] = (
                        record
                    )

                    path = (
                        save_transcript_file(
                            record
                        )
                    )

                    extraction = (
                        record.get(
                            "strategy_extraction",
                            {}
                        )
                    )

                    print(
                        "Transcript       : YES"
                    )

                    print(
                        "Provider         : "
                        "youtube-transcript.ai "
                        "(RAW CACHE)"
                    )

                    print(
                        f"Words            : "
                        f"{record.get('word_count', 0):,}"
                    )

                    print(
                        f"Characters       : "
                        f"{record.get('character_count', 0):,}"
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

                    for number, segment in enumerate(
                        extraction.get(
                            "segments",
                            []
                        ),
                        start=1
                    ):

                        print(
                            f"  Segment {number}: "
                            f"{segment.get('start')} "
                            f"-> "
                            f"{segment.get('end')} "
                            f"| score "
                            f"{segment.get('score')}"
                        )

                        evidence = (
                            segment.get(
                                "evidence",
                                []
                            )
                        )

                        for item in evidence[:2]:

                            print(
                                "    Race     : "
                                + ", ".join(
                                    item.get(
                                        "race_hits",
                                        []
                                    )
                                )
                            )

                            print(
                                "    Strategy : "
                                + ", ".join(
                                    item.get(
                                        "strategy_hits",
                                        []
                                    )
                                )
                            )

                    print(
                        f"Saved file       : "
                        f"{path}"
                    )

                    print("")

                    print(
                        "TRANSCRIPT PREVIEW"
                    )

                    print(
                        "-" * 96
                    )

                    preview = (
                        record.get(
                            "transcript",
                            ""
                        )
                    )

                    print(
                        preview[:3500]
                    )

                    if len(preview) > 3500:

                        print(
                            "[... preview truncated ...]"
                        )

                    print("")

                    available_count += 1
                    reused_raw_count += 1

                    run_results.append(
                        record
                    )

                    continue

                else:

                    extraction = (
                        local_result.get(
                            "extraction",
                            {}
                        )
                    )

                    print(
                        "Raw cache result : "
                        "NO VALID STRATEGY "
                        "SEGMENT"
                    )

                    print(
                        f"Candidate windows: "
                        f"{extraction.get('candidate_windows')}"
                    )

                    print(
                        f"Valid windows    : "
                        f"{extraction.get('valid_windows')}"
                    )

                    print("")

                    print(
                        "TOP WINDOW DIAGNOSTICS"
                    )

                    print(
                        "-" * 96
                    )

                    for diagnostic in (
                        extraction.get(
                            "diagnostics",
                            []
                        )[:8]
                    ):

                        print(
                            f"{diagnostic.get('start')} "
                            f"-> "
                            f"{diagnostic.get('end')} "
                            f"| score "
                            f"{diagnostic.get('score')} "
                            f"| valid "
                            f"{diagnostic.get('valid')}"
                        )

                        print(
                            "  Race     : "
                            + ", ".join(
                                diagnostic.get(
                                    "race_hits",
                                    []
                                )
                            )
                        )

                        print(
                            "  Strategy : "
                            + ", ".join(
                                diagnostic.get(
                                    "strategy_hits",
                                    []
                                )
                            )
                        )

                    print("")

        # ====================================================
        # LEGACY CACHE
        # ====================================================

        if not is_digit_strategy:

            legacy = find_legacy_transcript(
                video_id
            )

            if legacy:

                legacy_result = {
                    "success":
                        True,

                    "status":
                        "LEGACY_CACHE",

                    "provider":
                        "LOCAL_CACHE",

                    "delivery_mode":
                        "LOCAL_CACHE",

                    "text":
                        legacy.get("text"),

                    "raw_text":
                        (
                            legacy.get(
                                "raw_text"
                            )
                            or legacy.get("text")
                        ),
                }

                legacy_result = (
                    process_provider_result(
                        video,
                        legacy_result,
                        track
                    )
                )

                record = (
                    create_available_record(
                        week_key=week_key,
                        video=video,
                        result=legacy_result,
                        cache_source=legacy[
                            "source"
                        ]
                    )
                )

                transcript_database[
                    "videos"
                ][video_id] = (
                    record
                )

                path = (
                    save_transcript_file(
                        record
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

                print(
                    "Transcript       : YES"
                )

                print(
                    f"Words            : "
                    f"{record.get('word_count', 0):,}"
                )

                print(
                    f"Saved file       : "
                    f"{path}"
                )

                available_count += 1
                reused_legacy_count += 1

                run_results.append(
                    record
                )

                print("")

                continue

        # ====================================================
        # SUPADATA
        # ====================================================

        provider_result = None

        if not supadata_plan_limit:

            print(
                "Supadata         : REQUESTING"
            )

            provider_result = (
                request_supadata_transcript(
                    video.get("url")
                )
            )

            if (
                provider_result.get(
                    "status"
                )
                != "SUPADATA_API_KEY_MISSING"
            ):

                supadata_requests += 1

            print(
                f"Supadata status  : "
                f"{provider_result.get('status')}"
            )

            if (
                provider_result.get(
                    "status"
                )
                == "SUPADATA_PLAN_LIMIT"
            ):

                supadata_plan_limit = True

                print(
                    "Supadata quota exhausted. "
                    "Fallback will be used."
                )

        else:

            provider_result = {
                "success":
                    False,

                "status":
                    "SUPADATA_PLAN_LIMIT_SKIPPED",

                "provider":
                    "Supadata",
            }

            print(
                "Supadata         : "
                "SKIPPED - "
                "plan limit already known"
            )

        # ====================================================
        # YOUTUBE-TRANSCRIPT.AI FALLBACK
        # ====================================================

        if not provider_result.get(
            "success"
        ):

            print(
                "Fallback         : "
                "youtube-transcript.ai"
            )

            provider_result = (
                request_youtube_transcript_ai(
                    video_id
                )
            )

            yttai_requests += 1

            print(
                f"Fallback status  : "
                f"{provider_result.get('status')}"
            )

        # ====================================================
        # SUCCESS
        # ====================================================

        if provider_result.get(
            "success"
        ):

            raw_text = (
                provider_result.get(
                    "raw_text"
                )
                or provider_result.get(
                    "text"
                )
            )

            raw_path = save_raw_transcript(
                video,
                raw_text
            )

            provider_result = (
                process_provider_result(
                    video,
                    provider_result,
                    track
                )
            )

        if provider_result.get(
            "success"
        ):

            record = (
                create_available_record(
                    week_key=week_key,
                    video=video,
                    result=provider_result
                )
            )

            if raw_path:

                record[
                    "raw_transcript_file"
                ] = str(raw_path)

            transcript_database[
                "videos"
            ][video_id] = record

            run_results.append(record)

            available_count += 1

            path = save_transcript_file(
                record
            )

            print(
                "Transcript       : YES"
            )

            print(
                f"Provider         : "
                f"{record.get('provider')}"
            )

            print(
                f"Words            : "
                f"{record.get('word_count', 0):,}"
            )

            print(
                f"Characters       : "
                f"{record.get('character_count', 0):,}"
            )

            if raw_path:

                print(
                    f"Raw file         : "
                    f"{raw_path}"
                )

            print(
                f"Saved file       : "
                f"{path}"
            )

            extraction = (
                record.get(
                    "strategy_extraction"
                )
            )

            if extraction:

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

                for number, segment in enumerate(
                    extraction.get(
                        "segments",
                        []
                    ),
                    start=1
                ):

                    print(
                        f"  Segment {number}: "
                        f"{segment.get('start')} "
                        f"-> "
                        f"{segment.get('end')} "
                        f"| score "
                        f"{segment.get('score')}"
                    )

            print("")

            print(
                "TRANSCRIPT PREVIEW"
            )

            print(
                "-" * 96
            )

            preview = (
                record.get(
                    "transcript"
                )
                or ""
            )

            print(
                preview[:3500]
            )

            if len(preview) > 3500:

                print(
                    "[... preview truncated ...]"
                )

        # ====================================================
        # FAILURE
        # ====================================================

        else:

            record = (
                create_unavailable_record(
                    week_key,
                    video,
                    provider_result
                )
            )

            transcript_database[
                "videos"
            ][video_id] = record

            run_results.append(record)

            unavailable_count += 1

            print(
                "Transcript       : NO"
            )

            print(
                f"Final status     : "
                f"{record.get('status')}"
            )

            print(
                f"Provider         : "
                f"{record.get('provider')}"
            )

        print("")

    # ========================================================
    # SAVE DATABASE
    # ========================================================

    transcript_database[
        "version"
    ] = 5

    transcript_database[
        "updated_at"
    ] = datetime.now(
        UTC
    ).isoformat()

    transcript_database[
        "current_week"
    ] = week_key

    transcript_database[
        "source_policy"
    ] = {
        "strategy":
            STRATEGY_CHANNEL,

        "lap_guide":
            LAP_GUIDE_CHANNEL,

        "provider_order": [
            "LOCAL_CACHE",
            "RAW_CACHE",
            "Supadata",
            "youtube-transcript.ai",
        ],

        "digit_extractor":
            "ROLLING_WINDOWS_V5",
    }

    save_json(
        TRANSCRIPT_DB_FILE,
        transcript_database
    )

    # ========================================================
    # SUMMARY
    # ========================================================

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
        f"{len(selected)}"
    )

    print(
        f"Transcripts ready  : "
        f"{available_count}"
    )

    print(
        f"Reused database    : "
        f"{reused_database_count}"
    )

    print(
        f"Reprocessed raw    : "
        f"{reused_raw_count}"
    )

    print(
        f"Reused legacy      : "
        f"{reused_legacy_count}"
    )

    print(
        f"Unavailable        : "
        f"{unavailable_count}"
    )

    print(
        f"Supadata requests  : "
        f"{supadata_requests}"
    )

    print(
        f"YTTAI requests     : "
        f"{yttai_requests}"
    )

    print(
        f"Supadata limit     : "
        f"{'YES' if supadata_plan_limit else 'No'}"
    )

    print("")

    print(
        "PRIMARY TRANSCRIPT STATUS"
    )

    print(
        "-" * 96
    )

    purposes = {
        "STRATEGY":
            None,

        "LAP_GUIDE":
            None,
    }

    for record in run_results:

        purpose = record.get(
            "purpose"
        )

        if purpose in purposes:

            purposes[purpose] = (
                record
            )

    for purpose in [
        "STRATEGY",
        "LAP_GUIDE",
    ]:

        record = purposes.get(
            purpose
        )

        if not record:

            print(
                f"{purpose:<10}: "
                "NOT SELECTED"
            )

            continue

        print(
            f"{purpose:<10}: "
            f"{record.get('status')}"
        )

        print(
            f"  Channel : "
            f"{record.get('channel')}"
        )

        print(
            f"  Video   : "
            f"{record.get('title')}"
        )

        if (
            record.get("status")
            == "AVAILABLE"
        ):

            print(
                f"  Words   : "
                f"{record.get('word_count', 0):,}"
            )

            print(
                f"  Provider: "
                f"{record.get('provider')}"
            )

            extraction = record.get(
                "strategy_extraction"
            )

            if extraction:

                print(
                    f"  Extract : "
                    f"{extraction.get('mode')}"
                )

                print(
                    f"  Segments: "
                    f"{len(extraction.get('segments', []))}"
                )

    print("")

    strategy_ready = (
        purposes.get("STRATEGY")
        is not None
        and purposes[
            "STRATEGY"
        ].get("status")
        == "AVAILABLE"
    )

    lap_ready = (
        purposes.get("LAP_GUIDE")
        is not None
        and purposes[
            "LAP_GUIDE"
        ].get("status")
        == "AVAILABLE"
    )

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