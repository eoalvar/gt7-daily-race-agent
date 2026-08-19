import json
import re
from pathlib import Path

REPORT_FILE = Path("reports/latest.txt")
WEEKLY_HISTORY_FILE = Path("data/weekly_rating_history.json")
TRACK_BOP_FILE = Path("data/bop_lab/track_bop_classes.json")

UNWANTED_START = "YOUR BRAKE BIAS STARTING POINT\n"
UNWANTED_END = "FORECAST TO SUNDAY - V2\n"

CHANGED_START = "WHAT CHANGED SINCE PREVIOUS SNAPSHOT\n"
CHANGED_END = "DATA QUALITY / HEALTH\n"
CHANGED_INSERT_BEFORE = "WORLD RECORD & BENCHMARKS\n"

CARS_START = "CARS TO TEST THIS WEEK\n"
CARS_INSERT_BEFORE = "FORECAST TO SUNDAY - V2\n"

CURRENT_WEEK_MARKER = "NEW WEEK - CURRENT DAILY RACE C"


def remove_unwanted_sections(text):
    start = text.find(UNWANTED_START)
    end = text.find(UNWANTED_END, start if start >= 0 else 0)

    if start >= 0 and end > start:
        text = text[:start] + text[end:]

    return text


def move_changed_section(text):
    start = text.find(CHANGED_START)
    end = text.find(CHANGED_END, start if start >= 0 else 0)

    if start < 0 or end <= start:
        return text

    block = text[start:end].strip("\n")
    text = text[:start] + text[end:]

    insert_at = text.find(CHANGED_INSERT_BEFORE)
    if insert_at < 0:
        return text

    prefix = text[:insert_at].rstrip()
    suffix = text[insert_at:].lstrip("\n")
    return prefix + "\n\n" + block + "\n\n" + suffix


def move_cars_section(text):
    start = text.find(CARS_START)
    if start < 0:
        return text

    block = text[start:].strip()
    text = text[:start].rstrip()

    insert_at = text.find(CARS_INSERT_BEFORE)
    if insert_at < 0:
        return text + "\n\n" + block + "\n"

    prefix = text[:insert_at].rstrip()
    suffix = text[insert_at:].lstrip("\n")
    return prefix + "\n\n" + block + "\n\n" + suffix


def format_header(text):
    """Split the compact GTSH race-description line into a readable header."""
    lines = text.splitlines()

    snapshot_index = next(
        (i for i, line in enumerate(lines) if line.startswith("Snapshot:")),
        None,
    )
    if snapshot_index is None or snapshot_index + 1 >= len(lines):
        return text

    race_index = snapshot_index + 1
    race_line = lines[race_index].strip()

    if race_line.startswith("C ") and race_line.endswith("Daily Race C"):
        return text

    race_match = re.match(
        r"^(C\s+.+?\s+Daily Race C)\s+i\s+\d{1,2}:\d{2}\s+(.+)$",
        race_line,
    )
    if not race_match:
        return text

    race_title = race_match.group(1).strip()
    remainder = race_match.group(2).strip()

    wr_match = re.search(
        r"^WR\s*:\s*([^|\n]+?)\s*\|\s*([^|\n]+?)\s*\|\s*(.+?)\s*$",
        text,
        flags=re.MULTILINE,
    )
    if not wr_match:
        return text

    wr_time = wr_match.group(1).strip()
    wr_driver = wr_match.group(2).strip()
    wr_car = wr_match.group(3).strip()

    driver_marker = f" {wr_driver} - "
    if driver_marker not in remainder:
        return text

    circuit, after_driver = remainder.split(driver_marker, 1)
    circuit = circuit.strip()

    if not after_driver.startswith(wr_car):
        return text

    race_setup = after_driver[len(wr_car):].strip()

    new_header = [
        race_title,
        circuit,
        f"Current WR: {wr_driver} ({wr_time})",
        f"Current WR Car: {wr_car}",
        f"Race Setup: {race_setup}",
    ]

    lines[race_index:race_index + 1] = new_header
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def load_track_names():
    """Return canonical circuit names and aliases, longest names first."""
    if not TRACK_BOP_FILE.exists():
        return []

    try:
        data = json.loads(TRACK_BOP_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []

    tracks = data.get("tracks") if isinstance(data, dict) else None
    if not isinstance(tracks, dict):
        return []

    names = []

    for canonical, info in tracks.items():
        if not isinstance(canonical, str) or not canonical.strip():
            continue

        canonical = canonical.strip()
        names.append((canonical, canonical))

        if isinstance(info, dict):
            aliases = info.get("aliases")
            if isinstance(aliases, list):
                for alias in aliases:
                    if isinstance(alias, str) and alias.strip():
                        names.append((alias.strip(), canonical))

    # Prefer the longest match so variants such as "... Reverse" are not
    # truncated to their shorter base circuit name.
    names.sort(key=lambda item: len(item[0]), reverse=True)
    return names


def extract_group_and_circuit(record, track_names):
    race = str(record.get("race") or "").strip()

    group_match = re.match(
        r"^C\s+(Gr\.[1234]|Gr\.B)\b",
        race,
        flags=re.IGNORECASE,
    )
    group = group_match.group(1) if group_match else "Group N/A"

    after_time_match = re.search(
        r"Daily Race C\s+i\s+\d{1,2}:\d{2}\s+(.+)$",
        race,
        flags=re.IGNORECASE,
    )
    if not after_time_match:
        return group, "Circuit N/A"

    remainder = after_time_match.group(1).strip()
    remainder_lower = remainder.casefold()

    # Circuit names come from the validated track database. Matching the
    # beginning of the post-time text avoids ever consuming WR driver/car/setup.
    for candidate, canonical in track_names:
        candidate_lower = candidate.casefold()
        if remainder_lower == candidate_lower or remainder_lower.startswith(candidate_lower + " "):
            # Preserve the exact variant written in the race string when it is
            # itself a full known alias; otherwise use the canonical name.
            return group, candidate

    return group, "Circuit N/A"


def load_finalized_race_context():
    if not WEEKLY_HISTORY_FILE.exists():
        return {}

    try:
        history = json.loads(WEEKLY_HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

    if not isinstance(history, list):
        return {}

    track_names = load_track_names()
    context = {}

    for record in history:
        if not isinstance(record, dict) or record.get("participated") is not True:
            continue

        week = str(record.get("week_start") or "").strip()
        if not week:
            continue

        group, circuit = extract_group_and_circuit(record, track_names)
        context[week] = {
            "group": group,
            "circuit": circuit,
        }

    return context


def enrich_finalized_history(text):
    """Render each finalized race as a clean two-line memory aid."""
    context = load_finalized_race_context()
    if not context or "LAST FINALIZED RACES" not in text:
        return text

    source_lines = text.splitlines()
    output = []
    in_section = False
    i = 0

    while i < len(source_lines):
        line = source_lines[i]

        if line.strip() == "LAST FINALIZED RACES":
            in_section = True
            output.append(line)
            i += 1
            continue

        if in_section and not line.strip():
            in_section = False
            output.append(line)
            i += 1
            continue

        if not in_section:
            output.append(line)
            i += 1
            continue

        match = re.match(r"^-?\s*(\d{4}-\d{2}-\d{2})\s*\|\s*(.+)$", line)
        if not match:
            output.append(line)
            i += 1
            continue

        week = match.group(1)
        remainder = match.group(2)
        info = context.get(week)

        if not info:
            output.append(line)
            i += 1
            continue

        # Accept both the original one-line history and a previously enriched
        # version. Only the metric payload beginning at "Gen" is retained.
        metrics_match = re.search(r"\bGen\s+.+$", remainder)
        if not metrics_match and i + 1 < len(source_lines):
            metrics_match = re.search(r"\bGen\s+.+$", source_lines[i + 1])
            if metrics_match:
                i += 1

        metrics = metrics_match.group(0).strip() if metrics_match else remainder.strip()

        output.append(
            f"- {week} | {info['group']} | {info['circuit']}"
        )
        output.append(metrics)
        i += 1

    return "\n".join(output) + ("\n" if text.endswith("\n") else "")


def format_one_report(text):
    text = remove_unwanted_sections(text)
    text = move_changed_section(text)
    text = move_cars_section(text)
    text = format_header(text)
    text = enrich_finalized_history(text)

    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")

    return text.strip() + "\n"


def format_report(text):
    marker_pos = text.find(CURRENT_WEEK_MARKER)
    if marker_pos < 0:
        return format_one_report(text)

    first = text[:marker_pos]
    second = text[marker_pos:]

    first = format_one_report(first).rstrip()

    marker_end = second.find("\n")
    if marker_end < 0:
        return first + "\n\n" + second.strip() + "\n"

    marker_line = second[:marker_end].rstrip()
    remainder = second[marker_end + 1 :]
    remainder = format_one_report(remainder).strip()

    return first + "\n\n" + marker_line + "\n" + remainder + "\n"


def main():
    if not REPORT_FILE.exists():
        raise RuntimeError("reports/latest.txt not found")

    original = REPORT_FILE.read_text(encoding="utf-8")
    formatted = format_report(original)
    REPORT_FILE.write_text(formatted, encoding="utf-8")

    checks = {
        "brake_bias_removed": "YOUR BRAKE BIAS STARTING POINT" not in formatted,
        "top5_brake_removed": "BRAKE BIAS - TOP 5 USED CARS" not in formatted,
        "strategy_flags_removed": "RACE STRATEGY FLAGS" not in formatted,
        "header_current_wr": "Current WR:" in formatted,
        "header_current_wr_car": "Current WR Car:" in formatted,
        "header_race_setup": "Race Setup:" in formatted,
        "finalized_history_two_line": (
            "LAST FINALIZED RACES" not in formatted
            or bool(re.search(r"^- \d{4}-\d{2}-\d{2} \| Gr\.", formatted, re.MULTILINE))
        ),
    }

    for key, value in checks.items():
        print(f"{key}: {'YES' if value else 'NO'}")

    print("Daily report layout formatting completed.")


if __name__ == "__main__":
    main()
