import sys
import os
from pathlib import Path

# Add scripts/webapp to sys.path
sys.path.append(os.getcwd() + "/scripts/webapp")

from app import clean_html_for_ai, prepare_agent_payload

print("--- TESTING HTML CLEANER ---")
raw_html = """
<html>
  <head>
    <script>console.log('noise')</script>
    <style>.css { color: red; }</style>
  </head>
  <body>
    <header>Nav Item 1</header>
    <nav>Menu Item 2</nav>
    <main>
       <h1>Main Title</h1>
       <p>Strategic content here.</p>
       <noscript>Javascript off</noscript>
       <aside>Related Links</aside>
    </main>
    <footer>Copyright 2026</footer>
  </body>
</html>
"""

cleaned = clean_html_for_ai(raw_html)
print(f"Cleaned HTML Content:\n{cleaned}")

if "Main Title" in cleaned and "Strategic content" in cleaned:
    print("SUCCESS: Core content preserved.")
else:
    print("FAILED: Core content missing.")

if "Nav Item" in cleaned or "Copyright" in cleaned or "css" in cleaned:
    print("FAILED: Boilerplate (header/footer/style) leaked into output.")
else:
    print("SUCCESS: Boilerplate stripped.")

print("\n--- TESTING RICH PAYLOAD GENERATION ---")
mock_bundle = {
    "internal_pages": [{"url": "https://example.com", "content": raw_html}],
    "robots": "{}",
    "llms": "{}"
}

payload = prepare_agent_payload("geo-content", "https://example.com", mock_bundle)
if "AUDIT DATA" in payload and "Strategic content" in payload:
    print("SUCCESS: Cleaned content injected into agent payload.")
else:
    print("FAILED: Payload generation failed or content missing.")
