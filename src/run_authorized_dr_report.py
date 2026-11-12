"""Fetch expressly authorized DR leaderboard exports and prepare email report.

Secrets: GT7_DR_CSV_URL and GT7_DR_META_URL (HTTPS URLs issued by source).
Optional: GT7_DR_API_TOKEN for Bearer authentication.
No response bodies or credentials are logged. No partial data is reported.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit
import requests

from build_dr_benchmarks_from_csv import main as _unused  # shared standalone calculation module
from build_dr_benchmarks_from_csv import summarize
import csv
import io


def fetch_https(session, url, *, max_bytes):
    if urlsplit(url).scheme != "https" or not urlsplit(url).hostname:
        raise ValueError("Source endpoints must be valid HTTPS URLs")
    resp = session.get(url, timeout=60, allow_redirects=False, stream=True)
    resp.raise_for_status()
    data = bytearray()
    for chunk in resp.iter_content(chunk_size=65536):
        if chunk:
            data.extend(chunk)
            if len(data) > max_bytes:
                raise ValueError("Authorized export exceeds configured size limit")
    return bytes(data)


def build_report(result):
    lines = [
        "GT7 DAILY RACE C — DR LAP-TIME BENCHMARKS",
        "Qualified laps up to +20% of the world record (inclusive).",
        "",
        f"Event: {result['event_id']}",
        f"Source: {result['source']}",
        f"Observed: {result['observed_at']}",
        f"World record: {result['world_record_ms'] / 1000:.3f}s",
        f"Eligibility cutoff: {result['max_eligible_score_ms'] / 1000:.3f}s",
        f"Verified eligible drivers: {result['rows_verified']:,}",
        f"Over-cutoff source records excluded: {result['excluded_over_20pct']:,}",
        "",
        "DR | PILOTS | AVG QUALIFYING LAP | POPULATION SD",
        "----------------------------------------------",
    ]
    for code in (7, 6, 5, 4, 3, 2, 1):
        stat = result["dr_laptime_stats"][str(code)]
        sd = stat["stddev_seconds"]
        lines.append(
            f"{stat['label']:<2} | {stat['drivers']:>6,} | "
            f"{stat['average_laptime']:>17} | "
            f"{sd:.3f}s" if sd is not None
            else f"{stat['label']:<2} | {stat['drivers']:>6,} | N/A | N/A"
        )
    lines.extend([
        "",
        "Means and standard deviations use the established robust outlier filter",
        "(5 × MAD-based sigma); pilot counts reflect the cleaned sample.",
        "Data coverage was validated against the source-declared eligible total.",
    ])
    return "\n".join(lines) + "\n"


def main():
    csv_url = os.environ.get("GT7_DR_CSV_URL", "").strip()
    meta_url = os.environ.get("GT7_DR_META_URL", "").strip()
    if not csv_url or not meta_url:
        print("AUTHORIZED_DR_SOURCE_NOT_CONFIGURED")
        return 75
    session = requests.Session()
    token = os.environ.get("GT7_DR_API_TOKEN", "").strip()
    if token:
        session.headers["Authorization"] = f"Bearer {token}"
    csv_bytes = fetch_https(session, csv_url, max_bytes=30_000_000)
    meta_bytes = fetch_https(session, meta_url, max_bytes=128_000)
    metadata = json.loads(meta_bytes.decode("utf-8-sig"))
    stream = io.StringIO(csv_bytes.decode("utf-8-sig"))
    reader = csv.DictReader(stream)
    if not reader.fieldnames or not {"dr", "score_ms"}.issubset(reader.fieldnames):
        raise ValueError("Source CSV missing dr and score_ms")
    result = summarize(reader, metadata)
    out = Path("reports")
    out.mkdir(exist_ok=True)
    (out / "latest.txt").write_text(build_report(result), encoding="utf-8")
    (out / "email_subject.txt").write_text(
        f"GT7 DR LAP-TIME BENCHMARKS | {result['event_id']} | +20% WR",
        encoding="utf-8",
    )
    print(f"AUTHORIZED_DR_REPORT_READY: eligible={result['rows_verified']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
