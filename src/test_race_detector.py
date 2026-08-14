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

print("\nALL LINKS FOUND:")
print("-" * 80)

for i, link in enumerate(soup.find_all("a"), start=1):
    href = link.get("href")
    text = link.get_text(" ", strip=True)

    if href:
        full_url = urljoin(GTSH_URL, href)

        print(f"{i}. TEXT: {text}")
        print(f"   URL:  {full_url}")

print("-" * 80)

text = soup.get_text(" ", strip=True)

print("\nRACE DETECTION")
print("-" * 80)

if "Daily Race C" in text:
    print("Daily Race C: FOUND")
else:
    print("Daily Race C: NOT FOUND")

if "Grand Valley" in text:
    print("Grand Valley: FOUND")
else:
    print("Grand Valley: NOT FOUND")