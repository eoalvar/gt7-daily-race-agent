import json
import os
import re
import time
import requests

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


# ============================================================
# CONFIG
# ============================================================

DATA_DIR = Path("data")

COMMUNITY_SOURCES_FILE = (
    DATA_DIR
    / "community_sources.json"
)

TRANSCRIPT_DATABASE_FILE = (
    DATA_DIR
    / "community_transcripts.json"
)

TRANSCRIPT_STORAGE_DIR = (
    DATA_DIR
    / "community_transcripts"
)

SUPADATA_ENDPOINT = (
    "https://api.supadata.ai/v1/transcript"
)

SAO_PAULO = ZoneInfo(
    "America/Sao_Paulo"
)


# ============================================================
# API CONTROL
#
# Important for free / low-rate plans:
#
# - Do not aggressively poll async jobs.
# - Persist jobId for the next workflow execution.
# - Cache completed transcripts permanently.
# - Stop immediately if API returns HTTP 429.
# ============================================================

MAX_API_REQUESTS_PER_RUN = 3

MIN_SECONDS_BETWEEN_REQUESTS = 20

MAX_VIDEOS_TRACKED_PER_WEEK = 12


# ============================================================
# PRIORITY CHANNELS
# ============================================================

PRIORITY_CHANNELS = [
    "Wombleleader Racing",
    "GnC Racing",
    "MotoSeventeenX",
    "ProdigyRacing",
    "Digit Racing"
]


# ============================================================
# PRIORITY VALUES
# ============================================================

CONTENT_PRIORITY = {
    "STRATEGY": 6,
    "LAP_GUIDE": 5,
    "QUALIFYING": 4,
    "RACE": 3,
    "LIVESTREAM": 2,
    "OTHER": 1
}

TEMPORAL_PRIORITY = {
    "CONFIRMED": 5,
    "LIKELY": 3,
    "UNVERIFIED": 1
}


# ============================================================
# JSON HELPERS
# ============================================================

def load_json(
    path,
    default
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


# ============================================================
# TEXT HELPERS
# ============================================================

def normalize_text(text):

    if not text:

        return ""

    text = text.lower()

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def safe_filename(text):

    text = normalize_text(
        text
    )

    text = re.sub(
        r"[^a-z0-9_-]+",
        "_",
        text
    )

    text = text.strip(
        "_"
    )

    return (
        text[:80]
        or "video"
    )


# ============================================================
# TIME
# ============================================================

def now_iso():

    return (
        datetime.now(
            SAO_PAULO
        )
        .isoformat()
    )


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def load_transcript_database():

    data = load_json(
        TRANSCRIPT_DATABASE_FILE,
        {
            "version": 1,
            "weeks": {}
        }
    )

    if not isinstance(
        data,
        dict
    ):

        data = {
            "version": 1,
            "weeks": {}
        }

    data[
        "version"
    ] = 1

    data.setdefault(
        "weeks",
        {}
    )

    return data


# ============================================================
# CURRENT COMMUNITY WEEK
# ============================================================

def get_latest_week(
    source_database
):

    weeks = source_database.get(
        "weeks",
        {}
    )

    if not weeks:

        raise RuntimeError(
            "No weeks found in "
            "data/community_sources.json."
        )

    week_key = sorted(
        weeks.keys()
    )[-1]

    return (
        week_key,
        weeks[
            week_key
        ]
    )


# ============================================================
# CHANNEL PRIORITY
# ============================================================

def priority_channel_index(
    channel
):

    channel_norm = normalize_text(
        channel
    )

    for index, target in enumerate(
        PRIORITY_CHANNELS
    ):

        target_norm = normalize_text(
            target
        )

        if target_norm in channel_norm:

            return index

    return None


def channel_is_priority(
    channel
):

    return (
        priority_channel_index(
            channel
        )
        is not None
    )


# ============================================================
# VIDEO PRIORITY
# ============================================================

def video_priority_score(
    video
):

    score = 0

    channel_index = (
        priority_channel_index(
            video.get(
                "channel",
                ""
            )
        )
    )

    if channel_index is not None:

        # All preferred channels receive a large bonus.
        # Earlier entries receive a very small additional bonus.
        score += (
            100
            - channel_index
        )

    content_type = (
        video.get(
            "content_type",
            "OTHER"
        )
    )

    score += (
        CONTENT_PRIORITY.get(
            content_type,
            1
        )
        * 15
    )

    temporal = (
        video.get(
            "temporal_confidence",
            "UNVERIFIED"
        )
    )

    score += (
        TEMPORAL_PRIORITY.get(
            temporal,
            1
        )
        * 10
    )

    source_priority = (
        video.get(
            "priority_score",
            video.get(
                "search_relevance",
                0
            )
        )
    )

    if isinstance(
        source_priority,
        (int, float)
    ):

        score += source_priority

    return score


# ============================================================
# SELECT VIDEOS TO TRACK
# ============================================================

def select_week_videos(
    week_data
):

    videos = list(
        week_data
        .get(
            "videos",
            {}
        )
        .values()
    )

    videos = [
        video
        for video in videos
        if video.get(
            "video_id"
        )
    ]

    videos.sort(
        key=video_priority_score,
        reverse=True
    )

    selected = []

    # --------------------------------------------------------
    # First pass:
    # guarantee one source from each preferred channel
    # whenever available.
    # --------------------------------------------------------

    for target_channel in PRIORITY_CHANNELS:

        target = normalize_text(
            target_channel
        )

        matches = [
            video
            for video in videos
            if target
            in normalize_text(
                video.get(
                    "channel",
                    ""
                )
            )
        ]

        if not matches:

            continue

        matches.sort(
            key=video_priority_score,
            reverse=True
        )

        candidate = matches[
            0
        ]

        if not any(
            item.get(
                "video_id"
            )
            == candidate.get(
                "video_id"
            )
            for item in selected
        ):

            selected.append(
                candidate
            )

    # --------------------------------------------------------
    # Second pass:
    # fill remaining positions with strongest sources.
    # --------------------------------------------------------

    for video in videos:

        if (
            len(
                selected
            )
            >= MAX_VIDEOS_TRACKED_PER_WEEK
        ):

            break

        if any(
            item.get(
                "video_id"
            )
            == video.get(
                "video_id"
            )
            for item in selected
        ):

            continue

        selected.append(
            video
        )

    return selected[
        :MAX_VIDEOS_TRACKED_PER_WEEK
    ]


# ============================================================
# TRANSCRIPT CONTENT PARSER
# ============================================================

def extract_text_from_content(
    content
):

    if isinstance(
        content,
        str
    ):

        return content.strip()

    if isinstance(
        content,
        list
    ):

        parts = []

        for item in content:

            if isinstance(
                item,
                str
            ):

                value = item.strip()

                if value:

                    parts.append(
                        value
                    )

            elif isinstance(
                item,
                dict
            ):

                value = item.get(
                    "text"
                )

                if (
                    isinstance(
                        value,
                        str
                    )
                    and value.strip()
                ):

                    parts.append(
                        value.strip()
                    )

        return " ".join(
            parts
        ).strip()

    return ""


def extract_transcript_from_payload(
    payload
):

    if not isinstance(
        payload,
        dict
    ):

        return {
            "text":
                "",

            "language":
                None
        }

    # --------------------------------------------------------
    # Immediate response:
    #
    # {
    #   "content": ...,
    #   "lang": ...
    # }
    # --------------------------------------------------------

    direct_text = (
        extract_text_from_content(
            payload.get(
                "content"
            )
        )
    )

    if direct_text:

        return {
            "text":
                direct_text,

            "language":
                payload.get(
                    "lang"
                )
        }

    # --------------------------------------------------------
    # Async completed response:
    #
    # {
    #   "status": "completed",
    #   "result": {
    #       "content": ...,
    #       "lang": ...
    #   }
    # }
    # --------------------------------------------------------

    result = payload.get(
        "result"
    )

    if isinstance(
        result,
        dict
    ):

        result_text = (
            extract_text_from_content(
                result.get(
                    "content"
                )
            )
        )

        if result_text:

            return {
                "text":
                    result_text,

                "language":
                    result.get(
                        "lang"
                    )
            }

    return {
        "text":
            "",

        "language":
            payload.get(
                "lang"
            )
    }


# ============================================================
# RATE LIMIT CONTROLLER
# ============================================================

class ApiRequestController:

    def __init__(
        self
    ):

        self.requests_used = 0

        self.last_request_time = None

        self.rate_limited = False


    def can_request(
        self
    ):

        return (
            not self.rate_limited
            and self.requests_used
            < MAX_API_REQUESTS_PER_RUN
        )


    def wait_if_needed(
        self
    ):

        if (
            self.last_request_time
            is None
        ):

            return

        elapsed = (
            time.monotonic()
            - self.last_request_time
        )

        remaining = (
            MIN_SECONDS_BETWEEN_REQUESTS
            - elapsed
        )

        if remaining > 0:

            print(
                f"API pacing       : "
                f"waiting "
                f"{remaining:.1f}s"
            )

            time.sleep(
                remaining
            )


    def register_request(
        self
    ):

        self.requests_used += 1

        self.last_request_time = (
            time.monotonic()
        )


    def register_rate_limit(
        self
    ):

        self.rate_limited = True


# ============================================================
# SUPADATA HTTP
# ============================================================

def supadata_get(
    controller,
    url,
    api_key,
    params=None
):

    if not controller.can_request():

        return {
            "status":
                "REQUEST_BUDGET_EXHAUSTED",

            "http_status":
                None,

            "payload":
                None
        }

    controller.wait_if_needed()

    headers = {
        "x-api-key":
            api_key
    }

    try:

        response = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=120
        )

    except requests.Timeout:

        controller.register_request()

        return {
            "status":
                "TIMEOUT",

            "http_status":
                None,

            "payload":
                None
        }

    except Exception as exc:

        controller.register_request()

        return {
            "status":
                "REQUEST_ERROR",

            "http_status":
                None,

            "payload": {
                "error":
                    str(
                        exc
                    )
            }
        }

    controller.register_request()

    try:

        payload = response.json()

    except Exception:

        payload = {
            "raw":
                response.text
        }

    if response.status_code == 429:

        controller.register_rate_limit()

        return {
            "status":
                "RATE_LIMIT",

            "http_status":
                429,

            "payload":
                payload
        }

    if response.status_code == 401:

        return {
            "status":
                "AUTH_ERROR",

            "http_status":
                401,

            "payload":
                payload
        }

    if response.status_code == 402:

        return {
            "status":
                "PLAN_OR_CREDIT_LIMIT",

            "http_status":
                402,

            "payload":
                payload
        }

    if response.status_code == 403:

        return {
            "status":
                "FORBIDDEN",

            "http_status":
                403,

            "payload":
                payload
        }

    if response.status_code == 404:

        return {
            "status":
                "NOT_FOUND",

            "http_status":
                404,

            "payload":
                payload
        }

    if response.status_code >= 500:

        return {
            "status":
                "SERVER_ERROR",

            "http_status":
                response.status_code,

            "payload":
                payload
        }

    return {
        "status":
            "OK",

        "http_status":
            response.status_code,

        "payload":
            payload
    }


# ============================================================
# START TRANSCRIPT REQUEST
# ============================================================

def start_transcript_request(
    controller,
    api_key,
    video
):

    video_id = video.get(
        "video_id"
    )

    video_url = (
        video.get(
            "url"
        )
        or (
            "https://www.youtube.com/watch?v="
            f"{video_id}"
        )
    )

    params = {
        "url":
            video_url,

        "text":
            "true",

        "mode":
            "auto"
    }

    response = supadata_get(
        controller=controller,
        url=SUPADATA_ENDPOINT,
        api_key=api_key,
        params=params
    )

    if response[
        "status"
    ] != "OK":

        return {
            **response,

            "result_type":
                response[
                    "status"
                ],

            "job_id":
                None,

            "text":
                "",

            "language":
                None
        }

    payload = response.get(
        "payload"
    )

    transcript = (
        extract_transcript_from_payload(
            payload
        )
    )

    if transcript[
        "text"
    ]:

        return {
            **response,

            "result_type":
                "IMMEDIATE_SUCCESS",

            "job_id":
                None,

            "text":
                transcript[
                    "text"
                ],

            "language":
                transcript[
                    "language"
                ]
        }

    job_id = None

    if isinstance(
        payload,
        dict
    ):

        job_id = payload.get(
            "jobId"
        )

    if job_id:

        return {
            **response,

            "result_type":
                "ASYNC_PENDING",

            "job_id":
                job_id,

            "text":
                "",

            "language":
                None
        }

    # A successful HTTP response with no transcript and no job
    # means the provider returned no usable content.

    return {
        **response,

        "result_type":
            "NO_TRANSCRIPT",

        "job_id":
            None,

        "text":
            "",

        "language":
            (
                payload.get(
                    "lang"
                )
                if isinstance(
                    payload,
                    dict
                )
                else None
            )
    }


# ============================================================
# CHECK EXISTING ASYNC JOB
# ============================================================

def check_transcript_job(
    controller,
    api_key,
    job_id
):

    job_url = (
        f"{SUPADATA_ENDPOINT}/"
        f"{job_id}"
    )

    response = supadata_get(
        controller=controller,
        url=job_url,
        api_key=api_key
    )

    if response[
        "status"
    ] != "OK":

        return {
            **response,

            "result_type":
                response[
                    "status"
                ],

            "job_status":
                None,

            "text":
                "",

            "language":
                None
        }

    payload = response.get(
        "payload"
    )

    job_status = None

    if isinstance(
        payload,
        dict
    ):

        job_status = payload.get(
            "status"
        )

    transcript = (
        extract_transcript_from_payload(
            payload
        )
    )

    if transcript[
        "text"
    ]:

        return {
            **response,

            "result_type":
                "ASYNC_COMPLETED",

            "job_status":
                (
                    job_status
                    or "completed"
                ),

            "text":
                transcript[
                    "text"
                ],

            "language":
                transcript[
                    "language"
                ]
        }

    if job_status in {
        "queued",
        "active"
    }:

        return {
            **response,

            "result_type":
                "ASYNC_STILL_PENDING",

            "job_status":
                job_status,

            "text":
                "",

            "language":
                None
        }

    if job_status == "failed":

        return {
            **response,

            "result_type":
                "ASYNC_FAILED",

            "job_status":
                "failed",

            "text":
                "",

            "language":
                None
        }

    if job_status == "completed":

        return {
            **response,

            "result_type":
                "ASYNC_COMPLETED_NO_TEXT",

            "job_status":
                "completed",

            "text":
                "",

            "language":
                None
        }

    return {
        **response,

        "result_type":
            "ASYNC_UNKNOWN",

        "job_status":
            job_status,

        "text":
            "",

        "language":
            None
    }


# ============================================================
# TRANSCRIPT FILE
# ============================================================

def transcript_file_path(
    week_key,
    video
):

    video_id = video.get(
        "video_id"
    )

    channel = safe_filename(
        video.get(
            "channel",
            "unknown"
        )
    )

    return (
        TRANSCRIPT_STORAGE_DIR
        / week_key
        / (
            f"{video_id}_"
            f"{channel}.json"
        )
    )


def save_transcript_file(
    week_key,
    video,
    transcript_text,
    language,
    delivery_mode
):

    path = transcript_file_path(
        week_key,
        video
    )

    data = {
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

        "title":
            video.get(
                "title"
            ),

        "url":
            video.get(
                "url"
            ),

        "content_type":
            video.get(
                "content_type"
            ),

        "temporal_confidence":
            video.get(
                "temporal_confidence"
            ),

        "language":
            language,

        "delivery_mode":
            delivery_mode,

        "word_count":
            len(
                transcript_text.split()
            ),

        "character_count":
            len(
                transcript_text
            ),

        "saved_at":
            now_iso(),

        "transcript":
            transcript_text
    }

    save_json(
        path,
        data
    )

    return str(
        path
    )


# ============================================================
# WEEK DATABASE RECORD
# ============================================================

def ensure_week_record(
    transcript_database,
    week_key,
    week_data
):

    weeks = transcript_database[
        "weeks"
    ]

    if week_key not in weeks:

        weeks[
            week_key
        ] = {
            "track":
                week_data.get(
                    "track"
                ),

            "race_class":
                week_data.get(
                    "race_class"
                ),

            "direction":
                week_data.get(
                    "direction"
                ),

            "race_description":
                week_data.get(
                    "race_description"
                ),

            "leaderboard_url":
                week_data.get(
                    "leaderboard_url"
                ),

            "created_at":
                now_iso(),

            "updated_at":
                now_iso(),

            "videos":
                {}
        }

    week_record = weeks[
        week_key
    ]

    week_record[
        "updated_at"
    ] = now_iso()

    week_record.setdefault(
        "videos",
        {}
    )

    return week_record


# ============================================================
# REGISTER DISCOVERED VIDEOS
# ============================================================

def sync_selected_videos(
    week_record,
    selected_videos
):

    records = week_record[
        "videos"
    ]

    for video in selected_videos:

        video_id = video.get(
            "video_id"
        )

        if not video_id:

            continue

        if video_id not in records:

            records[
                video_id
            ] = {
                "video_id":
                    video_id,

                "channel":
                    video.get(
                        "channel"
                    ),

                "title":
                    video.get(
                        "title"
                    ),

                "url":
                    video.get(
                        "url"
                    ),

                "content_type":
                    video.get(
                        "content_type"
                    ),

                "temporal_confidence":
                    video.get(
                        "temporal_confidence"
                    ),

                "priority_score":
                    video_priority_score(
                        video
                    ),

                "status":
                    "NEW",

                "job_id":
                    None,

                "job_status":
                    None,

                "transcript_file":
                    None,

                "word_count":
                    0,

                "language":
                    None,

                "first_seen":
                    now_iso(),

                "last_attempt":
                    None,

                "last_success":
                    None,

                "attempt_count":
                    0,

                "error":
                    None
            }

        else:

            record = records[
                video_id
            ]

            record[
                "channel"
            ] = video.get(
                "channel"
            )

            record[
                "title"
            ] = video.get(
                "title"
            )

            record[
                "url"
            ] = video.get(
                "url"
            )

            record[
                "content_type"
            ] = video.get(
                "content_type"
            )

            record[
                "temporal_confidence"
            ] = video.get(
                "temporal_confidence"
            )

            record[
                "priority_score"
            ] = video_priority_score(
                video
            )


# ============================================================
# PERSIST COMPLETED TRANSCRIPT
# ============================================================

def mark_available(
    week_key,
    record,
    video,
    text,
    language,
    delivery_mode
):

    transcript_path = (
        save_transcript_file(
            week_key=week_key,
            video=video,
            transcript_text=text,
            language=language,
            delivery_mode=delivery_mode
        )
    )

    record[
        "status"
    ] = "AVAILABLE"

    record[
        "job_status"
    ] = "completed"

    record[
        "transcript_file"
    ] = transcript_path

    record[
        "word_count"
    ] = len(
        text.split()
    )

    record[
        "language"
    ] = language

    record[
        "last_success"
    ] = now_iso()

    record[
        "error"
    ] = None


# ============================================================
# BUILD VIDEO LOOKUP
# ============================================================

def selected_video_lookup(
    selected_videos
):

    return {
        video.get(
            "video_id"
        ):
            video
        for video in selected_videos
        if video.get(
            "video_id"
        )
    }


# ============================================================
# PROCESS PENDING JOBS
# ============================================================

def process_pending_jobs(
    controller,
    api_key,
    week_key,
    week_record,
    video_lookup
):

    records = week_record[
        "videos"
    ]

    pending = [
        record
        for record in records.values()
        if (
            record.get(
                "status"
            )
            == "PENDING"
            and record.get(
                "job_id"
            )
        )
    ]

    pending.sort(
        key=lambda item:
            item.get(
                "priority_score",
                0
            ),
        reverse=True
    )

    checked = 0

    for record in pending:

        if not controller.can_request():

            break

        video_id = record.get(
            "video_id"
        )

        video = (
            video_lookup.get(
                video_id
            )
            or {
                "video_id":
                    video_id,

                "channel":
                    record.get(
                        "channel"
                    ),

                "title":
                    record.get(
                        "title"
                    ),

                "url":
                    record.get(
                        "url"
                    ),

                "content_type":
                    record.get(
                        "content_type"
                    ),

                "temporal_confidence":
                    record.get(
                        "temporal_confidence"
                    )
            }
        )

        print()

        print(
            f"Checking pending : "
            f"{record.get('channel')}"
        )

        print(
            f"Video ID         : "
            f"{video_id}"
        )

        print(
            f"Job ID           : "
            f"{record.get('job_id')}"
        )

        result = check_transcript_job(
            controller=controller,
            api_key=api_key,
            job_id=record[
                "job_id"
            ]
        )

        checked += 1

        record[
            "last_attempt"
        ] = now_iso()

        record[
            "attempt_count"
        ] = (
            record.get(
                "attempt_count",
                0
            )
            + 1
        )

        print(
            f"Result           : "
            f"{result['result_type']}"
        )

        if (
            result[
                "result_type"
            ]
            == "ASYNC_COMPLETED"
        ):

            mark_available(
                week_key=week_key,
                record=record,
                video=video,
                text=result[
                    "text"
                ],
                language=result[
                    "language"
                ],
                delivery_mode="ASYNC"
            )

            print(
                f"Transcript       : YES"
            )

            print(
                f"Words            : "
                f"{record['word_count']:,}"
            )

        elif (
            result[
                "result_type"
            ]
            == "ASYNC_STILL_PENDING"
        ):

            record[
                "status"
            ] = "PENDING"

            record[
                "job_status"
            ] = result.get(
                "job_status"
            )

            print(
                f"Job status       : "
                f"{record['job_status']}"
            )

        elif (
            result[
                "result_type"
            ]
            in {
                "ASYNC_FAILED",
                "ASYNC_COMPLETED_NO_TEXT"
            }
        ):

            record[
                "status"
            ] = "UNAVAILABLE"

            record[
                "job_status"
            ] = result.get(
                "job_status"
            )

            record[
                "error"
            ] = result[
                "result_type"
            ]

        elif (
            result[
                "result_type"
            ]
            == "RATE_LIMIT"
        ):

            record[
                "error"
            ] = "RATE_LIMIT"

            print(
                "API rate limit reached. "
                "Stopping this run."
            )

            break

        else:

            record[
                "error"
            ] = result[
                "result_type"
            ]

    return checked


# ============================================================
# PROCESS NEW VIDEOS
# ============================================================

def process_new_videos(
    controller,
    api_key,
    week_key,
    week_record,
    video_lookup
):

    records = week_record[
        "videos"
    ]

    new_records = [
        record
        for record in records.values()
        if record.get(
            "status"
        )
        == "NEW"
    ]

    new_records.sort(
        key=lambda item:
            item.get(
                "priority_score",
                0
            ),
        reverse=True
    )

    started = 0

    for record in new_records:

        if not controller.can_request():

            break

        video_id = record[
            "video_id"
        ]

        video = (
            video_lookup.get(
                video_id
            )
            or {
                "video_id":
                    video_id,

                "channel":
                    record.get(
                        "channel"
                    ),

                "title":
                    record.get(
                        "title"
                    ),

                "url":
                    record.get(
                        "url"
                    ),

                "content_type":
                    record.get(
                        "content_type"
                    ),

                "temporal_confidence":
                    record.get(
                        "temporal_confidence"
                    )
            }
        )

        print()

        print(
            f"Starting video   : "
            f"{record.get('channel')}"
        )

        print(
            f"Video ID         : "
            f"{video_id}"
        )

        print(
            f"Type             : "
            f"{record.get('content_type')}"
        )

        result = start_transcript_request(
            controller=controller,
            api_key=api_key,
            video=video
        )

        started += 1

        record[
            "last_attempt"
        ] = now_iso()

        record[
            "attempt_count"
        ] = (
            record.get(
                "attempt_count",
                0
            )
            + 1
        )

        print(
            f"Result           : "
            f"{result['result_type']}"
        )

        if (
            result[
                "result_type"
            ]
            == "IMMEDIATE_SUCCESS"
        ):

            mark_available(
                week_key=week_key,
                record=record,
                video=video,
                text=result[
                    "text"
                ],
                language=result[
                    "language"
                ],
                delivery_mode="IMMEDIATE"
            )

            print(
                "Transcript       : YES"
            )

            print(
                f"Words            : "
                f"{record['word_count']:,}"
            )

        elif (
            result[
                "result_type"
            ]
            == "ASYNC_PENDING"
        ):

            record[
                "status"
            ] = "PENDING"

            record[
                "job_id"
            ] = result[
                "job_id"
            ]

            record[
                "job_status"
            ] = "queued"

            record[
                "error"
            ] = None

            print(
                f"Job ID           : "
                f"{record['job_id']}"
            )

            print(
                "Transcript will be checked "
                "in a future workflow run."
            )

        elif (
            result[
                "result_type"
            ]
            == "NO_TRANSCRIPT"
        ):

            record[
                "status"
            ] = "UNAVAILABLE"

            record[
                "error"
            ] = "NO_TRANSCRIPT"

            print(
                "Transcript       : NO"
            )

        elif (
            result[
                "result_type"
            ]
            == "RATE_LIMIT"
        ):

            # Keep NEW so the next run can try again.

            record[
                "status"
            ] = "NEW"

            record[
                "error"
            ] = "RATE_LIMIT"

            print(
                "API rate limit reached. "
                "Stopping this run."
            )

            break

        elif (
            result[
                "result_type"
            ]
            == "PLAN_OR_CREDIT_LIMIT"
        ):

            record[
                "status"
            ] = "NEW"

            record[
                "error"
            ] = (
                "PLAN_OR_CREDIT_LIMIT"
            )

            print(
                "Supadata plan or credit "
                "limit reached."
            )

            break

        else:

            # Temporary errors remain NEW so they may be
            # attempted again on a future run.

            record[
                "status"
            ] = "NEW"

            record[
                "error"
            ] = result[
                "result_type"
            ]

    return started


# ============================================================
# SUMMARY
# ============================================================

def build_status_counts(
    week_record
):

    counts = {
        "AVAILABLE": 0,
        "PENDING": 0,
        "NEW": 0,
        "UNAVAILABLE": 0,
        "OTHER": 0
    }

    for record in (
        week_record[
            "videos"
        ]
        .values()
    ):

        status = record.get(
            "status"
        )

        if status in counts:

            counts[
                status
            ] += 1

        else:

            counts[
                "OTHER"
            ] += 1

    return counts


# ============================================================
# MAIN
# ============================================================

def main():

    api_key = os.environ.get(
        "SUPADATA_API_KEY"
    )

    if not api_key:

        raise RuntimeError(
            "SUPADATA_API_KEY environment "
            "variable is not available."
        )

    source_database = load_json(
        COMMUNITY_SOURCES_FILE,
        None
    )

    if not source_database:

        raise RuntimeError(
            "data/community_sources.json "
            "not found or invalid."
        )

    (
        week_key,
        week_data
    ) = get_latest_week(
        source_database
    )

    selected_videos = (
        select_week_videos(
            week_data
        )
    )

    transcript_database = (
        load_transcript_database()
    )

    week_record = ensure_week_record(
        transcript_database,
        week_key,
        week_data
    )

    sync_selected_videos(
        week_record,
        selected_videos
    )

    video_lookup = (
        selected_video_lookup(
            selected_videos
        )
    )

    controller = (
        ApiRequestController()
    )

    print(
        "=" * 88
    )

    print(
        "GT7 COMMUNITY TRANSCRIPT COLLECTOR"
    )

    print(
        "=" * 88
    )

    print(
        f"Week             : "
        f"{week_key}"
    )

    print(
        f"Track            : "
        f"{week_data.get('track','UNKNOWN')}"
    )

    print(
        f"Race class       : "
        f"{week_data.get('race_class','UNKNOWN')}"
    )

    print(
        f"Videos selected  : "
        f"{len(selected_videos)}"
    )

    print(
        f"API budget/run   : "
        f"{MAX_API_REQUESTS_PER_RUN}"
    )

    print(
        f"API spacing      : "
        f"{MIN_SECONDS_BETWEEN_REQUESTS}s"
    )

    print()

    print(
        "PRIORITY SOURCES"
    )

    print(
        "-" * 88
    )

    for channel in PRIORITY_CHANNELS:

        selected = any(
            normalize_text(
                channel
            )
            in normalize_text(
                video.get(
                    "channel",
                    ""
                )
            )
            for video in selected_videos
        )

        print(
            f"{channel:<25} : "
            f"{'TRACKED' if selected else 'NOT FOUND'}"
        )

    # ========================================================
    # FIRST:
    # Check previously-created async jobs.
    # ========================================================

    pending_checked = (
        process_pending_jobs(
            controller=controller,
            api_key=api_key,
            week_key=week_key,
            week_record=week_record,
            video_lookup=video_lookup
        )
    )

    # ========================================================
    # SECOND:
    # Spend remaining request budget on new videos.
    # ========================================================

    new_started = (
        process_new_videos(
            controller=controller,
            api_key=api_key,
            week_key=week_key,
            week_record=week_record,
            video_lookup=video_lookup
        )
    )

    week_record[
        "updated_at"
    ] = now_iso()

    week_record[
        "last_run"
    ] = {
        "timestamp":
            now_iso(),

        "api_requests":
            controller.requests_used,

        "rate_limited":
            controller.rate_limited,

        "pending_jobs_checked":
            pending_checked,

        "new_videos_started":
            new_started
    }

    save_json(
        TRANSCRIPT_DATABASE_FILE,
        transcript_database
    )

    counts = build_status_counts(
        week_record
    )

    print()

    print(
        "=" * 88
    )

    print(
        "TRANSCRIPT DATABASE STATUS"
    )

    print(
        "=" * 88
    )

    print(
        f"Available         : "
        f"{counts['AVAILABLE']}"
    )

    print(
        f"Pending           : "
        f"{counts['PENDING']}"
    )

    print(
        f"New / waiting     : "
        f"{counts['NEW']}"
    )

    print(
        f"Unavailable       : "
        f"{counts['UNAVAILABLE']}"
    )

    print(
        f"API requests used : "
        f"{controller.requests_used}"
    )

    print(
        f"Rate limited      : "
        f"{'YES' if controller.rate_limited else 'No'}"
    )

    print()

    print(
        "AVAILABLE TRANSCRIPTS"
    )

    print(
        "-" * 88
    )

    available = [
        record
        for record
        in week_record[
            "videos"
        ].values()
        if record.get(
            "status"
        )
        == "AVAILABLE"
    ]

    available.sort(
        key=lambda item:
            item.get(
                "priority_score",
                0
            ),
        reverse=True
    )

    if not available:

        print(
            "None available yet."
        )

    else:

        for record in available:

            print(
                f"{record.get('channel')} | "
                f"{record.get('content_type')} | "
                f"{record.get('word_count',0):,} words"
            )

            print(
                f"  {record.get('title')}"
            )

            print(
                f"  {record.get('transcript_file')}"
            )

    print()

    print(
        "PENDING TRANSCRIPTS"
    )

    print(
        "-" * 88
    )

    pending = [
        record
        for record
        in week_record[
            "videos"
        ].values()
        if record.get(
            "status"
        )
        == "PENDING"
    ]

    if not pending:

        print(
            "None."
        )

    else:

        for record in pending:

            print(
                f"{record.get('channel')} | "
                f"{record.get('job_status')} | "
                f"{record.get('job_id')}"
            )

    print()

    print(
        f"Database file    : "
        f"{TRANSCRIPT_DATABASE_FILE}"
    )

    print(
        f"Transcript dir   : "
        f"{TRANSCRIPT_STORAGE_DIR}"
    )

    print(
        "=" * 88
    )


if __name__ == "__main__":

    main()