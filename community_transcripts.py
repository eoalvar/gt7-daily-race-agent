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

COMMUNITY_SOURCES_FILE = (
    DATA_DIR
    / "community_sources.json"
)

TRANSCRIPT_DB_FILE = (
    DATA_DIR
    / "community_transcripts.json"
)

TRANSCRIPT_DIR = (
    DATA_DIR
    / "community_transcripts"
)

RAW_TRANSCRIPT_DIR = (
    DATA_DIR
    / "community_transcripts_raw"
)

LEGACY_TRANSCRIPT_DIRS = [
    DATA_DIR
    / "community_supadata_test"
    / "transcripts",

    DATA_DIR
    / "community_transcript_test"
    / "transcripts",

    DATA_DIR
    / "community_youtube_transcript_test",
]

SUPADATA_BASE_URL = (
    "https://api.supadata.ai/v1"
)

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
# DIGIT STRATEGY EXTRACTION CONFIG
# ============================================================

DIGIT_CONTEXT_BEFORE_SECONDS = 180
DIGIT_CONTEXT_AFTER_SECONDS = 420

DIGIT_MAX_SEGMENTS = 4
DIGIT_MAX_TOTAL_SECONDS = 3600

DIGIT_STRONG_KEYWORDS = [
    "daily race c",
    "race c",
    "grand valley",
    "highway 1",
    "highway one",
]

DIGIT_STRATEGY_KEYWORDS = [
    "strategy",
    "pit",
    "pit stop",
    "pitstop",
    "fuel",
    "tyre",
    "tire",
    "medium",
    "soft",
    "hard",
    "racing medium",
    "racing soft",
    "racing hard",
    "mandatory",
    "lap",
    "laps",
    "fuel map",
    "short shift",
    "short-shift",
    "undercut",
    "overcut",
    "stint",
    "wear",
    "consumption",
    "race pace",
    "slipstream",
    "draft",
    "overtake",
    "overtaking",
    "brake",
    "braking",
    "track limits",
    "penalty",
    "penalties",
]


# ============================================================
# BASIC HELPERS
# ============================================================

def load_json(
    path,
    default=None
):

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


def save_json(
    path,
    data
):

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


def normalize_space(
    text
):

    return re.sub(
        r"\s+",
        " ",
        text or ""
    ).strip()


def safe_filename(
    text
):

    text = (
        text
        or "unknown"
    ).lower()

    text = re.sub(
        r"[^a-z0-9]+",
        "_",
        text
    )

    return text.strip(
        "_"
    )


def timestamp_to_seconds(
    timestamp
):

    if not timestamp:
        return None

    parts = timestamp.split(
        ":"
    )

    try:

        if len(parts) == 2:

            minutes = int(
                parts[0]
            )

            seconds = int(
                parts[1]
            )

            return (
                minutes * 60
                + seconds
            )

        if len(parts) == 3:

            hours = int(
                parts[0]
            )

            minutes = int(
                parts[1]
            )

            seconds = int(
                parts[2]
            )

            return (
                hours * 3600
                + minutes * 60
                + seconds
            )

    except Exception:

        return None

    return None


def seconds_to_timestamp(
    total_seconds
):

    total_seconds = max(
        0,
        int(
            total_seconds
        )
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
# TRANSCRIPT TEXT EXTRACTION
# ============================================================

def transcript_text_from_payload(
    payload
):

    if payload is None:
        return None

    if isinstance(
        payload,
        str
    ):

        text = normalize_space(
            payload
        )

        return (
            text
            if text
            else None
        )

    if isinstance(
        payload,
        list
    ):

        pieces = []

        for item in payload:

            if isinstance(
                item,
                str
            ):

                text = normalize_space(
                    item
                )

            elif isinstance(
                item,
                dict
            ):

                text = normalize_space(
                    item.get(
                        "text"
                    )
                    or item.get(
                        "content"
                    )
                    or item.get(
                        "transcript"
                    )
                    or ""
                )

            else:

                text = ""

            if text:

                pieces.append(
                    text
                )

        if pieces:

            return normalize_space(
                " ".join(
                    pieces
                )
            )

        return None

    if not isinstance(
        payload,
        dict
    ):

        return None

    for key in [
        "transcript",
        "text",
    ]:

        value = payload.get(
            key
        )

        if isinstance(
            value,
            str
        ):

            text = normalize_space(
                value
            )

            if text:
                return text

    content = payload.get(
        "content"
    )

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

        nested = payload.get(
            key
        )

        text = transcript_text_from_payload(
            nested
        )

        if text:
            return text

    return None


# ============================================================
# TRANSCRIPT DATABASE
# ============================================================

def normalize_database(
    database
):

    if not isinstance(
        database,
        dict
    ):

        database = {}

    database.setdefault(
        "version",
        4
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
        .get(
            "videos",
            {}
        )
        .get(
            video_id
        )
    )


def transcript_file_path(
    video
):

    video_id = (
        video.get(
            "video_id"
        )
        or "unknown"
    )

    channel = safe_filename(
        video.get(
            "channel"
        )
    )

    return (
        TRANSCRIPT_DIR
        / f"{video_id}_{channel}.json"
    )


def raw_transcript_file_path(
    video
):

    video_id = (
        video.get(
            "video_id"
        )
        or "unknown"
    )

    channel = safe_filename(
        video.get(
            "channel"
        )
    )

    return (
        RAW_TRANSCRIPT_DIR
        / f"{video_id}_{channel}.txt"
    )


# ============================================================
# CURRENT WEEK
# ============================================================

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

    week_key = week_keys[
        -1
    ]

    return (
        week_key,
        weeks[
            week_key
        ]
    )


# ============================================================
# SOURCE SELECTION
# ============================================================

def select_primary_sources(
    week_data
):

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

    if strategy:

        if (
            strategy.get(
                "channel"
            )
            == STRATEGY_CHANNEL
        ):

            strategy = dict(
                strategy
            )

            strategy[
                "purpose"
            ] = "STRATEGY"

            output.append(
                strategy
            )

    if lap_guide:

        if (
            lap_guide.get(
                "channel"
            )
            == LAP_GUIDE_CHANNEL
        ):

            lap_guide = dict(
                lap_guide
            )

            lap_guide[
                "purpose"
            ] = "LAP_GUIDE"

            output.append(
                lap_guide
            )

    return output


# ============================================================
# LEGACY TRANSCRIPT CACHE
# ============================================================

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

                    text = path.read_text(
                        encoding="utf-8"
                    )

                except Exception:

                    continue

                text = normalize_space(
                    text
                )

                if text:

                    return {
                        "text":
                            text,

                        "raw_text":
                            path.read_text(
                                encoding="utf-8"
                            ),

                        "source":
                            str(
                                path
                            )
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
                    "text":
                        text,

                    "raw_text":
                        text,

                    "source":
                        str(
                            path
                        )
                }

    broader_dirs = [
        DATA_DIR
        / "community_supadata_test",

        DATA_DIR
        / "community_transcript_test",

        DATA_DIR
        / "community_youtube_transcript_test",
    ]

    for directory in broader_dirs:

        if not directory.exists():
            continue

        for path in directory.rglob(
            "*.json"
        ):

            try:

                raw_text = path.read_text(
                    encoding="utf-8"
                )

            except Exception:

                continue

            if video_id not in raw_text:

                continue

            try:

                payload = json.loads(
                    raw_text
                )

            except Exception:

                continue

            if isinstance(
                payload,
                list
            ):

                candidates = payload

            elif isinstance(
                payload,
                dict
            ):

                candidates = []

                for key in [
                    "results",
                    "videos",
                    "items",
                ]:

                    value = payload.get(
                        key
                    )

                    if isinstance(
                        value,
                        list
                    ):

                        candidates.extend(
                            value
                        )

                    elif isinstance(
                        value,
                        dict
                    ):

                        candidates.extend(
                            value.values()
                        )

            else:

                candidates = []

            for item in candidates:

                if not isinstance(
                    item,
                    dict
                ):

                    continue

                item_video_id = (
                    item.get(
                        "video_id"
                    )
                    or item.get(
                        "videoId"
                    )
                    or item.get(
                        "id"
                    )
                )

                if item_video_id != video_id:
                    continue

                text = transcript_text_from_payload(
                    item
                )

                if text:

                    return {
                        "text":
                            text,

                        "raw_text":
                            text,

                        "source":
                            str(
                                path
                            )
                    }

    return None


# ============================================================
# TEXT DE-DUPLICATION
# ============================================================

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
    total = len(
        words
    )

    while index < total:

        best_size = 0
        best_repeats = 1

        max_size = min(
            32,
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

            next_start = (
                index
                + size
            )

            second = words[
                next_start:
                next_start
                + size
            ]

            if first != second:
                continue

            repeats = 2

            while True:

                repeat_start = (
                    index
                    + repeats
                    * size
                )

                repeat_end = (
                    repeat_start
                    + size
                )

                if repeat_end > total:
                    break

                candidate = words[
                    repeat_start:
                    repeat_end
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
                    index
                    + best_size
                ]
            )

            index += (
                best_size
                * best_repeats
            )

        else:

            output.append(
                words[
                    index
                ]
            )

            index += 1

    return normalize_space(
        " ".join(
            output
        )
    )


# ============================================================
# YOUTUBE-TRANSCRIPT.AI PARSER
# ============================================================

def parse_timestamped_markdown(
    raw_text
):

    chunks = []

    if not raw_text:
        return chunks

    pattern = re.compile(
        r"^\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*(.*)$"
    )

    current = None

    for raw_line in raw_text.splitlines():

        line = raw_line.strip()

        match = pattern.match(
            line
        )

        if match:

            if current:

                current[
                    "text"
                ] = normalize_space(
                    " ".join(
                        current[
                            "text_parts"
                        ]
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
                match.group(
                    1
                )
            )

            current = {
                "timestamp":
                    timestamp,

                "seconds":
                    timestamp_to_seconds(
                        timestamp
                    ),

                "text_parts": [
                    match.group(
                        2
                    )
                ]
            }

        else:

            if (
                current
                and line
                and not line.startswith(
                    "#"
                )
            ):

                current[
                    "text_parts"
                ].append(
                    line
                )

    if current:

        current[
            "text"
        ] = normalize_space(
            " ".join(
                current[
                    "text_parts"
                ]
            )
        )

        current.pop(
            "text_parts",
            None
        )

        chunks.append(
            current
        )

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

        normalized_compare = re.sub(
            r"[^a-z0-9]+",
            " ",
            text.lower()
        ).strip()

        if (
            previous_text
            and normalized_compare
            == previous_text
        ):

            continue

        previous_text = (
            normalized_compare
        )

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
                text
        })

    return cleaned


# ============================================================
# DIGIT STRATEGY EXTRACTION
# ============================================================

def digit_chunk_score(
    text,
    track
):

    text_lower = (
        text
        or ""
    ).lower()

    score = 0

    strong_hits = 0

    for keyword in DIGIT_STRONG_KEYWORDS:

        if keyword in text_lower:

            score += 10
            strong_hits += 1

    if track:

        simplified_track = (
            track
            .lower()
            .replace(
                "-",
                " "
            )
        )

        simplified_text = (
            text_lower
            .replace(
                "-",
                " "
            )
        )

        track_tokens = [
            token
            for token in re.findall(
                r"[a-z0-9]+",
                simplified_track
            )
            if len(
                token
            ) >= 4
        ]

        track_matches = sum(
            1
            for token in track_tokens
            if token
            in simplified_text
        )

        if track_matches >= 2:

            score += 8

        elif track_matches == 1:

            score += 3

    for keyword in DIGIT_STRATEGY_KEYWORDS:

        if keyword in text_lower:

            score += 1

    if "race a" in text_lower:

        score -= 6

    if "race b" in text_lower:

        score -= 6

    if (
        "route x"
        in text_lower
        and "grand valley"
        not in text_lower
    ):

        score -= 4

    if (
        "fuji"
        in text_lower
        and "grand valley"
        not in text_lower
    ):

        score -= 4

    return (
        score,
        strong_hits
    )


def merge_intervals(
    intervals
):

    if not intervals:
        return []

    intervals = sorted(
        intervals,
        key=lambda item:
            item[
                "start"
            ]
    )

    merged = [
        dict(
            intervals[
                0
            ]
        )
    ]

    for interval in intervals[
        1:
    ]:

        current = merged[
            -1
        ]

        if (
            interval[
                "start"
            ]
            <= current[
                "end"
            ]
            + 60
        ):

            current[
                "end"
            ] = max(
                current[
                    "end"
                ],
                interval[
                    "end"
                ]
            )

            current[
                "score"
            ] += interval.get(
                "score",
                0
            )

            current[
                "anchors"
            ] += interval.get(
                "anchors",
                0
            )

        else:

            merged.append(
                dict(
                    interval
                )
            )

    return merged


def extract_digit_strategy_segment(
    raw_text,
    track
):

    chunks = parse_timestamped_markdown(
        raw_text
    )

    chunks = clean_timestamp_chunks(
        chunks
    )

    if not chunks:

        cleaned = dedupe_consecutive_words(
            raw_text
        )

        return {
            "text":
                cleaned,

            "mode":
                "FULL_TEXT_FALLBACK",

            "segments":
                [],

            "raw_chunks":
                0,

            "selected_chunks":
                0
        }

    anchors = []

    for chunk in chunks:

        score, strong_hits = (
            digit_chunk_score(
                chunk.get(
                    "text",
                    ""
                ),
                track
            )
        )

        # Require a strong race/track signal.
        # This prevents generic strategy chat elsewhere in
        # the livestream from becoming part of Race C.

        if (
            strong_hits >= 1
            and score >= 8
        ):

            seconds = chunk.get(
                "seconds"
            )

            if seconds is None:
                continue

            anchors.append({
                "start":
                    max(
                        0,
                        seconds
                        - DIGIT_CONTEXT_BEFORE_SECONDS
                    ),

                "end":
                    (
                        seconds
                        + DIGIT_CONTEXT_AFTER_SECONDS
                    ),

                "score":
                    score,

                "anchors":
                    1
            })

    if not anchors:

        # Secondary fallback:
        # find the highest-scoring chunk even if it does not
        # contain a direct Race C phrase.

        scored = []

        for chunk in chunks:

            score, strong_hits = (
                digit_chunk_score(
                    chunk.get(
                        "text",
                        ""
                    ),
                    track
                )
            )

            if score > 0:

                scored.append(
                    (
                        score,
                        strong_hits,
                        chunk
                    )
                )

        if scored:

            scored.sort(
                key=lambda item:
                    (
                        item[
                            0
                        ],
                        item[
                            1
                        ]
                    ),
                reverse=True
            )

            best_chunk = scored[
                0
            ][
                2
            ]

            seconds = (
                best_chunk.get(
                    "seconds"
                )
                or 0
            )

            anchors.append({
                "start":
                    max(
                        0,
                        seconds
                        - DIGIT_CONTEXT_BEFORE_SECONDS
                    ),

                "end":
                    (
                        seconds
                        + DIGIT_CONTEXT_AFTER_SECONDS
                    ),

                "score":
                    scored[
                        0
                    ][
                        0
                    ],

                "anchors":
                    1
            })

    intervals = merge_intervals(
        anchors
    )

    intervals.sort(
        key=lambda item:
            (
                item.get(
                    "anchors",
                    0
                ),
                item.get(
                    "score",
                    0
                )
            ),
        reverse=True
    )

    selected_intervals = []

    total_duration = 0

    for interval in intervals:

        duration = max(
            0,
            interval[
                "end"
            ]
            - interval[
                "start"
            ]
        )

        if (
            selected_intervals
            and total_duration
            + duration
            > DIGIT_MAX_TOTAL_SECONDS
        ):

            continue

        selected_intervals.append(
            interval
        )

        total_duration += (
            duration
        )

        if (
            len(
                selected_intervals
            )
            >= DIGIT_MAX_SEGMENTS
        ):

            break

    selected_intervals.sort(
        key=lambda item:
            item[
                "start"
            ]
    )

    selected_chunks = []

    seen_chunk_keys = set()

    for interval in selected_intervals:

        for chunk in chunks:

            seconds = chunk.get(
                "seconds"
            )

            if seconds is None:
                continue

            if (
                interval[
                    "start"
                ]
                <= seconds
                <= interval[
                    "end"
                ]
            ):

                key = (
                    seconds,
                    chunk.get(
                        "text"
                    )
                )

                if key in seen_chunk_keys:
                    continue

                seen_chunk_keys.add(
                    key
                )

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

    if not selected_text:

        selected_text = dedupe_consecutive_words(
            raw_text
        )

        mode = (
            "FULL_TEXT_FALLBACK"
        )

    else:

        mode = (
            "RACE_C_CONTEXT_WINDOWS"
        )

    segment_metadata = []

    for interval in selected_intervals:

        segment_metadata.append({
            "start_seconds":
                interval[
                    "start"
                ],

            "end_seconds":
                interval[
                    "end"
                ],

            "start":
                seconds_to_timestamp(
                    interval[
                        "start"
                    ]
                ),

            "end":
                seconds_to_timestamp(
                    interval[
                        "end"
                    ]
                ),

            "anchor_score":
                interval.get(
                    "score",
                    0
                ),

            "anchors":
                interval.get(
                    "anchors",
                    0
                )
        })

    return {
        "text":
            selected_text,

        "mode":
            mode,

        "segments":
            segment_metadata,

        "raw_chunks":
            len(
                chunks
            ),

        "selected_chunks":
            len(
                selected_chunks
            )
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
                str(
                    exc
                )
        }

    http_status = (
        response.status_code
    )

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
                raw_text[
                    :3000
                ]
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
                http_status
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
        if indicator
        in lower
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
                raw_text[
                    :3000
                ]
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
            raw_text
    }


# ============================================================
# SUPADATA HEADERS
# ============================================================

def supadata_headers():

    return {
        "x-api-key":
            SUPADATA_API_KEY,

        "Accept":
            "application/json",
    }


# ============================================================
# SUPADATA ASYNC JOB
# ============================================================

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

                "job_id":
                    job_id,

                "error":
                    str(
                        exc
                    )
            }

        http_status = (
            response.status_code
        )

        try:

            payload = response.json()

        except Exception:

            payload = {
                "raw":
                    response.text[
                        :2000
                    ]
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
                    payload
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
                    payload
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

                "job_id":
                    job_id,

                "http_status":
                    http_status,

                "text":
                    text,

                "raw_text":
                    text
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
                    payload
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
            job_id
    }


# ============================================================
# SUPADATA REQUEST
# ============================================================

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
                "Supadata"
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
                str(
                    exc
                )
        }

    http_status = (
        response.status_code
    )

    try:

        payload = response.json()

    except Exception:

        payload = {
            "raw":
                response.text[
                    :2000
                ]
        }

    if http_status == 200:

        text = transcript_text_from_payload(
            payload
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
                    text
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
                payload
        }

    if http_status == 202:

        job_id = (
            payload.get(
                "jobId"
            )
            or payload.get(
                "job_id"
            )
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
                    payload
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
                payload
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
            payload
    }


# ============================================================
# PROCESS PROVIDER RESULT
# ============================================================

def process_provider_result(
    video,
    result,
    track
):

    if not result.get(
        "success"
    ):

        return result

    raw_text = (
        result.get(
            "raw_text"
        )
        or result.get(
            "text"
        )
        or ""
    )

    channel = video.get(
        "channel"
    )

    purpose = video.get(
        "purpose"
    )

    if (
        channel == STRATEGY_CHANNEL
        and purpose == "STRATEGY"
        and result.get(
            "provider"
        )
        == "youtube-transcript.ai"
    ):

        extracted = (
            extract_digit_strategy_segment(
                raw_text,
                track
            )
        )

        result[
            "text"
        ] = extracted[
            "text"
        ]

        result[
            "extraction"
        ] = extracted

    else:

        result[
            "text"
        ] = dedupe_consecutive_words(
            result.get(
                "text"
            )
            or raw_text
        )

    return result


# ============================================================
# RECORD CREATION
# ============================================================

def create_available_record(
    week_key,
    video,
    result,
    cache_source=None
):

    text = normalize_space(
        result.get(
            "text",
            ""
        )
    )

    record = {
        "week":
            week_key,

        "video_id":
            video.get(
                "video_id"
            ),

        "channel":
            video.get(
                "channel"
            ),

        "purpose":
            video.get(
                "purpose"
            ),

        "content_type":
            video.get(
                "content_type"
            ),

        "title":
            video.get(
                "title"
            ),

        "url":
            video.get(
                "url"
            ),

        "status":
            "AVAILABLE",

        "provider":
            result.get(
                "provider"
            ),

        "api_status":
            result.get(
                "status"
            ),

        "delivery_mode":
            result.get(
                "delivery_mode"
            ),

        "http_status":
            result.get(
                "http_status"
            ),

        "job_id":
            result.get(
                "job_id"
            ),

        "cache_source":
            cache_source,

        "word_count":
            len(
                text.split()
            ),

        "character_count":
            len(
                text
            ),

        "transcript":
            text,

        "updated_at":
            datetime.now(
                UTC
            ).isoformat()
    }

    extraction = result.get(
        "extraction"
    )

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

            "selected_chunks":
                extraction.get(
                    "selected_chunks"
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
            video.get(
                "video_id"
            ),

        "channel":
            video.get(
                "channel"
            ),

        "purpose":
            video.get(
                "purpose"
            ),

        "content_type":
            video.get(
                "content_type"
            ),

        "title":
            video.get(
                "title"
            ),

        "url":
            video.get(
                "url"
            ),

        "status":
            result.get(
                "status",
                "UNAVAILABLE"
            ),

        "provider":
            result.get(
                "provider"
            ),

        "api_status":
            result.get(
                "status"
            ),

        "delivery_mode":
            result.get(
                "delivery_mode"
            ),

        "http_status":
            result.get(
                "http_status"
            ),

        "job_id":
            result.get(
                "job_id"
            ),

        "word_count":
            0,

        "character_count":
            0,

        "transcript":
            None,

        "updated_at":
            datetime.now(
                UTC
            ).isoformat()
    }


# ============================================================
# SAVE INDIVIDUAL TRANSCRIPT
# ============================================================

def save_transcript_file(
    record
):

    video = {
        "video_id":
            record.get(
                "video_id"
            ),

        "channel":
            record.get(
                "channel"
            ),
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

    selected = select_primary_sources(
        week_data
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
        week_data.get(
            "track"
        )
        or ""
    )

    print(
        "=" * 92
    )

    print(
        "GT7 COMMUNITY TRANSCRIPT COLLECTOR V4"
    )

    print(
        "=" * 92
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
        "LOCAL CACHE -> SUPADATA -> "
        "youtube-transcript.ai"
    )

    print("")

    print(
        "PRIMARY SOURCES"
    )

    print(
        "-" * 92
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
            "=" * 92
        )

        print(
            f"[{index}/{len(selected)}] "
            f"{video.get('channel')} "
            f"- {video.get('purpose')}"
        )

        print(
            "=" * 92
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
        # 1. DEFINITIVE CACHE
        # ====================================================

        existing = get_existing_record(
            transcript_database,
            video_id
        )

        if (
            existing
            and existing.get(
                "status"
            )
            == "AVAILABLE"
            and existing.get(
                "transcript"
            )
        ):

            record = dict(
                existing
            )

            record[
                "purpose"
            ] = video.get(
                "purpose"
            )

            record[
                "content_type"
            ] = video.get(
                "content_type"
            )

            transcript_database[
                "videos"
            ][
                video_id
            ] = record

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
                f"{record.get('word_count',0):,}"
            )

            print(
                f"Provider         : "
                f"{record.get('provider') or record.get('api_status')}"
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
        # 2. LEGACY CACHE
        # ====================================================

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
                    legacy.get(
                        "text"
                    ),

                "raw_text":
                    legacy.get(
                        "raw_text"
                    )
                    or legacy.get(
                        "text"
                    )
            }

            legacy_result = (
                process_provider_result(
                    video,
                    legacy_result,
                    track
                )
            )

            record = create_available_record(
                week_key=week_key,
                video=video,
                result=legacy_result,
                cache_source=legacy[
                    "source"
                ]
            )

            transcript_database[
                "videos"
            ][
                video_id
            ] = record

            path = save_transcript_file(
                record
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
                f"{record.get('word_count',0):,}"
            )

            print(
                f"Saved file       : "
                f"{path}"
            )

            if record.get(
                "strategy_extraction"
            ):

                extraction = record[
                    "strategy_extraction"
                ]

                print(
                    f"Extraction mode  : "
                    f"{extraction.get('mode')}"
                )

                print(
                    f"Segments         : "
                    f"{len(extraction.get('segments',[]))}"
                )

            available_count += 1
            reused_legacy_count += 1

            run_results.append(
                record
            )

            print("")

            continue

        # ====================================================
        # 3. SUPADATA
        # ====================================================

        provider_result = None

        if not supadata_plan_limit:

            print(
                "Supadata         : REQUESTING"
            )

            provider_result = (
                request_supadata_transcript(
                    video.get(
                        "url"
                    )
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
                    "Supadata"
            }

            print(
                "Supadata         : "
                "SKIPPED - plan limit already known"
            )

        # ====================================================
        # 4. FALLBACK TO YOUTUBE-TRANSCRIPT.AI
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
        # 5. SUCCESS
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

            record = create_available_record(
                week_key=week_key,
                video=video,
                result=provider_result
            )

            if raw_path:

                record[
                    "raw_transcript_file"
                ] = str(
                    raw_path
                )

            transcript_database[
                "videos"
            ][
                video_id
            ] = record

            run_results.append(
                record
            )

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
                f"{record.get('word_count',0):,}"
            )

            print(
                f"Characters       : "
                f"{record.get('character_count',0):,}"
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

            extraction = record.get(
                "strategy_extraction"
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
                    f"Selected chunks  : "
                    f"{extraction.get('selected_chunks')}"
                )

                print(
                    f"Segments         : "
                    f"{len(extraction.get('segments',[]))}"
                )

                for segment_number, segment in enumerate(
                    extraction.get(
                        "segments",
                        []
                    ),
                    start=1
                ):

                    print(
                        f"  Segment "
                        f"{segment_number}: "
                        f"{segment.get('start')} "
                        f"-> "
                        f"{segment.get('end')} "
                        f"| score "
                        f"{segment.get('anchor_score')}"
                    )

            preview = (
                record.get(
                    "transcript"
                )
                or ""
            )

            print("")
            print(
                "TRANSCRIPT PREVIEW"
            )
            print(
                "-" * 92
            )

            print(
                preview[
                    :2500
                ]
            )

            if len(
                preview
            ) > 2500:

                print(
                    "[... preview truncated ...]"
                )

        # ====================================================
        # 6. BOTH PROVIDERS FAILED
        # ====================================================

        else:

            record = create_unavailable_record(
                week_key,
                video,
                provider_result
            )

            transcript_database[
                "videos"
            ][
                video_id
            ] = record

            run_results.append(
                record
            )

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
    # DATABASE METADATA
    # ========================================================

    transcript_database[
        "version"
    ] = 4

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
            "Supadata",
            "youtube-transcript.ai",
        ]
    }

    save_json(
        TRANSCRIPT_DB_FILE,
        transcript_database
    )

    # ========================================================
    # SUMMARY
    # ========================================================

    print(
        "=" * 92
    )

    print(
        "FINAL SUMMARY"
    )

    print(
        "=" * 92
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
        "-" * 92
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

            purposes[
                purpose
            ] = record

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
            record.get(
                "status"
            )
            == "AVAILABLE"
        ):

            print(
                f"  Words   : "
                f"{record.get('word_count',0):,}"
            )

            print(
                f"  Provider: "
                f"{record.get('provider') or record.get('api_status')}"
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
                    f"{len(extraction.get('segments',[]))}"
                )

    print("")

    # ========================================================
    # READINESS
    # ========================================================

    strategy_ready = (
        purposes.get(
            "STRATEGY"
        )
        is not None
        and purposes[
            "STRATEGY"
        ].get(
            "status"
        )
        == "AVAILABLE"
    )

    lap_ready = (
        purposes.get(
            "LAP_GUIDE"
        )
        is not None
        and purposes[
            "LAP_GUIDE"
        ].get(
            "status"
        )
        == "AVAILABLE"
    )

    print(
        "COMMUNITY INTELLIGENCE READINESS"
    )

    print(
        "-" * 92
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
        "=" * 92
    )


if __name__ == "__main__":

    main()