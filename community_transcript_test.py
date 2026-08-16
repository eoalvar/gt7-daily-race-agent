import json
import re
import subprocess
import shutil

from pathlib import Path


# ============================================================
# CONFIG
# ============================================================

DATA_DIR = Path("data")
COMMUNITY_FILE = DATA_DIR / "community_sources.json"

TRANSCRIPT_DIR = Path("data/community_transcript_test")

MAX_VIDEOS_TO_TEST = 8

# Priority channels requested / selected for the first test.
PRIORITY_CHANNELS = [
    "Wombleleader Racing",
    "GnC Racing",
    "MotoSeventeenX",
    "ProdigyRacing",
    "Digit Racing"
]

# Content types preferred for useful Community Intelligence.
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


def channel_is_priority(channel):

    normalized = normalize_text(
        channel
    )

    for priority in PRIORITY_CHANNELS:

        if normalize_text(
            priority
        ) in normalized:

            return True

    return False


# ============================================================
# GET CURRENT WEEK
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
# VIDEO SELECTION
# ============================================================

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
    used_channels = set()

    # --------------------------------------------------------
    # First pass:
    # Try to include one video from each preferred channel.
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

        video = matches[0]

        video_id = video.get(
            "video_id"
        )

        if not video_id:
            continue

        if any(
            item.get(
                "video_id"
            )
            == video_id
            for item in selected
        ):
            continue

        selected.append(
            video
        )

        used_channels.add(
            normalize_text(
                video.get(
                    "channel",
                    ""
                )
            )
        )

    # --------------------------------------------------------
    # Second pass:
    # Add highest-ranked remaining videos.
    # --------------------------------------------------------

    for video in videos:

        if len(
            selected
        ) >= MAX_VIDEOS_TO_TEST:

            break

        video_id = video.get(
            "video_id"
        )

        if not video_id:
            continue

        if any(
            item.get(
                "video_id"
            )
            == video_id
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
# CLEAN OUTPUT DIRECTORY
# ============================================================

def prepare_output_dir():

    if TRANSCRIPT_DIR.exists():

        shutil.rmtree(
            TRANSCRIPT_DIR
        )

    TRANSCRIPT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )


# ============================================================
# LIST SUBTITLES
# ============================================================

def list_subtitles(video):

    video_id = video[
        "video_id"
    ]

    url = video.get(
        "url"
    ) or (
        "https://www.youtube.com/watch?v="
        f"{video_id}"
    )

    command = [
        "yt-dlp",
        "--ignore-errors",
        "--skip-download",
        "--list-subs",
        url
    ]

    try:

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=90
        )

    except subprocess.TimeoutExpired:

        return {
            "success":
                False,

            "status":
                "TIMEOUT",

            "stdout":
                "",

            "stderr":
                ""
        }

    except Exception as exc:

        return {
            "success":
                False,

            "status":
                "EXECUTION_ERROR",

            "stdout":
                "",

            "stderr":
                str(
                    exc
                )
        }

    combined = (
        result.stdout
        + "\n"
        + result.stderr
    )

    lower = combined.lower()

    if (
        "sign in to confirm"
        in lower
        or "not a bot"
        in lower
    ):

        status = "BOT_DETECTION"

    elif (
        "po token"
        in lower
        or "pot"
        in lower
        and "token"
        in lower
    ):

        status = "PO_TOKEN_REQUIRED"

    elif (
        "429"
        in lower
        or "too many requests"
        in lower
    ):

        status = "RATE_LIMIT"

    elif result.returncode != 0:

        status = "FAILED"

    else:

        status = "OK"

    return {
        "success":
            (
                result.returncode == 0
            ),

        "status":
            status,

        "stdout":
            result.stdout,

        "stderr":
            result.stderr
    }


# ============================================================
# DOWNLOAD SUBTITLES ONLY
# ============================================================

def download_subtitles(video):

    video_id = video[
        "video_id"
    ]

    url = video.get(
        "url"
    ) or (
        "https://www.youtube.com/watch?v="
        f"{video_id}"
    )

    video_dir = (
        TRANSCRIPT_DIR
        / video_id
    )

    video_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    output_template = str(
        video_dir
        / "%(id)s.%(ext)s"
    )

    command = [
        "yt-dlp",

        "--ignore-errors",

        "--skip-download",

        "--write-subs",

        "--write-auto-subs",

        "--sub-langs",
        "en.*,en,pt.*,pt",

        "--sub-format",
        "vtt",

        "--output",
        output_template,

        "--no-playlist",

        url
    ]

    try:

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=120
        )

    except subprocess.TimeoutExpired:

        return {
            "status":
                "TIMEOUT",

            "files":
                [],

            "stdout":
                "",

            "stderr":
                ""
        }

    except Exception as exc:

        return {
            "status":
                "EXECUTION_ERROR",

            "files":
                [],

            "stdout":
                "",

            "stderr":
                str(
                    exc
                )
        }

    files = sorted(
        video_dir.glob(
            "*"
        )
    )

    subtitle_files = [
        path
        for path in files
        if path.suffix.lower()
        in {
            ".vtt",
            ".srt",
            ".ass",
            ".ttml",
            ".srv1",
            ".srv2",
            ".srv3"
        }
    ]

    combined = (
        result.stdout
        + "\n"
        + result.stderr
    )

    lower = combined.lower()

    if subtitle_files:

        status = "SUBTITLE_DOWNLOADED"

    elif (
        "sign in to confirm"
        in lower
        or "not a bot"
        in lower
    ):

        status = "BOT_DETECTION"

    elif (
        "po token"
        in lower
        or (
            "pot"
            in lower
            and "token"
            in lower
        )
    ):

        status = "PO_TOKEN_REQUIRED"

    elif (
        "429"
        in lower
        or "too many requests"
        in lower
    ):

        status = "RATE_LIMIT"

    elif (
        "there are no subtitles"
        in lower
        or "no subtitles"
        in lower
    ):

        status = "NO_SUBTITLES"

    elif result.returncode != 0:

        status = "FAILED"

    else:

        status = "NO_FILE_CREATED"

    return {
        "status":
            status,

        "files":
            [
                str(path)
                for path
                in subtitle_files
            ],

        "stdout":
            result.stdout,

        "stderr":
            result.stderr
    }


# ============================================================
# VTT TO CLEAN TEXT
# ============================================================

def clean_vtt_text(text):

    lines = []

    seen = set()

    for raw_line in text.splitlines():

        line = raw_line.strip()

        if not line:
            continue

        if line == "WEBVTT":
            continue

        if line.startswith(
            "Kind:"
        ):

            continue

        if line.startswith(
            "Language:"
        ):

            continue

        if "-->" in line:
            continue

        if re.match(
            r"^\d+$",
            line
        ):

            continue

        line = re.sub(
            r"<[^>]+>",
            "",
            line
        )

        line = (
            line
            .replace(
                "&nbsp;",
                " "
            )
            .replace(
                "&amp;",
                "&"
            )
            .replace(
                "&quot;",
                '"'
            )
            .strip()
        )

        if not line:
            continue

        # Auto captions often repeat lines.
        key = normalize_text(
            line
        )

        if key in seen:
            continue

        seen.add(
            key
        )

        lines.append(
            line
        )

    return "\n".join(
        lines
    )


# ============================================================
# READ TRANSCRIPT FILE
# ============================================================

def extract_transcript_text(
    subtitle_files
):

    if not subtitle_files:

        return None

    # Prefer English first.
    ordered = sorted(
        subtitle_files,
        key=lambda path: (
            0
            if ".en" in path.lower()
            else 1
        )
    )

    for filename in ordered:

        path = Path(
            filename
        )

        try:

            raw = path.read_text(
                encoding="utf-8",
                errors="ignore"
            )

        except Exception:

            continue

        if not raw.strip():
            continue

        if path.suffix.lower() == ".vtt":

            cleaned = clean_vtt_text(
                raw
            )

        else:

            cleaned = raw

        if cleaned.strip():

            return {
                "file":
                    str(
                        path
                    ),

                "text":
                    cleaned
            }

    return None


# ============================================================
# SAVE SUMMARY JSON
# ============================================================

def save_test_result(
    week_key,
    results
):

    output = {
        "week":
            week_key,

        "priority_channels":
            PRIORITY_CHANNELS,

        "videos_tested":
            len(
                results
            ),

        "results":
            results
    }

    output_path = (
        TRANSCRIPT_DIR
        / "transcript_test_results.json"
    )

    output_path.write_text(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    return output_path


# ============================================================
# MAIN
# ============================================================

def main():

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

    prepare_output_dir()

    print(
        "=" * 88
    )

    print(
        "GT7 COMMUNITY TRANSCRIPT TEST"
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
        "TRANSCRIPT TEST RESULTS"
    )

    print(
        "=" * 88
    )

    for index, video in enumerate(
        selected,
        start=1
    ):

        video_id = video[
            "video_id"
        ]

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
            f"{video_id}"
        )

        # ----------------------------------------------------
        # Step 1: list subtitles
        # ----------------------------------------------------

        subtitle_listing = (
            list_subtitles(
                video
            )
        )

        print(
            f"List subtitles   : "
            f"{subtitle_listing['status']}"
        )

        # ----------------------------------------------------
        # Step 2: try subtitle download
        # ----------------------------------------------------

        download_result = (
            download_subtitles(
                video
            )
        )

        print(
            f"Download result  : "
            f"{download_result['status']}"
        )

        print(
            f"Subtitle files   : "
            f"{len(download_result['files'])}"
        )

        # ----------------------------------------------------
        # Step 3: extract readable transcript
        # ----------------------------------------------------

        transcript = extract_transcript_text(
            download_result[
                "files"
            ]
        )

        if transcript:

            text = transcript[
                "text"
            ]

            char_count = len(
                text
            )

            word_count = len(
                text.split()
            )

            print(
                f"Transcript       : YES"
            )

            print(
                f"Words            : "
                f"{word_count:,}"
            )

            print(
                f"Characters       : "
                f"{char_count:,}"
            )

            print(
                "Preview          :"
            )

            preview = (
                text[:1000]
                .replace(
                    "\n",
                    " "
                )
            )

            print(
                f"  {preview}"
            )

            transcript_status = (
                "AVAILABLE"
            )

            transcript_file = (
                transcript[
                    "file"
                ]
            )

        else:

            print(
                "Transcript       : NO"
            )

            transcript_status = (
                "UNAVAILABLE"
            )

            transcript_file = None
            word_count = 0
            char_count = 0

        # ----------------------------------------------------
        # Short diagnostic output
        # ----------------------------------------------------

        diagnostic_text = (
            download_result[
                "stderr"
            ]
            or subtitle_listing[
                "stderr"
            ]
            or download_result[
                "stdout"
            ]
            or subtitle_listing[
                "stdout"
            ]
            or ""
        )

        diagnostic_text = (
            diagnostic_text[
                -1200:
            ]
        )

        if (
            transcript_status
            == "UNAVAILABLE"
            and diagnostic_text.strip()
        ):

            print(
                "Diagnostic       :"
            )

            print(
                diagnostic_text
            )

        results.append({
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

            "list_subtitles_status":
                subtitle_listing[
                    "status"
                ],

            "download_status":
                download_result[
                    "status"
                ],

            "transcript_status":
                transcript_status,

            "transcript_file":
                transcript_file,

            "word_count":
                word_count,

            "character_count":
                char_count
        })

    output_path = save_test_result(
        week_key,
        results
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

    bot_blocked = [
        item
        for item in results
        if (
            item[
                "download_status"
            ]
            == "BOT_DETECTION"
            or item[
                "list_subtitles_status"
            ]
            == "BOT_DETECTION"
        )
    ]

    po_token = [
        item
        for item in results
        if (
            item[
                "download_status"
            ]
            == "PO_TOKEN_REQUIRED"
            or item[
                "list_subtitles_status"
            ]
            == "PO_TOKEN_REQUIRED"
        )
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
        f"Bot-detection cases : "
        f"{len(bot_blocked)}"
    )

    print(
        f"PO-token cases      : "
        f"{len(po_token)}"
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
            "No transcript was obtained in this GitHub runner."
        )

    print()

    print(
        f"Results file       : "
        f"{output_path}"
    )

    print(
        "=" * 88
    )


if __name__ == "__main__":

    main()