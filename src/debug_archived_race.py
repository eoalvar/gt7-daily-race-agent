import requests
import json
from bs4 import BeautifulSoup
from urllib.parse import urljoin


# ============================================================
# CONFIG
# ============================================================

GTSH_URL = "https://gtsh-rank.com/daily/"
TARGET_WEEK = "03 Aug 2026"
TARGET_PSN = "crazy_rooster74"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (GT7 Archive Debug Agent)"
}


# ============================================================
# INITIAL RANKING EXTRACTOR
# ============================================================

def extract_initial_ranking(html):

    marker = "const initialRanking = "

    start = html.find(marker)

    if start == -1:
        return None

    start += len(marker)

    try:

        decoder = json.JSONDecoder()

        data, _ = decoder.raw_decode(
            html[start:].lstrip()
        )

        return data

    except Exception:

        return None


# ============================================================
# MAIN
# ============================================================

def main():

    session = requests.Session()

    session.headers.update(
        HEADERS
    )


    print("=" * 80)
    print("GT7 ARCHIVED DAILY RACE C - PAGINATION DEBUG")
    print("=" * 80)


    # ========================================================
    # FIND TARGET RACE
    # ========================================================

    target_url = None
    target_text = None


    for page in range(1, 10):

        page_url = (
            GTSH_URL
            if page == 1
            else f"{GTSH_URL}?page={page}&q="
        )


        print(
            f"Searching archive page {page}..."
        )


        response = session.get(
            page_url,
            timeout=30
        )

        response.raise_for_status()


        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )


        for link in soup.select(
            'a[href*="/daily/leaderboard?event="]'
        ):

            parent = link.parent

            if parent is None:
                continue


            text = parent.get_text(
                " ",
                strip=True
            )


            if (
                "Daily Race C" in text
                and TARGET_WEEK in text
            ):

                target_url = urljoin(
                    GTSH_URL,
                    link.get("href")
                )

                target_text = text

                break


        if target_url:
            break


    if not target_url:

        raise RuntimeError(
            "Could not find archived Daily Race C "
            "for 03 Aug 2026."
        )


    print()
    print("RACE FOUND")
    print("-" * 80)
    print(target_text)
    print()
    print(target_url)


    # ========================================================
    # OPEN LEADERBOARD
    # ========================================================

    response = session.get(
        target_url,
        timeout=60
    )

    response.raise_for_status()

    html = response.text


    print()
    print("INITIAL RANKING")
    print("-" * 80)


    initial_ranking = extract_initial_ranking(
        html
    )


    if isinstance(
        initial_ranking,
        list
    ):

        print(
            "Drivers in initialRanking:",
            len(initial_ranking)
        )

    else:

        print(
            "initialRanking not available as list."
        )


    # ========================================================
    # TEST EVENT-SPECIFIC UPDATE ENDPOINT
    # ========================================================

    separator = (
        "&"
        if "?" in target_url
        else "?"
    )


    update_url = (
        target_url
        + separator
        + "update=1"
    )


    print()
    print("UPDATE ENDPOINT")
    print("-" * 80)
    print(update_url)


    update_response = session.get(
        update_url,
        timeout=60
    )

    update_response.raise_for_status()


    print(
        "HTTP:",
        update_response.status_code
    )

    print(
        "Content-Type:",
        update_response.headers.get(
            "content-type"
        )
    )


    data = update_response.json()


    print()
    print("TOP LEVEL RESPONSE")
    print("-" * 80)

    print(
        "Python type:",
        type(data).__name__
    )


    # ========================================================
    # DICT ANALYSIS
    # ========================================================

    if isinstance(
        data,
        dict
    ):

        print(
            "Keys:",
            list(data.keys())
        )


        print()
        print("KEY DETAILS")
        print("-" * 80)


        for key, value in data.items():

            print()
            print(
                f"KEY: {key}"
            )

            print(
                f"TYPE: {type(value).__name__}"
            )


            if isinstance(
                value,
                list
            ):

                print(
                    f"LIST LENGTH: {len(value)}"
                )


                if value:

                    print(
                        "FIRST ITEM:"
                    )

                    print(
                        json.dumps(
                            value[0],
                            ensure_ascii=False,
                            indent=2
                        )[:4000]
                    )


            elif isinstance(
                value,
                dict
            ):

                print(
                    "DICT KEYS:",
                    list(value.keys())
                )

                print(
                    "DICT SAMPLE:"
                )

                print(
                    json.dumps(
                        value,
                        ensure_ascii=False,
                        indent=2
                    )[:4000]
                )


            else:

                print(
                    "VALUE:",
                    str(value)[:2000]
                )


        # ====================================================
        # RECURSIVE SEARCH FOR PSN
        # ====================================================

        print()
        print("RECURSIVE PSN SEARCH")
        print("-" * 80)


        matches = []


        def search_object(
            obj,
            path="root"
        ):

            if isinstance(
                obj,
                dict
            ):

                online_id = obj.get(
                    "np_online_id"
                )


                if (
                    isinstance(
                        online_id,
                        str
                    )
                    and TARGET_PSN.lower()
                    in online_id.lower()
                ):

                    matches.append(
                        {
                            "path":
                                path,
                            "data":
                                obj
                        }
                    )


                for key, value in obj.items():

                    search_object(
                        value,
                        f"{path}.{key}"
                    )


            elif isinstance(
                obj,
                list
            ):

                for index, value in enumerate(
                    obj
                ):

                    search_object(
                        value,
                        f"{path}[{index}]"
                    )


        search_object(
            data
        )


        print(
            "Matches found:",
            len(matches)
        )


        for match in matches:

            print()
            print(
                "PATH:",
                match["path"]
            )

            print(
                json.dumps(
                    match["data"],
                    ensure_ascii=False,
                    indent=2
                )
            )


    else:

        print(
            json.dumps(
                data,
                ensure_ascii=False,
                indent=2
            )[:10000]
        )


    # ========================================================
    # SEARCH HTML FOR PAGINATION PARAMETERS
    # ========================================================

    print()
    print("PAGINATION CODE")
    print("-" * 80)


    interesting_terms = [
        "serverPagedBoard",
        "pageData",
        "page=",
        "offset",
        "limit",
        "next",
        "previous",
        "Back 100",
        "Next 100"
    ]


    found_lines = set()


    for line in html.splitlines():

        if any(
            term.lower() in line.lower()
            for term in interesting_terms
        ):

            cleaned = line.strip()

            if (
                cleaned
                and cleaned not in found_lines
            ):

                found_lines.add(
                    cleaned
                )

                print(
                    cleaned[:3000]
                )


    print()
    print("=" * 80)
    print("END")
    print("=" * 80)


if __name__ == "__main__":
    main()