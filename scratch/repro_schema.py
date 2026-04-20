import requests
from bs4 import BeautifulSoup
import json

url = "https://www.typeform.com"
headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
}

print(f"Fetching {url}...")
resp = requests.get(url, headers=headers, timeout=15)
print(f"Status: {resp.status_code}")

soup = BeautifulSoup(resp.text, 'html.parser')

print("\n--- JSON-LD Search ---")
scripts = soup.find_all("script", type="application/ld+json")
print(f"Found {len(scripts)} ld+json scripts.")
for i, s in enumerate(scripts):
    try:
        data = json.loads(s.string)
        print(f"[{i}] Type: {data.get('@type')}")
    except:
        print(f"[{i}] Invalid JSON")

print("\n--- Microdata Search ---")
items = soup.find_all(attrs={"itemtype": True})
print(f"Found {len(items)} items with itemtype.")
for i, item in enumerate(items[:5]):
    print(f"[{i}] Type: {item.get('itemtype')}")

print("\n--- Meta Tag Search (Entity hints) ---")
for meta in soup.find_all("meta"):
    if 'og:' in meta.get('property', '') or 'twitter:' in meta.get('name', ''):
        print(f"{meta.get('property', meta.get('name'))}: {meta.get('content')}")
