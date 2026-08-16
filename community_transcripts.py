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
# ============================================================

MAX_API_REQUESTS_PER_RUN = 2

MIN_SECONDS_BETWEEN_REQUESTS = 10

MAX_VIDEOS_TRACKED_PER_WEEK = 10


# ============================================================
# SOURCE TIERS
#
# Tier 1:
# Sources already proven to provide useful native transcripts.
#
# Tier 2:
# High-value sources, but native transcript availability has
# not yet been proven.
#
# Tier 3:
# Sources previously observed with no usable native transcript
# or that are less suitable for automated textual analysis.
# ============================================================

SOURCE_TIERS = {

    "Wombleleader Racing": 1,
    "GnC Racing": 1,
    "Digit Racing": 1,

    "ProdigyRacing": 2,

    "MotoSeventeenX": 3
}


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

    return (
        text.strip("_")[:80]
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
# DATABASE
# ============================================================

def load_transcript_database():

    database = load_json(
        TRANSCRIPT_DATABASE_FILE,
        {
            "version": 2,
            "weeks": {}
        }
    )

    if not isinstance(
        database,
        dict
    ):

        database = {
            "version": 2,
            "weeks": {}
        }

    database[
        "version"
    ] = 2

    database.setdefault(
        "weeks",
        {}
    )

    return database


# ============================================================
# CURRENT WEEK
# ============================================================

def get_latest_week(source_database):

    weeks = source_database.get(
        "weeks",
        {}
    )

    if not weeks:

        raise RuntimeError(
            "No community source weeks found."
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
# SOURCE TIER
# ============================================================

def source_tier(channel):

    normalized_channel = (
        normalize_text(
            channel
        )
    )

    for known_channel, tier in (
        SOURCE_TIERS.items()
    ):

        if (
            normalize_text(
                known_channel
            )
            in normalized_channel
        ):

            return tier

    return 2


# ============================================================
# VIDEO SCORE
# ============================================================

def video_priority_score(video):

    tier = source_tier(
        video.get(
            "channel",
            ""
        )
    )

    # Tier dominates all other criteria.
    tier_score = {
        1: 1000,
        2: 500,
        3: 0
    }.get(
        tier,
        500
    )

    content_score = (
        CONTENT_PRIORITY.get(
            video.get(
                "content_type",
                "OTHER"
            ),
            1
        )
        * 20
    )

    temporal_score = (
        TEMPORAL_PRIORITY.get(
            video.get(
                "temporal_confidence",
                "UNVERIFIED"
            ),
            1
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

    if not isinstance(
        source_score,
        (int, float)
    ):
        source_score = 0

    return (
        tier_score
        + content_score
        + temporal_score
        + source_score
    )


# ============================================================
# SELECT WEEK VIDEOS
# ============================================================

def select_week_videos(week_data):

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
    # Guarantee Tier-1 sources first.
    # --------------------------------------------------------

    tier1_channels = [
        channel
        for channel, tier
        in SOURCE_TIERS.items()
        if tier == 1
    ]

    for target_channel in tier1_channels:

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

        candidate = matches[0]

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
    # Fill remaining slots by priority score.
    # --------------------------------------------------------

    for video in videos:

        if (
            len(selected)
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
# TRANSCRIPT PARSER
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
                str
            ):

                if item.strip():

                    parts.append(
                        item.strip()
                    )

            elif isinstance(
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

        return " ".join(
            parts
        ).strip()

    return ""


# ============================================================
# REQUEST CONTROLLER
# ============================================================

class ApiController:

    def __init__(self):

        self.requests_used = 0

        self.last_request_time = None

        self.rate_limited = False


    def can_request(self):

        return (
            not self.rate_limited
            and self.requests_used
            < MAX_API_REQUESTS_PER_RUN
        )


    def wait_if_needed(self):

        if self.last_request_time is None:
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
                f"waiting {remaining:.1f}s"
            )

            time.sleep(
                remaining
            )


    def register_request(self):

        self.requests_used += 1

        self.last_request_time = (
            time.monotonic()
        )


    def set_rate_limited(self):

        self.rate_limited = True


# ============================================================
# SUPADATA REQUEST
# ============================================================

def request_native_transcript(
    controller,
    api_key,
    video
):

    if not controller.can_request():

        return {
            "status":
                "REQUEST_BUDGET_EXHAUSTED",

            "text":
                "",

            "language":
                None,

            "http_status":
                None,

            "payload":
                None
        }

    controller.wait_if_needed()

    video_url = (
        video.get(
            "url"
        )
        or (
            "https://www.youtube.com/watch?v="
            f"{video['video_id']}"
        )
    )

    headers = {
        "x-api-key":
            api_key
    }

    params = {
        "url":
            video_url,

        "text":
            "true",

        # Native only.
        # Never trigger AI transcription in this collector.
        "mode":
            "native"
    }

    try:

        response = requests.get(
            SUPADATA_ENDPOINT,
            headers=headers,
            params=params,
            timeout=90
        )

    except Exception as exc:

        controller.register_request()

        return {
            "status":
                "REQUEST_ERROR",

            "text":
                "",

            "language":
                None,

            "http_status":
                None,

            "payload": {
                "error":
                    str(exc)
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

        controller.set_rate_limited()

        return {
            "status":
                "RATE_LIMIT",

            "text":
                "",

            "language":
                None,

            "http_status":
                429,

            "payload":
                payload
        }

    if response.status_code != 200:

        return {
            "status":
                f"HTTP_{response.status_code}",

            "text":
                "",

            "language":
                None,

            "http_status":
                response.status_code,

            "payload":
                payload
        }

    text = extract_text_from_content(
        payload.get(
            "content"
        )
        if isinstance(
            payload,
            dict
        )
        else None
    )

    if text:

        return {
            "status":
                "AVAILABLE",

            "text":
                text,

            "language":
                payload.get(
                    "lang"
                ),

            "http_status":
                response.status_code,

            "payload":
                payload
        }

    return {
        "status":
            "NO_NATIVE_TRANSCRIPT",

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
            ),

        "http_status":
            response.status_code,

        "payload":
            payload
    }


# ============================================================
# TRANSCRIPT FILE
# ============================================================

def transcript_file_path(
    week_key,
    video
):

    return (
        TRANSCRIPT_STORAGE_DIR
        / week_key
        / (
            f"{video['video_id']}_"
            f"{safe_filename(video.get('channel'))}.json"
        )
    )


def save_transcript(
    week_key,
    video,
    result
):

    path = transcript_file_path(
        week_key,
        video
    )

    text = result[
        "text"
    ]

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

        "source_tier":
            source_tier(
                video.get(
                    "channel"
                )
            ),

        "language":
            result.get(
                "language"
            ),

        "mode":
            "native",

        "word_count":
            len(
                text.split()
            ),

        "character_count":
            len(
                text
            ),

        "saved_at":
            now_iso(),

        "transcript":
            text
    }

    save_json(
        path,
        data
    )

    return (
        str(path),
        data[
            "word_count"
        ]
    )


# ============================================================
# WEEK RECORD
# ============================================================

def ensure_week_record(
    database,
    week_key,
    week_data
):

    weeks = database[
        "weeks"
    ]

    week = weeks.setdefault(
        week_key,
        {
            "created_at":
                now_iso(),

            "videos":
                {}
        }
    )

    week[
        "updated_at"
    ] = now_iso()

    week[
        "track"
    ] = week_data.get(
        "track"
    )

    week[
        "race_class"
    ] = week_data.get(
        "race_class"
    )

    week[
        "direction"
    ] = week_data.get(
        "direction"
    )

    week.setdefault(
        "videos",
        {}
    )

    return week


# ============================================================
# SYNC VIDEOS
# ============================================================

def sync_videos(
    week_record,
    selected_videos
):

    records = week_record[
        "videos"
    ]

    for video in selected_videos:

        video_id = video[
            "video_id"
        ]

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

                "source_tier":
                    source_tier(
                        video.get(
                            "channel"
                        )
                    ),

                "priority_score":
                    video_priority_score(
                        video
                    ),

                "status":
                    "NEW",

                "transcript_file":
                    None,

                "word_count":
                    0,

                "attempt_count":
                    0,

                "last_attempt":
                    None,

                "error":
                    None
            }

        else:

            records[
                video_id
            ][
                "priority_score"
            ] = video_priority_score(
                video
            )

            records[
                video_id
            ][
                "source_tier"
            ] = source_tier(
                video.get(
                    "channel"
                )
            )


# ============================================================
# PROCESS NEW VIDEOS
# ============================================================

def process_videos(
    controller,
    api_key,
    week_key,
    week_record,
    selected_videos
):

    lookup = {
        video[
            "video_id"
        ]:
            video
        for video in selected_videos
    }

    records = [
        record
        for record
        in week_record[
            "videos"
        ].values()
        if record.get(
            "status"
        )
        == "NEW"
    ]

    records.sort(
        key=lambda item:
            (
                item.get(
                    "source_tier",
                    2
                ),
                -item.get(
                    "priority_score",
                    0
                )
            )
    )

    for record in records:

        if not controller.can_request():
            break

        video = lookup.get(
            record[
                "video_id"
            ]
        )

        if not video:
            continue

        print()

        print(
            f"Starting video   : "
            f"{record.get('channel')}"
        )

        print(
            f"Source tier      : "
            f"{record.get('source_tier')}"
        )

        print(
            f"Video ID         : "
            f"{record.get('video_id')}"
        )

        print(
            f"Type             : "
            f"{record.get('content_type')}"
        )

        result = request_native_transcript(
            controller,
            api_key,
            video
        )

        record[
            "attempt_count"
        ] += 1

        record[
            "last_attempt"
        ] = now_iso()

        print(
            f"Result           : "
            f"{result['status']}"
        )

        if (
            result[
                "status"
            ]
            == "AVAILABLE"
        ):

            path, word_count = (
                save_transcript(
                    week_key,
                    video,
                    result
                )
            )

            record[
                "status"
            ] = "AVAILABLE"

            record[
                "transcript_file"
            ] = path

            record[
                "word_count"
            ] = word_count

            record[
                "error"
            ] = None

            print(
                "Transcript       : YES"
            )

            print(
                f"Words            : "
                f"{word_count:,}"
            )

        elif (
            result[
                "status"
            ]
            == "NO_NATIVE_TRANSCRIPT"
        ):

            record[
                "status"
            ] = "NO_NATIVE"

            record[
                "error"
            ] = (
                "NO_NATIVE_TRANSCRIPT"
            )

            print(
                "Transcript       : NO"
            )

        elif (
            result[
                "status"
            ]
            == "RATE_LIMIT"
        ):

            record[
                "status"
            ] = "NEW"

            record[
                "error"
            ] = "RATE_LIMIT"

            print(
                "Supadata returned HTTP 429."
            )

            break

        else:

            record[
                "status"
            ] = "NEW"

            record[
                "error"
            ] = result[
                "status"
            ]


# ============================================================
# MAIN
# ============================================================

def main():

    api_key = os.environ.get(
        "SUPADATA_API_KEY"
    )

    if not api_key:

        raise RuntimeError(
            "SUPADATA_API_KEY not available."
        )

    source_database = load_json(
        COMMUNITY_SOURCES_FILE,
        None
    )

    if not source_database:

        raise RuntimeError(
            "community_sources.json not found."
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

    sync_videos(
        week_record,
        selected_videos
    )

    controller = ApiController()

    print(
        "=" * 88
    )

    print(
        "GT7 COMMUNITY TRANSCRIPT COLLECTOR V2"
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
        f"{week_data.get('track')}"
    )

    print(
        f"Race class       : "
        f"{week_data.get('race_class')}"
    )

    print(
        f"Videos tracked   : "
        f"{len(selected_videos)}"
    )

    print(
        f"Transcript mode  : NATIVE ONLY"
    )

    print(
        f"API budget/run   : "
        f"{MAX_API_REQUESTS_PER_RUN}"
    )

    print()

    print(
        "VIDEO PRIORITY"
    )

    print(
        "-" * 88
    )

    for video in selected_videos:

        print(
            f"T{source_tier(video.get('channel'))} | "
            f"{video.get('channel')} | "
            f"{video.get('content_type')} | "
            f"{video.get('title')}"
        )

    process_videos(
        controller,
        api_key,
        week_key,
        week_record,
        selected_videos
    )

    week_record[
        "last_run"
    ] = {
        "timestamp":
            now_iso(),

        "requests":
            controller.requests_used,

        "rate_limited":
            controller.rate_limited
    }

    save_json(
        TRANSCRIPT_DATABASE_FILE,
        transcript_database
    )

    statuses = {}

    for record in (
        week_record[
            "videos"
        ].values()
    ):

        status = record.get(
            "status",
            "UNKNOWN"
        )

        statuses[
            status
        ] = (
            statuses.get(
                status,
                0
            )
            + 1
        )

    print()

    print(
        "=" * 88
    )

    print(
        "FINAL STATUS"
    )

    print(
        "=" * 88
    )

    print(
        f"Available         : "
        f"{statuses.get('AVAILABLE',0)}"
    )

    print(
        f"No native         : "
        f"{statuses.get('NO_NATIVE',0)}"
    )

    print(
        f"New / waiting     : "
        f"{statuses.get('NEW',0)}"
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

    if not available:

        print(
            "None."
        )

    else:

        for record in available:

            print(
                f"{record.get('channel')} | "
                f"{record.get('word_count',0):,} words"
            )

            print(
                f"  "
                f"{record.get('transcript_file')}"
            )

    print()

    print(
        f"Database file    : "
        f"{TRANSCRIPT_DATABASE_FILE}"
    )

    print(
        "=" * 88
    )


if __name__ == "__main__":

    main()