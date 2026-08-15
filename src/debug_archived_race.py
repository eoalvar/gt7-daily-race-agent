import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin


GTSH_URL = "https://gtsh-rank.com/daily/"
TARGET_WEEK = "03 Aug 2026"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (GT7 Archive Pagination Debug)"
}


def main():

    session = requests.Session()
    session.headers.update(HEADERS)

    target_url = None

    # ========================================================
    # FIND TARGET RACE
    # ========================================================

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

                print("RACE FOUND")
                print("=" * 80)
                print(text)
                print(target_url)

                break

        if target_url:
            break


    if not target_url:

        raise RuntimeError(
            "Target race not found."
        )


    # ========================================================
    # OPEN LEADERBOARD
    # ========================================================

    response = session.get(
        target_url,
        timeout=60
    )

    response.raise_for_status()

    html = response.text

    lines = html.splitlines()


    # ========================================================
    # PRINT JAVASCRIPT AROUND PAGINATION CODE
    # ========================================================

    targets = [
        "url.searchParams.set('offset'",
        'url.searchParams.set("offset"',
        "serverPagedBoard",
        "loadServerPage",
        "pageData = await response.json",
        "fetch(`${url.pathname}"
    ]


    print()
    print("PAGINATION JAVASCRIPT")
    print("=" * 80)


    printed_ranges = []


    for index, line in enumerate(lines):

        if not any(
            target in line
            for target in targets
        ):
            continue


        start = max(
            0,
            index - 20
        )

        end = min(
            len(lines),
            index + 35
        )


        # Avoid printing the same block repeatedly.

        overlapping = any(
            start <= previous_end
            and end >= previous_start
            for previous_start, previous_end
            in printed_ranges
        )

        if overlapping:
            continue


        printed_ranges.append(
            (start, end)
        )


        print()
        print(
            f"--- HTML lines {start + 1} to {end} ---"
        )

        print()


        for line_number in range(
            start,
            end
        ):

            print(
                f"{line_number + 1:05d}: "
                f"{lines[line_number]}"
            )


    # ========================================================
    # SEARCH FOR LIKELY PAGINATION PARAMETERS
    # ========================================================

    print()
    print("SEARCH PARAMETER REFERENCES")
    print("=" * 80)


    keywords = [
        "searchParams.set",
        "searchParams.delete",
        "searchParams.get",
        "offset",
        "limit",
        "pageSize",
        "serverPage",
        "board_page",
        "paged",
        "page_data",
        "pagination"
    ]


    for index, line in enumerate(
        lines,
        start=1
    ):

        if any(
            keyword.lower() in line.lower()
            for keyword in keywords
        ):

            cleaned = line.strip()

            if cleaned:

                print(
                    f"{index:05d}: "
                    f"{cleaned[:3000]}"
                )


    print()
    print("=" * 80)
    print("END")
    print("=" * 80)


if __name__ == "__main__":
    main()