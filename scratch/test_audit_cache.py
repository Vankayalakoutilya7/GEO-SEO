import sys
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
import uuid

# Add scripts/webapp to sys.path
sys.path.append(os.getcwd() + "/scripts/webapp")

from app import get_supabase

def test_cache_logic():
    sb = get_supabase()
    if not sb:
        print("SKIP: Supabase not configured.")
        return

    domain = "cache-test-" + str(uuid.uuid4())[:8] + ".com"
    print(f"--- TESTING CACHE FOR {domain} ---")

    # 1. Create a project
    proj = sb.table("projects").insert({"target_url": domain}).execute()
    project_id = proj.data[0]["id"]
    print(f"Project Created: {project_id}")

    # 2. Create a successful audit (simulated)
    audit_id = str(uuid.uuid4())
    sb.table("audits").insert({
        "id": audit_id,
        "project_id": project_id,
        "final_score": 85,
        "status": "SUCCESS",
        "summary": "Master Cache Test Summary",
        "metrics": {"test": True}
    }).execute()
    print(f"Audit Created: {audit_id}")

    # 3. Create a log
    sb.table("agent_logs").insert({
        "audit_id": audit_id,
        "agent_name": "geo-technical",
        "agent_score": 90,
        "summary": "Technical Cache Test",
        "status": "SUCCESS"
    }).execute()
    print("Agent Log Created.")

    # 4. Verify Query Logic (Simulating app.py)
    print("\n--- SIMULATING APP.PY CACHE CHECK ---")
    cache_res = sb.table("audits").select("id, final_score, metrics, created_at, summary")\
        .eq("project_id", project_id)\
        .eq("status", "SUCCESS")\
        .order("created_at", desc=True)\
        .limit(5).execute()

    if cache_res.data:
        latest = cache_res.data[0]
        # ISO parsing
        # Supabase returns UTC usually with Z or +00
        raw_date = latest["created_at"]
        print(f"Raw Date from DB: {raw_date}")
        
        created_at = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        age = now - created_at
        
        print(f"Calculated Age: {age}")
        
        if age < timedelta(hours=5):
            print("SUCCESS: Cache hit detected for recent audit.")
        else:
            print("FAILED: Cache check failed to detect recent audit.")
    else:
        print("FAILED: No audit found in DB.")

if __name__ == "__main__":
    test_cache_logic()
