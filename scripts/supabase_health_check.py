import os
import json
from supabase import create_client, Client
from dotenv import load_dotenv

def check_health():
    load_dotenv()
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")

    if not url or not key:
        print("❌ ERROR: SUPABASE_URL or SUPABASE_KEY missing from .env")
        return

    print(f"🔍 Starting Supabase Health Check...")
    print(f"🔗 Target: {url}")

    try:
        sb: Client = create_client(url, key)
        print("✅ Connection: SUCCESS")
    except Exception as e:
        print(f"❌ Connection: FAILED - {e}")
        return

    print("\n--- DATABASE TABLES ---")
    tables = ["projects", "audits", "agent_logs"]
    for table in tables:
        try:
            # Test simple select to check existence and RLS
            res = sb.table(table).select("*").limit(1).execute()
            print(f"✅ Table '{table}': ACCESSIBLE")
            
            # Check specific columns for agent_logs if they were just added
            if table == "agent_logs":
                try:
                    # Try to insert a dummy record with new columns
                    print("   🔍 Verifying 'agent_logs' columns (summary, roadmap, etc.)...")
                    # We won't actually insert, just select with those columns
                    sb.table("agent_logs").select("summary, roadmap, weaknesses").limit(1).execute()
                    print("   ✅ New Columns: FOUND")
                except Exception as ce:
                    print(f"   ❌ New Columns: NOT FOUND in schema cache ({ce})")
            
        except Exception as e:
            print(f"❌ Table '{table}': ERROR - {e}")

    print("\n--- STORAGE BUCKETS ---")
    try:
        buckets = sb.storage.list_buckets()
        bucket_names = [b.name for b in buckets]
        print(f"📦 Found Buckets: {', '.join(bucket_names) if bucket_names else 'None'}")
        
        if "reports" in bucket_names:
            print("✅ Bucket 'reports': FOUND")
            try:
                # Test list files in bucket
                sb.storage.from_("reports").list(limit=1)
                print("✅ Bucket 'reports': PERMISSIONS OK")
            except Exception as pe:
                print(f"❌ Bucket 'reports': PERMISSION ERROR - {pe}")
        else:
            print("❌ Bucket 'reports': NOT FOUND. (Action: Create a 'Public' bucket named 'reports' in Supabase Dashboard)")
            
    except Exception as e:
        print(f"❌ Storage: FAILED to list buckets - {e}")

if __name__ == "__main__":
    check_health()