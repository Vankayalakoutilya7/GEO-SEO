import sys
import os
from pathlib import Path
sys.path.append(os.getcwd() + "/scripts")
from fetch_page import fetch_page
import requests

def get_target_url():
    if len(sys.argv) > 1: return sys.argv[1]
    try:
        if os.path.exists("scratch/current_site.txt"):
            with open("scratch/current_site.txt", "r") as f:
                return f.read().strip()
    except Exception: pass
    raise ValueError("ERROR: No target URL provided. Please enter a URL in the frontend or pass it as an argument: python test_handshake.py <url>")

url = get_target_url()
print(f"--- STEP 1: Browser Handshake ({url}) ---")
res = fetch_page(url, use_playwright=True)

if res.get("cookies"):
    print(f"SUCCESS: Captured {len(res['cookies'])} cookies")
    session = requests.Session()
    for c in res["cookies"]:
        session.cookies.set(c['name'], c['value'], domain=c['domain'])
    # Browser User-Agent.
    # It tells the server exactly what software you are using
    if res.get("browser_ua"):
        session.headers.update({"User-Agent": res["browser_ua"]})
        print(f"UA: {res['browser_ua']}")

    print(f"\n--- STEP 2: Stealth Request (Internal Page) ---")
    # Use 2nd argument as internal URL if available, otherwise just re-test the main URL
    internal_url = sys.argv[2] if len(sys.argv) > 2 else url
    res2 = fetch_page(internal_url, use_playwright=False, session=session)
    print(f"Status: {res2['status_code']}")
    print(f"Title: {res2['title']}")
    print(f"Text Preview: {res2['text_content'][:200]}...")
else:
    print("FAILED: No cookies captured.")
