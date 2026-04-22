import os
from supabase import create_client, Client

def get_supabase() -> Client | None:
    sb_url = os.environ.get("SUPABASE_URL", "")
    sb_key = os.environ.get("SUPABASE_KEY", "")
    if sb_url and sb_key:
        try:
            return create_client(sb_url, sb_key)
        except Exception as e:
            print(f"Supabase init error: {e}")
    return None

def save_agent_log(audit_id, agent_id, parsed, tokens_used):
    """Tiered saving strategy for agent logs."""
    sb = get_supabase()
    if not sb: return False
    
    # Tier 1: FULL SAVE
    try:
        sb.table("agent_logs").insert({
            "audit_id": audit_id, "agent_name": agent_id, "agent_score": parsed["score"],
            "status": parsed["status"], "summary": parsed.get("summary"),
            "findings": parsed.get("findings", []), "weaknesses": parsed.get("weaknesses", []),
            "suggested_code": parsed.get("suggested_code", []), "roadmap": parsed.get("roadmap", []),
            "tokens_used": tokens_used, "error_message": parsed.get("restriction_reason")
        }).execute()
        return True
    except Exception as e:
        err_str = str(e)
        if "PGRST" in err_str:
            print(f"\n[!] ALERT: Supabase Cache Stale or Column Mismatch in {agent_id}. Attempting Tier 2...")
            try:
                # Tier 2: LEGACY SAVE
                sb.table("agent_logs").insert({
                    "audit_id": audit_id, "agent_name": agent_id, "agent_score": parsed["score"],
                    "status": parsed["status"], "summary": parsed.get("summary")
                }).execute()
                print(f"[+] Tier 2 Save Successful for {agent_id}.")
                return True
            except Exception as e2:
                print(f"[!] Tier 2 Failed for {agent_id}: {e2}.")
        else:
            print(f"[DEBUG] Supabase Save Error in {agent_id}: {err_str}")
    return False
