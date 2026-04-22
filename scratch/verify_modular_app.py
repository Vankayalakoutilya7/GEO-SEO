import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add scripts/webapp to path if needed
sys.path.append(str(Path(__file__).parent.parent / "scripts" / "webapp"))

try:
    import app
    import config
    import utils
    import agent_runner
    print("✅ All modules imported successfully.")
except Exception as e:
    print(f"❌ Import failed: {e}")
    sys.exit(1)

def mock_audit():
    print("🚀 Starting Mock Audit Flow...")
    url = "https://typeform.com"
    content_bundle = {
        "internal_pages": [{"url": url, "content": "<h1>Typeform</h1>", "h1": "Typeform"}],
        "metrics": {"broken_links": 5, "diagnostics": []}
    }
    
    # Test Calculate Score (util)
    score, pred = utils.calculate_deterministic_score([], {"broken_links": 5})
    print(f"✅ Calculation Check: {score} -> {pred}")
    
    # Test Payload Prep
    try:
        payload = agent_runner.prepare_agent_payload("geo-technical", url, content_bundle)
        print("✅ Payload Preparation: SUCCESS")
    except Exception as e:
        print(f"❌ Payload Preparation: FAILED - {e}")
    
    # Test app config access
    if app.AGENT_MAPPING:
        print("✅ App-Config Link: SUCCESS")
        
    print("✨ Mock Audit finished.")

if __name__ == "__main__":
    mock_audit()
