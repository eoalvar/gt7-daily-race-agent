import json
import os
import time
import requests

from pathlib import Path


# ============================================================
# CONFIG
# ============================================================

DATA_DIR = Path("data")
COMMUNITY_FILE = DATA_DIR / "community_sources.json"

OUTPUT_DIR = DATA_DIR / "community_extract_test"
OUTPUT_FILE = OUTPUT_DIR / "extract_test_results.json"

SUPADATA_EXTRACT_ENDPOINT = (
    "https://api.supadata.ai/v1/extract"
)

POLL_INTERVAL_SECONDS = 5
MAX_POLL_ATTEMPTS = 36


# ============================================================
# TEST SOURCES
# ============================================================

TARGET_CHANNELS = [
    "Wombleleader Racing",
    "GnC Racing"
]


# ============================================================
# EXTRACTION PROMPT
# ============================================================

EXTRACTION_PROMPT = """
Analyze this Gran Turismo 7 Daily Race C video as a racing coach.

Extract only information actually supported by the video. Do not invent
braking points, gears, tyre strategy, pit strategy, car recommendations,
or other details that are not stated or clearly demonstrated.

Return practical information useful to a GT7 driver preparing for the
same Daily Race C.

Focus on:

1. Race format and regulations mentioned in the video.
2. Recommended cars and meta observations.
3. Qualifying and lap-time advice.
4. Corner-by-corner driving advice.
5. Braking points and visual braking references.
6. Recommended gears where explicitly mentioned.
7. Racing line, turn-in, apex and track-limit advice.
8. Throttle application and acceleration points.
9. Kerb usage.
10. Tyre choice and tyre management.
11. Fuel management.
12. Pit-stop strategy and recommended pit window.
13. Racecraft, overtaking and defensive advice.
14. Common mistakes or warnings.
15. The five most useful takeaways.

When information is uncertain, conflicting, or not discussed, reflect
that rather than guessing.
"""


# ============================================================
# JSON SCHEMA
# ============================================================

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "race_summary": {
            "type": "string"
        },

        "cars": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "car": {
                        "type": "string"
                    },
                    "recommendation": {
                        "type": "string"
                    },
                    "reason": {
                        "type": "string"
                    }
                },
                "required": [
                    "car",
                    "recommendation",
                    "reason"
                ]
            }
        },

        "qualifying_advice": {
            "type": "array",
            "items": {
                "type": "string"
            }
        },

        "corner_advice": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "section": {
                        "type": "string"
                    },
                    "braking_reference": {
                        "type": "string"
                    },
                    "gear": {
                        "type": "string"
                    },
                    "line": {
                        "type": "string"
                    },
                    "throttle": {
                        "type": "string"
                    },
                    "kerb_usage": {
                        "type": "string"
                    },
                    "warning": {
                        "type": "string"
                    }
                },
                "required": [
                    "section",
                    "braking_reference",
                    "gear",
                    "line",
                    "throttle",
                    "kerb_usage",
                    "warning"
                ]
            }
        },

        "tyre_strategy": {
            "type": "array",
            "items": {
                "type": "string"
            }
        },

        "fuel_strategy": {
            "type": "array",
            "items": {
                "type": "string"
            }
        },

        "pit_strategy": {
            "type": "array",
            "items": {
                "type": "string"
            }
        },

        "racecraft": {
            "type": "array",
            "items": {
                "type": "string"
            }
        },

        "mistakes_and_warnings": {
            "type": "array",
            "items": {
                "type": "string"
            }
        },

        "top_takeaways": {
            "type": "array",
            "items": {
                "type": "string",
            },
            "maxItems": 5
        },

        "confidence_notes": {
            "type": "array",
            "items": {
                "type": "string"
            }
        }
    },

    "required": [
        "race_summary",
        "cars",
        "qualifying_advice",
        "corner_advice",
        "tyre_strategy",
        "fuel_strategy",
        "pit_strategy",
        "racecraft",
        "mistakes_and_warnings",
        "top_takeaways",
        "confidence_notes"
    ]
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

    return " ".join(
        text.lower().split()
    )


# ============================================================
# CURRENT WEEK
# ============================================================

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
# SELECT TEST VIDEOS
# ============================================================

def select_target_videos(week_data):

    videos = list(
        week_data
        .get(
            "videos",
            {}
        )
        .values()
    )

    selected = []

    for target_channel in TARGET_CHANNELS:

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

        # Prefer strategy/lap-guide content.
        matches.sort(
            key=lambda video: (
                video.get(
                    "content_type"
                ) in {
                    "STRATEGY",
                    "LAP_GUIDE"
                },

                video.get(
                    "priority_score",
                    0
                )
            ),
            reverse=True
        )

        selected.append(
            matches[0]
        )

    return selected


# ============================================================
# START EXTRACT JOB
# ============================================================

def create_extract_job(
    api_key,
    video
):

    headers = {
        "x-api-key":
            api_key,

        "Content-Type":
            "application/json"
    }

    payload = {
        "url":
            video[
                "url"
            ],

        "prompt":
            EXTRACTION_PROMPT,

        "schema":
            EXTRACTION_SCHEMA
    }

    try:

        response = requests.post(
            SUPADATA_EXTRACT_ENDPOINT,
            headers=headers,
            json=payload,
            timeout=120
        )

    except requests.Timeout:

        return {
            "status":
                "TIMEOUT",

            "job_id":
                None,

            "payload":
                None,

            "http_status":
                None
        }

    except Exception as exc:

        return {
            "status":
                "REQUEST_ERROR",

            "job_id":
                None,

            "payload": {
                "error":
                    str(
                        exc
                    )
            },

            "http_status":
                None
        }

    try:
        data = response.json()

    except Exception:
        data = {
            "raw":
                response.text
        }

    job_id = None

    if isinstance(
        data,
        dict
    ):

        job_id = data.get(
            "jobId"
        )

    if job_id:

        status = (
            "JOB_CREATED"
        )

    else:

        status = (
            f"HTTP_{response.status_code}"
        )

    return {
        "status":
            status,

        "job_id":
            job_id,

        "payload":
            data,

        "http_status":
            response.status_code
    }


# ============================================================
# POLL EXTRACT JOB
# ============================================================

def poll_extract_job(
    api_key,
    job_id
):

    headers = {
        "x-api-key":
            api_key
    }

    url = (
        f"{SUPADATA_EXTRACT_ENDPOINT}/"
        f"{job_id}"
    )

    last_payload = None
    last_http = None

    for attempt in range(
        1,
        MAX_POLL_ATTEMPTS + 1
    ):

        print(
            f"Polling          : "
            f"{attempt}/{MAX_POLL_ATTEMPTS}"
        )

        try:

            response = requests.get(
                url,
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

                "data":
                    None,

                "payload": {
                    "error":
                        str(
                            exc
                        )
                },

                "http_status":
                    None
            }

        last_http = (
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

            job_status = payload.get(
                "status"
            )

        print(
            f"Job status       : "
            f"{job_status or 'UNKNOWN'}"
        )

        if job_status == "completed":

            return {
                "status":
                    "COMPLETED",

                "data":
                    payload.get(
                        "data"
                    ),

                "payload":
                    payload,

                "http_status":
                    response.status_code
            }

        if job_status == "failed":

            return {
                "status":
                    "FAILED",

                "data":
                    None,

                "payload":
                    payload,

                "http_status":
                    response.status_code
            }

        if response.status_code in {
            400,
            401,
            402,
            403,
            404,
            429
        }:

            return {
                "status":
                    (
                        f"HTTP_"
                        f"{response.status_code}"
                    ),

                "data":
                    None,

                "payload":
                    payload,

                "http_status":
                    response.status_code
            }

        time.sleep(
            POLL_INTERVAL_SECONDS
        )

    return {
        "status":
            "POLL_TIMEOUT",

        "data":
            None,

        "payload":
            last_payload,

        "http_status":
            last_http
    }


# ============================================================
# PRINT RESULT
# ============================================================

def print_extracted_data(data):

    if not isinstance(
        data,
        dict
    ):

        print(
            "No structured data returned."
        )

        return

    print()

    print(
        "RACE SUMMARY"
    )

    print(
        "-" * 88
    )

    print(
        data.get(
            "race_summary",
            "N/A"
        )
    )

    print()

    print(
        "CARS"
    )

    print(
        "-" * 88
    )

    for item in data.get(
        "cars",
        []
    ):

        print(
            f"- "
            f"{item.get('car','N/A')} | "
            f"{item.get('recommendation','N/A')} | "
            f"{item.get('reason','')}"
        )

    print()

    print(
        "QUALIFYING ADVICE"
    )

    print(
        "-" * 88
    )

    for item in data.get(
        "qualifying_advice",
        []
    ):

        print(
            f"- {item}"
        )

    print()

    print(
        "CORNER ADVICE"
    )

    print(
        "-" * 88
    )

    for corner in data.get(
        "corner_advice",
        []
    ):

        print(
            f"Section          : "
            f"{corner.get('section','N/A')}"
        )

        print(
            f"Brake            : "
            f"{corner.get('braking_reference','N/A')}"
        )

        print(
            f"Gear             : "
            f"{corner.get('gear','N/A')}"
        )

        print(
            f"Line             : "
            f"{corner.get('line','N/A')}"
        )

        print(
            f"Throttle         : "
            f"{corner.get('throttle','N/A')}"
        )

        print(
            f"Kerb             : "
            f"{corner.get('kerb_usage','N/A')}"
        )

        print(
            f"Warning          : "
            f"{corner.get('warning','N/A')}"
        )

        print()

    sections = [
        (
            "TYRE STRATEGY",
            "tyre_strategy"
        ),
        (
            "FUEL STRATEGY",
            "fuel_strategy"
        ),
        (
            "PIT STRATEGY",
            "pit_strategy"
        ),
        (
            "RACECRAFT",
            "racecraft"
        ),
        (
            "MISTAKES / WARNINGS",
            "mistakes_and_warnings"
        ),
        (
            "TOP TAKEAWAYS",
            "top_takeaways"
        ),
        (
            "CONFIDENCE NOTES",
            "confidence_notes"
        )
    ]

    for title, key in sections:

        print(
            title
        )

        print(
            "-" * 88
        )

        values = data.get(
            key,
            []
        )

        if not values:

            print(
                "- None stated."
            )

        else:

            for item in values:

                print(
                    f"- {item}"
                )

        print()


# ============================================================
# MAIN
# ============================================================

def main():

    api_key = os.environ.get(
        "SUPADATA_API_KEY"
    )

    if not api_key:

        raise RuntimeError(
            "SUPADATA_API_KEY is not available."
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

    selected = select_target_videos(
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
        "GT7 COMMUNITY EXTRACT TEST"
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

    for video in selected:

        print(
            f"- "
            f"{video.get('channel')} | "
            f"{video.get('content_type')} | "
            f"{video.get('title')}"
        )

    results = []

    for index, video in enumerate(
        selected,
        start=1
    ):

        print()

        print(
            "=" * 88
        )

        print(
            f"[{index}/{len(selected)}] "
            f"{video.get('channel')}"
        )

        print(
            "=" * 88
        )

        print(
            f"Title            : "
            f"{video.get('title')}"
        )

        print(
            f"URL              : "
            f"{video.get('url')}"
        )

        created = create_extract_job(
            api_key,
            video
        )

        print(
            f"Create HTTP      : "
            f"{created['http_status']}"
        )

        print(
            f"Create status    : "
            f"{created['status']}"
        )

        print(
            f"Job ID           : "
            f"{created['job_id']}"
        )

        if not created[
            "job_id"
        ]:

            print(
                "No extract job created."
            )

            print(
                json.dumps(
                    created[
                        "payload"
                    ],
                    ensure_ascii=False,
                    indent=2
                )[:2000]
            )

            results.append({
                "channel":
                    video.get(
                        "channel"
                    ),

                "video_id":
                    video.get(
                        "video_id"
                    ),

                "title":
                    video.get(
                        "title"
                    ),

                "status":
                    created[
                        "status"
                    ],

                "data":
                    None
            })

            continue

        result = poll_extract_job(
            api_key,
            created[
                "job_id"
            ]
        )

        print(
            f"Final status     : "
            f"{result['status']}"
        )

        data = result.get(
            "data"
        )

        if data:

            print_extracted_data(
                data
            )

        else:

            print(
                "No extracted data."
            )

            print(
                json.dumps(
                    result.get(
                        "payload"
                    ),
                    ensure_ascii=False,
                    indent=2
                )[:2000]
            )

        video_result = {
            "week":
                week_key,

            "channel":
                video.get(
                    "channel"
                ),

            "video_id":
                video.get(
                    "video_id"
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

            "job_id":
                created[
                    "job_id"
                ],

            "status":
                result[
                    "status"
                ],

            "data":
                data
        }

        results.append(
            video_result
        )

        individual_file = (
            OUTPUT_DIR
            / (
                f"{video.get('video_id')}"
                f"_extract.json"
            )
        )

        save_json(
            individual_file,
            video_result
        )

    summary = {
        "week":
            week_key,

        "videos_tested":
            len(
                selected
            ),

        "results":
            results
    }

    save_json(
        OUTPUT_FILE,
        summary
    )

    completed = sum(
        1
        for item in results
        if item.get(
            "status"
        )
        == "COMPLETED"
    )

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
        f"{len(selected)}"
    )

    print(
        f"Extracts completed  : "
        f"{completed}"
    )

    print(
        f"Not completed       : "
        f"{len(selected) - completed}"
    )

    print(
        f"Results file        : "
        f"{OUTPUT_FILE}"
    )

    print(
        "=" * 88
    )


if __name__ == "__main__":

    main()