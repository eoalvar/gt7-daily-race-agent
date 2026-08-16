import json
import re
from pathlib import Path
from collections import defaultdict


# ============================================================
# CONFIG
# ============================================================

DATA_DIR = Path("data")

TRANSCRIPT_DIRS = [
    DATA_DIR / "community_transcripts",
    DATA_DIR / "community_supadata_test" / "transcripts",
]

OUTPUT_DIR = DATA_DIR / "community_intelligence"

OUTPUT_JSON = (
    OUTPUT_DIR
    / "community_intelligence.json"
)

OUTPUT_REPORT = (
    OUTPUT_DIR
    / "community_intelligence.txt"
)


# ============================================================
# KEYWORD GROUPS
# ============================================================

CATEGORY_KEYWORDS = {

    "RACE_STRATEGY": [
        "strategy",
        "race strategy",
        "pit",
        "pit stop",
        "stint",
        "mandatory",
        "medium",
        "soft",
        "hard",
        "tyre",
        "tire",
        "fuel",
        "save fuel",
        "fuel saving",
        "undercut",
        "overcut",
    ],

    "BRAKING": [
        "brake",
        "braking",
        "braking point",
        "braking marker",
        "brake marker",
        "brake at",
        "brake just",
        "brake before",
        "brake after",
    ],

    "GEARS": [
        "first gear",
        "second gear",
        "third gear",
        "fourth gear",
        "fifth gear",
        "sixth gear",
        "1st gear",
        "2nd gear",
        "3rd gear",
        "4th gear",
        "5th gear",
        "6th gear",
        "gear",
        "shift",
        "short shift",
        "upshift",
        "downshift",
    ],

    "RACING_LINE": [
        "line",
        "racing line",
        "apex",
        "turn in",
        "turn-in",
        "entry",
        "exit",
        "inside",
        "outside",
        "wide",
        "tight",
        "position the car",
    ],

    "THROTTLE": [
        "throttle",
        "accelerate",
        "acceleration",
        "full throttle",
        "flat out",
        "lift",
        "coast",
        "coasting",
    ],

    "KERBS": [
        "kerb",
        "kerbs",
        "curb",
        "curbs",
        "track limits",
        "white line",
    ],

    "CARS_META": [
        "meta",
        "car of choice",
        "popular",
        "best car",
        "gtr",
        "gt-r",
        "citroen",
        "genesis",
        "silvia",
        "swift",
        "nsx",
        "group four",
        "gr.4",
        "gr4",
    ],

    "RACECRAFT": [
        "overtake",
        "overtaking",
        "defend",
        "defensive",
        "draft",
        "slipstream",
        "dirty air",
        "traffic",
        "battle",
        "racecraft",
    ],

    "WARNINGS": [
        "careful",
        "warning",
        "don't",
        "do not",
        "avoid",
        "easy to",
        "risk",
        "penalty",
        "understeer",
        "oversteer",
        "spin",
        "lose time",
        "mistake",
    ],
}


# ============================================================
# TEXT HELPERS
# ============================================================

def normalize_space(text):

    return re.sub(
        r"\s+",
        " ",
        text or ""
    ).strip()


def normalize_compare(text):

    text = normalize_space(
        text
    ).lower()

    text = re.sub(
        r"[^a-z0-9 ]+",
        " ",
        text
    )

    return normalize_space(
        text
    )


def split_sentences(text):

    text = normalize_space(
        text
    )

    if not text:
        return []

    parts = re.split(
        r"(?<=[.!?])\s+",
        text
    )

    cleaned = []

    for part in parts:

        part = normalize_space(
            part
        )

        if len(part) < 25:
            continue

        cleaned.append(
            part
        )

    return cleaned


# ============================================================
# LOAD TRANSCRIPTS
# ============================================================

def find_transcript_files():

    files = []

    for base in TRANSCRIPT_DIRS:

        if not base.exists():
            continue

        files.extend(
            base.rglob(
                "*.json"
            )
        )

    unique = {}

    for path in files:

        try:

            data = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )

        except Exception:
            continue

        transcript = data.get(
            "transcript"
        )

        video_id = data.get(
            "video_id"
        )

        if (
            not transcript
            or not video_id
        ):
            continue

        # Prefer the first valid copy found.
        if video_id not in unique:

            unique[
                video_id
            ] = {
                "path":
                    str(path),

                "data":
                    data
            }

    return list(
        unique.values()
    )


# ============================================================
# SENTENCE SCORING
# ============================================================

def category_score(
    sentence,
    keywords
):

    normalized = (
        sentence.lower()
    )

    score = 0

    for keyword in keywords:

        if keyword in normalized:
            score += 1

    return score


def classify_sentence(
    sentence
):

    categories = []

    for category, keywords in (
        CATEGORY_KEYWORDS.items()
    ):

        score = category_score(
            sentence,
            keywords
        )

        if score > 0:

            categories.append(
                (
                    category,
                    score
                )
            )

    categories.sort(
        key=lambda item:
            item[1],
        reverse=True
    )

    return categories


# ============================================================
# EXTRACT STRUCTURED OBSERVATIONS
# ============================================================

def extract_observations(
    transcripts
):

    observations = defaultdict(
        list
    )

    for source in transcripts:

        data = source[
            "data"
        ]

        channel = data.get(
            "channel",
            "Unknown"
        )

        title = data.get(
            "title",
            ""
        )

        video_id = data.get(
            "video_id"
        )

        content_type = data.get(
            "content_type",
            "OTHER"
        )

        text = data.get(
            "transcript",
            ""
        )

        sentences = split_sentences(
            text
        )

        for sentence in sentences:

            classifications = (
                classify_sentence(
                    sentence
                )
            )

            if not classifications:
                continue

            for category, score in (
                classifications[:2]
            ):

                observations[
                    category
                ].append({
                    "channel":
                        channel,

                    "video_id":
                        video_id,

                    "title":
                        title,

                    "content_type":
                        content_type,

                    "score":
                        score,

                    "text":
                        sentence
                })

    return observations


# ============================================================
# DEDUPLICATION
# ============================================================

def word_set(text):

    return set(
        normalize_compare(
            text
        ).split()
    )


def similarity(
    a,
    b
):

    set_a = word_set(
        a
    )

    set_b = word_set(
        b
    )

    if (
        not set_a
        or not set_b
    ):
        return 0

    intersection = len(
        set_a & set_b
    )

    union = len(
        set_a | set_b
    )

    return (
        intersection
        / union
    )


def deduplicate_items(
    items,
    threshold=0.65
):

    results = []

    for item in items:

        duplicate = False

        for existing in results:

            if (
                similarity(
                    item["text"],
                    existing["text"]
                )
                >= threshold
            ):

                duplicate = True
                break

        if not duplicate:

            results.append(
                item
            )

    return results


# ============================================================
# RANK CATEGORY ITEMS
# ============================================================

def rank_category(
    items,
    limit=12
):

    deduped = deduplicate_items(
        items
    )

    for item in deduped:

        item[
            "ranking_score"
        ] = (
            item.get(
                "score",
                0
            )
            * 10
        )

        content_type = item.get(
            "content_type"
        )

        if content_type == "STRATEGY":

            item[
                "ranking_score"
            ] += 5

        elif content_type == "LAP_GUIDE":

            item[
                "ranking_score"
            ] += 4

        elif content_type == "QUALIFYING":

            item[
                "ranking_score"
            ] += 3

    deduped.sort(
        key=lambda item:
            item[
                "ranking_score"
            ],
        reverse=True
    )

    return deduped[
        :limit
    ]


# ============================================================
# CONSENSUS ENGINE
# ============================================================

def build_consensus(
    observations
):

    all_items = []

    for category, items in (
        observations.items()
    ):

        for item in items:

            all_items.append({
                **item,
                "category":
                    category
            })

    groups = []

    for item in all_items:

        found = None

        for group in groups:

            if (
                similarity(
                    item[
                        "text"
                    ],
                    group[
                        "representative"
                    ][
                        "text"
                    ]
                )
                >= 0.45
            ):

                found = group
                break

        if found is None:

            groups.append({
                "representative":
                    item,

                "items":
                    [item]
            })

        else:

            found[
                "items"
            ].append(
                item
            )

    results = []

    for group in groups:

        channels = sorted(
            {
                item[
                    "channel"
                ]
                for item in group[
                    "items"
                ]
            }
        )

        if len(channels) < 2:
            continue

        results.append({
            "category":
                group[
                    "representative"
                ][
                    "category"
                ],

            "text":
                group[
                    "representative"
                ][
                    "text"
                ],

            "channels":
                channels,

            "source_count":
                len(
                    channels
                )
        })

    results.sort(
        key=lambda item:
            item[
                "source_count"
            ],
        reverse=True
    )

    return results[
        :10
    ]


# ============================================================
# TOP TAKEAWAYS
# ============================================================

def build_top_takeaways(
    ranked
):

    priority_order = [
        "RACE_STRATEGY",
        "BRAKING",
        "RACING_LINE",
        "THROTTLE",
        "GEARS",
        "CARS_META",
        "WARNINGS",
        "KERBS",
        "RACECRAFT",
    ]

    results = []

    seen = []

    for category in priority_order:

        for item in ranked.get(
            category,
            []
        ):

            if any(
                similarity(
                    item[
                        "text"
                    ],
                    previous
                )
                >= 0.55
                for previous in seen
            ):
                continue

            results.append({
                "category":
                    category,

                "channel":
                    item[
                        "channel"
                    ],

                "text":
                    item[
                        "text"
                    ]
            })

            seen.append(
                item[
                    "text"
                ]
            )

            if len(results) >= 10:
                return results

    return results


# ============================================================
# BUILD REPORT
# ============================================================

def build_report(
    transcripts,
    ranked,
    consensus,
    takeaways
):

    lines = []

    lines.append(
        "GT7 COMMUNITY INTELLIGENCE"
    )

    lines.append(
        "=" * 88
    )

    lines.append(
        f"Sources analysed : "
        f"{len(transcripts)}"
    )

    lines.append("")

    lines.append(
        "SOURCES"
    )

    lines.append(
        "-" * 88
    )

    for source in transcripts:

        data = source[
            "data"
        ]

        lines.append(
            f"- "
            f"{data.get('channel','Unknown')} | "
            f"{data.get('content_type','OTHER')} | "
            f"{data.get('word_count',0):,} words"
        )

        lines.append(
            f"  "
            f"{data.get('title','')}"
        )

    category_titles = {
        "RACE_STRATEGY":
            "RACE STRATEGY",

        "BRAKING":
            "BRAKING POINTS",

        "GEARS":
            "GEARS / SHIFTING",

        "RACING_LINE":
            "RACING LINE",

        "THROTTLE":
            "THROTTLE / ACCELERATION",

        "KERBS":
            "KERBS / TRACK LIMITS",

        "CARS_META":
            "CARS / META",

        "RACECRAFT":
            "RACECRAFT",

        "WARNINGS":
            "MISTAKES / WARNINGS",
    }

    for category, title in (
        category_titles.items()
    ):

        lines.append("")
        lines.append(
            title
        )

        lines.append(
            "-" * 88
        )

        items = ranked.get(
            category,
            []
        )

        if not items:

            lines.append(
                "No strong transcript evidence found."
            )

            continue

        for item in items[:8]:

            lines.append(
                f"- [{item['channel']}] "
                f"{item['text']}"
            )

    lines.append("")
    lines.append(
        "CONSENSUS BETWEEN SOURCES"
    )

    lines.append(
        "-" * 88
    )

    if not consensus:

        lines.append(
            "No strong multi-source consensus detected automatically."
        )

    else:

        for item in consensus:

            lines.append(
                f"- [{item['category']}] "
                f"{item['text']}"
            )

            lines.append(
                f"  Sources: "
                f"{', '.join(item['channels'])}"
            )

    lines.append("")
    lines.append(
        "TOP PRACTICAL TAKEAWAYS"
    )

    lines.append(
        "-" * 88
    )

    for index, item in enumerate(
        takeaways,
        start=1
    ):

        lines.append(
            f"{index}. "
            f"[{item['category']}] "
            f"{item['text']} "
            f"({item['channel']})"
        )

    lines.append("")
    lines.append(
        "ANALYSIS NOTE"
    )

    lines.append(
        "-" * 88
    )

    lines.append(
        "This report is generated from transcript evidence only. "
        "It does not invent missing braking points, gears or strategy. "
        "Automatic sentence classification is heuristic and should be "
        "treated as community intelligence rather than telemetry validation."
    )

    lines.append("")
    lines.append(
        "=" * 88
    )

    return "\n".join(
        lines
    )


# ============================================================
# MAIN
# ============================================================

def main():

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    transcript_files = (
        find_transcript_files()
    )

    print(
        "=" * 88
    )

    print(
        "GT7 COMMUNITY ANALYZER"
    )

    print(
        "=" * 88
    )

    print(
        f"Transcript sources found : "
        f"{len(transcript_files)}"
    )

    if not transcript_files:

        raise RuntimeError(
            "No transcript JSON files were found. "
            "Expected files under data/community_transcripts/ "
            "or data/community_supadata_test/transcripts/."
        )

    observations = extract_observations(
        transcript_files
    )

    ranked = {}

    for category, items in (
        observations.items()
    ):

        ranked[
            category
        ] = rank_category(
            items
        )

    consensus = build_consensus(
        observations
    )

    takeaways = build_top_takeaways(
        ranked
    )

    output = {
        "sources": [
            {
                "channel":
                    source[
                        "data"
                    ].get(
                        "channel"
                    ),

                "video_id":
                    source[
                        "data"
                    ].get(
                        "video_id"
                    ),

                "title":
                    source[
                        "data"
                    ].get(
                        "title"
                    ),

                "content_type":
                    source[
                        "data"
                    ].get(
                        "content_type"
                    ),

                "word_count":
                    source[
                        "data"
                    ].get(
                        "word_count"
                    ),

                "source_file":
                    source[
                        "path"
                    ]
            }

            for source in transcript_files
        ],

        "categories":
            ranked,

        "consensus":
            consensus,

        "top_takeaways":
            takeaways
    }

    save_text = json.dumps(
        output,
        ensure_ascii=False,
        indent=2
    )

    OUTPUT_JSON.write_text(
        save_text,
        encoding="utf-8"
    )

    report = build_report(
        transcript_files,
        ranked,
        consensus,
        takeaways
    )

    OUTPUT_REPORT.write_text(
        report,
        encoding="utf-8"
    )

    print(
        report
    )

    print()

    print(
        f"JSON report      : "
        f"{OUTPUT_JSON}"
    )

    print(
        f"Text report      : "
        f"{OUTPUT_REPORT}"
    )


if __name__ == "__main__":

    main()