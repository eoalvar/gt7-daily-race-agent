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

# Previous test directories that may already contain
# successfully downloaded Supadata transcripts.
LEGACY_TRANSCRIPT_DIRS = [
    DATA_DIR
    / "community_supadata_test"
    / "transcripts",

    DATA_DIR
    / "community_transcript_test"
    / "transcripts",
]

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


# ============================================================
# TRANSCRIPT TEXT EXTRACTION
# ============================================================

def transcript_text_from_payload(
    payload
):

    if payload is None:
        return None

    # --------------------------------------------------------
    # RAW STRING
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # LIST
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # DICTIONARY
    # --------------------------------------------------------

    if not isinstance(
        payload,
        dict
    ):

        return None

    # Direct transcript fields first.

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

    # Supadata normally uses content.

    content = payload.get(
        "content"
    )

    text = transcript_text_from_payload(
        content
    )

    if text:
        return text

    # Some saved files may contain a result/payload/data
    # wrapper.

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
        3
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
# LEGACY TRANSCRIPT CACHE
# ============================================================

def find_legacy_transcript(
    video_id
):

    if not video_id:
        return None

    # --------------------------------------------------------
    # SEARCH KNOWN TEST DIRECTORIES
    # --------------------------------------------------------

    for directory in LEGACY_TRANSCRIPT_DIRS:

        if not directory.exists():
            continue

        matches = list(
            directory.glob(
                f"{video_id}_*.json"
            )
        )

        matches.extend(
            directory.glob(
                f"{video_id}.json"
            )
        )

        for path in matches:

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

                    "source":
                        str(
                            path
                        )
                }

    # --------------------------------------------------------
    # BROADER SAFE FALLBACK
    #
    # Search JSON files under known community test folders.
    # This allows us to recover transcripts even if an older
    # test used a different filename format.
    # --------------------------------------------------------

    broader_dirs = [
        DATA_DIR
        / "community_supadata_test",

        DATA_DIR
        / "community_transcript_test",
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

            # ------------------------------------------------
            # DIRECT FILE
            # ------------------------------------------------

            text = transcript_text_from_payload(
                payload
            )

            if text:

                # Avoid accidentally treating a large test
                # result database itself as the transcript if
                # the video-specific text cannot be isolated.

                if (
                    video_id
                    in path.name
                ):

                    return {
                        "text":
                            text,

                        "source":
                            str(
                                path
                            )
                    }

            # ------------------------------------------------
            # LIST OF TEST RESULTS
            # ------------------------------------------------

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

                        "source":
                            str(
                                path
                            )
                    }

    return None


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
                    "PLAN_LIMIT",

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

        status = normalize_space(
            payload.get(
                "status",
                ""
            )
        ).lower()

        print(
            f"Job status       : "
            f"{status or 'UNKNOWN'}"
        )

        text = transcript_text_from_payload(
            payload
        )

        # Some APIs may already include transcript content
        # before or without an explicit "completed" status.

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

        if status in {
            "completed",
            "complete",
            "done",
            "success",
        }:

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

        if status in {
            "failed",
            "error",
        }:

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
# SUPADATA REQUEST
# ============================================================

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
                    "true",
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
    # PLAN / USAGE LIMIT
    # --------------------------------------------------------

    if http_status == 429:

        return {
            "success":
                False,

            "status":
                "PLAN_LIMIT",

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
# RECORD CREATION
# ============================================================

def create_available_record(
    week_key,
    video,
    text,
    api_status,
    delivery_mode,
    cache_source=None,
    http_status=None,
    job_id=None
):

    text = normalize_space(
        text
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
            "AVAILABLE",

        "api_status":
            api_status,

        "delivery_mode":
            delivery_mode,

        "http_status":
            http_status,

        "job_id":
            job_id,

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

    print(
        "=" * 88
    )

    print(
        "GT7 COMMUNITY TRANSCRIPT COLLECTOR V3"
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
    api_requests = 0

    # Once the account-level Supadata quota is known to be
    # exhausted, no more API calls are made in the same run.
    # Local/database cache processing continues normally.

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

        # ====================================================
        # 1. REUSE DEFINITIVE DATABASE
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

            print(
                "Result           : "
                "REUSED_DATABASE"
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

            reused_database_count += 1
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
        # 2. REUSE LEGACY TEST TRANSCRIPTS
        # ====================================================

        legacy = find_legacy_transcript(
            video_id
        )

        if legacy:

            record = create_available_record(
                week_key=week_key,
                video=video,
                text=legacy[
                    "text"
                ],
                api_status="LEGACY_CACHE",
                delivery_mode="LOCAL_CACHE",
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

            available_count += 1
            reused_legacy_count += 1

            run_results.append(
                record
            )

            print("")

            continue

        # ====================================================
        # 3. NO LOCAL TRANSCRIPT
        # ====================================================

        if supadata_plan_limit:

            result = {
                "success":
                    False,

                "status":
                    "PLAN_LIMIT_SKIPPED",

                "http_status":
                    429,
            }

            record = create_unavailable_record(
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

            unavailable_count += 1

            print(
                "Result           : "
                "PLAN_LIMIT_SKIPPED"
            )

            print(
                "Transcript       : NO"
            )

            print(
                "Reason           : "
                "Supadata plan limit was "
                "already detected earlier "
                "in this run."
            )

            print("")

            continue

        # ====================================================
        # 4. REQUEST SUPADATA
        # ====================================================

        if not SUPADATA_API_KEY:

            result = {
                "success":
                    False,

                "status":
                    "API_KEY_MISSING",
            }

        else:

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

        # ====================================================
        # SUCCESS
        # ====================================================

        if result.get(
            "success"
        ):

            record = create_available_record(
                week_key=week_key,
                video=video,
                text=result.get(
                    "text"
                ),
                api_status=result.get(
                    "status"
                ),
                delivery_mode=result.get(
                    "delivery_mode"
                ),
                http_status=result.get(
                    "http_status"
                ),
                job_id=result.get(
                    "job_id"
                )
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

        # ====================================================
        # FAILURE
        # ====================================================

        else:

            record = create_unavailable_record(
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
                == "PLAN_LIMIT"
            ):

                supadata_plan_limit = True

                print(
                    "Supadata plan usage "
                    "limit detected."
                )

                print(
                    "Further API calls will "
                    "be skipped, but local "
                    "cache processing will continue."
                )

        print("")

    # ========================================================
    # DATABASE METADATA
    # ========================================================

    transcript_database[
        "version"
    ] = 3

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
        f"API requests used  : "
        f"{api_requests}"
    )

    print(
        f"Supadata plan limit: "
        f"{'YES' if supadata_plan_limit else 'No'}"
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

            print(
                f"  Source  : "
                f"{record.get('api_status')}"
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
        "-" * 88
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
        "=" * 88
    )


if __name__ == "__main__":

    main()