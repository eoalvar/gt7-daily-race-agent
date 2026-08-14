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
    raise Exception(f"Could not access GTSH-Rank: HTTP {response.status_code}")

soup = BeautifulSoup(response.text, "html.parser")

print("Page title:", soup.title.get_text(strip=True))

# Procurar todos os links da página
links = soup.find_all("a")

print(f"Total links found: {len(links)}")

print("\nPossible VictoryDash links:")

for link in links:
    href = link.get("href")

    if href and "victorydash" in href.lower():
        print(urljoin(GTSH_URL, href))

print("\nSearching for Race C...")

text = soup.get_text(" ", strip=True)

if "Daily Race C" in text:
    print("Daily Race C found on page.")
else:
    print("Daily Race C NOT found on page.")

print("\nSearching for Grand Valley...")

if "Grand Valley" in text:
    print("Grand Valley found on page.")
else:
    print("Grand Valley NOT found on page.")