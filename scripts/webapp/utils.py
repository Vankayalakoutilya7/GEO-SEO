import re
import json
import os
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup

def clean_html_for_ai(html_content: str) -> str:
    """Smart Stripper: Removes boilerplate (nav, footer, script, style) to save tokens."""
    if not html_content: return ""
    try:
        soup = BeautifulSoup(html_content, "lxml")
        # 1. Strip mission-critical noise
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
            tag.decompose()
        # 2. Extract text with preserved semantics
        text = soup.get_text(separator="\n", strip=True)
        # 3. Collapse whitespace
        text = re.sub(r'\n+', '\n', text)
        return text[:15000] # Safety cap
    except Exception as e:
        print(f"[DEBUG] HTML Cleaner Error: {e}")
        return html_content[:5000] # Fallback to raw truncation

def sync_summary_scores(summary: str, actual_score: int) -> str:
    """Industrial Scrubber: Ensures agent-hallucinated scores in text match header score."""
    # Replace patterns like "scoring 82/100", "score of 82", or just "82/100"
    scrubbed = re.sub(r"\d+/100", f"{actual_score}/100", summary)
    scrubbed = re.sub(r"scoring \d+", f"scoring {actual_score}", scrubbed)
    return scrubbed

def calculate_deterministic_score(results, metrics, crawl_obstructed=False):
    """The Single Source of Truth for GEO scoring."""
    if not results: return 0, 0
    # 1. Component Avg
    specialist_avg = round(sum(r.get("score", 0) * r.get("weight", 0) for r in results))
    # 2. Severity Penalties
    finding_deduction = 0
    for r in results:
        raw_w = r.get("weaknesses", [])
        if isinstance(raw_w, str): raw_w = [raw_w]
        for w in raw_w:
            if not isinstance(w, dict): continue
            sev = w.get("severity", "low").upper()
            if sev == "CRITICAL": finding_deduction += 15
            elif sev == "HIGH": finding_deduction += 8
    # 3. Infrastructural Penalties
    infr_penalty = 0
    if metrics.get("broken_links", 0) > 20: infr_penalty += 10
    if crawl_obstructed: infr_penalty += 20
    final_score = max(0, min(100, specialist_avg - finding_deduction - infr_penalty))
    predicted_score = min(99, final_score + 15)
    return int(final_score), int(predicted_score)

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
    if not value: return "—"
    return f"€{int(value):,}".replace(",", ".")
