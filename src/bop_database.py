import json
from pathlib import Path
from datetime import datetime


# ============================================================
# CONFIG
# ============================================================

DATA_DIR = Path("data") / "bop_lab"

DATABASE_FILE = (
    DATA_DIR
    / "bop_database.json"
)


DATABASE_VERSION = "1.0"


VALID_GROUPS = {
    "GR.1",
    "GR.2",
    "GR.3",
    "GR.4",
    "GR.B",
}


VALID_SPEED_CLASSES = {
    "HIGH",
    "MID",
    "LOW",
}


# ============================================================
# BASIC HELPERS
# ============================================================

def now_iso():

    return (
        datetime.now()
        .astimezone()
        .isoformat()
    )


def safe_float(value):

    if value is None:
        return None

    if isinstance(
        value,
        (int, float)
    ):
        return float(value)

    if isinstance(
        value,
        str
    ):

        value = (
            value
            .strip()
            .replace(",", "")
        )

        if not value:
            return None

        try:
            return float(value)

        except ValueError:
            return None

    return None


def safe_int(value):

    number = safe_float(
        value
    )

    if number is None:
        return None

    return int(
        round(number)
    )


def normalize_group(value):

    if value is None:
        return None

    text = (
        str(value)
        .strip()
        .upper()
        .replace(" ", "")
    )


    aliases = {

        "GR1":
            "GR.1",

        "GR.1":
            "GR.1",

        "GR2":
            "GR.2",

        "GR.2":
            "GR.2",

        "GR3":
            "GR.3",

        "GR.3":
            "GR.3",

        "GR4":
            "GR.4",

        "GR.4":
            "GR.4",

        "GRB":
            "GR.B",

        "GR.B":
            "GR.B",
    }


    return aliases.get(
        text
    )


def normalize_speed_class(
    value
):

    if value is None:
        return None


    text = (
        str(value)
        .strip()
        .upper()
    )


    aliases = {

        "HIGH":
            "HIGH",

        "HIGH SPEED":
            "HIGH",

        "HIGH-SPEED":
            "HIGH",

        "MID":
            "MID",

        "MEDIUM":
            "MID",

        "MID SPEED":
            "MID",

        "MID-SPEED":
            "MID",

        "MEDIUM SPEED":
            "MID",

        "LOW":
            "LOW",

        "LOW SPEED":
            "LOW",

        "LOW-SPEED":
            "LOW",
    }


    return aliases.get(
        text
    )


def normalize_car_name(
    value
):

    if value is None:
        return None


    text = str(
        value
    ).strip()


    if not text:
        return None


    return text


# ============================================================
# EMPTY DATABASE
# ============================================================

def empty_database():

    return {

        "schema_version":
            DATABASE_VERSION,

        "created_at":
            now_iso(),

        "updated_at":
            now_iso(),

        "records":
            []
    }


# ============================================================
# LOAD DATABASE
# ============================================================

def load_database():

    if not DATABASE_FILE.exists():

        return empty_database()


    try:

        data = json.loads(
            DATABASE_FILE.read_text(
                encoding="utf-8"
            )
        )

    except Exception:

        return empty_database()


    if not isinstance(
        data,
        dict
    ):

        return empty_database()


    records = data.get(
        "records"
    )


    if not isinstance(
        records,
        list
    ):

        records = []


    data[
        "records"
    ] = records


    if not data.get(
        "schema_version"
    ):

        data[
            "schema_version"
        ] = DATABASE_VERSION


    return data


# ============================================================
# SAVE DATABASE
# ============================================================

def save_database(
    database
):

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )


    database[
        "updated_at"
    ] = now_iso()


    if not database.get(
        "created_at"
    ):

        database[
            "created_at"
        ] = now_iso()


    database[
        "schema_version"
    ] = DATABASE_VERSION


    DATABASE_FILE.write_text(

        json.dumps(
            database,
            ensure_ascii=False,
            indent=2
        ),

        encoding="utf-8"
    )


# ============================================================
# RECORD KEY
# ============================================================

def record_key(
    record
):

    return (

        normalize_car_name(
            record.get(
                "car"
            )
        ),

        normalize_group(
            record.get(
                "group"
            )
        ),

        str(
            record.get(
                "bop_version"
            )
            or ""
        ).strip(),

        normalize_speed_class(
            record.get(
                "speed_class"
            )
        )
    )


# ============================================================
# BUILD RECORD
# ============================================================

def build_record(
    car,
    group,
    bop_version,
    speed_class,
    power_hp=None,
    torque_nm=None,
    weight_kg=None,
    pp=None,
    weight_balance=None,
    drivetrain=None,
    aspiration=None,
    displacement=None,
    engine_model=None,
    powertrain=None,
    acceleration_0_400=None,
    acceleration_0_1000=None,
    acceleration_100_150=None,
    rotational_g_60=None,
    rotational_g_120=None,
    rotational_g_240=None,
    stability_low_speed=None,
    stability_high_speed=None,
    source=None,
    source_url=None,
    source_confidence=None,
):

    car = normalize_car_name(
        car
    )

    group = normalize_group(
        group
    )

    speed_class = (
        normalize_speed_class(
            speed_class
        )
    )


    if not car:

        raise ValueError(
            "Car name is required."
        )


    if group not in VALID_GROUPS:

        raise ValueError(
            f"Invalid group: {group}"
        )


    if (
        speed_class
        not in VALID_SPEED_CLASSES
    ):

        raise ValueError(
            "speed_class must be "
            "HIGH, MID or LOW."
        )


    bop_version = str(
        bop_version
        or ""
    ).strip()


    if not bop_version:

        raise ValueError(
            "BoP version is required."
        )


    power_hp = safe_float(
        power_hp
    )

    torque_nm = safe_float(
        torque_nm
    )

    weight_kg = safe_float(
        weight_kg
    )


    power_weight_hp_t = None
    weight_power_kg_hp = None


    if (
        power_hp is not None
        and weight_kg is not None
        and power_hp > 0
        and weight_kg > 0
    ):

        power_weight_hp_t = (
            power_hp
            /
            (
                weight_kg
                / 1000.0
            )
        )

        weight_power_kg_hp = (
            weight_kg
            /
            power_hp
        )


    return {

        "car":
            car,

        "group":
            group,

        "bop_version":
            bop_version,

        "speed_class":
            speed_class,

        "pp":
            safe_float(
                pp
            ),

        "power_hp":
            power_hp,

        "torque_nm":
            torque_nm,

        "weight_kg":
            weight_kg,

        "power_weight_hp_t":
            power_weight_hp_t,

        "weight_power_kg_hp":
            weight_power_kg_hp,

        "weight_balance":
            weight_balance,

        "drivetrain":
            drivetrain,

        "aspiration":
            aspiration,

        "displacement":
            displacement,

        "engine_model":
            engine_model,

        "powertrain":
            powertrain,

        "acceleration": {

            "0_400m":
                safe_float(
                    acceleration_0_400
                ),

            "0_1000m":
                safe_float(
                    acceleration_0_1000
                ),

            "100_150_kmh":
                safe_float(
                    acceleration_100_150
                )
        },

        "rotational_g": {

            "60_kmh":
                safe_float(
                    rotational_g_60
                ),

            "120_kmh":
                safe_float(
                    rotational_g_120
                ),

            "240_kmh":
                safe_float(
                    rotational_g_240
                )
        },

        "stability": {

            "low_speed":
                stability_low_speed,

            "high_speed":
                stability_high_speed
        },

        "source": {

            "name":
                source,

            "url":
                source_url,

            "confidence":
                source_confidence
        },

        "collected_at":
            now_iso()
    }


# ============================================================
# INSERT / UPDATE RECORD
# ============================================================

def upsert_record(
    database,
    new_record
):

    records = database.setdefault(
        "records",
        []
    )


    new_key = record_key(
        new_record
    )


    for index, existing in enumerate(
        records
    ):

        if record_key(
            existing
        ) == new_key:

            old_collected_at = (
                existing.get(
                    "collected_at"
                )
            )


            records[
                index
            ] = new_record


            return {
                "status":
                    "UPDATED",

                "previous_collected_at":
                    old_collected_at
            }


    records.append(
        new_record
    )


    return {
        "status":
            "ADDED",

        "previous_collected_at":
            None
    }


# ============================================================
# FIND RECORD
# ============================================================

def find_record(
    car,
    group,
    bop_version,
    speed_class
):

    database = load_database()


    target_key = (

        normalize_car_name(
            car
        ),

        normalize_group(
            group
        ),

        str(
            bop_version
            or ""
        ).strip(),

        normalize_speed_class(
            speed_class
        )
    )


    for record in database.get(
        "records",
        []
    ):

        if record_key(
            record
        ) == target_key:

            return record


    return None


# ============================================================
# FIND ALL RECORDS FOR CAR
# ============================================================

def find_car_records(
    car,
    group=None
):

    database = load_database()


    car = normalize_car_name(
        car
    )

    group = (
        normalize_group(
            group
        )
        if group
        else None
    )


    result = []


    for record in database.get(
        "records",
        []
    ):

        if normalize_car_name(
            record.get(
                "car"
            )
        ) != car:

            continue


        if (
            group
            and normalize_group(
                record.get(
                    "group"
                )
            ) != group
        ):

            continue


        result.append(
            record
        )


    return result


# ============================================================
# FIND VERSION
# ============================================================

def find_version_records(
    group,
    bop_version,
    speed_class
):

    database = load_database()


    group = normalize_group(
        group
    )

    speed_class = (
        normalize_speed_class(
            speed_class
        )
    )

    bop_version = str(
        bop_version
        or ""
    ).strip()


    result = []


    for record in database.get(
        "records",
        []
    ):

        if (
            normalize_group(
                record.get(
                    "group"
                )
            ) == group

            and str(
                record.get(
                    "bop_version"
                )
                or ""
            ).strip()
            == bop_version

            and normalize_speed_class(
                record.get(
                    "speed_class"
                )
            ) == speed_class
        ):

            result.append(
                record
            )


    return result


# ============================================================
# DATABASE STATISTICS
# ============================================================

def database_stats():

    database = load_database()

    records = database.get(
        "records",
        []
    )


    groups = set()
    versions = set()
    speed_classes = set()
    cars = set()


    for record in records:

        car = record.get(
            "car"
        )

        group = normalize_group(
            record.get(
                "group"
            )
        )

        version = str(
            record.get(
                "bop_version"
            )
            or ""
        ).strip()

        speed_class = (
            normalize_speed_class(
                record.get(
                    "speed_class"
                )
            )
        )


        if car:
            cars.add(
                car
            )

        if group:
            groups.add(
                group
            )

        if version:
            versions.add(
                version
            )

        if speed_class:
            speed_classes.add(
                speed_class
            )


    return {

        "records":
            len(records),

        "cars":
            len(cars),

        "groups":
            sorted(
                groups
            ),

        "versions":
            sorted(
                versions
            ),

        "speed_classes":
            sorted(
                speed_classes
            ),

        "database_file":
            str(
                DATABASE_FILE
            )
    }


# ============================================================
# VALIDATE DATABASE
# ============================================================

def validate_database():

    database = load_database()

    records = database.get(
        "records",
        []
    )


    errors = []


    seen_keys = set()


    for index, record in enumerate(
        records,
        start=1
    ):

        key = record_key(
            record
        )


        if key in seen_keys:

            errors.append(
                f"Duplicate record #{index}: "
                f"{key}"
            )

        else:

            seen_keys.add(
                key
            )


        if not record.get(
            "car"
        ):

            errors.append(
                f"Record #{index}: "
                "missing car."
            )


        if normalize_group(
            record.get(
                "group"
            )
        ) not in VALID_GROUPS:

            errors.append(
                f"Record #{index}: "
                "invalid group."
            )


        if normalize_speed_class(
            record.get(
                "speed_class"
            )
        ) not in VALID_SPEED_CLASSES:

            errors.append(
                f"Record #{index}: "
                "invalid speed class."
            )


        power = safe_float(
            record.get(
                "power_hp"
            )
        )

        weight = safe_float(
            record.get(
                "weight_kg"
            )
        )


        if (
            power is not None
            and power <= 0
        ):

            errors.append(
                f"Record #{index}: "
                "invalid power."
            )


        if (
            weight is not None
            and weight <= 0
        ):

            errors.append(
                f"Record #{index}: "
                "invalid weight."
            )


    return {

        "valid":
            len(errors) == 0,

        "records_checked":
            len(records),

        "errors":
            errors
    }


# ============================================================
# INITIALIZE DATABASE
# ============================================================

def initialize_database():

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )


    database = load_database()


    save_database(
        database
    )


    return database


# ============================================================
# STANDALONE TEST
# ============================================================

def main():

    initialize_database()


    stats = database_stats()

    validation = (
        validate_database()
    )


    print(
        "GT7 BOP LAB - DATABASE"
    )

    print(
        "=" * 78
    )

    print(
        f"Database file : "
        f"{stats['database_file']}"
    )

    print(
        f"Records       : "
        f"{stats['records']}"
    )

    print(
        f"Cars          : "
        f"{stats['cars']}"
    )

    print(
        f"Groups        : "
        f"{', '.join(stats['groups']) or 'None'}"
    )

    print(
        f"BoP versions  : "
        f"{', '.join(stats['versions']) or 'None'}"
    )

    print(
        f"Speed classes : "
        f"{', '.join(stats['speed_classes']) or 'None'}"
    )

    print(
        f"Validation    : "
        f"{'PASSED' if validation['valid'] else 'FAILED'}"
    )


    if validation[
        "errors"
    ]:

        print()

        print(
            "VALIDATION ERRORS"
        )

        print(
            "-" * 78
        )


        for error in validation[
            "errors"
        ]:

            print(
                error
            )


    print(
        "=" * 78
    )


if __name__ == "__main__":
    main()