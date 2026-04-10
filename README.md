
# GEO-SEO AI Analysis Pipeline (GEO Audit Agent)

## Introduction: The Emergence of GEO from SEO
**Generative Engine Optimization (GEO)** represents the evolutionary next step from traditional Search Engine Optimization (SEO). While SEO historically focused on optimizing websites for standard search engine crawlers and keyword rankings, GEO focuses on preparing and optimizing a website's compatibility for modern AI-driven search engines. The GEO Audit Agent specifically evaluates a domain's readiness for platforms like ChatGPT, Perplexity, and Google AI Overviews. 

## Executive Overview
The GEO Audit Agent is a high-performance, autonomous system that utilizes a **master-worker architecture**. It orchestrates five specialized subagents in parallel to calculate a comprehensive readiness score across multiple technical and qualitative vectors.

---

## Pipeline Architecture & Data Flow

### Phase 1: Discovery & Reconnaissance (Extraction)
*   The system begins by fetching the target homepage and extracting semantic HTML, metatags, navigation schema, and schema.org data to heuristically classify the business type (e.g., E-commerce, SaaS, Local Business).
*   It retrieves technical AI and crawler directives from the `robots.txt` and `llms.txt` files. 
*   The agent then attempts to parse the `sitemap.xml` to prioritize up to 50 URLs, or falls back to an internal link crawl up to 2-3 levels deep.
*   This creates a massive **Discovery Queue of up to 10,000 URLs**. 
*   Critical metadata (such as HTTP status, word count, and schemas) is collected synchronously, strictly respecting timeouts (30 seconds) and crawler rules.

### Phase 2: Intelligent Prioritization
*   Instead of blindly crawling the site, the agent applies an **advanced heuristic engine** to score and rank URLs based on semantic markers.
*   High-value pages containing terms like "pricing," "product," and "faq" receive heavy boosts, while low-value pages like privacy policies are downranked.
*   This distilled filtering yields an elite **Target List of the top 1,000 pages** that are most impactful for AI platforms.

### Phase 3: Mass Extraction & Normalization
*   A rapid **15-worker concurrency pool** simultaneously fetches the 1,000 targeted URLs.
*   The system normalizes this massive dataset into a tight bundle by extracting only the H1 headers, Meta descriptions, and the first 400 to 600 characters of page content.
*   Enterprise analytics are then run to quantify total Answer Blocks, schema markup deployments, and AI-citable FAQs.

### Phase 4: Token Compression & Parallel Subagent Delegation
*   To manage API limits and contextual windows, the system employs a **Token Compression strategy**. The top 100 pillar pages are passed with their full textual context, while the remaining 900 are passed as a lightweight structural map (URLs and primary H1 headers).
*   This payload is dispatched in parallel to **5 specialized subagents**:
    1.  **AI Visibility:** Evaluates citability scoring, AI crawler readiness, and brand mentions.
    2.  **Platform Optimization:** Tailors specific checks for AI engines like Perplexity and ChatGPT.
    3.  **Technical GEO:** Audits Core Web Vitals, Server-Side Rendering (SSR) capabilities, and security protocols.
    4.  **Content E-E-A-T:** Analyzes authoritativeness, depth, and citation validation.
    5.  **Schema:** Extracts and validates JSON-LD/schema.org implementations.
*   These agents perform their analysis asynchronously, backed by a 4-cycle failover mechanism across Haiku series models.
<!-- *   These agents perform their analysis asynchronously, backed by a 4-cycle failover mechanism across Haiku series and sonnet series models. -->
### Phase 5: Synthesis, Reporting & Supabase Integration
*   The deep analyses are regex-parsed into strict JSON objects.
*   The orchestrator retrieves the 0-100 scores from all subagents and calculates a weighted composite score (e.g., Citability 25%, Brand 20%, EEAT 20%, Technical 15%, Schema 10%, Platform 10%).
*   The system categorizes the severity of findings (Critical, High, Medium, Low) based on the business type.
*   Data is integrated directly into a normalized Supabase schema, storing `projects`, `audits`, and `agent_logs`.
*   Finally, the pipeline compiles a Markdown report (`GEO-AUDIT-REPORT.md`) with a 30-day action plan and generates a heavily-formatted PDF artifact that is securely stored in S3.

---

## Future Scalability & Architectural Alternatives

To accommodate enterprise-level complexity, the architecture supports several advanced alternative methods:

**Discovery & Crawling Upgrades:**
*   **Dynamic Content Rendering:** Integrating headless browsers (Puppeteer, Playwright) or high-performance JS rendering engines to capture Client-Side Rendering (CSR) content.
*   **Intelligent Distributed Crawling:** Offloading tasks to external services like Apify, BrightData, or ZenRows to bypass geographical blockers and CAPTCHAs.
*   **Semantic URL Clustering:** Using lightweight embedding models to cluster URLs and extract a "represented sample" of page varieties, skipping duplicative templates to save tokens.

**Agent Execution Upgrades:**
*   **Event-Driven Task Queues:** Moving from local threads to asynchronous distributed queues (e.g., Kafka, Celery, RabbitMQ) running on independent stateless workers for massive scalability.
*   **Stream-Based Findings:** Utilizing Server-Sent Events (SSE) or WebSockets to stream findings to a live dashboard in real-time.
*   **Agent Collaboration Protocol:** Using frameworks like LangGraph or AutoGen to allow subagents to communicate mid-run (e.g., the Technical Agent passing rendering bottlenecks to the Content Agent).

**Aggregation & Output Upgrades:**
*   **Persistent Database Backing:** Piping results directly into SQL (PostgreSQL) or Document Stores (MongoDB) to track historical trendlines.
*   **Dynamic Weighting per Vertical:** Training predictive models to dynamically adjust category weights based on the target audience, replacing hard-coded formulas.
*   **API-First Headless Output:** Outputting results as a JSON API response to allow engineering teams to pipe GEO scores seamlessly into their CI/CD pipelines.
