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

# Avoid enriching too many weak search results.
MAX_ENRICH_CANDIDATES = 40


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


def normalize_track_text(
    text
):

    text = normalize_text(
        text
    )

    text = text.replace(
        "-",
        " "
    )

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


def extract_track(
    race_text
):

    if not race_text:
        return None

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


def extract_race_class(
    race_text
):

    if not race_text:
        return None

    match = re.search(
        r"\bGr\.(\d)\b",
        race_text,
        re.IGNORECASE
    )

    if not match:
        return None

    return (
        f"Gr.{match.group(1)}"
    )


def race_is_reverse(
    race_text
):

    return (
        "reverse"
        in normalize_text(
            race_text
        )
    )


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
            )
        ])

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
        track,
        race_class
    )


# ============================================================
# YOUTUBE SEARCH VIA YT-DLP
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
            f"WARNING: search timed out: "
            f"{query}"
        )

        return []

    except Exception as exc:

        print(
            f"WARNING: yt-dlp search failed: "
            f"{query}"
        )

        print(
            f"Reason: {exc}"
        )

        return []

    if result.returncode != 0:

        print(
            f"WARNING: search failed: "
            f"{query}"
        )

        if result.stderr:

            print(
                result.stderr[
                    -1200:
                ]
            )

        return []

    try:

        payload = json.loads(
            result.stdout
        )

    except Exception:

        print(
            f"WARNING: invalid search JSON: "
            f"{query}"
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
# FULL VIDEO METADATA
# ============================================================

def get_full_video_metadata(
    video_id
):

    url = (
        "https://www.youtube.com/watch?v="
        f"{video_id}"
    )

    command = [
        "yt-dlp",
        "--ignore-errors",
        "--skip-download",
        "--dump-single-json",
        "--no-playlist",
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

        print(
            f"    Metadata timeout: "
            f"{video_id}"
        )

        return None

    except Exception as exc:

        print(
            f"    Metadata failure: "
            f"{video_id} | {exc}"
        )

        return None

    if result.returncode != 0:

        print(
            f"    Metadata unavailable: "
            f"{video_id}"
        )

        return None

    try:

        payload = json.loads(
            result.stdout
        )

    except Exception:

        return None

    if not isinstance(
        payload,
        dict
    ):

        return None

    return payload


# ============================================================
# DATE HELPERS
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

    return None


# ============================================================
# RELEVANCE
# ============================================================

def relevance_score(
    entry,
    track,
    race_class
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

    if "gt7" in title:
        score += 3

    if "gran turismo 7" in title:
        score += 3

    if "daily race c" in title:
        score += 7

    elif "daily race" in title:
        score += 3

    if "race c" in title:
        score += 3

    if track:

        track_norm = normalize_track_text(
            track
        )

        text_norm = normalize_track_text(
            text
        )

        if track_norm in text_norm:
            score += 8

        important_words = [
            word
            for word in track_norm.split()
            if len(word) >= 4
        ]

        matching_words = sum(
            1
            for word in important_words
            if word in text_norm
        )

        score += min(
            matching_words,
            4
        )

    if race_class:

        class_norm = normalize_text(
            race_class
        )

        class_variants = [
            class_norm,
            class_norm.replace(
                ".",
                ""
            ),
            class_norm.replace(
                ".",
                " "
            ),
            (
                "group "
                + race_class[-1]
            )
        ]

        if any(
            variant in text
            for variant in class_variants
        ):

            score += 5

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
        "weekly races",
        "tips"
    ]

    for term in useful_terms:

        if term in title:
            score += 1

    return score


# ============================================================
# EXACT RACE VALIDATION
# ============================================================

def validate_video(
    metadata,
    track,
    race_class,
    current_reverse,
    earliest_allowed,
    latest_allowed
):

    reasons = []

    title = normalize_text(
        metadata.get(
            "title",
            ""
        )
    )

    description = normalize_text(
        metadata.get(
            "description",
            ""
        )
    )

    text = (
        title
        + " "
        + description
    )

    # --------------------------------------------------------
    # DATE
    # --------------------------------------------------------

    upload_datetime = parse_upload_date(
        metadata
    )

    if upload_datetime is None:

        reasons.append(
            "DATE_UNKNOWN"
        )

    else:

        if upload_datetime < earliest_allowed:

            reasons.append(
                "TOO_OLD"
            )

        if upload_datetime > latest_allowed:

            reasons.append(
                "FUTURE_DATE"
            )

    # --------------------------------------------------------
    # GT7 / DAILY RACE C IDENTITY
    # --------------------------------------------------------

    gt7_match = (
        "gt7" in text
        or "gran turismo 7" in text
    )

    if not gt7_match:

        reasons.append(
            "NOT_GT7"
        )

    race_c_match = (
        "daily race c" in text
        or (
            "daily race" in text
            and "race c" in text
        )
    )

    if not race_c_match:

        reasons.append(
            "NOT_RACE_C"
        )

    # --------------------------------------------------------
    # TRACK
    # --------------------------------------------------------

    if track:

        track_norm = normalize_track_text(
            track
        )

        text_norm = normalize_track_text(
            text
        )

        track_words = [
            word
            for word in track_norm.split()
            if len(word) >= 4
        ]

        matches = sum(
            1
            for word in track_words
            if word in text_norm
        )

        minimum_matches = max(
            2,
            len(track_words) - 1
        )

        if matches < minimum_matches:

            reasons.append(
                "WRONG_TRACK"
            )

    # --------------------------------------------------------
    # REVERSE / NORMAL DIRECTION
    # --------------------------------------------------------

    video_reverse = (
        "reverse"
        in text
    )

    if (
        current_reverse
        and not video_reverse
    ):

        # Do not strictly reject normal titles for a Reverse
        # race unless enough metadata exists.
        pass

    elif (
        not current_reverse
        and video_reverse
    ):

        reasons.append(
            "WRONG_DIRECTION"
        )

    # --------------------------------------------------------
    # RACE CLASS
    #
    # Explicit wrong class is rejected.
    # Lack of class text is allowed because some excellent
    # guides omit it from the title/description.
    # --------------------------------------------------------

    explicit_classes = set(
        re.findall(
            r"\b(?:gr\.?|group)\s*([1-4])\b",
            text,
            re.IGNORECASE
        )
    )

    if (
        race_class
        and explicit_classes
    ):

        expected_number = (
            race_class[
                -1
            ]
        )

        if expected_number not in explicit_classes:

            reasons.append(
                "WRONG_CLASS"
            )

    hard_rejections = {
        "TOO_OLD",
        "FUTURE_DATE",
        "NOT_GT7",
        "NOT_RACE_C",
        "WRONG_TRACK",
        "WRONG_DIRECTION",
        "WRONG_CLASS"
    }

    rejected = any(
        reason in hard_rejections
        for reason in reasons
    )

    return {
        "accepted":
            not rejected,

        "reasons":
            reasons,

        "upload_datetime":
            (
                upload_datetime.isoformat()
                if upload_datetime
                else None
            )
    }


# ============================================================
# SEARCH CANDIDATE MERGE
# ============================================================

def merge_search_candidate(
    candidates,
    entry,
    query,
    track,
    race_class
):

    video_id = entry.get(
        "id"
    )

    if not video_id:
        return

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

    score = relevance_score(
        entry,
        track,
        race_class
    )

    if video_id not in candidates:

        candidates[
            video_id
        ] = {
            "video_id":
                video_id,

            "title":
                title,

            "channel":
                channel,

            "search_relevance":
                score,

            "matched_queries":
                [
                    query
                ]
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

    queries = candidate.setdefault(
        "matched_queries",
        []
    )

    if query not in queries:

        queries.append(
            query
        )


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
        "description",
        ""
    )

    week_start = parse_week_start(
        snapshot
    )

    queries, track, race_class = build_queries(
        snapshot
    )

    current_reverse = race_is_reverse(
        race_description
    )

    # Include preview videos from Sunday before Monday.
    earliest_allowed = (
        week_start
        - timedelta(
            days=1
        )
    )

    # Do not allow timestamps beyond the current scan.
    latest_allowed = (
        now
        + timedelta(
            hours=2
        )
    )

    print(
        "=" * 78
    )

    print(
        "GT7 COMMUNITY SOURCE COLLECTOR V2"
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
        f"Earliest video  : "
        f"{earliest_allowed.date().isoformat()}"
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

            merge_search_candidate(
                candidates,
                entry,
                query,
                track,
                race_class
            )

    # --------------------------------------------------------
    # Rank candidates BEFORE expensive metadata enrichment.
    # --------------------------------------------------------

    ranked_candidates = sorted(
        candidates.values(),
        key=lambda item:
            item.get(
                "search_relevance",
                0
            ),
        reverse=True
    )

    ranked_candidates = ranked_candidates[
        :MAX_ENRICH_CANDIDATES
    ]

    print()

    print(
        f"Unique search candidates : "
        f"{len(candidates)}"
    )

    print(
        f"Candidates to enrich     : "
        f"{len(ranked_candidates)}"
    )

    # ========================================================
    # ENRICH + VALIDATE
    # ========================================================

    accepted = {}
    rejected = {}

    for index, search_candidate in enumerate(
        ranked_candidates,
        start=1
    ):

        video_id = search_candidate[
            "video_id"
        ]

        print(
            f"[{index:02d}/{len(ranked_candidates):02d}] "
            f"Enriching {video_id} | "
            f"{search_candidate.get('title','')[:70]}"
        )

        metadata = get_full_video_metadata(
            video_id
        )

        if not metadata:

            rejected[
                video_id
            ] = {
                "video_id":
                    video_id,

                "title":
                    search_candidate.get(
                        "title"
                    ),

                "channel":
                    search_candidate.get(
                        "channel"
                    ),

                "reasons":
                    [
                        "METADATA_UNAVAILABLE"
                    ]
            }

            continue

        validation = validate_video(
            metadata,
            track,
            race_class,
            current_reverse,
            earliest_allowed,
            latest_allowed
        )

        score = relevance_score(
            metadata,
            track,
            race_class
        )

        video = {
            "video_id":
                video_id,

            "title":
                metadata.get(
                    "title"
                )
                or search_candidate.get(
                    "title"
                ),

            "channel":
                (
                    metadata.get(
                        "channel"
                    )
                    or metadata.get(
                        "uploader"
                    )
                    or search_candidate.get(
                        "channel"
                    )
                    or "Unknown"
                ),

            "channel_id":
                metadata.get(
                    "channel_id"
                ),

            "url":
                (
                    "https://www.youtube.com/watch?v="
                    f"{video_id}"
                ),

            "upload_datetime":
                validation[
                    "upload_datetime"
                ],

            "duration":
                metadata.get(
                    "duration"
                ),

            "view_count":
                metadata.get(
                    "view_count"
                ),

            "description":
                metadata.get(
                    "description"
                ),

            "relevance_score":
                score,

            "matched_queries":
                search_candidate.get(
                    "matched_queries",
                    []
                ),

            "validation_notes":
                validation[
                    "reasons"
                ]
        }

        if validation[
            "accepted"
        ]:

            accepted[
                video_id
            ] = video

        else:

            rejected[
                video_id
            ] = {
                **video,

                "reasons":
                    validation[
                        "reasons"
                    ]
            }

    # ========================================================
    # LOAD PERSISTENT DATABASE
    # ========================================================

    database = load_json(
        COMMUNITY_FILE,
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

    week_key = (
        week_start
        .date()
        .isoformat()
    )

    old_week = (
        database[
            "weeks"
        ]
        .get(
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

    # ========================================================
    # PRESERVE PREVIOUSLY ACCEPTED VIDEOS
    #
    # But revalidate them where possible so the bad V1 entries
    # are cleaned automatically.
    # ========================================================

    persistent_videos = {}

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

        video[
            "status"
        ] = "ACCEPTED"

        persistent_videos[
            video_id
        ] = video

    # --------------------------------------------------------
    # Preserve older ACCEPTED entries that were not returned
    # in today's search, but do NOT preserve old V1 entries
    # blindly. They need to have a validated upload date.
    # --------------------------------------------------------

    for (
        video_id,
        old_video
    ) in old_videos.items():

        if video_id in persistent_videos:
            continue

        if (
            old_video.get(
                "status"
            )
            == "ACCEPTED"
            and old_video.get(
                "upload_datetime"
            )
        ):

            persistent_videos[
                video_id
            ] = old_video

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
                len(
                    candidates
                ),

            "enriched":
                len(
                    ranked_candidates
                ),

            "accepted_this_scan":
                len(
                    accepted
                ),

            "rejected_this_scan":
                len(
                    rejected
                ),

            "new_videos":
                new_count,

            "previously_known":
                known_count,

            "total_tracked":
                len(
                    persistent_videos
                )
        },

        "videos":
            persistent_videos
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
    # REPORT
    # ========================================================

    ranked_accepted = sorted(
        persistent_videos.values(),
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
        f"Search candidates : "
        f"{len(candidates)}"
    )

    print(
        f"Enriched          : "
        f"{len(ranked_candidates)}"
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
        f"{len(persistent_videos)}"
    )

    print()

    print(
        "ACCEPTED COMMUNITY SOURCES"
    )

    print(
        "-" * 78
    )

    if not ranked_accepted:

        print(
            "No validated current-week videos found."
        )

    else:

        for index, video in enumerate(
            ranked_accepted[
                :20
            ],
            start=1
        ):

            print(
                f"{index:>2}. "
                f"[{video.get('relevance_score',0):02d}] "
                f"{video.get('channel','Unknown')} | "
                f"{video.get('title','')}"
            )

            print(
                f"    Published: "
                f"{video.get('upload_datetime','unknown')}"
            )

            print(
                f"    "
                f"{video.get('url','')}"
            )

            if video.get(
                "validation_notes"
            ):

                print(
                    f"    Notes: "
                    f"{', '.join(video['validation_notes'])}"
                )

    print()

    print(
        "REJECTED SAMPLE"
    )

    print(
        "-" * 78
    )

    for index, video in enumerate(
        list(
            rejected.values()
        )[
            :15
        ],
        start=1
    ):

        print(
            f"{index:>2}. "
            f"{video.get('channel','Unknown')} | "
            f"{video.get('title','')}"
        )

        print(
            f"    Reasons: "
            f"{', '.join(video.get('reasons', []))}"
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