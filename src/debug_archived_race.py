import requests
import json
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse


GTSH_URL = "https://gtsh-rank.com/daily/"
TARGET_WEEK = "03 Aug 2026"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (GT7 Archive Pagination Debug)",
    "Accept": "*/*"
}


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
            pass

    return None


def build_url(
    event_url,
    offset,
    limit=100
):

    parsed = urlparse(event_url)

    path = parsed.path

    if not path.endswith("/"):
        path += "/"

    query = parse_qs(
        parsed.query,
        keep_blank_values=True
    )

    query["offset"] = [str(offset)]
    query["limit"] = [str(limit)]

    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            path,
            parsed.params,
            urlencode(query, doseq=True),
            parsed.fragment
        )
    )


def inspect_response(
    label,
    response
):

    print()
    print(label)
    print("-" * 80)

    print(
        "Requested URL:",
        response.request.url
    )

    print(
        "Final URL:",
        response.url
    )

    print(
        "HTTP:",
        response.status_code
    )

    print(
        "Content-Type:",
        response.headers.get(
            "content-type"
        )
    )

    print(
        "Length:",
        len(response.content)
    )


    try:

        data = response.json()

        print(
            "JSON type:",
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
                "Offset:",
                data.get("offset")
            )

            print(
                "Limit:",
                data.get("limit")
            )

            print(
                "Total:",
                data.get("total")
            )

            board = data.get(
                "board"
            )

            if isinstance(
                board,
                list
            ):

                print(
                    "Board length:",
                    len(board)
                )

                if board:

                    print(
                        "First rank:",
                        board[0].get(
                            "display_rank"
                        )
                    )

                    print(
                        "Last rank:",
                        board[-1].get(
                            "display_rank"
                        )
                    )

        print(
            "JSON sample:"
        )

        print(
            json.dumps(
                data,
                ensure_ascii=False,
                indent=2
            )[:3000]
        )

        return


    except Exception:

        print(
            "Response is NOT direct JSON."
        )


    html = response.text

    server_page = extract_json_variable(
        html,
        "initialServerPage"
    )


    if isinstance(
        server_page,
        dict
    ):

        print(
            "HTML contains initialServerPage."
        )

        print(
            "Offset:",
            server_page.get(
                "offset"
            )
        )

        print(
            "Limit:",
            server_page.get(
                "limit"
            )
        )

        print(
            "Total:",
            server_page.get(
                "total"
            )
        )

        board = server_page.get(
            "board"
        )

        if isinstance(
            board,
            list
        ):

            print(
                "Board length:",
                len(board)
            )

            if board:

                print(
                    "First rank:",
                    board[0].get(
                        "display_rank"
                    )
                )

                print(
                    "Last rank:",
                    board[-1].get(
                        "display_rank"
                    )
                )

    else:

        print(
            "No initialServerPage found."
        )


def main():

    session = requests.Session()

    session.headers.update(
        HEADERS
    )


    print(
        "=" * 80
    )

    print(
        "GT7 ARCHIVED PAGINATION URL TEST"
    )

    print(
        "=" * 80
    )


    target_url = None
    target_text = None


    for page in range(
        1,
        10
    ):

        page_url = (
            GTSH_URL
            if page == 1
            else f"{GTSH_URL}?page={page}&q="
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
            "Tokyo Daily Race C not found."
        )


    print()
    print(
        "RACE:"
    )

    print(
        target_text
    )

    print()

    print(
        "Original URL:",
        target_url
    )


    # ========================================================
    # PAGE 1
    # ========================================================

    first = session.get(
        target_url,
        timeout=60
    )

    first.raise_for_status()

    inspect_response(
        "PAGE 1 - NORMAL EVENT URL",
        first
    )


    # ========================================================
    # TEST A
    # event + offset + limit
    # ========================================================

    url_a = build_url(
        first.url,
        100,
        100
    )


    response_a = session.get(
        url_a,
        headers={
            "User-Agent":
                HEADERS[
                    "User-Agent"
                ],

            "Accept":
                "application/json"
        },
        timeout=60
    )


    inspect_response(
        "TEST A - EVENT + OFFSET + LIMIT",
        response_a
    )


    # ========================================================
    # TEST B
    # pathname only + offset + limit
    # This mirrors the JS:
    # fetch(`${url.pathname}?${url.searchParams.toString()}`)
    # ========================================================

    parsed = urlparse(
        first.url
    )


    query = parse_qs(
        parsed.query,
        keep_blank_values=True
    )

    query[
        "offset"
    ] = ["100"]

    query[
        "limit"
    ] = ["100"]


    relative_path = (
        parsed.path
        + "?"
        + urlencode(
            query,
            doseq=True
        )
    )


    url_b = urljoin(
        first.url,
        relative_path
    )


    response_b = session.get(
        url_b,
        headers={
            "User-Agent":
                HEADERS[
                    "User-Agent"
                ],

            "Accept":
                "application/json"
        },
        timeout=60
    )


    inspect_response(
        "TEST B - JS-STYLE PATHNAME REQUEST",
        response_b
    )


    # ========================================================
    # TEST C
    # Same query, but AJAX-ish header
    # ========================================================

    response_c = session.get(
        url_b,
        headers={
            "User-Agent":
                HEADERS[
                    "User-Agent"
                ],

            "Accept":
                "application/json",

            "X-Requested-With":
                "XMLHttpRequest",

            "Referer":
                first.url
        },
        timeout=60
    )


    inspect_response(
        "TEST C - AJAX HEADER",
        response_c
    )


    print()
    print(
        "=" * 80
    )

    print(
        "END"
    )

    print(
        "=" * 80
    )


if __name__ == "__main__":
    main()