import json
from pathlib import Path

from car_database import (
    load_car_database,
    get_car_name
)


# ============================================================
# CONFIG
# ============================================================

DATA_DIR = Path("data")

HISTORY_FILE = (
    DATA_DIR
    / "weekly_rating_history.json"
)

REPORT_FILE = (
    DATA_DIR
    / "history_car_name_repair.txt"
)


# ============================================================
# MAIN
# ============================================================

def main():

    if not HISTORY_FILE.exists():

        raise RuntimeError(
            f"History file not found: {HISTORY_FILE}"
        )


    history = json.loads(
        HISTORY_FILE.read_text(
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


    database = load_car_database()


    changed = 0
    unchanged = 0
    unresolved = []


    lines = []

    lines.append(
        "GT7 HISTORY CAR NAME REPAIR"
    )

    lines.append(
        "=" * 72
    )


    for record in history:

        if not isinstance(
            record,
            dict
        ):
            continue


        car_code = record.get(
            "car_code"
        )


        if car_code is None:

            continue


        old_name = record.get(
            "car"
        )


        new_name = get_car_name(
            car_code,
            database
        )


        if new_name.startswith(
            "Unknown car"
        ):

            unresolved.append(
                car_code
            )

            continue


        if old_name != new_name:

            record[
                "car"
            ] = new_name

            changed += 1


            lines.append(
                f"{record.get('week_start','?')} | "
                f"{car_code} | "
                f"{old_name} -> {new_name}"
            )

        else:

            unchanged += 1


    HISTORY_FILE.write_text(
        json.dumps(
            history,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


    lines.append("")

    lines.append(
        f"Records changed    : {changed}"
    )

    lines.append(
        f"Records unchanged  : {unchanged}"
    )

    lines.append(
        f"Unresolved codes   : {len(set(unresolved))}"
    )


    if unresolved:

        lines.append("")

        lines.append(
            "UNRESOLVED"
        )

        for code in sorted(
            set(unresolved)
        ):

            lines.append(
                str(code)
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