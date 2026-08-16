import math
from datetime import datetime


# ============================================================
# BASIC HELPERS
# ============================================================

def score_to_laptime(score):

    if score is None:
        return "N/A"

    score = int(round(score))

    minutes = score // 60000
    seconds = (score % 60000) // 1000
    milliseconds = score % 1000

    return f"{minutes}:{seconds:02d}.{milliseconds:03d}"


def parse_datetime(value):

    if not value:
        return None

    try:
        return datetime.fromisoformat(value)

    except Exception:
        return None


def linear_regression(points):

    if len(points) < 2:
        return None

    xs = [float(x) for x, _ in points]
    ys = [float(y) for _, y in points]

    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)

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
            for x, y in zip(xs, ys)
        )
        / denominator
    )

    intercept = (
        y_mean
        - slope * x_mean
    )

    residuals = [
        y
        - (
            slope * x
            + intercept
        )
        for x, y in zip(xs, ys)
    ]

    rmse = math.sqrt(
        sum(
            residual ** 2
            for residual in residuals
        )
        / len(residuals)
    )

    return {
        "slope": slope,
        "intercept": intercept,
        "rmse": rmse
    }


# ============================================================
# SNAPSHOT METRICS
# ============================================================

def threshold_score(snapshot, rank):

    value = (
        snapshot
        .get("thresholds", {})
        .get(str(rank))
    )

    if isinstance(value, dict):
        return value.get("score")

    if isinstance(value, (int, float)):
        return value

    return None


def world_record_score(snapshot):

    return (
        snapshot
        .get("world_record", {})
        .get("score")
    )


def personal_score(snapshot):

    result = snapshot.get("my_result")

    if not result:
        return None

    return result.get("score")


def personal_rank(snapshot):

    result = snapshot.get("my_result")

    if not result:
        return None

    return result.get("rank")


# ============================================================
# CURRENT-WEEK SNAPSHOTS
# ============================================================

def current_week_snapshots(
    history,
    current_snapshot
):

    current_url = (
        current_snapshot
        .get("race", {})
        .get("leaderboard_url")
    )

    combined = (
        list(history)
        + [current_snapshot]
    )

    selected = []
    seen = set()

    for snapshot in combined:

        url = (
            snapshot
            .get("race", {})
            .get("leaderboard_url")
        )

        if url != current_url:
            continue

        timestamp_text = snapshot.get(
            "timestamp"
        )

        timestamp = parse_datetime(
            timestamp_text
        )

        if not timestamp:
            continue

        if timestamp_text in seen:
            continue

        seen.add(
            timestamp_text
        )

        selected.append(
            snapshot
        )

    selected.sort(
        key=lambda item:
            parse_datetime(
                item["timestamp"]
            )
    )

    return selected


# ============================================================
# TIME AXIS
# ============================================================

def build_time_axis(
    snapshots,
    race_start
):

    output = []

    for snapshot in snapshots:

        timestamp = parse_datetime(
            snapshot.get("timestamp")
        )

        if not timestamp:
            continue

        hours = (
            timestamp
            - race_start
        ).total_seconds() / 3600

        output.append(
            (
                hours,
                snapshot
            )
        )

    return output


# ============================================================
# GENERIC FORECAST
# ============================================================

def forecast_metric(
    snapshots,
    race_start,
    target_time,
    extractor,
    direction="down"
):

    axis = build_time_axis(
        snapshots,
        race_start
    )

    points = []

    for hours, snapshot in axis:

        value = extractor(
            snapshot
        )

        if isinstance(
            value,
            (int, float)
        ):

            points.append(
                (
                    hours,
                    float(value)
                )
            )

    if len(points) < 3:
        return None

    regression = linear_regression(
        points
    )

    if not regression:
        return None

    span_hours = (
        max(x for x, _ in points)
        - min(x for x, _ in points)
    )

    slope = regression[
        "slope"
    ]

    if direction == "down":
        slope = min(
            slope,
            0
        )

    elif direction == "up":
        slope = max(
            slope,
            0
        )

    target_x = (
        target_time
        - race_start
    ).total_seconds() / 3600

    predicted = (
        regression["intercept"]
        + slope * target_x
    )

    current_value = points[-1][1]

    if direction == "down":
        predicted = min(
            predicted,
            current_value
        )

    elif direction == "up":
        predicted = max(
            predicted,
            current_value
        )

    if (
        len(points) >= 10
        and span_hours >= 72
    ):
        confidence = "HIGH"

    elif (
        len(points) >= 6
        and span_hours >= 24
    ):
        confidence = "MEDIUM"

    else:
        confidence = "LOW"

    return {
        "predicted":
            predicted,

        "current":
            current_value,

        "slope_per_hour":
            slope,

        "rmse":
            regression["rmse"],

        "samples":
            len(points),

        "span_hours":
            span_hours,

        "confidence":
            confidence
    }


# ============================================================
# RANK / PERCENTILE HELPERS
# ============================================================

def score_at_rank(
    ranking,
    rank
):

    if not ranking:
        return None

    rank = max(
        1,
        min(
            len(ranking),
            int(rank)
        )
    )

    return ranking[
        rank - 1
    ].get("score")


def percentile_rank(
    total,
    percent
):

    return max(
        1,
        min(
            total,
            math.ceil(
                total
                * percent
                / 100
            )
        )
    )


def current_percentile_score(
    ranking,
    percent
):

    rank = percentile_rank(
        len(ranking),
        percent
    )

    return {
        "rank":
            rank,

        "score":
            score_at_rank(
                ranking,
                rank
            )
    }


# ============================================================
# PERCENTILE FORECAST
# ============================================================

def projected_percentile_score(
    ranking,
    top500_forecast,
    top1000_forecast,
    percent
):

    current = current_percentile_score(
        ranking,
        percent
    )

    current_score = current[
        "score"
    ]

    if current_score is None:
        return None

    projected_deltas = []

    if top500_forecast:

        projected_deltas.append(
            top500_forecast["predicted"]
            - top500_forecast["current"]
        )

    if top1000_forecast:

        projected_deltas.append(
            top1000_forecast["predicted"]
            - top1000_forecast["current"]
        )

    expected_delta = (
        sum(projected_deltas)
        / len(projected_deltas)
        if projected_deltas
        else 0
    )

    return {
        "current_rank":
            current["rank"],

        "current_score":
            current_score,

        "predicted_score":
            int(
                round(
                    current_score
                    + expected_delta
                )
            ),

        "estimated_change_ms":
            int(
                round(
                    expected_delta
                )
            )
    }


# ============================================================
# DRIVER RANK FORECAST
# ============================================================

def rank_forecast(
    snapshots,
    current_snapshot,
    race_start,
    target_time
):

    current_result = (
        current_snapshot
        .get("my_result")
    )

    if not current_result:

        return None

    current_personal_score = (
        current_result.get("score")
    )

    current_personal_rank = (
        current_result.get("rank")
    )

    if (
        current_personal_score is None
        or current_personal_rank is None
    ):

        return None

    comparable = []

    for snapshot in snapshots:

        score = personal_score(
            snapshot
        )

        rank = personal_rank(
            snapshot
        )

        timestamp = parse_datetime(
            snapshot.get("timestamp")
        )

        if (
            score == current_personal_score
            and isinstance(
                rank,
                (int, float)
            )
            and timestamp
        ):

            comparable.append(
                snapshot
            )

    if len(comparable) < 3:

        return {
            "current_rank":
                current_personal_rank,

            "projected_rank":
                None,

            "confidence":
                "INSUFFICIENT",

            "samples":
                len(comparable),

            "span_hours":
                0
        }

    forecast = forecast_metric(
        comparable,
        race_start,
        target_time,
        extractor=personal_rank,
        direction="up"
    )

    if not forecast:
        return None

    projected_rank = max(
        current_personal_rank,
        int(
            round(
                forecast["predicted"]
            )
        )
    )

    return {
        "current_rank":
            current_personal_rank,

        "projected_rank":
            projected_rank,

        "confidence":
            forecast["confidence"],

        "samples":
            forecast["samples"],

        "span_hours":
            forecast["span_hours"],

        "rank_growth_per_hour":
            forecast["slope_per_hour"]
    }


# ============================================================
# TOTAL DRIVERS FORECAST
# ============================================================

def total_driver_forecast(
    snapshots,
    race_start,
    target_time
):

    forecast = forecast_metric(
        snapshots,
        race_start,
        target_time,
        extractor=lambda snapshot:
            snapshot.get(
                "total_drivers"
            ),
        direction="up"
    )

    if not forecast:
        return None

    return {
        "current":
            int(
                round(
                    forecast["current"]
                )
            ),

        "predicted":
            int(
                round(
                    forecast["predicted"]
                )
            ),

        "confidence":
            forecast["confidence"],

        "samples":
            forecast["samples"]
    }


# ============================================================
# OVERALL CONFIDENCE
# ============================================================

def overall_confidence(
    forecasts
):

    values = {
        "HIGH": 3,
        "MEDIUM": 2,
        "LOW": 1
    }

    scores = []

    for forecast in forecasts:

        if not forecast:
            continue

        confidence = forecast.get(
            "confidence"
        )

        if confidence in values:

            scores.append(
                values[
                    confidence
                ]
            )

    if not scores:
        return "LOW"

    average = (
        sum(scores)
        / len(scores)
    )

    if average >= 2.5:
        return "HIGH"

    if average >= 1.5:
        return "MEDIUM"

    return "LOW"


# ============================================================
# FORECAST V2
# ============================================================

def build_forecast_v2(
    history,
    current_snapshot,
    ranking,
    race_start,
    sunday_end
):

    snapshots = current_week_snapshots(
        history,
        current_snapshot
    )

    if len(snapshots) < 3:

        return {
            "available":
                False,

            "reason":
                "Fewer than 3 comparable current-week snapshots."
        }

    wr_forecast = forecast_metric(
        snapshots,
        race_start,
        sunday_end,
        extractor=world_record_score,
        direction="down"
    )

    top100_forecast = forecast_metric(
        snapshots,
        race_start,
        sunday_end,
        extractor=lambda snapshot:
            threshold_score(
                snapshot,
                100
            ),
        direction="down"
    )

    top500_forecast = forecast_metric(
        snapshots,
        race_start,
        sunday_end,
        extractor=lambda snapshot:
            threshold_score(
                snapshot,
                500
            ),
        direction="down"
    )

    top1000_forecast = forecast_metric(
        snapshots,
        race_start,
        sunday_end,
        extractor=lambda snapshot:
            threshold_score(
                snapshot,
                1000
            ),
        direction="down"
    )

    top10 = projected_percentile_score(
        ranking,
        top500_forecast,
        top1000_forecast,
        10
    )

    top5 = projected_percentile_score(
        ranking,
        top500_forecast,
        top1000_forecast,
        5
    )

    total_forecast = total_driver_forecast(
        snapshots,
        race_start,
        sunday_end
    )

    personal_rank_projection = rank_forecast(
        snapshots,
        current_snapshot,
        race_start,
        sunday_end
    )

    current_result = (
        current_snapshot
        .get("my_result")
    )

    personal = None

    if current_result:

        current_score = (
            current_result.get("score")
        )

        current_rank = (
            current_result.get("rank")
        )

        current_top_percent = (
            current_result.get(
                "top_percent"
            )
        )

        projected_rank = None
        projected_top_percent = None

        if personal_rank_projection:

            projected_rank = (
                personal_rank_projection
                .get(
                    "projected_rank"
                )
            )

        if (
            projected_rank is not None
            and total_forecast
        ):

            projected_total = max(
                total_forecast["predicted"],
                projected_rank
            )

            projected_top_percent = (
                projected_rank
                / projected_total
                * 100
            )

        personal = {
            "score":
                current_score,

            "current_rank":
                current_rank,

            "current_top_percent":
                current_top_percent,

            "projected_rank":
                projected_rank,

            "projected_top_percent":
                projected_top_percent,

            "rank_forecast_confidence":
                (
                    personal_rank_projection
                    .get(
                        "confidence"
                    )
                    if personal_rank_projection
                    else "INSUFFICIENT"
                )
        }

    targets = {}

    if (
        current_result
        and current_result.get("score")
    ):

        current_score = (
            current_result["score"]
        )

        if top10:

            targets["top10"] = {
                "score":
                    top10[
                        "predicted_score"
                    ],

                "gain_needed_ms":
                    max(
                        0,
                        current_score
                        - top10[
                            "predicted_score"
                        ]
                    )
            }

        if top5:

            targets["top5"] = {
                "score":
                    top5[
                        "predicted_score"
                    ],

                "gain_needed_ms":
                    max(
                        0,
                        current_score
                        - top5[
                            "predicted_score"
                        ]
                    )
            }

    confidence = overall_confidence(
        [
            wr_forecast,
            top100_forecast,
            top500_forecast,
            top1000_forecast,
            total_forecast
        ]
    )

    timestamps = [
        parse_datetime(
            snapshot.get(
                "timestamp"
            )
        )
        for snapshot in snapshots
    ]

    timestamps = [
        timestamp
        for timestamp in timestamps
        if timestamp
    ]

    span_hours = 0

    if len(timestamps) >= 2:

        span_hours = (
            max(timestamps)
            - min(timestamps)
        ).total_seconds() / 3600

    return {
        "available":
            True,

        "model":
            "CURRENT_WEEK_HYBRID_V2",

        "historical_training":
            "INSUFFICIENT",

        "samples":
            len(snapshots),

        "span_hours":
            span_hours,

        "confidence":
            confidence,

        "world_record":
            wr_forecast,

        "top100":
            top100_forecast,

        "top500":
            top500_forecast,

        "top1000":
            top1000_forecast,

        "top10_percent":
            top10,

        "top5_percent":
            top5,

        "total_drivers":
            total_forecast,

        "personal":
            personal,

        "targets":
            targets
    }


# ============================================================
# REPORT OUTPUT
# ============================================================

def forecast_report_lines(
    forecast
):

    lines = []

    lines.append(
        "FORECAST TO SUNDAY - V2"
    )

    if not forecast.get(
        "available"
    ):

        lines.append(
            forecast.get(
                "reason",
                "Forecast unavailable."
            )
        )

        return lines

    lines.append(
        f"Model           : "
        f"{forecast['model']}"
    )

    lines.append(
        f"Confidence      : "
        f"{forecast['confidence']}"
    )

    lines.append(
        f"Samples         : "
        f"{forecast['samples']}"
    )

    lines.append(
        f"Observed span   : "
        f"{forecast['span_hours']:.1f} h"
    )

    lines.append(
        "Historical model: not yet active "
        "(insufficient cross-week training data)"
    )

    lines.append("")
    lines.append(
        "PROJECTED LEADERBOARD"
    )

    metrics = [
        (
            "world_record",
            "WR"
        ),
        (
            "top100",
            "Top 100"
        ),
        (
            "top500",
            "Top 500"
        ),
        (
            "top1000",
            "Top 1000"
        )
    ]

    for key, label in metrics:

        item = forecast.get(
            key
        )

        if not item:
            continue

        lines.append(
            f"{label:<15}: "
            f"{score_to_laptime(item['predicted'])} | "
            f"{item['confidence']} | "
            f"{item['samples']} samples"
        )

    top10 = forecast.get(
        "top10_percent"
    )

    if top10:

        lines.append(
            f"{'Top 10%':<15}: "
            f"{score_to_laptime(top10['predicted_score'])}"
        )

    top5 = forecast.get(
        "top5_percent"
    )

    if top5:

        lines.append(
            f"{'Top 5%':<15}: "
            f"{score_to_laptime(top5['predicted_score'])}"
        )

    total = forecast.get(
        "total_drivers"
    )

    if total:

        lines.append(
            f"{'Drivers':<15}: "
            f"{total['current']:,} -> "
            f"~{total['predicted']:,}"
        )

    personal = forecast.get(
        "personal"
    )

    if personal:

        lines.append("")
        lines.append(
            "IF YOU DO NOT IMPROVE"
        )

        lines.append(
            f"Current time    : "
            f"{score_to_laptime(personal['score'])}"
        )

        lines.append(
            f"Current rank    : "
            f"#{personal['current_rank']:,}"
        )

        if (
            personal[
                "current_top_percent"
            ]
            is not None
        ):

            lines.append(
                f"Current Top %   : "
                f"{personal['current_top_percent']:.2f}%"
            )

        if (
            personal[
                "projected_rank"
            ]
            is not None
        ):

            lines.append(
                f"Projected rank  : "
                f"~#{personal['projected_rank']:,}"
            )

        else:

            lines.append(
                "Projected rank  : "
                "insufficient comparable rank history"
            )

        if (
            personal[
                "projected_top_percent"
            ]
            is not None
        ):

            lines.append(
                f"Projected Top % : "
                f"~{personal['projected_top_percent']:.2f}%"
            )

        lines.append(
            f"Rank confidence : "
            f"{personal['rank_forecast_confidence']}"
        )

    targets = forecast.get(
        "targets",
        {}
    )

    if targets:

        lines.append("")
        lines.append(
            "TARGETS FOR SUNDAY"
        )

        if "top10" in targets:

            target = (
                targets[
                    "top10"
                ]
            )

            lines.append(
                f"Top 10% target  : "
                f"{score_to_laptime(target['score'])} | "
                f"gain needed "
                f"{target['gain_needed_ms']/1000:.3f}s"
            )

        if "top5" in targets:

            target = (
                targets[
                    "top5"
                ]
            )

            lines.append(
                f"Top 5% target   : "
                f"{score_to_laptime(target['score'])} | "
                f"gain needed "
                f"{target['gain_needed_ms']/1000:.3f}s"
            )

    lines.append("")
    lines.append(
        "Forecast note   : "
        "V2 uses current-week leaderboard evolution. "
        "Cross-week historical learning will activate "
        "after sufficient multi-week intraday data exists."
    )

    return lines