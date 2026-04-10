import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from scripts.webapp.app import build_and_upload_pdf
import traceback

data = {
    "url": "https://example.com",
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
