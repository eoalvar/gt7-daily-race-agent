import json
import re
from collections import Counter, defaultdict
from pathlib import Path


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

TRANSCRIPT_DIRS = [
    DATA_DIR
    / "community_transcripts",

    DATA_DIR
    / "community_supadata_test"
    / "transcripts",
]

OUTPUT_DIR = (
    DATA_DIR
    / "community_intelligence"
)

OUTPUT_JSON = (
    OUTPUT_DIR
    / "community_intelligence.json"
)

OUTPUT_REPORT = (
    OUTPUT_DIR
    / "community_intelligence.txt"
)


# ============================================================
# BASIC HELPERS
# ============================================================

def load_json(path, default=None):

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

    text = (
        text
        .replace("é", "e")
        .replace("á", "a")
        .replace("à", "a")
        .replace("ã", "a")
        .replace("â", "a")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ô", "o")
        .replace("õ", "o")
        .replace("ú", "u")
        .replace("ç", "c")
    )

    text = re.sub(
        r"[^a-z0-9.+%-]+",
        " ",
        text
    )

    return normalize_space(
        text
    )


def unique_preserve_order(values):

    output = []
    seen = set()

    for value in values:

        if value in seen:
            continue

        seen.add(
            value
        )

        output.append(
            value
        )

    return output


# ============================================================
# NUMBER PARSING
# ============================================================

NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


def parse_number_token(value):

    if value is None:
        return None

    value = (
        value.strip().lower()
    )

    if value.isdigit():

        return int(
            value
        )

    return NUMBER_WORDS.get(
        value
    )


# ============================================================
# CURRENT RACE GROUND TRUTH
# ============================================================

def build_ground_truth(
    snapshot,
    community_database
):

    race = snapshot.get(
        "race",
        {}
    )

    start_date = race.get(
        "start_date"
    )

    week_key = None

    if start_date:

        week_key = (
            start_date[:10]
        )

    community_week = {}

    if community_database:

        weeks = community_database.get(
            "weeks",
            {}
        )

        if (
            week_key
            and week_key in weeks
        ):

            community_week = weeks[
                week_key
            ]

        elif weeks:

            latest_key = sorted(
                weeks.keys()
            )[-1]

            community_week = weeks[
                latest_key
            ]

    description = race.get(
        "description",
        ""
    )

    race_class = (
        community_week.get(
            "race_class"
        )
    )

    if not race_class:

        match = re.search(
            r"\bGr\.?\s*(\d+)\b",
            description,
            re.IGNORECASE
        )

        if match:

            race_class = (
                f"Gr.{match.group(1)}"
            )

    track = community_week.get(
        "track"
    )

    direction = (
        community_week.get(
            "direction",
            "NORMAL"
        )
    )

    compounds = race.get(
        "compounds",
        []
    )

    compounds = [
        str(value).upper()
        for value in compounds
    ]

    return {
        "week":
            week_key,

        "description":
            description,

        "leaderboard_url":
            race.get(
                "leaderboard_url"
            ),

        "track":
            track,

        "race_class":
            race_class,

        "direction":
            direction,

        "fuel_multiplier":
            race.get(
                "fuel_multiplier"
            ),

        "tyre_multiplier":
            race.get(
                "tyre_multiplier"
            ),

        "compounds":
            compounds,

        "top5_used_cars":
            snapshot.get(
                "top5_used_cars",
                []
            ),

        "my_result":
            snapshot.get(
                "my_result"
            ),

        "car_comparison":
            snapshot.get(
                "car_comparison"
            ),
    }


# ============================================================
# TRANSCRIPT LOADING
# ============================================================

def find_transcript_files():

    results = {}

    for base in TRANSCRIPT_DIRS:

        if not base.exists():
            continue

        for path in base.rglob(
            "*.json"
        ):

            data = load_json(
                path
            )

            if not isinstance(
                data,
                dict
            ):
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

            if video_id in results:
                continue

            results[
                video_id
            ] = {
                "path":
                    str(path),

                "data":
                    data
            }

    return list(
        results.values()
    )


# ============================================================
# TITLE / TRACK VALIDATION
# ============================================================

def fuzzy_contains(
    target,
    text
):

    if not target:
        return None

    target_words = [
        word
        for word
        in normalize_text(
            target
        ).split()
        if len(word) >= 3
    ]

    haystack = set(
        normalize_text(
            text
        ).split()
    )

    if not target_words:
        return None

    matches = sum(
        1
        for word in target_words
        if word in haystack
    )

    ratio = (
        matches
        / len(target_words)
    )

    return ratio >= 0.60


def detect_class_mentions(text):

    matches = re.findall(
        r"\b(?:gr|group)\s*\.?\s*(\d+)\b",
        text,
        re.IGNORECASE
    )

    return {
        f"Gr.{value}"
        for value in matches
    }


def detect_direction(text):

    normalized = normalize_text(
        text
    )

    if "reverse" in normalized:

        return "REVERSE"

    return None


# ============================================================
# MULTIPLIER DETECTION
# ============================================================

def extract_multiplier_mentions(
    text,
    kind
):

    normalized = normalize_space(
        text
    ).lower()

    if kind == "fuel":

        prefixes = [
            "fuel",
            "fuel rate",
            "fuel consumption",
        ]

    else:

        prefixes = [
            "tyre",
            "tyres",
            "tire",
            "tires",
            "tyre wear",
            "tire wear",
        ]

    values = []

    number_pattern = (
        r"(?:"
        r"\d+"
        r"|one|two|three|four|five|six|seven|eight|nine|ten"
        r")"
    )

    for prefix in prefixes:

        patterns = [
            rf"{re.escape(prefix)}"
            rf".{{0,30}}?"
            rf"(?:x|times)\s*"
            rf"({number_pattern})",

            rf"{re.escape(prefix)}"
            rf".{{0,30}}?"
            rf"(?:at|is|of)\s+"
            rf"(?:times\s+)?"
            rf"({number_pattern})",
        ]

        for pattern in patterns:

            for match in re.findall(
                pattern,
                normalized,
                re.IGNORECASE
            ):

                number = (
                    parse_number_token(
                        match
                    )
                )

                if (
                    number is not None
                    and 1 <= number <= 20
                ):

                    values.append(
                        number
                    )

    return values


def dominant_value(values):

    if not values:
        return None

    counter = Counter(
        values
    )

    value, count = (
        counter.most_common(
            1
        )[0]
    )

    return {
        "value":
            value,

        "count":
            count,

        "mentions":
            values,
    }


# ============================================================
# COMPOUND DETECTION
# ============================================================

COMPOUND_NAMES = {
    "racing hard": "RH",
    "hard tire": "RH",
    "hard tyre": "RH",
    "hard tires": "RH",
    "hard tyres": "RH",

    "racing medium": "RM",
    "medium tire": "RM",
    "medium tyre": "RM",
    "medium tires": "RM",
    "medium tyres": "RM",

    "racing soft": "RS",
    "soft tire": "RS",
    "soft tyre": "RS",
    "soft tires": "RS",
    "soft tyres": "RS",
}


def detect_regulation_compounds(
    text
):

    normalized = normalize_text(
        text
    )

    regulation_cues = [
        "available",
        "mandatory",
        "required",
        "must use",
        "tire choice",
        "tyre choice",
        "tires available",
        "tyres available",
    ]

    results = []

    words = normalized.split()

    for index, word in enumerate(
        words
    ):

        start = max(
            0,
            index - 15
        )

        end = min(
            len(words),
            index + 16
        )

        window = " ".join(
            words[start:end]
        )

        if not any(
            cue in window
            for cue in regulation_cues
        ):
            continue

        for phrase, code in (
            COMPOUND_NAMES.items()
        ):

            if phrase in window:

                results.append(
                    code
                )

    return set(
        results
    )


# ============================================================
# VIDEO VALIDATION
# ============================================================

def validate_source(
    source,
    ground_truth
):

    data = source[
        "data"
    ]

    title = data.get(
        "title",
        ""
    )

    transcript = normalize_space(
        data.get(
            "transcript",
            ""
        )
    )

    evidence_text = (
        title
        + " "
        + transcript[
            :12000
        ]
    )

    reasons = []
    warnings = []
    matches = []

    rejected = False

    # --------------------------------------------------------
    # TRACK
    # --------------------------------------------------------

    track = ground_truth.get(
        "track"
    )

    track_match = fuzzy_contains(
        track,
        title
    )

    if track_match is True:

        matches.append(
            "TRACK_MATCH"
        )

    elif (
        track
        and track_match is False
    ):

        warnings.append(
            "TRACK_NOT_CONFIRMED_FROM_TITLE"
        )

    # --------------------------------------------------------
    # CLASS
    # --------------------------------------------------------

    expected_class = ground_truth.get(
        "race_class"
    )

    detected_classes = (
        detect_class_mentions(
            evidence_text
        )
    )

    if (
        expected_class
        and detected_classes
    ):

        if expected_class in detected_classes:

            matches.append(
                "CLASS_MATCH"
            )

        else:

            rejected = True

            reasons.append(
                (
                    "CLASS_CONFLICT: "
                    f"expected {expected_class}, "
                    f"detected "
                    f"{', '.join(sorted(detected_classes))}"
                )
            )

    # --------------------------------------------------------
    # DIRECTION
    # --------------------------------------------------------

    expected_direction = (
        ground_truth.get(
            "direction"
        )
        or "NORMAL"
    )

    detected_direction = (
        detect_direction(
            title
        )
    )

    if (
        expected_direction == "NORMAL"
        and detected_direction == "REVERSE"
    ):

        rejected = True

        reasons.append(
            "DIRECTION_CONFLICT: video says Reverse"
        )

    elif (
        expected_direction == "REVERSE"
        and detected_direction != "REVERSE"
    ):

        warnings.append(
            "REVERSE_NOT_CONFIRMED"
        )

    elif detected_direction:

        matches.append(
            "DIRECTION_MATCH"
        )

    # --------------------------------------------------------
    # FUEL
    # --------------------------------------------------------

    expected_fuel = ground_truth.get(
        "fuel_multiplier"
    )

    fuel = dominant_value(
        extract_multiplier_mentions(
            transcript,
            "fuel"
        )
    )

    if (
        expected_fuel
        and fuel
    ):

        if fuel[
            "value"
        ] == expected_fuel:

            matches.append(
                "FUEL_MATCH"
            )

        else:

            rejected = True

            reasons.append(
                (
                    "FUEL_CONFLICT: "
                    f"video x{fuel['value']} "
                    f"vs live x{expected_fuel}"
                )
            )

    # --------------------------------------------------------
    # TYRE WEAR
    # --------------------------------------------------------

    expected_tyre = ground_truth.get(
        "tyre_multiplier"
    )

    tyre = dominant_value(
        extract_multiplier_mentions(
            transcript,
            "tyre"
        )
    )

    if (
        expected_tyre
        and tyre
    ):

        if tyre[
            "value"
        ] == expected_tyre:

            matches.append(
                "TYRE_MATCH"
            )

        else:

            rejected = True

            reasons.append(
                (
                    "TYRE_CONFLICT: "
                    f"video x{tyre['value']} "
                    f"vs live x{expected_tyre}"
                )
            )

    # --------------------------------------------------------
    # COMPOUNDS
    # --------------------------------------------------------

    expected_compounds = set(
        ground_truth.get(
            "compounds",
            []
        )
    )

    detected_compounds = (
        detect_regulation_compounds(
            transcript
        )
    )

    if (
        expected_compounds
        and detected_compounds
    ):

        conflicts = (
            detected_compounds
            - expected_compounds
        )

        overlap = (
            detected_compounds
            & expected_compounds
        )

        if conflicts:

            rejected = True

            reasons.append(
                (
                    "COMPOUND_CONFLICT: "
                    f"video "
                    f"{'/'.join(sorted(detected_compounds))} "
                    f"vs live "
                    f"{'/'.join(sorted(expected_compounds))}"
                )
            )

        elif overlap:

            matches.append(
                "COMPOUND_MATCH"
            )

    # --------------------------------------------------------
    # FINAL STATUS
    # --------------------------------------------------------

    if rejected:

        status = "REJECTED"
        reliability = "STALE_OR_WRONG_RACE"

    else:

        strong_matches = sum(
            1
            for item in matches
            if item in {
                "FUEL_MATCH",
                "TYRE_MATCH",
                "COMPOUND_MATCH",
            }
        )

        if strong_matches >= 2:

            status = "CONFIRMED"
            reliability = "HIGH"

        elif matches:

            status = "PARTIAL"
            reliability = "MEDIUM"

        else:

            status = "UNVERIFIED"
            reliability = "LOW"

    return {
        "video_id":
            data.get(
                "video_id"
            ),

        "channel":
            data.get(
                "channel",
                "Unknown"
            ),

        "title":
            title,

        "content_type":
            data.get(
                "content_type",
                "OTHER"
            ),

        "status":
            status,

        "reliability":
            reliability,

        "matches":
            matches,

        "reasons":
            reasons,

        "warnings":
            warnings,

        "detected": {
            "fuel_multiplier":
                (
                    fuel[
                        "value"
                    ]
                    if fuel
                    else None
                ),

            "fuel_mentions":
                (
                    fuel[
                        "mentions"
                    ]
                    if fuel
                    else []
                ),

            "tyre_multiplier":
                (
                    tyre[
                        "value"
                    ]
                    if tyre
                    else None
                ),

            "tyre_mentions":
                (
                    tyre[
                        "mentions"
                    ]
                    if tyre
                    else []
                ),

            "compounds":
                sorted(
                    detected_compounds
                ),

            "classes":
                sorted(
                    detected_classes
                ),

            "direction":
                detected_direction,
        }
    }


# ============================================================
# TRANSCRIPT SEGMENTATION
# ============================================================

def transcript_segments(
    text,
    min_words=18,
    target_words=55,
    max_words=90
):

    text = normalize_space(
        text
    )

    if not text:
        return []

    # --------------------------------------------------------
    # First use punctuation where it exists.
    # --------------------------------------------------------

    punctuation_parts = re.split(
        r"(?<=[.!?])\s+",
        text
    )

    results = []

    for part in punctuation_parts:

        words = part.split()

        if len(words) <= max_words:

            if len(words) >= min_words:

                results.append(
                    part.strip()
                )

            continue

        # ----------------------------------------------------
        # Transcript has little/no punctuation.
        # Break it into overlapping semantic windows.
        # ----------------------------------------------------

        step = target_words

        for start in range(
            0,
            len(words),
            step
        ):

            chunk = words[
                start:
                start
                + max_words
            ]

            if len(chunk) < min_words:
                continue

            results.append(
                " ".join(
                    chunk
                )
            )

    return results


# ============================================================
# TECHNICAL CATEGORY DETECTION
# ============================================================

CATEGORY_PATTERNS = {

    "BRAKING": [
        r"\bbrak(?:e|es|ing)\b",
        r"\b\d+\s*(?:m|meter|meters|feet|ft)\b",
        r"\b\d+\s+board\b",
        r"\bbrake marker\b",
        r"\bbraking point\b",
    ],

    "GEARS": [
        r"\b(?:first|second|third|fourth|fifth|sixth)\s+gear\b",
        r"\b[1-6](?:st|nd|rd|th)\s+gear\b",
        r"\bdownshift",
        r"\bupshift",
        r"\bshort shift",
        r"\bshift",
    ],

    "RACING_LINE": [
        r"\bapex\b",
        r"\bturn in\b",
        r"\bturn-in\b",
        r"\binside line\b",
        r"\btight line\b",
        r"\bwide\b",
        r"\bposition the car\b",
        r"\byellow lines\b",
        r"\bentry\b",
        r"\bexit\b",
    ],

    "THROTTLE": [
        r"\bfull throttle\b",
        r"\bthrottle\b",
        r"\baccelerat",
        r"\bpower down\b",
        r"\bget on the power\b",
        r"\blift\b",
        r"\bcoast",
    ],

    "KERBS_TRACK_LIMITS": [
        r"\bkerb",
        r"\bcurb",
        r"\btrack limit",
        r"\bwhite line\b",
        r"\bbollard",
        r"\bpenalty\b",
    ],

    "RACECRAFT": [
        r"\bovertak",
        r"\bdefend",
        r"\bslipstream\b",
        r"\bdraft\b",
        r"\btraffic\b",
        r"\bbattle\b",
        r"\bdirty air\b",
    ],

    "TYRE_MANAGEMENT": [
        r"\btyre wear\b",
        r"\btire wear\b",
        r"\bfront tyre\b",
        r"\bfront tire\b",
        r"\btyres\b",
        r"\btires\b",
    ],

    "FUEL_MANAGEMENT": [
        r"\bfuel saving\b",
        r"\bsave fuel\b",
        r"\bfuel map\b",
        r"\bshort shift\b",
        r"\bfuel\b",
    ],

    "PIT_STRATEGY": [
        r"\bpit stop\b",
        r"\bpit lane\b",
        r"\bpit window\b",
        r"\bno stop\b",
        r"\bone stop\b",
        r"\bstint\b",
        r"\bmandatory change\b",
    ],

    "WARNINGS": [
        r"\bundersteer\b",
        r"\boversteer\b",
        r"\bpenalty\b",
        r"\bcareful\b",
        r"\bavoid\b",
        r"\blose time\b",
        r"\bmistake\b",
        r"\btoo wide\b",
        r"\btoo deep\b",
    ],
}


def category_hits(
    segment,
    category
):

    patterns = CATEGORY_PATTERNS[
        category
    ]

    normalized = (
        segment.lower()
    )

    return sum(
        1
        for pattern in patterns
        if re.search(
            pattern,
            normalized
        )
    )


# ============================================================
# REMOVE LOW-VALUE SPEECH
# ============================================================

LOW_VALUE_PATTERNS = [
    "welcome back to the channel",
    "leave a like",
    "subscribe",
    "thank you very much for watching",
    "catch you guys next time",
    "chapter markers",
    "do not want to miss this",
]


def low_value_segment(
    text
):

    normalized = normalize_text(
        text
    )

    return any(
        pattern in normalized
        for pattern in LOW_VALUE_PATTERNS
    )


# ============================================================
# BUILD OBSERVATIONS
# ============================================================

def build_observations(
    transcript_sources,
    validations
):

    validation_lookup = {
        item[
            "video_id"
        ]:
            item
        for item in validations
    }

    observations = defaultdict(
        list
    )

    for source in transcript_sources:

        data = source[
            "data"
        ]

        video_id = data.get(
            "video_id"
        )

        validation = (
            validation_lookup.get(
                video_id
            )
        )

        if not validation:

            continue

        # ----------------------------------------------------
        # Rejected videos cannot contribute recommendations.
        # ----------------------------------------------------

        if (
            validation[
                "status"
            ]
            == "REJECTED"
        ):

            continue

        segments = transcript_segments(
            data.get(
                "transcript",
                ""
            )
        )

        for segment in segments:

            if low_value_segment(
                segment
            ):
                continue

            category_scores = []

            for category in CATEGORY_PATTERNS:

                hits = category_hits(
                    segment,
                    category
                )

                if hits > 0:

                    category_scores.append(
                        (
                            category,
                            hits
                        )
                    )

            category_scores.sort(
                key=lambda item:
                    item[1],
                reverse=True
            )

            for category, hits in (
                category_scores[:2]
            ):

                reliability_bonus = {
                    "HIGH": 6,
                    "MEDIUM": 3,
                    "LOW": 0,
                }.get(
                    validation[
                        "reliability"
                    ],
                    0
                )

                content_bonus = {
                    "LAP_GUIDE": 4,
                    "STRATEGY": 4,
                    "QUALIFYING": 3,
                    "RACE": 2,
                    "LIVESTREAM": 1,
                }.get(
                    data.get(
                        "content_type"
                    ),
                    0
                )

                observations[
                    category
                ].append({
                    "video_id":
                        video_id,

                    "channel":
                        data.get(
                            "channel",
                            "Unknown"
                        ),

                    "title":
                        data.get(
                            "title"
                    ),

                    "content_type":
                        data.get(
                            "content_type"
                    ),

                    "validation":
                        validation[
                            "status"
                        ],

                    "reliability":
                        validation[
                            "reliability"
                        ],

                    "text":
                        segment,

                    "score":
                        (
                            hits * 10
                            + reliability_bonus
                            + content_bonus
                        ),
                })

    return observations


# ============================================================
# DEDUPLICATION
# ============================================================

def text_tokens(text):

    ignore = {
        "the",
        "and",
        "you",
        "this",
        "that",
        "with",
        "for",
        "from",
        "into",
        "then",
        "just",
        "your",
        "when",
        "we",
        "our",
        "car",
        "going",
    }

    return {
        word
        for word
        in normalize_text(
            text
        ).split()
        if (
            len(word) >= 3
            and word not in ignore
        )
    }


def similarity(a, b):

    set_a = text_tokens(
        a
    )

    set_b = text_tokens(
        b
    )

    if (
        not set_a
        or not set_b
    ):

        return 0.0

    return (
        len(
            set_a & set_b
        )
        / len(
            set_a | set_b
        )
    )


def rank_and_dedupe(
    items,
    limit=8
):

    items = sorted(
        items,
        key=lambda item:
            item[
                "score"
            ],
        reverse=True
    )

    output = []

    for item in items:

        if any(
            (
                item[
                    "channel"
                ]
                == existing[
                    "channel"
                ]
                and similarity(
                    item[
                        "text"
                    ],
                    existing[
                        "text"
                    ]
                )
                >= 0.45
            )
            for existing in output
        ):

            continue

        output.append(
            item
        )

        if len(output) >= limit:
            break

    return output


# ============================================================
# TECHNICAL CONCEPT TAGS
# ============================================================

CONCEPT_PATTERNS = {
    "RELEASE_BRAKE_TO_ROTATE": [
        r"release.*brake",
        r"let go.*brake",
        r"brake.*understeer",
    ],

    "AVOID_LONG_TRAIL_BRAKING": [
        r"trail braking.*understeer",
        r"stay on the brakes.*understeer",
        r"brakes for too long",
    ],

    "TIGHT_LINE": [
        r"tight line",
        r"narrowest possible",
        r"stay.*inside",
        r"hugging the inside",
    ],

    "EARLY_POWER": [
        r"power.*as soon as possible",
        r"accelerate.*early",
        r"get on the power",
    ],

    "TRACK_LIMIT_RISK": [
        r"track limits",
        r"half second penalty",
        r"white line",
        r"bollard",
    ],

    "USE_KERB_FOR_ROTATION": [
        r"curb.*rotate",
        r"kerb.*rotate",
        r"curb.*help",
    ],

    "FULL_THROTTLE_EXIT": [
        r"full throttle",
        r"carry.*speed.*straight",
    ],

    "NO_STOP": [
        r"no stop",
        r"no-stop",
    ],
}


def concept_tags(text):

    normalized = (
        text.lower()
    )

    tags = []

    for tag, patterns in (
        CONCEPT_PATTERNS.items()
    ):

        if any(
            re.search(
                pattern,
                normalized
            )
            for pattern in patterns
        ):

            tags.append(
                tag
            )

    return tags


# ============================================================
# CONSENSUS ENGINE
# ============================================================

def build_consensus(
    observations
):

    tag_sources = defaultdict(
        set
    )

    tag_examples = defaultdict(
        list
    )

    for category, items in (
        observations.items()
    ):

        for item in items:

            tags = concept_tags(
                item[
                    "text"
                ]
            )

            for tag in tags:

                tag_sources[
                    tag
                ].add(
                    item[
                        "channel"
                    ]
                )

                tag_examples[
                    tag
                ].append({
                    "category":
                        category,

                    "channel":
                        item[
                            "channel"
                        ],

                    "text":
                        item[
                            "text"
                        ],
                })

    results = []

    for tag, sources in (
        tag_sources.items()
    ):

        if len(sources) < 2:
            continue

        results.append({
            "concept":
                tag,

            "source_count":
                len(
                    sources
                ),

            "sources":
                sorted(
                    sources
                ),

            "example":
                tag_examples[
                    tag
                ][0][
                    "text"
                ],
        })

    results.sort(
        key=lambda item:
            item[
                "source_count"
            ],
        reverse=True
    )

    return results


# ============================================================
# COMMUNITY CAR MENTIONS
# ============================================================

KNOWN_CAR_TERMS = {
    "GT by Citroën Gr.4": [
        "gt by citroen",
        "citroen gr 4",
        "citroen gr4",
    ],

    "Genesis G70 GR4": [
        "genesis g70",
        "g70 gr4",
        "g70 gr 4",
    ],

    "Nissan GT-R Gr.4": [
        "nissan gtr",
        "nissan gt r",
        "gt-r gr.4",
        "gtr gr4",
    ],

    "Nissan Silvia Gr.4": [
        "nissan silvia",
        "silvia gr4",
        "silvia gr 4",
    ],

    "Suzuki Swift Sport KATANA Edition Gr.4": [
        "suzuki swift",
        "swift sport",
    ],

    "Honda NSX Gr.4": [
        "honda nsx",
        "nsx gr4",
        "nsx gr 4",
    ],
}


def community_car_mentions(
    transcript_sources,
    validations
):

    validation_lookup = {
        item[
            "video_id"
        ]:
            item
        for item in validations
    }

    counts = Counter()

    channels = defaultdict(
        set
    )

    for source in transcript_sources:

        data = source[
            "data"
        ]

        validation = (
            validation_lookup.get(
                data.get(
                    "video_id"
                )
            )
        )

        if (
            not validation
            or validation[
                "status"
            ]
            == "REJECTED"
        ):

            continue

        text = normalize_text(
            data.get(
                "transcript",
                ""
            )
        )

        for car, terms in (
            KNOWN_CAR_TERMS.items()
        ):

            hits = sum(
                text.count(
                    normalize_text(
                        term
                    )
                )
                for term in terms
            )

            if hits:

                counts[
                    car
                ] += hits

                channels[
                    car
                ].add(
                    data.get(
                        "channel",
                        "Unknown"
                    )
                )

    results = []

    for car, count in (
        counts.most_common()
    ):

        results.append({
            "car":
                car,

            "mentions":
                count,

            "sources":
                sorted(
                    channels[
                        car
                    ]
                ),
        })

    return results


# ============================================================
# COMMUNITY VS LIVE META
# ============================================================

def build_meta_comparison(
    ground_truth,
    car_mentions
):

    live = []

    for item in ground_truth.get(
        "top5_used_cars",
        []
    ):

        live.append({
            "car":
                item.get(
                    "car"
                ),

            "drivers":
                item.get(
                    "count"
                ),

            "percentage":
                item.get(
                    "percentage"
                ),
        })

    return {
        "community_mentions":
            car_mentions,

        "live_top5":
            live,
    }


# ============================================================
# TOP TAKEAWAYS
# ============================================================

def build_takeaways(
    ranked,
    consensus
):

    results = []

    priority = [
        "BRAKING",
        "RACING_LINE",
        "THROTTLE",
        "GEARS",
        "KERBS_TRACK_LIMITS",
        "TYRE_MANAGEMENT",
        "PIT_STRATEGY",
        "WARNINGS",
    ]

    for item in consensus:

        results.append({
            "type":
                "CONSENSUS",

            "category":
                "MULTI_SOURCE",

            "source":
                ", ".join(
                    item[
                        "sources"
                    ]
                ),

            "text":
                item[
                    "example"
                ],
        })

        if len(results) >= 3:
            break

    for category in priority:

        for item in ranked.get(
            category,
            []
        ):

            if any(
                similarity(
                    item[
                        "text"
                    ],
                    existing[
                        "text"
                    ]
                )
                > 0.40
                for existing in results
            ):

                continue

            results.append({
                "type":
                    "SOURCE",

                "category":
                    category,

                "source":
                    item[
                        "channel"
                    ],

                "text":
                    item[
                        "text"
                    ],
            })

            if len(results) >= 10:

                return results

    return results


# ============================================================
# REPORT HELPERS
# ============================================================

def format_compounds(values):

    if not values:
        return "Not detected"

    return ", ".join(
        values
    )


def compact_text(
    text,
    max_chars=420
):

    text = normalize_space(
        text
    )

    if len(text) <= max_chars:
        return text

    shortened = text[
        :max_chars
    ]

    cut = shortened.rfind(
        " "
    )

    if cut > 0:

        shortened = shortened[
            :cut
        ]

    return (
        shortened
        + "..."
    )


# ============================================================
# BUILD REPORT
# ============================================================

def build_report(
    ground_truth,
    validations,
    ranked,
    consensus,
    meta_comparison,
    takeaways
):

    lines = []

    lines.append(
        "GT7 COMMUNITY INTELLIGENCE V2"
    )

    lines.append(
        "=" * 92
    )

    lines.append(
        f"Race week        : "
        f"{ground_truth.get('week')}"
    )

    lines.append(
        f"Track            : "
        f"{ground_truth.get('track') or 'Unknown'}"
    )

    lines.append(
        f"Class            : "
        f"{ground_truth.get('race_class') or 'Unknown'}"
    )

    lines.append(
        f"Direction        : "
        f"{ground_truth.get('direction') or 'Unknown'}"
    )

    lines.append(
        f"Live fuel        : "
        f"x{ground_truth.get('fuel_multiplier')}"
    )

    lines.append(
        f"Live tyre wear   : "
        f"x{ground_truth.get('tyre_multiplier')}"
    )

    lines.append(
        f"Live compounds   : "
        f"{format_compounds(ground_truth.get('compounds'))}"
    )

    # ========================================================
    # SOURCE VALIDATION
    # ========================================================

    lines.append("")
    lines.append(
        "SOURCE VALIDATION"
    )

    lines.append(
        "-" * 92
    )

    for item in validations:

        lines.append(
            f"{item['channel']} | "
            f"{item['status']} | "
            f"{item['reliability']}"
        )

        lines.append(
            f"  {item['title']}"
        )

        detected = item[
            "detected"
        ]

        details = []

        if (
            detected[
                "fuel_multiplier"
            ]
            is not None
        ):

            details.append(
                f"Fuel x"
                f"{detected['fuel_multiplier']}"
            )

        if (
            detected[
                "tyre_multiplier"
            ]
            is not None
        ):

            details.append(
                f"Tyres x"
                f"{detected['tyre_multiplier']}"
            )

        if detected[
            "compounds"
        ]:

            details.append(
                "Compounds "
                + "/".join(
                    detected[
                        "compounds"
                    ]
                )
            )

        if details:

            lines.append(
                "  Detected: "
                + " | ".join(
                    details
                )
            )

        if item[
            "matches"
        ]:

            lines.append(
                "  Matches : "
                + ", ".join(
                    item[
                        "matches"
                    ]
                )
            )

        for reason in item[
            "reasons"
        ]:

            lines.append(
                f"  REJECT  : "
                f"{reason}"
            )

        for warning in item[
            "warnings"
        ]:

            lines.append(
                f"  Note    : "
                f"{warning}"
            )

    accepted = sum(
        1
        for item in validations
        if item[
            "status"
        ]
        != "REJECTED"
    )

    rejected = sum(
        1
        for item in validations
        if item[
            "status"
        ]
        == "REJECTED"
    )

    lines.append("")

    lines.append(
        f"Usable sources   : "
        f"{accepted}"
    )

    lines.append(
        f"Rejected sources : "
        f"{rejected}"
    )

    # ========================================================
    # TECHNICAL SECTIONS
    # ========================================================

    section_titles = {
        "BRAKING":
            "BRAKING POINTS",

        "GEARS":
            "GEARS / SHIFTING",

        "RACING_LINE":
            "RACING LINE",

        "THROTTLE":
            "THROTTLE / ACCELERATION",

        "KERBS_TRACK_LIMITS":
            "KERBS / TRACK LIMITS",

        "TYRE_MANAGEMENT":
            "TYRE MANAGEMENT",

        "FUEL_MANAGEMENT":
            "FUEL MANAGEMENT",

        "PIT_STRATEGY":
            "PIT / RACE STRATEGY",

        "RACECRAFT":
            "RACECRAFT",

        "WARNINGS":
            "MISTAKES / WARNINGS",
    }

    for category, title in (
        section_titles.items()
    ):

        lines.append("")
        lines.append(
            title
        )

        lines.append(
            "-" * 92
        )

        items = ranked.get(
            category,
            []
        )

        if not items:

            lines.append(
                "No strong validated transcript evidence found."
            )

            continue

        for item in items:

            lines.append(
                f"- [{item['channel']} | "
                f"{item['reliability']}] "
                f"{compact_text(item['text'])}"
            )

    # ========================================================
    # CONSENSUS
    # ========================================================

    lines.append("")
    lines.append(
        "CONSENSUS BETWEEN VALIDATED SOURCES"
    )

    lines.append(
        "-" * 92
    )

    if not consensus:

        lines.append(
            "No strong multi-source technical consensus detected yet."
        )

    else:

        for item in consensus:

            lines.append(
                f"- {item['concept']}"
            )

            lines.append(
                f"  Sources: "
                f"{', '.join(item['sources'])}"
            )

            lines.append(
                f"  Example: "
                f"{compact_text(item['example'])}"
            )

    # ========================================================
    # COMMUNITY VS LIVE META
    # ========================================================

    lines.append("")
    lines.append(
        "COMMUNITY VS LIVE LEADERBOARD META"
    )

    lines.append(
        "-" * 92
    )

    community_mentions = (
        meta_comparison[
            "community_mentions"
        ]
    )

    if community_mentions:

        lines.append(
            "Community car mentions:"
        )

        for item in (
            community_mentions[
                :5
            ]
        ):

            lines.append(
                f"- {item['car']} | "
                f"{item['mentions']} mentions | "
                f"{', '.join(item['sources'])}"
            )

    else:

        lines.append(
            "Community car mentions: none detected."
        )

    live_top5 = (
        meta_comparison[
            "live_top5"
        ]
    )

    lines.append("")

    lines.append(
        "Live leaderboard Top 1000:"
    )

    if live_top5:

        for index, item in enumerate(
            live_top5,
            start=1
        ):

            percentage = (
                item.get(
                    "percentage"
                )
            )

            if isinstance(
                percentage,
                (int, float)
            ):

                percentage_text = (
                    f"{percentage:.1f}%"
                )

            else:

                percentage_text = "N/A"

            lines.append(
                f"{index}. "
                f"{item.get('car')} | "
                f"{item.get('drivers')} drivers | "
                f"{percentage_text}"
            )

    else:

        lines.append(
            "No live meta data available."
        )

    # ========================================================
    # TAKEAWAYS
    # ========================================================

    lines.append("")
    lines.append(
        "TOP PRACTICAL TAKEAWAYS"
    )

    lines.append(
        "-" * 92
    )

    if not takeaways:

        lines.append(
            "No validated takeaways available."
        )

    else:

        for index, item in enumerate(
            takeaways,
            start=1
        ):

            lines.append(
                f"{index}. "
                f"[{item['category']}] "
                f"{compact_text(item['text'])}"
            )

            lines.append(
                f"   Source: "
                f"{item['source']}"
            )

    # ========================================================
    # NOTES
    # ========================================================

    lines.append("")
    lines.append(
        "ANALYSIS POLICY"
    )

    lines.append(
        "-" * 92
    )

    lines.append(
        "Live race configuration from latest_snapshot.json is treated "
        "as ground truth."
    )

    lines.append(
        "A community source that materially contradicts the live race "
        "configuration is excluded from recommendations."
    )

    lines.append(
        "Unverified sources may contribute driving technique only when "
        "they do not contradict known race facts."
    )

    lines.append(
        "Community car opinions are shown separately from actual "
        "leaderboard usage."
    )

    lines.append("")
    lines.append(
        "=" * 92
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

    snapshot = load_json(
        LATEST_SNAPSHOT_FILE
    )

    if not snapshot:

        raise RuntimeError(
            "data/latest_snapshot.json not found or invalid."
        )

    community_database = load_json(
        COMMUNITY_SOURCES_FILE,
        {}
    )

    ground_truth = build_ground_truth(
        snapshot,
        community_database
    )

    transcript_sources = (
        find_transcript_files()
    )

    if not transcript_sources:

        raise RuntimeError(
            "No transcript files were found."
        )

    print(
        "=" * 92
    )

    print(
        "GT7 COMMUNITY ANALYZER V2"
    )

    print(
        "=" * 92
    )

    print(
        f"Transcript sources found : "
        f"{len(transcript_sources)}"
    )

    print(
        f"Ground truth fuel        : "
        f"x{ground_truth.get('fuel_multiplier')}"
    )

    print(
        f"Ground truth tyres       : "
        f"x{ground_truth.get('tyre_multiplier')}"
    )

    print(
        f"Ground truth compounds   : "
        f"{format_compounds(ground_truth.get('compounds'))}"
    )

    # ========================================================
    # VALIDATE
    # ========================================================

    validations = []

    for source in transcript_sources:

        validation = validate_source(
            source,
            ground_truth
        )

        validations.append(
            validation
        )

    # ========================================================
    # OBSERVATIONS
    # ========================================================

    observations = build_observations(
        transcript_sources,
        validations
    )

    ranked = {}

    for category in CATEGORY_PATTERNS:

        ranked[
            category
        ] = rank_and_dedupe(
            observations.get(
                category,
                []
            )
        )

    # ========================================================
    # CONSENSUS
    # ========================================================

    consensus = build_consensus(
        observations
    )

    # ========================================================
    # META
    # ========================================================

    car_mentions = (
        community_car_mentions(
            transcript_sources,
            validations
        )
    )

    meta_comparison = (
        build_meta_comparison(
            ground_truth,
            car_mentions
        )
    )

    # ========================================================
    # TAKEAWAYS
    # ========================================================

    takeaways = build_takeaways(
        ranked,
        consensus
    )

    # ========================================================
    # OUTPUT STRUCTURE
    # ========================================================

    output = {
        "version":
            2,

        "ground_truth":
            ground_truth,

        "source_validation":
            validations,

        "categories":
            ranked,

        "consensus":
            consensus,

        "meta_comparison":
            meta_comparison,

        "top_takeaways":
            takeaways,
    }

    OUTPUT_JSON.write_text(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    report = build_report(
        ground_truth,
        validations,
        ranked,
        consensus,
        meta_comparison,
        takeaways
    )

    OUTPUT_REPORT.write_text(
        report,
        encoding="utf-8"
    )

    print()

    print(
        report
    )

    print("")

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