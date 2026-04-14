import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from scripts.webapp.app import build_and_upload_pdf
import traceback

def get_target_url():
    if len(sys.argv) > 1: return sys.argv[1]
    try:
        import os
        if os.path.exists("scratch/current_site.txt"):
            with open("scratch/current_site.txt", "r") as f:
                return f.read().strip()
    except Exception: pass
    raise ValueError("ERROR: No target URL provided. Please enter a URL in the frontend or pass it as an argument: python test_pdf.py <url>")

url = get_target_url()
data = {
    "url": url,
    "score": 85,
    "date": "2026-04-10",
    "meta_insight": "Test insight",
    "metrics": {},
    "results": [
        {
            "id": "geo-technical",
            "score": 50,
            "label": "Technical",
            "findings": [{"title": "Test", "description": "Desc"}],
            "weaknesses": [{"issue": "Desc", "evidence_url": "http://x"}]
        }
    ]
}

try:
    build_and_upload_pdf("test_task", data, None)
    import os
    print("PDF Exists?:", os.path.exists("/tmp/test_task.pdf"))
except Exception as e:
    traceback.print_exc()
