# GEO-SEO Architecture: Manager's Flowchart

Here is the comprehensive, end-to-end flowchart of the entire GEO-SEO architecture. This demonstrates the robust logic scaling from the moment the user clicks "Analyze" to the generation of the boardroom-ready PDF.

```mermaid
flowchart TD
    %% Styling
    classDef userAction fill:#f9f,stroke:#333,stroke-width:2px;
    classDef database fill:#bbf,stroke:#333,stroke-width:2px,stroke-dasharray: 5 5;
    classDef scraping fill:#ff9,stroke:#333,stroke-width:1px;
    classDef logic fill:#cfc,stroke:#333,stroke-width:1px;
    classDef aiAgent fill:#fcf,stroke:#333,stroke-width:2px;
    classDef completion fill:#ffd700,stroke:#333,stroke-width:2px;

    %% 1. Initiation
    Start([User Initiates Scan from UI Dashboard]):::userAction --> InitDB[Initialize Secure Supabase Audit Trace]:::database
    InitDB --> |Generate UUID & Assign Project ID| Recon

    %% 2. Reconnaissance (Phase 1)
    subgraph Recon [Phase 1: Deep Target Reconnaissance]
        R1[Fetch 'robots.txt' & Extract AI Crawler Permissions]:::scraping
        R2[Fetch 'llms.txt' Standard File]:::scraping
        R3{Parse 'sitemap.xml'?}
        R4_A[Yes: Extract up to 10,000 URLs]:::scraping
        R4_B[No: Fallback to Recursive BFS Crawl]:::scraping

        R1 --> R3
        R2 --> R3
        R3 -->|Found| R4_A
        R3 -->|Missing| R4_B
    end

    Recon --> Ranking

    %% 3. Intelligent Ranking & Data Extraction (Phase 2)
    subgraph Ranking [Phase 2: High-Value Target Prioritization]
        H1[Aggregated URL Pool]:::logic
        H2[Score each URL via Heuristics]:::logic
        note1>Bonus for 'Pricing', 'Blog', 'Solution'\nPenalty for 'Legal', 'Privacy']
        H2 -.-> note1
        H3[Select Top 1,000 Mission-Critical URLs]:::logic
        
        H1 --> H2 --> H3
    end

    H3 --> Extraction

    subgraph Extraction [Phase 3: Concurrent Data Extraction]
        E1[Initiate 15x Worker Thread Pool]:::logic
        E2[Scrape Semantic HTML, Struct Data, H1s, Meta]:::scraping
        E3[Identify Site Metrics]:::logic
        note2>Count FAQs, Schema Density, Broken Links]
        E3 -.-> note2

        E1 --> E2 --> E3
    end

    Extraction --> Compression

    %% 4. Compression Architecture (Rate-Limit Protection)
    subgraph Compression [Phase 4: Token Optimization Strategy]
        C1[Divide the 1,000 Pages into Tiers]:::logic
        C2[Tier 1: Top 100 Pages]:::logic
        C3[Extract H1, Meta, + Up to 600 chars of Body Content]:::logic
        C4[Tier 2: Bottom 900 Pages]:::logic
        C5[Extract URL + H1 only to map structure]:::logic
        C6[Merge into Single Consolidated Payload Context]:::logic

        C1 --> C2 --> C3 --> C6
        C1 --> C4 --> C5 --> C6
    end

    Compression --> Subagents

    %% 5. Agentic Evaluation (Phase 5)
    subgraph Subagents [Phase 5: Staggered LLM Agent Pipeline]
        A0[Pass Context Payload + Target URL via Anthropic API]:::aiAgent
        A1[Agent 1: AI Visibility & Citability]:::aiAgent
        A2[Agent 2: Network & Platform Optimization]:::aiAgent
        A3[Agent 3: Technical GEO Infrastructure]:::aiAgent
        A4[Agent 4: Content E-E-A-T Framework]:::aiAgent
        A5[Agent 5: Schema & Structured Data Analysis]:::aiAgent
        A_Err{Status 429 Rate Limit?}
        A_Retry[Trigger Exponential Backoff & Retry]:::logic
        A_Haiku[Fallback Strategy: Claude Haiku Model]:::logic

        A0 --> A1 & A2 & A3 & A4 & A5
        A1 & A2 & A3 & A4 & A5 --> A_Err
        A_Err -->|Yes| A_Retry
        A_Retry -->|Retry Limit Reached| A_Haiku
        A_Err -->|No| Extraction_JSON
    end

    A_Haiku --> Extraction_JSON
    
    %% 6. Synthesis & Report Generation (Phase 6)
    subgraph Synthesis [Phase 6: Synthesis & Finalization]
        Extraction_JSON[RegEx Extract 10/10 Formatted JSON Response]:::logic
        S1[Log Agent Execution Status to Supabase]:::database
        S2[Calculate Final Composite Score]:::logic
        note3>Weighted execution based on 5 parameters]
        S2 -.-> note3
        S3[Update Supabase Final Audit Record]:::database
        
        Extraction_JSON --> S1 --> S2 --> S3
    end

    Synthesis --> Output

    %% 7. Generation
    subgraph Output [Phase 7: Data Formatting & PDF Delivery]
        O1[Pass structured JSON into Reportlab Pipeline]:::logic
        O2[Generate Boardroom-ready PDF in Memory]:::logic
        O3[Upload PDF payload to Supabase S3 bucket]:::database
        O4[Render HTMX UI with Dashboard Analytics]:::userAction
        
        O1 --> O2 --> O3 --> O4
    end

    O4 --> Finish([Complete: PDF Delivered to User]):::completion
```

### 📋 Breakdown of Key Architectural Highlights
If you need to speak to the specifics of the diagram above, here are 3 key technical highlights:

1. **Strategic URL Scaling (Phase 2 & 4):** The application doesn't blindly feed 10,000 URLs to Claude (which would immediately crash due to `429 Rate Limits` and token explosions). Instead, it uses a **Heuristic Ranker** to find the 1,000 most profitable pages (e.g., pricing, solutions, case-studies), then **compresses** the payload to deep-read the top 100 pages while mapping the sheer structure of the remaining 900.
2. **Concurrent Workers vs. Staggered LLMs:** It utilizes heavy thread pooling (15 concurrent workers) to fetch HTML blisteringly fast. However, when connecting to Claude (Phase 5), it pivots to *staggered, sequential execution* across its 5 agents to guarantee it skirts the strict Tokens-Per-Minute restrictions.
3. **Enterprise Resilience (Phase 5):** The system features a built-in "Exponential Backoff" strategy gracefully woven inside. If the API rate limits the engine, the internal loop pauses, re-attempts, and finally dynamically fails over to a cheaper model (Claude 3.5 Haiku) automatically just to guarantee the audit successfully finishes for the user.
