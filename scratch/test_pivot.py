import sys
import os
from pathlib import Path
sys.path.append(os.getcwd() + "/scripts")
from fetch_page import fetch_page

url = "https://www.flipkart.com/mobile-phones-store"
print(f"--- TESTING AUTO-PIVOT RENDERING (Playwright for Internal Page) ---")
res = fetch_page(url, use_playwright=True)

print(f"Status (Browser Rendered): {res.get('status_code') or 'Rendered'}")
print(f"Title: {res['title']}")
print(f"Text Preview: {res['text_content'][:300]}...")
if "human" in res['text_content'].lower() or "captcha" in res['text_content'].lower():
    print("\n[!] STILL DETECTED AS BOT.")
else:
    print("\n[SUCCESS] Content bypassed and extracted!")
