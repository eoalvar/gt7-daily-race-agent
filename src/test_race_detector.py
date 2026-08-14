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

print("Main page HTTP status:", response.status_code)

if response.status_code != 200:
    raise Exception("Could not access GTSH-Rank")

soup = BeautifulSoup(response.text, "html.parser")

# ---------------------------------------------------------
# Find the current Race C
# ---------------------------------------------------------

race_c_link = None

for link in soup.select('a[href*="/daily/leaderboard?event="]'):

    parent_text = link.parent.get_text(" ", strip=True)

    if (
        "Running" in parent_text
        and "Daily Race C" in parent_text
    ):
        race_c_link = urljoin(
            GTSH_URL,
            link.get("href")
        )
        break

if not race_c_link:
    raise Exception("Could not find current Daily Race C leaderboard")

print("\nCURRENT DAILY RACE C")
print("=" * 80)
print("Leaderboard URL:")
print(race_c_link)

print("\nRace information:")
print(parent_text)

# ---------------------------------------------------------
# Open Race C leaderboard
# ---------------------------------------------------------

leaderboard_response = requests.get(
    race_c_link,
    headers=headers,
    timeout=30
)

print("\nLeaderboard HTTP status:",
      leaderboard_response.status_code)

if leaderboard_response.status_code != 200:
    raise Exception(
        "Could not access Race C leaderboard"
    )

leaderboard_soup = BeautifulSoup(
    leaderboard_response.text,
    "html.parser"
)

print(
    "Leaderboard title:",
    leaderboard_soup.title.get_text(strip=True)
)

# ---------------------------------------------------------
# Show page text
# ---------------------------------------------------------

print("\nLEADERBOARD PAGE TEXT")
print("=" * 80)

page_text = leaderboard_soup.get_text(
    "\n",
    strip=True
)

print(page_text[:12000])

print("\nEND")