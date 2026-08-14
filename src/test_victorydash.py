import requests
from bs4 import BeautifulSoup

URL = "https://victorydash.io/daily-races/p_rt_1013505_001"

response = requests.get(URL, timeout=30)

print("HTTP status:", response.status_code)

soup = BeautifulSoup(response.text, "html.parser")

print("Page title:", soup.title.get_text(strip=True))

# Procurar tabelas
tables = soup.find_all("table")

print("Number of tables:", len(tables))

for i, table in enumerate(tables):
    rows = table.find_all("tr")

    print(f"\nTABLE {i}: {len(rows)} rows")

    for row in rows[:5]:
        cells = row.find_all(["th", "td"])
        values = [cell.get_text(" ", strip=True) for cell in cells]
        print(values)