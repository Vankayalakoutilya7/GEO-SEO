import sys
import os
from pathlib import Path

# Add scripts/webapp to sys.path
sys.path.append(os.getcwd() + "/scripts/webapp")

from app import prepare_agent_payload, extract_skill_logic

print("--- TESTING OPTIMIZED SKILL EXTRACTION ---")

# Test single extraction
tech_logic = extract_skill_logic("geo-technical")
print(f"Technical Logic Length: {len(tech_logic)} characters")
if "## Category 1" in tech_logic and "## Output Format" not in tech_logic:
    print("SUCCESS: Logic extracted, Output Format stripped.")
else:
    print("FAILED: Extraction logic is incorrect.")

# Test full payload injection for Technical Agent
mock_bundle = {
    "internal_pages": [{"url": "https://example.com", "page_weight_kb": 500, "ttfb_ms": 150}],
    "robots": "User-agent: *\nAllow: /"
}

print("\n--- TESTING PAYLOAD INJECTION ---")
payload = prepare_agent_payload("geo-technical", "https://example.com", mock_bundle)

if "=== ELITE INDUSTRIAL STANDARD OPERATING PROCEDURES (SOP) ===" in payload:
    print("SUCCESS: SOP found in Technical Payload.")
    sop_count = payload.count("--- ELITE LOGIC:")
    print(f"Total skills injected for Technical: {sop_count} (Expected 3: technical, crawlers, llmstxt)")
else:
    print("FAILED: SOP missing from payload.")

# Token count estimation (roughly 4 chars per token)
est_tokens = len(payload) // 4
print(f"\nEstimated total input tokens for Technical Agent: ~{est_tokens}")
if est_tokens < 5000:
    print("SUCCESS: Within optimized budget (< 5000 tokens).")
else:
    print(f"WARNING: Token count is high ({est_tokens}). Check if extraction is lean enough.")

# Verification of Content Agent
payload_content = prepare_agent_payload("geo-content", "https://example.com", mock_bundle)
if "ELITE LOGIC: GEO-CONTENT" in payload_content:
    print("SUCCESS: Content Logic injected for Content Agent.")
