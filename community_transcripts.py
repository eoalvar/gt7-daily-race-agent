import json
import os
import time
import re
from pathlib import Path
from datetime import datetime, UTC

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

SUPADATA_BASE_URL = (
    "https://api.supadata.ai/v1"
)

SUPADATA_API_KEY = os.environ.get(
    "SUPADATA_API_KEY",
    ""
)

REQUEST_TIMEOUT = 60

POLL_INTERVAL_SECONDS = 2
MAX_POLL_ATTEMPTS = 60


# ============================================================
# SOURCE POLICY
# ============================================================

STRATEGY_CHANNEL = "Digit Racing"
LAP_GUIDE_CHANNEL = "GnC Racing"


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
        text or "unknown"
    ).lower()

    text = re.sub(
        r"[^a-z0-9]+",
        "_",
        text
    )

    return text.strip(
        "_"
    )


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
        2
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
# SUPADATA RESPONSE PARSING
# ============================================================

def transcript_text_from_payload(
    payload
):

    if not isinstance(
        payload,
        dict
    ):

        return None

    content = payload.get(
        "content"
    )

    # --------------------------------------------------------
    # PLAIN STRING
    # --------------------------------------------------------

    if isinstance(
        content,
        str
    ):

        cleaned = normalize_space(
            content
        )

        return (
            cleaned
            if cleaned
            else None
        )

    # --------------------------------------------------------
    # SEGMENT LIST
    # --------------------------------------------------------

    if isinstance(
        content,
        list
    ):

        pieces = []

        for item in content:

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

    # --------------------------------------------------------
    # POSSIBLE NESTED RESULT
    # --------------------------------------------------------

    result = payload.get(
        "result"
    )

    if isinstance(
        result,
        dict
    ):

        return transcript_text_from_payload(
            result
        )

    return None


# ============================================================
# SUPADATA REQUEST
# ============================================================

def supadata_headers():

    return {
        "x-api-key":
            SUPADATA_API_KEY,

        "Accept":
            "application/json"
    }


def request_transcript(
    video_url
):

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
                    "true"
            },
            timeout=REQUEST_TIMEOUT
        )

    except Exception as exc:

        return {
            "success":
                False,

            "status":
                "REQUEST_ERROR",

            "http_status":
                None,

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

    # --------------------------------------------------------
    # IMMEDIATE RESULT
    # --------------------------------------------------------

    if http_status == 200:

        text = transcript_text_from_payload(
            payload
        )

        if text:

            return {
                "success":
                    True,

                "status":
                    "IMMEDIATE_SUCCESS",

                "delivery_mode":
                    "IMMEDIATE",

                "http_status":
                    http_status,

                "payload":
                    payload,

                "text":
                    text
            }

        return {
            "success":
                False,

            "status":
                "NO_TRANSCRIPT_CONTENT",

            "delivery_mode":
                "NONE",

            "http_status":
                http_status,

            "payload":
                payload
        }

    # --------------------------------------------------------
    # ASYNC RESULT
    # --------------------------------------------------------

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
                    "ASYNC_NO_JOB_ID",

                "delivery_mode":
                    "ASYNC",

                "http_status":
                    http_status,

                "payload":
                    payload
            }

        return poll_transcript_job(
            job_id
        )

    # --------------------------------------------------------
    # RATE LIMIT
    # --------------------------------------------------------

    if http_status == 429:

        return {
            "success":
                False,

            "status":
                "RATE_LIMIT",

            "http_status":
                http_status,

            "payload":
                payload
        }

    return {
        "success":
            False,

        "status":
            f"HTTP_{http_status}",

        "http_status":
            http_status,

        "payload":
            payload
    }


# ============================================================
# ASYNC JOB POLLING
# ============================================================

def poll_transcript_job(
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
            f"Polling job      : "
            f"{attempt}/{MAX_POLL_ATTEMPTS}"
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
                    "POLL_REQUEST_ERROR",

                "delivery_mode":
                    "ASYNC",

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
                    "RATE_LIMIT",

                "delivery_mode":
                    "ASYNC",

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
                    f"HTTP_{http_status}",

                "delivery_mode":
                    "ASYNC",

                "job_id":
                    job_id,

                "http_status":
                    http_status,

                "payload":
                    payload
            }

        status = (
            payload.get(
                "status"
            )
            or ""
        ).lower()

        print(
            f"Job status       : "
            f"{status or 'UNKNOWN'}"
        )

        # ----------------------------------------------------
        # COMPLETED
        # ----------------------------------------------------

        if status == "completed":

            text = transcript_text_from_payload(
                payload
            )

            if text:

                return {
                    "success":
                        True,

                    "status":
                        "ASYNC_SUCCESS",

                    "delivery_mode":
                        "ASYNC",

                    "job_id":
                        job_id,

                    "http_status":
                        http_status,

                    "payload":
                        payload,

                    "text":
                        text
                }

            return {
                "success":
                    False,

                "status":
                    "ASYNC_COMPLETED_NO_CONTENT",

                "delivery_mode":
                    "ASYNC",

                "job_id":
                    job_id,

                "http_status":
                    http_status,

                "payload":
                    payload
            }

        # ----------------------------------------------------
        # FAILED
        # ----------------------------------------------------

        if status == "failed":

            return {
                "success":
                    False,

                "status":
                    "ASYNC_FAILED",

                "delivery_mode":
                    "ASYNC",

                "job_id":
                    job_id,

                "http_status":
                    http_status,

                "payload":
                    payload
            }

        # ----------------------------------------------------
        # STILL PROCESSING
        # ----------------------------------------------------

        if status in {
            "queued",
            "active",
            "",
        }:

            time.sleep(
                POLL_INTERVAL_SECONDS
            )

            continue

        time.sleep(
            POLL_INTERVAL_SECONDS
        )

    return {
        "success":
            False,

        "status":
            "ASYNC_TIMEOUT",

        "delivery_mode":
            "ASYNC",

        "job_id":
            job_id
    }


# ============================================================
# RECORD CREATION
# ============================================================

def create_transcript_record(
    week_key,
    video,
    result
):

    text = result.get(
        "text"
    )

    word_count = (
        len(
            text.split()
        )
        if text
        else 0
    )

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
            (
                "AVAILABLE"
                if result.get(
                    "success"
                )
                else result.get(
                    "status",
                    "UNAVAILABLE"
                )
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
            word_count,

        "character_count":
            (
                len(
                    text
                )
                if text
                else 0
            ),

        "transcript":
            text,

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

    if not SUPADATA_API_KEY:

        raise RuntimeError(
            "SUPADATA_API_KEY is not configured."
        )

    TRANSCRIPT_DIR.mkdir(
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
        f"Selected sources : "
        f"{len(selected)}"
    )

    print("")

    print(
        "PRIMARY SOURCES"
    )

    print(
        "-" * 88
    )

    if not selected:

        print(
            "No primary community sources selected."
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
    reused_count = 0
    api_requests = 0
    rate_limited = False

    run_results = []

    for index, video in enumerate(
        selected,
        start=1
    ):

        video_id = video.get(
            "video_id"
        )

        print(
            "=" * 88
        )

        print(
            f"[{index}/{len(selected)}] "
            f"{video.get('channel')} "
            f"- {video.get('purpose')}"
        )

        print(
            "=" * 88
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

        existing = get_existing_record(
            transcript_database,
            video_id
        )

        # ====================================================
        # REUSE EXISTING TRANSCRIPT
        # ====================================================

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

            # Keep purpose aligned with current source policy.
            record[
                "purpose"
            ] = video.get(
                "purpose"
            )

            print(
                "Result           : "
                "REUSED_EXISTING"
            )

            print(
                f"Words            : "
                f"{record.get('word_count',0):,}"
            )

            path = save_transcript_file(
                record
            )

            print(
                f"Saved file       : "
                f"{path}"
            )

            reused_count += 1
            available_count += 1

            run_results.append(
                record
            )

            transcript_database[
                "videos"
            ][
                video_id
            ] = record

            print("")

            continue

        # ====================================================
        # REQUEST SUPADATA
        # ====================================================

        print(
            "Result           : REQUESTING"
        )

        result = request_transcript(
            video.get(
                "url"
            )
        )

        api_requests += 1

        print(
            f"API status       : "
            f"{result.get('status')}"
        )

        if result.get(
            "http_status"
        ) is not None:

            print(
                f"HTTP status      : "
                f"{result.get('http_status')}"
            )

        if result.get(
            "delivery_mode"
        ):

            print(
                f"Delivery mode    : "
                f"{result.get('delivery_mode')}"
            )

        if result.get(
            "job_id"
        ):

            print(
                f"Job ID           : "
                f"{result.get('job_id')}"
            )

        record = create_transcript_record(
            week_key,
            video,
            result
        )

        transcript_database[
            "videos"
        ][
            video_id
        ] = record

        run_results.append(
            record
        )

        if result.get(
            "success"
        ):

            available_count += 1

            path = save_transcript_file(
                record
            )

            print(
                "Transcript       : YES"
            )

            print(
                f"Words            : "
                f"{record.get('word_count',0):,}"
            )

            print(
                f"Characters       : "
                f"{record.get('character_count',0):,}"
            )

            print(
                f"Saved file       : "
                f"{path}"
            )

            preview = normalize_space(
                record.get(
                    "transcript"
                )
            )

            print(
                "Preview          :"
            )

            print(
                f"  {preview[:900]}"
            )

        else:

            unavailable_count += 1

            print(
                "Transcript       : NO"
            )

            if result.get(
                "payload"
            ):

                print(
                    "API payload      :"
                )

                print(
                    json.dumps(
                        result.get(
                            "payload"
                        ),
                        ensure_ascii=False
                    )[
                        :1500
                    ]
                )

            if (
                result.get(
                    "status"
                )
                == "RATE_LIMIT"
            ):

                rate_limited = True

                print(
                    "Rate limit reached. "
                    "Stopping further API calls."
                )

                break

        print("")

    # ========================================================
    # DATABASE METADATA
    # ========================================================

    transcript_database[
        "version"
    ] = 2

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
            LAP_GUIDE_CHANNEL
    }

    save_json(
        TRANSCRIPT_DB_FILE,
        transcript_database
    )

    # ========================================================
    # SUMMARY
    # ========================================================

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
        f"Primary sources    : "
        f"{len(selected)}"
    )

    print(
        f"Transcripts ready  : "
        f"{available_count}"
    )

    print(
        f"Reused existing    : "
        f"{reused_count}"
    )

    print(
        f"Unavailable        : "
        f"{unavailable_count}"
    )

    print(
        f"API requests used  : "
        f"{api_requests}"
    )

    print(
        f"Rate limited       : "
        f"{'YES' if rate_limited else 'No'}"
    )

    print("")

    print(
        "PRIMARY TRANSCRIPT STATUS"
    )

    print(
        "-" * 88
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
        "=" * 88
    )


if __name__ == "__main__":

    main()