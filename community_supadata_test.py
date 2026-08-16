import json
import os
import re
import requests

from pathlib import Path


# ============================================================
# CONFIG
# ============================================================

DATA_DIR = Path("data")
COMMUNITY_FILE = DATA_DIR / "community_sources.json"

OUTPUT_DIR = DATA_DIR / "community_supadata_test"
OUTPUT_FILE = OUTPUT_DIR / "supadata_test_results.json"

SUPADATA_ENDPOINT = (
    "https://api.supadata.ai/v1/transcript"
)

MAX_VIDEOS_TO_TEST = 5

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

    # --------------------------------------------------------
    # First: try one video from each priority channel.
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Fill remaining slots with strongest sources.
    # --------------------------------------------------------

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

    return selected[
        :MAX_VIDEOS_TO_TEST
    ]


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

                if isinstance(
                    text,
                    str
                ) and text.strip():

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


def classify_response_status(
    response,
    payload
):

    if response.status_code == 200:
        return "SUCCESS"

    if response.status_code == 202:
        return "ASYNC_JOB"

    if response.status_code == 206:
        return "PARTIAL"

    if response.status_code == 401:
        return "AUTH_ERROR"

    if response.status_code == 402:
        return "CREDITS_OR_PLAN"

    if response.status_code == 403:
        return "FORBIDDEN"

    if response.status_code == 404:
        return "NOT_FOUND"

    if response.status_code == 429:
        return "RATE_LIMIT"

    if response.status_code >= 500:
        return "SERVER_ERROR"

    return (
        f"HTTP_{response.status_code}"
    )


# ============================================================
# SUPADATA REQUEST
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

    # Current generic transcript endpoint accepts the URL.
    params = {
        "url":
            video_url
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

            "error":
                "Request timed out."
        }

    except Exception as exc:

        return {
            "status":
                "REQUEST_ERROR",

            "http_status":
                None,

            "payload":
                None,

            "text":
                "",

            "error":
                str(exc)
        }

    try:

        payload = response.json()

    except Exception:

        payload = {
            "raw":
                response.text
        }

    status = classify_response_status(
        response,
        payload
    )

    transcript_text = ""

    if isinstance(
        payload,
        dict
    ):

        transcript_text = (
            extract_text_from_content(
                payload.get(
                    "content"
                )
            )
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

        "error":
            None
    }


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

    print(
        "=" * 88
    )

    print(
        "GT7 SUPADATA TRANSCRIPT TEST"
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

        result = request_transcript(
            api_key,
            video
        )

        print(
            f"HTTP status      : "
            f"{result['http_status']}"
        )

        print(
            f"API status       : "
            f"{result['status']}"
        )

        transcript_text = (
            result[
                "text"
            ]
        )

        if transcript_text:

            word_count = len(
                transcript_text.split()
            )

            character_count = len(
                transcript_text
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
                "Preview          :"
            )

            print(
                "  "
                + transcript_text[
                    :1200
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

                payload_preview = json.dumps(
                    payload,
                    ensure_ascii=False
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

            "api_status":
                result[
                    "status"
                ],

            "http_status":
                result[
                    "http_status"
                ],

            "transcript_status":
                transcript_status,

            "word_count":
                word_count,

            "character_count":
                character_count,

            "transcript_preview":
                (
                    transcript_text[
                        :1000
                    ]
                    if transcript_text
                    else None
                )
        })

    # ========================================================
    # SAVE
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

        "results":
            results
    }

    save_json(
        OUTPUT_FILE,
        output
    )

    # ========================================================
    # SUMMARY
    # ========================================================

    available = [
        result
        for result in results
        if result[
            "transcript_status"
        ]
        == "AVAILABLE"
    ]

    async_jobs = [
        result
        for result in results
        if result[
            "api_status"
        ]
        == "ASYNC_JOB"
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
        f"Async jobs returned : "
        f"{len(async_jobs)}"
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
                f"{item['word_count']:,} words | "
                f"{item['title']}"
            )

    else:

        print(
            "No transcript returned immediately."
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