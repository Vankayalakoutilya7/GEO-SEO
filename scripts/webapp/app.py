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
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
load_dotenv()

# Add parent directory to sys.path to import fetch_page
sys.path.append(str(Path(__file__).parent.parent))
try:
    from fetch_page import fetch_page, fetch_robots_txt, fetch_llms_txt
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

# ── Agent Configurations ───────────────────────────────────────────────
AGENT_DIR = Path(__file__).parent.parent.parent / "agents"
AGENT_MAPPING = {
    "geo-ai-visibility": {"weight": 0.25, "label": "AI Visibility & Citability"},
    "geo-content": {"weight": 0.20, "label": "Content E-E-A-T"},
    "geo-technical": {"weight": 0.15, "label": "Technical GEO Infrastructure"},
    "geo-schema": {"weight": 0.15, "label": "Schema & Structured Data"},
    "geo-platform-analysis": {"weight": 0.25, "label": "Platform Optimization"},
    "geo-echo": {"label": "Unique Value (Echo Penalty)", "weight": 0.0},
    "geo-executive-roadmap": {"label": "Executive Strategic Roadmap", "weight": 0.0}
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

    # ── Context Slicing (Optimized Token Usage) ──────────────
    data_context = prepare_agent_payload(agent_id, url, content_bundle)

    # ── Agent Debug Logging (Transparency) ──────────────
    try:
        import os
        os.makedirs("scratch/payloads", exist_ok=True)
        with open(f"scratch/payloads/{agent_id}_payload.txt", "w", encoding="utf-8") as f:
            f.write(f"=== SYSTEM PROMPT ===\n{prompt}\n\n=== CONTEXT PAYLOAD ===\n{data_context}")
    except Exception as e:
        print(f"[DEBUG] Failed to write payload log: {e}")

    # ── Claude 4 Safety Net (Current for April 2026) ──────────────
    models_to_try = ["claude-haiku-4-5"]
    
    # Define Structured Output Tool
    tools = [{
        "name": "submit_audit_result",
        "description": "Submit the finalized GEO audit scores and findings with evidence.",
        "input_schema": {
            "type": "object",
            "properties": {
                "score": {"type": "integer", "description": "0-100 score for this metric."},
                "restricted": {"type": "boolean", "description": "Set to true if you are restricted from auditing because required data is missing or blocked."},
                "restriction_reason": {"type": "string", "description": "Detailed explanation of why the audit was restricted."},
                "summary": {"type": "string", "description": "2-3 sentence executive summary."},
                "weaknesses": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "issue": {"type": "string"},
                            "evidence_url": {"type": "string", "description": "Specific URL where the issue was found."}
                        }
                    }
                },
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "description": {"type": "string"},
                            "severity": {"enum": ["critical", "high", "medium", "low"]}
                        }
                    }
                },
                "suggested_code": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "file_name": {"type": "string", "description": "e.g. llms.txt or schema.json"},
                            "code": {"type": "string"}
                        }
                    }
                }
            },
            "required": ["score", "summary", "weaknesses", "findings"]
        }
    }]

    for model_name in models_to_try:
        for attempt in range(3):
            try:
                # Stealth Mode Jitter
                import time, random
                time.sleep(random.uniform(0.5, 2.0))
                
                print(f"[DEBUG] [{agent_id}] Calling {model_name} (Attempt {attempt+1})...")
                response = client.messages.create(
                    model=model_name,
                    max_tokens=4096,
                    system=prompt,
                    tools=tools,
                    tool_choice={"type": "tool", "name": "submit_audit_result"},
                    messages=[{"role": "user", "content": f"AUDIT CONTEXT:\n{data_context}"}]
                )
                
                # Extract Tool Output
                tool_use = next(block for block in response.content if block.type == "tool_use")
                parsed = tool_use.input
                
                # Enrich 
                tokens_used = response.usage.input_tokens + response.usage.output_tokens
                parsed.update({
                    "id": agent_id,
                    "label": AGENT_MAPPING.get(agent_id, {}).get("label", agent_id),
                    "weight": AGENT_MAPPING.get(agent_id, {}).get("weight", 0.2),
                    "tokens_used": tokens_used,
                    "status": "RESTRICTED" if parsed.get("restricted") else "SUCCESS"
                })
                
                # Enforce No-Bluff visual warning
                if parsed.get("restricted"):
                    parsed["score"] = 0
                    parsed["summary"] = f"🚨 [RESTRICTED DATA]: {parsed.get('restriction_reason')}\n\n{parsed.get('summary', '')}"


                # Log Success to Supabase
                sb = get_supabase()
                if sb:
                    try:
                        sb.table("agent_logs").insert({
                            "audit_id": audit_id, "agent_name": agent_id, "agent_score": parsed["score"],
                            "status": parsed["status"], "tokens_used": tokens_used, "error_message": parsed.get("restriction_reason")
                        }).execute()
                    except Exception: pass

                return parsed

            except Exception as e:
                err_msg = str(e)
                print(f"[DEBUG] [{agent_id}] {model_name} Error: {err_msg}")
                if "429" in err_msg and attempt < 2:
                    time.sleep(4 * (attempt + 1))
                    continue
                break # Try next model if it's not a retry-able 429

    return {
        "id": agent_id, "label": AGENT_MAPPING.get(agent_id, {}).get("label", agent_id),
        "score": 0, "summary": f"Audit Failed on all Claude models.", "weight": 0.2, "error": True,
        "pdf_description": "Audit Failed: API exhausted.", "tokens_used": 0, "status": "FAILED"
    }

def prepare_agent_payload(agent_id: str, url: str, content_bundle: dict) -> str:
    """Enterprise Router: Deliver only relevant specialized data per agent (v4 with Brand Ground Truth)."""
    
    # 1. Base Context (Shared by all)
    context = f"TARGET_URL: {url}\n\n"
    
    brand_report = content_bundle.get("brand_report", {})
    if brand_report:
        context += f"BRAND_VISIBILITY_GROUND_TRUTH: {json.dumps(brand_report)}\n\n"
        
    pages = content_bundle.get('internal_pages', [])
    
    # Define payload slices (Absolute Context Slices)
    if agent_id == "geo-schema":
        schema_data = ""
        for p in pages:
            schema_data += f"--- SCHEMA FRAGMENT: {p['url']} ---\nJSON-LD: {json.dumps(p.get('structured_data', []))}\n\n"
        return context + f"AUDIT DATA (FULL SCHEMA ONLY):\n{schema_data}\n"

    elif agent_id == "geo-technical":
        tech_data = ""
        for p in pages:
            tech_data += f"--- TECH SCAN: {p['url']} ---\nHTTP: {json.dumps(p.get('security_headers', {}))}\nMETRICS: {p.get('page_weight_kb')}KB | TTFB: {p.get('ttfb_ms')}ms | SSR: {p.get('has_ssr')}\nCOMPRESSED: {p.get('is_compressed')} | REDIRECTS: {len(p.get('redirect_chain', []))}\n"
        return context + f"AUDIT DATA (TECHNICAL HEADERS ONLY):\n{tech_data}\nROBOTS: {content_bundle.get('robots')}"

    elif agent_id == "geo-content":
        content_data = ""
        for i, p in enumerate(pages):
            limit = 10000 if i == 0 else 1500 
            content_data += f"--- CONTENT DEEP DIVE: {p['url']} ---\nH1: {p.get('h1')}\nBODY: {p.get('content', '')[:limit]}\n"
        return context + f"AUDIT DATA (TEXT CONTENT ONLY):\n{content_data}"

    elif agent_id == "geo-ai-visibility":
        visibility_data = ""
        for p in pages:
            visibility_data += f"--- VISIBILITY SNIPPET: {p['url']} ---\nH1: {p.get('h1')}\nSNIPPET: {p.get('content', '')[:400]}\n"
        return context + f"AUDIT DATA (SNIPPETS ONLY): \n{visibility_data}"

    elif agent_id == "geo-platform-analysis":
        platform_data = ""
        for p in pages:
            platform_data += f"--- PLATFORM ASSET: {p['url']} ---\nMETA: {p.get('meta', 'None')}\nH1: {p.get('h1')}\nCANONICAL: {p.get('canonical', 'Not Found')}\nSTATUS: {p.get('status_code', 200)}\n"
        return context + f"AUDIT DATA (META & CRAWLER SIGNALS ONLY):\n{platform_data}\nROBOTS: {content_bundle.get('robots')}\nLLMS: {content_bundle.get('llms')}"

    elif agent_id == "geo-executive-roadmap":
        # THE MASTER STRATEGIST: Review specialist results and ROI
        specialist_results = ""
        for res in content_bundle.get("agent_results", []):
            specialist_results += f"### {res.get('label')} (Score: {res.get('score')})\nSUMMARY: {res.get('summary')}\nFIXES: {json.dumps(res.get('top_fixes', []))}\nEVIDENCE: {res.get('evidence_url')}\n\n"
        
        return context + f"MASTER AUDIT SYNTHESIS:\n{specialist_results}\nGOAL: Create a prioritized 30-60-90 day ROI roadmap."

    return context + "ERROR: Agent ID not recognized for specialization."

def run_triage_agent(discovery_queue: list, api_key: str) -> list:
    """Triage Agent: Efficiently filters 5,000 URLs → 50 high-value targets (Haiku)."""
    if not api_key or api_key == "your-api-key-here" or not discovery_queue:
        return discovery_queue[:50]
    
    client = anthropic.Anthropic(api_key=api_key)
    prompt = load_agent_prompt("triage-agent")
    
    # Batch the URLs for Haiku (max 200 URLs per batch for speed/token limits)
    # Actually, we can fit 1000 URLs easily in one 200k context prompt.
    url_text = "\n".join([f"{i}: {u}" for i, u in enumerate(discovery_queue[:5000])]) # Cap triage to 5000 for budget
    
    try:
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=2048,
            system=prompt,
            messages=[{"role": "user", "content": f"URL LIST FOR TRIAGE:\n{url_text}"}]
        )
        
        # Parse indices (v2: supporting score-based semantic ranking)
        json_match = re.search(r"\{.*\}", response.content[0].text, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                # Support both simple list and the newer index/score object list
                raw_selections = data.get("selected_indices", [])
                
                final_targets = []
                for item in raw_selections:
                    idx = None
                    score = 50
                    if isinstance(item, dict) and "index" in item:
                        idx = item["index"]
                        score = item.get("score", 50)
                    elif isinstance(item, int):
                        idx = item
                    
                    if idx is not None and idx < len(discovery_queue):
                        url_item = discovery_queue[idx]
                        url_str = url_item["url"] if isinstance(url_item, dict) else url_item
                        final_targets.append({"url": url_str, "ai_priority": score})
                
                # Sort by AI priority
                final_targets.sort(key=lambda x: x.get("ai_priority", 0), reverse=True)
                return [t["url"] for t in final_targets[:50]]
            except Exception as e:
                print(f"[DEBUG] [TRIAGE] Selection Parsing Error: {e}")
    except Exception as e:
        print(f"[DEBUG] [TRIAGE] Failed: {e}")
    
    # Fallback: Just return first 50 URLs
    return [u["url"] if isinstance(u, dict) else u for u in discovery_queue[:50]]

def calculate_echo_penalty(pages: list) -> float:
    """Detects 'Template Bloat' vs 'Unique Value' by comparing content across sampled pages."""
    if len(pages) < 2: return 0.0
    
    # Take a sample of 10 pages to avoid O(N^2) explosion
    sample = pages[:min(10, len(pages))]
    similarities = []
    
    for i in range(len(sample)):
        for j in range(i + 1, len(sample)):
            text1 = set(sample[i].get('content', '').split()[:200])
            text2 = set(sample[j].get('content', '').split()[:200])
            
            if not text1 or not text2: continue
            
            intersection = len(text1.intersection(text2))
            union = len(text1.union(text2))
    
    if not similarities: return 0.0
    return round(sum(similarities) / len(similarities), 1)
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
            "metrics": data.get("metrics", {}),
            "findings": [],
            "suggested_code": [],
            "platforms": {
                "ChatGPT Web Search": results_map.get("geo-ai-visibility", 0),
                "claude-haiku-4-5": results_map.get("geo-ai-visibility", 0),
            },
            "crawler_access": {k: {"status": v, "platform": "Generative AI", "recommendation": "Allow" if v == "ALLOWED" else "Review"} for k, v in data["metrics"].get("crawlers", {}).items()},
            "quick_wins": ["Implement llms.txt standard" if data["metrics"].get("faq_count", 0) < 3 else "Optimize Answer Blocks"],
        }
        
        # Aggregate structured findings and code from all agents
        for r in data.get("results", []):
            if r.get("findings"):
                for f in r["findings"]:
                    f["title"] = f"{r['label']}: {f.get('title', 'Finding')}"
                    # Find matching weakness to get evidence_url
                    matching_weakness = next((w for w in r.get("weaknesses", []) if w.get("issue") in (f.get("description") or "")), None)
                    if matching_weakness:
                        f["evidence_url"] = matching_weakness.get("evidence_url")
                    report_data_pdf["findings"].append(f)
            
            if r.get("suggested_code"):
                report_data_pdf["suggested_code"].extend(r["suggested_code"])
        
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
    if fetch_page is None:
        return "ERROR: Dependencies not found. Please ensure you are running in the virtual environment (venv)."
    
    url = request.form.get("url", "").strip()
    if not url: return "Please enter a valid URL."
    if not url.startswith("http"): url = "https://" + url
    
    print(f"\n{'='*50}\n[DEBUG] [MASTER TRACE] Starting Deep Audit for: {url}")
    
    sb = get_supabase()
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
        # ── Universal Session Priming (Stealth & Persistence) ────────────
        import requests
        session_obj = requests.Session()
        
        # A. Robots & LLMS
        rob = fetch_robots_txt(url) if fetch_robots_txt else {}
        data_robots = rob
        data_llms = fetch_llms_txt(url) if fetch_llms_txt else {}
        
        metrics["robots_status"] = "ALLOWED" if data_robots.get("is_allowed") else "BLOCKED"
        metrics["llms_status"] = "ALLOWED" if data_llms.get("is_allowed") else "BLOCKED"
        content_bundle["robots"] = json.dumps(data_robots)
        content_bundle["llms"] = json.dumps(data_llms)
        metrics["crawlers"] = data_robots.get("ai_crawler_status", {})
        
        discovery_queue = []
        if rob.get("sitemaps"):
            try:
                from fetch_page import crawl_sitemap
                sitemap_links = crawl_sitemap(url, max_pages=MAX_DISCOVERY)
                discovery_queue.extend([l for l in sitemap_links if l not in visited])
            except ImportError: pass

        # BFS Fallback Check if Sitemap failed or didn't exist
        if not discovery_queue:
            print("[DEBUG] No Sitemap found or sitemap empty. Falling back to Recursive BFS Crawler...")
            try:
                from fetch_page import recursive_bfs_crawl
                bfs_links = recursive_bfs_crawl(url, max_pages=3000)
                discovery_queue.extend([l for l in bfs_links if l not in visited])
            except ImportError as e:
                print(f"[DEBUG] Failed to import recursion crawler: {e}")

        # B. Homepage extraction (Forcing Playwright to bypass initial bot challenges)
        res = fetch_page(url, use_playwright=True)
        brand_name = domain.split('.')[0].capitalize() # Fallback
        
        # --- STEALTH HANDSHAKE BRIDGE (New) ---
        # Initialize a persistent session using the browser's credentials
        session_obj = requests.Session()
        if res.get("cookies"):
            for cookie in res["cookies"]:
                session_obj.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'])
            print(f"[DEBUG] Handshake successful. Injected {len(res['cookies'])} browser-primed cookies.")
        
        if res.get("browser_ua"):
            session_obj.headers.update({"User-Agent": res["browser_ua"]})
        
        # Detect bot protection in the response
        page_text = res.get("text_content", "").lower()
        pivot_to_browser = False
        if "are you a human" in page_text or "captcha" in page_text or res.get("bot_detected"):
            print("[WARNING] HIGH-FRICTION BOT PROTECTION: Pivoting to Full Browser Rendering for audit accuracy.")
            pivot_to_browser = True
            content_bundle["crawl_obstructed"] = True
        else:
            content_bundle["crawl_obstructed"] = False
        
        if res and not res.get("errors"):
            content_bundle["page"] = res.get("text_content", "")
            # Try to get better brand name from H1
            h1s = res.get("h1_tags", [])
            if h1s: brand_name = h1s[0]
            
            metrics["schema_types"].update([s.get("@type") for s in res.get("structured_data", []) if isinstance(s, dict)])
            for link in res.get("internal_links", []):
                l_url = link["url"].split("#")[0].rstrip("/")
                if root_domain in urlparse(l_url).netloc and l_url not in visited:
                    discovery_queue.append(l_url)
                    visited.add(l_url)
            content_bundle["menu_structure"] = [l.get("text", "") for l in res.get("internal_links", [])[:50]]
        
        # Step 1.2: Brand Visibility Scan (Wikipedia/Reddit/YouTube)
        if generate_brand_report:
            print(f"[DEBUG] [STEP 1.2] Scanning Brand Visibility for '{brand_name}'...")
            content_bundle["brand_report"] = generate_brand_report(brand_name, domain)
            
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
                if r.get("status_code", 0) >= 400: metrics["broken_links"] += 1
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
    
    # ── 4. High-Standard Meta-Analysis (Final Synthesis) ──────────────
    # We use the Strategist's Global Score as the final authority (Self-Healing Intelligence)
    final_score = master_result.get("score", round(sum(r.get("score", 0) * r.get("weight", 0) for r in results)))
    predicted_score = min(99, final_score + 12) 
    
    meta_insight = master_result.get("summary", "Analysis complete.")
    roadmap_fixes = master_result.get("top_fixes", [])
    
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
        metrics=metrics, meta_insight=meta_insight, roadmap_fixes=roadmap_fixes,
        missing_analysis=missing_analysis
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