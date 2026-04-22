import json
import re
import time
import random
import anthropic
from pathlib import Path
from .config import AGENT_DIR, SCHEMA_DIR, SKILLS_DIR, AGENT_MAPPING, AGENT_SKILL_MAP
from .utils import clean_html_for_ai, sync_summary_scores
from .database import save_agent_log

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
    if not api_key: return {"id": agent_id, "score": 0, "summary": "API key not set.", "top_fixes": [], "weight": 0}
    client = anthropic.Anthropic(api_key=api_key)
    prompt = load_agent_prompt(agent_id)
    if not prompt: return {"id": agent_id, "score": 0, "summary": f"Agent {agent_id} instructions not found.", "top_fixes": [], "weight": 0}

    data_context = prepare_agent_payload(agent_id, url, content_bundle)
    
    tools = [{
        "name": "submit_audit_result",
        "description": "Submit finalized GEO audit scores and findings.",
        "input_schema": {
            "type": "object",
            "properties": {
                "score": {"type": "integer"},
                "restricted": {"type": "boolean"},
                "restriction_reason": {"type": "string"},
                "summary": {"type": "string"},
                "weaknesses": {"type": "array", "items": {"type": "object", "properties": {"issue": {"type": "string"}, "evidence_url": {"type": "string"}}}},
                "findings": {"type": "array", "items": {"type": "object", "properties": {"title": {"type": "string"}, "severity": {"enum": ["critical", "high", "medium", "low"]}}}},
                "suggested_code": {"type": "array", "items": {"type": "object", "properties": {"file_name": {"type": "string"}, "code": {"type": "string"}}}}
            },
            "required": ["score", "summary", "weaknesses", "findings"]
        }
    }]

    for model_name in ["claude-3-haiku-20240307"]:
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
                
                save_agent_log(audit_id, agent_id, parsed, tokens_used)
                return parsed
            except Exception as e:
                if "429" in str(e) and attempt < 2: time.sleep(4 * (attempt + 1)); continue
                break
    return {"id": agent_id, "score": 0, "summary": "Audit Failed on all Claude models.", "weight": 0.2, "status": "FAILED"}
