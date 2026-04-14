import sys
import os
from pathlib import Path
import json
# It allows us to confirm that the "Instruction Manual" is being handed to the AI correctly without spending any money on Anthropic API tokens to run a real scan.
# Add scripts/webapp to sys.path
sys.path.append(os.getcwd() + "/scripts/webapp")

from app import prepare_agent_payload, load_schema_templates

# Mock data
url = "https://example.com"
content_bundle = {
    "internal_pages": [
        {"url": "https://example.com", "structured_data": [{"@type": "Organization", "name": "Example"}]}
    ]
}

print("--- TESTING SCHEMA INJECTION ---")
payload = prepare_agent_payload("geo-schema", url, content_bundle)

if "=== STANDARD_SCHEMA_TEMPLATES_GROUND_TRUTH ===" in payload:
    print("SUCCESS: Templates found in payload.")
    if "FILE: software-saas.json" in payload:
        print("SUCCESS: Specific templates (software-saas) verified.")
else:
    print("FAILED: Templates missing from payload.")

# Verify file existence as a double check
templates = load_schema_templates()
print(f"\nTotal template content length: {len(templates)} characters")
