import json
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


# ============================================================
# CONFIG
# ============================================================

DATA_DIR = Path("data")

WEEKLY_HISTORY_FILE = (
    DATA_DIR
    / "weekly_rating_history.json"
)

REPORT_FILE = (
    DATA_DIR
    / "remove_current_week_history.txt"
)

SAO_PAULO = ZoneInfo(
    "America/Sao_Paulo"
)


# ============================================================
# HELPERS
# ============================================================

def monday_of_week(dt):

    monday = (
        dt
        - timedelta(
            days=dt.weekday()
        )
    )

    return monday.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )


# ============================================================
# MAIN
# ============================================================

def main():

    if not WEEKLY_HISTORY_FILE.exists():

        raise RuntimeError(
            f"History file not found: "
            f"{WEEKLY_HISTORY_FILE}"
        )


    history = json.loads(
        WEEKLY_HISTORY_FILE.read_text(
            encoding="utf-8"
        )
    )


    if not isinstance(
        history,
        list
    ):

        raise RuntimeError(
            "weekly_rating_history.json "
            "must contain a list."
        )


    now = datetime.now(
        SAO_PAULO
    )


    current_week = (
        monday_of_week(
            now
        )
        .date()
        .isoformat()
    )


    kept = []

    removed = []


    for record in history:

        if not isinstance(
            record,
            dict
        ):

            kept.append(
                record
            )

            continue


        week_start = record.get(
            "week_start"
        )


        if week_start == current_week:

            removed.append(
                record
            )

        else:

            kept.append(
                record
            )


    WEEKLY_HISTORY_FILE.write_text(
        json.dumps(
            kept,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


    lines = []

    lines.append(
        "GT7 CURRENT-WEEK HISTORY CLEANUP"
    )

    lines.append(
        "=" * 72
    )

    lines.append(
        f"Current week       : "
        f"{current_week}"
    )

    lines.append(
        f"Records before     : "
        f"{len(history)}"
    )

    lines.append(
        f"Records removed    : "
        f"{len(removed)}"
    )

    lines.append(
        f"Records remaining  : "
        f"{len(kept)}"
    )


    if removed:

        lines.append("")

        lines.append(
            "REMOVED RECORDS"
        )

        lines.append(
            "-" * 72
        )


        for record in removed:

            lines.append(
                f"{record.get('week_start')} | "
                f"#{record.get('position')} / "
                f"{record.get('total_drivers')} | "
                f"{record.get('car')} | "
                f"{record.get('finalization_mode')}"
            )


    lines.append("")

    lines.append(
        "=" * 72
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