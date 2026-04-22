#!/usr/bin/env python3
"""
GEO-SEO CRM — Web UI (Flask + HTMX)
Usage:
    pip install flask anthropic beautifulsoup4 requests
    From project root: python3 scripts/webapp/app.py
    From webapp dir:  python3 app.py
    Open http://localhost:5050
"""

import json
import os
import re
import sys
import html
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file if it exists(supabase)
load_dotenv()

# Add parent directory to sys.path to import fetch_page
sys.path.append(str(Path(__file__).parent.parent))
try:
    from fetch_page import fetch_page, fetch_robots_txt, fetch_llms_txt, DEFAULT_HEADERS, is_internal
    from citability_scorer import analyze_page_citability
    from brand_scanner import generate_brand_report
except ImportError as e:
    print("\n" + "!"*60)
    print("CRITICAL ERROR: MISSING DEPENDENCIES DETECTED")
    print(f"Details: {e}")
    print("Please run: ./venv/bin/python3 scripts/webapp/app.py")
    print("!"*60 + "\n")
    fetch_page = None
    fetch_robots_txt = None
    fetch_llms_txt = None
    analyze_page_citability = None
    generate_brand_report = None

from flask import Flask, render_template, request, redirect, url_for, send_file, abort, jsonify, session
import anthropic
from concurrent.futures import ThreadPoolExecutor
try:
    from supabase import create_client, Client
except ImportError:
    create_client = None

app = Flask(__name__)
app.secret_key = "GEO_STABLE_SESSION_KEY_2026_MASTER"

# ── Modular Imports (Config, Utils, DB, Runner) ────────────────────────
try:
    # Try relative imports (if run as module)
    from .config import AGENT_MAPPING, AGENT_SKILL_MAP, AGENT_DIR, SCHEMA_DIR, SKILLS_DIR
    from .utils import (
        clean_html_for_ai, sync_summary_scores, calculate_deterministic_score,
        score_tier, score_label, format_eur
    )
    from .database import get_supabase, save_agent_log
    from .agent_runner import run_agent, run_triage_agent, simulate_geo_query
except (ImportError, ValueError):
    # Fallback to direct imports (if run as script)
    import config
    import utils
    import database
    import agent_runner
    from config import AGENT_MAPPING, AGENT_SKILL_MAP, AGENT_DIR, SCHEMA_DIR, SKILLS_DIR
    from utils import (
        clean_html_for_ai, sync_summary_scores, calculate_deterministic_score,
        score_tier, score_label, format_eur
    )
    from database import get_supabase, save_agent_log
    from agent_runner import run_agent, run_triage_agent, simulate_geo_query

# Business logic and Agent execution moved to modular files in .config, .utils, .agent_runner
# ==============================================================================
# [EXECUTION STEP 5: INDUSTRIAL JSON SCORE PARSING]
# Invoked internally by Step 4. Extracts the 10/10 JSON arrays from Claude's literal text.
# ==============================================================================
def parse_agent_response(full_text: str, agent_id: str, weight: float) -> dict:
    """Elite JSON Extraction (Industrial Grade) supporting Boardroom Schema."""
    res_data = {
        "id": agent_id,
        "label": AGENT_MAPPING.get(agent_id, {}).get("label", agent_id),
        "score": 50, 
        "score_after": 60,
        "summary": full_text, 
        "strengths": [],
        "weaknesses": [],
        "roadmap": [],
        "weight": weight
    }
    
    # ── 1. Elite Extraction ──────────────────────────────────────────
    json_match = re.search(r"<json>(.*?)</json>", full_text, re.DOTALL)
    if not json_match:
        json_match = re.search(r"```json\s*(\{.*?\})\s*```", full_text, re.DOTALL)
    if not json_match:
        json_match = re.search(r"(\{.*\})", full_text, re.DOTALL | re.MULTILINE)

    if json_match:
        try:
            raw_json = json_match.group(1).strip()
            # Remove the destructive single quote replace. Only fix smart quotes.
            raw_json = raw_json.replace("“", '"').replace("”", '"')
            parsed = json.loads(raw_json)
            if isinstance(parsed, dict):
                res_data.update({
                    "score": int(parsed.get("score", 50)),
                    "score_after": int(parsed.get("score_after", parsed.get("score", 50) + 10)),
                    "summary": sync_summary_scores(parsed.get("summary", full_text)),
                    "strengths": parsed.get("strengths", []),
                    "weaknesses": parsed.get("weaknesses", []),
                    "roadmap": parsed.get("roadmap", [])
                })
        except Exception as je:
            print(f"--- JSON Parse Error in {agent_id} ---:\nError: {je}\nRaw Failed JSON:\n{raw_json[:500]}...\n---------------------------------")

    # ── 2. Strategic English Normalization ───────────────────
    res_data["score"] = max(0, min(100, int(res_data["score"])))
    res_data["score_after"] = max(0, min(100, int(res_data["score_after"])))
    
    # Final Boardroom-Ready Formatting for PDF (Combines all fields into Description)
    formatted = f"{res_data['summary']}\n\n"
    if res_data["strengths"]:
        formatted += "STRATEGIC STRENGTHS:\n• " + "\n• ".join(res_data["strengths"]) + "\n\n"
    if res_data["weaknesses"]:
        formatted += "CRITICAL WEAKNESSES:\n• " + "\n• ".join(res_data["weaknesses"]) + "\n\n"
    if res_data["roadmap"]:
        formatted += "IMPROVEMENT ROADMAP:\n• " + "\n• ".join(res_data["roadmap"]) + "\n\n"
    
    formatted += f"PERFORMANCE PROJECTION: Current Audit Score {res_data['score']}/100 → Optimization Target {res_data['score_after']}/100"
    
    res_data["pdf_description"] = formatted
    return res_data

@app.context_processor
def inject_now():
    return {
        "now": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "claude_api_key_set": "claude_api_key" in session or (CLAUDE_API_KEY != "your-api-key-here" and CLAUDE_API_KEY != ""),
        "missing_deps": fetch_page is None
    }

CRM_PATH = Path.home() / ".geo-prospects" / "prospects.json"
PROPOSALS_DIR = Path.home() / ".geo-prospects" / "proposals"
AUDITS_DIR = Path.home() / ".geo-prospects" / "audits"


# ── Helpers ────────────────────────────────────────────────────────────

def load_prospects() -> list[dict]:
    if not CRM_PATH.exists():
        CRM_PATH.parent.mkdir(parents=True, exist_ok=True)
        save_prospects([])
        return []
    try:
        with open(CRM_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return []

def save_prospects(prospects: list[dict]):
    with open(CRM_PATH, "w") as f:
        json.dump(prospects, f, indent=2, ensure_ascii=False)

# Helper functions moved to utils.py

def crm_stats(prospects: list[dict]) -> dict:
    total = len(prospects)
    active = [p for p in prospects if p.get("status") == "active"]
    proposals = [p for p in prospects if p.get("status") == "proposal"]
    mrr = sum(p.get("monthly_value", 0) for p in active)
    pipeline = sum(p.get("monthly_value", 0) for p in proposals)
    avg_score = round(sum(p.get("geo_score", 0) for p in prospects) / total) if total else 0
    return {
        "total": total,
        "active": len(active),
        "mrr": format_eur(mrr),
        "pipeline": format_eur(pipeline),
        "avg_score": avg_score,
        "avg_tier": score_tier(avg_score),
    }

def find_pdf(prospect: dict) -> Path | None:
    """Find the PDF file for a prospect."""
    domain = prospect.get("domain", "")
    if not PROPOSALS_DIR.exists():
        return None
    for f in sorted(PROPOSALS_DIR.glob(f"{domain}*.pdf"), reverse=True):
        return f
    return None


# ── Template filters ────────────────────────────────────────────────────

app.jinja_env.filters["score_tier"] = score_tier
app.jinja_env.filters["score_label"] = score_label
app.jinja_env.filters["format_eur"] = format_eur

STATUS_META = {
    "lead":     {"icon": "⬜", "badge": "secondary",  "label": "Lead"},
    "audit":    {"icon": "🔍", "badge": "warning",    "label": "Audit"},
    "proposal": {"icon": "📄", "badge": "info",       "label": "Proposal"},
    "active":   {"icon": "✅", "badge": "success",    "label": "Active"},
    "churned":  {"icon": "❌", "badge": "danger",     "label": "Churned"},
    "lost":     {"icon": "💀", "badge": "dark",       "label": "Lost"},
}

@app.template_filter("status_meta")
def status_meta_filter(status: str) -> dict:
    return STATUS_META.get(status, {"icon": "?", "badge": "secondary", "label": status})


# ── Routes ─────────────────────────────────────────────────────────────

import uuid
from datetime import datetime
import json
import os
from pathlib import Path

RESULTS_CACHE = Path("/tmp/geo_results")
RESULTS_CACHE.mkdir(exist_ok=True, parents=True)

# ── Formula Mapping (Aligned with SKILL.md/Audit) ──────────────────────
# (Citability * 0.25) + (Brand * 0.20) + (EEAT * 0.20) + (Technical * 0.15) + (Schema * 0.10) + (Platform * 0.10)
# Note: Since we have 5 agents, we'll map them carefully.
# Formula calculation moved to utils.py

# ==============================================================================
# [EXECUTION STEP 1: INITIAL UI DASHBOARD RENDER]
# The user visits the app on their browser and the frontend dashboard renders gracefully checks the database for previous scans.
# ==============================================================================
@app.route("/")
def dashboard():
    sb = get_supabase()
    history = []
    if sb:
        try:
            # Fetch latest 25 audits tightly joined with their parental Project URLs and child Agent Logs 
            res = sb.table("audits").select(
                "id, final_score, status, pdf_url, created_at, projects(target_url), agent_logs(tokens_used)"
            ).order("created_at", desc=True).limit(25).execute()
            
            if res.data:
                for idx, row in enumerate(res.data):
                    target_url = row.get("projects", {}).get("target_url", "Unknown") if row.get("projects") else "Unknown"
                    # Deeply sum tokens across all LLM threads 
                    tokens = sum(log.get("tokens_used", 0) for log in row.get("agent_logs", [])) if row.get("agent_logs") else 0
                    
                    history.append({
                        "serial": idx + 1,
                        "id": row.get("id"),
                        "url": target_url,
                        "status": row.get("status", "UNKNOWN"),
                        "tokens": tokens,
                        "score": row.get("final_score", 0),
                        "pdf_url": row.get("pdf_url"),
                        "raw_date": row.get("created_at")
                    })
        except Exception as e:
            print(f"[DEBUG] [ERROR] Failed to fetch scan history from Supabase: {e}")

    return render_template("dashboard.html", history=history)

# ==============================================================================
# [EXECUTION STEP 6: PDF GENERATION & SUPABASE POSTING]
# Automatically invoked at the end of Step 3. Packages the beautiful PDF and sends to Supabase.
# ==============================================================================
def build_and_upload_pdf(task_id: str, data: dict, sb: Client | None) -> str | None:
    """Enterprise Sync Tool: Creates PDF from analysis and pushes instantly to S3 Bucket."""
    sys.path.append(str(Path(__file__).parent.parent))
    try:
        from generate_pdf_report import generate_report
        pdf_path = f"/tmp/{task_id}.pdf"

        results_map = {r["id"]: r["score"] for r in data["results"]}
        mapped_scores = {
            "ai_citability": results_map.get("geo-ai-visibility", 0),
            "brand_authority": results_map.get("geo-platform-analysis", 0), 
            "content_eeat": results_map.get("geo-content", 0),
            "technical": results_map.get("geo-technical", 0),
            "schema": results_map.get("geo-schema", 0),
            "platform_optimization": results_map.get("geo-platform-analysis", 0)
        }
        
        def clean_md(text):
            t = re.sub(r"\*\*(.*?)\*\*", r"\1", text) 
            t = re.sub(r"### (.*)", r"\1:", t)       
            t = re.sub(r"## (.*)", r"\1:", t)        
            return t.strip()

        report_data_pdf = {
            "url": data["url"],
            "geo_score": data["score"],
            "date": data["date"],
            "executive_summary": data.get("meta_insight", ""),
            "scores": mapped_scores,
            "metrics": data.get("metrics", {}),
            "findings": [],
            "suggested_code": [],
            "ai_readiness_score": results_map.get("geo-ai-visibility", 0), # Unified Score
            "crawler_access": {k: {"status": v, "platform": "Generative AI", "recommendation": "Allow" if v == "ALLOWED" else "Review"} for k, v in (data["metrics"].get("crawlers") or {}).items()},
            "quick_wins": ["Implement llms.txt standard" if data["metrics"].get("faq_count", 0) < 3 else "Optimize Answer Blocks"],
        }
        
        # Aggregate structured findings and code from all agents
        for r in data.get("results", []):
            agent_findings = r.get("findings", [])
            
            # --- NO-BLUFF BRIDGE: If findings are empty, use weaknesses ---
            if not agent_findings and r.get("weaknesses"):
                raw_weaknesses = r["weaknesses"]
                # Safeguard against string iteration (character spamming)
                if isinstance(raw_weaknesses, str):
                    raw_weaknesses = [raw_weaknesses]
                
                for w in raw_weaknesses:
                    if isinstance(w, dict):
                        agent_findings.append({
                            "title": "Audit Weakness",
                            "description": w.get("issue", "Technical Issue Identified"),
                            "severity": w.get("severity", "medium"),
                            "evidence_url": w.get("evidence_url"),
                            "evidence_snippet": w.get("evidence_snippet") or w.get("proof_snippet")
                        })
                    else:
                        agent_findings.append({"title": "Audit Weakness", "description": str(w), "severity": "medium"})

            # Process combined list
            if isinstance(agent_findings, str):
                agent_findings = [agent_findings]
                
            for f in agent_findings:
                if isinstance(f, str):
                    f = {"title": "Discovery", "description": f, "severity": "medium"}
                    
                f["title"] = f"{r.get('label', 'System')}: {f.get('title', 'Finding')}"
                
                # Ensure evidence_url is present if not already set (fallback mapping)
                if not f.get("evidence_url"):
                    matching_weakness = next((w for w in r.get("weaknesses", []) if isinstance(w, dict) and w.get("issue") in (f.get("description") or "")), None)
                    if matching_weakness:
                        f["evidence_url"] = matching_weakness.get("evidence_url")
                
                report_data_pdf["findings"].append(f)
            
        
        generate_report(report_data_pdf, pdf_path)
        
        public_url = None
        if sb:
            try:
                with open(pdf_path, 'rb') as f:
                    file_bytes = f.read()
                safe_domain = re.sub(r'[^a-zA-Z0-9]', '_', data["url"])
                bucket_path = f"audit_{task_id[:8]}_{safe_domain}.pdf"
                
                sb.storage.from_("reports").upload(
                    path=bucket_path, file=file_bytes,
                    file_options={"content-type": "application/pdf", "upsert": "true"}
                )
                public_url = sb.storage.from_("reports").get_public_url(bucket_path)
            except Exception as e:
                print(f"Failed to upload PDF to Supabase S3: {e}")

        return public_url
    except Exception as e:
        print(f"PDF Structural Errors: {e}")
        return None

# ==============================================================================
# [EXECUTION STEP 3: MASTER ANALYSIS SEQUENCE INITIATED]
# Central nervous system. Triggered when the user enters a URL and hits "Analyze".
# ==============================================================================

# Since many modern sites (like Typeform) use complex JavaScript to set security cookies, a simple request isn't enough.
#  Your code uses Playwright (a real browser) for the first page:
@app.route("/analyze_url", methods=["POST"])
def analyze_url():
    """Deep Site-wide Recursive Audit (30+ Pages)."""
    if fetch_page is None:
        return "ERROR: Dependencies not found. Please ensure you are running in the virtual environment (venv)."
    
    url = request.form.get("url", "").strip()
    if not url: return "Please enter a valid URL."
    if not url.startswith("http"): url = "https://" + url
    
    # --- SHARED STATE FOR TEST SCRIPTS ---
    try:
        os.makedirs("scratch", exist_ok=True)
        with open("scratch/current_site.txt", "w") as f:
            f.write(url)
    except Exception: pass

    print(f"\n{'='*50}\n[DEBUG] [MASTER TRACE] Starting Deep Audit for: {url}")
    
    # ── 0. Supabase Connectivity Guard ────────────────────────────────
    sb = get_supabase()
    if not sb:
        print(f"[CRITICAL] Supabase Client Failed to Initialize. Check SUPABASE_URL/KEY in .env")
    else:
        print(f"[DEBUG] Supabase Connection: Active.")
    
    project_id = None
    audit_id = str(uuid.uuid4())  # Pre-generated UUID for the historical run

    from urllib.parse import urlparse, urljoin
    domain = urlparse(url).netloc.replace("www.", "")
    if not domain: domain = url

    # ── 0. Project Hierarchy ──────────────────────────────────────────
    print(f"[DEBUG] [STEP 0] Establishing Supreme Relational UUIDs (Audit ID: {audit_id})")
    if sb:
        try:
            # Check if domain exists as a project
            existing = sb.table("projects").select("id").eq("target_url", domain).execute()
            if existing.data and len(existing.data) > 0:
                project_id = existing.data[0]['id']
            else:
                # Create a new project row and capture its generated ID
                print(f"[DEBUG] [STEP 0] Creating new project for {domain}...")
                new_proj = sb.table("projects").insert({"target_url": domain}).execute()
                if not new_proj.data:
                    print(f"[ERROR] Project Creation Failed (Empty Data). Check RLS policies for 'projects' table.")
                project_id = new_proj.data[0]['id']

            # ── Resilient Audit Placeholder ──────────────────────────
            try:
                sb.table("audits").insert({
                    "id": audit_id, "project_id": project_id, "final_score": 0,
                    "status": "RUNNING", "pdf_url": None, "metrics": {}
                }).execute()
            except Exception as ae:
                err_str = str(ae)
                if "PGRST" in err_str:
                    print(f"[!] ALERT: Audits Table Schema Stale or RLS Block. Attempting Atomic Placeholder...")
                    try:
                        sb.table("audits").insert({
                            "id": audit_id, "project_id": project_id, "status": "RUNNING"
                        }).execute()
                        print(f"[+] Atomic Audit Placeholder Created.")
                    except Exception as ae2:
                        print(f"[CRITICAL] Database Block: Audit initialization failed after fallback. Error: {ae2}")
                else: 
                    print(f"[ERROR] Critical Audit Initialization Failure: {err_str}")
                    if "403" in err_str or "new row violates" in err_str:
                        print("[!] DIAGNOSTIC: This looks like an RLS Policy violation. Please check your 'audits' table policies.")
                    raise ae

            # --- 30-MINUTE CACHE PROTECTION (New) ---
            print(f"[DEBUG] Checking Cache for Project {project_id}...")
            # Check the latest successful audit for this domain
            cache_res = sb.table("audits").select("id, final_score, metrics, created_at, summary")\
                .eq("project_id", project_id)\
                .eq("status", "SUCCESS")\
                .order("created_at", desc=True)\
                .limit(1).execute()
            
            if cache_res.data:
                latest = cache_res.data[0]
                # Ensure created_at is offset-aware even if the string format varies
                created_at = datetime.fromisoformat(latest["created_at"].replace("Z", "+00:00"))
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                
                # Compare awareness-safe datetimes
                age = datetime.now(timezone.utc) - created_at
                
                if age < timedelta(minutes=5):
                    print(f"[DEBUG] [CACHE HIT] Serving recent audit from {created_at} (Age: {age})")
                    cached_audit_id = latest["id"]
                    
                    # Reconstruct results from agent_logs
                    logs_res = sb.table("agent_logs").select("*").eq("audit_id", cached_audit_id).execute()
                    
                    if logs_res.data:
                        results = []
                        for log in logs_res.data:
                            # Re-map DB columns to the template-friendly 'results' structure
                            results.append({
                                "id": log["agent_name"],
                                "label": AGENT_MAPPING.get(log["agent_name"], {}).get("label", log["agent_name"]),
                                "score": log["agent_score"],
                                "summary": log["summary"],
                                "findings": log["findings"],
                                "weaknesses": log["weaknesses"],
                                "suggested_code": log["suggested_code"],
                                "roadmap": log["roadmap"],
                                "status": log["status"],
                                "weight": AGENT_MAPPING.get(log["agent_name"], {}).get("weight", 0.2)
                            })
                        
                        # Reconstruct master metrics
                        final_score = latest["final_score"]
                        metrics = latest["metrics"]
                        predicted_score = min(99, final_score + 12)
                        meta_insight = latest.get("summary") or results[-1]["summary"] # Fallback
                        roadmap_fixes = next((r["roadmap"] for r in results if r["id"] == "geo-executive-roadmap"), [])
                        task_id = cached_audit_id # Ensure PDF / UI links work
                        
                        grad_map = [(90, "A+", "Excellent"), (80, "A", "Good"), (60, "B", "Moderate"), (40, "C", "Poor"), (0, "F", "Critical")]
                        grade, label = next((g, l) for s, g, l in grad_map if final_score >= s)
                        
                        missing_analysis = [
                            "Historical Backlink Velocity Trends (Requires Ahrefs/Semrush API Integration)",
                            "Real-time Sentiment Analysis in Gated AI Communities (X, Discord, Slack)",
                            "Competitive Share-of-Voice (Requires per-query serpapi monitoring)"
                        ]

                        return render_template(
                            "_analysis_result.html",
                            url=url, score=final_score, predicted_score=predicted_score, grade=grade,
                            label=label, results=results, task_id=task_id, formula=FORMULA_TEXT,
                            metrics=metrics, meta_insight=meta_insight, roadmap_fixes=roadmap_fixes,
                            missing_analysis=missing_analysis
                        )

        except Exception as e:
            print(f"Supabase Cache/DB Error: {e}")
    
    # ── 1. Elite Enterprise Stratified Audit (10,000 URLs) ────────────
    visited = {url.split("#")[0].rstrip("/")}
    content_bundle = {"page": "", "robots": "Not Found", "llms": "Not Found", "internal_pages": [], "menu_structure": []}
    metrics = {"faq_count": 0, "answer_blocks": 0, "snippet_coverage": 0, "schema_count": 0, "schema_types": set(), 
               "crawlers": {}, "total_discovered": 0, "deep_audited": 0, "broken_links": 0}
    
    MAX_DISCOVERY = 5000 
    MAX_AUDIT = 50     
    
    def rank_url(u: str) -> int:
        """Inclusive 'Wide-Net' filter to feed the AI Triage Agent (v2)."""
        u = u.lower()
        score = 10 
        # Broad high-priority captures
        if any(x in u for x in ["pricing", "plan", "subscript", "enroll", "book", "register", "join", "start", "membership"]): score += 100
        if any(x in u for x in ["product", "feature", "solution", "service"]): score += 80
        if any(x in u for x in ["blog", "guide", "article", "post", "news"]): score += 60
        if any(x in u for x in ["faq", "docs", "help", "support", "kb", "knowledge"]): score += 70
        if any(x in u for x in ["case-study", "customer", "review", "testimonial"]): score += 50
        # Aggressive low-priority filtering
        if any(x in u for x in ["terms", "privacy", "legal", "cookie", "login", "signin", "signup", "cart", "checkout", "account"]): score -= 150
        return score

    parsed_root = urlparse(url)
    root_domain = ".".join(parsed_root.netloc.split(".")[-2:])
    
    print(f"[DEBUG] [STEP 1] Crawling Sitemap & Deep Extraction...")
    if fetch_page:
        # ── Universal Master Session (Elite Stealth) ────────────────────
        import requests
        session_obj = requests.Session()
        session_obj.headers.update(DEFAULT_HEADERS)
        
        # A. Robots & LLMS
        rob = fetch_robots_txt(url) if fetch_robots_txt else {}
        data_robots = rob
        data_llms = fetch_llms_txt(url) if fetch_llms_txt else {}
        
        metrics["robots_status"] = "ALLOWED" if data_robots.get("is_allowed") else "BLOCKED"
        metrics["llms_status"] = "ALLOWED" if data_llms.get("is_allowed") else "BLOCKED"
        content_bundle["robots"] = json.dumps(data_robots)
        content_bundle["llms"] = json.dumps(data_llms)
        metrics["crawlers"] = data_robots.get("ai_crawler_status", {})
        
        # B. Homepage extraction (Handshake Priming)
        # We always use Playwright for the homepage to get the authenticated / JS-prime cookies
        res = fetch_page(url, use_playwright=True)
        brand_name = domain.split('.')[0].capitalize() # Fallback
        
        # --- STEALTH HANDSHAKE BRIDGE ---
        if res.get("cookies"):
            for cookie in res["cookies"]:
                session_obj.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'])
            print(f"[DEBUG] Handshake successful. Injected {len(res['cookies'])} browser-primed cookies.")
        
        if res.get("browser_ua"):
            session_obj.headers.update({"User-Agent": res["browser_ua"]})
        
        discovery_queue = []
        if rob.get("sitemaps"):
            try:
                from fetch_page import crawl_sitemap
                # Pass the primed session to sitemap crawler
                sitemap_links = crawl_sitemap(url, max_pages=MAX_DISCOVERY, session=session_obj)
                discovery_queue.extend([l for l in sitemap_links if l not in visited])
                visited.update(discovery_queue)
            except ImportError: pass
        
        # BFS Fallback Check if Sitemap failed or didn't exist
        if not discovery_queue:
            print("[DEBUG] No Sitemap found or sitemap empty. Falling back to Recursive BFS Crawler...")
            try:
                from fetch_page import recursive_bfs_crawl
                bfs_links = recursive_bfs_crawl(url, max_pages=3000, session=session_obj)
                discovery_queue.extend([l for l in bfs_links if l not in visited])
                visited.update(discovery_queue)
            except ImportError as e:
                print(f"[DEBUG] Failed to import recursion crawler: {e}")
        
        # Detect bot protection in the response
        page_text = res.get("text_content", "").lower()
        pivot_to_browser = False
        if "are you a human" in page_text or "captcha" in page_text or res.get("bot_detected"):
            print("[WARNING] HIGH-FRICTION BOT PROTECTION: Pivoting to Full Browser Rendering for audit accuracy.")
            pivot_to_browser = True
            content_bundle["crawl_obstructed"] = True
        else:
            content_bundle["crawl_obstructed"] = False
        
        external_links = []
        # C. Content Population & Redirect Handling
        final_url = res.get("url", url)
        if urlparse(final_url).netloc != urlparse(url).netloc:
            print(f"[DEBUG] [STEP 1.1] Redirect Pivot: {url} -> {final_url}. Following new domain.")
            url = final_url
            domain = urlparse(url).netloc.replace("www.", "")

        if res and not res.get("errors"):
            content_bundle["page"] = res.get("text_content", "")
            print(f"[DEBUG] [STEP 1.2] Content Bundle Primed: {len(content_bundle['page'])} chars extracted from {url}")
            external_links = res.get("external_links", [])
            # Try to get better brand name from H1
            h1s = res.get("h1_tags", [])
            if h1s: brand_name = h1s[0]
            
            metrics["schema_types"].update([s.get("@type") for s in res.get("structured_data", []) if isinstance(s, dict)])
            for link in res.get("internal_links", []):
                l_url = link["url"].split("#")[0].rstrip("/")
                if is_internal(l_url, url) and l_url not in visited:
                    discovery_queue.append(l_url)
                    visited.add(l_url)
            content_bundle["menu_structure"] = [l.get("text", "") for l in res.get("internal_links", [])[:50]]
        
        # Step 1.2: Brand Visibility Scan (Wikipedia/Reddit/YouTube)
        if generate_brand_report:
            print(f"[DEBUG] [STEP 1.2] Scanning Brand Visibility for '{brand_name}'...")
            brand_report = generate_brand_report(brand_name, domain, external_links=external_links)
            
            # --- TOP 1% ELITE: Real GEO Query Simulation ---
            print(f"[DEBUG] [STEP 1.3] Simulating Real GEO Queries for '{brand_name}'...")
            brand_report["geo_query_simulation"] = simulate_geo_query(
                brand_name, 
                context_text=content_bundle["page"], 
                api_key=session.get("claude_api_key", CLAUDE_API_KEY)
            )
            
            # --- TOP 1% ELITE: Authority Scorer ---
            brand_report["authority_score"] = calculate_authority_proxy(brand_name, brand_report)
            
            # --- TOP 1% ELITE: Competitor Discovery ---
            print(f"[DEBUG] [STEP 1.4] Discovering Competitors for Benchmarking...")
            brand_report["competitors"] = discover_competitors(brand_name, domain)
            
            content_bundle["brand_report"] = brand_report
            
        # C. Intelligent Selection Logic (Top 1000)
        discovery_queue = list(dict.fromkeys(discovery_queue))
        metrics["total_discovered"] = len(discovery_queue)
        
        # Sort by brilliant rank scores (Basic semantic sorting to fit within Triage Agent's 1000-page limit)
        # discovery_queue.sort(key=rank_url, reverse=True) 
        # (Disabled heuristic sort as per Elite Triage plan to allow Agent to rank)
        
        # AI Triage enhancement (Phase 1.5)
        print(f"[DEBUG] [STEP 1.5] Running AI Triage for High-Value Targets...")
        api_key = session.get("claude_api_key", CLAUDE_API_KEY)
        to_audit = run_triage_agent(discovery_queue, api_key)
        
        # Power Worker Pool (Stealth Mode: 5 Concurrency + Primed Session)
        # BSR PIVOT: If browser pivot is active, we use Playwright for EVERY page but reduce concurrency to prevent crash
        concurrency = 3 if pivot_to_browser else 5
        with ThreadPoolExecutor(max_workers=concurrency) as crawl_exec:
            results_crawl = list(crawl_exec.map(
                lambda u: fetch_page(u, use_playwright=pivot_to_browser, session=session_obj), 
                to_audit
            ))
            for r in results_crawl:
                if not r: continue
                if r.get("status_code", 0) >= 400: 
                    metrics["broken_links"] += 1
                    if "diagnostics" not in metrics: metrics["diagnostics"] = []
                    metrics["diagnostics"].append({"url": r["url"], "status": r["status_code"], "error": ", ".join(r.get("errors", [])) or "Resource Blocked"})
                
                if not r.get("errors"):
                    content_bundle["internal_pages"].append({
                        "url": r["url"],
                        "meta": r.get("description", ""),
                        "h1": r.get("h1_tags", [""])[0] if r.get("h1_tags") else "",
                        "content": r.get("text_content", ""),
                        "security_headers": r.get("security_headers", {}),
                        "structured_data": r.get("structured_data", []),
                        "ttfb_ms": r.get("ttfb_ms", 0),
                        "page_weight_kb": r.get("page_weight_kb", 0),
                        "has_ssr": r.get("has_ssr_content", True),
                        "is_compressed": r.get("is_compressed", False),
                        "redirect_chain": r.get("redirect_chain", []),
                        "canonical": r.get("canonical"),
                        "status_code": r.get("status_code", 200)
                    })
                    metrics["schema_types"].update([s.get("@type") for s in r.get("structured_data", []) if isinstance(s, dict)])
        # Calculate Advanced Aggregate Metrics for UI
        # FALLBACK: If discovery failed, ensure we at least audit the homepage
        if not content_bundle["internal_pages"] and res and not res.get("errors"):
            print("[WARNING] [SEED FALLBACK] Discovery found 0 pages. Auditing homepage as deep audit fallback.")
            content_bundle["internal_pages"].append({
                "url": res["url"],
                "meta": res.get("description", ""),
                "h1": res.get("h1_tags", [""])[0] if res.get("h1_tags") else "",
                "content": res.get("text_content", ""),
                "security_headers": res.get("security_headers", {}),
                "structured_data": res.get("structured_data", []),
                "ttfb_ms": res.get("ttfb_ms", 0),
                "page_weight_kb": res.get("page_weight_kb", 0),
                "has_ssr": res.get("has_ssr_content", True),
                "is_compressed": res.get("is_compressed", False),
                "redirect_chain": res.get("redirect_chain", []),
                "canonical": res.get("canonical"),
                "status_code": res.get("status_code", 200)
            })

        if content_bundle["internal_pages"]:
            audited_pages = content_bundle["internal_pages"]
            metrics["avg_ttfb"] = int(sum(p.get("ttfb_ms", 0) for p in audited_pages) / len(audited_pages))
            metrics["compression_status"] = any(p.get("is_compressed", False) for p in audited_pages)
            metrics["redirect_hops"] = sum(len(p.get("redirect_chain", [])) for p in audited_pages)
            metrics["snippet_coverage"] = min(100, int((metrics["answer_blocks"] / len(audited_pages)) * 100)) if len(audited_pages) > 0 else 0
        else:
            metrics["avg_ttfb"] = 0
            metrics["compression_status"] = False
            metrics["redirect_hops"] = 0
            metrics["snippet_coverage"] = 0
        
        metrics["deep_audited"] = len(content_bundle["internal_pages"])
        
        # Calculate Echo Penalty (Phase 3.5)
        echo_penalty = calculate_echo_penalty(content_bundle.get("internal_pages", []))
        metrics["echo_penalty"] = echo_penalty
        print(f"[DEBUG] [STEP 1.7] Echo Penalty Detected: {echo_penalty}% Similarity.")
        
        # D. Enterprise-Scale Normalization (Preventing 850% Overload)
        all_text = " ".join([p.get("content", "") for p in content_bundle["internal_pages"]])
        metrics["faq_count"] = len(re.findall(r"([^.!?]*\?)\s", all_text)[:100])
        metrics["answer_blocks"] = len(re.findall(r"(?i)\b(is|how|what|why|guide)\s+[^.!?]{10,200}[.!?]", all_text)[:60])
        metrics["schema_count"] = len(metrics["schema_types"])
        
        # New High-Precision Formula for 1000 Pages
        raw_cov = (metrics["schema_count"] * 2) + (metrics["answer_blocks"] * 0.5)
        metrics["snippet_coverage"] = min(99, int(raw_cov))
        metrics["schema_types"] = list(metrics["schema_types"])
        
        print(f"[DEBUG] [STEP 2] Extraction Complete. Discovered {metrics['total_discovered']} URLs, Deep-Audited {metrics['deep_audited']} Pages.")

    if fetch_llms_txt:
        lms = fetch_llms_txt(url)
        if lms.get("llms_txt", {}).get("exists"):
            content_bundle["llms"] = lms.get("llms_txt", {}).get("content", "")
    
    # ── 2. Specialized Specialist Audits (Parallel 3x Speed) ───────────
    api_key = session.get("claude_api_key", CLAUDE_API_KEY)
    specialist_agents = [a for a in AGENT_MAPPING.keys() if a not in ["geo-executive-roadmap", "geo-echo"]]
    results = []
    
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(run_agent, agent_id, url, content_bundle, api_key, audit_id): agent_id for agent_id in specialist_agents}
        for future in futures:
            results.append(future.result())
            time.sleep(1) # Small stagger for safety
            
    # ── 3. High-Standard Master Synthesis (The 7th Pass) ──────────────
    print(f"[DEBUG] [STEP 3] Running Master Strategist Pass (Roadmap Synthesis)...")
    content_bundle["agent_results"] = results # Pass results to strategist context
    master_result = run_agent("geo-executive-roadmap", url, content_bundle, api_key, audit_id)
    
    # ── 3. Deterministic Source of Truth Calculation ──────────────
    # We calculate the final score BEFORE the Master Synthesis to ensure Sync
    final_score, predicted_score = calculate_deterministic_score(
        results, metrics, crawl_obstructed=content_bundle.get("crawl_obstructed", False)
    )
    
    # ── 4. Master Strategist Pass (The Total Sync Injection) ──────────────
    print(f"[DEBUG] [STEP 4] Running Master Strategist Pass (Roadmap Synthesis)...")
    content_bundle["agent_results"] = results 
    content_bundle["FINAL_CALCULATED_SCORE"] = final_score # CRITICAL: Injection for Sync
    content_bundle["SCORING_FORMULA"] = FORMULA_TEXT
    
    master_result = run_agent("geo-executive-roadmap", url, content_bundle, api_key, audit_id)
    master_result = master_result or {}
    
    meta_insight = master_result.get("summary", "Analysis complete.")
    meta_insight = sync_summary_scores(meta_insight, final_score) # Deterministic Sync
    roadmap_fixes = master_result.get("top_fixes", [])
    
    print(f"[DEBUG] [STEP 5] Finalizing Report & PDF (Score: {final_score})")

    # ── 4. Cache & Synchronous PDF Generation ──────────────────────────
    task_id = audit_id
    report_data = {
        "url": url, "score": final_score, "predicted_score": predicted_score,
        "formula": FORMULA_TEXT, "results": results, "metrics": metrics,
        "meta_insight": meta_insight,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    with open(RESULTS_CACHE / f"{task_id}.json", "w") as f:
        json.dump(report_data, f)
        
    generated_pdf_url = build_and_upload_pdf(task_id, report_data, sb)

    # ── 5. Supabase Master Audit Logging ──────────────────────────────
    if sb and project_id:
        try:
            sb.table("audits").update({
                "final_score": final_score,
                "status": "SUCCESS",
                "summary": meta_insight,
                "pdf_url": generated_pdf_url,
                "metrics": metrics
            }).eq("id", audit_id).execute()
        except Exception as e:
            print(f"Failed to log master audit to Supabase: {e}")
    
    grad_map = [(90, "A+", "Excellent"), (80, "A", "Good"), (60, "B", "Moderate"), (40, "C", "Poor"), (0, "F", "Critical")]
    grade, label = next((g, l) for s, g, l in grad_map if final_score >= s)

    # Agency-Level Missing Analysis Warnings
    missing_analysis = [
        "Historical Backlink Velocity Trends (Requires Ahrefs/Semrush API Integration)",
        "Real-time Sentiment Analysis in Gated AI Communities (X, Discord, Slack)",
        "Competitive Share-of-Voice (Requires per-query serpapi monitoring)"
    ]

    return render_template(
        "_analysis_result.html",
        url=url, score=final_score, predicted_score=predicted_score, grade=grade,
        label=label, results=results, task_id=task_id, formula=FORMULA_TEXT,
        metrics=metrics, meta_insight=meta_insight, roadmap_fixes=roadmap_fixes,
        missing_analysis=missing_analysis
    )

# ==============================================================================
# [EXECUTION STEP 7: SECURE PDF DELIVERY]
# If the user clicks "View PDF" or "Download" in the UI, this serves the pre-generated memory file instantly.
# ==============================================================================
@app.route("/download_pdf/<task_id>")
def download_pdf(task_id):
    """Serve the pre-generated PDF report. Automatically reconstructs it from cache if /tmp is cleared."""
    pdf_path = f"/tmp/{task_id}.pdf"
    import os
    if not os.path.exists(pdf_path):
        # Attempt self-healing regeneration from disk cache
        cache_path = Path(RESULTS_CACHE) / f"{task_id}.json"
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r") as f:
                    cached_data = json.load(f)
                build_and_upload_pdf(task_id, cached_data, get_supabase())
            except Exception as e:
                print(f"[ERROR] Failed to regenerate PDF from cache: {e}")
        
    if not os.path.exists(pdf_path):
        abort(404, description="PDF is missing from memory and cache could not be reconstructed.")
        
    try:
        return send_file(
            pdf_path, 
            as_attachment=(request.args.get("action") != "view"), 
            download_name=f"GEO_REPORT_{task_id[:8]}.pdf"
        )
    except Exception as e:
        return f"Failed to serve PDF: {str(e)}"
# ==============================================================================
# [EXECUTION STEP 2: API KEY CONFIGURATION]
# If the user clicks Settings, they provide their Anthropic key to secure the session.
# ==============================================================================
#mentiond in frontend
@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        key = request.form.get("claude_api_key", "").strip()
        if key:
            session["claude_api_key"] = key
        return redirect(url_for("dashboard"))
    
    # Restoring the "***" placeholder for security as requested
    is_key_set = "claude_api_key" in session or (CLAUDE_API_KEY != "your-api-key-here" and CLAUDE_API_KEY != "")
    key_placeholder = "***" if is_key_set else "Enter Claude API Key"
    return render_template("settings.html", key_placeholder=key_placeholder)

#global in code
@app.route("/compare", methods=["POST"])
def compare_competitive():
    """Enterprise Benchmarking: Compare target vs competitor URL."""
    target_url = request.form.get("target_url")
    competitor_url = request.form.get("competitor_url")
    api_key = session.get("claude_api_key", CLAUDE_API_KEY)
    
    if not target_url or not competitor_url:
        return jsonify({"error": "Both URLs are required."}), 400
        
    return render_template("compare.html", target=target_url, competitor=competitor_url)
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5050)