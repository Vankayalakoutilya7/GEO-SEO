# GEO Audit Agent: Data Flow Architecture Documentation

> [!NOTE]
> This documentation outlines the exact data flow mechanism utilized by the Generative Engine Optimization (GEO) audit engine. It provides a technical breakdown of the multi-agent pipeline and highlights alternative architectural approaches for future scalability.

## 1. Executive Overview

The GEO Audit Agent provides a high-performance, autonomous system for analyzing a website's readiness for AI-driven search engines (like ChatGPT, Perplexity, and Google AI Overviews). The system operates as a **master-worker architecture**, orchestrating five specialized subagents in parallel to score the target domain across various technical and qualitative vectors.

## 2. Data Flow Architecture Diagram

The following Mermaid diagram illustrates the sequential and parallel data execution paths.

```mermaid
flowchart TD
    Start([User Initiates: /geo audit URL]) --> P1[Phase 1: Discovery & Reconnaissance]
    
    subgraph Phase 1: Data Acquisition
        P1 --> F1[Fetch Homepage]
        F1 --> F2[Feature Extraction & Business Classification]
        F2 --> S1{Sitemap.xml Available?}
        S1 -- Yes --> C1[Extract up to 50 Prioritized URLs]
        S1 -- No --> C2[Crawl Internal Links ≤ 2 Levels Deep]
        C1 --> D1[Collect Page-Level Metadata]
        C2 --> D1
    end
    
    D1 --> P2[Phase 2: Parallel Subagent Delegation]
    
    subgraph Phase 2: Distributed Analysis
        P2 --> S_A1[geo-ai-visibility]
        P2 --> S_A2[geo-platform-analysis]
        P2 --> S_A3[geo-technical]
        P2 --> S_A4[geo-content]
        P2 --> S_A5[geo-schema]
    end
    
    S_A1 --> P3[Phase 3: Score Synthesis]
    S_A2 --> P3
    S_A3 --> P3
    S_A4 --> P3
    S_A5 --> P3
    
    subgraph Phase 3: Synthesis, Reporting & Supabase Integration
        P3 --> R1[Calculate Weighted GEO Composite Score]
        R1 --> R2[(Supabase: Store 'projects', 'audits', 'agent_logs')]
        R2 --> R3[Generate PDF Report & Store in S3]
        R3 --> R4[Generate Final Markdown Output]
    end
    
    R4 --> End([Report Generated: GEO-AUDIT-REPORT.md & PDF])
```

---

## 3. Detailed Implementation & Technical Alternatives

### Phase 1: Discovery and Reconnaissance

**Current Implementation:**
The system initiates by fetching the target homepage. It extracts semantic HTML, metatags, navigation schema, and schema.org data to heuristically classify the business type (e.g., SaaS, E-commerce, Local Business). Next, it prioritizes up to 50 URLs by attempting to parse `/sitemap.xml`. If no sitemap is present, it falls back to a generalized internal link crawl up to 2 levels deep. Critical metadata (H1s, word count, schemas, HTTP status) is collected synchronously, strictly respecting `robots.txt` and utilizing a 30-second timeout constraint.

**Possible Changes & Alternative Methods:**
- **Dynamic Content Rendering:** 
  - *Alternative:* Integrate a headless browser (Puppeteer, Playwright) or high-performance JS rendering engine instead of simple HTTP requests. This prevents missing content heavily reliant on Client-Side Rendering (CSR).
- **Intelligent Distributed Crawling:**
  - *Alternative:* Offload crawling to an external service like BrightData, Apify, or ZenRows to easily bypass CAPTCHAs and geographical blockers, enabling audits of heavily-protected enterprise sites.
- **Semantic URL Clustering:**
  - *Alternative:* Instead of simple heuristics, pass discovered URLs through a lightweight embedding model to cluster and extract a "represented sample" of page varieties, skipping duplicative template pages to save tokens.

---

### Phase 2: Parallel Subagent Delegation

**Current Implementation:**
The extracted data payload is dispatched to 5 parallel subagents. Each agent performs isolated evaluations:
1. **AI Visibility:** Citability scoring, AI crawler readiness, brand mentions.
2. **Platform Optimization:** Tailored checks for Perplexity, ChatGPT, etc.
3. **Technical GEO:** Core Web Vitals, SSR, security protocols.
4. **Content E-E-A-T:** Authoritativeness, depth, and citation validation.
5. **Schema:** Extraction and validation of JSON-LD/schema.org implementations.

**Possible Changes & Alternative Methods:**
- **Event-Driven Task Queues:**
  - *Alternative:* Shift from local parallel threads to an asynchronous distributed task queue (e.g., Celery, RabbitMQ, Kafka) running on independent stateless workers. This allows the system to scale predictably to tens of thousands of pages.
- **Stream-Based Findings:**
  - *Alternative:* Implement WebSocket or Server-Sent Events (SSE) connections. Instead of waiting for all 5 subagents to finish their complete batch, agents stream findings in real-time to a live-dashboard, dramatically improving user experience.
- **Agent Collaboration Protocol:**
  - *Alternative:* Introduce inter-agent communication (e.g., using LangGraph or AutoGen frameworks), enabling the Technical Subagent to pass specific rendering bottlenecks directly to the Content Subagent mid-run.

---

### Phase 3: Score Aggregation and Report Generation

**Current Implementation:**
Upon completion of Phase 2, the orchestrator retrieves the 0-100 scores from all subagents. It calculates a weighted average: `(Citability * 0.25) + (Brand * 0.20) + ...`. Following this synthesis, the system integrates directly with **Supabase**, inserting structured execution data into the `projects`, `audits`, and `agent_logs` normalized schema. Finally, it generates a comprehensive Markdown report containing a 30-day action plan and triggers the synchronous generation of a PDF report, which is securely uploaded to Supabase's S3-compatible storage.

**Possible Changes & Alternative Methods:**
- **Persistent Database Backing:**
  - *Alternative:* Rather than persisting data exclusively to a static `.md` file, pipe results directly into a structured SQL database (e.g., PostgreSQL) or Document Store (e.g., MongoDB). This enables tracking historical trendlines and computing time-series delta comparisons for retainers.
- **Dynamic Weighting per Vertical:**
  - *Alternative:* Train a predictive model to dynamically re-adjust category weights based on the target audience and niche, replacing the hard-coded 25/20/20 formula.
- **API-First Headless Output:**
  - *Alternative:* Output the result as a comprehensive JSON API response instead of/in addition to Markdown. This allows enterprise engineering teams to integrate GEO scores seamlessly into their external CI/CD pipelines (e.g., failing a build if the GEO score drops below 70).
