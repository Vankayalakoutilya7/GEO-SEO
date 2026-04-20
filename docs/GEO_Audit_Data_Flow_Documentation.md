# GEO Audit Agent: Data Flow Architecture Documentation

## I. Executive Overview
The GEO-SEO Audit Pipeline is an autonomous, high-performance agentic system designed to transition websites from traditional search rankings to "AI Citability" (Generative Engine Optimization). It utilizes a multi-agent orchestration layer to perform deep technical audits, semantic content evaluation, and entity resolution in under 3 minutes per domain.

## II. System Architecture: The "Orchestrator & Hive" Model
The system operates via a Central Conductor (`app.py`) that coordinates 7 specialized Agent Personas and 14 Industrial SOPs (Standard Operating Procedures). These SOPs are professional blueprints that define the rigorous scoring and logic for every phase of the project.

---

## III. Elite Engineering Highlights

### 1. The "Stealth Handshake" & Adaptive Hydration [UPGRADED]
To bypass enterprise-grade Web Application Firewalls (WAFs) like Cloudflare, Datadome, or Typeform's internal blockers, we use a hybrid identity-cloning mechanism:
- **Harden Stealth Core**: Integrated `playwright-stealth` to satisfy deep headless-browser checks.
- **Proof-of-Work Challenge**: The system spawns a real, invisible Playwright browser to solve "Is this a human?" JS challenges.
- **Identity Cloning**: Once solved, it captures session cookies and User-Agents, "handshaking" them over to high-speed request sessions.
- **Adaptive Hydration (v5)**: Instead of static timeouts, the system uses dynamic stability monitoring (up to 15s) to ensure complex SPAs are fully rendered before extraction.
- **The Pivot**: If lightweight crawling hits a 403 Forbidden, the system dynamically "Pivots" back to full browser rendering with human-like interactions (scrolling/jitter) to ensure 100% crawl success.

### 2. Semantic Context Slicing & HTML Stripping
To maintain a strict <$1 API budget, we implemented a Context Routing Architecture:
- **Boilerplate Decomposition**: Surgically removes `<nav>`, `<footer>`, and `<script>` tags, reducing token "noise" by up to 60%.
- **Targeted Provisioning**: Specialists only receive relevant data slices (e.g., the Technical Agent receives DOM metrics, while the Content Agent receives raw citable text).

### 3. Algorithmic Echo Penalty
Uses Jaccard Similarity to identify "Thin Content" and "Template Bloat":
- **The Logic**: Calculates the overlap between sets of common N-grams across all 50 audited pages.
- **The Penalty**: If similarity exceeds 40%, the system triggers an automatic "Echo Penalty," flagging the site as "Nav-Heavy" and "Content-Poor."

---

## IV. 3-Tier Database & Persistence Layer [NEW]
The system uses Supabase (PostgreSQL + S3) with a **Multi-Tier Reliability Layer** to resolve schema drift and PostgREST maintenance (`PGRST204`) errors:
- **Tier 1 (Full Save)**: Stores the complete hierarchical audit results (Findings, Roadmaps, Suggested Code).
- **Tier 2 (Legacy Save)**: Automatic fallback to minimal Score/Summary if schema cache is stale.
- **Tier 3 (Atomic Save)**: Ultra-minimal emergency save (UUID + Status) to ensure Foreign Key consistency even during a "Database Lock."
- **Maintenance**: Users can resolve persistent cache errors via `schema/fix_supabase_cache.sql` (`NOTIFY pgrst, 'reload schema'`).

---

## V. Detailed Workflow Step-by-Step

### 1. Project Initialization (Audit IDs)
Generates unique UUIDs and checks Supabase for existing Projects. If a domain is found within a 5-hour window, it performs a **Full Reconstruction** (Findings, Roadmaps, Executive Summary) from cache instead of a fresh crawl.

### 2. AI Triage Specialist (Bulk Filtering)
Uses **Claude-3-Haiku** as a gatekeeper to review up to 5,000 URLs in milliseconds, selecting the Top 50 high-intent targets (Pricing, Features, Reviews, Pillar Content).

### 3. Agent Execution (Native Tool Calling)
Agents are strictly prohibited from returning raw text. They must use the `submit_audit_result` tool, enforcing:
- **No-Bluff Protocol**: Findings must map to a verifiable `evidence_url`.
- **Restricted State**: If data is missing (e.g., site blockade), agents trigger a mandatory failure state (Score 0) to prevent hallucinated advice.

---

## VI. Project File Significance

| Path | Significance |
| :--- | :--- |
| `/agents/*.md` | **Intelligence Layer**: Specialist prompts with "Elite" SOP mandates. |
| `/skills/*.md` | **The Brain**: Professional benchmarks and audit workflows. |
| `/scripts/fetch_page.py` | **The Scout**: Hardened hybrid browser/stealth crawler. |
| `/scripts/webapp/app.py` | **The Conductor**: Orchestrates multi-threaded agent execution and tiered saving. |
| `/schema/*.json` | **Gold Standards**: Templates for Schema.org entity resolution. |
| `/templates/` | **Dashboard**: The "Glow" UI for visualizing AI insights and code. |

---

## VII. Cost Optimization Summary (USD per Audit)

| Audit Phase | Cost (USD) | Optimization Method |
| :--- | :--- | :--- |
| **AI Triage (Haiku)** | ~$0.015 | Sequential 5,000 URL batching. |
| **Specialist Hive (Sonnet)** | ~$0.09 | **60% Savings** via Semantic HTML Stripping. |
| **Master Synthesis (Sonnet)** | ~$0.015 | Specialized context payload routing. |
| **Re-Scan / Cache Hit** | **$0.00** | 100% Saving via Supabase Cache Protocol. |
| **TOTAL** | **~$0.12** | (Original Cost: ~$0.25) |
