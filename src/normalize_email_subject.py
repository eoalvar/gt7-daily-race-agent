import re
from pathlib import Path

REPORT_FILE = Path("reports/latest.txt")
SUBJECT_FILE = Path("reports/email_subject.txt")


def extract_header_context(report: str):
    category_match = re.search(r"^Car category:\s*(.+?)\s*$", report, flags=re.MULTILINE)
    category = category_match.group(1).strip() if category_match else None

    circuit = None
    lines = report.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("Car category:") and i + 1 < len(lines):
            candidate = lines[i + 1].strip()
            if candidate and not candidate.startswith(("Current WR:", "Race Setup:", "Race detection:")):
                circuit = candidate
            break

    return category, circuit


def main():
    if not REPORT_FILE.exists() or not SUBJECT_FILE.exists():
        raise SystemExit("report or email subject file missing")

    report = REPORT_FILE.read_text(encoding="utf-8")
    old_subject = SUBJECT_FILE.read_text(encoding="utf-8").strip()
    category, circuit = extract_header_context(report)

    parts = [part.strip() for part in old_subject.split("|")]

    # Preserve any Monday prefix before the Daily C token.
    try:
        daily_index = next(i for i, part in enumerate(parts) if part == "Daily C")
    except StopIteration:
        daily_index = 0
        parts.insert(0, "Daily C")

    prefix = parts[:daily_index]
    daily_parts = parts[daily_index + 1:]

    # Retain the useful performance suffixes regardless of previous subject layout.
    rank = next((p for p in daily_parts if re.fullmatch(r"#\d[\d,]*", p)), "Ranking N/A")
    wr = next((p for p in daily_parts if p.startswith("WR ")), "WR N/A")
    top = next((p for p in daily_parts if p.startswith("Top ")), "Top N/A")

    # A valid date can be kept at the end, but never let N/A displace the group.
    date = next((p for p in daily_parts if re.fullmatch(r"\d{2}[A-Za-z]{3}\d{2}", p)), None)

    rebuilt = prefix + ["Daily C"]
    if category:
        rebuilt.append(category)
    if circuit:
        rebuilt.append(circuit)
    rebuilt.extend([rank, wr, top])
    if date:
        rebuilt.append(date)

    subject = " | ".join(rebuilt)
    SUBJECT_FILE.write_text(subject, encoding="utf-8")
    print(f"Normalized email subject: {subject}")


if __name__ == "__main__":
    main()
