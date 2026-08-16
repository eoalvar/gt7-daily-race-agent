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


def compact_text(
    text,
    max_chars=330
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
        value
        .strip()
        .lower()
    )

    if value.isdigit():

        return int(
            value
        )

    return NUMBER_WORDS.get(
        value
    )


# ============================================================
# GROUND TRUTH
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

    week_key = (
        start_date[:10]
        if start_date
        else None
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

    compounds = [
        str(value).upper()
        for value in race.get(
            "compounds",
            []
        )
    ]

    return {
        "week":
            week_key,

        "description":
            description,

        "track":
            community_week.get(
                "track"
            ),

        "race_class":
            race_class,

        "direction":
            community_week.get(
                "direction",
                "NORMAL"
            ),

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
                    data,
            }

    return list(
        results.values()
    )


# ============================================================
# TRACK / CLASS / DIRECTION VALIDATION
# ============================================================

def fuzzy_contains(
    target,
    text
):

    if not target:
        return None

    target_words = [
        word
        for word in normalize_text(
            target
        ).split()
        if len(word) >= 3
    ]

    if not target_words:
        return None

    haystack = set(
        normalize_text(
            text
        ).split()
    )

    matched = sum(
        1
        for word in target_words
        if word in haystack
    )

    ratio = (
        matched
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
# MULTIPLIER DETECTION V3
# ============================================================

def extract_multiplier_mentions(
    text,
    kind
):

    normalized = normalize_space(
        text
    ).lower()

    number_pattern = (
        r"(?:"
        r"\d+"
        r"|one|two|three|four|five|six|seven|eight|nine|ten"
        r")"
    )

    if kind == "fuel":

        subject_pattern = (
            r"(?:"
            r"fuel"
            r"|fuel rate"
            r"|fuel consumption"
            r"|fuel multiplier"
            r")"
        )

    else:

        subject_pattern = (
            r"(?:"
            r"tyre wear"
            r"|tire wear"
            r"|tyres"
            r"|tires"
            r"|tyre"
            r"|tire"
            r")"
        )

    patterns = [
        (
            rf"{subject_pattern}"
            rf".{{0,45}}?"
            rf"(?:x|times|multiplier(?:\s+of)?)"
            rf"\s*({number_pattern})"
        ),

        (
            rf"{subject_pattern}"
            rf".{{0,45}}?"
            rf"(?:at|is|of)"
            rf"\s+(?:a\s+)?"
            rf"({number_pattern})"
            rf"\s*(?:times|x)?"
        ),

        (
            rf"({number_pattern})"
            rf"\s*(?:x|times)"
            rf".{{0,35}}?"
            rf"{subject_pattern}"
        ),
    ]

    values = []

    for pattern in patterns:

        matches = re.findall(
            pattern,
            normalized,
            re.IGNORECASE
        )

        for match in matches:

            if isinstance(
                match,
                tuple
            ):

                tokens = [
                    item
                    for item in match
                    if item
                ]

                if not tokens:
                    continue

                match = tokens[
                    0
                ]

            number = parse_number_token(
                match
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
# COMPOUND DETECTION V3
# ============================================================

COMPOUND_PATTERNS = {
    "RH": [
        r"\bracing hard\b",
        r"\bhard tires?\b",
        r"\bhard tyres?\b",
    ],

    "RM": [
        r"\bracing medium\b",
        r"\bmedium tires?\b",
        r"\bmedium tyres?\b",
    ],

    "RS": [
        r"\bracing soft\b",
        r"\bsoft tires?\b",
        r"\bsoft tyres?\b",
    ],

    "IM": [
        r"\bintermediate tires?\b",
        r"\bintermediate tyres?\b",
    ],

    "W": [
        r"\bwet tires?\b",
        r"\bwet tyres?\b",
    ],
}


def detect_regulation_compounds(
    text
):

    normalized = normalize_space(
        text
    ).lower()

    cue_patterns = [
        r"available",
        r"mandatory",
        r"required",
        r"must use",
        r"tire type",
        r"tyre type",
        r"tires are",
        r"tyres are",
        r"tire choice",
        r"tyre choice",
    ]

    compounds = set()

    for code, patterns in (
        COMPOUND_PATTERNS.items()
    ):

        for pattern in patterns:

            for match in re.finditer(
                pattern,
                normalized,
                re.IGNORECASE
            ):

                start = max(
                    0,
                    match.start()
                    - 120
                )

                end = min(
                    len(normalized),
                    match.end()
                    + 120
                )

                window = normalized[
                    start:end
                ]

                if any(
                    re.search(
                        cue,
                        window,
                        re.IGNORECASE
                    )
                    for cue in cue_patterns
                ):

                    compounds.add(
                        code
                    )

    return compounds


# ============================================================
# SOURCE VALIDATION
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
            :15000
        ]
    )

    matches = []
    reasons = []
    warnings = []

    rejected = False

    # --------------------------------------------------------
    # TRACK
    # --------------------------------------------------------

    track_match = fuzzy_contains(
        ground_truth.get(
            "track"
        ),
        title
    )

    if track_match is True:

        matches.append(
            "TRACK_MATCH"
        )

    # --------------------------------------------------------
    # CLASS
    # --------------------------------------------------------

    expected_class = (
        ground_truth.get(
            "race_class"
        )
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
            "DIRECTION_CONFLICT"
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
    # TYRES
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

        technical_matches = sum(
            1
            for item in matches
            if item in {
                "FUEL_MATCH",
                "TYRE_MATCH",
                "COMPOUND_MATCH",
            }
        )

        if technical_matches >= 2:

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
        },
    }


# ============================================================
# TRANSCRIPT SEGMENTATION
# ============================================================

def transcript_segments(
    text,
    min_words=12,
    target_words=38,
    max_words=65
):

    text = normalize_space(
        text
    )

    if not text:
        return []

    punctuation_parts = re.split(
        r"(?<=[.!?])\s+",
        text
    )

    output = []

    for part in punctuation_parts:

        words = part.split()

        if len(words) < min_words:
            continue

        if len(words) <= max_words:

            output.append(
                part.strip()
            )

            continue

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

            output.append(
                " ".join(
                    chunk
                )
            )

    return output


# ============================================================
# LOW VALUE FILTER
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


def low_value_segment(text):

    normalized = normalize_text(
        text
    )

    return any(
        pattern in normalized
        for pattern in LOW_VALUE_PATTERNS
    )


# ============================================================
# TECHNICAL PATTERNS
# ============================================================

CATEGORY_PATTERNS = {

    "BRAKING": [
        r"\bbrak(?:e|es|ing)\b",
        r"\b\d+\s*(?:m|meters?|feet|ft)\b",
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
    ],

    "RACING_LINE": [
        r"\bapex\b",
        r"\bturn in\b",
        r"\binside line\b",
        r"\btight line\b",
        r"\bnarrowest\b",
        r"\bposition the car\b",
        r"\byellow lines\b",
        r"\bentry\b",
        r"\bexit\b",
    ],

    "THROTTLE": [
        r"\bfull throttle\b",
        r"\bthrottle\b",
        r"\baccelerat",
        r"\bget on the power\b",
        r"\bpower down\b",
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

    "TYRE_MANAGEMENT": [
        r"\btyre wear\b",
        r"\btire wear\b",
        r"\bfront tyre\b",
        r"\bfront tire\b",
    ],

    "FUEL_MANAGEMENT": [
        r"\bfuel saving\b",
        r"\bsave fuel\b",
        r"\bfuel map\b",
        r"\bshort shift\b",
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
    text,
    category
):

    normalized = (
        text.lower()
    )

    return sum(
        1
        for pattern in (
            CATEGORY_PATTERNS[
                category
            ]
        )
        if re.search(
            pattern,
            normalized
        )
    )


# ============================================================
# OBSERVATIONS
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

        validation = (
            validation_lookup.get(
                data.get(
                    "video_id"
                )
            )
        )

        if not validation:
            continue

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

        for segment_index, segment in enumerate(
            segments
        ):

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

            for category, hits in (
                category_scores[
                    :2
                ]
            ):

                observations[
                    category
                ].append({
                    "video_id":
                        data.get(
                            "video_id"
                        ),

                    "channel":
                        data.get(
                            "channel",
                            "Unknown"
                        ),

                    "content_type":
                        data.get(
                            "content_type",
                            "OTHER"
                        ),

                    "segment_index":
                        segment_index,

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
                        ),
                })

    return observations


# ============================================================
# SIMILARITY
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
        for word in normalize_text(
            text
        ).split()
        if (
            len(word) >= 3
            and word not in ignore
        )
    }


def similarity(a, b):

    a_tokens = text_tokens(
        a
    )

    b_tokens = text_tokens(
        b
    )

    if (
        not a_tokens
        or not b_tokens
    ):

        return 0.0

    return (
        len(
            a_tokens & b_tokens
        )
        / len(
            a_tokens | b_tokens
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

        duplicate = False

        for existing in output:

            if (
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
                >= 0.42
            ):

                duplicate = True
                break

        if duplicate:
            continue

        output.append(
            item
        )

        if len(output) >= limit:
            break

    return output


# ============================================================
# DRIVING REFERENCE EXTRACTION
# ============================================================

def extract_brake_reference(text):

    normalized = (
        text.lower()
    )

    patterns = [
        r"\baround\s+(\d+)\s*m\b",
        r"\bat\s+(\d+)\s*m\b",
        r"\b(\d+)\s*m\b",
        r"\b(\d+)\s*(?:feet|ft)\b",
        r"\b(\d+)\s+board\b",
        r"\b(\d+)\s+sign\b",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            normalized
        )

        if match:

            return match.group(
                0
            )

    reference_phrases = [
        "after we pass under this bridge",
        "under the bridge",
        "dark mark in the sand",
        "arrow sign",
        "yellow lines",
        "out of the tunnel",
    ]

    for phrase in reference_phrases:

        if phrase in normalized:

            return phrase

    return None


def extract_gear(text):

    normalized = (
        text.lower()
    )

    patterns = [
        (
            r"\b(first|second|third|fourth|fifth|sixth)\s+gear\b"
        ),
        (
            r"\b([1-6])(?:st|nd|rd|th)\s+gear\b"
        ),
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            normalized
        )

        if match:

            return match.group(
                0
            )

    return None


def extract_technique(text):

    normalized = (
        text.lower()
    )

    techniques = []

    checks = [
        (
            "release brake to help rotation",
            [
                "let go of the brakes",
                "release the brakes",
                "release brake",
            ]
        ),

        (
            "avoid prolonged trail braking",
            [
                "trail braking",
                "brakes for too long",
                "stay on the brakes for too long",
            ]
        ),

        (
            "keep a tight/narrow line",
            [
                "tight line",
                "narrowest possible",
                "hugging the inside",
            ]
        ),

        (
            "use early throttle",
            [
                "power as soon as possible",
                "accelerate as soon as possible",
                "get on the power",
            ]
        ),

        (
            "use kerb to aid rotation",
            [
                "curbs on the right",
                "curb",
                "kerb",
            ]
        ),

        (
            "coast to help rotation",
            [
                "coast",
                "coasting",
            ]
        ),
    ]

    for label, phrases in checks:

        if any(
            phrase in normalized
            for phrase in phrases
        ):

            techniques.append(
                label
            )

    return techniques


# ============================================================
# CORNER-BY-CORNER APPROXIMATION
# ============================================================

def build_corner_guide(
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

    guide = []

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

        segments = transcript_segments(
            data.get(
                "transcript",
                ""
            )
        )

        for index, segment in enumerate(
            segments
        ):

            braking_hits = (
                category_hits(
                    segment,
                    "BRAKING"
                )
            )

            line_hits = (
                category_hits(
                    segment,
                    "RACING_LINE"
                )
            )

            throttle_hits = (
                category_hits(
                    segment,
                    "THROTTLE"
                )
            )

            gear_hits = (
                category_hits(
                    segment,
                    "GEARS"
                )
            )

            total_hits = (
                braking_hits
                + line_hits
                + throttle_hits
                + gear_hits
            )

            if total_hits < 2:
                continue

            previous_text = (
                segments[
                    index - 1
                ]
                if index > 0
                else ""
            )

            next_text = (
                segments[
                    index + 1
                ]
                if index
                + 1
                < len(
                    segments
                )
                else ""
            )

            context = normalize_space(
                previous_text
                + " "
                + segment
                + " "
                + next_text
            )

            guide.append({
                "channel":
                    data.get(
                        "channel",
                        "Unknown"
                    ),

                "reliability":
                    validation[
                        "reliability"
                    ],

                "segment_index":
                    index,

                "brake_reference":
                    extract_brake_reference(
                        segment
                    )
                    or extract_brake_reference(
                        context
                    ),

                "gear":
                    extract_gear(
                        segment
                    )
                    or extract_gear(
                        context
                    ),

                "techniques":
                    extract_technique(
                        context
                    ),

                "summary":
                    compact_text(
                        segment,
                        300
                    ),

                "score":
                    total_hits,
            })

    guide.sort(
        key=lambda item:
            (
                item[
                    "channel"
                ],
                item[
                    "segment_index"
                ]
            )
    )

    return guide


# ============================================================
# CONSENSUS
# ============================================================

CONCEPT_PATTERNS = {

    "TIGHT_LINE": [
        r"tight line",
        r"narrowest possible",
        r"hugging the inside",
    ],

    "EARLY_POWER": [
        r"power as soon as possible",
        r"get on the power",
        r"accelerate",
    ],

    "RELEASE_BRAKE_FOR_ROTATION": [
        r"release.*brake",
        r"let go.*brake",
    ],

    "AVOID_LONG_TRAIL_BRAKING": [
        r"trail braking",
        r"brakes for too long",
    ],

    "TRACK_LIMIT_RISK": [
        r"track limits",
        r"white line",
        r"penalty",
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


def build_consensus(
    observations
):

    tag_sources = defaultdict(
        set
    )

    tag_examples = defaultdict(
        list
    )

    for items in observations.values():

        for item in items:

            for tag in concept_tags(
                item[
                    "text"
                ]
            ):

                tag_sources[
                    tag
                ].add(
                    item[
                        "channel"
                    ]
                )

                tag_examples[
                    tag
                ].append(
                    item[
                        "text"
                    ]
                )

    results = []

    for tag, sources in (
        tag_sources.items()
    ):

        if len(sources) < 2:
            continue

        results.append({
            "concept":
                tag,

            "sources":
                sorted(
                    sources
                ),

            "source_count":
                len(
                    sources
                ),

            "example":
                compact_text(
                    tag_examples[
                        tag
                    ][0]
                ),
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
# CAR MENTIONS
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

            if hits > 0:

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

    return [
        {
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
        }

        for car, count in (
            counts.most_common()
        )
    ]


# ============================================================
# META COMPARISON
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
# TAKEAWAYS
# ============================================================

def build_takeaways(
    ranked,
    consensus
):

    results = []

    for item in consensus:

        results.append({
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

    priority = [
        "BRAKING",
        "RACING_LINE",
        "THROTTLE",
        "GEARS",
        "KERBS_TRACK_LIMITS",
        "WARNINGS",
    ]

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
                >= 0.40
                for existing in results
            ):

                continue

            results.append({
                "category":
                    category,

                "source":
                    item[
                        "channel"
                    ],

                "text":
                    compact_text(
                        item[
                            "text"
                        ]
                    ),
            })

            if len(results) >= 10:
                return results

    return results


# ============================================================
# REPORT
# ============================================================

def format_compounds(values):

    if not values:
        return "Not detected"

    return ", ".join(
        values
    )


def build_report(
    ground_truth,
    validations,
    ranked,
    corner_guide,
    consensus,
    meta_comparison,
    takeaways
):

    lines = []

    lines.append(
        "GT7 COMMUNITY INTELLIGENCE V3"
    )

    lines.append(
        "=" * 94
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
        f"{ground_truth.get('direction')}"
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
        "-" * 94
    )

    for item in validations:

        lines.append(
            f"{item['channel']} | "
            f"{item['status']} | "
            f"{item['reliability']}"
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

    # ========================================================
    # CORNER GUIDE
    # ========================================================

    lines.append("")
    lines.append(
        "CORNER-BY-CORNER / SEQUENTIAL GUIDE"
    )

    lines.append(
        "-" * 94
    )

    if not corner_guide:

        lines.append(
            "No sequential technical guide extracted."
        )

    else:

        for index, item in enumerate(
            corner_guide[
                :18
            ],
            start=1
        ):

            lines.append(
                f"{index}. "
                f"[{item['channel']} | "
                f"{item['reliability']}]"
            )

            if item[
                "brake_reference"
            ]:

                lines.append(
                    f"   Brake ref : "
                    f"{item['brake_reference']}"
                )

            if item[
                "gear"
            ]:

                lines.append(
                    f"   Gear      : "
                    f"{item['gear']}"
                )

            if item[
                "techniques"
            ]:

                lines.append(
                    f"   Technique : "
                    f"{'; '.join(item['techniques'])}"
                )

            lines.append(
                f"   Note      : "
                f"{item['summary']}"
            )

    # ========================================================
    # TECHNICAL CATEGORIES
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
            "-" * 94
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
        "-" * 94
    )

    if not consensus:

        lines.append(
            "No strong multi-source consensus detected."
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
                f"{item['example']}"
            )

    # ========================================================
    # META
    # ========================================================

    lines.append("")
    lines.append(
        "COMMUNITY VS LIVE LEADERBOARD META"
    )

    lines.append(
        "-" * 94
    )

    community_mentions = (
        meta_comparison[
            "community_mentions"
        ]
    )

    if community_mentions:

        lines.append(
            "Community mentions:"
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
            "Community mentions: none."
        )

    lines.append("")
    lines.append(
        "Live Top 1000:"
    )

    live_top5 = (
        meta_comparison[
            "live_top5"
        ]
    )

    if live_top5:

        for index, item in enumerate(
            live_top5,
            start=1
        ):

            percentage = item.get(
                "percentage"
            )

            percentage_text = (
                f"{percentage:.1f}%"
                if isinstance(
                    percentage,
                    (int, float)
                )
                else "N/A"
            )

            lines.append(
                f"{index}. "
                f"{item.get('car')} | "
                f"{item.get('drivers')} drivers | "
                f"{percentage_text}"
            )

    # ========================================================
    # TAKEAWAYS
    # ========================================================

    lines.append("")
    lines.append(
        "TOP PRACTICAL TAKEAWAYS"
    )

    lines.append(
        "-" * 94
    )

    for index, item in enumerate(
        takeaways,
        start=1
    ):

        lines.append(
            f"{index}. "
            f"[{item['category']}] "
            f"{item['text']}"
        )

        lines.append(
            f"   Source: "
            f"{item['source']}"
        )

    # ========================================================
    # POLICY
    # ========================================================

    lines.append("")
    lines.append(
        "ANALYSIS POLICY"
    )

    lines.append(
        "-" * 94
    )

    lines.append(
        "Live race configuration remains the authoritative source "
        "for current regulations."
    )

    lines.append(
        "Rejected community sources cannot influence strategy or "
        "driving recommendations."
    )

    lines.append(
        "Sequential corner guidance is inferred from transcript order "
        "and is not yet mapped to official corner numbers."
    )

    lines.append(
        "Leaderboard usage remains the primary evidence for live car meta."
    )

    lines.append("")
    lines.append(
        "=" * 94
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
        "=" * 94
    )

    print(
        "GT7 COMMUNITY ANALYZER V3"
    )

    print(
        "=" * 94
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
    # VALIDATION
    # ========================================================

    validations = [
        validate_source(
            source,
            ground_truth
        )
        for source in transcript_sources
    ]

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
    # CORNER GUIDE
    # ========================================================

    corner_guide = build_corner_guide(
        transcript_sources,
        validations
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
    # OUTPUT
    # ========================================================

    output = {
        "version":
            3,

        "ground_truth":
            ground_truth,

        "source_validation":
            validations,

        "corner_guide":
            corner_guide,

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
        corner_guide,
        consensus,
        meta_comparison,
        takeaways
    )

    OUTPUT_REPORT.write_text(
        report,
        encoding="utf-8"
    )

    print("")
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