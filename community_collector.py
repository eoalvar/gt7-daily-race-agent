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
# HELPERS
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


def parse_week_start(snapshot):

    start_date = (
        snapshot
        .get("race", {})
        .get("start_date")
    )

    if not start_date:
        raise RuntimeError(
            "Race start_date not found in latest_snapshot.json."
        )

    return datetime.fromisoformat(
        start_date
    )


# ============================================================
# BUILD SEARCH QUERIES
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

    # Remove the long regulations section as much as possible.
    clean = race_text

    clean = re.sub(
        r"^C\s+",
        "",
        clean
    )

    # Extract track from the known GTSH text.
    track = None

    match = re.search(
        r"Daily Race C.*?\d{1,2}:\d{2}\s+(.+?)\s+"
        r"(?:[A-Z]\.\s*[A-Za-z]|GT by|Genesis|Nissan|Toyota|"
        r"TOYOTA|Honda|Suzuki|BMW|Mazda|MAZDA|Ferrari|"
        r"Porsche|Renault|Volkswagen|Audi|Lexus|Ford|"
        r"Chevrolet|Jaguar|McLaren|Peugeot|Subaru|"
        r"Mitsubishi|Lamborghini|Dodge|Alfa)",
        clean,
        re.IGNORECASE
    )

    if match:
        track = match.group(1).strip()

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

    # Remove duplicates while preserving order.
    unique = []

    seen = set()

    for query in queries:

        key = normalize_text(query)

        if key not in seen:

            seen.add(key)
            unique.append(query)

    return unique, track


# ============================================================
# YT-DLP SEARCH
# ============================================================

def search_youtube(query):

    search_target = (
        f"ytsearchdate{MAX_RESULTS_PER_QUERY}:"
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

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=120
    )

    if result.returncode != 0:

        print(
            f"WARNING: search failed for: {query}"
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
            f"WARNING: invalid JSON for query: {query}"
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
# DATE FILTER
# ============================================================

def parse_upload_date(entry):

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
                str(upload_date),
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
    track
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
        score += 5

    elif "daily race" in title:
        score += 2

    if track:

        track_norm = normalize_text(
            track
        )

        if track_norm in title:
            score += 5

        # Useful if title contains only part of a long track name.
        important_words = [
            word
            for word in re.findall(
                r"[a-z0-9]+",
                track_norm
            )
            if len(word) >= 4
        ]

        matches = sum(
            1
            for word in important_words
            if word in title
        )

        score += min(
            matches,
            3
        )

    return score


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
            "data/latest_snapshot.json not found or invalid."
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

    # Allow a small margin before Monday in case a creator
    # publishes an early preview.
    earliest_allowed = (
        week_start
        - timedelta(days=1)
    )

    queries, track = build_queries(
        snapshot
    )

    print("=" * 78)
    print("GT7 COMMUNITY SOURCE COLLECTOR")
    print("=" * 78)

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
        print(f"  - {query}")

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
        existing["weeks"]
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

    # If race metadata improves later, refresh it.
    week_data[
        "race_description"
    ] = race_description

    week_data[
        "leaderboard_url"
    ] = race_url

    if track:
        week_data["track"] = track

    videos = week_data.setdefault(
        "videos",
        {}
    )

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
            f"  Results: {len(entries)}"
        )

        for entry in entries:

            video_id = entry.get(
                "id"
            )

            if not video_id:
                continue

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

            upload_datetime = (
                parse_upload_date(
                    entry
                )
            )

            # If date is known, reject clearly old videos.
            if (
                upload_datetime
                and upload_datetime
                < earliest_allowed
            ):
                continue

            score = relevance_score(
                entry,
                track
            )

            # Keep only plausibly relevant material.
            if score < 5:
                continue

            url = (
                f"https://www.youtube.com/watch?v="
                f"{video_id}"
            )

            candidate = {
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

                "relevance_score":
                    score,

                "matched_queries":
                    [query],

                "first_seen":
                    now.isoformat(),

                "last_seen":
                    now.isoformat(),

                "status":
                    "DISCOVERED"
            }

            if video_id in candidates:

                old_candidate = candidates[
                    video_id
                ]

                old_candidate[
                    "relevance_score"
                ] = max(
                    old_candidate[
                        "relevance_score"
                    ],
                    score
                )

                if (
                    query
                    not in old_candidate[
                        "matched_queries"
                    ]
                ):

                    old_candidate[
                        "matched_queries"
                    ].append(
                        query
                    )

            else:

                candidates[
                    video_id
                ] = candidate

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

            old_queries = (
                existing_video
                .setdefault(
                    "matched_queries",
                    []
                )
            )

            for query in candidate[
                "matched_queries"
            ]:

                if query not in old_queries:
                    old_queries.append(query)

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

    week_data[
        "last_scan"
    ] = now.isoformat()

    week_data[
        "last_scan_stats"
    ] = {
        "candidates_found":
            len(candidates),

        "new_videos":
            new_count,

        "previously_known":
            seen_again_count,

        "total_tracked":
            len(videos)
    }

    save_json(
        COMMUNITY_FILE,
        existing
    )

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
    print("=" * 78)
    print("COLLECTOR RESULT")
    print("=" * 78)

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
    print("TOP DISCOVERED SOURCES")
    print("-" * 78)

    if not ranked:

        print(
            "No relevant videos found."
        )

    else:

        for index, video in enumerate(
            ranked[:20],
            start=1
        ):

            print(
                f"{index:>2}. "
                f"[{video.get('relevance_score', 0):02d}] "
                f"{video.get('channel', 'Unknown')} | "
                f"{video.get('title', '')}"
            )

            print(
                f"    {video.get('url', '')}"
            )

    print()
    print(
        f"Database saved   : "
        f"{COMMUNITY_FILE}"
    )

    print("=" * 78)


if __name__ == "__main__":
    main()