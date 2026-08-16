from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


VERSION = "5.3"

DATA_DIR = Path("data")
TRANSCRIPT_DIR = DATA_DIR / "community_transcripts"
OUTPUT_DIR = DATA_DIR / "community_intelligence"

OUTPUT_JSON = OUTPUT_DIR / "community_intelligence.json"
OUTPUT_TXT = OUTPUT_DIR / "community_intelligence.txt"


# =============================================================================
# GENERIC HELPERS
# =============================================================================


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def safe_str(value: Any, default: str = "unknown") -> str:
    if value is None:
        return default

    value = str(value).strip()

    if not value:
        return default

    return value


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize_for_search(text: str) -> str:
    text = text.lower()
    text = text.replace("tyre", "tire")
    text = text.replace("citroën", "citroen")
    text = text.replace("gr 4", "gr.4")
    return normalize_space(text)


def unique_preserve_order(values: list[str]) -> list[str]:
    result = []
    seen = set()

    for value in values:
        key = normalize_space(value)

        if not key:
            continue

        if key in seen:
            continue

        seen.add(key)
        result.append(value.strip())

    return result


def format_multiplier(value: Any) -> str:
    if value is None:
        return "unknown"

    try:
        return f"x{int(value)}"
    except Exception:
        return safe_str(value)


def score_to_laptime(score: Any) -> str:
    try:
        ms = int(round(float(score)))
    except Exception:
        return "unknown"

    minutes = ms // 60000
    seconds = (ms % 60000) / 1000

    return f"{minutes}:{seconds:06.3f}"


# =============================================================================
# FIND SNAPSHOT
# =============================================================================


def find_snapshot_file() -> Path:
    candidates = [
        DATA_DIR / "latest_snapshot.json",
        DATA_DIR / "snapshot.json",
        Path("latest_snapshot.json"),
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    recursive = list(DATA_DIR.rglob("latest_snapshot.json"))

    if recursive:
        recursive.sort(
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return recursive[0]

    raise FileNotFoundError(
        "Could not find latest_snapshot.json."
    )


# =============================================================================
# RACE CONFIGURATION
# =============================================================================


def parse_track_from_description(description: str) -> str:
    if not description:
        return "unknown"

    known_tracks = [
        "Grand Valley - Highway 1",
        "Grand Valley Highway 1",
        "Fuji International Speedway",
        "Suzuka Circuit",
        "Michelin Raceway Road Atlanta",
        "Autodromo de Interlagos",
        "Autódromo de Interlagos",
        "Tokyo Expressway",
        "Mount Panorama",
    ]

    lower = description.lower()

    for track in known_tracks:
        if track.lower() in lower:
            if track == "Grand Valley Highway 1":
                return "Grand Valley - Highway 1"

            return track

    match = re.search(
        r"Daily Race C.*?\d{1,2}:\d{2}\s+(.+?)\s+"
        r"(?:[A-Z]\.\s*[A-Za-z]+|[A-Za-z0-9_-]+\s*-\s*)",
        description,
        re.I,
    )

    if match:
        track = normalize_space(match.group(1))

        if track:
            return track

    return "unknown"


def parse_class_from_description(description: str) -> str:
    match = re.search(
        r"\bGr\.?\s*([1-4BX])\b",
        description,
        re.I,
    )

    if not match:
        return "unknown"

    value = match.group(1).upper()

    return f"Gr.{value}"


def parse_direction(description: str) -> str:
    text = description.lower()

    if "reverse" in text:
        return "REVERSE"

    return "NORMAL"


def extract_live_configuration(snapshot: dict) -> dict:
    race = snapshot.get("race", {})

    if not isinstance(race, dict):
        race = {}

    description = safe_str(
        race.get("description"),
        "",
    )

    start_date = race.get("start_date")

    if not start_date:
        start_date = snapshot.get("race_week")

    track = (
        race.get("track")
        or race.get("track_name")
        or parse_track_from_description(description)
    )

    race_class = (
        race.get("class")
        or race.get("race_class")
        or parse_class_from_description(description)
    )

    direction = (
        race.get("direction")
        or parse_direction(description)
    )

    compounds = race.get("compounds", [])

    if not isinstance(compounds, list):
        compounds = []

    return {
        "week": safe_str(start_date),
        "track": safe_str(track),
        "class": safe_str(race_class),
        "direction": safe_str(direction).upper(),
        "fuel_multiplier": race.get("fuel_multiplier"),
        "tyre_multiplier": race.get("tyre_multiplier"),
        "compounds": compounds,
        "description": description,
    }


# =============================================================================
# TRANSCRIPT READING
# =============================================================================


LIKELY_TEXT_KEYS = [
    "transcript",
    "text",
    "content",
    "clean_text",
    "selected_text",
    "extracted_text",
]


def collect_strings(value: Any) -> list[str]:
    result = []

    if isinstance(value, str):
        if len(value.strip()) > 30:
            result.append(value)

    elif isinstance(value, list):
        for item in value:
            result.extend(
                collect_strings(item)
            )

    elif isinstance(value, dict):
        for item in value.values():
            result.extend(
                collect_strings(item)
            )

    return result


def extract_transcript_text(data: Any) -> str:
    if isinstance(data, str):
        return data.strip()

    if isinstance(data, dict):
        preferred = []

        for key in LIKELY_TEXT_KEYS:
            if key not in data:
                continue

            value = data[key]

            if isinstance(value, str):
                preferred.append(value)

            elif isinstance(value, list):
                strings = collect_strings(value)

                if strings:
                    preferred.append(
                        "\n".join(strings)
                    )

        if preferred:
            preferred.sort(
                key=len,
                reverse=True,
            )

            return preferred[0].strip()

    all_strings = collect_strings(data)

    if not all_strings:
        return ""

    all_strings.sort(
        key=len,
        reverse=True,
    )

    return all_strings[0].strip()


def identify_transcript(path: Path, data: Any) -> str:
    filename = path.name.lower()

    combined = filename

    if isinstance(data, dict):
        metadata_parts = []

        for key in [
            "channel",
            "channel_name",
            "source",
            "title",
            "role",
            "type",
        ]:
            value = data.get(key)

            if value:
                metadata_parts.append(
                    str(value)
                )

        combined += " " + " ".join(metadata_parts)

    combined = combined.lower()

    if "digit" in combined:
        return "DIGIT"

    if "gnc" in combined or "gnc racing" in combined:
        return "GNC"

    return "UNKNOWN"


def load_primary_transcripts() -> tuple[dict, dict]:
    if not TRANSCRIPT_DIR.exists():
        raise FileNotFoundError(
            f"Transcript directory not found: {TRANSCRIPT_DIR}"
        )

    digit_candidates = []
    gnc_candidates = []

    for path in TRANSCRIPT_DIR.glob("*.json"):
        try:
            data = load_json(path)
        except Exception:
            continue

        text = extract_transcript_text(data)

        if not text:
            continue

        identity = identify_transcript(
            path,
            data,
        )

        item = {
            "path": path,
            "data": data,
            "text": text,
        }

        if identity == "DIGIT":
            digit_candidates.append(item)

        elif identity == "GNC":
            gnc_candidates.append(item)

    if not digit_candidates:
        raise FileNotFoundError(
            "Digit Racing transcript not found."
        )

    if not gnc_candidates:
        raise FileNotFoundError(
            "GnC Racing transcript not found."
        )

    digit_candidates.sort(
        key=lambda x: len(x["text"]),
        reverse=True,
    )

    gnc_candidates.sort(
        key=lambda x: len(x["text"]),
        reverse=True,
    )

    return (
        digit_candidates[0],
        gnc_candidates[0],
    )


# =============================================================================
# TRANSCRIPT SENTENCE EXTRACTION
# =============================================================================


TIMESTAMP_PATTERN = re.compile(
    r"(\[\d{1,2}:\d{2}(?::\d{2})?\])"
)


def split_transcript(text: str) -> list[str]:
    text = text.replace("\r", "\n")

    parts = re.split(
        r"(?=\[\d{1,2}:\d{2}(?::\d{2})?\])",
        text,
    )

    lines = []

    for part in parts:
        part = normalize_space(part)

        if part:
            lines.append(part)

    if len(lines) <= 1:
        lines = [
            normalize_space(x)
            for x in re.split(
                r"(?<=[.!?])\s+",
                text,
            )
            if normalize_space(x)
        ]

    return lines


def lines_matching(
    text: str,
    required_any: list[str],
    forbidden: list[str] | None = None,
    max_results: int = 10,
) -> list[str]:
    forbidden = forbidden or []

    results = []

    for line in split_transcript(text):
        normalized = normalize_for_search(line)

        if not any(
            term in normalized
            for term in required_any
        ):
            continue

        if any(
            term in normalized
            for term in forbidden
        ):
            continue

        results.append(line)

    results = unique_preserve_order(results)

    return results[:max_results]


# =============================================================================
# DIGIT RACING STRATEGY
# =============================================================================


def analyze_digit_strategy(text: str) -> dict:
    normalized = normalize_for_search(text)

    overcut = lines_matching(
        text,
        [
            "overcut",
            "stayed out",
            "stay out",
            "pitted earlier",
            "pit later",
        ],
        max_results=8,
    )

    tyre_saving = lines_matching(
        text,
        [
            "tire saving",
            "saving tires",
            "gentle with my tires",
            "tire wear",
            "tyres are better",
            "tires are better",
        ],
        max_results=10,
    )

    tyre_change = lines_matching(
        text,
        [
            "required tire change",
            "change the tires",
            "mandatory",
            "pit stop is required",
            "need to change the tires",
        ],
        max_results=8,
    )

    compounds = lines_matching(
        text,
        [
            "mediums and soft",
            "racing mediums",
            "racing soft",
            "medium and soft",
        ],
        max_results=8,
    )

    pit_window = lines_matching(
        text,
        [
            "lap four",
            "lap five",
            "lap 4",
            "lap 5",
            "pit window",
        ],
        max_results=8,
    )

    citroen = lines_matching(
        text,
        [
            "citroen",
            "citroën",
        ],
        max_results=8,
    )

    overcut_supported = (
        "overcut" in normalized
        or "should have stayed out" in normalized
        or "pitted earlier" in normalized
    )

    tyre_saving_supported = bool(
        tyre_saving
    )

    tyre_change_supported = bool(
        tyre_change
    )

    citroen_supported = bool(
        citroen
    )

    evidence_score = sum(
        [
            overcut_supported,
            tyre_saving_supported,
            tyre_change_supported,
            citroen_supported,
            bool(compounds),
            bool(pit_window),
        ]
    )

    if evidence_score >= 5:
        confidence = "HIGH"
    elif evidence_score >= 3:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    if overcut_supported:
        preferred_logic = (
            "OVERCUT / EXTEND FIRST STINT"
        )
    elif pit_window:
        preferred_logic = (
            "CONVENTIONAL PIT WINDOW"
        )
    else:
        preferred_logic = (
            "NO CLEAR STRATEGY CONCLUSION"
        )

    recommendations = []

    if overcut_supported:
        recommendations.append(
            "The later race-tested evidence favours the "
            "overcut: staying out longer performed better "
            "than stopping early."
        )

    if tyre_saving_supported:
        recommendations.append(
            "Tyre preservation is strategically important; "
            "avoid unnecessary sliding and steering input "
            "during the first stint."
        )

    if tyre_change_supported:
        recommendations.append(
            "Digit confirms that the race requires use of "
            "the tyre-change rule."
        )

    if citroen_supported:
        recommendations.append(
            "Digit identifies the GT by Citroën Gr.4 as "
            "particularly strong for this race, including "
            "tyre performance."
        )

    return {
        "confidence": confidence,
        "preferred_logic": preferred_logic,
        "tyre_saving_supported": tyre_saving_supported,
        "tyre_change_supported": tyre_change_supported,
        "citroen_supported": citroen_supported,
        "recommendations": recommendations,
        "evidence": {
            "overcut": overcut,
            "tyre_saving": tyre_saving,
            "tyre_change": tyre_change,
            "compounds": compounds,
            "citroen": citroen,
            "pit_window": pit_window,
        },
    }


# =============================================================================
# GNC QUALIFYING GUIDE
# =============================================================================


def classify_gnc_line(line: str) -> list[str]:
    normalized = normalize_for_search(line)

    tags = []

    braking_terms = [
        "brake",
        "braking",
        "200 board",
        "100 board",
        "350 m",
        "50 m ahead",
    ]

    throttle_terms = [
        "accelerate",
        "power",
        "full throttle",
        "hit the throttle",
    ]

    gear_terms = [
        "gear",
        "shifting",
        "shift down",
        "shift up",
    ]

    line_terms = [
        "line",
        "inside",
        "outside",
        "left side",
        "right side",
        "turn in",
        "hug",
        "apex",
        "drift over",
    ]

    track_limit_terms = [
        "curb",
        "kerb",
        "white line",
        "track side",
        "bollard",
        "bridge",
    ]

    if any(
        term in normalized
        for term in braking_terms
    ):
        tags.append("BRAKING")

    if any(
        term in normalized
        for term in throttle_terms
    ):
        tags.append("THROTTLE")

    if any(
        term in normalized
        for term in gear_terms
    ):
        tags.append("GEAR")

    if any(
        term in normalized
        for term in line_terms
    ):
        tags.append("LINE")

    if any(
        term in normalized
        for term in track_limit_terms
    ):
        tags.append("TRACK_LIMIT")

    return tags


def analyze_gnc(text: str) -> dict:
    lines = split_transcript(text)

    guide = []

    braking = []
    gears = []
    track_limits = []

    for line in lines:
        normalized = normalize_for_search(line)

        tags = classify_gnc_line(line)

        if not tags:
            continue

        useful = any(
            term in normalized
            for term in [
                "200 board",
                "100 board",
                "350 m",
                "50 m",
                "accelerate",
                "power",
                "second gear",
                "inside",
                "left side",
                "right side",
                "bridge",
                "curb",
                "white line",
                "tunnel",
                "rock",
                "banner",
                "yellow",
                "sand",
                "hut",
                "apex",
            ]
        )

        if not useful:
            continue

        guide.append(
            {
                "tags": tags,
                "text": line,
            }
        )

        if "BRAKING" in tags:
            braking.append(line)

        if "GEAR" in tags:
            gears.append(line)

        if "TRACK_LIMIT" in tags:
            track_limits.append(line)

    # Deduplicate
    seen = set()
    clean_guide = []

    for item in guide:
        key = normalize_space(item["text"])

        if key in seen:
            continue

        seen.add(key)
        clean_guide.append(item)

    return {
        "confidence": (
            "HIGH"
            if len(clean_guide) >= 8
            else "MEDIUM"
        ),
        "guide": clean_guide[:30],
        "braking_references": unique_preserve_order(
            braking
        )[:15],
        "gears": unique_preserve_order(
            gears
        )[:10],
        "track_limits": unique_preserve_order(
            track_limits
        )[:10],
    }


# =============================================================================
# LIVE CAR META
# =============================================================================


def extract_car_meta(snapshot: dict) -> list[dict]:
    cars = snapshot.get(
        "top5_used_cars",
        [],
    )

    if not isinstance(cars, list):
        return []

    result = []

    for car in cars[:5]:
        if not isinstance(car, dict):
            continue

        result.append(
            {
                "car": safe_str(
                    car.get("car")
                ),
                "count": car.get("count"),
                "percentage": car.get(
                    "percentage"
                ),
            }
        )

    return result


# =============================================================================
# PRACTICAL PLAN
# =============================================================================


def build_practical_plan(
    strategy: dict,
    meta: list[dict],
) -> list[str]:

    plan = [
        (
            "Use the official/live race configuration "
            "as the regulatory baseline."
        )
    ]

    if strategy[
        "preferred_logic"
    ] == "OVERCUT / EXTEND FIRST STINT":
        plan.append(
            "Do not treat laps 4-5 as a rigid pit "
            "window. Digit's later race-tested "
            "conclusion favours staying out longer "
            "and using the overcut rather than "
            "stopping early."
        )

    if strategy[
        "tyre_saving_supported"
    ]:
        plan.append(
            "Protect the tyres during the first stint; "
            "excessive steering, sliding and front-tyre "
            "overload reduce the benefit of the overcut."
        )

    if meta:
        top_car = meta[0]["car"]

        if (
            strategy["citroen_supported"]
            and "citro" in top_car.lower()
        ):
            plan.append(
                "The GT by Citroën Gr.4 is supported "
                "independently by both Digit's race "
                "experience and the live leaderboard meta."
            )
        else:
            plan.append(
                f"The live leaderboard currently favours "
                f"{top_car}; use leaderboard evidence as "
                f"the primary reference for the car meta."
            )

    plan.append(
        "Use the GnC guide for braking references, "
        "gears, racing line and throttle technique; "
        "do not mix lap instructions from other "
        "community sources."
    )

    return plan


# =============================================================================
# TEXT REPORT
# =============================================================================


def separator(char: str = "=") -> str:
    return char * 100


def build_text_report(
    race: dict,
    digit: dict,
    gnc: dict,
    meta: list[dict],
    practical_plan: list[str],
) -> str:

    out = []

    out.append(separator())
    out.append(
        f"GT7 COMMUNITY INTELLIGENCE V{VERSION}"
    )
    out.append(separator())

    out.append(
        f"Race week        : {race['week']}"
    )
    out.append(
        f"Track            : {race['track']}"
    )
    out.append(
        f"Class            : {race['class']}"
    )
    out.append(
        f"Direction        : {race['direction']}"
    )
    out.append(
        f"Fuel             : "
        f"{format_multiplier(race['fuel_multiplier'])}"
    )
    out.append(
        f"Tyre wear        : "
        f"{format_multiplier(race['tyre_multiplier'])}"
    )

    compounds = (
        ", ".join(race["compounds"])
        if race["compounds"]
        else "unknown"
    )

    out.append(
        f"Compounds        : {compounds}"
    )
    out.append("")

    out.append("SOURCE POLICY")
    out.append(separator("-"))
    out.append(
        "Race strategy    : Digit Racing only"
    )
    out.append(
        "Qualifying guide : GnC Racing only"
    )
    out.append(
        "Race regulations : live GT7/GTSH snapshot"
    )
    out.append(
        "Car meta         : live leaderboard"
    )
    out.append("")

    out.append(
        "RACE STRATEGY — DIGIT RACING"
    )
    out.append(separator("-"))

    out.append(
        f"Confidence       : "
        f"{digit['confidence']}"
    )

    out.append(
        f"Preferred logic  : "
        f"{digit['preferred_logic']}"
    )

    out.append(
        "Tyre saving      : "
        + (
            "SUPPORTED BY DIGIT"
            if digit["tyre_saving_supported"]
            else "not explicitly established"
        )
    )

    out.append(
        "Tyre change      : "
        + (
            "SUPPORTED BY DIGIT"
            if digit["tyre_change_supported"]
            else "not established from Digit transcript"
        )
    )

    out.append(
        "Citroën          : "
        + (
            "SUPPORTED BY DIGIT"
            if digit["citroen_supported"]
            else "not explicitly established"
        )
    )

    out.append("")

    for i, item in enumerate(
        digit["recommendations"],
        start=1,
    ):
        out.append(
            f"{i}. {item}"
        )

    out.append("")
    out.append("STRATEGY EVIDENCE")
    out.append(separator("-"))

    evidence_sections = [
        (
            "Overcut / stay out",
            digit["evidence"]["overcut"],
        ),
        (
            "Tyre saving",
            digit["evidence"]["tyre_saving"],
        ),
        (
            "Tyre change",
            digit["evidence"]["tyre_change"],
        ),
        (
            "Compounds",
            digit["evidence"]["compounds"],
        ),
        (
            "Citroën / meta",
            digit["evidence"]["citroen"],
        ),
        (
            "Pit-window discussion",
            digit["evidence"]["pit_window"],
        ),
    ]

    for title, entries in evidence_sections:
        if not entries:
            continue

        out.append("")
        out.append(f"{title}:")

        for entry in entries:
            out.append(
                f"  - {entry}"
            )

    out.append("")
    out.append(
        "QUALIFYING / FAST LAP — GNC RACING"
    )
    out.append(separator("-"))

    out.append(
        f"Confidence       : {gnc['confidence']}"
    )

    for i, item in enumerate(
        gnc["guide"],
        start=1,
    ):
        tags = "/".join(
            item["tags"]
        )

        out.append(
            f"{i:2d}. [{tags}] {item['text']}"
        )

    out.append("")
    out.append(
        "BRAKING REFERENCES — GNC"
    )
    out.append(separator("-"))

    for entry in gnc[
        "braking_references"
    ]:
        out.append(
            f"- {entry}"
        )

    out.append("")
    out.append(
        "GEARS / SHIFTING — GNC"
    )
    out.append(separator("-"))

    for entry in gnc["gears"]:
        out.append(
            f"- {entry}"
        )

    out.append("")
    out.append(
        "TRACK LIMITS / KERBS — GNC"
    )
    out.append(separator("-"))

    for entry in gnc["track_limits"]:
        out.append(
            f"- {entry}"
        )

    out.append("")
    out.append(
        "LIVE CAR META — TOP 1000"
    )
    out.append(separator("-"))

    for i, car in enumerate(
        meta,
        start=1,
    ):
        percentage = car.get(
            "percentage"
        )

        if isinstance(
            percentage,
            (int, float),
        ):
            pct = f"{percentage:.1f}%"
        else:
            pct = "unknown"

        out.append(
            f"{i:2d}. {car['car']} | "
            f"{car['count']} drivers | {pct}"
        )

    out.append("")
    out.append("PRACTICAL RACE PLAN")
    out.append(separator("-"))

    for i, item in enumerate(
        practical_plan,
        start=1,
    ):
        out.append(
            f"{i}. {item}"
        )

    out.append("")
    out.append("ANALYSIS POLICY")
    out.append(separator("-"))

    policy = [
        (
            "Digit Racing is the sole community "
            "source for race strategy."
        ),
        (
            "GnC Racing is the sole community "
            "source for qualifying/lap guidance."
        ),
        (
            "Live GT7/GTSH data overrides any "
            "conflicting community statement."
        ),
        (
            "Later race-tested Digit conclusions "
            "override earlier speculative strategy comments."
        ),
        (
            "Live leaderboard usage is authoritative "
            "for current car meta."
        ),
        (
            "Snapshot Top-1000 car percentages are "
            "used directly and are never renormalized."
        ),
        (
            "Transcript evidence is never used to "
            "invent missing braking points, gears "
            "or strategy."
        ),
    ]

    for i, item in enumerate(
        policy,
        start=1,
    ):
        out.append(
            f"{i}. {item}"
        )

    out.append("")
    out.append(separator())

    return "\n".join(out)


# =============================================================================
# MAIN
# =============================================================================


def main() -> None:
    print(separator())
    print(
        f"GT7 COMMUNITY ANALYZER V{VERSION}"
    )
    print(separator())

    snapshot_file = find_snapshot_file()
    snapshot = load_json(snapshot_file)

    digit_source, gnc_source = (
        load_primary_transcripts()
    )

    digit_text = digit_source["text"]
    gnc_text = gnc_source["text"]

    print(
        "Digit transcript : FOUND"
    )
    print(
        "GnC transcript   : FOUND"
    )
    print(
        f"Digit characters : {len(digit_text):,}"
    )
    print(
        f"GnC characters   : {len(gnc_text):,}"
    )
    print()

    race = extract_live_configuration(
        snapshot
    )

    print("LIVE CONFIGURATION")
    print(separator("-"))
    print(
        f"Week             : {race['week']}"
    )
    print(
        f"Track            : {race['track']}"
    )
    print(
        f"Class            : {race['class']}"
    )
    print(
        f"Direction        : {race['direction']}"
    )
    print(
        "Fuel             : "
        + format_multiplier(
            race["fuel_multiplier"]
        )
    )
    print(
        "Tyre wear        : "
        + format_multiplier(
            race["tyre_multiplier"]
        )
    )

    compounds = (
        ", ".join(race["compounds"])
        if race["compounds"]
        else "unknown"
    )

    print(
        f"Compounds        : {compounds}"
    )
    print()

    digit_analysis = (
        analyze_digit_strategy(
            digit_text
        )
    )

    gnc_analysis = analyze_gnc(
        gnc_text
    )

    meta = extract_car_meta(
        snapshot
    )

    practical_plan = (
        build_practical_plan(
            digit_analysis,
            meta,
        )
    )

    report = build_text_report(
        race,
        digit_analysis,
        gnc_analysis,
        meta,
        practical_plan,
    )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_data = {
        "version": VERSION,
        "race": race,
        "source_policy": {
            "strategy": "Digit Racing",
            "lap_guide": "GnC Racing",
            "regulations": (
                "live GT7/GTSH snapshot"
            ),
            "car_meta": (
                "live leaderboard"
            ),
        },
        "source_files": {
            "snapshot": str(
                snapshot_file
            ),
            "digit": str(
                digit_source["path"]
            ),
            "gnc": str(
                gnc_source["path"]
            ),
        },
        "strategy": digit_analysis,
        "qualifying": gnc_analysis,
        "live_car_meta": meta,
        "practical_race_plan": (
            practical_plan
        ),
    }

    OUTPUT_JSON.write_text(
        json.dumps(
            output_data,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    OUTPUT_TXT.write_text(
        report,
        encoding="utf-8",
    )

    print(report)
    print()

    print(
        f"JSON report      : {OUTPUT_JSON}"
    )
    print(
        f"Text report      : {OUTPUT_TXT}"
    )
    print()

    print(separator())
    print(
        "COMMUNITY INTELLIGENCE COMPLETE"
    )
    print(separator())


if __name__ == "__main__":
    main()