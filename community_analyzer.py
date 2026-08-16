import json
import re

from collections import Counter
from pathlib import Path


# ============================================================
# CONFIG
# ============================================================

DATA_DIR = Path("data")

LATEST_SNAPSHOT_FILE = DATA_DIR / "latest_snapshot.json"
COMMUNITY_SOURCES_FILE = DATA_DIR / "community_sources.json"

TRANSCRIPT_DIRS = [
    DATA_DIR / "community_transcripts",
    DATA_DIR / "community_supadata_test" / "transcripts",
]

OUTPUT_DIR = DATA_DIR / "community_intelligence"
OUTPUT_JSON = OUTPUT_DIR / "community_intelligence.json"
OUTPUT_REPORT = OUTPUT_DIR / "community_intelligence.txt"


# ============================================================
# SOURCE PRIORITY
# ============================================================

STRATEGY_PRIORITY = [
    "Digit Racing",
    "Wombleleader Racing",
    "ProdigyRacing",
]

LAP_GUIDE_PRIORITY = [
    "GnC Racing",
    "Digit Racing",
]


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
    max_chars=360
):

    text = normalize_space(
        text
    )

    if len(text) <= max_chars:
        return text

    shortened = text[:max_chars]

    cut = shortened.rfind(
        " "
    )

    if cut > 0:
        shortened = shortened[:cut]

    return shortened + "..."


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

    value = value.strip().lower()

    if value.isdigit():
        return int(value)

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

    race_class = community_week.get(
        "race_class"
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
# VALIDATION HELPERS
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

    return (
        matched
        / len(target_words)
    ) >= 0.60


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

    if "reverse" in normalize_text(
        text
    ):
        return "REVERSE"

    return None


# ============================================================
# MULTIPLIERS
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
            r"fuel rate"
            r"|fuel consumption"
            r"|fuel multiplier"
            r"|fuel"
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
            rf".{{0,50}}?"
            rf"(?:x|times|multiplier(?:\s+of)?)"
            rf"\s*({number_pattern})"
        ),

        (
            rf"{subject_pattern}"
            rf".{{0,50}}?"
            rf"(?:at|is|of)"
            rf"\s+(?:a\s+)?"
            rf"({number_pattern})"
            rf"\s*(?:times|x)?"
        ),

        (
            rf"({number_pattern})"
            rf"\s*(?:x|times)"
            rf".{{0,40}}?"
            rf"{subject_pattern}"
        ),
    ]

    values = []

    for pattern in patterns:

        for match in re.findall(
            pattern,
            normalized,
            re.IGNORECASE
        ):

            if isinstance(
                match,
                tuple
            ):
                match = next(
                    (
                        value
                        for value in match
                        if value
                    ),
                    None
                )

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

    value, count = counter.most_common(
        1
    )[0]

    return {
        "value":
            value,

        "count":
            count,

        "mentions":
            values,
    }


# ============================================================
# COMPOUNDS
# ============================================================

def detect_regulation_compounds(
    text
):

    normalized = normalize_space(
        text
    ).lower()

    compounds = set()

    # Direct expressions
    direct_patterns = {
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
    }

    regulation_cues = [
        "available",
        "mandatory",
        "required",
        "must use",
        "tire type",
        "tyre type",
        "tires are",
        "tyres are",
    ]

    for code, patterns in direct_patterns.items():

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
                    cue in window
                    for cue in regulation_cues
                ):
                    compounds.add(
                        code
                    )

    # Shared noun expressions:
    # "medium and soft tires"
    shared_patterns = [
        (
            r"\bmedium\s+and\s+soft\s+tires?\b",
            {"RM", "RS"}
        ),

        (
            r"\bmedium\s+and\s+soft\s+tyres?\b",
            {"RM", "RS"}
        ),

        (
            r"\bhard\s+and\s+medium\s+tires?\b",
            {"RH", "RM"}
        ),

        (
            r"\bhard\s+and\s+medium\s+tyres?\b",
            {"RH", "RM"}
        ),

        (
            r"\bsoft\s+and\s+medium\s+tires?\b",
            {"RS", "RM"}
        ),

        (
            r"\bsoft\s+and\s+medium\s+tyres?\b",
            {"RS", "RM"}
        ),
    ]

    for pattern, detected in (
        shared_patterns
    ):

        if re.search(
            pattern,
            normalized,
            re.IGNORECASE
        ):
            compounds.update(
                detected
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
        + transcript[:15000]
    )

    matches = []
    reasons = []

    rejected = False

    # Track
    if fuzzy_contains(
        ground_truth.get(
            "track"
        ),
        title
    ):
        matches.append(
            "TRACK_MATCH"
        )

    # Class
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

    # Direction
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

    # Fuel
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

    # Tyres
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

    # Compounds
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

    if rejected:

        status = "REJECTED"
        reliability = (
            "STALE_OR_WRONG_RACE"
        )

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

        "detected": {
            "fuel_multiplier":
                (
                    fuel["value"]
                    if fuel
                    else None
                ),

            "tyre_multiplier":
                (
                    tyre["value"]
                    if tyre
                    else None
                ),

            "compounds":
                sorted(
                    detected_compounds
                ),
        },
    }


# ============================================================
# SOURCE SELECTION
# ============================================================

def select_priority_source(
    transcript_sources,
    validations,
    priority_channels,
    allowed_types=None
):

    validation_lookup = {
        item[
            "video_id"
        ]:
            item
        for item in validations
    }

    candidates = []

    for source in transcript_sources:

        data = source[
            "data"
        ]

        validation = validation_lookup.get(
            data.get(
                "video_id"
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

        content_type = data.get(
            "content_type",
            "OTHER"
        )

        if (
            allowed_types
            and content_type
            not in allowed_types
        ):
            continue

        candidates.append(
            source
        )

    for priority_channel in (
        priority_channels
    ):

        for source in candidates:

            channel = (
                source[
                    "data"
                ]
                .get(
                    "channel",
                    ""
                )
            )

            if (
                channel.strip().lower()
                == priority_channel.lower()
            ):
                return source

    return None


# ============================================================
# SEGMENTATION
# ============================================================

def transcript_segments(
    text,
    min_words=10,
    target_words=32,
    max_words=52
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

        for start in range(
            0,
            len(words),
            target_words
        ):

            chunk = words[
                start:
                start + max_words
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
# LAP GUIDE EXTRACTION
# ============================================================

def lap_guide_score(text):

    normalized = (
        text.lower()
    )

    patterns = [
        r"\bbrak",
        r"\bboard\b",
        r"\bgear\b",
        r"\bdownshift",
        r"\bupshift",
        r"\bturn in\b",
        r"\bapex\b",
        r"\bcurb\b",
        r"\bkerb\b",
        r"\bthrottle\b",
        r"\baccelerat",
        r"\bpower\b",
        r"\bentry\b",
        r"\bexit\b",
        r"\bwhite line\b",
        r"\bundersteer\b",
    ]

    return sum(
        1
        for pattern in patterns
        if re.search(
            pattern,
            normalized
        )
    )


def extract_reference(text):

    normalized = (
        text.lower()
    )

    patterns = [
        r"\baround\s+\d+\s*m\b",
        r"\b\d+\s*m\b",
        r"\b\d+\s*(?:feet|ft)\b",
        r"\b\d+\s+board\b",
        r"\b\d+\s+sign\b",
        r"\bunder the bridge\b",
        r"\bafter we pass under this bridge\b",
        r"\bout of the tunnel\b",
        r"\bdark mark in the sand\b",
        r"\barrow sign\b",
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


def extract_gear(text):

    normalized = text.lower()

    patterns = [
        r"\b(first|second|third|fourth|fifth|sixth)\s+gear\b",
        r"\b([1-6])(?:st|nd|rd|th)\s+gear\b",
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


def extract_lap_guide(
    source
):

    if not source:
        return []

    data = source[
        "data"
    ]

    segments = transcript_segments(
        data.get(
            "transcript",
            ""
        )
    )

    entries = []

    for index, segment in enumerate(
        segments
    ):

        score = lap_guide_score(
            segment
        )

        if score < 2:
            continue

        entries.append({
            "sequence":
                index,

            "reference":
                extract_reference(
                    segment
                ),

            "gear":
                extract_gear(
                    segment
                ),

            "text":
                compact_text(
                    segment,
                    300
                ),

            "score":
                score,
        })

    # Avoid near-neighbor repetition
    cleaned = []

    previous_sequence = None

    for entry in entries:

        if (
            previous_sequence
            is not None
            and entry[
                "sequence"
            ]
            == previous_sequence + 1
            and entry[
                "reference"
            ]
            == (
                cleaned[
                    -1
                ][
                    "reference"
                ]
                if cleaned
                else None
            )
        ):
            continue

        cleaned.append(
            entry
        )

        previous_sequence = entry[
            "sequence"
        ]

    return cleaned[:16]


# ============================================================
# STRATEGY EXTRACTION
# ============================================================

STRATEGY_PATTERNS = {
    "PIT":
        [
            r"\bpit\b",
            r"\bno stop\b",
            r"\bone stop\b",
            r"\bstop strategy\b",
        ],

    "TYRES":
        [
            r"\btyre\b",
            r"\btire\b",
            r"\bmandatory\b",
            r"\bcompound\b",
        ],

    "FUEL":
        [
            r"\bfuel\b",
            r"\bshort shift\b",
            r"\bsave fuel\b",
        ],

    "RACECRAFT":
        [
            r"\bovertak",
            r"\bslipstream\b",
            r"\bdraft\b",
            r"\btraffic\b",
            r"\bdefend",
        ],

    "WARNINGS":
        [
            r"\bpenalty\b",
            r"\btrack limits\b",
            r"\bcareful\b",
            r"\bavoid\b",
        ],
}


def strategy_segment_score(
    text
):

    normalized = (
        text.lower()
    )

    score = 0

    for patterns in (
        STRATEGY_PATTERNS.values()
    ):

        score += sum(
            1
            for pattern in patterns
            if re.search(
                pattern,
                normalized
            )
        )

    return score


def strategy_categories(
    text
):

    normalized = text.lower()

    categories = []

    for category, patterns in (
        STRATEGY_PATTERNS.items()
    ):

        if any(
            re.search(
                pattern,
                normalized
            )
            for pattern in patterns
        ):
            categories.append(
                category
            )

    return categories


def extract_strategy(
    source
):

    if not source:
        return []

    data = source[
        "data"
    ]

    segments = transcript_segments(
        data.get(
            "transcript",
            ""
        )
    )

    rows = []

    for segment in segments:

        score = strategy_segment_score(
            segment
        )

        if score < 1:
            continue

        rows.append({
            "categories":
                strategy_categories(
                    segment
                ),

            "text":
                compact_text(
                    segment,
                    360
                ),

            "score":
                score,
        })

    rows.sort(
        key=lambda item:
            item[
                "score"
            ],
        reverse=True
    )

    output = []

    seen = set()

    for row in rows:

        key = normalize_text(
            row[
                "text"
            ]
        )[:120]

        if key in seen:
            continue

        seen.add(
            key
        )

        output.append(
            row
        )

        if len(output) >= 8:
            break

    return output


# ============================================================
# LIVE META
# ============================================================

def build_live_meta(
    ground_truth
):

    return [
        {
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
        }

        for item in ground_truth.get(
            "top5_used_cars",
            []
        )
    ]


# ============================================================
# REPORT
# ============================================================

def format_compounds(values):

    if not values:
        return "Not detected"

    return ", ".join(
        values
    )


def source_description(
    source
):

    if not source:
        return "NOT AVAILABLE"

    data = source[
        "data"
    ]

    return (
        f"{data.get('channel','Unknown')} | "
        f"{data.get('content_type','OTHER')} | "
        f"{data.get('title','')}"
    )


def build_report(
    ground_truth,
    validations,
    strategy_source,
    strategy_rows,
    lap_source,
    lap_rows,
    live_meta
):

    lines = []

    lines.append(
        "GT7 COMMUNITY INTELLIGENCE V4"
    )

    lines.append(
        "=" * 96
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
        f"Fuel             : "
        f"x{ground_truth.get('fuel_multiplier')}"
    )

    lines.append(
        f"Tyre wear        : "
        f"x{ground_truth.get('tyre_multiplier')}"
    )

    lines.append(
        f"Compounds        : "
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
        "-" * 96
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
    # SELECTED SOURCES
    # ========================================================

    lines.append("")
    lines.append(
        "SELECTED COMMUNITY SOURCES"
    )

    lines.append(
        "-" * 96
    )

    lines.append(
        "Race strategy   : "
        + source_description(
            strategy_source
        )
    )

    lines.append(
        "Lap guide       : "
        + source_description(
            lap_source
        )
    )

    # ========================================================
    # RACE STRATEGY
    # ========================================================

    lines.append("")
    lines.append(
        "RACE STRATEGY"
    )

    lines.append(
        "-" * 96
    )

    lines.append(
        f"Official/live fuel      : "
        f"x{ground_truth.get('fuel_multiplier')}"
    )

    lines.append(
        f"Official/live tyre wear : "
        f"x{ground_truth.get('tyre_multiplier')}"
    )

    lines.append(
        f"Official/live compounds : "
        f"{format_compounds(ground_truth.get('compounds'))}"
    )

    if not strategy_source:

        lines.append("")
        lines.append(
            "Digit Racing strategy source: NOT AVAILABLE."
        )

        lines.append(
            "No community pit/fuel/tyre strategy is inferred."
        )

    elif not strategy_rows:

        lines.append("")
        lines.append(
            "Selected strategy source contains no strong "
            "strategy evidence."
        )

    else:

        lines.append("")

        for index, row in enumerate(
            strategy_rows,
            start=1
        ):

            categories = (
                ", ".join(
                    row[
                        "categories"
                    ]
                )
                or "GENERAL"
            )

            lines.append(
                f"{index}. "
                f"[{categories}] "
                f"{row['text']}"
            )

    # ========================================================
    # LAP GUIDE
    # ========================================================

    lines.append("")
    lines.append(
        "QUALIFYING / LAP GUIDE"
    )

    lines.append(
        "-" * 96
    )

    if not lap_source:

        lines.append(
            "GnC Racing lap guide source: NOT AVAILABLE."
        )

    elif not lap_rows:

        lines.append(
            "Selected lap guide contains no strong technical evidence."
        )

    else:

        for index, row in enumerate(
            lap_rows,
            start=1
        ):

            lines.append(
                f"{index}. "
                f"{row['text']}"
            )

            details = []

            if row[
                "reference"
            ]:
                details.append(
                    "Ref "
                    + row[
                        "reference"
                    ]
                )

            if row[
                "gear"
            ]:
                details.append(
                    "Gear "
                    + row[
                        "gear"
                    ]
                )

            if details:
                lines.append(
                    "   "
                    + " | ".join(
                        details
                    )
                )

    # ========================================================
    # LIVE META
    # ========================================================

    lines.append("")
    lines.append(
        "LIVE CAR META - TOP 1000"
    )

    lines.append(
        "-" * 96
    )

    if not live_meta:

        lines.append(
            "No live leaderboard meta data available."
        )

    else:

        for index, item in enumerate(
            live_meta,
            start=1
        ):

            percentage = item.get(
                "percentage"
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

    # ========================================================
    # POLICY
    # ========================================================

    lines.append("")
    lines.append(
        "SOURCE POLICY"
    )

    lines.append(
        "-" * 96
    )

    lines.append(
        "Race regulations come from live GT7/GTSH data, "
        "not from community videos."
    )

    lines.append(
        "Strategy uses one selected source only."
    )

    lines.append(
        "Lap guidance uses one selected source only."
    )

    lines.append(
        "Rejected/stale sources cannot contribute recommendations."
    )

    lines.append(
        "Live leaderboard data remains authoritative for car meta."
    )

    lines.append("")
    lines.append(
        "=" * 96
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
        "=" * 96
    )

    print(
        "GT7 COMMUNITY ANALYZER V4"
    )

    print(
        "=" * 96
    )

    print(
        f"Transcript sources found : "
        f"{len(transcript_sources)}"
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
    # SELECT STRATEGY SOURCE
    # ========================================================

    strategy_source = (
        select_priority_source(
            transcript_sources,
            validations,
            STRATEGY_PRIORITY,
            allowed_types={
                "STRATEGY",
                "RACE",
                "LIVESTREAM",
            }
        )
    )

    # ========================================================
    # SELECT LAP GUIDE SOURCE
    # ========================================================

    lap_source = (
        select_priority_source(
            transcript_sources,
            validations,
            LAP_GUIDE_PRIORITY,
            allowed_types={
                "LAP_GUIDE",
                "QUALIFYING",
            }
        )
    )

    # ========================================================
    # ANALYSIS
    # ========================================================

    strategy_rows = (
        extract_strategy(
            strategy_source
        )
    )

    lap_rows = (
        extract_lap_guide(
            lap_source
        )
    )

    live_meta = (
        build_live_meta(
            ground_truth
        )
    )

    output = {
        "version":
            4,

        "ground_truth":
            ground_truth,

        "source_validation":
            validations,

        "selected_sources": {
            "strategy":
                (
                    strategy_source[
                        "data"
                    ]
                    if strategy_source
                    else None
                ),

            "lap_guide":
                (
                    lap_source[
                        "data"
                    ]
                    if lap_source
                    else None
                ),
        },

        "strategy":
            strategy_rows,

        "lap_guide":
            lap_rows,

        "live_meta":
            live_meta,
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
        strategy_source,
        strategy_rows,
        lap_source,
        lap_rows,
        live_meta
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