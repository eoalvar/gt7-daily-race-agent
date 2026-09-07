#!/usr/bin/env python3

import re
from pathlib import Path

REPORT = Path("reports/latest.txt")
MARKER = "NEW WEEK - CURRENT DAILY RACE C"
SHORT_SEPARATOR = "-" * 40


def clean_previous_block(block: str) -> str:
    lines = block.splitlines()
    out = []

    # apply_cpi_production scans the entire Monday combined report and can inject
    # the current week's CPI after the previous week's WR line. Remove that
    # injected pipe-style CPI when another fallback CPI line is already present.
    cpi_lines = [line for line in lines if re.match(r"^\s*CPI\s*:", line)]
    has_fallback_cpi = any("(" in line or "FINAL SNAPSHOT" in block for line in cpi_lines)

    for line in lines:
        stripped = line.strip()
        if has_fallback_cpi and re.match(r"^CPI\s*:.*\|", stripped) and len(cpi_lines) > 1:
            continue
        if stripped and set(stripped) == {"="} and len(stripped) >= 20:
            if not out or out[-1] != SHORT_SEPARATOR:
                out.append(SHORT_SEPARATOR)
            continue
        out.append(line)

    # Collapse duplicate separator rows and excessive blank lines.
    cleaned = []
    blanks = 0
    for line in out:
        if line == SHORT_SEPARATOR and cleaned and cleaned[-1] == SHORT_SEPARATOR:
            continue
        if not line.strip():
            blanks += 1
            if blanks <= 1:
                cleaned.append(line)
        else:
            blanks = 0
            cleaned.append(line)
    return "\n".join(cleaned).strip()


def main():
    if not REPORT.exists():
        return
    text = REPORT.read_text(encoding="utf-8")
    if MARKER not in text:
        return

    previous, current = text.split(MARKER, 1)
    previous = clean_previous_block(previous)
    current = current.lstrip("\n")

    # Avoid the 78-character separator wrapping awkwardly in Spark/iPhone.
    current = re.sub(r"^={20,}$", SHORT_SEPARATOR, current, flags=re.MULTILINE)

    combined = previous + "\n\n" + MARKER + "\n" + SHORT_SEPARATOR + "\n\n" + current.lstrip("-\n")
    REPORT.write_text(combined.rstrip() + "\n", encoding="utf-8")
    print("Monday combined report cleaned for mobile email presentation.")


if __name__ == "__main__":
    main()
