import json
import re
from pathlib import Path


# ============================================================
# CONFIG
# ============================================================

DATA_DIR = Path("data")

CAR_DATABASE_FILE = (
    DATA_DIR
    / "car_names.json"
)

CAR_TECHNICAL_FILE = (
    DATA_DIR
    / "car_technical.json"
)


# ============================================================
# FALLBACK NAME DATABASE
# ============================================================

FALLBACK_CARS = {
    1563: "Renault Mégane Trophy '11",
    2157: "Aston Martin V8 Vantage Gr.4",
    2161: "Nissan GT-R Gr.4",
    2163: "Genesis Gr.4",
    2164: "Ford Mustang Gr.4",
    2166: "Alfa Romeo 4C Gr.4",
    3192: "Mercedes-Benz SLS AMG Gr.4",
    3231: "Volkswagen Scirocco Gr.4",
    3245: "BMW M4 Gr.4",
    3246: "Bugatti Veyron Gr.4",
    3247: "Chevrolet Corvette C7 Gr.4",
    3248: "GT by Citroën Gr.4",
    3249: "Dodge Viper Gr.4",
    3251: "Honda NSX Gr.4",
    3252: "Jaguar F-type Gr.4",
    3253: "Lamborghini Huracán Gr.4",
    3254: "Lexus RC F Gr.4",
    3256: "Mazda Atenza Gr.4",
    3257: "McLaren 650S Gr.4",
    3258: "Mitsubishi Lancer Evolution Final Gr.4",
    3259: "Peugeot RCZ Gr.4",
    3260: "Renault Mégane Gr.4",
    3261: "Subaru WRX Gr.4",
    3262: "Toyota 86 Gr.4",
    3263: "Ferrari 458 Italia Gr.4",
    3298: "Audi TT Cup '16",
    3310: "Porsche Cayman GT4 Clubsport '16",
    3352: "Toyota GR Supra Racing Concept '18",
    3399: "Toyota GR Supra Race Car '19",
    3477: "Nissan Silvia spec-R Aero (S15) Touring Car",
    3480: "Suzuki Swift Sport Gr.4",
    3501: "Genesis G70 GR4",
    3537: "Mazda3 Gr.4"
}


# ============================================================
# FALLBACK VALIDATED TECHNICAL DATABASE
#
# layout:
#   FF  = Front-engine / Front-wheel drive
#   FR  = Front-engine / Rear-wheel drive
#   MR  = Mid-engine / Rear-wheel drive
#   RR  = Rear-engine / Rear-wheel drive
#   4WD = Four-wheel drive
#
# Only validated entries belong here.
# ============================================================

FALLBACK_TECHNICAL = {

    # --------------------------------------------------------
    # Existing validated cars from the previous
    # CAR_TECHNICAL_INFO table
    # --------------------------------------------------------

    1563: {
        "layout": "MR",
        "validated": True,
        "source": "existing_validated_database"
    },

    2157: {
        "layout": "FR",
        "validated": True,
        "source": "existing_validated_database"
    },

    2161: {
        "layout": "4WD",
        "validated": True,
        "source": "existing_validated_database"
    },

    2163: {
        "layout": "FR",
        "validated": True,
        "source": "existing_validated_database"
    },

    2164: {
        "layout": "FR",
        "validated": True,
        "source": "existing_validated_database"
    },

    2166: {
        "layout": "MR",
        "validated": True,
        "source": "existing_validated_database"
    },

    3192: {
        "layout": "FR",
        "validated": True,
        "source": "existing_validated_database"
    },

    3231: {
        "layout": "FF",
        "validated": True,
        "source": "existing_validated_database"
    },

    3245: {
        "layout": "FR",
        "validated": True,
        "source": "existing_validated_database"
    },

    3246: {
        "layout": "4WD",
        "validated": True,
        "source": "existing_validated_database"
    },

    3247: {
        "layout": "FR",
        "validated": True,
        "source": "existing_validated_database"
    },

    3248: {
        "layout": "MR",
        "validated": True,
        "source": "existing_validated_database"
    },

    3249: {
        "layout": "FR",
        "validated": True,
        "source": "existing_validated_database"
    },

    3251: {
        "layout": "MR",
        "validated": True,
        "source": "existing_validated_database"
    },

    3252: {
        "layout": "FR",
        "validated": True,
        "source": "existing_validated_database"
    },

    3253: {
        "layout": "4WD",
        "validated": True,
        "source": "existing_validated_database"
    },

    3254: {
        "layout": "FR",
        "validated": True,
        "source": "existing_validated_database"
    },

    3256: {
        "layout": "4WD",
        "validated": True,
        "source": "existing_validated_database"
    },

    3257: {
        "layout": "MR",
        "validated": True,
        "source": "existing_validated_database"
    },

    3258: {
        "layout": "4WD",
        "validated": True,
        "source": "existing_validated_database"
    },

    3259: {
        "layout": "FF",
        "validated": True,
        "source": "existing_validated_database"
    },

    3260: {
        "layout": "FF",
        "validated": True,
        "source": "existing_validated_database"
    },

    3261: {
        "layout": "4WD",
        "validated": True,
        "source": "existing_validated_database"
    },

    3262: {
        "layout": "FR",
        "validated": True,
        "source": "existing_validated_database"
    },

    3263: {
        "layout": "MR",
        "validated": True,
        "source": "existing_validated_database"
    },

    3298: {
        "layout": "FF",
        "validated": True,
        "source": "existing_validated_database"
    },

    3310: {
        "layout": "MR",
        "validated": True,
        "source": "existing_validated_database"
    },

    3399: {
        "layout": "FR",
        "validated": True,
        "source": "existing_validated_database"
    },

    3477: {
        "layout": "FR",
        "validated": True,
        "source": "existing_validated_database"
    },

    3480: {
        "layout": "FF",
        "validated": True,
        "source": "existing_validated_database"
    },

    3501: {
        "layout": "4WD",
        "validated": True,
        "source": "existing_validated_database"
    },

    3537: {
        "layout": "FF",
        "validated": True,
        "source": "existing_validated_database"
    },

    # --------------------------------------------------------
    # Current Gr.3 additions
    # --------------------------------------------------------

    3405: {
        "layout": "MR",
        "validated": True,
        "source": "gran_turismo_official_car_list"
    }
}


VALID_LAYOUTS = {
    "FF",
    "FR",
    "MR",
    "RR",
    "4WD"
}


# ============================================================
# LOAD NAME DATABASE
# ============================================================

def load_car_database():

    database = dict(
        FALLBACK_CARS
    )

    if not CAR_DATABASE_FILE.exists():
        return database


    try:

        saved = json.loads(
            CAR_DATABASE_FILE.read_text(
                encoding="utf-8"
            )
        )


        if isinstance(
            saved,
            dict
        ):

            for key, value in saved.items():

                try:
                    car_code = int(key)

                except Exception:
                    continue


                if (
                    isinstance(value, str)
                    and value.strip()
                ):

                    database[
                        car_code
                    ] = value.strip()


    except Exception:
        pass


    return database


# ============================================================
# SAVE NAME DATABASE
# ============================================================

def save_car_database(
    database
):

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )


    clean = {}


    for car_code, name in database.items():

        try:
            car_code = int(
                car_code
            )

        except Exception:
            continue


        if (
            not isinstance(name, str)
            or not name.strip()
        ):
            continue


        clean[
            str(car_code)
        ] = name.strip()


    ordered = dict(
        sorted(
            clean.items(),
            key=lambda item:
                int(item[0])
        )
    )


    CAR_DATABASE_FILE.write_text(
        json.dumps(
            ordered,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


# ============================================================
# LOAD TECHNICAL DATABASE
# ============================================================

def load_car_technical_database():

    database = {
        int(car_code): dict(info)
        for car_code, info
        in FALLBACK_TECHNICAL.items()
    }


    if not CAR_TECHNICAL_FILE.exists():
        return database


    try:

        saved = json.loads(
            CAR_TECHNICAL_FILE.read_text(
                encoding="utf-8"
            )
        )


        if isinstance(
            saved,
            dict
        ):

            for raw_code, raw_info in saved.items():

                try:
                    car_code = int(
                        raw_code
                    )

                except Exception:
                    continue


                if not isinstance(
                    raw_info,
                    dict
                ):
                    continue


                layout = raw_info.get(
                    "layout"
                )


                if isinstance(
                    layout,
                    str
                ):
                    layout = (
                        layout
                        .strip()
                        .upper()
                    )


                if layout not in VALID_LAYOUTS:
                    continue


                database[
                    car_code
                ] = {
                    "layout":
                        layout,

                    "validated":
                        bool(
                            raw_info.get(
                                "validated",
                                True
                            )
                        ),

                    "source":
                        str(
                            raw_info.get(
                                "source",
                                "car_technical.json"
                            )
                        )
                }


    except Exception:
        pass


    return database


# ============================================================
# SAVE TECHNICAL DATABASE
# ============================================================

def save_car_technical_database(
    database
):

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )


    clean = {}


    for car_code, info in database.items():

        try:
            car_code = int(
                car_code
            )

        except Exception:
            continue


        if not isinstance(
            info,
            dict
        ):
            continue


        layout = info.get(
            "layout"
        )


        if isinstance(
            layout,
            str
        ):
            layout = (
                layout
                .strip()
                .upper()
            )


        if layout not in VALID_LAYOUTS:
            continue


        clean[
            str(car_code)
        ] = {
            "layout":
                layout,

            "validated":
                bool(
                    info.get(
                        "validated",
                        True
                    )
                ),

            "source":
                str(
                    info.get(
                        "source",
                        "manual"
                    )
                )
        }


    ordered = dict(
        sorted(
            clean.items(),
            key=lambda item:
                int(item[0])
        )
    )


    CAR_TECHNICAL_FILE.write_text(
        json.dumps(
            ordered,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


# ============================================================
# TECHNICAL LOOKUPS
# ============================================================

def get_car_technical_info(
    car_code,
    database=None
):

    if car_code is None:
        return None


    try:

        car_code = int(
            car_code
        )

    except Exception:

        return None


    if database is None:

        database = (
            load_car_technical_database()
        )


    info = database.get(
        car_code
    )


    if not isinstance(
        info,
        dict
    ):
        return None


    return dict(
        info
    )


def get_car_layout(
    car_code,
    database=None
):

    info = get_car_technical_info(
        car_code,
        database
    )


    if not info:
        return None


    if not info.get(
        "validated",
        False
    ):
        return None


    layout = info.get(
        "layout"
    )


    if layout not in VALID_LAYOUTS:
        return None


    return layout


def set_car_technical_info(
    car_code,
    layout,
    source="manual",
    validated=True
):

    try:

        car_code = int(
            car_code
        )

    except Exception:

        raise ValueError(
            "Invalid car code."
        )


    if not isinstance(
        layout,
        str
    ):

        raise ValueError(
            "Layout must be a string."
        )


    layout = (
        layout
        .strip()
        .upper()
    )


    if layout not in VALID_LAYOUTS:

        raise ValueError(
            f"Invalid layout: {layout}"
        )


    database = (
        load_car_technical_database()
    )


    database[
        car_code
    ] = {
        "layout":
            layout,

        "validated":
            bool(
                validated
            ),

        "source":
            str(
                source
            )
    }


    save_car_technical_database(
        database
    )


    return database[
        car_code
    ]


# ============================================================
# FIND JAVASCRIPT OBJECT
# ============================================================

def extract_javascript_object(
    html,
    variable_name
):

    if not html:
        return None


    pattern = re.compile(
        rf"\b(?:const|let|var)\s+"
        rf"{re.escape(variable_name)}\s*=\s*",
        re.MULTILINE
    )


    match = pattern.search(
        html
    )


    if not match:
        return None


    start = match.end()


    while (
        start < len(html)
        and html[start].isspace()
    ):
        start += 1


    if (
        start >= len(html)
        or html[start] != "{"
    ):
        return None


    try:

        decoder = json.JSONDecoder()

        value, _ = decoder.raw_decode(
            html[start:]
        )

        return value


    except Exception:

        return None


# ============================================================
# EXTRACT GTSH CAR NAME DATABASE
# ============================================================

def extract_car_database_from_html(
    html
):

    raw_database = (
        extract_javascript_object(
            html,
            "carNames"
        )
    )


    if not isinstance(
        raw_database,
        dict
    ):

        return {}


    result = {}


    for raw_code, name in raw_database.items():

        if not isinstance(
            raw_code,
            str
        ):
            continue


        if not isinstance(
            name,
            str
        ):
            continue


        code_match = re.search(
            r"(\d+)$",
            raw_code.strip()
        )


        if not code_match:
            continue


        car_code = int(
            code_match.group(1)
        )


        clean_name = (
            name
            .strip()
        )


        if clean_name:

            result[
                car_code
            ] = clean_name


    return result


# ============================================================
# UPDATE NAME DATABASE FROM HTML
# ============================================================

def update_car_database_from_html(
    html
):

    current = load_car_database()


    discovered = (
        extract_car_database_from_html(
            html
        )
    )


    added = 0
    updated = 0


    for car_code, name in discovered.items():

        previous = current.get(
            car_code
        )


        if previous is None:

            added += 1


        elif previous != name:

            updated += 1


        current[
            car_code
        ] = name


    save_car_database(
        current
    )


    return {
        "database":
            current,

        "discovered":
            len(discovered),

        "added":
            added,

        "updated":
            updated
    }


# ============================================================
# GET CAR NAME
# ============================================================

def get_car_name(
    car_code,
    database=None
):

    if car_code is None:
        return "Unknown car"


    try:

        car_code = int(
            car_code
        )


    except Exception:

        return (
            f"Unknown car ({car_code})"
        )


    if database is None:

        database = (
            load_car_database()
        )


    return database.get(
        car_code,
        f"Unknown car ({car_code})"
    )


# ============================================================
# DATABASE STATS
# ============================================================

def database_stats():

    names = (
        load_car_database()
    )

    technical = (
        load_car_technical_database()
    )


    validated_technical = sum(
        1
        for info
        in technical.values()
        if (
            isinstance(
                info,
                dict
            )
            and info.get(
                "validated"
            )
            and info.get(
                "layout"
            )
            in VALID_LAYOUTS
        )
    )


    return {
        "cars":
            len(names),

        "technical_records":
            len(technical),

        "validated_technical_records":
            validated_technical,

        "name_file":
            str(
                CAR_DATABASE_FILE
            ),

        "technical_file":
            str(
                CAR_TECHNICAL_FILE
            )
    }


# ============================================================
# TEST
# ============================================================

def main():

    name_database = (
        load_car_database()
    )

    technical_database = (
        load_car_technical_database()
    )


    save_car_database(
        name_database
    )

    save_car_technical_database(
        technical_database
    )


    stats = database_stats()


    print(
        "GT7 CAR DATABASE"
    )

    print(
        "=" * 70
    )

    print(
        f"Cars currently stored     : "
        f"{stats['cars']}"
    )

    print(
        f"Technical records         : "
        f"{stats['technical_records']}"
    )

    print(
        f"Validated technical       : "
        f"{stats['validated_technical_records']}"
    )

    print(
        f"Name database file        : "
        f"{stats['name_file']}"
    )

    print(
        f"Technical database file   : "
        f"{stats['technical_file']}"
    )


if __name__ == "__main__":
    main()