import json
from pathlib import Path
from datetime import datetime
from collections import defaultdict


# ============================================================
# CONFIG
# ============================================================

DATA_DIR = Path("data")
HISTORY_DIR = DATA_DIR / "history"

REPORT_FILE = (
    DATA_DIR
    / "forecast_history_audit.txt"
)

JSON_FILE = (
    DATA_DIR
    / "forecast_history_audit.json"
)


# ============================================================
# HELPERS
# ============================================================

def parse_datetime(value):

    if not value:
        return None

    try:
        return datetime.fromisoformat(
            value
        )

    except Exception:
        return None


def get_threshold_score(
    snapshot,
    key
):

    value = (
        snapshot
        .get(
            "thresholds",
            {}
        )
        .get(
            str(key)
        )
    )

    if isinstance(
        value,
        dict
    ):
        return value.get(
            "score"
        )

    if isinstance(
        value,
        (int, float)
    ):
        return value

    return None


def get_week_start(
    snapshot
):

    race = snapshot.get(
        "race",
        {}
    )

    start_date = race.get(
        "start_date"
    )

    parsed = parse_datetime(
        start_date
    )

    if parsed:
        return parsed.date().isoformat()

    return None


# ============================================================
# MAIN
# ============================================================

def main():

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    if not HISTORY_DIR.exists():

        raise RuntimeError(
            "data/history does not exist."
        )

    snapshots = []

    unreadable = 0

    for path in sorted(
        HISTORY_DIR.glob(
            "*.json"
        )
    ):

        try:

            data = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )

            timestamp = parse_datetime(
                data.get(
                    "timestamp"
                )
            )

            if not timestamp:
                continue

            week_start = get_week_start(
                data
            )

            snapshots.append({
                "file":
                    path.name,

                "timestamp":
                    timestamp,

                "week_start":
                    week_start,

                "race_url":
                    (
                        data
                        .get(
                            "race",
                            {}
                        )
                        .get(
                            "leaderboard_url"
                        )
                    ),

                "total_drivers":
                    data.get(
                        "total_drivers"
                    ),

                "wr":
                    (
                        data
                        .get(
                            "world_record",
                            {}
                        )
                        .get(
                            "score"
                        )
                    ),

                "top100":
                    get_threshold_score(
                        data,
                        100
                    ),

                "top500":
                    get_threshold_score(
                        data,
                        500
                    ),

                "top1000":
                    get_threshold_score(
                        data,
                        1000
                    ),

                "my_score":
                    (
                        data
                        .get(
                            "my_result",
                            {}
                        )
                        .get(
                            "score"
                        )
                        if data.get(
                            "my_result"
                        )
                        else None
                    ),

                "my_rank":
                    (
                        data
                        .get(
                            "my_result",
                            {}
                        )
                        .get(
                            "rank"
                        )
                        if data.get(
                            "my_result"
                        )
                        else None
                    ),

                "my_top_percent":
                    (
                        data
                        .get(
                            "my_result",
                            {}
                        )
                        .get(
                            "top_percent"
                        )
                        if data.get(
                            "my_result"
                        )
                        else None
                    )
            })

        except Exception:

            unreadable += 1

    # ========================================================
    # GROUP BY WEEK / EVENT
    # ========================================================

    groups = defaultdict(
        list
    )

    for snapshot in snapshots:

        key = (
            snapshot[
                "week_start"
            ],
            snapshot[
                "race_url"
            ]
        )

        groups[
            key
        ].append(
            snapshot
        )

    weeks = []

    for (
        week_start,
        race_url
    ), items in groups.items():

        items.sort(
            key=lambda item:
                item[
                    "timestamp"
                ]
        )

        first = items[0][
            "timestamp"
        ]

        last = items[-1][
            "timestamp"
        ]

        span_hours = (
            last
            - first
        ).total_seconds() / 3600

        days_present = sorted(
            {
                item[
                    "timestamp"
                ].strftime(
                    "%a"
                )
                for item in items
            }
        )

        metrics = {
            "wr":
                sum(
                    1
                    for item in items
                    if item[
                        "wr"
                    ] is not None
                ),

            "top100":
                sum(
                    1
                    for item in items
                    if item[
                        "top100"
                    ] is not None
                ),

            "top500":
                sum(
                    1
                    for item in items
                    if item[
                        "top500"
                    ] is not None
                ),

            "top1000":
                sum(
                    1
                    for item in items
                    if item[
                        "top1000"
                    ] is not None
                ),

            "my_rank":
                sum(
                    1
                    for item in items
                    if item[
                        "my_rank"
                    ] is not None
                )
        }

        weeks.append({
            "week_start":
                week_start,

            "race_url":
                race_url,

            "snapshots":
                len(
                    items
                ),

            "first_snapshot":
                first.isoformat(),

            "last_snapshot":
                last.isoformat(),

            "span_hours":
                span_hours,

            "days_present":
                days_present,

            "metrics":
                metrics
        })

    weeks.sort(
        key=lambda item:
            (
                item[
                    "week_start"
                ]
                or "",
                item[
                    "first_snapshot"
                ]
            )
    )

    # ========================================================
    # FORECAST TRAINING QUALITY
    # ========================================================

    usable_3 = [
        week
        for week in weeks
        if (
            week[
                "snapshots"
            ] >= 3
            and week[
                "span_hours"
            ] >= 12
        )
    ]

    usable_6 = [
        week
        for week in weeks
        if (
            week[
                "snapshots"
            ] >= 6
            and week[
                "span_hours"
            ] >= 24
        )
    ]

    strong = [
        week
        for week in weeks
        if (
            week[
                "snapshots"
            ] >= 10
            and week[
                "span_hours"
            ] >= 72
        )
    ]

    # ========================================================
    # JSON
    # ========================================================

    result = {
        "history_files":
            len(
                snapshots
            ),

        "unreadable_files":
            unreadable,

        "race_weeks":
            len(
                weeks
            ),

        "weeks_usable_minimum":
            len(
                usable_3
            ),

        "weeks_usable_good":
            len(
                usable_6
            ),

        "weeks_usable_strong":
            len(
                strong
            ),

        "weeks":
            weeks
    }

    JSON_FILE.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    # ========================================================
    # TEXT REPORT
    # ========================================================

    lines = []

    lines.append(
        "GT7 FORECAST HISTORY AUDIT"
    )

    lines.append(
        "=" * 84
    )

    lines.append(
        f"Snapshot files read     : "
        f"{len(snapshots)}"
    )

    lines.append(
        f"Unreadable files        : "
        f"{unreadable}"
    )

    lines.append(
        f"Race weeks represented  : "
        f"{len(weeks)}"
    )

    lines.append(
        f"Minimum usable weeks    : "
        f"{len(usable_3)}"
    )

    lines.append(
        f"Good training weeks     : "
        f"{len(usable_6)}"
    )

    lines.append(
        f"Strong training weeks   : "
        f"{len(strong)}"
    )

    lines.append("")

    lines.append(
        "WEEK-BY-WEEK COVERAGE"
    )

    lines.append(
        "-" * 84
    )

    for week in weeks:

        days = (
            ", ".join(
                week[
                    "days_present"
                ]
            )
            if week[
                "days_present"
            ]
            else "N/A"
        )

        lines.append(
            f"{week['week_start'] or 'UNKNOWN'} | "
            f"{week['snapshots']:3d} snapshots | "
            f"{week['span_hours']:6.1f} h | "
            f"days: {days}"
        )

        lines.append(
            f"    WR {week['metrics']['wr']} | "
            f"Top100 {week['metrics']['top100']} | "
            f"Top500 {week['metrics']['top500']} | "
            f"Top1000 {week['metrics']['top1000']} | "
            f"MyRank {week['metrics']['my_rank']}"
        )

    lines.append("")

    lines.append(
        "TRAINING ASSESSMENT"
    )

    lines.append(
        "-" * 84
    )

    if len(strong) >= 4:

        assessment = (
            "STRONG - enough historical intraday data exists "
            "to build a historical leaderboard-decay model."
        )

    elif len(usable_6) >= 3:

        assessment = (
            "GOOD - enough historical data exists for Forecast v2, "
            "but uncertainty should remain conservative."
        )

    elif len(usable_3) >= 2:

        assessment = (
            "LIMITED - Forecast v2 is possible, but historical "
            "training data is still sparse."
        )

    else:

        assessment = (
            "INSUFFICIENT - current history is not yet rich enough "
            "to train a reliable cross-week forecast model."
        )

    lines.append(
        assessment
    )

    lines.append("")

    lines.append(
        "Definitions:"
    )

    lines.append(
        "Minimum = >=3 snapshots spanning >=12h."
    )

    lines.append(
        "Good    = >=6 snapshots spanning >=24h."
    )

    lines.append(
        "Strong  = >=10 snapshots spanning >=72h."
    )

    lines.append("")

    lines.append(
        "=" * 84
    )

    report = "\n".join(
        lines
    )

    REPORT_FILE.write_text(
        report,
        encoding="utf-8"
    )

    print(
        report
    )


if __name__ == "__main__":
    main()