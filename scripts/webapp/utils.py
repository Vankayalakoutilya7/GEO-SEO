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
    """The Single Source of Truth for GEO scoring — Pure Weighted Math Implementation."""
    if not results: return 0, 0
    
    # 1. Base Weighted Score (Components)
    # We use the weights from config or results directly.
    # No hidden global penalties are applied here to ensure 100% manual sync.
    base_score = 0
    total_weight = 0
    for r in results:
        w = r.get("weight", 0)
        # If a component failed, its score is 0, which correctly pulls down the average.
        base_score += r.get("score", 0) * w
        total_weight += w
    
    final_score = int(base_score / total_weight) if total_weight > 0 else 0
    final_score = max(0, min(100, final_score))
    
    predicted_score = final_score
    
    print(f"[DEBUG] [MATH] Pure Weighted Score: {final_score}")
    return final_score, int(predicted_score)

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

def calculate_authority_proxy(brand_name, brand_report):
    """Calculates a 0-100 authority score based on cross-platform digital footprint."""
    if not brand_report or "platforms" not in brand_report:
        return 0
        
    score = 0
    plats = brand_report["platforms"]
    
    # 1. YouTube (Strongest Correlation: 0.737)
    yt = plats.get("youtube", {})
    if yt.get("has_channel"): score += 30
    if yt.get("mentioned_in_videos"): score += 10
    
    # 2. Reddit (High Contextual Authority)
    rd = plats.get("reddit", {})
    if rd.get("has_subreddit"): score += 20
    if rd.get("mentioned_in_discussions"): score += 10
    
    # 3. Wikipedia (Trust Signal)
    wk = plats.get("wikipedia", {})
    if wk.get("has_wikipedia_page"): score += 20
    elif wk.get("cited_in_articles"): score += 10
    
    # 4. LinkedIn (B2B Signal)
    li = plats.get("linkedin", {})
    if li.get("has_company_page"): score += 10
    
    return min(100, score)

def discover_competitors(brand_name, domain):
    """Simple competitor heuristics for benchmarking."""
    # Common industry-specific lookups
    market_map = {
        "Typeform": ["SurveyMonkey", "Jotform", "Google Forms", "Paperform"],
        "SurveyMonkey": ["Typeform", "Jotform", "Alchemer"],
        "Ahrefs": ["Semrush", "Moz", "Ubersuggest"],
        "Semrush": ["Ahrefs", "Moz", "Screaming Frog"],
        "Canva": ["Adobe Express", "VistaCreate", "Figma"],
    }
    
    # Direct match or fuzzy match
    for key in market_map:
        if key.lower() in brand_name.lower():
            return market_map[key]
            
    # Generic fallback
    return ["Competitor A", "Competitor B", "Competitor C"]
def calculate_echo_penalty(internal_pages):
    """Detects content redundancy (Echo) across internal pages."""
    if not internal_pages or len(internal_pages) < 2:
        return 0
        
    def get_shingles(text):
        if not text: return set()
        words = re.findall(r'\w+', text.lower())
        return set(words)

    overlaps = []
    # Compare first few pages for template redundancy
    base_pages = internal_pages[:5]
    for i in range(len(base_pages)):
        for j in range(i + 1, len(base_pages)):
            s1 = get_shingles(base_pages[i].get("content", ""))
            s2 = get_shingles(base_pages[j].get("content", ""))
            if not s1 or not s2: continue
            
            intersection = len(s1.intersection(s2))
            union = len(s1.union(s2))
            if union > 0:
                overlaps.append(intersection / union)
                
    if not overlaps:
        return 0
        
    avg_overlap = sum(overlaps) / len(overlaps)
    return int(avg_overlap * 100)

def calculate_authority_proxy(brand_name, brand_report):
    """Calculates a 0-100 authority score based on cross-platform digital footprint."""
    if not brand_report or "platforms" not in brand_report:
        return 0
    score = 0
    plats = brand_report["platforms"]
    yt = plats.get("youtube", {})
    if yt.get("has_channel"): score += 30
    if yt.get("mentioned_in_videos"): score += 10
    rd = plats.get("reddit", {})
    if rd.get("has_subreddit"): score += 20
    if rd.get("mentioned_in_discussions"): score += 10
    wk = plats.get("wikipedia", {})
    if wk.get("has_wikipedia_page"): score += 20
    elif wk.get("cited_in_articles"): score += 10
    li = plats.get("linkedin", {})
    if li.get("has_company_page"): score += 10
    return min(100, score)