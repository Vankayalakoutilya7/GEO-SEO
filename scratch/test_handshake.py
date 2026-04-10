import sys
import os
from pathlib import Path
sys.path.append(os.getcwd() + "/scripts")
from fetch_page import fetch_page
import requests

url = "https://www.flipkart.com"
print(f"--- STEP 1: Browser Handshake ---")
res = fetch_page(url, use_playwright=True)

if res.get("cookies"):
    print(f"SUCCESS: Captured {len(res['cookies'])} cookies")
    session = requests.Session()
    for c in res["cookies"]:
        session.cookies.set(c['name'], c['value'], domain=c['domain'])
    
    if res.get("browser_ua"):
        session.headers.update({"User-Agent": res["browser_ua"]})
        print(f"UA: {res['browser_ua']}")

    print(f"\n--- STEP 2: Stealth Request (Internal Page) ---")
    internal_url = "https://www.flipkart.com/mobile-phones-store"
    res2 = fetch_page(internal_url, use_playwright=False, session=session)
    print(f"Status: {res2['status_code']}")
    print(f"Title: {res2['title']}")
    print(f"Text Preview: {res2['text_content'][:200]}...")
else:
    print("FAILED: No cookies captured.")
