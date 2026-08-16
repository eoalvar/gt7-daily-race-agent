import json
import os
import re
import time
import requests

from pathlib import Path


# ============================================================
# CONFIG
# ============================================================

DATA_DIR = Path("data")
COMMUNITY_FILE = DATA_DIR / "community_sources.json"

OUTPUT_DIR = DATA_DIR / "community_supadata_test"
OUTPUT_FILE = OUTPUT_DIR / "supadata_test_results.json"

SUPADATA_ENDPOINT = "https://api.supadata.ai/v1/transcript"

MAX_VIDEOS_TO_TEST = 5

POLL_INTERVAL_SECONDS = 5
MAX_POLL_ATTEMPTS = 24

PRIORITY_CHANNELS = [
    "Wombleleader Racing",
    "GnC Racing",
    "MotoSeventeenX",
    "ProdigyRacing",
    "Digit Racing"
]

CONTENT_PRIORITY = {
    "STRATEGY": 5,
    "LAP_GUIDE": 4,
    "QUALIFYING": 3,
    "RACE": 2,
    "LIVESTREAM": 1,
    "OTHER": 0
}

TEMPORAL_PRIORITY = {
    "CONFIRMED": 3,
    "LIKELY": 2,
    "UNVERIFIED": 1
}


# ============================================================
# HELPERS
# ============================================================

def load_json(path, default):

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


def get_latest_week(database):

    weeks = database.get(
        "weeks",
        {}
    )

    if not weeks:

        raise RuntimeError(
            "No community weeks found."
        )

    week_key = sorted(
        weeks.keys()
    )[-1]

    return (
        week_key,
        weeks[week_key]
    )


# ============================================================
# VIDEO SELECTION
# ============================================================

def channel_is_priority(channel):

    normalized = normalize_text(
        channel
    )

    return any(
        normalize_text(priority)
        in normalized
        for priority in PRIORITY_CHANNELS
    )


def video_selection_score(video):

    channel_bonus = (
        100
        if channel_is_priority(
            video.get(
                "channel",
                ""
            )
        )
        else 0
    )

    content_bonus = (
        CONTENT_PRIORITY.get(
            video.get(
                "content_type",
                "OTHER"
            ),
            0
        )
        * 20
    )

    temporal_bonus = (
        TEMPORAL_PRIORITY.get(
            video.get(
                "temporal_confidence",
                "UNVERIFIED"
            ),
            0
        )
        * 10
    )

    source_score = video.get(
        "priority_score",
        video.get(
            "search_relevance",
            0
        )
    )

    return (
        channel_bonus
        + content_bonus
        + temporal_bonus
        + source_score
    )


def select_videos(week_data):

    videos = list(
        week_data
        .get(
            "videos",
            {}
        )
        .values()
    )

    videos.sort(
        key=video_selection_score,
        reverse=True
    )

    selected = []

    # First pass:
    # try one video from each priority channel.

    for priority_channel in PRIORITY_CHANNELS:

        target = normalize_text(
            priority_channel
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
            key=video_selection_score,
            reverse=True
        )

        candidate = matches[0]

        if not any(
            item.get("video_id")
            == candidate.get("video_id")
            for item in selected
        ):

            selected.append(
                candidate
            )

    # Second pass:
    # fill remaining positions with strongest sources.

    for video in videos:

        if len(selected) >= MAX_VIDEOS_TO_TEST:
            break

        if any(
            item.get("video_id")
            == video.get("video_id")
            for item in selected
        ):
            continue

        selected.append(
            video
        )

    return selected[:MAX_VIDEOS_TO_TEST]


# ============================================================
# SUPADATA RESPONSE PARSING
# ============================================================

def extract_text_from_content(content):

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
                dict
            ):

                text = item.get(
                    "text"
                )

                if (
                    isinstance(
                        text,
                        str
                    )
                    and text.strip()
                ):
                    parts.append(
                        text.strip()
                    )

            elif isinstance(
                item,
                str
            ):

                if item.strip():
                    parts.append(
                        item.strip()
                    )

        return " ".join(
            parts
        ).strip()

    return ""


def transcript_from_payload(payload):

    if not isinstance(
        payload,
        dict
    ):
        return ""

    return extract_text_from_content(
        payload.get(
            "content"
        )
    )


# ============================================================
# INITIAL SUPADATA REQUEST
# ============================================================

def request_transcript(
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

    headers = {
        "x-api-key":
            api_key
    }

    params = {
        "url":
            video_url,

        # Plain text is enough for this test.
        "text":
            "true",

        # Try existing captions first and use generation
        # only when necessary.
        "mode":
            "auto"
    }

    try:

        response = requests.get(
            SUPADATA_ENDPOINT,
            headers=headers,
            params=params,
            timeout=120
        )

    except requests.Timeout:

        return {
            "status":
                "TIMEOUT",

            "http_status":
                None,

            "payload":
                None,

            "text":
                "",

            "job_id":
                None
        }

    except Exception as exc:

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
            },

            "text":
                "",

            "job_id":
                None
        }

    try:
        payload = response.json()

    except Exception:
        payload = {
            "raw":
                response.text
        }

    transcript_text = transcript_from_payload(
        payload
    )

    job_id = None

    if isinstance(
        payload,
        dict
    ):
        job_id = payload.get(
            "jobId"
        )

    if transcript_text:

        status = "IMMEDIATE_SUCCESS"

    elif job_id:

        status = "ASYNC_JOB"

    elif response.status_code == 401:

        status = "AUTH_ERROR"

    elif response.status_code == 402:

        status = "CREDITS_OR_PLAN"

    elif response.status_code == 403:

        status = "FORBIDDEN"

    elif response.status_code == 404:

        status = "NOT_FOUND"

    elif response.status_code == 429:

        status = "RATE_LIMIT"

    elif response.status_code >= 500:

        status = "SERVER_ERROR"

    else:

        status = (
            f"HTTP_{response.status_code}"
        )

    return {
        "status":
            status,

        "http_status":
            response.status_code,

        "payload":
            payload,

        "text":
            transcript_text,

        "job_id":
            job_id
    }


# ============================================================
# ASYNC JOB POLLING
# ============================================================

def poll_transcript_job(
    api_key,
    job_id
):

    headers = {
        "x-api-key":
            api_key
    }

    job_url = (
        f"{SUPADATA_ENDPOINT}/"
        f"{job_id}"
    )

    last_payload = None
    last_http_status = None

    for attempt in range(
        1,
        MAX_POLL_ATTEMPTS + 1
    ):

        print(
            f"Polling job      : "
            f"{attempt}/{MAX_POLL_ATTEMPTS}"
        )

        try:

            response = requests.get(
                job_url,
                headers=headers,
                timeout=60
            )

        except requests.Timeout:

            print(
                "Poll result      : TIMEOUT"
            )

            time.sleep(
                POLL_INTERVAL_SECONDS
            )

            continue

        except Exception as exc:

            return {
                "status":
                    "POLL_REQUEST_ERROR",

                "http_status":
                    None,

                "payload": {
                    "error":
                        str(
                            exc
                        )
                },

                "text":
                    ""
            }

        last_http_status = (
            response.status_code
        )

        try:
            payload = response.json()

        except Exception:
            payload = {
                "raw":
                    response.text
            }

        last_payload = payload

        job_status = None

        if isinstance(
            payload,
            dict
        ):

            job_status = (
                payload.get(
                    "status"
                )
            )

        transcript_text = (
            transcript_from_payload(
                payload
            )
        )

        print(
            f"Poll status      : "
            f"{job_status or 'UNKNOWN'}"
        )

        if transcript_text:

            return {
                "status":
                    "ASYNC_COMPLETED",

                "http_status":
                    response.status_code,

                "payload":
                    payload,

                "text":
                    transcript_text
            }

        if job_status == "completed":

            return {
                "status":
                    "ASYNC_COMPLETED_NO_TEXT",

                "http_status":
                    response.status_code,

                "payload":
                    payload,

                "text":
                    ""
            }

        if job_status == "failed":

            return {
                "status":
                    "ASYNC_FAILED",

                "http_status":
                    response.status_code,

                "payload":
                    payload,

                "text":
                    ""
            }

        if response.status_code in (
            400,
            401,
            402,
            403,
            404,
            429
        ):

            return {
                "status":
                    (
                        f"POLL_HTTP_"
                        f"{response.status_code}"
                    ),

                "http_status":
                    response.status_code,

                "payload":
                    payload,

                "text":
                    ""
            }

        time.sleep(
            POLL_INTERVAL_SECONDS
        )

    return {
        "status":
            "ASYNC_TIMEOUT",

        "http_status":
            last_http_status,

        "payload":
            last_payload,

        "text":
            ""
    }


# ============================================================
# COMPLETE TRANSCRIPT REQUEST
# ============================================================

def get_transcript(
    api_key,
    video
):

    initial = request_transcript(
        api_key,
        video
    )

    if (
        initial[
            "status"
        ]
        == "IMMEDIATE_SUCCESS"
    ):

        return {
            **initial,

            "delivery_mode":
                "IMMEDIATE"
        }

    if (
        initial[
            "status"
        ]
        == "ASYNC_JOB"
        and initial.get(
            "job_id"
        )
    ):

        print(
            f"Async job ID     : "
            f"{initial['job_id']}"
        )

        async_result = (
            poll_transcript_job(
                api_key,
                initial[
                    "job_id"
                ]
            )
        )

        return {
            **async_result,

            "job_id":
                initial[
                    "job_id"
                ],

            "delivery_mode":
                "ASYNC"
        }

    return {
        **initial,

        "delivery_mode":
            "NONE"
    }


# ============================================================
# SAVE INDIVIDUAL TRANSCRIPT
# ============================================================

def save_video_transcript(
    week_key,
    video,
    result
):

    transcript_text = result.get(
        "text",
        ""
    )

    if not transcript_text:
        return None

    video_id = video.get(
        "video_id"
    )

    channel = video.get(
        "channel",
        "Unknown"
    )

    name = (
        f"{video_id}_"
        f"{safe_filename(channel)}.json"
    )

    path = (
        OUTPUT_DIR
        / "transcripts"
        / name
    )

    data = {
        "week":
            week_key,

        "video_id":
            video_id,

        "channel":
            channel,

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

        "delivery_mode":
            result.get(
                "delivery_mode"
            ),

        "api_status":
            result.get(
                "status"
            ),

        "job_id":
            result.get(
                "job_id"
            ),

        "word_count":
            len(
                transcript_text.split()
            ),

        "character_count":
            len(
                transcript_text
            ),

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
# MAIN
# ============================================================

def main():

    api_key = os.environ.get(
        "SUPADATA_API_KEY"
    )

    if not api_key:

        raise RuntimeError(
            "SUPADATA_API_KEY environment variable "
            "is not available."
        )

    database = load_json(
        COMMUNITY_FILE,
        None
    )

    if not database:

        raise RuntimeError(
            "data/community_sources.json "
            "not found or invalid."
        )

    (
        week_key,
        week_data
    ) = get_latest_week(
        database
    )

    selected = select_videos(
        week_data
    )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    print(
        "=" * 88
    )

    print(
        "GT7 SUPADATA TRANSCRIPT TEST V2"
    )

    print(
        "=" * 88
    )

    print(
        f"Week             : "
        f"{week_key}"
    )

    print(
        f"Videos selected  : "
        f"{len(selected)}"
    )

    print()

    print(
        "PRIORITY CHANNELS"
    )

    print(
        "-" * 88
    )

    for channel in PRIORITY_CHANNELS:

        found = any(
            normalize_text(
                channel
            )
            in normalize_text(
                video.get(
                    "channel",
                    ""
                )
            )
            for video in selected
        )

        print(
            f"{channel:<25} : "
            f"{'SELECTED' if found else 'NOT FOUND'}"
        )

    print()

    print(
        "SELECTED VIDEOS"
    )

    print(
        "-" * 88
    )

    for index, video in enumerate(
        selected,
        start=1
    ):

        print(
            f"{index}. "
            f"{video.get('channel','Unknown')} | "
            f"[{video.get('content_type','OTHER')}] | "
            f"[{video.get('temporal_confidence','UNVERIFIED')}]"
        )

        print(
            f"   {video.get('title','')}"
        )

        print(
            f"   {video.get('url','')}"
        )

    results = []

    print()

    print(
        "=" * 88
    )

    print(
        "SUPADATA RESULTS"
    )

    print(
        "=" * 88
    )

    for index, video in enumerate(
        selected,
        start=1
    ):

        print()

        print(
            f"[{index}/{len(selected)}] "
            f"{video.get('channel','Unknown')}"
        )

        print(
            f"Title            : "
            f"{video.get('title','')}"
        )

        print(
            f"Video ID         : "
            f"{video.get('video_id','')}"
        )

        result = get_transcript(
            api_key,
            video
        )

        transcript_text = (
            result.get(
                "text",
                ""
            )
        )

        print(
            f"HTTP status      : "
            f"{result.get('http_status')}"
        )

        print(
            f"API status       : "
            f"{result.get('status')}"
        )

        print(
            f"Delivery mode    : "
            f"{result.get('delivery_mode')}"
        )

        if result.get(
            "job_id"
        ):

            print(
                f"Job ID           : "
                f"{result['job_id']}"
            )

        if transcript_text:

            word_count = len(
                transcript_text.split()
            )

            character_count = len(
                transcript_text
            )

            transcript_file = (
                save_video_transcript(
                    week_key,
                    video,
                    result
                )
            )

            print(
                "Transcript       : YES"
            )

            print(
                f"Words            : "
                f"{word_count:,}"
            )

            print(
                f"Characters       : "
                f"{character_count:,}"
            )

            print(
                f"Saved file       : "
                f"{transcript_file}"
            )

            print(
                "Preview          :"
            )

            print(
                "  "
                + transcript_text[
                    :1000
                ]
                .replace(
                    "\n",
                    " "
                )
            )

            transcript_status = (
                "AVAILABLE"
            )

        else:

            word_count = 0
            character_count = 0
            transcript_file = None

            print(
                "Transcript       : NO"
            )

            transcript_status = (
                "UNAVAILABLE"
            )

            payload = result.get(
                "payload"
            )

            if payload is not None:

                print(
                    "API payload      :"
                )

                payload_preview = (
                    json.dumps(
                        payload,
                        ensure_ascii=False
                    )
                )

                print(
                    "  "
                    + payload_preview[
                        :1500
                    ]
                )

        results.append({
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

            "delivery_mode":
                result.get(
                    "delivery_mode"
                ),

            "api_status":
                result.get(
                    "status"
                ),

            "http_status":
                result.get(
                    "http_status"
                ),

            "job_id":
                result.get(
                    "job_id"
                ),

            "transcript_status":
                transcript_status,

            "transcript_file":
                transcript_file,

            "word_count":
                word_count,

            "character_count":
                character_count
        })

    # ========================================================
    # SAVE SUMMARY
    # ========================================================

    output = {
        "week":
            week_key,

        "videos_tested":
            len(
                results
            ),

        "priority_channels":
            PRIORITY_CHANNELS,

        "poll_interval_seconds":
            POLL_INTERVAL_SECONDS,

        "max_poll_attempts":
            MAX_POLL_ATTEMPTS,

        "results":
            results
    }

    save_json(
        OUTPUT_FILE,
        output
    )

    # ========================================================
    # FINAL SUMMARY
    # ========================================================

    available = [
        item
        for item in results
        if item[
            "transcript_status"
        ]
        == "AVAILABLE"
    ]

    immediate = [
        item
        for item in available
        if item.get(
            "delivery_mode"
        )
        == "IMMEDIATE"
    ]

    async_completed = [
        item
        for item in available
        if item.get(
            "delivery_mode"
        )
        == "ASYNC"
    ]

    unavailable = [
        item
        for item in results
        if item[
            "transcript_status"
        ]
        != "AVAILABLE"
    ]

    print()

    print(
        "=" * 88
    )

    print(
        "FINAL SUMMARY"
    )

    print(
        "=" * 88
    )

    print(
        f"Videos tested       : "
        f"{len(results)}"
    )

    print(
        f"Transcripts found   : "
        f"{len(available)}"
    )

    print(
        f"Immediate           : "
        f"{len(immediate)}"
    )

    print(
        f"Async completed     : "
        f"{len(async_completed)}"
    )

    print(
        f"Unavailable         : "
        f"{len(unavailable)}"
    )

    print()

    if available:

        print(
            "TRANSCRIPTS AVAILABLE"
        )

        print(
            "-" * 88
        )

        for item in available:

            print(
                f"{item['channel']} | "
                f"{item['delivery_mode']} | "
                f"{item['word_count']:,} words | "
                f"{item['title']}"
            )

    if unavailable:

        print()

        print(
            "TRANSCRIPTS UNAVAILABLE"
        )

        print(
            "-" * 88
        )

        for item in unavailable:

            print(
                f"{item['channel']} | "
                f"{item['api_status']} | "
                f"{item['title']}"
            )

    print()

    print(
        f"Results file       : "
        f"{OUTPUT_FILE}"
    )

    print(
        "=" * 88
    )


if __name__ == "__main__":

    main()