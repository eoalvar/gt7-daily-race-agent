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
# JSON VARIABLE EXTRACTOR
# ============================================================

def extract_json_variable(html, variable_name):

    markers = [
        f"const {variable_name} = ",
        f"let {variable_name} = ",
        f"var {variable_name} = "
    ]

    for marker in markers:

        start = html.find(marker)

        if start == -1:
            continue

        start += len(marker)

        try:

            decoder = json.JSONDecoder()

            data, _ = decoder.raw_decode(
                html[start:].lstrip()
            )

            return data

        except Exception:
            continue

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
    print("GT7 ARCHIVED RACE - ADD RACER DEBUG")
    print("=" * 80)


    # ========================================================
    # FIND TOKYO RACE C
    # ========================================================

    target_url = None
    target_text = None


    for page in range(1, 10):

        if page == 1:
            page_url = GTSH_URL
        else:
            page_url = (
                f"{GTSH_URL}?page={page}&q="
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
            'a[href*="/daily/leaderboard?event="], '
            'a[href*="/daily/leaderboard/?event="]'
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
    # OPEN EVENT FIRST
    #
    # Important: this establishes any session/cookies that
    # GTSH-Rank may use for the selected archived event.
    # ========================================================

    event_response = session.get(
        target_url,
        timeout=60
    )

    event_response.raise_for_status()

    html = event_response.text


    print()
    print("EVENT PAGE")
    print("-" * 80)

    print(
        "HTTP:",
        event_response.status_code
    )

    print(
        "Final URL:",
        event_response.url
    )


    # ========================================================
    # INITIAL SERVER PAGE
    # ========================================================

    server_page = extract_json_variable(
        html,
        "initialServerPage"
    )


    print()
    print("INITIAL SERVER PAGE")
    print("-" * 80)


    if isinstance(
        server_page,
        dict
    ):

        print(
            "Keys:",
            list(server_page.keys())
        )

        print(
            "Offset:",
            server_page.get("offset")
        )

        print(
            "Limit:",
            server_page.get("limit")
        )

        print(
            "Total:",
            (
                server_page.get("total")
                or server_page.get("total_records")
                or server_page.get("totalRecords")
                or server_page.get("count")
            )
        )

        board = server_page.get(
            "board",
            []
        )

        print(
            "Board length:",
            len(board)
            if isinstance(board, list)
            else "N/A"
        )

    else:

        print(
            "initialServerPage not found."
        )


    # ========================================================
    # CALL ADD RACER ENDPOINT
    # ========================================================

    add_racer_url = (
        "https://gtsh-rank.com/"
        "daily/leaderboard/"
        f"?add_racer=1&id={TARGET_PSN}"
    )


    print()
    print("ADD RACER REQUEST")
    print("-" * 80)

    print(
        add_racer_url
    )


    racer_response = session.get(
        add_racer_url,
        headers={
            "User-Agent":
                HEADERS["User-Agent"],

            "Accept":
                "application/json"
        },
        timeout=60
    )


    print(
        "HTTP:",
        racer_response.status_code
    )

    print(
        "Final URL:",
        racer_response.url
    )

    print(
        "Content-Type:",
        racer_response.headers.get(
            "content-type"
        )
    )


    # ========================================================
    # PARSE RESPONSE
    # ========================================================

    print()
    print("ADD RACER RESPONSE")
    print("-" * 80)


    try:

        data = racer_response.json()

        print(
            "Python type:",
            type(data).__name__
        )


        if isinstance(
            data,
            dict
        ):

            print(
                "Keys:",
                list(data.keys())
            )


        print(
            json.dumps(
                data,
                ensure_ascii=False,
                indent=2
            )[:12000]
        )


        # ====================================================
        # RECURSIVE SEARCH FOR OUR PSN
        # ====================================================

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
                    == online_id.lower()
                ):

                    matches.append(
                        {
                            "path": path,
                            "object": obj
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


        print()
        print("PSN SEARCH")
        print("-" * 80)

        print(
            "Matches found:",
            len(matches)
        )


        for match in matches:

            print(
                "PATH:",
                match["path"]
            )

            print(
                json.dumps(
                    match["object"],
                    ensure_ascii=False,
                    indent=2
                )
            )


    except Exception:

        print(
            "Response is not valid JSON."
        )

        print(
            racer_response.text[:12000]
        )


    print()
    print("=" * 80)
    print("END")
    print("=" * 80)


if __name__ == "__main__":
    main()