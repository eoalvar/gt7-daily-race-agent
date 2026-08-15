import json
import math
import statistics
from pathlib import Path
from datetime import datetime


# ============================================================
# CONFIG
# ============================================================

DATA_DIR = Path("data")
REPORT_DIR = Path("reports")

HISTORY_FILE = DATA_DIR / "weekly_rating_history.json"

SUMMARY_FILE = DATA_DIR / "rating_history_summary.json"

REPORT_FILE = REPORT_DIR / "rating_history.txt"

MOVING_AVERAGE_WINDOW = 5
PERIOD_COMPARISON_SIZE = 5


# ============================================================
# BASIC HELPERS
# ============================================================

def safe_number(value):

    if isinstance(value, (int, float)):
        return float(value)

    return None


def fmt(value, decimals=2):

    if value is None:
        return "N/A"

    return f"{value:.{decimals}f}"


def fmt_signed(value, decimals=2):

    if value is None:
        return "N/A"

    sign = "+" if value > 0 else ""

    return f"{sign}{value:.{decimals}f}"


def percent(value, decimals=2):

    if value is None:
        return "N/A"

    return f"{value:.{decimals}f}%"


def average(values):

    clean = [
        value
        for value in values
        if isinstance(value, (int, float))
    ]

    if not clean:
        return None

    return sum(clean) / len(clean)


# ============================================================
# LOAD HISTORY
# ============================================================

def load_history():

    if not HISTORY_FILE.exists():

        raise RuntimeError(
            f"History file not found: {HISTORY_FILE}"
        )


    data = json.loads(
        HISTORY_FILE.read_text(
            encoding="utf-8"
        )
    )


    if not isinstance(data, list):

        raise RuntimeError(
            "weekly_rating_history.json must contain a list."
        )


    records = [

        record
        for record in data
        if (
            isinstance(record, dict)
            and record.get("participated") is True
        )

    ]


    records.sort(
        key=lambda item:
            item.get("week_start", "")
    )


    if not records:

        raise RuntimeError(
            "No participated Daily Race C records found."
        )


    return records


# ============================================================
# MOVING AVERAGES
# ============================================================

def moving_average(
    records,
    key,
    window=MOVING_AVERAGE_WINDOW
):

    values = []

    for index in range(len(records)):

        start = max(
            0,
            index - window + 1
        )

        subset = records[
            start:
            index + 1
        ]

        subset_values = [

            safe_number(
                record.get(key)
            )

            for record in subset

        ]

        subset_values = [
            value
            for value in subset_values
            if value is not None
        ]


        if len(subset_values) < min(
            window,
            index + 1
        ):

            values.append(None)

        else:

            values.append(
                average(subset_values)
            )


    return values


# ============================================================
# LINEAR TREND
# ============================================================

def linear_trend(
    records,
    key,
    higher_is_better=True
):

    points = []

    for index, record in enumerate(records):

        value = safe_number(
            record.get(key)
        )

        if value is not None:

            points.append(
                (
                    float(index),
                    value
                )
            )


    if len(points) < 3:

        return None


    xs = [
        point[0]
        for point in points
    ]

    ys = [
        point[1]
        for point in points
    ]


    x_mean = average(xs)
    y_mean = average(ys)


    denominator = sum(
        (x - x_mean) ** 2
        for x in xs
    )


    if denominator == 0:

        return None


    slope = (

        sum(
            (x - x_mean)
            * (y - y_mean)

            for x, y
            in points
        )

        / denominator

    )


    improvement_slope = (
        slope
        if higher_is_better
        else -slope
    )


    if abs(improvement_slope) < 0.01:

        direction = "STABLE"

    elif improvement_slope > 0:

        direction = "IMPROVING"

    else:

        direction = "DECLINING"


    return {
        "slope_per_race":
            slope,

        "improvement_slope":
            improvement_slope,

        "direction":
            direction
    }


# ============================================================
# PERIOD COMPARISON
# ============================================================

def period_comparison(
    records,
    key,
    size=PERIOD_COMPARISON_SIZE,
    higher_is_better=True
):

    if len(records) < size * 2:

        return None


    recent = records[
        -size:
    ]

    previous = records[
        -(size * 2):
        -size
    ]


    recent_avg = average(
        [
            safe_number(
                record.get(key)
            )
            for record in recent
        ]
    )


    previous_avg = average(
        [
            safe_number(
                record.get(key)
            )
            for record in previous
        ]
    )


    if (
        recent_avg is None
        or previous_avg is None
    ):

        return None


    raw_change = (
        recent_avg
        - previous_avg
    )


    improvement = (
        raw_change
        if higher_is_better
        else -raw_change
    )


    return {
        "recent_average":
            recent_avg,

        "previous_average":
            previous_avg,

        "raw_change":
            raw_change,

        "improvement":
            improvement
    }


# ============================================================
# BEST / WORST RECORDS
# ============================================================

def best_record(
    records,
    key,
    higher_is_better=True
):

    valid = [

        record
        for record in records
        if safe_number(
            record.get(key)
        ) is not None

    ]


    if not valid:

        return None


    return (
        max(
            valid,
            key=lambda record:
                safe_number(
                    record.get(key)
                )
        )

        if higher_is_better

        else

        min(
            valid,
            key=lambda record:
                safe_number(
                    record.get(key)
                )
        )
    )


def worst_record(
    records,
    key,
    higher_is_better=True
):

    valid = [

        record
        for record in records
        if safe_number(
            record.get(key)
        ) is not None

    ]


    if not valid:

        return None


    return (
        min(
            valid,
            key=lambda record:
                safe_number(
                    record.get(key)
                )
        )

        if higher_is_better

        else

        max(
            valid,
            key=lambda record:
                safe_number(
                    record.get(key)
                )
        )
    )


# ============================================================
# CONSISTENCY
# ============================================================

def standard_deviation(
    records,
    key,
    last_n=None
):

    selected = (
        records[-last_n:]
        if last_n
        else records
    )


    values = [

        safe_number(
            record.get(key)
        )

        for record in selected

    ]


    values = [
        value
        for value in values
        if value is not None
    ]


    if len(values) < 2:

        return None


    return statistics.pstdev(
        values
    )


# ============================================================
# PERFORMANCE CLASSIFICATION
# ============================================================

def classify_recent_form(
    general_comparison,
    elite_comparison,
    wr_comparison
):

    signals = []


    if general_comparison:

        signals.append(
            general_comparison[
                "improvement"
            ]
        )


    if elite_comparison:

        signals.append(
            elite_comparison[
                "improvement"
            ]
        )


    if wr_comparison:

        signals.append(
            wr_comparison[
                "improvement"
            ]
        )


    if not signals:

        return "INSUFFICIENT DATA"


    positive = sum(
        1
        for value in signals
        if value > 0.02
    )


    negative = sum(
        1
        for value in signals
        if value < -0.02
    )


    if positive >= 2:

        return "IMPROVING"


    if negative >= 2:

        return "DECLINING"


    return "STABLE"


# ============================================================
# MAIN ANALYSIS
# ============================================================

def build_analysis(records):

    general_ma = moving_average(
        records,
        "general_score"
    )

    elite_ma = moving_average(
        records,
        "elite_score"
    )

    composite_ma = moving_average(
        records,
        "composite_rating"
    )

    wr_ma = moving_average(
        records,
        "wr_percentage"
    )


    weekly = []


    for index, record in enumerate(records):

        weekly.append(
            {
                "week_start":
                    record.get(
                        "week_start"
                    ),

                "general":
                    record.get(
                        "general_score"
                    ),

                "elite":
                    record.get(
                        "elite_score"
                    ),

                "composite":
                    record.get(
                        "composite_rating"
                    ),

                "top_percent":
                    record.get(
                        "top_percent"
                    ),

                "wr_percentage":
                    record.get(
                        "wr_percentage"
                    ),

                "position":
                    record.get(
                        "position"
                    ),

                "total_drivers":
                    record.get(
                        "total_drivers"
                    ),

                "car":
                    record.get(
                        "car"
                    ),

                "general_ma5":
                    general_ma[index],

                "elite_ma5":
                    elite_ma[index],

                "composite_ma5":
                    composite_ma[index],

                "wr_percentage_ma5":
                    wr_ma[index]
            }
        )


    general_comparison = period_comparison(
        records,
        "general_score",
        higher_is_better=True
    )

    elite_comparison = period_comparison(
        records,
        "elite_score",
        higher_is_better=True
    )

    composite_comparison = period_comparison(
        records,
        "composite_rating",
        higher_is_better=True
    )

    top_comparison = period_comparison(
        records,
        "top_percent",
        higher_is_better=False
    )

    wr_comparison = period_comparison(
        records,
        "wr_percentage",
        higher_is_better=False
    )


    recent_form = classify_recent_form(
        general_comparison,
        elite_comparison,
        wr_comparison
    )


    return {
        "generated_at":
            datetime.now()
            .astimezone()
            .isoformat(),

        "races_analyzed":
            len(records),

        "first_week":
            records[0].get(
                "week_start"
            ),

        "latest_week":
            records[-1].get(
                "week_start"
            ),

        "recent_form":
            recent_form,

        "trend": {

            "general":
                linear_trend(
                    records,
                    "general_score",
                    True
                ),

            "elite":
                linear_trend(
                    records,
                    "elite_score",
                    True
                ),

            "composite":
                linear_trend(
                    records,
                    "composite_rating",
                    True
                ),

            "top_percent":
                linear_trend(
                    records,
                    "top_percent",
                    False
                ),

            "wr_percentage":
                linear_trend(
                    records,
                    "wr_percentage",
                    False
                )
        },

        "last5_vs_previous5": {

            "general":
                general_comparison,

            "elite":
                elite_comparison,

            "composite":
                composite_comparison,

            "top_percent":
                top_comparison,

            "wr_percentage":
                wr_comparison
        },

        "best": {

            "general":
                best_record(
                    records,
                    "general_score",
                    True
                ),

            "elite":
                best_record(
                    records,
                    "elite_score",
                    True
                ),

            "composite":
                best_record(
                    records,
                    "composite_rating",
                    True
                ),

            "top_percent":
                best_record(
                    records,
                    "top_percent",
                    False
                ),

            "wr_percentage":
                best_record(
                    records,
                    "wr_percentage",
                    False
                )
        },

        "worst": {

            "general":
                worst_record(
                    records,
                    "general_score",
                    True
                ),

            "elite":
                worst_record(
                    records,
                    "elite_score",
                    True
                )
        },

        "consistency": {

            "general_all":
                standard_deviation(
                    records,
                    "general_score"
                ),

            "general_last5":
                standard_deviation(
                    records,
                    "general_score",
                    5
                ),

            "elite_all":
                standard_deviation(
                    records,
                    "elite_score"
                ),

            "elite_last5":
                standard_deviation(
                    records,
                    "elite_score",
                    5
                )
        },

        "weekly":
            weekly
    }


# ============================================================
# TEXT REPORT
# ============================================================

def build_text_report(
    records,
    analysis
):

    lines = []


    lines.append(
        "GT7 DAILY RACE C - LONG-TERM RATING ANALYSIS"
    )

    lines.append(
        "=" * 78
    )

    lines.append(
        f"Races analyzed : "
        f"{analysis['races_analyzed']}"
    )

    lines.append(
        f"Period         : "
        f"{analysis['first_week']} "
        f"to {analysis['latest_week']}"
    )

    lines.append(
        f"Recent form    : "
        f"{analysis['recent_form']}"
    )


    # ========================================================
    # CURRENT
    # ========================================================

    latest = records[-1]


    lines.append("")
    lines.append(
        "CURRENT POSITION"
    )


    lines.append(
        f"General Rating : "
        f"{fmt(latest.get('general_score'))}"
    )

    lines.append(
        f"Elite Rating   : "
        f"{fmt(latest.get('elite_score'))}"
    )

    lines.append(
        f"Composite      : "
        f"{fmt(latest.get('composite_rating'))}"
    )

    lines.append(
        f"Top %          : "
        f"{percent(latest.get('top_percent'))}"
    )

    lines.append(
        f"WR %           : "
        f"{percent(latest.get('wr_percentage'), 3)}"
    )

    lines.append(
        f"Position       : "
        f"#{latest.get('position'):,} "
        f"of {latest.get('total_drivers'):,}"
    )


    # ========================================================
    # MOVING AVERAGE
    # ========================================================

    latest_week = analysis[
        "weekly"
    ][
        -1
    ]


    lines.append("")
    lines.append(
        "5-RACE MOVING AVERAGE"
    )


    lines.append(
        f"General MA5    : "
        f"{fmt(latest_week.get('general_ma5'))}"
    )

    lines.append(
        f"Elite MA5      : "
        f"{fmt(latest_week.get('elite_ma5'))}"
    )

    lines.append(
        f"Composite MA5  : "
        f"{fmt(latest_week.get('composite_ma5'))}"
    )

    lines.append(
        f"WR % MA5       : "
        f"{percent(latest_week.get('wr_percentage_ma5'), 3)}"
    )


    # ========================================================
    # LAST 5 VS PREVIOUS 5
    # ========================================================

    lines.append("")
    lines.append(
        "LAST 5 RACES VS PREVIOUS 5"
    )


    comparison = analysis[
        "last5_vs_previous5"
    ]


    labels = [
        (
            "General",
            "general",
            True,
            False
        ),

        (
            "Elite",
            "elite",
            True,
            False
        ),

        (
            "Composite",
            "composite",
            True,
            False
        ),

        (
            "Top %",
            "top_percent",
            False,
            True
        ),

        (
            "WR %",
            "wr_percentage",
            False,
            True
        )
    ]


    for label, key, _, is_percent in labels:

        item = comparison.get(
            key
        )


        if not item:
            continue


        if is_percent:

            previous_text = percent(
                item[
                    "previous_average"
                ],
                3
            )

            recent_text = percent(
                item[
                    "recent_average"
                ],
                3
            )

            delta_text = (
                f"{item['raw_change']:+.3f} pp"
            )

        else:

            previous_text = fmt(
                item[
                    "previous_average"
                ]
            )

            recent_text = fmt(
                item[
                    "recent_average"
                ]
            )

            delta_text = fmt_signed(
                item[
                    "raw_change"
                ]
            )


        lines.append(
            f"{label:<14}: "
            f"{previous_text} -> "
            f"{recent_text} "
            f"({delta_text})"
        )


    # ========================================================
    # LONG-TERM TREND
    # ========================================================

    lines.append("")
    lines.append(
        "LONG-TERM TREND"
    )


    trend = analysis[
        "trend"
    ]


    for label, key in [
        (
            "General",
            "general"
        ),

        (
            "Elite",
            "elite"
        ),

        (
            "Composite",
            "composite"
        ),

        (
            "Top %",
            "top_percent"
        ),

        (
            "WR %",
            "wr_percentage"
        )
    ]:

        item = trend.get(
            key
        )

        if item:

            lines.append(
                f"{label:<14}: "
                f"{item['direction']} | "
                f"slope/race "
                f"{item['slope_per_race']:+.4f}"
            )


    # ========================================================
    # PERSONAL BESTS
    # ========================================================

    lines.append("")
    lines.append(
        "PERSONAL BESTS"
    )


    best = analysis[
        "best"
    ]


    general_best = best.get(
        "general"
    )

    elite_best = best.get(
        "elite"
    )

    top_best = best.get(
        "top_percent"
    )

    wr_best = best.get(
        "wr_percentage"
    )


    if general_best:

        lines.append(
            f"Best General   : "
            f"{general_best['general_score']:.2f} | "
            f"{general_best['week_start']}"
        )


    if elite_best:

        lines.append(
            f"Best Elite     : "
            f"{elite_best['elite_score']:.2f} | "
            f"{elite_best['week_start']}"
        )


    if top_best:

        lines.append(
            f"Best Top %     : "
            f"Top {top_best['top_percent']:.2f}% | "
            f"{top_best['week_start']}"
        )


    if wr_best:

        lines.append(
            f"Closest to WR  : "
            f"{wr_best['wr_percentage']:.3f}% | "
            f"{wr_best['week_start']}"
        )


    # ========================================================
    # CONSISTENCY
    # ========================================================

    consistency = analysis[
        "consistency"
    ]


    lines.append("")
    lines.append(
        "CONSISTENCY"
    )


    lines.append(
        f"General SD all : "
        f"{fmt(consistency['general_all'], 3)}"
    )

    lines.append(
        f"General SD L5  : "
        f"{fmt(consistency['general_last5'], 3)}"
    )

    lines.append(
        f"Elite SD all   : "
        f"{fmt(consistency['elite_all'], 3)}"
    )

    lines.append(
        f"Elite SD L5    : "
        f"{fmt(consistency['elite_last5'], 3)}"
    )


    # ========================================================
    # WEEK-BY-WEEK
    # ========================================================

    lines.append("")
    lines.append(
        "WEEK-BY-WEEK"
    )

    lines.append(
        "Date       | Gen  | Elite | Comp | Top %  | WR %    | Gen MA5 | Elite MA5"
    )

    lines.append(
        "-" * 78
    )


    for item in analysis[
        "weekly"
    ]:

        lines.append(
            f"{item['week_start']} | "
            f"{fmt(item['general']):>4} | "
            f"{fmt(item['elite']):>5} | "
            f"{fmt(item['composite']):>4} | "
            f"{fmt(item['top_percent']):>6} | "
            f"{fmt(item['wr_percentage'], 3):>7} | "
            f"{fmt(item['general_ma5']):>7} | "
            f"{fmt(item['elite_ma5']):>9}"
        )


    lines.append("")
    lines.append(
        "=" * 78
    )


    return "\n".join(
        lines
    )


# ============================================================
# MAIN
# ============================================================

def main():

    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )


    records = load_history()

    analysis = build_analysis(
        records
    )


    SUMMARY_FILE.write_text(
        json.dumps(
            analysis,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


    report = build_text_report(
        records,
        analysis
    )


    REPORT_FILE.write_text(
        report,
        encoding="utf-8"
    )


    print(
        report
    )

    print()
    print(
        f"Saved report: {REPORT_FILE}"
    )

    print(
        f"Saved summary: {SUMMARY_FILE}"
    )


if __name__ == "__main__":
    main()