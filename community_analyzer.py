#!/usr/bin/env python3

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


VERSION = "5.3"

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"

SNAPSHOT_CANDIDATES = [
    DATA_DIR / "latest_snapshot.json",
    DATA_DIR / "snapshot.json",
]

TRANSCRIPT_DB = DATA_DIR / "community_transcripts.json"
TRANSCRIPT_DIR = DATA_DIR / "community_transcripts"

OUTPUT_DIR = DATA_DIR / "community_intelligence"
OUTPUT_JSON = OUTPUT_DIR / "community_intelligence.json"
OUTPUT_TEXT = OUTPUT_DIR / "community_intelligence.txt"

STRATEGY_CHANNEL = "Digit Racing"
LAP_GUIDE_CHANNEL = "GnC Racing"

LINE_WIDTH = 100


# ============================================================================
# BASIC HELPERS
# ============================================================================


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def normalize_key(text: str) -> str:
    text = normalize_space(text).lower()
    text = text.replace("–", "-").replace("—", "-")
    return text


def print_rule(char: str = "-") -> None:
    print(char * LINE_WIDTH)


def print_header(title: str, char: str = "=") -> None:
    print(char * LINE_WIDTH)
    print(title)
    print(char * LINE_WIDTH)


def safe_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def clean_channel_name(name: str) -> str:
    return normalize_space(name)


# ============================================================================
# TRANSCRIPT CLEANING
# ============================================================================


def strip_music_noise(text: str) -> str:
    text = re.sub(
        r"\[(?:music|applause|laughter|foreign|snorts?)\]",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(r"&gt;&gt;", "", text)
    return normalize_space(text)


def collapse_consecutive_duplicate_words(text: str) -> str:
    """
    youtube-transcript.ai sometimes emits:
        "stayed out stayed out stayed out"
        "I should have I should have"

    Remove only immediately repeated word sequences.
    Conservative approach: sequence size 1..12 words.
    """
    words = text.split()

    if not words:
        return ""

    changed = True

    while changed:
        changed = False

        max_chunk = min(12, len(words) // 2)

        for size in range(max_chunk, 0, -1):
            i = 0
            result: List[str] = []
            local_change = False

            while i < len(words):
                if (
                    i + (2 * size) <= len(words)
                    and [w.lower() for w in words[i : i + size]]
                    == [w.lower() for w in words[i + size : i + (2 * size)]]
                ):
                    result.extend(words[i : i + size])

                    i += size

                    while (
                        i + size <= len(words)
                        and [w.lower() for w in words[i : i + size]]
                        == [w.lower() for w in words[i - size : i]]
                    ):
                        i += size

                    local_change = True
                else:
                    result.append(words[i])
                    i += 1

            if local_change:
                words = result
                changed = True
                break

    return " ".join(words)


def clean_transcript_line(text: str) -> str:
    text = strip_music_noise(text)
    text = collapse_consecutive_duplicate_words(text)
    text = normalize_space(text)
    return text


def clean_transcript(text: str) -> str:
    cleaned_lines: List[str] = []

    for raw_line in str(text or "").splitlines():
        line = clean_transcript_line(raw_line)

        if not line:
            continue

        if cleaned_lines and normalize_key(line) == normalize_key(cleaned_lines[-1]):
            continue

        cleaned_lines.append(line)

    return "\n".join(cleaned_lines)


# ============================================================================
# GENERIC JSON / TRANSCRIPT EXTRACTION
# ============================================================================


TEXT_KEYS = {
    "transcript",
    "text",
    "content",
    "full_text",
    "transcript_text",
    "cleaned_text",
    "extracted_text",
}


def recursively_collect_text(
    value: Any,
    key_name: Optional[str] = None,
) -> List[str]:

    found: List[str] = []

    if isinstance(value, str):
        if key_name is None or key_name.lower() in TEXT_KEYS:
            if len(value.strip()) >= 20:
                found.append(value)

    elif isinstance(value, list):
        for item in value:
            found.extend(recursively_collect_text(item, key_name))

    elif isinstance(value, dict):
        for key, item in value.items():
            found.extend(recursively_collect_text(item, str(key)))

    return found


def get_best_text_from_json(data: Any) -> str:
    texts = recursively_collect_text(data)

    if not texts:
        return ""

    texts = sorted(texts, key=len, reverse=True)
    return clean_transcript(texts[0])


def recursive_find_strings(data: Any, key_names: Iterable[str]) -> List[str]:
    target = {k.lower() for k in key_names}
    found: List[str] = []

    if isinstance(data, dict):
        for key, value in data.items():
            if str(key).lower() in target and isinstance(value, str):
                found.append(value)

            found.extend(recursive_find_strings(value, key_names))

    elif isinstance(data, list):
        for item in data:
            found.extend(recursive_find_strings(item, key_names))

    return found


def identify_channel(data: Any, path: Path) -> str:
    values = recursive_find_strings(
        data,
        [
            "channel",
            "channel_name",
            "source_channel",
            "author",
            "creator",
        ],
    )

    joined = " ".join(values + [path.name]).lower()

    if "digit racing" in joined or "digit_racing" in joined:
        return STRATEGY_CHANNEL

    if "gnc racing" in joined or "gnc_racing" in joined:
        return LAP_GUIDE_CHANNEL

    return values[0] if values else "unknown"


def identify_title(data: Any) -> str:
    values = recursive_find_strings(
        data,
        [
            "title",
            "video_title",
        ],
    )
    return normalize_space(values[0]) if values else "unknown"


def identify_video_id(data: Any, path: Path) -> str:
    values = recursive_find_strings(
        data,
        [
            "video_id",
            "videoId",
            "youtube_id",
        ],
    )

    if values:
        return normalize_space(values[0])

    match = re.match(r"([A-Za-z0-9_-]{8,})_", path.stem)

    if match:
        return match.group(1)

    return "unknown"


def discover_transcript_files() -> List[Path]:
    if not TRANSCRIPT_DIR.exists():
        return []

    return sorted(TRANSCRIPT_DIR.glob("*.json"))


def load_transcript_sources() -> Dict[str, Dict[str, Any]]:
    sources: Dict[str, Dict[str, Any]] = {}

    for path in discover_transcript_files():
        try:
            data = load_json(path)
        except Exception:
            continue

        channel = clean_channel_name(identify_channel(data, path))

        if channel not in {STRATEGY_CHANNEL, LAP_GUIDE_CHANNEL}:
            continue

        text = get_best_text_from_json(data)

        if not text:
            continue

        record = {
            "channel": channel,
            "title": identify_title(data),
            "video_id": identify_video_id(data, path),
            "path": str(path.relative_to(ROOT)),
            "text": text,
            "characters": len(text),
            "words": len(text.split()),
            "raw": data,
        }

        previous = sources.get(channel)

        if previous is None or len(text) > previous["characters"]:
            sources[channel] = record

    return sources


# ============================================================================
# SNAPSHOT DISCOVERY
# ============================================================================


def discover_snapshot() -> Tuple[Path, Dict[str, Any]]:
    for candidate in SNAPSHOT_CANDIDATES:
        if candidate.exists():
            data = load_json(candidate)

            if isinstance(data, dict):
                return candidate, data

    json_files = sorted(
        DATA_DIR.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    for path in json_files:
        if path.name in {
            "community_transcripts.json",
            "community_sources.json",
        }:
            continue

        try:
            data = load_json(path)
        except Exception:
            continue

        if not isinstance(data, dict):
            continue

        if (
            isinstance(data.get("race"), dict)
            and (
                "world_record" in data
                or "thresholds" in data
                or "top5_used_cars" in data
            )
        ):
            return path, data

    raise FileNotFoundError(
        "Could not locate a GT7 live snapshot JSON in data/."
    )


# ============================================================================
# LIVE CONFIGURATION
# ============================================================================


def extract_track_from_description(description: str) -> str:
    description = normalize_space(description)

    # Typical source:
    # Daily Race C i 16:48 Grand Valley - Highway 1 M. Estevez - GT by Citroën Gr.4 ...
    match = re.search(
        r"Daily Race C.*?\b\d{1,2}:\d{2}\s+(.+?)\s+[A-Z]\.\s*[A-Za-zÀ-ÿ'’\-]+\s+-\s+",
        description,
        flags=re.I,
    )

    if match:
        candidate = normalize_space(match.group(1))

        candidate = re.sub(
            r"^(?:i\s+)?",
            "",
            candidate,
            flags=re.I,
        ).strip()

        if candidate:
            return candidate

    known_tracks = [
        "Grand Valley - Highway 1",
        "Grand Valley Highway 1",
        "Fuji International Speedway",
        "Suzuka Circuit",
        "Autodrome Lago Maggiore",
        "Michelin Raceway Road Atlanta",
        "Dragon Trail - Seaside",
        "Dragon Trail - Gardens",
        "Deep Forest Raceway",
        "Trial Mountain Circuit",
        "Mount Panorama Motor Racing Circuit",
        "Nürburgring",
        "Brands Hatch",
        "Watkins Glen",
        "Interlagos",
        "Daytona Road Course",
    ]

    desc_lower = description.lower()

    for track in known_tracks:
        if track.lower() in desc_lower:
            if track == "Grand Valley Highway 1":
                return "Grand Valley - Highway 1"
            return track

    return "unknown"


def extract_class_from_description(description: str) -> str:
    match = re.search(
        r"\b(Gr\.\s*[1-4])\b",
        description,
        flags=re.I,
    )

    if match:
        return match.group(1).replace(" ", "")

    return "unknown"


def extract_live_configuration(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    race = snapshot.get("race", {})

    if not isinstance(race, dict):
        race = {}

    description = normalize_space(race.get("description", ""))

    track = normalize_space(
        race.get("track")
        or race.get("track_name")
        or ""
    )

    if not track:
        track = extract_track_from_description(description)

    race_class = normalize_space(
        race.get("class")
        or race.get("race_class")
        or ""
    )

    if not race_class:
        race_class = extract_class_from_description(description)

    direction = normalize_space(
        race.get("direction")
        or ""
    )

    if not direction:
        if re.search(r"\breverse\b", description, flags=re.I):
            direction = "REVERSE"
        else:
            direction = "NORMAL"

    fuel = safe_int(
        race.get("fuel_multiplier")
        or race.get("fuel")
    )

    tyres = safe_int(
        race.get("tyre_multiplier")
        or race.get("tire_multiplier")
        or race.get("tyres")
        or race.get("tires")
    )

    compounds = race.get("compounds", [])

    if not isinstance(compounds, list):
        compounds = []

    compounds = [
        normalize_space(x).upper()
        for x in compounds
        if normalize_space(x)
    ]

    week = (
        race.get("start_date")
        or snapshot.get("race_week")
        or snapshot.get("week")
        or "unknown"
    )

    return {
        "week": week,
        "track": track or "unknown",
        "class": race_class or "unknown",
        "direction": direction or "unknown",
        "fuel_multiplier": fuel,
        "tyre_multiplier": tyres,
        "compounds": compounds,
        "description": description,
    }


# ============================================================================
# TRANSCRIPT SENTENCE / TIMESTAMP HELPERS
# ============================================================================


TIMESTAMP_PATTERN = re.compile(
    r"^\[(\d{1,2}(?::\d{2}){1,2})\]\s*(.*)$"
)


def split_timestamped_units(text: str) -> List[Dict[str, str]]:
    units: List[Dict[str, str]] = []

    for raw_line in text.splitlines():
        line = clean_transcript_line(raw_line)

        if not line:
            continue

        match = TIMESTAMP_PATTERN.match(line)

        if match:
            timestamp = match.group(1)
            body = match.group(2).strip()
        else:
            timestamp = ""
            body = line

        # Split lightly, preserving useful context.
        sentences = re.split(
            r"(?<=[.!?])\s+(?=[A-Z0-9])",
            body,
        )

        for sentence in sentences:
            sentence = normalize_space(sentence)

            if len(sentence) < 12:
                continue

            units.append(
                {
                    "timestamp": timestamp,
                    "text": sentence,
                }
            )

    return units


def evidence_label(unit: Dict[str, str]) -> str:
    timestamp = unit.get("timestamp", "")
    text = unit.get("text", "")

    if timestamp:
        return f"[{timestamp}] {text}"

    return text


def unique_units(units: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen = set()
    result = []

    for unit in units:
        key = normalize_key(unit["text"])

        if key in seen:
            continue

        seen.add(key)
        result.append(unit)

    return result


def find_units(
    units: List[Dict[str, str]],
    patterns: Iterable[str],
) -> List[Dict[str, str]]:
    compiled = [
        re.compile(pattern, flags=re.I)
        for pattern in patterns
    ]

    found = []

    for unit in units:
        text = unit["text"]

        if any(pattern.search(text) for pattern in compiled):
            found.append(unit)

    return unique_units(found)


# ============================================================================
# DIGIT STRATEGY ANALYSIS
# ============================================================================


def analyse_digit_strategy(
    transcript: str,
    live: Dict[str, Any],
) -> Dict[str, Any]:

    units = split_timestamped_units(transcript)

    overcut = find_units(
        units,
        [
            r"\bovercut\b",
            r"\bunder\s*cut\b",
            r"\bshould have stayed out\b",
            r"\bstayed out\b",
            r"\bpitted earlier\b.*\blost\b",
        ],
    )

    tyre_saving = find_units(
        units,
        [
            r"\btire saving\b",
            r"\btyre saving\b",
            r"\bsaving tires\b",
            r"\bsaving tyres\b",
            r"\bgentle\b.*\btires\b",
            r"\bgentle\b.*\btyres\b",
            r"\btire wear\b",
            r"\btyre wear\b",
        ],
    )

    tyre_change = find_units(
        units,
        [
            r"\brequired\b.*\b(?:tire|tyre) change\b",
            r"\b(?:tire|tyre) change\b.*\brequired\b",
            r"\bchange the (?:tires|tyres)\b",
            r"\bpit stop is required\b",
        ],
    )

    compounds = find_units(
        units,
        [
            r"\bmediums?\b.*\bsoft\b",
            r"\bsoft\b.*\bmediums?\b",
            r"\bracing medium\b",
            r"\bracing soft\b",
        ],
    )

    pit_window = find_units(
        units,
        [
            r"\blap four\b.*\blap five\b",
            r"\blap 4\b.*\blap 5\b",
            r"\blap four[,/ -]+five\b",
            r"\blap 4[,/ -]+5\b",
        ],
    )

    start_medium = find_units(
        units,
        [
            r"\btypically starting on the mediums\b",
            r"\bstart(?:ing)? on (?:the )?mediums\b",
            r"\bstart(?:ing)? on (?:the )?racing mediums\b",
        ],
    )

    citroen = find_units(
        units,
        [
            r"\bcitroen\b",
            r"\bcitroën\b",
        ],
    )

    later_overcut = False

    for unit in overcut:
        text = normalize_key(unit["text"])

        if (
            "overcut it is" in text
            or "should have stayed out" in text
            or "pitted earlier" in text
        ):
            later_overcut = True
            break

    strategy_confidence_points = 0

    if overcut:
        strategy_confidence_points += 2

    if later_overcut:
        strategy_confidence_points += 2

    if tyre_saving:
        strategy_confidence_points += 1

    if tyre_change:
        strategy_confidence_points += 1

    if compounds:
        strategy_confidence_points += 1

    if pit_window:
        strategy_confidence_points += 1

    if start_medium:
        strategy_confidence_points += 1

    if strategy_confidence_points >= 7:
        confidence = "HIGH"
    elif strategy_confidence_points >= 4:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    preferred_logic = (
        "OVERCUT / EXTEND FIRST STINT"
        if later_overcut
        else "NO RACE-TESTED OVERRIDE IDENTIFIED"
    )

    start_compound: Optional[str] = None
    finish_compound: Optional[str] = None
    finish_compound_basis: Optional[str] = None

    if start_medium:
        start_compound = "RM"

        live_compounds = live.get("compounds", [])

        if (
            "RM" in live_compounds
            and "RS" in live_compounds
            and tyre_change
        ):
            finish_compound = "RS"
            finish_compound_basis = (
                "Derived from Digit's explicit RM start, the live RM/RS "
                "compound set and the required tyre change."
            )

    initial_window = None

    if pit_window:
        initial_window = "LAPS 4-5"

    final_window = None

    if later_overcut:
        final_window = (
            "EXTEND BEYOND THE INITIAL 4-5 WINDOW WHEN TYRE CONDITION, "
            "TRAFFIC AND LAP TIME REMAIN ACCEPTABLE"
        )
    elif initial_window:
        final_window = initial_window

    recommendations: List[str] = []

    if later_overcut:
        recommendations.append(
            "Later race-tested evidence favours the overcut: "
            "staying out longer performed better than stopping early."
        )

    if tyre_saving:
        recommendations.append(
            "Protect the tyres in the first stint; avoid unnecessary "
            "sliding, steering input and front-axle overload."
        )

    if tyre_change:
        recommendations.append(
            "A tyre change is required by the race rules."
        )

    if start_compound == "RM":
        recommendations.append(
            "Digit explicitly identifies Racing Medium as the normal "
            "starting compound."
        )

    if finish_compound == "RS":
        recommendations.append(
            "With RM/RS as the live available pair, an RM start implies "
            "RS for the second stint when complying with the required "
            "compound change."
        )

    if citroen:
        recommendations.append(
            "Digit identifies the GT by Citroën Gr.4 as particularly "
            "strong, including tyre performance."
        )

    return {
        "confidence": confidence,
        "preferred_logic": preferred_logic,
        "tyre_saving_supported": bool(tyre_saving),
        "tyre_change_supported": bool(tyre_change),
        "citroen_supported": bool(citroen),
        "start_compound": start_compound,
        "finish_compound": finish_compound,
        "finish_compound_basis": finish_compound_basis,
        "initial_pit_window": initial_window,
        "final_pit_logic": final_window,
        "recommendations": recommendations,
        "evidence": {
            "overcut": [evidence_label(x) for x in overcut],
            "tyre_saving": [evidence_label(x) for x in tyre_saving],
            "tyre_change": [evidence_label(x) for x in tyre_change],
            "compounds": [evidence_label(x) for x in compounds],
            "pit_window": [evidence_label(x) for x in pit_window],
            "start_medium": [evidence_label(x) for x in start_medium],
            "citroen": [evidence_label(x) for x in citroen],
        },
    }


# ============================================================================
# GNC LAP GUIDE ANALYSIS
# ============================================================================


def classify_lap_guide_unit(text: str) -> List[str]:
    labels: List[str] = []

    lower = normalize_key(text)

    if re.search(
        r"\bbrak(?:e|ing)\b|\bbrakes\b|\b200 board\b|\b100 board\b|\b350 m\b",
        lower,
    ):
        labels.append("BRAKING")

    if re.search(
        r"\bsecond gear\b|\bthird gear\b|\bshift(?:ing)?\b|\bdownshift\b|\bupshift\b",
        lower,
    ):
        labels.append("GEAR")

    if re.search(
        r"\baccelerat|\bthrottle\b|\bpower\b|\bfull throttle\b",
        lower,
    ):
        labels.append("THROTTLE")

    if re.search(
        r"\bline\b|\binside\b|\boutside\b|\bhug\b|\bturn in\b|\bdrift over\b",
        lower,
    ):
        labels.append("LINE")

    if re.search(
        r"\bcurb\b|\bkerb\b|\bwhite line\b|\btrack side\b|\bbollard\b",
        lower,
    ):
        labels.append("TRACK_LIMIT")

    return labels


def analyse_gnc_lap_guide(transcript: str) -> Dict[str, Any]:
    units = split_timestamped_units(transcript)

    selected = []

    for unit in units:
        labels = classify_lap_guide_unit(unit["text"])

        if not labels:
            continue

        selected.append(
            {
                "timestamp": unit["timestamp"],
                "text": unit["text"],
                "labels": labels,
            }
        )

    selected = unique_units(selected)

    braking = [
        x for x in selected
        if "BRAKING" in x["labels"]
    ]

    gears = [
        x for x in selected
        if "GEAR" in x["labels"]
    ]

    track_limits = [
        x for x in selected
        if "TRACK_LIMIT" in x["labels"]
    ]

    return {
        "confidence": "HIGH" if len(selected) >= 10 else "MEDIUM",
        "sequential_guide": selected[:30],
        "braking_references": braking[:20],
        "gear_references": gears[:12],
        "track_limit_references": track_limits[:12],
    }


# ============================================================================
# LIVE META
# ============================================================================


def extract_live_car_meta(snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    entries = snapshot.get("top5_used_cars", [])

    if not isinstance(entries, list):
        return []

    result = []

    for item in entries:
        if not isinstance(item, dict):
            continue

        car = normalize_space(item.get("car", ""))

        if not car:
            continue

        count = safe_int(item.get("count"))

        try:
            percentage = float(item.get("percentage"))
        except (TypeError, ValueError):
            percentage = None

        result.append(
            {
                "car": car,
                "count": count,
                "percentage": percentage,
                "layout": item.get("layout"),
            }
        )

    return result[:5]


# ============================================================================
# FINAL STRATEGY
# ============================================================================


def build_final_strategy(
    strategy: Dict[str, Any],
    live: Dict[str, Any],
    meta: List[Dict[str, Any]],
) -> Dict[str, Any]:

    meta_car = meta[0]["car"] if meta else None
    meta_share = meta[0]["percentage"] if meta else None

    start = strategy.get("start_compound")
    finish = strategy.get("finish_compound")

    if start and finish:
        compound_plan = f"{start} -> {finish}"
    elif start:
        compound_plan = f"Start {start}; second compound not fully established"
    else:
        compound_plan = "Not fully established"

    mandatory_change = strategy.get("tyre_change_supported", False)

    return {
        "confidence": strategy["confidence"],
        "strategy_type": strategy["preferred_logic"],
        "compound_plan": compound_plan,
        "start_compound": start,
        "finish_compound": finish,
        "required_tyre_change": mandatory_change,
        "initial_pit_window": strategy.get("initial_pit_window"),
        "race_tested_adjustment": strategy.get("final_pit_logic"),
        "tyre_management": (
            "Protect the first-stint tyres. Minimize sliding, unnecessary "
            "steering input and front-axle overload."
            if strategy.get("tyre_saving_supported")
            else "No explicit Digit tyre-management conclusion."
        ),
        "meta_car": meta_car,
        "meta_share_top1000": meta_share,
        "live_fuel_multiplier": live.get("fuel_multiplier"),
        "live_tyre_multiplier": live.get("tyre_multiplier"),
        "live_compounds": live.get("compounds", []),
        "decision_rule": (
            "Do not force the original lap 4-5 window. Extend the first "
            "stint when tyre condition, traffic and pace support the overcut."
            if strategy.get("preferred_logic")
            == "OVERCUT / EXTEND FIRST STINT"
            else "Use only the strategy explicitly supported by Digit."
        ),
    }


# ============================================================================
# REPORT WRITING
# ============================================================================


def fmt_bool_supported(value: bool) -> str:
    return "SUPPORTED BY DIGIT" if value else "not explicitly established"


def format_percentage(value: Any) -> str:
    if value is None:
        return "unknown"

    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return str(value)


def build_text_report(
    live: Dict[str, Any],
    sources: Dict[str, Dict[str, Any]],
    digit: Dict[str, Any],
    gnc: Dict[str, Any],
    meta: List[Dict[str, Any]],
    final_strategy: Dict[str, Any],
) -> str:

    lines: List[str] = []

    def add(text: str = "") -> None:
        lines.append(text)

    def rule(char: str = "-") -> None:
        add(char * LINE_WIDTH)

    rule("=")
    add(f"GT7 COMMUNITY INTELLIGENCE V{VERSION}")
    rule("=")

    add(f"Race week        : {live.get('week', 'unknown')}")
    add(f"Track            : {live.get('track', 'unknown')}")
    add(f"Class            : {live.get('class', 'unknown')}")
    add(f"Direction        : {live.get('direction', 'unknown')}")
    add(
        f"Fuel             : "
        f"x{live['fuel_multiplier']}"
        if live.get("fuel_multiplier") is not None
        else "Fuel             : unknown"
    )
    add(
        f"Tyre wear        : "
        f"x{live['tyre_multiplier']}"
        if live.get("tyre_multiplier") is not None
        else "Tyre wear        : unknown"
    )
    add(
        "Compounds        : "
        + (
            ", ".join(live.get("compounds", []))
            if live.get("compounds")
            else "unknown"
        )
    )

    add()
    add("SOURCE POLICY")
    rule()
    add("Race strategy    : Digit Racing only")
    add("Qualifying guide : GnC Racing only")
    add("Race regulations : live GT7/GTSH snapshot")
    add("Car meta         : live leaderboard")

    # ------------------------------------------------------------------
    # FINAL OPERATIONAL STRATEGY
    # ------------------------------------------------------------------

    add()
    rule("=")
    add("FINAL RACE STRATEGY")
    rule("=")

    add(
        f"Confidence       : "
        f"{final_strategy.get('confidence', 'unknown')}"
    )
    add(
        f"Strategy         : "
        f"{final_strategy.get('strategy_type', 'unknown')}"
    )
    add(
        f"Compound plan    : "
        f"{final_strategy.get('compound_plan', 'unknown')}"
    )

    if final_strategy.get("required_tyre_change"):
        add("Tyre change      : REQUIRED")
    else:
        add("Tyre change      : not established")

    add(
        f"Initial window   : "
        f"{final_strategy.get('initial_pit_window') or 'not established'}"
    )
    add(
        f"Race-tested call : "
        f"{final_strategy.get('race_tested_adjustment') or 'not established'}"
    )
    add(
        f"Tyre management  : "
        f"{final_strategy.get('tyre_management')}"
    )

    meta_car = final_strategy.get("meta_car")

    if meta_car:
        add(
            f"Meta car         : {meta_car} | "
            f"{format_percentage(final_strategy.get('meta_share_top1000'))} "
            f"of Top 1000"
        )
    else:
        add("Meta car         : unknown")

    add()
    add("DECISION RULE")
    rule()
    add(final_strategy.get("decision_rule", ""))

    # ------------------------------------------------------------------
    # DIGIT
    # ------------------------------------------------------------------

    add()
    add("RACE STRATEGY — DIGIT RACING")
    rule()

    add(f"Confidence       : {digit['confidence']}")
    add(f"Preferred logic  : {digit['preferred_logic']}")
    add(
        f"Tyre saving      : "
        f"{fmt_bool_supported(digit['tyre_saving_supported'])}"
    )
    add(
        f"Tyre change      : "
        f"{fmt_bool_supported(digit['tyre_change_supported'])}"
    )
    add(
        f"Citroën          : "
        f"{fmt_bool_supported(digit['citroen_supported'])}"
    )

    if digit.get("start_compound"):
        add(f"Start compound   : {digit['start_compound']}")

    if digit.get("finish_compound"):
        add(f"Finish compound  : {digit['finish_compound']}")

    add()

    for index, rec in enumerate(digit["recommendations"], start=1):
        add(f"{index}. {rec}")

    add()
    add("STRATEGY EVIDENCE")
    rule()

    evidence_groups = [
        ("Overcut / stay out", "overcut"),
        ("Tyre saving", "tyre_saving"),
        ("Tyre change", "tyre_change"),
        ("Compounds", "compounds"),
        ("Pit-window discussion", "pit_window"),
        ("Starting compound", "start_medium"),
        ("Citroën / meta", "citroen"),
    ]

    for title, key in evidence_groups:
        values = digit["evidence"].get(key, [])

        if not values:
            continue

        add()
        add(f"{title}:")

        for item in values[:12]:
            add(f"  - {item}")

    # ------------------------------------------------------------------
    # GNC
    # ------------------------------------------------------------------

    add()
    add("QUALIFYING / FAST LAP — GNC RACING")
    rule()
    add(f"Confidence       : {gnc['confidence']}")

    for index, item in enumerate(
        gnc["sequential_guide"],
        start=1,
    ):
        labels = "/".join(item["labels"])
        prefix = (
            f"[{item['timestamp']}] "
            if item.get("timestamp")
            else ""
        )

        add(
            f"{index:2d}. [{labels}] "
            f"{prefix}{item['text']}"
        )

    add()
    add("BRAKING REFERENCES — GNC")
    rule()

    for item in gnc["braking_references"]:
        prefix = (
            f"[{item['timestamp']}] "
            if item.get("timestamp")
            else ""
        )
        add(f"- {prefix}{item['text']}")

    add()
    add("GEARS / SHIFTING — GNC")
    rule()

    for item in gnc["gear_references"]:
        prefix = (
            f"[{item['timestamp']}] "
            if item.get("timestamp")
            else ""
        )
        add(f"- {prefix}{item['text']}")

    add()
    add("TRACK LIMITS / KERBS — GNC")
    rule()

    for item in gnc["track_limit_references"]:
        prefix = (
            f"[{item['timestamp']}] "
            if item.get("timestamp")
            else ""
        )
        add(f"- {prefix}{item['text']}")

    # ------------------------------------------------------------------
    # META
    # ------------------------------------------------------------------

    add()
    add("LIVE CAR META — TOP 1000")
    rule()

    if not meta:
        add("No live car meta available.")
    else:
        for index, item in enumerate(meta, start=1):
            add(
                f"{index:2d}. {item['car']} | "
                f"{item.get('count', 'unknown')} drivers | "
                f"{format_percentage(item.get('percentage'))}"
            )

    # ------------------------------------------------------------------
    # PRACTICAL PLAN
    # ------------------------------------------------------------------

    add()
    add("PRACTICAL RACE PLAN")
    rule()

    practical = [
        "Use the official/live race configuration as the regulatory baseline.",
        (
            "Start on Racing Medium when following Digit's stated base plan, "
            "then use Racing Soft for the second stint under the live RM/RS "
            "compound rule."
            if final_strategy.get("start_compound") == "RM"
            and final_strategy.get("finish_compound") == "RS"
            else
            "Use only the compound sequence explicitly supported by the "
            "available Digit evidence and live regulations."
        ),
        (
            "Do not treat laps 4-5 as a rigid pit window. Digit's later "
            "race-tested conclusion favours staying out longer and using "
            "the overcut rather than stopping early."
            if digit["preferred_logic"]
            == "OVERCUT / EXTEND FIRST STINT"
            else
            "No later race-tested pit-window override was identified."
        ),
        (
            "Protect the tyres during the first stint; excessive steering, "
            "sliding and front-tyre overload reduce the benefit of the "
            "overcut."
            if digit["tyre_saving_supported"]
            else
            "No explicit tyre-preservation recommendation was established."
        ),
        (
            f"The {meta[0]['car']} is the live leaderboard meta leader"
            + (
                f" at {format_percentage(meta[0].get('percentage'))} "
                f"of the Top 1000."
            )
            if meta
            else
            "No live meta leader is available."
        ),
        (
            "Use the GnC guide exclusively for braking references, gears, "
            "racing line and throttle technique."
        ),
    ]

    for index, item in enumerate(practical, start=1):
        add(f"{index}. {item}")

    add()
    add("ANALYSIS POLICY")
    rule()
    add("1. Digit Racing is the sole community source for race strategy.")
    add("2. GnC Racing is the sole community source for qualifying/lap guidance.")
    add("3. Live GT7/GTSH data overrides any conflicting community statement.")
    add(
        "4. Later race-tested Digit conclusions override earlier speculative "
        "strategy comments."
    )
    add("5. Live leaderboard usage is authoritative for current car meta.")
    add(
        "6. Snapshot Top-1000 car percentages are used directly and are "
        "never renormalized."
    )
    add(
        "7. Transcript evidence is never used to invent missing braking "
        "points, gears or strategy."
    )
    add(
        "8. RM -> RS is reported only when Digit explicitly supports an RM "
        "start, live data confirms RM/RS and the required tyre change is "
        "supported."
    )

    return "\n".join(lines)


# ============================================================================
# MAIN
# ============================================================================


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print_header(f"GT7 COMMUNITY ANALYZER V{VERSION}")

    snapshot_path, snapshot = discover_snapshot()
    sources = load_transcript_sources()

    digit_source = sources.get(STRATEGY_CHANNEL)
    gnc_source = sources.get(LAP_GUIDE_CHANNEL)

    print(
        f"Digit transcript : "
        f"{'FOUND' if digit_source else 'NOT FOUND'}"
    )
    print(
        f"GnC transcript   : "
        f"{'FOUND' if gnc_source else 'NOT FOUND'}"
    )

    if digit_source:
        print(
            f"Digit characters : "
            f"{digit_source['characters']:,}"
        )

    if gnc_source:
        print(
            f"GnC characters   : "
            f"{gnc_source['characters']:,}"
        )

    if not digit_source:
        raise RuntimeError(
            "Digit Racing transcript not found in "
            "data/community_transcripts/."
        )

    if not gnc_source:
        raise RuntimeError(
            "GnC Racing transcript not found in "
            "data/community_transcripts/."
        )

    live = extract_live_configuration(snapshot)

    print()
    print("LIVE CONFIGURATION")
    print_rule()

    print(f"Week             : {live['week']}")
    print(f"Track            : {live['track']}")
    print(f"Class            : {live['class']}")
    print(f"Direction        : {live['direction']}")

    if live["fuel_multiplier"] is not None:
        print(f"Fuel             : x{live['fuel_multiplier']}")
    else:
        print("Fuel             : unknown")

    if live["tyre_multiplier"] is not None:
        print(f"Tyre wear        : x{live['tyre_multiplier']}")
    else:
        print("Tyre wear        : unknown")

    print(
        "Compounds        : "
        + (
            ", ".join(live["compounds"])
            if live["compounds"]
            else "unknown"
        )
    )

    digit_analysis = analyse_digit_strategy(
        digit_source["text"],
        live,
    )

    gnc_analysis = analyse_gnc_lap_guide(
        gnc_source["text"],
    )

    meta = extract_live_car_meta(snapshot)

    final_strategy = build_final_strategy(
        digit_analysis,
        live,
        meta,
    )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "version": VERSION,
        "snapshot_file": str(snapshot_path.relative_to(ROOT)),
        "live_configuration": live,
        "source_policy": {
            "race_strategy": "Digit Racing only",
            "qualifying_guide": "GnC Racing only",
            "race_regulations": "live GT7/GTSH snapshot",
            "car_meta": "live leaderboard",
        },
        "sources": {
            "strategy": {
                "channel": STRATEGY_CHANNEL,
                "title": digit_source["title"],
                "video_id": digit_source["video_id"],
                "file": digit_source["path"],
                "words": digit_source["words"],
                "characters": digit_source["characters"],
            },
            "lap_guide": {
                "channel": LAP_GUIDE_CHANNEL,
                "title": gnc_source["title"],
                "video_id": gnc_source["video_id"],
                "file": gnc_source["path"],
                "words": gnc_source["words"],
                "characters": gnc_source["characters"],
            },
        },
        "final_race_strategy": final_strategy,
        "digit_strategy": digit_analysis,
        "gnc_lap_guide": gnc_analysis,
        "live_car_meta_top1000": meta,
    }

    text_report = build_text_report(
        live=live,
        sources=sources,
        digit=digit_analysis,
        gnc=gnc_analysis,
        meta=meta,
        final_strategy=final_strategy,
    )

    save_json(OUTPUT_JSON, report)

    with OUTPUT_TEXT.open("w", encoding="utf-8") as f:
        f.write(text_report)
        f.write("\n")

    print()
    print(text_report)

    print()
    print_header("COMMUNITY INTELLIGENCE COMPLETE")
    print(f"Snapshot         : {snapshot_path.relative_to(ROOT)}")
    print(f"JSON report      : {OUTPUT_JSON.relative_to(ROOT)}")
    print(f"Text report      : {OUTPUT_TEXT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()