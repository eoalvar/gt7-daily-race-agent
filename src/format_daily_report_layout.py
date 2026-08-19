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

    # The recommendation block is generated at the end of the current
    # Daily C report. Preserve only the block itself, dropping separator
    # whitespace around its former location.
    block = text[start:].strip()
    text = text[:start].rstrip()

    insert_at = text.find(CARS_INSERT_BEFORE)
    if insert_at < 0:
        # Fail safe: if the expected anchor changes, keep the block at end.
        return text + "\n\n" + block + "\n"

    prefix = text[:insert_at].rstrip()
    suffix = text[insert_at:].lstrip("\n")
    return prefix + "\n\n" + block + "\n\n" + suffix


def format_one_report(text):
    text = remove_unwanted_sections(text)
    text = move_changed_section(text)
    text = move_cars_section(text)

    # Normalize excessive blank lines without changing report content.
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")

    return text.strip() + "\n"


def format_report(text):
    # Monday emails contain a previous-week final followed by the current
    # report. Format both independently so removed sections cannot survive
    # in the combined email.
    marker_pos = text.find(CURRENT_WEEK_MARKER)
    if marker_pos < 0:
        return format_one_report(text)

    first = text[:marker_pos]
    second = text[marker_pos:]

    first = format_one_report(first).rstrip()

    # Preserve the Monday marker itself; format only the Daily C content
    # that follows it.
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
    }

    for key, value in checks.items():
        print(f"{key}: {'YES' if value else 'NO'}")

    print("Daily report layout formatting completed.")


if __name__ == "__main__":
    main()
