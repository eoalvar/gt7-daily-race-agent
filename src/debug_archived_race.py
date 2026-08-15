import requests
import json
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse


GTSH_URL = "https://gtsh-rank.com/daily/"
TARGET_WEEK = "03 Aug 2026"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (GT7 Archive Pagination Debug)"
}


def build_page_url(event_url, offset, limit=100):

    parsed = urlparse(event_url)

    path = parsed.path

    if not path.endswith("/"):
        path += "/"

    query = parse_qs(
        parsed.query,
        keep_blank_values=True
    )

    query["page_data"] = ["1"]
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


def main():

    session = requests.Session()
    session.headers.update(HEADERS)

    target_url = None
    target_text = None

    # --------------------------------------------------------
    # FIND TOKYO DAILY RACE C
    # --------------------------------------------------------

    for page in range(1, 10):

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


    print("=" * 80)
    print("RACE")
    print("=" * 80)

    print(target_text)
    print(target_url)


    # --------------------------------------------------------
    # FIRST OPEN EVENT
    # --------------------------------------------------------

    response = session.get(
        target_url,
        timeout=60
    )

    response.raise_for_status()

    canonical_url = response.url


    print()
    print("CANONICAL EVENT URL")
    print("=" * 80)

    print(canonical_url)


    # --------------------------------------------------------
    # TEST OFFSETS
    # --------------------------------------------------------

    for offset in [
        0,
        100,
        200,
        1000,
        4000
    ]:

        test_url = build_page_url(
            canonical_url,
            offset,
            100
        )


        print()
        print("=" * 80)
        print(f"OFFSET {offset}")
        print("=" * 80)

        print(
            "URL:",
            test_url
        )


        r = session.get(
            test_url,
            headers={
                "User-Agent":
                    HEADERS["User-Agent"],

                "Accept":
                    "application/json",

                "Referer":
                    canonical_url
            },
            timeout=60
        )


        print(
            "HTTP:",
            r.status_code
        )

        print(
            "Content-Type:",
            r.headers.get(
                "content-type"
            )
        )

        print(
            "Final URL:",
            r.url
        )


        try:

            data = r.json()

        except Exception:

            print(
                "ERROR: response is not JSON"
            )

            print(
                r.text[:1000]
            )

            continue


        print(
            "Keys:",
            list(data.keys())
        )


        print(
            "Returned offset:",
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

        print(
            "Has more:",
            data.get("has_more")
        )


        board = data.get(
            "board"
        )


        if not isinstance(
            board,
            list
        ):

            print(
                "ERROR: board is not a list"
            )

            print(
                json.dumps(
                    data,
                    ensure_ascii=False,
                    indent=2
                )[:3000]
            )

            continue


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


            first_user = (
                board[0]
                .get(
                    "user",
                    {}
                )
                .get(
                    "np_online_id"
                )
            )


            last_user = (
                board[-1]
                .get(
                    "user",
                    {}
                )
                .get(
                    "np_online_id"
                )
            )


            print(
                "First PSN:",
                first_user
            )

            print(
                "Last PSN:",
                last_user
            )


    print()
    print("=" * 80)
    print("END")
    print("=" * 80)


if __name__ == "__main__":
    main()