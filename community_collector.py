import json
import re
import subprocess

from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse, parse_qs


# ============================================================
# CONFIG
# ============================================================

DATA_DIR = Path("data")

LATEST_SNAPSHOT_FILE = (
    DATA_DIR
    / "latest_snapshot.json"
)

COMMUNITY_SOURCES_FILE = (
    DATA_DIR
    / "community_sources.json"
)

SEARCH_RESULTS_PER_QUERY = 20

MAX_GENERAL_RESULTS = 120
MAX_DIGIT_RESULTS = 80

MAX_SAVED_VIDEOS = 60


# ============================================================
# PRIORITY CHANNELS
# ============================================================

PRIORITY_CHANNELS = {
    "Digit Racing": 30,
    "GnC Racing": 25,
    "Wombleleader Racing": 15,
    "MotoSeventeenX": 12,
    "ProdigyRacing": 12,
}


# ============================================================
# CHANNEL ROLE
# ============================================================

CHANNEL_ROLE = {
    "Digit Racing": "STRATEGY_PRIMARY",
    "GnC Racing": "LAP_GUIDE_PRIMARY",
}


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


def normalize_space(text):

    return re.sub(
        r"\s+",
        " ",
        text or ""
    ).strip()


def normalize_text(text):

    text = normalize_space(
        text
    ).lower()

    replacements = {
        "é": "e",
        "á": "a",
        "à": "a",
        "ã": "a",
        "â": "a",
        "í": "i",
        "ó": "o",
        "ô": "o",
        "õ": "o",
        "ú": "u",
        "ç": "c",
    }

    for old, new in replacements.items():

        text = text.replace(
            old,
            new
        )

    text = re.sub(
        r"[^a-z0-9.+%'-]+",
        " ",
        text
    )

    return normalize_space(
        text
    )


def canonical_channel_name(
    channel
):

    value = normalize_text(
        channel
    )

    aliases = {
        "digit racing":
            "Digit Racing",

        "gnc racing":
            "GnC Racing",

        "wombleleader racing":
            "Wombleleader Racing",

        "motoseventeenx":
            "MotoSeventeenX",

        "prodigyracing":
            "ProdigyRacing",

        "prodigy racing":
            "ProdigyRacing",
    }

    return aliases.get(
        value,
        channel
    )


# ============================================================
# CURRENT RACE
# ============================================================

def build_race_context(
    snapshot
):

    race = snapshot.get(
        "race",
        {}
    )

    description = race.get(
        "description",
        ""
    )

    start_date_text = race.get(
        "start_date"
    )

    week_start = None

    if start_date_text:

        try:

            week_start = (
                datetime
                .fromisoformat(
                    start_date_text
                )
                .date()
            )

        except Exception:

            pass

    track = detect_track(
        description
    )

    race_class = detect_race_class(
        description
    )

    direction = (
        "REVERSE"
        if "reverse" in normalize_text(
            description
        )
        else "NORMAL"
    )

    return {
        "week_start":
            week_start,

        "week_key":
            (
                week_start.isoformat()
                if week_start
                else "UNKNOWN"
            ),

        "description":
            description,

        "track":
            track,

        "race_class":
            race_class,

        "direction":
            direction,
    }


def detect_track(
    description
):

    text = normalize_space(
        description
    )

    # Typical GTSH Daily Race text:
    # ... Daily Race C ... Grand Valley - Highway 1 ...
    #
    # First try known separators / class markers.

    patterns = [
        (
            r"Daily Race C.*?"
            r"\d{1,2}:\d{2}\s+"
            r"(.+?)"
            r"\s+(?:Gr\.?\s*\d+|Group\s+\d+)"
        ),

        (
            r"Daily Race C.*?"
            r"([A-Za-z0-9 .'\-–]+?)"
            r"\s+(?:Gr\.?\s*\d+|Group\s+\d+)"
        ),
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:

            candidate = normalize_space(
                match.group(
                    1
                )
            )

            candidate = re.sub(
                r"^\d{1,2}:\d{2}\s+",
                "",
                candidate
            )

            if len(candidate) >= 4:

                return candidate

    # Specific fallback for current known structure.

    known_track_patterns = [
        r"Grand Valley\s*-\s*Highway 1",
        r"Grand Valley Highway 1",
        r"Grand Valley-Highway 1",
        r"Grand Valley Highway One",
    ]

    for pattern in (
        known_track_patterns
    ):

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:

            return (
                "Grand Valley - Highway 1"
            )

    return None


def detect_race_class(
    text
):

    match = re.search(
        r"\bGr\.?\s*(\d+)\b",
        text,
        re.IGNORECASE
    )

    if match:

        return (
            f"Gr.{match.group(1)}"
        )

    match = re.search(
        r"\bGroup\s+(\d+)\b",
        text,
        re.IGNORECASE
    )

    if match:

        return (
            f"Gr.{match.group(1)}"
        )

    return None


# ============================================================
# SEARCH QUERIES
# ============================================================

def build_general_queries(
    context
):

    track = context.get(
        "track"
    )

    race_class = context.get(
        "race_class"
    )

    queries = [
        "GT7 Daily Race C",
        "Gran Turismo 7 Daily Race C",
    ]

    if track:

        queries.extend([
            f"GT7 Daily Race C {track}",
            f"Gran Turismo 7 Daily Race C {track}",
            f"GT7 {track} Daily Race",
        ])

    if (
        track
        and race_class
    ):

        queries.extend([
            (
                f"GT7 Daily Race C "
                f"{track} {race_class}"
            ),

            (
                f"GT7 {track} "
                f"{race_class} guide"
            ),

            (
                f"GT7 {track} "
                f"{race_class} strategy"
            ),
        ])

    return queries


def build_digit_queries(
    context
):

    track = context.get(
        "track"
    )

    race_class = context.get(
        "race_class"
    )

    queries = [
        '"Digit Racing" GT7 Daily Race C strategy',
        '"Digit Racing" Gran Turismo 7 Daily Race C strategy',
        '"Digit Racing" GT7 Daily Race C race guide',
        '"Digit Racing" GT7 Daily Race C pit strategy',
    ]

    if track:

        queries.extend([
            (
                f'"Digit Racing" GT7 '
                f'{track} Daily Race C'
            ),

            (
                f'"Digit Racing" GT7 '
                f'{track} strategy'
            ),

            (
                f'"Digit Racing" '
                f'{track} race strategy'
            ),

            (
                f'"Digit Racing" '
                f'{track} Daily Racing'
            ),
        ])

    if (
        track
        and race_class
    ):

        queries.extend([
            (
                f'"Digit Racing" GT7 '
                f'{track} {race_class} strategy'
            ),

            (
                f'"Digit Racing" GT7 '
                f'{track} {race_class} Daily Race C'
            ),
        ])

    return queries


def build_gnc_queries(
    context
):

    track = context.get(
        "track"
    )

    race_class = context.get(
        "race_class"
    )

    queries = [
        '"GnC Racing" GT7 Daily Race C lap guide',
        '"GnC Racing" Gran Turismo 7 Daily Race C',
    ]

    if track:

        queries.append(
            (
                f'"GnC Racing" GT7 '
                f'{track} lap guide'
            )
        )

    if (
        track
        and race_class
    ):

        queries.append(
            (
                f'"GnC Racing" GT7 '
                f'{track} {race_class} lap guide'
            )
        )

    return queries


# ============================================================
# YT-DLP SEARCH
# ============================================================

def yt_search(
    query,
    limit=20
):

    search_expression = (
        f"ytsearch{limit}:{query}"
    )

    command = [
        "yt-dlp",
        "--flat-playlist",
        "--dump-json",
        "--skip-download",
        "--no-warnings",
        search_expression,
    ]

    try:

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=90,
            check=False
        )

    except Exception as exc:

        print(
            f"WARNING: search failed: "
            f"{exc}"
        )

        return []

    if (
        result.returncode != 0
        and not result.stdout
    ):

        diagnostic = (
            result.stderr.strip()
            or "unknown yt-dlp error"
        )

        print(
            f"WARNING: yt-dlp returned "
            f"{result.returncode}: "
            f"{diagnostic[:300]}"
        )

        return []

    rows = []

    for line in (
        result.stdout.splitlines()
    ):

        line = line.strip()

        if not line:
            continue

        try:

            payload = json.loads(
                line
            )

        except Exception:

            continue

        video_id = (
            payload.get(
                "id"
            )
        )

        if not video_id:
            continue

        channel = (
            payload.get(
                "channel"
            )
            or payload.get(
                "uploader"
            )
            or payload.get(
                "channel_id"
            )
            or "Unknown"
        )

        channel = canonical_channel_name(
            channel
        )

        title = payload.get(
            "title",
            ""
        )

        url = (
            payload.get(
                "webpage_url"
            )
            or payload.get(
                "url"
            )
        )

        if (
            not url
            or not str(
                url
            ).startswith(
                "http"
            )
        ):

            url = (
                "https://www.youtube.com/"
                f"watch?v={video_id}"
            )

        rows.append({
            "video_id":
                video_id,

            "title":
                title,

            "channel":
                channel,

            "url":
                url,

            "duration":
                payload.get(
                    "duration"
                ),

            "timestamp":
                payload.get(
                    "timestamp"
                ),

            "upload_date":
                payload.get(
                    "upload_date"
                ),
        })

    return rows


# ============================================================
# VIDEO ID
# ============================================================

def extract_video_id(
    url
):

    if not url:
        return None

    parsed = urlparse(
        url
    )

    if (
        parsed.hostname
        and "youtu.be" in parsed.hostname
    ):

        return (
            parsed.path
            .strip("/")
        )

    query = parse_qs(
        parsed.query
    )

    values = query.get(
        "v"
    )

    if values:
        return values[
            0
        ]

    return None


# ============================================================
# TITLE DATE DETECTION
# ============================================================

def detect_title_date(
    title,
    week_start
):

    if not week_start:
        return None

    # US style:
    # 8-11-26
    # 08/11/2026

    patterns = [
        r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})\b",
    ]

    for pattern in patterns:

        for match in re.finditer(
            pattern,
            title
        ):

            first = int(
                match.group(
                    1
                )
            )

            second = int(
                match.group(
                    2
                )
            )

            year = int(
                match.group(
                    3
                )
            )

            if year < 100:
                year += 2000

            possible_dates = []

            # US MM-DD-YY
            try:

                possible_dates.append(
                    datetime(
                        year,
                        first,
                        second
                    ).date()
                )

            except ValueError:

                pass

            # International DD-MM-YY
            try:

                possible_dates.append(
                    datetime(
                        year,
                        second,
                        first
                    ).date()
                )

            except ValueError:

                pass

            for candidate in (
                possible_dates
            ):

                if (
                    week_start
                    - timedelta(
                        days=1
                    )
                    <= candidate
                    <= week_start
                    + timedelta(
                        days=6
                    )
                ):

                    return candidate

    return None


# ============================================================
# OLD DATE / MONTH DETECTION
# ============================================================

MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


def old_month_year_in_title(
    title,
    week_start
):

    if not week_start:
        return False

    normalized = (
        title.lower()
    )

    month_pattern = (
        r"\b("
        + "|".join(
            MONTHS.keys()
        )
        + r")"
        r"\s*['\- ]?"
        r"(\d{2,4})\b"
    )

    matches = re.findall(
        month_pattern,
        normalized,
        re.IGNORECASE
    )

    for month_text, year_text in matches:

        month = MONTHS[
            month_text.lower()
        ]

        year = int(
            year_text
        )

        if year < 100:
            year += 2000

        if (
            year != week_start.year
            or month != week_start.month
        ):

            return True

    return False


# ============================================================
# CONTENT TYPE
# ============================================================

def classify_content_type(
    title
):

    text = normalize_text(
        title
    )

    # Strategy gets priority over generic race classification.

    strategy_terms = [
        "strategy",
        "race strategy",
        "strategy guide",
        "pit strategy",
        "tyre strategy",
        "tire strategy",
        "fuel strategy",
        "best strategy",
        "race guide",
    ]

    if any(
        term in text
        for term in strategy_terms
    ):

        return "STRATEGY"

    if (
        "lap guide" in text
        or "track guide" in text
    ):

        return "LAP_GUIDE"

    if (
        "qualifying" in text
        or "hotlap" in text
        or "hot lap" in text
        or re.search(
            r"\bpb\b",
            text
        )
    ):

        return "QUALIFYING"

    if (
        "livestream" in text
        or "live stream" in text
        or text.startswith(
            "live "
        )
    ):

        return "LIVESTREAM"

    if (
        "daily race" in text
        or "race c" in text
        or "daily racing" in text
    ):

        return "RACE"

    return "OTHER"


# ============================================================
# TITLE FACT DETECTION
# ============================================================

def daily_race_letter(
    title
):

    normalized = normalize_text(
        title
    )

    match = re.search(
        r"\bdaily race\s*([abc])\b",
        normalized
    )

    if match:

        return match.group(
            1
        ).upper()

    return None


def class_from_title(
    title
):

    return detect_race_class(
        title
    )


def direction_from_title(
    title
):

    if "reverse" in normalize_text(
        title
    ):

        return "REVERSE"

    return None


# ============================================================
# RELEVANCE
# ============================================================

def track_match_score(
    title,
    track
):

    if not track:
        return 0

    title_words = set(
        normalize_text(
            title
        ).split()
    )

    track_words = [
        word
        for word in normalize_text(
            track
        ).split()
        if len(word) >= 3
    ]

    if not track_words:
        return 0

    matches = sum(
        1
        for word in track_words
        if word in title_words
    )

    ratio = (
        matches
        / len(track_words)
    )

    if ratio >= 0.90:
        return 12

    if ratio >= 0.70:
        return 9

    if ratio >= 0.50:
        return 5

    return 0


def priority_channel_score(
    channel
):

    canonical = canonical_channel_name(
        channel
    )

    return PRIORITY_CHANNELS.get(
        canonical,
        0
    )


def is_digit_channel(
    channel
):

    return (
        normalize_text(
            canonical_channel_name(
                channel
            )
        )
        == "digit racing"
    )


def is_gnc_channel(
    channel
):

    return (
        normalize_text(
            canonical_channel_name(
                channel
            )
        )
        == "gnc racing"
    )


# ============================================================
# VIDEO VALIDATION
# ============================================================

def validate_candidate(
    video,
    context
):

    title = video.get(
        "title",
        ""
    )

    channel = canonical_channel_name(
        video.get(
            "channel",
            "Unknown"
        )
    )

    video[
        "channel"
    ] = channel

    normalized = normalize_text(
        title
    )

    reasons = []
    notes = []

    # --------------------------------------------------------
    # GT7
    # --------------------------------------------------------

    gt7_signal = any(
        term in normalized
        for term in [
            "gt7",
            "gran turismo 7",
            "gran turismo",
        ]
    )

    if not gt7_signal:

        reasons.append(
            "NOT_GT7"
        )

    # --------------------------------------------------------
    # TRACK
    # --------------------------------------------------------

    track_score = track_match_score(
        title,
        context.get(
            "track"
        )
    )

    if (
        context.get(
            "track"
        )
        and track_score == 0
    ):

        reasons.append(
            "TRACK_MISMATCH"
        )

    # --------------------------------------------------------
    # DAILY RACE
    # --------------------------------------------------------

    letter = daily_race_letter(
        title
    )

    if (
        letter
        and letter != "C"
    ):

        reasons.append(
            "WRONG_DAILY_RACE"
        )

    elif not letter:

        notes.append(
            "RACE_LETTER_UNVERIFIED"
        )

    # --------------------------------------------------------
    # CLASS
    # --------------------------------------------------------

    expected_class = context.get(
        "race_class"
    )

    detected_class = class_from_title(
        title
    )

    if (
        expected_class
        and detected_class
        and detected_class
        != expected_class
    ):

        reasons.append(
            "WRONG_CLASS"
        )

    elif (
        expected_class
        and not detected_class
    ):

        notes.append(
            "CLASS_UNVERIFIED"
        )

    # --------------------------------------------------------
    # DIRECTION
    # --------------------------------------------------------

    expected_direction = context.get(
        "direction",
        "NORMAL"
    )

    detected_direction = (
        direction_from_title(
            title
        )
    )

    if (
        expected_direction == "NORMAL"
        and detected_direction == "REVERSE"
    ):

        reasons.append(
            "WRONG_DIRECTION"
        )

    if (
        expected_direction == "REVERSE"
        and detected_direction != "REVERSE"
    ):

        notes.append(
            "DIRECTION_UNVERIFIED"
        )

    # --------------------------------------------------------
    # DATE
    # --------------------------------------------------------

    detected_date = detect_title_date(
        title,
        context.get(
            "week_start"
        )
    )

    if detected_date:

        date_confidence = (
            "CONFIRMED"
        )

        notes.append(
            "DATE_FROM_TITLE"
        )

    else:

        date_confidence = (
            "UNVERIFIED"
        )

        notes.append(
            "DATE_UNVERIFIED"
        )

    if old_month_year_in_title(
        title,
        context.get(
            "week_start"
        )
    ):

        reasons.append(
            "OLD_MONTH_YEAR_IN_TITLE"
        )

    # --------------------------------------------------------
    # CONTENT
    # --------------------------------------------------------

    content_type = (
        classify_content_type(
            title
        )
    )

    # --------------------------------------------------------
    # BASE SCORE
    # --------------------------------------------------------

    score = 0

    score += track_score

    score += priority_channel_score(
        channel
    )

    if letter == "C":

        score += 10

    if detected_class == expected_class:

        score += 8

    if detected_date:

        score += 14

    if content_type == "STRATEGY":

        score += 12

    elif content_type == "LAP_GUIDE":

        score += 10

    elif content_type == "QUALIFYING":

        score += 8

    elif content_type == "RACE":

        score += 5

    elif content_type == "LIVESTREAM":

        score += 4

    # --------------------------------------------------------
    # SPECIAL ROLE BOOSTS
    # --------------------------------------------------------

    if is_digit_channel(
        channel
    ):

        score += 15

        if content_type == "STRATEGY":

            # This is exactly what we want.
            score += 35

            notes.append(
                "DIGIT_STRATEGY_PRIMARY"
            )

        elif content_type in {
            "RACE",
            "LIVESTREAM",
        }:

            # Could contain strategy discussion.
            score += 12

            notes.append(
                "DIGIT_STRATEGY_CANDIDATE"
            )

        elif content_type == "LAP_GUIDE":

            # Keep it in database, but do not promote
            # as race strategy.
            notes.append(
                "DIGIT_LAP_GUIDE_NOT_STRATEGY"
            )

    if is_gnc_channel(
        channel
    ):

        if content_type in {
            "LAP_GUIDE",
            "QUALIFYING",
        }:

            score += 25

            notes.append(
                "GNC_LAP_GUIDE_PRIMARY"
            )

    # --------------------------------------------------------
    # ACCEPT / REJECT
    # --------------------------------------------------------

    hard_rejects = {
        "NOT_GT7",
        "TRACK_MISMATCH",
        "WRONG_DAILY_RACE",
        "WRONG_CLASS",
        "WRONG_DIRECTION",
        "OLD_MONTH_YEAR_IN_TITLE",
    }

    accepted = not any(
        reason in hard_rejects
        for reason in reasons
    )

    # Generic weak videos need minimum evidence.
    if (
        accepted
        and score < 12
    ):

        accepted = False

        reasons.append(
            "LOW_RELEVANCE"
        )

    output = dict(
        video
    )

    output.update({
        "content_type":
            content_type,

        "priority_score":
            score,

        "date_confidence":
            date_confidence,

        "detected_date":
            (
                detected_date.isoformat()
                if detected_date
                else None
            ),

        "notes":
            notes,

        "rejection_reasons":
            reasons,

        "accepted":
            accepted,

        "role":
            CHANNEL_ROLE.get(
                channel
            ),
    })

    return output


# ============================================================
# DATABASE COMPATIBILITY
# ============================================================

def normalize_existing_database(
    database
):

    if not isinstance(
        database,
        dict
    ):

        database = {}

    if "weeks" not in database:

        database[
            "weeks"
        ] = {}

    return database


def existing_week_videos(
    database,
    week_key
):

    week = (
        database
        .get(
            "weeks",
            {}
        )
        .get(
            week_key,
            {}
        )
    )

    videos = week.get(
        "videos",
        []
    )

    if isinstance(
        videos,
        list
    ):

        return videos

    return []


# ============================================================
# MERGE VIDEO DATABASE
# ============================================================

def merge_videos(
    existing,
    current
):

    merged = {}

    for video in existing:

        video_id = video.get(
            "video_id"
        )

        if video_id:

            merged[
                video_id
            ] = video

    for video in current:

        video_id = video.get(
            "video_id"
        )

        if not video_id:
            continue

        old = merged.get(
            video_id,
            {}
        )

        updated = dict(
            old
        )

        updated.update(
            video
        )

        merged[
            video_id
        ] = updated

    output = list(
        merged.values()
    )

    output.sort(
        key=lambda item:
            (
                item.get(
                    "priority_score",
                    0
                ),
                item.get(
                    "detected_date"
                )
                or ""
            ),
        reverse=True
    )

    return output[
        :MAX_SAVED_VIDEOS
    ]


# ============================================================
# SELECT BEST ROLES
# ============================================================

def best_digit_strategy(
    videos
):

    digit = [
        video
        for video in videos
        if (
            video.get(
                "accepted"
            )
            and is_digit_channel(
                video.get(
                    "channel",
                    ""
                )
            )
        )
    ]

    direct = [
        video
        for video in digit
        if video.get(
            "content_type"
        )
        == "STRATEGY"
    ]

    if direct:

        return max(
            direct,
            key=lambda item:
                item.get(
                    "priority_score",
                    0
                )
        )

    candidates = [
        video
        for video in digit
        if video.get(
            "content_type"
        )
        in {
            "RACE",
            "LIVESTREAM",
        }
    ]

    if candidates:

        return max(
            candidates,
            key=lambda item:
                item.get(
                    "priority_score",
                    0
                )
        )

    return None


def best_gnc_lap_guide(
    videos
):

    candidates = [
        video
        for video in videos
        if (
            video.get(
                "accepted"
            )
            and is_gnc_channel(
                video.get(
                    "channel",
                    ""
                )
            )
            and video.get(
                "content_type"
            )
            in {
                "LAP_GUIDE",
                "QUALIFYING",
            }
        )
    ]

    if not candidates:

        return None

    return max(
        candidates,
        key=lambda item:
            item.get(
                "priority_score",
                0
            )
    )


# ============================================================
# SEARCH RUNNER
# ============================================================

def execute_queries(
    queries,
    label
):

    collected = {}

    print("")
    print(
        label
    )

    print(
        "-" * 88
    )

    for query in queries:

        print(
            f"Searching: {query}"
        )

        results = yt_search(
            query,
            SEARCH_RESULTS_PER_QUERY
        )

        print(
            f"  Results: {len(results)}"
        )

        for video in results:

            video_id = video.get(
                "video_id"
            )

            if not video_id:

                video_id = extract_video_id(
                    video.get(
                        "url"
                    )
                )

                video[
                    "video_id"
                ] = video_id

            if video_id:

                collected[
                    video_id
                ] = video

    return list(
        collected.values()
    )


# ============================================================
# MAIN
# ============================================================

def main():

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    snapshot = load_json(
        LATEST_SNAPSHOT_FILE
    )

    if not snapshot:

        raise RuntimeError(
            "data/latest_snapshot.json "
            "not found or invalid."
        )

    context = build_race_context(
        snapshot
    )

    print(
        "=" * 88
    )

    print(
        "GT7 COMMUNITY SOURCE COLLECTOR V5"
    )

    print(
        "=" * 88
    )

    print(
        f"Race week       : "
        f"{context['week_key']}"
    )

    print(
        f"Track detected  : "
        f"{context.get('track')}"
    )

    print(
        f"Race class      : "
        f"{context.get('race_class')}"
    )

    print(
        f"Direction       : "
        f"{context.get('direction')}"
    )

    # ========================================================
    # QUERIES
    # ========================================================

    general_queries = build_general_queries(
        context
    )

    digit_queries = build_digit_queries(
        context
    )

    gnc_queries = build_gnc_queries(
        context
    )

    print(
        f"General queries : "
        f"{len(general_queries)}"
    )

    print(
        f"Digit queries   : "
        f"{len(digit_queries)}"
    )

    print(
        f"GnC queries     : "
        f"{len(gnc_queries)}"
    )

    # ========================================================
    # GENERAL SEARCH
    # ========================================================

    general_results = execute_queries(
        general_queries,
        "GENERAL COMMUNITY SEARCH"
    )

    # ========================================================
    # DIGIT SEARCH
    # ========================================================

    digit_results = execute_queries(
        digit_queries,
        "DIGIT RACING STRATEGY SEARCH"
    )

    # ========================================================
    # GNC SEARCH
    # ========================================================

    gnc_results = execute_queries(
        gnc_queries,
        "GNC LAP GUIDE SEARCH"
    )

    # ========================================================
    # COMBINE
    # ========================================================

    unique = {}

    for video in (
        general_results
        + digit_results
        + gnc_results
    ):

        video_id = video.get(
            "video_id"
        )

        if video_id:

            unique[
                video_id
            ] = video

    raw_candidates = list(
        unique.values()
    )

    # ========================================================
    # VALIDATE
    # ========================================================

    validated = [
        validate_candidate(
            video,
            context
        )
        for video in raw_candidates
    ]

    accepted = [
        video
        for video in validated
        if video.get(
            "accepted"
        )
    ]

    rejected = [
        video
        for video in validated
        if not video.get(
            "accepted"
        )
    ]

    accepted.sort(
        key=lambda item:
            item.get(
                "priority_score",
                0
            ),
        reverse=True
    )

    # ========================================================
    # LOAD EXISTING DATABASE
    # ========================================================

    database = normalize_existing_database(
        load_json(
            COMMUNITY_SOURCES_FILE,
            {}
        )
    )

    existing = existing_week_videos(
        database,
        context[
            "week_key"
        ]
    )

    existing_ids = {
        video.get(
            "video_id"
        )
        for video in existing
        if video.get(
            "video_id"
        )
    }

    current_ids = {
        video.get(
            "video_id"
        )
        for video in accepted
        if video.get(
            "video_id"
        )
    }

    new_ids = (
        current_ids
        - existing_ids
    )

    known_ids = (
        current_ids
        & existing_ids
    )

    merged = merge_videos(
        existing,
        accepted
    )

    # ========================================================
    # ROLE SELECTION
    # ========================================================

    digit_strategy = (
        best_digit_strategy(
            merged
        )
    )

    gnc_lap = (
        best_gnc_lap_guide(
            merged
        )
    )

    # ========================================================
    # SAVE DATABASE
    # ========================================================

    database[
        "version"
    ] = 5

    database[
        "updated_at"
    ] = (
        datetime.utcnow()
        .isoformat()
        + "Z"
    )

    database[
        "weeks"
    ][
        context[
            "week_key"
        ]
    ] = {
        "track":
            context.get(
                "track"
            ),

        "race_class":
            context.get(
                "race_class"
            ),

        "direction":
            context.get(
                "direction"
            ),

        "race_description":
            context.get(
                "description"
            ),

        "selected_sources": {
            "strategy_primary":
                (
                    digit_strategy
                    if digit_strategy
                    else None
                ),

            "lap_guide_primary":
                (
                    gnc_lap
                    if gnc_lap
                    else None
                ),
        },

        "videos":
            merged,
    }

    save_json(
        COMMUNITY_SOURCES_FILE,
        database
    )

    # ========================================================
    # REPORT
    # ========================================================

    print("")
    print(
        "=" * 88
    )

    print(
        "COLLECTOR RESULT"
    )

    print(
        "=" * 88
    )

    print(
        f"Search candidates : "
        f"{len(raw_candidates)}"
    )

    print(
        f"Accepted          : "
        f"{len(accepted)}"
    )

    print(
        f"Rejected          : "
        f"{len(rejected)}"
    )

    print(
        f"New videos        : "
        f"{len(new_ids)}"
    )

    print(
        f"Already known     : "
        f"{len(known_ids)}"
    )

    print(
        f"Total tracked     : "
        f"{len(merged)}"
    )

    confirmed_dates = sum(
        1
        for video in merged
        if video.get(
            "date_confidence"
        )
        == "CONFIRMED"
    )

    unverified_dates = sum(
        1
        for video in merged
        if video.get(
            "date_confidence"
        )
        == "UNVERIFIED"
    )

    print(
        f"Date confirmed    : "
        f"{confirmed_dates}"
    )

    print(
        f"Date unverified   : "
        f"{unverified_dates}"
    )

    # ========================================================
    # ROLE STATUS
    # ========================================================

    print("")
    print(
        "PRIMARY SOURCE STATUS"
    )

    print(
        "-" * 88
    )

    if digit_strategy:

        print(
            "STRATEGY PRIMARY : FOUND"
        )

        print(
            f"Channel          : "
            f"{digit_strategy.get('channel')}"
        )

        print(
            f"Type             : "
            f"{digit_strategy.get('content_type')}"
        )

        print(
            f"Score            : "
            f"{digit_strategy.get('priority_score')}"
        )

        print(
            f"Title            : "
            f"{digit_strategy.get('title')}"
        )

        print(
            f"URL              : "
            f"{digit_strategy.get('url')}"
        )

        if (
            digit_strategy.get(
                "content_type"
            )
            != "STRATEGY"
        ):

            print(
                "NOTE             : "
                "Digit source is a fallback "
                "RACE/LIVESTREAM candidate, "
                "not a confirmed strategy guide."
            )

    else:

        print(
            "STRATEGY PRIMARY : NOT FOUND"
        )

        print(
            "Digit Racing has no accepted "
            "STRATEGY/RACE/LIVESTREAM candidate "
            "for this race in the current database."
        )

    print("")

    if gnc_lap:

        print(
            "LAP GUIDE PRIMARY: FOUND"
        )

        print(
            f"Channel          : "
            f"{gnc_lap.get('channel')}"
        )

        print(
            f"Type             : "
            f"{gnc_lap.get('content_type')}"
        )

        print(
            f"Score            : "
            f"{gnc_lap.get('priority_score')}"
        )

        print(
            f"Title            : "
            f"{gnc_lap.get('title')}"
        )

        print(
            f"URL              : "
            f"{gnc_lap.get('url')}"
        )

    else:

        print(
            "LAP GUIDE PRIMARY: NOT FOUND"
        )

    # ========================================================
    # DIGIT CANDIDATES
    # ========================================================

    print("")
    print(
        "DIGIT RACING CANDIDATES"
    )

    print(
        "-" * 88
    )

    digit_candidates = [
        video
        for video in merged
        if is_digit_channel(
            video.get(
                "channel",
                ""
            )
        )
    ]

    if not digit_candidates:

        print(
            "No accepted Digit Racing videos found."
        )

    else:

        for index, video in enumerate(
            digit_candidates[
                :10
            ],
            start=1
        ):

            print(
                f"{index}. "
                f"[P{video.get('priority_score',0)}] "
                f"[{video.get('content_type')}] "
                f"{video.get('title')}"
            )

            print(
                f"   Date : "
                f"{video.get('detected_date') or 'unverified'}"
            )

            print(
                f"   Notes: "
                f"{', '.join(video.get('notes',[])) or 'None'}"
            )

            print(
                f"   {video.get('url')}"
            )

    # ========================================================
    # TOP ACCEPTED
    # ========================================================

    print("")
    print(
        "TOP ACCEPTED COMMUNITY SOURCES"
    )

    print(
        "-" * 88
    )

    for index, video in enumerate(
        merged[
            :20
        ],
        start=1
    ):

        print(
            f"{index:2d}. "
            f"[P{video.get('priority_score',0)}] "
            f"[{video.get('content_type')}] "
            f"{video.get('channel')} | "
            f"{video.get('title')}"
        )

    # ========================================================
    # REJECTED SAMPLE
    # ========================================================

    print("")
    print(
        "REJECTED SAMPLE"
    )

    print(
        "-" * 88
    )

    for index, video in enumerate(
        rejected[
            :15
        ],
        start=1
    ):

        print(
            f"{index}. "
            f"{video.get('channel')} | "
            f"{video.get('title')}"
        )

        print(
            "   Reasons: "
            + ", ".join(
                video.get(
                    "rejection_reasons",
                    []
                )
            )
        )

    print("")

    print(
        f"Database saved    : "
        f"{COMMUNITY_SOURCES_FILE}"
    )

    print(
        "=" * 88
    )


if __name__ == "__main__":

    main()