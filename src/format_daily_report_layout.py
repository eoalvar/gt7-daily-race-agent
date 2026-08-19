import re
from pathlib import Path

REPORT_FILE = Path("reports/latest.txt")

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

    # Already formatted: make the function idempotent.
    if race_line.startswith("C ") and race_line.endswith("Daily Race C"):
        return text

    # Expected source example:
    # C Gr.3 Running 17 Aug 2026 Daily Race C i 17:29 Yas Marina Circuit
    # N.Baglioni - Porsche ... RM RS BoP On ...
    race_match = re.match(
        r"^(C\s+.+?\s+Daily Race C)\s+i\s+\d{1,2}:\d{2}\s+(.+)$",
        race_line,
    )
    if not race_match:
        return text

    race_title = race_match.group(1).strip()
    remainder = race_match.group(2).strip()

    # Use the WR section as the authoritative source for driver, time and car.
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

    # The compact line is: TRACK + WR DRIVER + " - " + WR CAR + RACE SETUP.
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


def format_one_report(text):
    text = remove_unwanted_sections(text)
    text = move_changed_section(text)
    text = move_cars_section(text)
    text = format_header(text)

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
    }

    for key, value in checks.items():
        print(f"{key}: {'YES' if value else 'NO'}")

    print("Daily report layout formatting completed.")


if __name__ == "__main__":
    main()
