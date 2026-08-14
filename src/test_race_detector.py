import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

GTSH_URL = "https://gtsh-rank.com/daily/"

headers = {
    "User-Agent": "Mozilla/5.0 (GT7 Daily Race Agent)"
}

response = requests.get(
    GTSH_URL,
    headers=headers,
    timeout=30
)

print("HTTP status:", response.status_code)

if response.status_code != 200:
    raise Exception(
        f"Could not access GTSH-Rank: HTTP {response.status_code}"
    )

soup = BeautifulSoup(response.text, "html.parser")

print("Page title:", soup.title.get_text(strip=True))

print("\nLEADERBOARD LINKS")
print("=" * 80)

leaderboard_links = soup.select('a[href*="/daily/leaderboard?event="]')

print(f"Found {len(leaderboard_links)} leaderboard links.")

for i, link in enumerate(leaderboard_links, start=1):

    href = link.get("href")
    full_url = urljoin(GTSH_URL, href)

    print(f"\nLEADERBOARD #{i}")
    print("-" * 80)

    # Mostrar o texto do próprio link
    print("Link text:", link.get_text(" ", strip=True))

    # Mostrar o texto do elemento pai
    parent = link.parent

    if parent:
        parent_text = parent.get_text(" ", strip=True)
        print("Parent text:", parent_text[:1000])

    # Mostrar os elementos ancestrais próximos
    ancestor = link

    for level in range(1, 4):

        if ancestor.parent:
            ancestor = ancestor.parent

            text = ancestor.get_text(" ", strip=True)

            print(
                f"Ancestor level {level}: "
                f"{text[:1500]}"
            )

    print("URL:", full_url)

print("\nEND")