import json
import re
import time
import random
import anthropic
from pathlib import Path

try:
    from .config import AGENT_DIR, SCHEMA_DIR, SKILLS_DIR, AGENT_MAPPING, AGENT_SKILL_MAP
    from .utils import clean_html_for_ai, sync_summary_scores
    from .database import save_agent_log
except (ImportError, ValueError):
    import config
    import utils
    import database
    from config import AGENT_DIR, SCHEMA_DIR, SKILLS_DIR, AGENT_MAPPING, AGENT_SKILL_MAP
    from utils import clean_html_for_ai, sync_summary_scores
    from database import save_agent_log

def load_agent_prompt(name: str) -> str:
    path = AGENT_DIR / f"{name}.md"
    return path.read_text() if path.exists() else ""

def extract_skill_logic(skill_name: str) -> str:
    """Extract only the core logic/checklists from a SKILL.md to optimize tokens."""
    skill_path = SKILLS_DIR / skill_name / "SKILL.md"
    if not skill_path.exists(): return ""
    try:
        content = skill_path.read_text()
        start_markers = ["## Purpose", "## Category", "## E-E-A-T", "## Audit Workflow"]
        start_idx = -1
        for m in start_markers:
            idx = content.find(m)
            if idx != -1 and (start_idx == -1 or idx < start_idx):
                start_idx = idx
        if start_idx == -1: return ""
        end_idx = content.find("## Output Format")
        if end_idx == -1: end_idx = len(content)
        meat = content[start_idx:end_idx].strip()
        return f"\n--- ELITE LOGIC: {skill_name.upper()} ---\n{meat}\n"
    except Exception: return ""

def load_schema_templates() -> str:
    templates_block = "=== STANDARD_SCHEMA_TEMPLATES_GROUND_TRUTH ===\n"
    if not SCHEMA_DIR.exists(): return ""
    for schema_file in SCHEMA_DIR.glob("*.json"):
        try:
            name = schema_file.name
            content = schema_file.read_text()
            templates_block += f"\nFILE: {name}\nCONTENT:\n{content}\n"
        except Exception: pass
    return templates_block

def prepare_agent_payload(agent_id: str, url: str, content_bundle: dict) -> str:
    """Enterprise Router: Deliver only relevant specialized data per agent."""
    context = f"TARGET_URL: {url}\n"
    context += "=== AUDIT_METADATA (INDUSTRIAL PROOF) ===\n"
    context += "AUDIT_NODE_ORIGIN: US-East (Virginia)\n"
    context += "AUDIT_MEASUREMENT_ENGINE: Playwright-Stealth Crawler Engine (v4.2)\n"
    context += f"TIMESTAMP: {time.strftime('%Y-%m-%dT%H:%M:%S')}\n"
    context += "========================================\n\n"
    
    graveyard = content_bundle.get("metrics", {}).get("diagnostics", [])
    if graveyard:
        context += "=== INTERNAL_DIAGNOSTICS (THE GRAVEYARD) ===\n"
        for entry in graveyard[:50]:
            context += f"• {entry.get('url')} | STATUS: {entry.get('status')} | ERROR: {entry.get('error')}\n"
        context += "============================================\n\n"
    
    brand_report = content_bundle.get("brand_report", {})
    if brand_report:
        context += f"BRAND_VISIBILITY_GROUND_TRUTH: {json.dumps(brand_report)}\n\n"
        
    pages = content_bundle.get('internal_pages', [])
    skills_to_load = AGENT_SKILL_MAP.get(agent_id, [])
    sop_block = ""
    if skills_to_load:
        sop_block = "\n=== ELITE INDUSTRIAL STANDARD OPERATING PROCEDURES (SOP) ===\n"
        for s in skills_to_load: sop_block += extract_skill_logic(s)
    
    if agent_id == "geo-schema":
        schema_data = ""
        for p in pages: schema_data += f"--- SCHEMA FRAGMENT: {p['url']} ---\nJSON-LD: {json.dumps(p.get('structured_data', []))}\n\n"
        return context + f"AUDIT DATA (FULL SCHEMA ONLY):\n{schema_data}\n\n{load_schema_templates()}\n" + sop_block

    elif agent_id == "geo-technical":
        tech_data = ""
        for p in pages:
            tech_data += f"--- TECH SCAN: {p['url']} ---\nHTTP: {json.dumps(p.get('security_headers', {}))}\nMETRICS: {p.get('page_weight_kb')}KB | TTFB: {p.get('ttfb_ms')}ms | SSR: {p.get('has_ssr')}\n"
        return context + f"AUDIT DATA (TECHNICAL HEADERS ONLY):\n{tech_data}\nROBOTS: {content_bundle.get('robots')}\n" + sop_block

    elif agent_id == "geo-content":
        content_data = ""
        for i, p in enumerate(pages):
            cleaned = clean_html_for_ai(p.get('content', ''))
            limit = 8000 if i == 0 else 1000
            content_data += f"--- CONTENT DEEP DIVE: {p['url']} ---\nH1: {p.get('h1')}\nBODY: {cleaned[:limit]}\n"
        return context + f"AUDIT DATA (TEXT CONTENT ONLY):\n{content_data}\n" + sop_block

    elif agent_id == "geo-executive-roadmap":
        results_context = "\n=== SPECIALIST AUDIT RESULTS (QA & CONSISTENCY CHECK) ===\n"
        for r in content_bundle.get("agent_results", []):
            results_context += f"AGENT: {r['label']} | SCORE: {r['score']}\nSUMMARY: {r['summary']}\nWEAKNESSES: {json.dumps(r.get('weaknesses', []))}\n"
        return context + results_context + sop_block

    return context + str(content_bundle) + sop_block

def run_agent(agent_id: str, url: str, content_bundle: dict, api_key: str, audit_id: str):
    if not api_key or api_key == "your-api-key-here": 
        return {"id": agent_id, "label": agent_id, "score": 0, "summary": "API Key not provided. Please enter your Anthropic API Key in the web interface.", "top_fixes": [], "weight": 0}
    client = anthropic.Anthropic(api_key=api_key)
    prompt = load_agent_prompt(agent_id)
    if not prompt: return {"id": agent_id, "label": agent_id, "score": 0, "summary": f"Agent {agent_id} instructions not found.", "top_fixes": [], "weight": 0}

    data_context = prepare_agent_payload(agent_id, url, content_bundle)
    
    tools = [{
        "name": "submit_audit_result",
        "description": "Submit finalized GEO audit scores and findings for industrial reports.",
        "input_schema": {
            "type": "object",
            "properties": {
                "score": {"type": "integer", "description": "The current audited GEO score (0-100)"},
                "summary": {"type": "string", "description": "High-fidelity strategic summary (markdown-friendly)"},
                "roadmap": {"type": "array", "items": {"type": "string"}, "description": "Step-by-step action plan of prioritized fixes"},
                "weaknesses": {
                    "type": "array", 
                    "items": {
                        "type": "object", 
                        "properties": {
                            "issue": {"type": "string"},
                            "category": {"type": "string"},
                            "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                            "evidence_url": {"type": "string"},
                            "evidence_snippet": {"type": "string"},
                            "explanation": {"type": "string"}
                        },
                        "required": ["issue", "severity", "evidence_snippet"]
                    }
                },
                "strengths": {"type": "array", "items": {"type": "string"}},
                "restricted": {"type": "boolean"},
                "restriction_reason": {"type": "string"}
            },
            "required": ["score", "summary", "roadmap", "weaknesses"]
        }
    }]

    # Fallback chain: Premium Haiku -> Stable Haiku -> Legacy Sonnet (if needed)
    for model_name in ["claude-haiku-4-5", "claude-3-5-haiku-20241022"]:
        for attempt in range(3):
            try:
                time.sleep(random.uniform(0.5, 2.0))
                response = client.messages.create(
                    model=model_name, max_tokens=4096, system=prompt, tools=tools,
                    tool_choice={"type": "tool", "name": "submit_audit_result"},
                    messages=[{"role": "user", "content": f"AUDIT CONTEXT:\n{data_context}"}]
                )
                tool_use = next(block for block in response.content if block.type == "tool_use")
                parsed = tool_use.input
                tokens_used = response.usage.input_tokens + response.usage.output_tokens
                parsed.update({
                    "id": agent_id, "label": AGENT_MAPPING.get(agent_id, {}).get("label", agent_id),
                    "weight": AGENT_MAPPING.get(agent_id, {}).get("weight", 0.2),
                    "tokens_used": tokens_used, "status": "RESTRICTED" if parsed.get("restricted") else "SUCCESS"
                })
                if parsed.get("restricted"):
                    parsed["score"] = 0
                    parsed["summary"] = f"🚨 [RESTRICTED DATA]: {parsed.get('restriction_reason')}\n\n{parsed.get('summary', '')}"
                
                # Use sync_summary_scores here if needed
                parsed["summary"] = sync_summary_scores(parsed["summary"], parsed["score"])
                
                save_agent_log(audit_id, agent_id, parsed, tokens_used)
                return parsed
            except Exception as e:
                print(f"[ERROR] Agent {agent_id} failed on {model_name} (Attempt {attempt+1}/3): {str(e)}")
                if "429" in str(e) and attempt < 2: 
                    time.sleep(5 * (attempt + 1))
                    continue
                # If it's a 404 (Model not found), don't retry on the same model
                if "404" in str(e) or "not found" in str(e).lower():
                    break
        # Continue to next model in fallback chain
    
    error_msg = "Audit Failed: Missing or Invalid API Key." if (not api_key or api_key == "your-api-key-here") else f"Audit Failed on all models. Last error usually: {str(e) if 'e' in locals() else 'Unknown'}"
    return {"id": agent_id, "label": agent_id, "score": 0, "summary": error_msg, "weight": 0.2, "status": "FAILED"}

def simulate_geo_query(brand: str, context_text: str = "", api_key: str = None) -> dict:
    """Industrial AI Simulation: Evaluates citation probability for the brand."""
    common_queries = [f"What is {brand}?", f"Top {brand} alternatives", f"How does {brand} work?"]
    if not api_key or not context_text:
        return {"queries_tested": common_queries, "citation_potential": "Medium", "status": "Incomplete Simulation"}
    try:
        client = anthropic.Anthropic(api_key=api_key)
        prompt = f"You are a Search AI. Based on the context, how likely are you to cite '{brand}' for 'What is {brand}?'?\n\nCONTEXT:\n{context_text[:2000]}"
        response = client.messages.create(model="claude-3-haiku-20240307", max_tokens=500, messages=[{"role": "user", "content": prompt}])
        ans = response.content[0].text
        return {
            "queries_tested": common_queries, 
            "citation_potential": "High" if "very likely" in ans.lower() or "strong candidate" in ans.lower() else "Medium",
            "mock_ai_result": ans[:300] + "...",
            "citations_found": 3 if "High" else 1
        }
    except Exception as e: return {"queries_tested": common_queries, "status": f"Error: {e}"}

def run_triage_agent(discovery_queue: list, api_key: str) -> list:
    """Triage Agent: Efficiently filters URLs → 50 high-value targets."""
    if not api_key or not discovery_queue: return discovery_queue[:50]
    client = anthropic.Anthropic(api_key=api_key)
    prompt = load_agent_prompt("triage-agent")
    if not prompt: return [u["url"] if isinstance(u, dict) else u for u in discovery_queue[:50]]
    url_text = "\n".join([f"{i}: {u}" for i, u in enumerate(discovery_queue[:5000])])
    try:
        response = client.messages.create(model="claude-3-haiku-20240307", max_tokens=2048, system=prompt, messages=[{"role": "user", "content": f"URL LIST FOR TRIAGE:\n{url_text}"}])
        json_match = re.search(r"\{.*\}", response.content[0].text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group(0))
            raw_selections = data.get("selected_indices", [])
            final_targets = []
            for item in raw_selections:
                idx = item["index"] if isinstance(item, dict) else item
                if idx < len(discovery_queue): final_targets.append(discovery_queue[idx])
            return [u["url"] if isinstance(u, dict) else u for u in final_targets[:70]]
    except Exception: pass
    return [u["url"] if isinstance(u, dict) else u for u in discovery_queue[:50]]
