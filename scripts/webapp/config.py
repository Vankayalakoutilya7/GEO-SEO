from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).parent.parent.parent
AGENT_DIR = BASE_DIR / "agents"
SCHEMA_DIR = BASE_DIR / "schema"
SKILLS_DIR = BASE_DIR / "skills"

# Agent Configurations
AGENT_MAPPING = {
    "geo-ai-visibility": {"weight": 0.25, "label": "AI Visibility & Citability"},
    "geo-content": {"weight": 0.20, "label": "Content E-E-A-T"},
    "geo-technical": {"weight": 0.15, "label": "Technical GEO Infrastructure"},
    "geo-schema": {"weight": 0.15, "label": "Schema & Structured Data"},
    "geo-platform-analysis": {"weight": 0.25, "label": "Platform Optimization"},
    "geo-echo": {"label": "Unique Value (Echo Penalty)", "weight": 0.0},
    "geo-executive-roadmap": {"label": "Executive Strategic Roadmap", "weight": 0.0}
}

# Mapping Agents to their Elite Industrial Skill SOPs
AGENT_SKILL_MAP = {
    "geo-ai-visibility": ["geo-citability", "geo-brand-mentions"],
    "geo-content": ["geo-content"],
    "geo-technical": ["geo-technical", "geo-crawlers", "geo-llmstxt"],
    "geo-schema": ["geo-schema"],
    "geo-platform-analysis": ["geo-platform-optimizer", "geo-compare"],
    "geo-executive-roadmap": ["geo-audit", "geo-report", "geo-proposal"]
}
