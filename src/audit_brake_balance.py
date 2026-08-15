import json
from pathlib import Path

from car_database import load_car_database


# ============================================================
# CONFIG
# ============================================================

DATA_DIR = Path("data")

REPORT_FILE = (
    DATA_DIR
    / "brake_balance_audit.txt"
)

JSON_FILE = (
    DATA_DIR
    / "brake_balance_audit.json"
)


# ============================================================
# ORIGINAL BRAKE BASELINES
# ============================================================

BRAKE_BASELINES = {

    1563: {
        "expected_name": "Renault Mégane Trophy '11",
        "layout": "MR",
        "qual_bb": 0,
        "race_bb": -1
    },

    2157: {
        "expected_name": "Aston Martin V8 Vantage Gr.4",
        "layout": "FR",
        "qual_bb": 1,
        "race_bb": 2
    },

    2161: {
        "expected_name": "Nissan GT-R Gr.4",
        "layout": "4WD",
        "qual_bb": 2,
        "race_bb": 3
    },

    2163: {
        "expected_name": "Genesis Gr.4",
        "layout": "FR",
        "qual_bb": 1,
        "race_bb": 2
    },

    2164: {
        "expected_name": "Ford Mustang Gr.4",
        "layout": "FR",
        "qual_bb": 1,
        "race_bb": 2
    },

    2166: {
        "expected_name": "Alfa Romeo 4C Gr.4",
        "layout": "MR",
        "qual_bb": 0,
        "race_bb": -1
    },

    3192: {
        "expected_name": "Mercedes-Benz SLS AMG Gr.4",
        "layout": "FR",
        "qual_bb": 1,
        "race_bb": 2
    },

    3231: {
        "expected_name": "Volkswagen Scirocco Gr.4",
        "layout": "FF",
        "qual_bb": 3,
        "race_bb": 4
    },

    3245: {
        "expected_name": "BMW M4 Gr.4",
        "layout": "FR",
        "qual_bb": 1,
        "race_bb": 2
    },

    3246: {
        "expected_name": "Bugatti Veyron Gr.4",
        "layout": "4WD",
        "qual_bb": 2,
        "race_bb": 3
    },

    3247: {
        "expected_name": "Chevrolet Corvette C7 Gr.4",
        "layout": "FR",
        "qual_bb": 1,
        "race_bb": 2
    },

    3248: {
        "expected_name": "GT by Citroën Gr.4",
        "layout": "MR",
        "qual_bb": 0,
        "race_bb": -1
    },

    3249: {
        "expected_name": "Dodge Viper Gr.4",
        "layout": "FR",
        "qual_bb": 1,
        "race_bb": 2
    },

    3251: {
        "expected_name": "Honda NSX Gr.4",
        "layout": "MR",
        "qual_bb": -1,
        "race_bb": -2
    },

    3252: {
        "expected_name": "Jaguar F-type Gr.4",
        "layout": "FR",
        "qual_bb": 1,
        "race_bb": 2
    },

    3253: {
        "expected_name": "Lamborghini Huracán Gr.4",
        "layout": "4WD",
        "qual_bb": 1,
        "race_bb": 2
    },

    3254: {
        "expected_name": "Lexus RC F Gr.4",
        "layout": "FR",
        "qual_bb": 1,
        "race_bb": 2
    },

    3256: {
        "expected_name": "Mazda Atenza Gr.4",
        "layout": "4WD",
        "qual_bb": 2,
        "race_bb": 3
    },

    3257: {
        "expected_name": "McLaren 650S Gr.4",
        "layout": "MR",
        "qual_bb": -1,
        "race_bb": -2
    },

    3258: {
        "expected_name": "Mitsubishi Lancer Evolution Final Gr.4",
        "layout": "4WD",
        "qual_bb": 2,
        "race_bb": 3
    },

    3259: {
        "expected_name": "Peugeot RCZ Gr.4",
        "layout": "FF",
        "qual_bb": 3,
        "race_bb": 4
    },

    3260: {
        "expected_name": "Renault Mégane Gr.4",
        "layout": "FF",
        "qual_bb": 3,
        "race_bb": 4
    },

    3261: {
        "expected_name": "Subaru WRX Gr.4",
        "layout": "4WD",
        "qual_bb": 2,
        "race_bb": 3
    },

    3262: {
        "expected_name": "Toyota 86 Gr.4",
        "layout": "FR",
        "qual_bb": 1,
        "race_bb": 2
    },

    3263: {
        "expected_name": "Ferrari 458 Italia Gr.4",
        "layout": "MR",
        "qual_bb": -1,
        "race_bb": -2
    },

    3298: {
        "expected_name": "Audi TT Cup '16",
        "layout": "FF",
        "qual_bb": 3,
        "race_bb": 4
    },

    3310: {
        "expected_name": "Porsche Cayman GT4 Clubsport '16",
        "layout": "MR",
        "qual_bb": -1,
        "race_bb": -2
    },

    3399: {
        "expected_name": "Toyota GR Supra Race Car '19",
        "layout": "FR",
        "qual_bb": 1,
        "race_bb": 2
    },

    3477: {
        "expected_name": "Nissan Silvia spec-R Aero (S15) Touring Car",
        "layout": "FR",
        "qual_bb": 1,
        "race_bb": 2
    },

    3480: {
        "expected_name": "Suzuki Swift Sport Gr.4",
        "layout": "FF",
        "qual_bb": 3,
        "race_bb": 4
    },

    3501: {
        "expected_name": "Genesis G70 GR4",
        "layout": "FR",
        "qual_bb": 1,
        "race_bb": 2
    },

    3537: {
        "expected_name": "Mazda3 Gr.4",
        "layout": "FF",
        "qual_bb": 3,
        "race_bb": 4
    }
}


# ============================================================
# NAME NORMALIZATION
# ============================================================

def normalize_name(text):

    if not isinstance(
        text,
        str
    ):
        return ""

    text = text.lower()

    replacements = [
        ("gr.4", ""),
        ("gr4", ""),
        ("'", ""),
        ('"', ""),
        ("-", " "),
        ("  ", " ")
    ]

    for old, new in replacements:

        text = text.replace(
            old,
            new
        )

    return " ".join(
        text.split()
    )


def compare_names(
    expected,
    current
):

    if expected == current:

        return "EXACT"

    expected_normalized = normalize_name(
        expected
    )

    current_normalized = normalize_name(
        current
    )

    if (
        expected_normalized
        == current_normalized
    ):

        return "NORMALIZED_MATCH"

    if (
        expected_normalized
        and expected_normalized
        in current_normalized
    ):

        return "CURRENT_NAME_EXTENDS_EXPECTED"

    if (
        current_normalized
        and current_normalized
        in expected_normalized
    ):

        return "EXPECTED_NAME_EXTENDS_CURRENT"

    return "MISMATCH"


# ============================================================
# MAIN
# ============================================================

def main():

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    database = load_car_database()

    results = []

    exact = 0
    normalized = 0
    extensions = 0
    mismatches = 0
    missing = 0


    for (
        car_code,
        baseline
    ) in BRAKE_BASELINES.items():

        expected_name = baseline[
            "expected_name"
        ]

        current_name = database.get(
            car_code
        )

        if current_name is None:

            status = (
                "CODE_NOT_IN_CENTRAL_DATABASE"
            )

            missing += 1

        else:

            status = compare_names(
                expected_name,
                current_name
            )

            if status == "EXACT":

                exact += 1

            elif status == "NORMALIZED_MATCH":

                normalized += 1

            elif status in (
                "CURRENT_NAME_EXTENDS_EXPECTED",
                "EXPECTED_NAME_EXTENDS_CURRENT"
            ):

                extensions += 1

            else:

                mismatches += 1


        results.append({
            "car_code":
                car_code,

            "expected_name":
                expected_name,

            "current_name":
                current_name,

            "name_status":
                status,

            "layout":
                baseline[
                    "layout"
                ],

            "qual_bb":
                baseline[
                    "qual_bb"
                ],

            "race_bb":
                baseline[
                    "race_bb"
                ]
        })


    structured = {
        "central_database_size":
            len(database),

        "brake_baselines":
            len(BRAKE_BASELINES),

        "exact_matches":
            exact,

        "normalized_matches":
            normalized,

        "name_extensions":
            extensions,

        "mismatches":
            mismatches,

        "missing_codes":
            missing,

        "results":
            results
    }


    JSON_FILE.write_text(
        json.dumps(
            structured,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


    lines = []

    lines.append(
        "GT7 BRAKE BALANCE DATABASE AUDIT"
    )

    lines.append(
        "=" * 82
    )

    lines.append(
        f"Central car database : "
        f"{len(database)}"
    )

    lines.append(
        f"Brake baselines      : "
        f"{len(BRAKE_BASELINES)}"
    )

    lines.append(
        f"Exact name matches   : "
        f"{exact}"
    )

    lines.append(
        f"Normalized matches   : "
        f"{normalized}"
    )

    lines.append(
        f"Name extensions      : "
        f"{extensions}"
    )

    lines.append(
        f"Name mismatches      : "
        f"{mismatches}"
    )

    lines.append(
        f"Missing car codes    : "
        f"{missing}"
    )


    lines.append("")

    lines.append(
        "BASELINE AUDIT"
    )

    lines.append(
        "-" * 82
    )


    for item in results:

        lines.append(
            f"{item['car_code']} | "
            f"{item['name_status']} | "
            f"{item['expected_name']} "
            f"-> "
            f"{item['current_name']} | "
            f"{item['layout']} | "
            f"Q {item['qual_bb']:+d} | "
            f"R {item['race_bb']:+d}"
        )


    lines.append("")

    lines.append(
        "ITEMS REQUIRING REVIEW"
    )

    lines.append(
        "-" * 82
    )


    review_items = [
        item
        for item in results
        if item[
            "name_status"
        ] not in (
            "EXACT",
            "NORMALIZED_MATCH"
        )
    ]


    if review_items:

        for item in review_items:

            lines.append(
                f"Code {item['car_code']} | "
                f"{item['name_status']} | "
                f"OLD: {item['expected_name']} | "
                f"CURRENT: {item['current_name']}"
            )

    else:

        lines.append(
            "None."
        )


    lines.append("")

    lines.append(
        "IMPORTANT"
    )

    lines.append(
        "-" * 82
    )

    lines.append(
        "This audit verifies code-to-name consistency only."
    )

    lines.append(
        "It does NOT prove that layout or brake-balance "
        "recommendations are technically optimal."
    )

    lines.append(
        "Technical metadata must be audited separately "
        "before being treated as validated."
    )


    lines.append("")

    lines.append(
        "=" * 82
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