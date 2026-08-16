from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable


# ======================================================================================
# GT7 COMMUNITY ANALYZER V5.2
# ======================================================================================
#
# SOURCE POLICY
#
# Race regulations:
#   data/latest_snapshot.json
#
# Race strategy:
#   Digit Racing ONLY
#
# Qualifying / lap guide:
#   GnC Racing ONLY
#
# Live car meta:
#   latest_snapshot.json
#
# Important:
#   - structured snapshot data always overrides transcript/community data
#   - percentages from top5_used_cars are used exactly as stored in the snapshot
#   - rejected/stale community sources are not mixed into recommendations
#
# ======================================================================================


VERSION = "5.2"

DATA_DIR = Path("data")

SNAPSHOT_FILE = DATA_DIR / "latest_snapshot.json"
TRANSCRIPT_DB_FILE = DATA_DIR / "community_transcripts.json"
TRANSCRIPT_DIR = DATA_DIR / "community_transcripts"

OUTPUT_DIR = DATA_DIR / "community_intelligence"
OUTPUT_JSON = OUTPUT_DIR / "community_intelligence.json"
OUTPUT_TEXT = OUTPUT_DIR / "community_intelligence.txt"

LINE_WIDTH = 100


# ======================================================================================
# BASIC HELPERS
# ======================================================================================


def line(char: str = "=") -> str:
    return char * LINE_WIDTH


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_for_search(text: str) -> str:
    text = normalize_spaces(text).lower()

    replacements = {
        "citroën": "citroen",
        "tyres": "tires",
        "tyre": "tire",
        "braking": "brake",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    return text


def format_multiplier(value: Any) -> str:
    ivalue = safe_int(value)
    if ivalue is None:
        return "unknown"
    return f"x{ivalue}"


def unique_preserve_order(items: Iterable[str]) -> list[str]:
    seen = set()
    result = []

    for item in items:
        key = normalize_spaces(item)

        if not key:
            continue

        if key in seen:
            continue

        seen.add(key)
        result.append(key)

    return result


# ======================================================================================
# RECURSIVE JSON HELPERS
# ======================================================================================


def recursive_strings(value: Any) -> list[str]:
    result: list[str] = []

    if isinstance(value, str):
        text = value.strip()
        if text:
            result.append(text)

    elif isinstance(value, dict):
        for child in value.values():
            result.extend(recursive_strings(child))

    elif isinstance(value, list):
        for child in value:
            result.extend(recursive_strings(child))

    return result


def recursive_find_key(value: Any, key_names: set[str]) -> Any:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in key_names:
                return child

        for child in value.values():
            found = recursive_find_key(child, key_names)
            if found is not None:
                return found

    elif isinstance(value, list):
        for child in value:
            found = recursive_find_key(child, key_names)
            if found is not None:
                return found

    return None


# ======================================================================================
# SNAPSHOT / LIVE CONFIGURATION
# ======================================================================================


def extract_track_from_description(description: str) -> str:
    """
    Example:
    C Gr.4 Running 10 Aug 2026 Daily Race C i 16:48
    Grand Valley - Highway 1
    M. Estevez - GT by Citroën Gr.4 RM RS ...
    """

    if not description:
        return "unknown"

    # First try: explicit known pattern between time and driver/car area.
    match = re.search(
        r"\b\d{1,2}:\d{2}\s+(.+?)\s+"
        r"(?:[A-ZÀ-ÿ]\.\s*[A-ZÀ-ÿ][A-Za-zÀ-ÿ' -]+)\s*-\s*"
        r".+?\bGr\.\d\b",
        description,
        re.IGNORECASE,
    )

    if match:
        track = normalize_spaces(match.group(1))
        if track:
            return track

    # More tolerant fallback.
    match = re.search(
        r"Daily Race C.*?\b\d{1,2}:\d{2}\s+(.+?)\s+"
        r"[A-ZÀ-ÿ]\.\s*[A-Za-zÀ-ÿ' -]+\s*-\s*",
        description,
        re.IGNORECASE,
    )

    if match:
        track = normalize_spaces(match.group(1))
        if track:
            return track

    # Last-resort special handling for current known GT7 naming form.
    track_patterns = [
        r"(Grand Valley\s*-\s*Highway 1)",
        r"(Grand Valley Highway 1)",
        r"(Grand Valley\s*-\s*Highway 1 Reverse)",
        r"(Grand Valley Highway 1 Reverse)",
    ]

    for pattern in track_patterns:
        match = re.search(pattern, description, re.IGNORECASE)
        if match:
            return normalize_spaces(match.group(1))

    return "unknown"


def extract_class_from_description(description: str) -> str:
    if not description:
        return "unknown"

    match = re.search(r"\bGr\.\s*(\d)\b", description, re.IGNORECASE)

    if match:
        return f"Gr.{match.group(1)}"

    return "unknown"


def extract_direction_from_description(description: str) -> str:
    if not description:
        return "unknown"

    text = description.lower()

    if "reverse" in text:
        return "REVERSE"

    # GT7/GTSH descriptions normally omit "Normal".
    # Therefore absence of Reverse means standard/normal direction.
    return "NORMAL"


def extract_live_config(snapshot: dict[str, Any]) -> dict[str, Any]:
    race = snapshot.get("race") or {}

    if not isinstance(race, dict):
        race = {}

    description = normalize_spaces(str(race.get("description") or ""))

    track = race.get("track")
    race_class = race.get("class")
    direction = race.get("direction")

    if not track:
        track = extract_track_from_description(description)

    if not race_class:
        race_class = extract_class_from_description(description)

    if not direction:
        direction = extract_direction_from_description(description)

    compounds = race.get("compounds")

    if not isinstance(compounds, list):
        compounds = []

    compounds = [str(x).strip() for x in compounds if str(x).strip()]

    start_date = race.get("start_date")

    return {
        "week": start_date or "unknown",
        "track": track or "unknown",
        "class": race_class or "unknown",
        "direction": direction or "unknown",
        "fuel_multiplier": safe_int(race.get("fuel_multiplier")),
        "tyre_multiplier": safe_int(race.get("tyre_multiplier")),
        "compounds": compounds,
        "description": description,
        "leaderboard_url": race.get("leaderboard_url"),
        "detection_mode": race.get("detection_mode"),
        "source_mode": race.get("source_mode"),
    }


# ======================================================================================
# TRANSCRIPT LOADING
# ======================================================================================


def transcript_channel(blob: dict[str, Any]) -> str:
    strings = recursive_strings(blob)
    joined = " ".join(strings).lower()

    if "digit racing" in joined:
        return "Digit Racing"

    if "gnc racing" in joined:
        return "GnC Racing"

    if "wombleleader" in joined:
        return "Wombleleader Racing"

    return "unknown"


def transcript_role(blob: dict[str, Any]) -> str:
    possible = recursive_find_key(
        blob,
        {
            "role",
            "source_role",
            "selected_role",
            "purpose",
        },
    )

    if isinstance(possible, str):
        return possible.upper()

    return ""


def transcript_text(blob: dict[str, Any]) -> str:
    preferred_keys = {
        "transcript",
        "text",
        "content",
        "selected_text",
        "extracted_text",
        "strategy_text",
    }

    value = recursive_find_key(blob, preferred_keys)

    if isinstance(value, str) and len(value.strip()) >= 100:
        return value.strip()

    if isinstance(value, list):
        strings = recursive_strings(value)
        joined = "\n".join(strings)
        if len(joined.strip()) >= 100:
            return joined.strip()

    strings = recursive_strings(blob)

    candidates = [
        text
        for text in strings
        if len(text) >= 100
    ]

    if not candidates:
        return ""

    # Usually the transcript is the longest textual value.
    return max(candidates, key=len)


def load_transcript_files() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    if TRANSCRIPT_DIR.exists():
        for path in sorted(TRANSCRIPT_DIR.glob("*.json")):
            try:
                blob = load_json(path)

                if not isinstance(blob, dict):
                    continue

                records.append(
                    {
                        "path": path,
                        "blob": blob,
                        "channel": transcript_channel(blob),
                        "role": transcript_role(blob),
                        "text": transcript_text(blob),
                    }
                )

            except Exception as exc:
                print(f"WARNING: could not read transcript {path}: {exc}")

    return records


def select_transcript(
    records: list[dict[str, Any]],
    channel_name: str,
) -> dict[str, Any] | None:

    candidates = [
        record
        for record in records
        if record["channel"].lower() == channel_name.lower()
        and record["text"]
    ]

    if not candidates:
        return None

    # Prefer the largest useful transcript for that selected channel.
    candidates.sort(
        key=lambda x: len(x.get("text", "")),
        reverse=True,
    )

    return candidates[0]


# ======================================================================================
# TRANSCRIPT SENTENCE / TIMESTAMP PROCESSING
# ======================================================================================


TIMESTAMP_PATTERN = re.compile(
    r"(\[(?:\d+:)?\d{1,2}:\d{2}\])"
)


def split_transcript_units(text: str) -> list[str]:
    """
    Keep timestamp blocks reasonably intact.
    """

    if not text:
        return []

    text = text.replace("\r", "\n")

    # Break at timestamps.
    text = TIMESTAMP_PATTERN.sub(r"\n\1 ", text)

    chunks = []

    for raw in text.splitlines():
        raw = normalize_spaces(raw)

        if not raw:
            continue

        if len(raw) > 700:
            sentences = re.split(
                r"(?<=[.!?])\s+(?=[A-Z0-9\[])",
                raw,
            )

            for sentence in sentences:
                sentence = normalize_spaces(sentence)

                if sentence:
                    chunks.append(sentence)

        else:
            chunks.append(raw)

    return chunks


def find_units(
    units: list[str],
    terms: list[str],
    limit: int = 20,
) -> list[str]:

    found = []

    for unit in units:
        normalized = normalize_for_search(unit)

        if any(term in normalized for term in terms):
            found.append(unit)

        if len(found) >= limit:
            break

    return unique_preserve_order(found)


# ======================================================================================
# DIGIT RACING STRATEGY
# ======================================================================================


def digit_strategy_analysis(text: str) -> dict[str, Any]:
    units = split_transcript_units(text)

    overcut = find_units(
        units,
        [
            "overcut",
            "stayed out",
            "stay out",
            "staying out",
            "pitted earlier",
            "pit later",
        ],
        limit=12,
    )

    tyre_saving = find_units(
        units,
        [
            "save the tire",
            "save the tires",
            "saving tire",
            "saving tires",
            "tire saving",
            "gentle with my tires",
            "tire wear",
        ],
        limit=12,
    )

    tyre_change = find_units(
        units,
        [
            "required tire change",
            "tire change",
            "change the tires",
            "change the tire",
            "mandatory",
        ],
        limit=12,
    )

    compounds = find_units(
        units,
        [
            "racing mediums",
            "racing medium",
            "racing soft",
            "soft tires",
            "mediums and soft",
        ],
        limit=8,
    )

    citroen = find_units(
        units,
        [
            "citroen",
            "citroën",
        ],
        limit=12,
    )

    pit_window = find_units(
        units,
        [
            "lap four",
            "lap five",
            "lap 4",
            "lap 5",
            "pit window",
        ],
        limit=10,
    )

    normalized_all = normalize_for_search(text)

    later_overcut = (
        "overcut it is" in normalized_all
        or "overcut is more" in normalized_all
        or "should have stayed out" in normalized_all
        or "pitted earlier just lost more time" in normalized_all
    )

    citroen_supported = "citroen" in normalized_all

    tyre_change_supported = any(
        phrase in normalized_all
        for phrase in [
            "required tire change",
            "required tyre change",
            "change the tires",
            "change the tyres",
        ]
    )

    tyre_saving_supported = any(
        phrase in normalized_all
        for phrase in [
            "tire saving",
            "tyre saving",
            "save the tires",
            "save the tyres",
            "gentle with my tires",
            "gentle with my tyres",
        ]
    )

    if later_overcut:
        preferred_logic = "OVERCUT / EXTEND FIRST STINT"
        confidence = "HIGH"
    elif pit_window:
        preferred_logic = "PIT WINDOW DISCUSSED"
        confidence = "MEDIUM"
    else:
        preferred_logic = "NO STRONG STRATEGY CONCLUSION"
        confidence = "LOW"

    recommendations: list[str] = []

    if later_overcut:
        recommendations.append(
            "The later race-tested evidence favours the overcut: "
            "staying out longer performed better than stopping early."
        )

    if tyre_saving_supported:
        recommendations.append(
            "Tyre preservation is strategically important; avoid unnecessary "
            "sliding and steering input during the first stint."
        )

    if tyre_change_supported:
        recommendations.append(
            "Digit confirms that the race requires use of the tyre-change rule."
        )

    if citroen_supported:
        recommendations.append(
            "Digit identifies the GT by Citroën Gr.4 as particularly strong "
            "for this race, including tyre performance."
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


# ======================================================================================
# GNC FAST-LAP GUIDE
# ======================================================================================


def classify_gnc_unit(unit: str) -> list[str]:
    text = normalize_for_search(unit)

    categories = []

    if any(
        x in text
        for x in [
            "brake",
            "braking",
            "100 board",
            "200 board",
            "350 m",
        ]
    ):
        categories.append("BRAKING")

    if any(
        x in text
        for x in [
            "second gear",
            "third gear",
            "fourth gear",
            "shift",
            "shifting",
        ]
    ):
        categories.append("GEAR")

    if any(
        x in text
        for x in [
            "accelerate",
            "throttle",
            "power",
            "full throttle",
        ]
    ):
        categories.append("THROTTLE")

    if any(
        x in text
        for x in [
            "curb",
            "kerb",
            "white line",
            "track side",
            "bollard",
        ]
    ):
        categories.append("TRACK_LIMIT")

    if any(
        x in text
        for x in [
            "inside line",
            "tight line",
            "left side",
            "right side",
            "turn in",
            "apex",
        ]
    ):
        categories.append("LINE")

    return categories


def gnc_lap_analysis(text: str) -> dict[str, Any]:
    units = split_transcript_units(text)

    useful: list[dict[str, Any]] = []

    for unit in units:
        categories = classify_gnc_unit(unit)

        if not categories:
            continue

        # Ignore tiny fragments.
        if len(unit) < 35:
            continue

        useful.append(
            {
                "categories": categories,
                "text": unit,
            }
        )

    # Preserve transcript order.
    useful = useful[:24]

    braking = []
    gears = []
    limits = []

    for item in useful:
        categories = item["categories"]
        text_item = item["text"]

        if "BRAKING" in categories:
            braking.append(text_item)

        if "GEAR" in categories:
            gears.append(text_item)

        if "TRACK_LIMIT" in categories:
            limits.append(text_item)

    return {
        "confidence": "HIGH" if useful else "LOW",
        "guide": useful,
        "braking": unique_preserve_order(braking),
        "gears": unique_preserve_order(gears),
        "track_limits": unique_preserve_order(limits),
    }


# ======================================================================================
# LIVE LEADERBOARD META
# ======================================================================================


def build_live_meta(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """
    IMPORTANT V5.2 FIX

    Do NOT recompute / renormalize percentages.

    Snapshot percentage is already relative to Top 1000.
    """

    raw = snapshot.get("top5_used_cars")

    if not isinstance(raw, list):
        return []

    result = []

    for row in raw:
        if not isinstance(row, dict):
            continue

        result.append(
            {
                "car_code": row.get("car_code"),
                "car": row.get("car") or "unknown",
                "count": safe_int(row.get("count")) or 0,
                "percentage": safe_float(row.get("percentage")),
                "layout": row.get("layout"),
                "qualifying_range": row.get("qualifying_range"),
                "race_range": row.get("race_range"),
                "qualifying_start": row.get("qualifying_start"),
                "race_start": row.get("race_start"),
                "confidence": row.get("confidence"),
                "reason": row.get("reason"),
                "wear_adjustment": row.get("wear_adjustment"),
            }
        )

    return result


# ======================================================================================
# PRACTICAL PLAN
# ======================================================================================


def build_practical_plan(
    live: dict[str, Any],
    strategy: dict[str, Any],
    meta: list[dict[str, Any]],
) -> list[str]:

    plan = [
        "Use the official/live race configuration as the regulatory baseline."
    ]

    if strategy.get("preferred_logic") == "OVERCUT / EXTEND FIRST STINT":
        plan.append(
            "Do not treat laps 4-5 as a rigid pit window. "
            "Digit's later race-tested conclusion favours staying out longer "
            "and using the overcut rather than stopping early."
        )

    if strategy.get("tyre_saving_supported"):
        plan.append(
            "Protect the tyres during the first stint; excessive steering, "
            "sliding and front-tyre overload reduce the benefit of the overcut."
        )

    if strategy.get("citroen_supported"):
        if meta and normalize_for_search(meta[0]["car"]).startswith(
            "gt by citroen"
        ):
            plan.append(
                "The GT by Citroën Gr.4 is supported independently by both "
                "Digit's race experience and the live leaderboard meta."
            )
        else:
            plan.append(
                "Digit supports the GT by Citroën Gr.4; verify that recommendation "
                "against the live leaderboard before changing car."
            )

    plan.append(
        "Use the GnC guide for braking references, gears, racing line and throttle "
        "technique; do not mix lap instructions from other community sources."
    )

    return plan


# ======================================================================================
# REPORT BUILDERS
# ======================================================================================


def build_report_json(
    snapshot: dict[str, Any],
    live: dict[str, Any],
    digit_record: dict[str, Any] | None,
    gnc_record: dict[str, Any] | None,
    strategy: dict[str, Any],
    lap: dict[str, Any],
    meta: list[dict[str, Any]],
) -> dict[str, Any]:

    practical_plan = build_practical_plan(
        live,
        strategy,
        meta,
    )

    return {
        "analyzer_version": VERSION,
        "race": live,
        "sources": {
            "strategy": {
                "channel": "Digit Racing",
                "available": digit_record is not None,
                "file": (
                    str(digit_record["path"])
                    if digit_record
                    else None
                ),
            },
            "lap_guide": {
                "channel": "GnC Racing",
                "available": gnc_record is not None,
                "file": (
                    str(gnc_record["path"])
                    if gnc_record
                    else None
                ),
            },
        },
        "strategy": strategy,
        "qualifying_lap_guide": lap,
        "live_car_meta": meta,
        "world_record": snapshot.get("world_record"),
        "my_result": snapshot.get("my_result"),
        "next_targets": snapshot.get("next_targets"),
        "same_car_stats": snapshot.get("same_car_stats"),
        "country_stats": snapshot.get("country_stats"),
        "dr_stats": snapshot.get("dr_stats"),
        "car_comparison": snapshot.get("car_comparison"),
        "overperformance": snapshot.get("overperformance"),
        "forecast_v2": snapshot.get("forecast_v2"),
        "practical_race_plan": practical_plan,
        "policy": [
            "Digit Racing is the sole community source for race strategy.",
            "GnC Racing is the sole community source for qualifying/lap guidance.",
            "Live GT7/GTSH data overrides any conflicting community statement.",
            "Later race-tested Digit conclusions override earlier speculative strategy comments.",
            "Live leaderboard usage is authoritative for current car meta.",
            "Percentages stored in top5_used_cars are not renormalized.",
            "Transcript evidence is never used to invent missing braking points, gears or strategy.",
        ],
    }


def build_text_report(
    live: dict[str, Any],
    strategy: dict[str, Any],
    lap: dict[str, Any],
    meta: list[dict[str, Any]],
    practical_plan: list[str],
) -> str:

    out: list[str] = []

    out.append(line("="))
    out.append(f"GT7 COMMUNITY INTELLIGENCE V{VERSION}")
    out.append(line("="))

    out.append(f"Race week        : {live['week']}")
    out.append(f"Track            : {live['track']}")
    out.append(f"Class            : {live['class']}")
    out.append(f"Direction        : {live['direction']}")
    out.append(
        f"Fuel             : {format_multiplier(live['fuel_multiplier'])}"
    )
    out.append(
        f"Tyre wear        : {format_multiplier(live['tyre_multiplier'])}"
    )
    out.append(
        f"Compounds        : {', '.join(live['compounds']) or 'unknown'}"
    )
    out.append("")

    out.append("SOURCE POLICY")
    out.append(line("-"))
    out.append("Race strategy    : Digit Racing only")
    out.append("Qualifying guide : GnC Racing only")
    out.append("Race regulations : live GT7/GTSH snapshot")
    out.append("Car meta         : live leaderboard")
    out.append("")

    out.append("RACE STRATEGY — DIGIT RACING")
    out.append(line("-"))
    out.append(
        f"Confidence       : {strategy.get('confidence', 'LOW')}"
    )
    out.append(
        f"Preferred logic  : "
        f"{strategy.get('preferred_logic', 'UNKNOWN')}"
    )
    out.append(
        "Tyre saving      : "
        + (
            "SUPPORTED BY DIGIT"
            if strategy.get("tyre_saving_supported")
            else "not explicitly established"
        )
    )
    out.append(
        "Tyre change      : "
        + (
            "SUPPORTED BY DIGIT"
            if strategy.get("tyre_change_supported")
            else "not established from Digit transcript"
        )
    )
    out.append(
        "Citroën          : "
        + (
            "SUPPORTED BY DIGIT"
            if strategy.get("citroen_supported")
            else "not established from Digit transcript"
        )
    )
    out.append("")

    recommendations = strategy.get("recommendations", [])

    for i, item in enumerate(recommendations, 1):
        out.append(f"{i}. {item}")

    out.append("")
    out.append("STRATEGY EVIDENCE")
    out.append(line("-"))

    evidence = strategy.get("evidence", {})

    evidence_sections = [
        ("Overcut / stay out", "overcut"),
        ("Tyre saving", "tyre_saving"),
        ("Tyre change", "tyre_change"),
        ("Compounds", "compounds"),
        ("Citroën / meta", "citroen"),
        ("Pit-window discussion", "pit_window"),
    ]

    for title, key in evidence_sections:
        items = evidence.get(key, [])

        if not items:
            continue

        out.append("")
        out.append(f"{title}:")

        for item in items:
            out.append(f"  - {item}")

    out.append("")
    out.append("QUALIFYING / FAST LAP — GNC RACING")
    out.append(line("-"))
    out.append(
        f"Confidence       : {lap.get('confidence', 'LOW')}"
    )

    for i, item in enumerate(lap.get("guide", []), 1):
        categories = "/".join(item["categories"])
        out.append(
            f"{i:2d}. [{categories}] {item['text']}"
        )

    out.append("")
    out.append("BRAKING REFERENCES — GNC")
    out.append(line("-"))

    for item in lap.get("braking", []):
        out.append(f"- {item}")

    out.append("")
    out.append("GEARS / SHIFTING — GNC")
    out.append(line("-"))

    for item in lap.get("gears", []):
        out.append(f"- {item}")

    out.append("")
    out.append("TRACK LIMITS / KERBS — GNC")
    out.append(line("-"))

    for item in lap.get("track_limits", []):
        out.append(f"- {item}")

    out.append("")
    out.append("LIVE CAR META — TOP 1000")
    out.append(line("-"))

    if meta:
        for i, car in enumerate(meta, 1):
            percentage = car.get("percentage")

            if percentage is None:
                pct_text = "unknown"
            else:
                pct_text = f"{percentage:.1f}%"

            out.append(
                f"{i:2d}. {car['car']} | "
                f"{car['count']} drivers | "
                f"{pct_text}"
            )
    else:
        out.append("No live car-meta data available.")

    out.append("")
    out.append("PRACTICAL RACE PLAN")
    out.append(line("-"))

    for i, item in enumerate(practical_plan, 1):
        out.append(f"{i}. {item}")

    out.append("")
    out.append("ANALYSIS POLICY")
    out.append(line("-"))
    out.append(
        "1. Digit Racing is the sole community source for race strategy."
    )
    out.append(
        "2. GnC Racing is the sole community source for qualifying/lap guidance."
    )
    out.append(
        "3. Live GT7/GTSH data overrides any conflicting community statement."
    )
    out.append(
        "4. Later race-tested Digit conclusions override earlier speculative strategy comments."
    )
    out.append(
        "5. Live leaderboard usage is authoritative for current car meta."
    )
    out.append(
        "6. Snapshot Top-1000 car percentages are used directly and are never renormalized."
    )
    out.append(
        "7. Transcript evidence is never used to invent missing braking points, gears or strategy."
    )

    out.append("")
    out.append(line("="))

    return "\n".join(out)


# ======================================================================================
# MAIN
# ======================================================================================


def main() -> None:
    print(line("="))
    print(f"GT7 COMMUNITY ANALYZER V{VERSION}")
    print(line("="))

    if not SNAPSHOT_FILE.exists():
        raise FileNotFoundError(
            f"Required snapshot not found: {SNAPSHOT_FILE}"
        )

    snapshot = load_json(SNAPSHOT_FILE)

    if not isinstance(snapshot, dict):
        raise ValueError(
            "latest_snapshot.json does not contain a JSON object."
        )

    live = extract_live_config(snapshot)

    transcript_records = load_transcript_files()

    digit_record = select_transcript(
        transcript_records,
        "Digit Racing",
    )

    gnc_record = select_transcript(
        transcript_records,
        "GnC Racing",
    )

    digit_text = digit_record["text"] if digit_record else ""
    gnc_text = gnc_record["text"] if gnc_record else ""

    print(
        f"Digit transcript : "
        f"{'FOUND' if digit_record else 'NOT FOUND'}"
    )
    print(
        f"GnC transcript   : "
        f"{'FOUND' if gnc_record else 'NOT FOUND'}"
    )
    print(
        f"Digit characters : {len(digit_text):,}"
    )
    print(
        f"GnC characters   : {len(gnc_text):,}"
    )

    print()
    print("LIVE CONFIGURATION")
    print(line("-"))
    print(f"Week             : {live['week']}")
    print(f"Track            : {live['track']}")
    print(f"Class            : {live['class']}")
    print(f"Direction        : {live['direction']}")
    print(
        f"Fuel             : "
        f"{format_multiplier(live['fuel_multiplier'])}"
    )
    print(
        f"Tyre wear        : "
        f"{format_multiplier(live['tyre_multiplier'])}"
    )
    print(
        f"Compounds        : "
        f"{', '.join(live['compounds']) or 'unknown'}"
    )

    strategy = (
        digit_strategy_analysis(digit_text)
        if digit_text
        else {
            "confidence": "LOW",
            "preferred_logic": "NO DIGIT TRANSCRIPT",
            "tyre_saving_supported": False,
            "tyre_change_supported": False,
            "citroen_supported": False,
            "recommendations": [],
            "evidence": {},
        }
    )

    lap = (
        gnc_lap_analysis(gnc_text)
        if gnc_text
        else {
            "confidence": "LOW",
            "guide": [],
            "braking": [],
            "gears": [],
            "track_limits": [],
        }
    )

    meta = build_live_meta(snapshot)

    practical_plan = build_practical_plan(
        live,
        strategy,
        meta,
    )

    report_json = build_report_json(
        snapshot=snapshot,
        live=live,
        digit_record=digit_record,
        gnc_record=gnc_record,
        strategy=strategy,
        lap=lap,
        meta=meta,
    )

    report_text = build_text_report(
        live=live,
        strategy=strategy,
        lap=lap,
        meta=meta,
        practical_plan=practical_plan,
    )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUTPUT_JSON.write_text(
        json.dumps(
            report_json,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    OUTPUT_TEXT.write_text(
        report_text,
        encoding="utf-8",
    )

    print()
    print(report_text)

    print()
    print(f"JSON report      : {OUTPUT_JSON}")
    print(f"Text report      : {OUTPUT_TEXT}")
    print()
    print(line("="))
    print("COMMUNITY INTELLIGENCE COMPLETE")
    print(line("="))


if __name__ == "__main__":
    main()