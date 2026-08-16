import json
import re
import subprocess

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


# ============================================================
# CONFIG
# ============================================================

DATA_DIR = Path("data")

LATEST_SNAPSHOT_FILE = DATA_DIR / "latest_snapshot.json"
COMMUNITY_FILE = DATA_DIR / "community_sources.json"

SAO_PAULO = ZoneInfo("America/Sao_Paulo")

MAX_RESULTS_PER_QUERY = 20


# ============================================================
# JSON
# ============================================================

def load_json(path, default):

    if not path.exists():
        return default

    try:
        return json.loads(
            path.read_text(encoding="utf-8")
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
# TEXT
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


def normalize_track_text(text):

    text = normalize_text(text)

    text = text.replace("-", " ")

    text = re.sub(
        r"[^a-z0-9à-ÿ ]+",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# ============================================================
# RACE METADATA
# ============================================================

def parse_week_start(snapshot):

    start_date = (
        snapshot
        .get("race", {})
        .get("start_date")
    )

    if not start_date:

        raise RuntimeError(
            "Race start_date not found "
            "in data/latest_snapshot.json."
        )

    return datetime.fromisoformat(
        start_date
    )


def extract_track(race_text):

    if not race_text:
        return None

    match = re.search(
        r"Daily Race C.*?"
        r"\d{1,2}:\d{2}\s+"
        r"(.+?)\s+"
        r"[A-Z]\.\s*[A-Za-zÀ-ÿ]",
        race_text,
        re.IGNORECASE
    )

    if match:

        track = match.group(1).strip()

        if track:
            return track

    manufacturer_pattern = (
        r"(?:GT by|Genesis|Hyundai|Nissan|Toyota|"
        r"Honda|Suzuki|BMW|Mazda|Ferrari|Porsche|"
        r"Renault|Volkswagen|Audi|Lexus|Ford|Chevrolet|"
        r"Jaguar|McLaren|Peugeot|Subaru|Mitsubishi|"
        r"Lamborghini|Dodge|Alfa|Mercedes-Benz|Bugatti|"
        r"Aston Martin)"
    )

    match = re.search(
        r"Daily Race C.*?"
        r"\d{1,2}:\d{2}\s+"
        r"(.+?)\s+"
        + manufacturer_pattern,
        race_text,
        re.IGNORECASE
    )

    if match:

        track = match.group(1).strip()

        if track:
            return track

    return None


def extract_race_class(race_text):

    if not race_text:
        return None

    match = re.search(
        r"\bGr\.(\d)\b",
        race_text,
        re.IGNORECASE
    )

    if not match:
        return None

    return f"Gr.{match.group(1)}"


def race_is_reverse(race_text):

    return (
        "reverse"
        in normalize_text(race_text)
    )


# ============================================================
# SEARCH QUERIES
# ============================================================

def build_queries(snapshot):

    race_text = (
        snapshot
        .get("race", {})
        .get("description", "")
    )

    if not race_text:

        raise RuntimeError(
            "Race description not found."
        )

    track = extract_track(race_text)

    race_class = extract_race_class(
        race_text
    )

    queries = [
        "GT7 Daily Race C",
        "Gran Turismo 7 Daily Race C"
    ]

    if track:

        queries.extend([
            f"GT7 Daily Race C {track}",
            f"Gran Turismo 7 Daily Race C {track}",
            f"GT7 {track} Daily Race"
        ])

    if track and race_class:

        queries.extend([
            f"GT7 Daily Race C {track} {race_class}",
            f"GT7 {track} {race_class} guide",
            f"GT7 {track} {race_class} strategy"
        ])

    unique = []
    seen = set()

    for query in queries:

        key = normalize_text(query)

        if key in seen:
            continue

        seen.add(key)
        unique.append(query)

    return (
        unique,
        track,
        race_class
    )


# ============================================================
# YOUTUBE SEARCH
# ============================================================

def search_youtube(query):

    target = (
        f"ytsearch{MAX_RESULTS_PER_QUERY}:"
        f"{query}"
    )

    command = [
        "yt-dlp",
        "--ignore-errors",
        "--skip-download",
        "--dump-single-json",
        "--flat-playlist",
        target
    ]

    try:

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=120
        )

    except subprocess.TimeoutExpired:

        print(
            f"WARNING: search timeout: "
            f"{query}"
        )

        return []

    except Exception as exc:

        print(
            f"WARNING: search failure: "
            f"{query}"
        )

        print(exc)

        return []

    if result.returncode != 0:

        print(
            f"WARNING: search failed: "
            f"{query}"
        )

        if result.stderr:

            print(
                result.stderr[-1000:]
            )

        return []

    try:

        payload = json.loads(
            result.stdout
        )

    except Exception:

        print(
            f"WARNING: invalid JSON: "
            f"{query}"
        )

        return []

    entries = payload.get(
        "entries",
        []
    )

    if not isinstance(entries, list):
        return []

    return [
        entry
        for entry in entries
        if isinstance(entry, dict)
    ]


# ============================================================
# TITLE DATE DETECTION
# ============================================================

def detect_date_from_title(
    title,
    week_start
):

    if not title:
        return None

    # Examples:
    # 8-11-26
    # 8/11/26
    # 08-11-2026

    patterns = [
        r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})\b"
    ]

    candidates = []

    for pattern in patterns:

        for match in re.finditer(
            pattern,
            title
        ):

            a = int(match.group(1))
            b = int(match.group(2))
            year = int(match.group(3))

            if year < 100:
                year += 2000

            # YouTube GT7 titles are often US-style
            # month-day-year.
            try:

                dt = datetime(
                    year,
                    a,
                    b,
                    tzinfo=SAO_PAULO
                )

                candidates.append(dt)

            except ValueError:
                pass

            # Also test day-month-year.
            try:

                dt = datetime(
                    year,
                    b,
                    a,
                    tzinfo=SAO_PAULO
                )

                candidates.append(dt)

            except ValueError:
                pass

    if not candidates:
        return None

    # Pick the interpretation closest to
    # the current race week.
    return min(
        candidates,
        key=lambda dt:
            abs(
                (
                    dt.date()
                    - week_start.date()
                ).days
            )
    )


# ============================================================
# CLASS DETECTION
# ============================================================

def detect_explicit_classes(text):

    text = normalize_text(text)

    classes = set()

    patterns = [
        r"\bgr\.?\s*([1-4])\b",
        r"\bgroup\s*([1-4])\b"
    ]

    for pattern in patterns:

        for match in re.finditer(
            pattern,
            text,
            re.IGNORECASE
        ):

            classes.add(
                match.group(1)
            )

    return classes


# ============================================================
# DAILY RACE DETECTION
# ============================================================

def detect_explicit_race_letter(text):

    text = normalize_text(text)

    letters = set()

    patterns = [
        r"\bdaily\s+race\s+([abc])\b",
        r"\bdaily\s+races?\s+([abc])\b"
    ]

    for pattern in patterns:

        for match in re.finditer(
            pattern,
            text,
            re.IGNORECASE
        ):

            letters.add(
                match.group(1).upper()
            )

    return letters


# ============================================================
# CONTENT TYPE
# ============================================================

def classify_content(title):

    text = normalize_text(title)

    if (
        "strategy guide" in text
        or "race strategy" in text
        or "strategy" in text
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
        or "world record" in text
    ):
        return "QUALIFYING"

    if (
        "livestream" in text
        or " live" in text
        or text.startswith("live")
    ):
        return "LIVESTREAM"

    if (
        "race" in text
    ):
        return "RACE"

    return "OTHER"


# ============================================================
# RELEVANCE
# ============================================================

def relevance_score(
    entry,
    track,
    race_class
):

    title = normalize_text(
        entry.get("title", "")
    )

    score = 0

    if "gt7" in title:
        score += 3

    if "gran turismo 7" in title:
        score += 3

    if "daily race c" in title:
        score += 10

    elif "daily race" in title:
        score += 3

    if track:

        track_norm = normalize_track_text(
            track
        )

        title_norm = normalize_track_text(
            title
        )

        if track_norm in title_norm:
            score += 10

        words = [
            word
            for word in track_norm.split()
            if len(word) >= 4
        ]

        score += sum(
            1
            for word in words
            if word in title_norm
        )

    if race_class:

        expected = race_class[-1]

        classes = detect_explicit_classes(
            title
        )

        if expected in classes:
            score += 6

    content_type = classify_content(
        title
    )

    bonuses = {
        "STRATEGY": 8,
        "LAP_GUIDE": 8,
        "QUALIFYING": 5,
        "RACE": 2,
        "LIVESTREAM": 1,
        "OTHER": 0
    }

    score += bonuses.get(
        content_type,
        0
    )

    return score


# ============================================================
# VALIDATION
# ============================================================

def validate_candidate(
    entry,
    track,
    race_class,
    current_reverse,
    week_start,
    now
):

    title = entry.get(
        "title",
        ""
    )

    text = normalize_text(title)

    reasons = []
    notes = []

    # --------------------------------------------------------
    # GAME
    # --------------------------------------------------------

    gt7_match = (
        "gt7" in text
        or "gran turismo 7" in text
        or "gran turismo® 7" in text
    )

    if not gt7_match:

        reasons.append(
            "NOT_GT7"
        )

    # --------------------------------------------------------
    # DAILY RACE LETTER
    # --------------------------------------------------------

    race_letters = (
        detect_explicit_race_letter(
            title
        )
    )

    if race_letters:

        if "C" not in race_letters:

            reasons.append(
                "WRONG_DAILY_RACE"
            )

    else:

        # Search may find useful titles without an
        # explicit letter, but they must at least
        # mention Daily Race.
        if "daily race" not in text:

            notes.append(
                "RACE_LETTER_UNVERIFIED"
            )

    # --------------------------------------------------------
    # TRACK
    # --------------------------------------------------------

    if track:

        track_norm = normalize_track_text(
            track
        )

        title_norm = normalize_track_text(
            title
        )

        track_words = [
            word
            for word in track_norm.split()
            if len(word) >= 4
        ]

        matching = sum(
            1
            for word in track_words
            if word in title_norm
        )

        minimum = max(
            2,
            len(track_words) - 1
        )

        if matching < minimum:

            reasons.append(
                "WRONG_TRACK"
            )

    # --------------------------------------------------------
    # DIRECTION
    # --------------------------------------------------------

    video_reverse = (
        "reverse" in text
    )

    if (
        not current_reverse
        and video_reverse
    ):

        reasons.append(
            "WRONG_DIRECTION"
        )

    # --------------------------------------------------------
    # CLASS
    # --------------------------------------------------------

    explicit_classes = (
        detect_explicit_classes(
            title
        )
    )

    if (
        race_class
        and explicit_classes
    ):

        expected = race_class[-1]

        if expected not in explicit_classes:

            reasons.append(
                "WRONG_CLASS"
            )

    elif race_class:

        notes.append(
            "CLASS_UNVERIFIED"
        )

    # --------------------------------------------------------
    # DATE
    # --------------------------------------------------------

    title_date = detect_date_from_title(
        title,
        week_start
    )

    earliest = (
        week_start
        - timedelta(days=1)
    )

    latest = (
        week_start
        + timedelta(days=7)
    )

    if title_date:

        if title_date < earliest:

            reasons.append(
                "TITLE_DATE_TOO_OLD"
            )

        elif title_date > latest:

            reasons.append(
                "TITLE_DATE_OUTSIDE_WEEK"
            )

        else:

            notes.append(
                "DATE_FROM_TITLE"
            )

    else:

        notes.append(
            "DATE_UNVERIFIED"
        )

    # --------------------------------------------------------
    # FINAL
    # --------------------------------------------------------

    accepted = (
        len(reasons) == 0
    )

    return {
        "accepted":
            accepted,

        "reasons":
            reasons,

        "notes":
            notes,

        "title_date":
            (
                title_date.date().isoformat()
                if title_date
                else None
            )
    }


# ============================================================
# MERGE SEARCH RESULTS
# ============================================================

def merge_candidate(
    candidates,
    entry,
    query,
    track,
    race_class
):

    video_id = entry.get("id")

    if not video_id:
        return

    title = entry.get(
        "title",
        ""
    )

    channel = (
        entry.get("channel")
        or entry.get("uploader")
        or entry.get("channel_id")
        or "Unknown"
    )

    score = relevance_score(
        entry,
        track,
        race_class
    )

    if video_id not in candidates:

        candidates[video_id] = {
            "video_id":
                video_id,

            "title":
                title,

            "channel":
                channel,

            "url":
                (
                    "https://www.youtube.com/watch?v="
                    f"{video_id}"
                ),

            "search_relevance":
                score,

            "matched_queries":
                [query]
        }

        return

    candidate = candidates[
        video_id
    ]

    candidate[
        "search_relevance"
    ] = max(
        candidate.get(
            "search_relevance",
            0
        ),
        score
    )

    if query not in candidate[
        "matched_queries"
    ]:

        candidate[
            "matched_queries"
        ].append(query)


# ============================================================
# MAIN
# ============================================================

def main():

    now = datetime.now(
        SAO_PAULO
    )

    snapshot = load_json(
        LATEST_SNAPSHOT_FILE,
        None
    )

    if not snapshot:

        raise RuntimeError(
            "data/latest_snapshot.json "
            "not found or invalid."
        )

    race = snapshot.get(
        "race",
        {}
    )

    race_description = race.get(
        "description",
        ""
    )

    race_url = race.get(
        "leaderboard_url"
    )

    week_start = parse_week_start(
        snapshot
    )

    (
        queries,
        track,
        race_class
    ) = build_queries(
        snapshot
    )

    current_reverse = race_is_reverse(
        race_description
    )

    print(
        "=" * 78
    )

    print(
        "GT7 COMMUNITY SOURCE COLLECTOR V3"
    )

    print(
        "=" * 78
    )

    print(
        f"Race week       : "
        f"{week_start.date().isoformat()}"
    )

    print(
        f"Track detected  : "
        f"{track or 'UNKNOWN'}"
    )

    print(
        f"Race class      : "
        f"{race_class or 'UNKNOWN'}"
    )

    print(
        f"Direction       : "
        f"{'REVERSE' if current_reverse else 'NORMAL'}"
    )

    print(
        f"Search queries  : "
        f"{len(queries)}"
    )

    for query in queries:

        print(
            f"  - {query}"
        )

    # ========================================================
    # SEARCH
    # ========================================================

    candidates = {}

    for query in queries:

        print()

        print(
            f"Searching: {query}"
        )

        entries = search_youtube(
            query
        )

        print(
            f"  Results: "
            f"{len(entries)}"
        )

        for entry in entries:

            merge_candidate(
                candidates,
                entry,
                query,
                track,
                race_class
            )

    # ========================================================
    # VALIDATE
    # ========================================================

    accepted = {}
    rejected = {}

    for (
        video_id,
        candidate
    ) in candidates.items():

        validation = validate_candidate(
            candidate,
            track,
            race_class,
            current_reverse,
            week_start,
            now
        )

        content_type = classify_content(
            candidate.get(
                "title",
                ""
            )
        )

        video = {
            **candidate,

            "content_type":
                content_type,

            "validation_notes":
                validation[
                    "notes"
                ],

            "title_date":
                validation[
                    "title_date"
                ],

            "status":
                (
                    "ACCEPTED"
                    if validation[
                        "accepted"
                    ]
                    else "REJECTED"
                )
        }

        if validation[
            "accepted"
        ]:

            accepted[
                video_id
            ] = video

        else:

            video[
                "rejection_reasons"
            ] = validation[
                "reasons"
            ]

            rejected[
                video_id
            ] = video

    # ========================================================
    # DATABASE
    # ========================================================

    database = load_json(
        COMMUNITY_FILE,
        {
            "version": 3,
            "weeks": {}
        }
    )

    if not isinstance(
        database,
        dict
    ):

        database = {
            "version": 3,
            "weeks": {}
        }

    database["version"] = 3

    database.setdefault(
        "weeks",
        {}
    )

    week_key = (
        week_start
        .date()
        .isoformat()
    )

    old_week = (
        database[
            "weeks"
        ].get(
            week_key,
            {}
        )
    )

    old_videos = (
        old_week.get(
            "videos",
            {}
        )
        if isinstance(
            old_week,
            dict
        )
        else {}
    )

    persistent = {}

    new_count = 0
    known_count = 0

    for (
        video_id,
        video
    ) in accepted.items():

        if video_id in old_videos:

            old_video = old_videos[
                video_id
            ]

            video[
                "first_seen"
            ] = old_video.get(
                "first_seen"
            ) or now.isoformat()

            known_count += 1

        else:

            video[
                "first_seen"
            ] = now.isoformat()

            new_count += 1

        video[
            "last_seen"
        ] = now.isoformat()

        persistent[
            video_id
        ] = video

    week_data = {
        "race_description":
            race_description,

        "leaderboard_url":
            race_url,

        "track":
            track,

        "race_class":
            race_class,

        "direction":
            (
                "REVERSE"
                if current_reverse
                else "NORMAL"
            ),

        "first_scan":
            (
                old_week.get(
                    "first_scan"
                )
                if isinstance(
                    old_week,
                    dict
                )
                else None
            )
            or now.isoformat(),

        "last_scan":
            now.isoformat(),

        "last_scan_stats": {
            "search_candidates":
                len(candidates),

            "accepted":
                len(accepted),

            "rejected":
                len(rejected),

            "new_videos":
                new_count,

            "previously_known":
                known_count,

            "total_tracked":
                len(persistent)
        },

        "videos":
            persistent
    }

    database[
        "weeks"
    ][
        week_key
    ] = week_data

    save_json(
        COMMUNITY_FILE,
        database
    )

    # ========================================================
    # OUTPUT
    # ========================================================

    ranked = sorted(
        persistent.values(),
        key=lambda item:
            item.get(
                "search_relevance",
                0
            ),
        reverse=True
    )

    print()

    print(
        "=" * 78
    )

    print(
        "COLLECTOR RESULT"
    )

    print(
        "=" * 78
    )

    print(
        f"Search candidates : "
        f"{len(candidates)}"
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
        f"{new_count}"
    )

    print(
        f"Already known     : "
        f"{known_count}"
    )

    print(
        f"Total tracked     : "
        f"{len(persistent)}"
    )

    print()

    print(
        "TOP COMMUNITY SOURCES"
    )

    print(
        "-" * 78
    )

    if not ranked:

        print(
            "No relevant videos found."
        )

    else:

        for index, video in enumerate(
            ranked[:25],
            start=1
        ):

            notes = ", ".join(
                video.get(
                    "validation_notes",
                    []
                )
            )

            print(
                f"{index:>2}. "
                f"[{video.get('search_relevance',0):02d}] "
                f"[{video.get('content_type','OTHER')}] "
                f"{video.get('channel','Unknown')} | "
                f"{video.get('title','')}"
            )

            print(
                f"    Date: "
                f"{video.get('title_date') or 'unverified'}"
            )

            print(
                f"    Notes: "
                f"{notes or 'none'}"
            )

            print(
                f"    "
                f"{video.get('url','')}"
            )

    print()

    print(
        "REJECTED SAMPLE"
    )

    print(
        "-" * 78
    )

    rejected_ranked = sorted(
        rejected.values(),
        key=lambda item:
            item.get(
                "search_relevance",
                0
            ),
        reverse=True
    )

    for index, video in enumerate(
        rejected_ranked[:20],
        start=1
    ):

        reasons = ", ".join(
            video.get(
                "rejection_reasons",
                []
            )
        )

        print(
            f"{index:>2}. "
            f"{video.get('channel','Unknown')} | "
            f"{video.get('title','')}"
        )

        print(
            f"    Reasons: "
            f"{reasons}"
        )

    print()

    print(
        f"Database saved    : "
        f"{COMMUNITY_FILE}"
    )

    print(
        "=" * 78
    )


if __name__ == "__main__":

    main()