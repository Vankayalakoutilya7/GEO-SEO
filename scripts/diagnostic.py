import sys
import os

print(f"Python Executable: {sys.executable}")
print("-" * 30)

try:
    import playwright
    from playwright.sync_api import sync_playwright
    print("✅ Playwright: Installed")
except ImportError as e:
    print(f"❌ Playwright: NOT FOUND ({e})")

try:
    import playwright_stealth
    print("✅ Playwright Stealth: Installed")
except ImportError as e:
    print(f"❌ Playwright Stealth: NOT FOUND ({e})")

print("-" * 30)
print("Environment Paths:")
for p in sys.path:
    print(f"  {p}")
