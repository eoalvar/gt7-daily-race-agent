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

LATEST_SNAPSHOT_FILE = (
    DATA_DIR
    / "latest_snapshot.json"
)

COMMUNITY_FILE = (
    DATA_DIR
    / "community_sources.json"
)

SAO_PAULO = ZoneInfo(
    "America/Sao_Paulo"
)

MAX_RESULTS_PER_QUERY = 20


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

def normalize_text(
    text
):

    if not text:
        return ""

    text = text.lower()

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# ============================================================
# RACE WEEK
# ============================================================

def parse_week_start(
    snapshot
):

    start_date = (
        snapshot
        .get(
            "race",
            {}
        )
        .get(
            "start_date"
        )
    )

    if not start_date:

        raise RuntimeError(
            "Race start_date not found "
            "in data/latest_snapshot.json."
        )

    return datetime.fromisoformat(
        start_date
    )


# ============================================================
# TRACK EXTRACTION
# ============================================================

def extract_track(
    race_text
):

    if not race_text:
        return None

    # Expected structure:
    #
    # C Gr.4 Running 10 Aug 2026 Daily Race C i 16:48
    # Grand Valley - Highway 1
    # M. Estevez - GT by Citroën Gr.4
    # RM RS BoP ...
    #
    # The driver name immediately after the track normally
    # starts with an initial followed by a dot.

    match = re.search(
        r"Daily Race C.*?"
        r"\d{1,2}:\d{2}\s+"
        r"(.+?)\s+"
        r"[A-Z]\.\s*"
        r"[A-Za-zÀ-ÿ]",
        race_text,
        re.IGNORECASE
    )

    if match:

        track = (
            match
            .group(1)
            .strip()
        )

        if track:
            return track

    # --------------------------------------------------------
    # Fallback:
    # Attempt extraction before common car/manufacturer names.
    # --------------------------------------------------------

    manufacturer_pattern = (
        r"(?:GT by|Genesis|Hyundai|Nissan|Toyota|TOYOTA|"
        r"Honda|Suzuki|BMW|Mazda|MAZDA|Ferrari|Porsche|"
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

        track = (
            match
            .group(1)
            .strip()
        )

        if track:
            return track

    return None


# ============================================================
# SEARCH QUERIES
# ============================================================

def build_queries(
    snapshot
):

    race_text = (
        snapshot
        .get(
            "race",
            {}
        )
        .get(
            "description",
            ""
        )
    )

    if not race_text:

        raise RuntimeError(
            "Race description not found."
        )

    track = extract_track(
        race_text
    )

    queries = [
        "GT7 Daily Race C",
        "Gran Turismo 7 Daily Race C"
    ]

    if track:

        queries.extend([
            (
                f"GT7 Daily Race C "
                f"{track}"
            ),
            (
                f"Gran Turismo 7 Daily Race C "
                f"{track}"
            ),
            (
                f"GT7 {track} "
                f"Daily Race"
            )
        ])

    # --------------------------------------------------------
    # Remove duplicate queries while keeping original order.
    # --------------------------------------------------------

    unique_queries = []

    seen = set()

    for query in queries:

        key = normalize_text(
            query
        )

        if key in seen:
            continue

        seen.add(
            key
        )

        unique_queries.append(
            query
        )

    return (
        unique_queries,
        track
    )


# ============================================================
# YOUTUBE SEARCH VIA YT-DLP
#
# IMPORTANT:
# Use ytsearchN:, not ytsearchdateN:.
# ============================================================

def search_youtube(
    query
):

    search_target = (
        f"ytsearch{MAX_RESULTS_PER_QUERY}:"
        f"{query}"
    )

    command = [
        "yt-dlp",
        "--ignore-errors",
        "--skip-download",
        "--dump-single-json",
        "--flat-playlist",
        search_target
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
            f"WARNING: search timed out for: "
            f"{query}"
        )

        return []

    except Exception as exc:

        print(
            f"WARNING: yt-dlp execution failed "
            f"for: {query}"
        )

        print(
            f"Reason: {exc}"
        )

        return []

    if result.returncode != 0:

        print(
            f"WARNING: search failed for: "
            f"{query}"
        )

        if result.stderr:

            print(
                result.stderr[
                    -1500:
                ]
            )

        return []

    try:

        payload = json.loads(
            result.stdout
        )

    except Exception:

        print(
            f"WARNING: invalid JSON returned "
            f"for query: {query}"
        )

        if result.stdout:

            print(
                result.stdout[
                    -1000:
                ]
            )

        return []

    entries = payload.get(
        "entries",
        []
    )

    if not isinstance(
        entries,
        list
    ):

        return []

    return [
        entry
        for entry in entries
        if isinstance(
            entry,
            dict
        )
    ]


# ============================================================
# UPLOAD DATE
# ============================================================

def parse_upload_date(
    entry
):

    timestamp = entry.get(
        "timestamp"
    )

    if isinstance(
        timestamp,
        (int, float)
    ):

        try:

            return datetime.fromtimestamp(
                timestamp,
                tz=SAO_PAULO
            )

        except Exception:
            pass

    upload_date = entry.get(
        "upload_date"
    )

    if upload_date:

        try:

            parsed = datetime.strptime(
                str(
                    upload_date
                ),
                "%Y%m%d"
            )

            return parsed.replace(
                tzinfo=SAO_PAULO
            )

        except Exception:
            pass

    release_timestamp = entry.get(
        "release_timestamp"
    )

    if isinstance(
        release_timestamp,
        (int, float)
    ):

        try:

            return datetime.fromtimestamp(
                release_timestamp,
                tz=SAO_PAULO
            )

        except Exception:
            pass

    return None


# ============================================================
# RELEVANCE SCORING
# ============================================================

def relevance_score(
    entry,
    track
):

    title = normalize_text(
        entry.get(
            "title",
            ""
        )
    )

    description = normalize_text(
        entry.get(
            "description",
            ""
        )
    )

    text = (
        title
        + " "
        + description
    )

    score = 0

    # --------------------------------------------------------
    # GT7 identity
    # --------------------------------------------------------

    if "gt7" in title:
        score += 3

    if "gran turismo 7" in title:
        score += 3

    # --------------------------------------------------------
    # Daily Race identity
    # --------------------------------------------------------

    if "daily race c" in title:
        score += 7

    elif "daily races" in title:
        score += 3

    elif "daily race" in title:
        score += 3

    if "race c" in title:
        score += 3

    # --------------------------------------------------------
    # Track identity
    # --------------------------------------------------------

    if track:

        track_norm = normalize_text(
            track
        )

        if track_norm in text:

            score += 7

        important_words = [
            word
            for word in re.findall(
                r"[a-z0-9]+",
                track_norm
            )
            if len(word) >= 4
        ]

        matching_words = sum(
            1
            for word in important_words
            if word in text
        )

        score += min(
            matching_words,
            4
        )

    # --------------------------------------------------------
    # Useful GT7 content keywords
    # --------------------------------------------------------

    useful_terms = [
        "guide",
        "lap guide",
        "strategy",
        "race strategy",
        "qualifying",
        "hotlap",
        "hot lap",
        "track guide",
        "daily races",
        "weekly races"
    ]

    for term in useful_terms:

        if term in title:

            score += 1

    return score


# ============================================================
# ENTRY NORMALIZATION
# ============================================================

def normalize_entry(
    entry,
    query,
    track,
    now
):

    video_id = entry.get(
        "id"
    )

    if not video_id:
        return None

    title = entry.get(
        "title",
        ""
    )

    channel = (
        entry.get(
            "channel"
        )
        or entry.get(
            "uploader"
        )
        or entry.get(
            "channel_id"
        )
        or "Unknown"
    )

    upload_datetime = (
        parse_upload_date(
            entry
        )
    )

    score = relevance_score(
        entry,
        track
    )

    url = (
        "https://www.youtube.com/watch?v="
        f"{video_id}"
    )

    return {
        "video_id":
            video_id,

        "title":
            title,

        "channel":
            channel,

        "url":
            url,

        "upload_datetime":
            (
                upload_datetime.isoformat()
                if upload_datetime
                else None
            ),

        "duration":
            entry.get(
                "duration"
            ),

        "view_count":
            entry.get(
                "view_count"
            ),

        "relevance_score":
            score,

        "matched_queries":
            [
                query
            ],

        "first_seen":
            now.isoformat(),

        "last_seen":
            now.isoformat(),

        "status":
            "DISCOVERED"
    }


# ============================================================
# MERGE CANDIDATES
# ============================================================

def merge_candidate(
    candidates,
    candidate
):

    video_id = candidate[
        "video_id"
    ]

    if video_id not in candidates:

        candidates[
            video_id
        ] = candidate

        return

    existing = candidates[
        video_id
    ]

    existing[
        "relevance_score"
    ] = max(
        existing.get(
            "relevance_score",
            0
        ),
        candidate.get(
            "relevance_score",
            0
        )
    )

    existing_queries = (
        existing
        .setdefault(
            "matched_queries",
            []
        )
    )

    for query in candidate.get(
        "matched_queries",
        []
    ):

        if query not in existing_queries:

            existing_queries.append(
                query
            )

    if (
        not existing.get(
            "upload_datetime"
        )
        and candidate.get(
            "upload_datetime"
        )
    ):

        existing[
            "upload_datetime"
        ] = candidate[
            "upload_datetime"
        ]


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

    race_url = race.get(
        "leaderboard_url"
    )

    race_description = race.get(
        "description"
    )

    week_start = parse_week_start(
        snapshot
    )

    # --------------------------------------------------------
    # Permit videos published on Sunday before the race week.
    # This catches previews uploaded shortly before Monday.
    # --------------------------------------------------------

    earliest_allowed = (
        week_start
        - timedelta(
            days=1
        )
    )

    queries, track = build_queries(
        snapshot
    )

    print(
        "=" * 78
    )

    print(
        "GT7 COMMUNITY SOURCE COLLECTOR"
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
        f"Search queries  : "
        f"{len(queries)}"
    )

    for query in queries:

        print(
            f"  - {query}"
        )

    # ========================================================
    # LOAD COMMUNITY DATABASE
    # ========================================================

    existing = load_json(
        COMMUNITY_FILE,
        {
            "version": 1,
            "weeks": {}
        }
    )

    if not isinstance(
        existing,
        dict
    ):

        existing = {
            "version": 1,
            "weeks": {}
        }

    existing.setdefault(
        "version",
        1
    )

    existing.setdefault(
        "weeks",
        {}
    )

    week_key = (
        week_start
        .date()
        .isoformat()
    )

    week_data = (
        existing[
            "weeks"
        ]
        .setdefault(
            week_key,
            {
                "race_description":
                    race_description,

                "leaderboard_url":
                    race_url,

                "track":
                    track,

                "first_scan":
                    now.isoformat(),

                "last_scan":
                    None,

                "videos":
                    {}
            }
        )
    )

    # --------------------------------------------------------
    # Refresh metadata every run.
    # --------------------------------------------------------

    week_data[
        "race_description"
    ] = race_description

    week_data[
        "leaderboard_url"
    ] = race_url

    if track:

        week_data[
            "track"
        ] = track

    videos = (
        week_data
        .setdefault(
            "videos",
            {}
        )
    )

    candidates = {}

    # ========================================================
    # RUN SEARCHES
    # ========================================================

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

        accepted_this_query = 0

        for entry in entries:

            candidate = normalize_entry(
                entry,
                query,
                track,
                now
            )

            if not candidate:
                continue

            upload_datetime_text = (
                candidate.get(
                    "upload_datetime"
                )
            )

            upload_datetime = None

            if upload_datetime_text:

                try:

                    upload_datetime = (
                        datetime
                        .fromisoformat(
                            upload_datetime_text
                        )
                    )

                except Exception:
                    pass

            # ------------------------------------------------
            # Reject clearly old videos where date is known.
            #
            # Flat search results may not always provide a date,
            # so unknown dates are not rejected at this stage.
            # ------------------------------------------------

            if (
                upload_datetime
                and upload_datetime
                < earliest_allowed
            ):

                continue

            # ------------------------------------------------
            # Minimum relevance.
            # ------------------------------------------------

            if (
                candidate[
                    "relevance_score"
                ]
                < 5
            ):

                continue

            merge_candidate(
                candidates,
                candidate
            )

            accepted_this_query += 1

        print(
            f"  Accepted: "
            f"{accepted_this_query}"
        )

    # ========================================================
    # MERGE INTO PERSISTENT DATABASE
    # ========================================================

    new_count = 0
    seen_again_count = 0

    for (
        video_id,
        candidate
    ) in candidates.items():

        if video_id in videos:

            existing_video = videos[
                video_id
            ]

            existing_video[
                "last_seen"
            ] = now.isoformat()

            existing_video[
                "title"
            ] = candidate[
                "title"
            ]

            existing_video[
                "channel"
            ] = candidate[
                "channel"
            ]

            existing_video[
                "url"
            ] = candidate[
                "url"
            ]

            existing_video[
                "relevance_score"
            ] = max(
                existing_video.get(
                    "relevance_score",
                    0
                ),
                candidate[
                    "relevance_score"
                ]
            )

            if (
                candidate.get(
                    "view_count"
                )
                is not None
            ):

                existing_video[
                    "view_count"
                ] = candidate[
                    "view_count"
                ]

            if (
                candidate.get(
                    "duration"
                )
                is not None
            ):

                existing_video[
                    "duration"
                ] = candidate[
                    "duration"
                ]

            old_queries = (
                existing_video
                .setdefault(
                    "matched_queries",
                    []
                )
            )

            for query in candidate.get(
                "matched_queries",
                []
            ):

                if query not in old_queries:

                    old_queries.append(
                        query
                    )

            if (
                not existing_video.get(
                    "upload_datetime"
                )
                and candidate.get(
                    "upload_datetime"
                )
            ):

                existing_video[
                    "upload_datetime"
                ] = candidate[
                    "upload_datetime"
                ]

            seen_again_count += 1

        else:

            videos[
                video_id
            ] = candidate

            new_count += 1

    # ========================================================
    # SCAN METADATA
    # ========================================================

    week_data[
        "last_scan"
    ] = now.isoformat()

    week_data[
        "last_scan_stats"
    ] = {
        "candidates_found":
            len(
                candidates
            ),

        "new_videos":
            new_count,

        "previously_known":
            seen_again_count,

        "total_tracked":
            len(
                videos
            )
    }

    save_json(
        COMMUNITY_FILE,
        existing
    )

    # ========================================================
    # DISPLAY RESULTS
    # ========================================================

    ranked = sorted(
        videos.values(),
        key=lambda item: (
            item.get(
                "relevance_score",
                0
            ),
            item.get(
                "upload_datetime"
            )
            or ""
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
        f"Candidates found : "
        f"{len(candidates)}"
    )

    print(
        f"New videos       : "
        f"{new_count}"
    )

    print(
        f"Already known    : "
        f"{seen_again_count}"
    )

    print(
        f"Total tracked    : "
        f"{len(videos)}"
    )

    print()

    print(
        "TOP DISCOVERED SOURCES"
    )

    print(
        "-" * 78
    )

    if not ranked:

        print(
            "No relevant videos found."
        )

    else:

        for (
            index,
            video
        ) in enumerate(
            ranked[
                :20
            ],
            start=1
        ):

            upload_display = (
                video.get(
                    "upload_datetime"
                )
                or "date unknown"
            )

            print(
                f"{index:>2}. "
                f"[{video.get('relevance_score', 0):02d}] "
                f"{video.get('channel', 'Unknown')} | "
                f"{video.get('title', '')}"
            )

            print(
                f"    Published: "
                f"{upload_display}"
            )

            print(
                f"    "
                f"{video.get('url', '')}"
            )

    print()

    print(
        f"Database saved   : "
        f"{COMMUNITY_FILE}"
    )

    print(
        "=" * 78
    )


if __name__ == "__main__":

    main()