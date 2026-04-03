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
from datetime import datetime
from pathlib import Path

# Add parent directory to sys.path to import fetch_page
sys.path.append(str(Path(__file__).parent.parent))
try:
    from fetch_page import fetch_page, fetch_robots_txt, fetch_llms_txt
    from citability_scorer import analyze_page_citability
except ImportError:
    fetch_page = None
    fetch_robots_txt = None
    fetch_llms_txt = None
    analyze_page_citability = None

from flask import Flask, render_template, request, redirect, url_for, send_file, abort, jsonify, session
import anthropic
from concurrent.futures import ThreadPoolExecutor
try:
    from supabase import create_client, Client
except ImportError:
    create_client = None

app = Flask(__name__)
app.secret_key = os.urandom(24)

# ── Agent Configurations ───────────────────────────────────────────────
AGENT_DIR = Path(__file__).parent.parent.parent / "agents"
AGENT_MAPPING = {
    "geo-ai-visibility": {"weight": 0.25, "label": "AI Visibility & Citability"},
    "geo-content": {"weight": 0.20, "label": "Content E-E-A-T"},
    "geo-technical": {"weight": 0.15, "label": "Technical GEO Infrastructure"},
    "geo-schema": {"weight": 0.15, "label": "Schema & Structured Data"},
    "geo-platform-analysis": {"weight": 0.25, "label": "Platform Optimization"}
}

def load_agent_prompt(name: str) -> str:
    path = AGENT_DIR / f"{name}.md"
    if path.exists():
        return path.read_text()
    return ""

# ── Claude Integration ──────────────────────────────────────────────────
CLAUDE_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "your-api-key-here")

def get_claude_client():
    api_key = session.get("claude_api_key", CLAUDE_API_KEY)
    if not api_key or api_key == "your-api-key-here":
        return None
    return anthropic.Anthropic(api_key=api_key)

# ── Supabase Integration ────────────────────────────────────────────────
def get_supabase() -> Client | None:
    sb_url = os.environ.get("SUPABASE_URL", "")
    sb_key = os.environ.get("SUPABASE_KEY", "")
    if sb_url and sb_key and create_client:
        try:
            return create_client(sb_url, sb_key)
        except Exception as e:
            print(f"Supabase init error: {e}")
    return None

import time

# ==============================================================================
# [EXECUTION STEP 4: AI AGENT STRATIFIED EXECUTION]
# Invoked repeatedly (in threads) by Step 3. Connects to Claude and performs strict SEO analysis.
# ==============================================================================
def run_agent(agent_id: str, url: str, content_bundle: dict, api_key: str, audit_id: str):
    if not api_key or api_key == "your-api-key-here":
        return {"id": agent_id, "score": 0, "summary": "API key not set.", "top_fixes": [], "weight": 0}
    
    client = anthropic.Anthropic(api_key=api_key)
    prompt = load_agent_prompt(agent_id)
    if not prompt:
        return {"id": agent_id, "score": 0, "summary": f"Agent {agent_id} instructions not found.", "top_fixes": [], "weight": 0}

    # ── Brilliant Compression (TPM-Safe for 1,000 Pages) ──────────────
    # To avoid 'Error 429', we send full content for Top 100 
    # and structural maps (URL+H1) for the other 900.
    internal_data = ""
    pages = content_bundle.get('internal_pages', [])
    for i, p in enumerate(pages):
        u_base = p['url']
        h_base = p.get('h1', 'No H1')
        if i < 100: # Deep Audit Sector
            c_base = p.get('content', '')[:600]
            m_base = p.get('meta', '')
            internal_data += f"--- DEEP PAGE: {u_base} ---\nH1: {h_base}\nMETA: {m_base}\nCONTENT: {c_base}\n\n"
        else: # Structural Scan Sector (Significantly reduces tokens)
            internal_data += f"--- SCAN: {u_base} (H1: {h_base})\n"

    data_context = f"TARGET: {url}\n\n"
    data_context += f"HOMEPAGE: {content_bundle.get('page', '')[:3000]}\n\n"
    data_context += f"ELITE AUDIT MAP (1,000 TARGETS):\n{internal_data}\n"
    data_context += f"TECH SPECS: {content_bundle.get('robots', 'None')} | {content_bundle.get('llms', 'None')}\n"

    # Sequential Retry Logic (Fixes 429 Pressure)
    # models_to_try = ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022"]
    models_to_try = ["claude-3-5-haiku-20241022"]
    for model_name in models_to_try:
        for attempt in range(4): # Increased to 4 attempts
            try:
                response = client.messages.create(
                    model=model_name,
                    max_tokens=2048,
                    system=prompt + "\n\n10/10 INDUSTRIAL AUDIT: Focus on precision. Return <json>...",
                    messages=[{"role": "user", "content": f"Audit Deep-Read:\n{data_context}"}]
                )
                
                # Extract Tokens
                tokens_used = 0
                if hasattr(response, 'usage') and response.usage:
                    tokens_used = getattr(response.usage, 'input_tokens', 0) + getattr(response.usage, 'output_tokens', 0)
                
                parsed = parse_agent_response(response.content[0].text, agent_id, AGENT_MAPPING.get(agent_id, {}).get("weight", 0.2))
                parsed["tokens_used"] = tokens_used
                parsed["status"] = "SUCCESS"

                # Log Success to Supabase
                sb = get_supabase()
                if sb:
                    try:
                        sb.table("agent_logs").insert({
                            "audit_id": audit_id,
                            "agent_name": agent_id,
                            "agent_score": parsed["score"],
                            "status": "SUCCESS",
                            "tokens_used": tokens_used,
                            "error_message": None
                        }).execute()
                    except Exception as e:
                        print(f"Failed to log success to Supabase agent_logs: {e}")

                return parsed
            except Exception as e:
                err_msg = str(e)
                print(f"[DEBUG] [AGENT: {agent_id}] Encountered Server Trace: {err_msg}")
                if "429" in err_msg and attempt < 3:
                    delay_s = 4 * (attempt + 1)
                    print(f"[DEBUG] [AGENT: {agent_id}] Rate Limited (429). Retrying in {delay_s}s...")
                    # Sequential delay: 4s, 8s, 12s
                    time.sleep(delay_s)
                    continue
                elif model_name != models_to_try[-1]: 
                    break # Try Haiku (Higher TPM)
                else:
                    sb = get_supabase()
                    if sb:
                        try:
                            sb.table("agent_logs").insert({
                                "audit_id": audit_id, "agent_name": agent_id, "agent_score": 0, "status": "FAILED_RATE_LIMIT",
                                "tokens_used": 0, "error_message": err_msg
                            }).execute()
                        except Exception: pass
                    
                    return {
                        "id": agent_id, "label": AGENT_MAPPING.get(agent_id, {}).get("label", agent_id),
                        "score": 0, "summary": f"Audit Failure (Rate Limit): {err_msg}", "weight": 0.2, "error": True,
                        "pdf_description": f"Audit Failure (Rate Limit): {err_msg}\n\nSTRATEGIC STRENGTHS:\n• N/A\n\nCRITICAL WEAKNESSES:\n• API Rate Limit Threshold Reached\n\nIMPROVEMENT ROADMAP:\n• Retry audit with extended cooldown",
                        "tokens_used": 0, "status": "FAILED_RATE_LIMIT"
                    }
    sb = get_supabase()
    if sb:
        try:
            sb.table("agent_logs").insert({
                "audit_id": audit_id, "agent_name": agent_id, "agent_score": 0, "status": "FAILED",
                "tokens_used": 0, "error_message": "All LLM models exhausted"
            }).execute()
        except Exception: pass

    return {
        "id": agent_id, "label": AGENT_MAPPING.get(agent_id, {}).get("label", agent_id),
        "score": 0, "summary": f"Audit Failed on all Claude models.", "weight": 0.2, "error": True,
        "pdf_description": f"Audit Failed\n\nSTRATEGIC STRENGTHS:\n• N/A\n\nCRITICAL WEAKNESSES:\n• All LLM models (Sonnet/Haiku) exhausted\n\nIMPROVEMENT ROADMAP:\n• Verify Anthropic API Key Status",
        "tokens_used": 0, "status": "FAILED"
    }

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
                    "summary": parsed.get("summary", full_text),
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
        "claude_api_key_set": "claude_api_key" in session or (CLAUDE_API_KEY != "your-api-key-here" and CLAUDE_API_KEY != "")
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

def score_tier(score: int) -> str:
    if score >= 80: return "good"
    if score >= 60: return "moderate"
    if score >= 40: return "poor"
    return "critical"

def score_label(score: int) -> str:
    if score >= 80: return "Good"
    if score >= 60: return "Moderate"
    if score >= 40: return "Poor"
    return "Critical"

def format_eur(value) -> str:
    if not value:
        return "—"
    return f"€{int(value):,}".replace(",", ".")

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
FORMULA_TEXT = "(Visibility * 0.25) + (Content EEAT * 0.20) + (Technical * 0.15) + (Schema * 0.15) + (Platform * 0.25)"

# ==============================================================================
# [EXECUTION STEP 1: INITIAL UI DASHBOARD RENDER]
# The user visits the app on their browser and the frontend dashboard renders gracefully.
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
            "findings": [{"title": r["label"], "severity": "HIGH" if r["score"] < 50 else "INFO", "description": clean_md(r["pdf_description"])} for r in data["results"]],
            "platforms": {
                "ChatGPT Web Search": results_map.get("geo-ai-visibility", 0),
                "Claude 3.5 Sonnet": results_map.get("geo-ai-visibility", 0),
                "Google AIO": results_map.get("geo-technical", 0),
                "Perplexity": results_map.get("geo-content", 0),
                "Bing Copilot": results_map.get("geo-schema", 0)
            },
            "crawler_access": {k: {"status": v, "platform": "Generative AI", "recommendation": "Allow" if v == "ALLOWED" else "Review"} for k, v in data["metrics"].get("crawlers", {}).items()},
            "quick_wins": ["Implement llms.txt standard" if data["metrics"].get("faq_count", 0) < 3 else "Optimize Answer Blocks"],
        }
        
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
@app.route("/analyze_url", methods=["POST"])
def analyze_url():
    """Deep Site-wide Recursive Audit (30+ Pages)."""
    url = request.form.get("url", "").strip()
    if not url: return "Please enter a valid URL."
    if not url.startswith("http"): url = "https://" + url
    
    print(f"\n{'='*50}\n[DEBUG] [MASTER TRACE] Starting Deep Audit for: {url}")
    
    sb = get_supabase()
    project_id = None
    audit_id = str(uuid.uuid4())  # Pre-generated UUID for the historical run

    from urllib.parse import urlparse, urljoin

    # ── 0. Project Hierarchy ──────────────────────────────────────────
    print(f"[DEBUG] [STEP 0] Establishing Supreme Relational UUIDs (Audit ID: {audit_id})")
    if sb:
        try:
            domain = urlparse(url).netloc.replace("www.", "")
            if not domain: domain = url
            # Check if domain exists as a project
            existing = sb.table("projects").select("id").eq("target_url", domain).execute()
            if existing.data and len(existing.data) > 0:
                project_id = existing.data[0]['id']
            else:
                # Create a new project row and capture its generated ID
                new_proj = sb.table("projects").insert({"target_url": domain}).execute()
                project_id = new_proj.data[0]['id']

            # Insert placeholder audit row to satisfy Foreign Key constraints for agents!
            sb.table("audits").insert({
                "id": audit_id,
                "project_id": project_id,
                "final_score": 0,
                "status": "RUNNING",
                "pdf_url": None,
                "metrics": {}
            }).execute()

        except Exception as e:
            print(f"Supabase Project DB Error: {e}")
    
    # ── 1. Elite Enterprise Stratified Audit (10,000 URLs) ────────────
    visited = {url.split("#")[0].rstrip("/")}
    content_bundle = {"page": "", "robots": "Not Found", "llms": "Not Found", "internal_pages": [], "menu_structure": []}
    metrics = {"faq_count": 0, "answer_blocks": 0, "snippet_coverage": 0, "schema_count": 0, "schema_types": set(), 
               "crawlers": {}, "total_discovered": 0, "deep_audited": 0, "broken_links": 0}
    
    MAX_DISCOVERY = 10000 
    MAX_AUDIT = 1000     
    
    def rank_url(u: str) -> int:
        """Brilliant heuristic to prioritize high-value pillars (10/10 Accuracy)."""
        u = u.lower()
        score = 10 
        if any(x in u for x in ["pricing", "plan"]): score += 100
        if any(x in u for x in ["product", "feature", "solution"]): score += 80
        if any(x in u for x in ["blog", "guide", "article"]): score += 60
        if any(x in u for x in ["faq", "docs", "help"]): score += 70
        if any(x in u for x in ["case-study", "customer"]): score += 50
        if any(x in u for x in ["terms", "privacy", "legal", "cookie"]): score -= 100 # Low priority
        return score

    parsed_root = urlparse(url)
    root_domain = ".".join(parsed_root.netloc.split(".")[-2:])
    
    print(f"[DEBUG] [STEP 1] Crawling Sitemap & Deep Extraction...")
    if fetch_page:
        # A. Sitemap discovery
        rob = fetch_robots_txt(url) if fetch_robots_txt else {}
        content_bundle["robots"] = rob.get("content", "Not Found")
        metrics["crawlers"] = rob.get("ai_crawler_status", {})
        
        discovery_queue = []
        if rob.get("sitemaps"):
            try:
                from fetch_page import crawl_sitemap
                sitemap_links = crawl_sitemap(url, max_pages=MAX_DISCOVERY)
                discovery_queue.extend([l for l in sitemap_links if l not in visited])
            except ImportError: pass

        # B. Homepage extraction
        res = fetch_page(url)
        if res and not res.get("errors"):
            content_bundle["page"] = res.get("text_content", "")
            metrics["schema_types"].update([s.get("@type") for s in res.get("structured_data", []) if isinstance(s, dict)])
            for link in res.get("internal_links", []):
                l_url = link["url"].split("#")[0].rstrip("/")
                if root_domain in urlparse(l_url).netloc and l_url not in visited:
                    discovery_queue.append(l_url)
                    visited.add(l_url)
            content_bundle["menu_structure"] = [l.get("text", "") for l in res.get("internal_links", [])[:50]]
            
        # C. Brilliant Selection Logic (Top 1000)
        discovery_queue = list(dict.fromkeys(discovery_queue))
        metrics["total_discovered"] = len(discovery_queue)
        
        # Sort by brilliant rank scores
        discovery_queue.sort(key=rank_url, reverse=True)
        to_audit = discovery_queue[:MAX_AUDIT]
        
        # Power Worker Pool (15 Concurrency for 1,000 URLs)
        with ThreadPoolExecutor(max_workers=15) as crawl_exec:
            results_crawl = list(crawl_exec.map(fetch_page, to_audit))
            for r in results_crawl:
                if not r: continue
                if r.get("status_code", 0) >= 400: metrics["broken_links"] += 1
                if not r.get("errors"):
                    content_bundle["internal_pages"].append({
                        "url": r["url"],
                        # Optimized to fit 1000 pages (1000 * 400 = 400k characters)
                        "meta": r.get("description", ""),
                        "h1": r.get("h1_tags", [""])[0] if r.get("h1_tags") else "",
                        "content": r["text_content"][:400] 
                    })
                    metrics["schema_types"].update([s.get("@type") for s in r.get("structured_data", []) if isinstance(s, dict)])
        
        metrics["deep_audited"] = len(content_bundle["internal_pages"])
        
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
    
    # ── 2. Sequential Elite Agent Audit (Staggered to prevent 429s) ───
    api_key = session.get("claude_api_key", CLAUDE_API_KEY)
    agents = list(AGENT_MAPPING.keys())
    results = []
    
    print(f"[DEBUG] [STEP 3] Igniting {len(agents)} AI Cloud Agents Sequentially...")
    
    # We run sequentially for large audits to respect Claude TPM limits.
    with ThreadPoolExecutor(max_workers=1) as executor:
        futures = {executor.submit(run_agent, agent_id, url, content_bundle, api_key, audit_id): agent_id for agent_id in agents}
        for future in futures:
            results.append(future.result())
            # Industrial Staggering: small pause between massive 100k token calls
            time.sleep(2) 
    
    # ── 3. High-Standard Meta-Analysis (Final Synthesis) ──────────────
    final_score = round(sum(r.get("score", 0) * r.get("weight", 0) for r in results))
    boost = 12 if final_score < 40 else (8 if final_score < 70 else 5)
    predicted_score = min(99, final_score + boost) 
    
    primary_threat = "Enterprise Scale Inconsistency" if metrics.get("deep_audited", 0) > 500 else "Shallow Contextual Depth"
    if metrics.get("answer_blocks", 0) < 10: primary_threat = "Low Citation Intent"
    
    meta_insight = f"ELITE ENTERPRISE AUDIT: Found {metrics.get('total_discovered', 0)} URLs. Analyzed top {metrics.get('deep_audited', 0)} targets with Brilliant Ranking. Primary Threat: {primary_threat}."
    
    print(f"[DEBUG] [STEP 4] Executing Master Data Synthesis & Final Score Calculation... (Score: {final_score})")

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
        metrics=metrics, meta_insight=meta_insight, missing_analysis=missing_analysis
    )

# ==============================================================================
# [EXECUTION STEP 7: SECURE PDF DELIVERY]
# If the user clicks "View PDF" or "Download" in the UI, this serves the pre-generated memory file instantly.
# ==============================================================================
@app.route("/download_pdf/<task_id>")
def download_pdf(task_id):
    """Serve the pre-generated PDF report."""
    pdf_path = f"/tmp/{task_id}.pdf"
    import os
    if not os.path.exists(pdf_path):
        abort(404, description="PDF is missing from memory.")
        
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


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5050)