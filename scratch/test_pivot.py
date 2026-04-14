import sys
import os
from pathlib import Path
sys.path.append(os.getcwd() + "/scripts")
from fetch_page import fetch_page
# verifies the Auto-Pivot Rendering strategy. 
# This is your "Plan B" for when a website tries to block automated access.
def get_target_url():
    if len(sys.argv) > 1: return sys.argv[1]
    try:
        if os.path.exists("scratch/current_site.txt"):
            with open("scratch/current_site.txt", "r") as f:
                return f.read().strip()
    except Exception: pass
    raise ValueError("ERROR: No target URL provided. Please enter a URL in the frontend or pass it as an argument: python test_pivot.py <url>")

url = get_target_url()
print(f"--- TESTING AUTO-PIVOT RENDERING ({url}) ---")
res = fetch_page(url, use_playwright=True)

print(f"Status (Browser Rendered): {res.get('status_code') or 'Rendered'}")
print(f"Title: {res['title']}")
print(f"Text Preview: {res['text_content'][:300]}...")
if "human" in res['text_content'].lower() or "captcha" in res['text_content'].lower():
    print("\n[!] STILL DETECTED AS BOT.")
else:
    print("\n[SUCCESS] Content bypassed and extracted!")
