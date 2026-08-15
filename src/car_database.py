import json
from pathlib import Path


# ============================================================
# CONFIG
# ============================================================

DATA_DIR = Path("data")

CAR_DATABASE_FILE = (
    DATA_DIR
    / "car_names.json"
)


# ============================================================
# BUILT-IN FALLBACK
#
# Apenas uma proteção mínima.
# A base principal será extraída automaticamente do GTSH-Rank.
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
# LOAD SAVED DATABASE
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
# SAVE DATABASE
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
# EXTRACT carNames FROM GTSH HTML
# ============================================================

def extract_car_database_from_html(
    html
):

    if not html:
        return {}


    markers = [
        "const carNames = ",
        "let carNames = ",
        "var carNames = "
    ]


    raw_database = None


    for marker in markers:

        start = html.find(
            marker
        )

        if start == -1:
            continue


        start += len(
            marker
        )


        try:

            decoder = (
                json.JSONDecoder()
            )


            raw_database, _ = (
                decoder.raw_decode(
                    html[
                        start:
                    ].lstrip()
                )
            )


            break

        except Exception:
            raw_database = None


    if not isinstance(
        raw_database,
        dict
    ):

        return {}


    result = {}


    for raw_code, name in (
        raw_database.items()
    ):

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


        # GTSH normally uses:
        #
        # "#CAR3248"
        #
        # Convert it to:
        #
        # 3248

        cleaned_code = (
            raw_code
            .upper()
            .replace(
                "#CAR",
                ""
            )
            .strip()
        )


        if not cleaned_code.isdigit():
            continue


        car_code = int(
            cleaned_code
        )


        result[
            car_code
        ] = name.strip()


    return result


# ============================================================
# UPDATE DATABASE FROM HTML
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


    for car_code, name in (
        discovered.items()
    ):

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


    if discovered:

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
# DATABASE HEALTH
# ============================================================

def database_stats():

    database = load_car_database()


    return {
        "cars":
            len(database),

        "file":
            str(
                CAR_DATABASE_FILE
            )
    }


# ============================================================
# STANDALONE TEST
# ============================================================

def main():

    database = load_car_database()


    print(
        "GT7 CAR DATABASE"
    )

    print(
        "=" * 70
    )

    print(
        f"Cars currently stored: "
        f"{len(database)}"
    )

    print(
        f"Database file: "
        f"{CAR_DATABASE_FILE}"
    )

    print()


    for car_code, name in list(
        sorted(
            database.items()
        )
    )[:20]:

        print(
            f"{car_code}: {name}"
        )


if __name__ == "__main__":
    main()