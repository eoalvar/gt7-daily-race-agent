import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIG
# ============================================================

BASE_URL = "https://www.gran-turismo.com"
CAR_LIST_URL = (
    "https://www.gran-turismo.com/us/gt7/carlist/"
)

DATA_DIR = Path("data")

OUTPUT_FILE = (
    DATA_DIR
    / "car_technical.json"
)

REQUEST_DELAY_SECONDS = 0.10

HEADERS = {
    "User-Agent":
        "Mozilla/5.0 "
        "(GT7 Technical Car Database Builder)"
}


# ============================================================
# HELPERS
# ============================================================

def clean_text(value):

    if not isinstance(value, str):
        return None

    value = re.sub(
        r"\s+",
        " ",
        value
    ).strip()

    return value or None


def extract_number(value):

    if not value:
        return None

    match = re.search(
        r"[-+]?\d+(?:\.\d+)?",
        value.replace(",", "")
    )

    if not match:
        return None

    try:
        return float(
            match.group(0)
        )

    except Exception:
        return None


# ============================================================
# LOAD EXISTING DATABASE
# ============================================================

def load_existing_database():

    if not OUTPUT_FILE.exists():
        return {}


    try:

        data = json.loads(
            OUTPUT_FILE.read_text(
                encoding="utf-8"
            )
        )

        if isinstance(data, dict):
            return data

    except Exception:
        pass


    return {}


# ============================================================
# SAVE DATABASE
# ============================================================

def save_database(database):

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )


    ordered = dict(
        sorted(
            database.items(),
            key=lambda item:
                int(item[0])
        )
    )


    OUTPUT_FILE.write_text(
        json.dumps(
            ordered,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


# ============================================================
# DISCOVER OFFICIAL CAR PAGES
# ============================================================

def discover_car_pages(session):

    print(
        "Reading official GT7 car list..."
    )


    response = session.get(
        CAR_LIST_URL,
        timeout=60
    )

    response.raise_for_status()


    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )


    cars = {}


    for link in soup.select(
        'a[href*="/gt7/carlist/id/car"]'
    ):

        href = link.get(
            "href"
        )

        if not href:
            continue


        match = re.search(
            r"/gt7/carlist/id/car(\d+)",
            href
        )

        if not match:
            continue


        official_id = int(
            match.group(1)
        )


        url = urljoin(
            BASE_URL,
            href
        )


        cars[
            official_id
        ] = url


    print(
        f"Official car pages discovered: "
        f"{len(cars)}"
    )


    return dict(
        sorted(
            cars.items()
        )
    )


# ============================================================
# EXTRACT SPECIFICATION
# ============================================================

def find_specification(
    soup,
    label
):

    target = label.strip().lower()


    elements = soup.find_all(
        string=True
    )


    for element in elements:

        text = clean_text(
            str(element)
        )

        if not text:
            continue


        if text.lower() != target:
            continue


        parent = element.parent

        if parent is None:
            continue


        # Search nearby elements for the value.

        candidates = []


        if parent.next_sibling:

            candidates.append(
                parent.next_sibling
            )


        if parent.parent:

            children = list(
                parent.parent.children
            )

            try:

                index = children.index(
                    parent
                )

                candidates.extend(
                    children[
                        index + 1:
                        index + 5
                    ]
                )

            except Exception:
                pass


        for candidate in candidates:

            if hasattr(
                candidate,
                "get_text"
            ):

                value = clean_text(
                    candidate.get_text(
                        " ",
                        strip=True
                    )
                )

            else:

                value = clean_text(
                    str(candidate)
                )


            if (
                value
                and value.lower()
                != target
            ):

                return value


    return None


# ============================================================
# EXTRACT CAR NAME
# ============================================================

def extract_car_name(soup):

    h1 = soup.find(
        "h1"
    )


    if h1:

        name = clean_text(
            h1.get_text(
                " ",
                strip=True
            )
        )

        if name:
            return name


    title = soup.find(
        "title"
    )


    if title:

        value = clean_text(
            title.get_text(
                " ",
                strip=True
            )
        )


        if value:

            value = re.sub(
                r"\s*-\s*Gran Turismo.*$",
                "",
                value,
                flags=re.IGNORECASE
            )

            return clean_text(
                value
            )


    return None


# ============================================================
# EXTRACT ONE CAR
# ============================================================

def extract_car(
    session,
    official_id,
    url
):

    response = session.get(
        url,
        timeout=60
    )

    response.raise_for_status()


    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )


    name = extract_car_name(
        soup
    )


    drivetrain = find_specification(
        soup,
        "Drivetrain"
    )


    power = find_specification(
        soup,
        "Max Power"
    )


    weight = find_specification(
        soup,
        "Weight"
    )


    displacement = find_specification(
        soup,
        "Displacement"
    )


    aspiration = find_specification(
        soup,
        "Aspiration"
    )


    drivetrain = clean_text(
        drivetrain
    )


    if drivetrain:

        drivetrain_match = re.search(
            r"\b(FF|FR|MR|RR|4WD)\b",
            drivetrain.upper()
        )

        if drivetrain_match:

            drivetrain = (
                drivetrain_match
                .group(1)
            )


    return {
        "official_id":
            official_id,

        "name":
            name,

        "layout":
            drivetrain,

        "max_power_raw":
            power,

        "weight_raw":
            weight,

        "displacement_raw":
            displacement,

        "aspiration":
            aspiration,

        "max_power":
            extract_number(
                power
            ),

        "weight":
            extract_number(
                weight
            ),

        "displacement":
            extract_number(
                displacement
            ),

        "validated":
            bool(
                name
                and drivetrain
            ),

        "source":
            "gran_turismo_official",

        "source_url":
            url
    }


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print(
        "GT7 OFFICIAL TECHNICAL CAR DATABASE BUILDER"
    )

    print(
        "=" * 78
    )


    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )


    session = requests.Session()

    session.headers.update(
        HEADERS
    )


    existing = (
        load_existing_database()
    )


    print(
        f"Existing records: "
        f"{len(existing)}"
    )


    cars = discover_car_pages(
        session
    )


    if not cars:

        raise RuntimeError(
            "No GT7 car pages discovered."
        )


    database = dict(
        existing
    )


    success = 0
    failed = 0
    validated = 0


    print()
    print(
        "DOWNLOADING OFFICIAL SPECIFICATIONS"
    )

    print(
        "-" * 78
    )


    for index, (
        official_id,
        url
    ) in enumerate(
        cars.items(),
        start=1
    ):


        try:

            record = extract_car(
                session,
                official_id,
                url
            )


            database[
                str(official_id)
            ] = record


            success += 1


            if record.get(
                "validated"
            ):

                validated += 1


            print(
                f"[{index:03d}/{len(cars):03d}] "
                f"{official_id:4d} | "
                f"{record.get('layout') or '???':>3} | "
                f"{record.get('name') or 'UNKNOWN'}"
            )


        except Exception as error:

            failed += 1


            print(
                f"[{index:03d}/{len(cars):03d}] "
                f"{official_id:4d} | ERROR | "
                f"{error}"
            )


        if (
            index % 25 == 0
        ):

            save_database(
                database
            )


        time.sleep(
            REQUEST_DELAY_SECONDS
        )


    save_database(
        database
    )


    print()
    print(
        "=" * 78
    )

    print(
        f"Official cars discovered : "
        f"{len(cars)}"
    )

    print(
        f"Successfully downloaded  : "
        f"{success}"
    )

    print(
        f"Validated name + layout  : "
        f"{validated}"
    )

    print(
        f"Failed                   : "
        f"{failed}"
    )

    print(
        f"Database records         : "
        f"{len(database)}"
    )

    print(
        f"Saved to                 : "
        f"{OUTPUT_FILE}"
    )

    print(
        "=" * 78
    )


if __name__ == "__main__":
    main()