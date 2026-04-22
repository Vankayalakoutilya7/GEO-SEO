#!/usr/bin/env python3
"""
Fetch and parse web pages for GEO analysis.
Extracts HTML, text content, meta tags, headers, and structured data.
"""



# Mode,    Action,Best Use Case
# page,    Runs fetch_page.,Deep technical/SEO audit of a single URL.
# robots,    Runs fetch_robots_txt.,Checking if a site blocks AI or specific bots.
# llms,    Runs fetch_llms_txt.,Checking if a site provides clean data for LLMs.
# bfs,    Runs recursive_bfs_crawl.,"Discovery mode—finding up to 3,000 pages manually."
# sitemap,   Runs crawl_sitemap.,Discovery mode—finding pages via the official map.
# blocks,  Runs extract_content_blocks.,"Content analysis—breaking a page into ""citable"" chunks."
# full,    Runs almost everything.,A complete audit of a brand's entry point.

import sys
import json
import os
import re
import time
from urllib.parse import urljoin, urlparse

try:
    # Used to make HTTP connections to the target websites. It downloads the raw HTML content of pages, fetches robots.txt and sitemaps, and maintains cross-request sessions (to hold cookies and prevent blocks) when crawling.
    import requests
    # Used to parse the raw HTML that requests downloads. It surgically extracts the exact elements the SEO agents need—pulling <h1> tags, scraping body text while ignoring noise (like <script> or footer tags), extracting internal links for the crawler, and isolating hidden JSON-LD structured data.
    from bs4 import BeautifulSoup
except ImportError:
    print("WARNING: Required packages (requests, bs4) not installed. Crawling functions will be disabled.")

try:
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth
    STEALTH_ENGINE = Stealth()
    PLAYWRIGHT_AVAILABLE = True
except Exception as e:
    PLAYWRIGHT_AVAILABLE = False
    STEALTH_ENGINE = None
    print(f"[ENVIRONMENT DEBUG] Playwright Engine Disabled: {e}")

# Common AI crawler user agents for testing. like ID card for bots
AI_CRAWLERS = {
    "GPTBot": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2; +https://openai.com/gptbot)",
    "ClaudeBot": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; ClaudeBot/1.0; +https://www.anthropic.com/claude-bot)",
    "PerplexityBot": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; PerplexityBot/1.0; +https://perplexity.ai/perplexitybot)",
    "GoogleBot": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "BingBot": "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
}

# When you use a script to scrape a website, the server can easily tell it’s a script because it lacks the "baggage" a real browser carries. These DEFAULT_HEADERS mimic the exact metadata sent by a real person using Google Chrome on a Mac.
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

# rotational pool Think of it as a spy who changes their hat, glasses, and jacket every time they walk past the same security guard.
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:124.0) Gecko/20100101 Firefox/124.0",
]

def is_internal(url_to_check, seed_url, allowed_domains=None):
    """
    Determines if a URL is 'internal' to the brand being audited.
    Supports fuzzy matching to handle redirects across TLDs (e.g., canva.in -> canva.com).
    """
    from urllib.parse import urlparse
    
    if not url_to_check or not seed_url: return False
    
    # 1. Exact Match Check
    target_host = urlparse(url_to_check).netloc.replace("www.", "").lower()
    if not target_host: return False # Relative link check happens elsewhere
    
    seed_host = urlparse(seed_url).netloc.replace("www.", "").lower()
    
    if target_host == seed_host: return True
    if allowed_domains and target_host in allowed_domains: return True
    
    # 2. Fuzzy Root Match (e.g., canva.in and canva.com)
    # Extracts the Second-Level Domain (SLD) if possible
    def get_sld(host):
        parts = host.split('.')
        if len(parts) >= 2:
            return parts[-2] # Simple but effective for brands
        return host

    if get_sld(target_host) == get_sld(seed_host) and len(get_sld(target_host)) > 3:
        return True
        
    return False

#what content to take and store
def fetch_page(url: str, timeout: int = 30, use_playwright: bool = False, session: any = None) -> dict:
    """Fetch a page and return structured analysis data."""
    result = {
        "url": url,
        "status_code": None,
        "redirect_chain": [],
        "headers": {},
        "meta_tags": {},
        "title": None,
        "description": None,
        "canonical": None,
        "h1_tags": [],
        "heading_structure": [],
        "word_count": 0,
        "text_content": "",
        "internal_links": [],
        "external_links": [],
        "images": [],
        "structured_data": [],
        "has_ssr_content": True,
        "security_headers": {},
        "page_weight_kb": 0,
        "is_compressed": False,
        "ttfb_ms": 0,
        "errors": [],
    }

    try:
        target_session = session or requests.Session()
        response = target_session.get(
            url,
            headers=DEFAULT_HEADERS,
            timeout=timeout,
            allow_redirects=True,
        )

        # Track redirects
        if response.history:
            result["redirect_chain"] = [
                {"url": r.url, "status": r.status_code} for r in response.history
            ]

        result["status_code"] = response.status_code
        result["headers"] = dict(response.headers)
        result["page_weight_kb"] = round(len(response.content) / 1024, 2)
        result["is_compressed"] = "gzip" in response.headers.get("Content-Encoding", "") or "br" in response.headers.get("Content-Encoding", "")
        result["ttfb_ms"] = int(response.elapsed.total_seconds() * 1000)

        # Security headers check
        security_headers = [
            "Strict-Transport-Security",
            "Content-Security-Policy",
            "X-Frame-Options",
            "X-Content-Type-Options",
            "Referrer-Policy",
            "Permissions-Policy",
        ]
        for header in security_headers:
            result["security_headers"][header] = response.headers.get(header, None)

        # Parse HTML
        soup = BeautifulSoup(response.text, "lxml")

        # Title
        title_tag = soup.find("title")
        result["title"] = title_tag.get_text(strip=True) if title_tag else None

        # Meta tags
        for meta in soup.find_all("meta"):
            name = meta.get("name", meta.get("property", ""))
            content = meta.get("content", "")
            if name and content:
                result["meta_tags"][name.lower()] = content
                if name.lower() == "description":
                    result["description"] = content

        # Canonical
        canonical = soup.find("link", rel="canonical")
        result["canonical"] = canonical.get("href") if canonical else None

        # Headings
        for level in range(1, 7):
            for heading in soup.find_all(f"h{level}"):
                text = heading.get_text(strip=True)
                result["heading_structure"].append({"level": level, "text": text})
                if level == 1:
                    result["h1_tags"].append(text)

        # Structured data (JSON-LD) — extract before decompose() mutates the tree
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                # Use get_text() to handle internal comments or malformed whitespace
                script_content = script.get_text(strip=True)
                if not script_content and script.string:
                    script_content = script.string.strip()
                
                if script_content:
                    data = json.loads(script_content)
                    result["structured_data"].append(data)
            except (json.JSONDecodeError, TypeError):
                result["errors"].append("Invalid JSON-LD detected")

        # Microdata Fallback (For Entity Hints)
        microdata_items = soup.find_all(attrs={"itemtype": True})
        if microdata_items:
            result["structured_data"].append({
                "@context": "https://schema.org",
                "@type": "MicrodataDiscovery",
                "types_found": list(set([item.get("itemtype") for item in microdata_items])),
                "count": len(microdata_items)
            })

        # SSR check — must run BEFORE decompose() mutates the tree
        js_app_roots = soup.find_all(
            id=re.compile(r"(app|root|__next|__nuxt)", re.I)
        )

        # Check SSR by measuring content inside framework root divs
        # before decompose() strips elements from the tree
        ssr_check_results = []
        for root_el in js_app_roots:
            inner_text = root_el.get_text(strip=True)
            ssr_check_results.append({
                "id": root_el.get("id", "unknown"),
                "text_length": len(inner_text),
            })

        # Links (Extract BEFORE decomposing nav/footer/header)
        final_host = urlparse(result["url"]).netloc.replace("www.", "")
        seed_host = urlparse(url).netloc.replace("www.", "")
        
        for link in soup.find_all("a", href=True):
            href = urljoin(url, link["href"])
            href = href.split("#")[0].rstrip("/")
            link_text = link.get_text(strip=True)
            parsed_href = urlparse(href)
            href_host = parsed_href.netloc.replace("www.", "")
            
            # Fuzzy Match: Use is_internal to handle redirects/TLD jumps
            if is_internal(href, url, allowed_domains={final_host}):
                result["internal_links"].append({"url": href, "text": link_text})
            elif parsed_href.scheme in ("http", "https"):
                result["external_links"].append({"url": href, "text": link_text})

        # Text content — decompose non-content elements (destructive)
        for element in soup.find_all(["script", "style", "nav", "footer", "header"]):
            element.decompose()
        text = soup.get_text(separator=" ", strip=True)
        result["text_content"] = text
        word_count = len(text.split())
        # Standardize for Industrial GEO (No fake precision)
        # Force rounding to nearest 100 or 'Sparse' if very low
        if word_count < 100:
            result["word_count"] = "Sparse (<100)"
        else:
            result["word_count"] = f"~{ (word_count // 100) * 100 }"

        # --- INDUSTRIAL SCHEMA DISCOVERY ---
        # Explicit flags for high-priority SaaS schemas
        schema_types = [s.get("@type") for s in result.get("structured_data", []) if isinstance(s, dict)]
        result["high_priority_schema"] = {
            "organization_found": "Organization" in schema_types or "Corp" in str(schema_types),
            "product_found": "Product" in schema_types or "SoftwareApplication" in schema_types,
            "faq_found": "FAQPage" in schema_types
        }

        # --- INDUSTRIAL EVIDENCE BANK ---
        # Collect raw snippets for 'No-Bluff' reporting
        evidence_bank = []
        definition_patterns = [
            r"is a [a-zA-Z\s]+ that", 
            r"refers to the [a-zA-Z\s]+", 
            r"defined as [a-zA-Z\s]+",
            r"is the process of",
            r"is a platform for"
        ]
        
        # 1. Definition Evidence
        for pattern in definition_patterns:
            matches = list(re.finditer(pattern, text, re.I))
            for m in matches[:3]: # Cap at 3 for token efficiency
                start = max(0, m.start() - 50)
                end = min(len(text), m.end() + 100)
                evidence_bank.append({
                    "type": "DEFINITION",
                    "snippet": f"...{text[start:end]}...",
                    "pattern": pattern
                })
        
        # 2. Schema Anchor Evidence (Raw JSON fragment)
        if result.get("structured_data"):
            evidence_bank.append({
                "type": "SCHEMA",
                "snippet": str(result["structured_data"])[:200] + "..."
            })
            
        result["evidence_bank"] = evidence_bank

        # Images
        for img in soup.find_all("img"):
            img_data = {
                "src": img.get("src", ""),
                "alt": img.get("alt", ""),
                "width": img.get("width"),
                "height": img.get("height"),
                "loading": img.get("loading"),
            }
            result["images"].append(img_data)

        # SSR assessment — use pre-decompose measurements + overall content
        if js_app_roots:
            for check in ssr_check_results:
                # Only flag as client-rendered if both the root div has
                # minimal content AND the overall page has little text.
                # Sites using SSR/prerendering (WordPress, LiteSpeed Cache,
                # Prerender.io) will have substantial text despite having
                # framework-style root divs.
                if check["text_length"] < 50 and result["word_count"] < 200:
                    result["has_ssr_content"] = False
                    result["errors"].append(
                        f"Possible client-side only rendering detected: "
                        f"#{check['id']} has minimal server-rendered content "
                        f"({result['word_count']} words on page)"
                    )

    except requests.exceptions.Timeout:
        result["errors"].append(f"Timeout after {timeout} seconds")
    except requests.exceptions.ConnectionError as e:
        result["errors"].append(f"Connection error: {str(e)}")
    except Exception as e:
        result["errors"].append(f"Unexpected error: {str(e)}")
#If the root div has less than 50 characters (text_length < 50) and the whole page has fewer than 200 words, it flags the page as has_ssr_content = False.
#Why? If a page is that empty, it means the content is likely hidden behind a JavaScript "wall" that a simple requests call can't see.
    # Universal Blockade Detection (Status 403, 429, or empty HTML/Title/Links)
    status_block = result.get("status_code") in [403, 401, 429]
    # If no title, meta, content, OR NO LINKS were found, it's likely a JS rendering wall
    content_block = not result.get("title") or not result.get("meta_tags") or not result.get("has_ssr_content") or len(result.get("internal_links", [])) == 0
    blockade_text = any(x in (result["text_content"] or "").lower() for x in ["access denied", "please verify", "captcha", "bot detection"])
    
    triggers_pivot = use_playwright or status_block or content_block or blockade_text
    
    if triggers_pivot:
        print(f"[DEBUG] Pivot Triggered: status_block={status_block}, content_block={content_block}, blockade_text={blockade_text}, internal_links={len(result.get('internal_links', []))}")
    
    if triggers_pivot and PLAYWRIGHT_AVAILABLE:
        print(f"[DEBUG] Entering Playwright Block...")
        try:
            import time
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                
                # Launch with Elite Stealth Context
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800},
                    device_scale_factor=1,
                    is_mobile=False,
                    has_touch=False,
                    locale="en-US",
                    timezone_id="America/New_York",
                )
                
                page = context.new_page()
                # Apply Industrial Stealth (Bypass detection)
                if STEALTH_ENGINE:
                    STEALTH_ENGINE.apply_stealth_sync(page)
                
                # Visit with human-like jitter
                page.goto(url, wait_until="networkidle", timeout=60000)
                # Wait an extra 2 seconds for JS skeletons to populate
                time.sleep(2)
                
                rendered_text = page.inner_text("body")
                rendered_html = page.content()
                
                # ADAPTIVE HYDRATION LOOP (v5)
                # Monitors content stability rather than static timeouts
                max_h_wait = 15 
                h_start = time.time()
                last_len = 0
                while (time.time() - h_start) < max_h_wait:
                    curr_len = len(page.content())
                    if curr_len > last_len and curr_len > 1000:
                        last_len = curr_len
                        page.wait_for_timeout(2000)
                    elif curr_len > 1000:
                        break # Stability reached
                    else:
                        page.wait_for_timeout(1000)

                # Human Interaction Simulation (Lazy-load triggers)
                page.mouse.wheel(0, 1200)
                page.wait_for_timeout(2000)
                page.mouse.wheel(0, -600) # Micro-jitter to trigger non-scroll listeners
                page.wait_for_timeout(1000)
                
                # Capture and Parse
                rendered_content = page.content()
                rendered_soup = BeautifulSoup(rendered_content, "lxml")
                rendered_text = rendered_soup.get_text(separator=" ", strip=True)

                # Capture session state
                result["cookies"] = context.cookies()
                result["browser_ua"] = context.evaluate("navigator.userAgent")
                
                # Bot detection check
                if any(x in rendered_text.lower() for x in ["are you a human", "captcha", "bot detection", "access denied"]):
                    result["bot_detected"] = True
                
                # Final content capture logic
                if len(rendered_text) > len(result["text_content"]) * 1.2 or (not result["text_content"] and len(rendered_text) > 200) or len(result.get("internal_links", [])) == 0:
                    # SSR VALIDATION PROOF: Calculated ratio of raw to rendered text
                    raw_len = len(result.get("text_content", ""))
                    rend_len = len(rendered_text)
                    result["ssr_efficiency_ratio"] = round(raw_len / rend_len, 2) if rend_len > 0 else 0
                    
                    result["has_ssr_content"] = False
                    result["rendering_wall_detected"] = True if result["ssr_efficiency_ratio"] < 0.3 else False
                    result["text_content"] = rendered_text
                    
                    # Standardize Word Count for Rendered Content
                    r_word_count = len(rendered_text.split())
                    result["word_count"] = f"{ (r_word_count // 50) * 50 }+" if r_word_count > 50 else r_word_count
                    
                    print(f"[DEBUG] [PIVOT SUCCESS] Captured {len(rendered_text)} chars and {len(result['internal_links'])} internal links from behind wall.")
                    
                    result["title"] = rendered_soup.title.string if rendered_soup.title else result["title"]
                    
                    # RE-EXTRACT LINKS FROM RENDERED CONTENT
                    result["internal_links"] = []
                    result["external_links"] = []
                    result["structured_data"] = []
                    
                    final_host = urlparse(page.url).netloc.replace("www.", "")
                    seed_host = urlparse(url).netloc.replace("www.", "")
                    
                    for link in rendered_soup.find_all("a", href=True):
                        href = urljoin(url, link["href"])
                        href = href.split("#")[0].rstrip("/")
                        link_text = link.get_text(strip=True)
                        parsed_href = urlparse(href)
                        href_host = parsed_href.netloc.replace("www.", "")
                        
                        # Fuzzy Match: Use is_internal to handle redirects/TLD jumps
                        if is_internal(href, url, allowed_domains=allowed_domains):
                            result["internal_links"].append({"url": href, "text": link_text})
                        elif parsed_href.scheme in ("http", "https"):
                            result["external_links"].append({"url": href, "text": link_text})
                            
                    # RE-EXTRACT STRUCTURED DATA (Hardened Path)
                    for script in rendered_soup.find_all("script", type="application/ld+json"):
                        try:
                            script_content = script.get_text(strip=True)
                            if not script_content and script.string:
                                script_content = script.string.strip()
                            if script_content:
                                data = json.loads(script_content)
                                result["structured_data"].append(data)
                        except: pass
                    
                    # Hardened Microdata extraction for Playwright
                    p_microdata = rendered_soup.find_all(attrs={"itemtype": True})
                    if p_microdata:
                        result["structured_data"].append({
                            "@context": "https://schema.org",
                            "@type": "MicrodataDiscovery",
                            "types_found": list(set([item.get("itemtype") for item in p_microdata])),
                            "count": len(p_microdata)
                        })
                
                browser.close()
        except Exception as e:
            result["errors"].append(f"Playwright error: {str(e)}")
    return result


def fetch_robots_txt(url: str, timeout: int = 15) -> dict:
    """Fetch and parse robots.txt for AI crawler directives."""
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    ai_crawlers = [
        "GPTBot",
        "OAI-SearchBot",
        "ChatGPT-User",
        "ClaudeBot",
        "anthropic-ai",
        "PerplexityBot",
        "CCBot",
        "Bytespider",
        "cohere-ai",
        "Google-Extended",
        "GoogleOther",
        "Applebot-Extended",
        "FacebookBot",
        "Amazonbot",
    ]

    result = {
        "url": robots_url,
        "exists": False,
        "content": "",
        "ai_crawler_status": {},
        "sitemaps": [],
        "errors": [],
    }

    try:
        response = requests.get(robots_url, headers=DEFAULT_HEADERS, timeout=timeout)

        if response.status_code == 200:
            result["exists"] = True
            result["content"] = response.text

            # Parse for each AI crawler
            lines = response.text.split("\n")
            current_agent = None
            agent_rules = {}

            for line in lines:
                line = line.strip()
                if line.lower().startswith("user-agent:"):
                    current_agent = line.split(":", 1)[1].strip()
                    if current_agent not in agent_rules:
                        agent_rules[current_agent] = []
                elif line.lower().startswith("disallow:") and current_agent:
                    path = line.split(":", 1)[1].strip()
                    agent_rules[current_agent].append(
                        {"directive": "Disallow", "path": path}
                    )
                elif line.lower().startswith("allow:") and current_agent:
                    path = line.split(":", 1)[1].strip()
                    agent_rules[current_agent].append(
                        {"directive": "Allow", "path": path}
                    )
                elif line.lower().startswith("sitemap:"):
                    sitemap_url = line.split(":", 1)[1].strip()
                    # Handle case where "Sitemap:" splits off the "http"
                    if not sitemap_url.startswith("http"):
                        sitemap_url = "http" + sitemap_url
                    result["sitemaps"].append(sitemap_url)

            # Determine status for each AI crawler
            for crawler in ai_crawlers:
                if crawler in agent_rules:
                    rules = agent_rules[crawler]
                    if any(
                        r["directive"] == "Disallow" and r["path"] == "/"
                        for r in rules
                    ):
                        result["ai_crawler_status"][crawler] = "BLOCKED"
                    elif any(
                        r["directive"] == "Disallow" and r["path"] for r in rules
                    ):
                        result["ai_crawler_status"][crawler] = "PARTIALLY_BLOCKED"
                    else:
                        result["ai_crawler_status"][crawler] = "ALLOWED"
                elif "*" in agent_rules:
                    wildcard_rules = agent_rules["*"]
                    if any(
                        r["directive"] == "Disallow" and r["path"] == "/"
                        for r in wildcard_rules
                    ):
                        result["ai_crawler_status"][crawler] = "BLOCKED_BY_WILDCARD"
                    else:
                        result["ai_crawler_status"][crawler] = "ALLOWED_BY_DEFAULT"
                else:
                    result["ai_crawler_status"][crawler] = "NOT_MENTIONED"

        elif response.status_code == 404:
            result["errors"].append("No robots.txt found (404)")
            for crawler in ai_crawlers:
                result["ai_crawler_status"][crawler] = "NO_ROBOTS_TXT"
        else:
            result["errors"].append(
                f"Unexpected status code: {response.status_code}"
            )

    except Exception as e:
        result["errors"].append(f"Error fetching robots.txt: {str(e)}")

    return result


def fetch_llms_txt(url: str, timeout: int = 15) -> dict:
    """Check for llms.txt file."""
    parsed = urlparse(url)
    llms_url = f"{parsed.scheme}://{parsed.netloc}/llms.txt"
    llms_full_url = f"{parsed.scheme}://{parsed.netloc}/llms-full.txt"

    result = {
        "llms_txt": {"url": llms_url, "exists": False, "content": ""},
        "llms_full_txt": {"url": llms_full_url, "exists": False, "content": ""},
        "errors": [],
    }

    for key, check_url in [("llms_txt", llms_url), ("llms_full_txt", llms_full_url)]:
        try:
            response = requests.get(
                check_url, headers=DEFAULT_HEADERS, timeout=timeout
            )
            if response.status_code == 200:
                result[key]["exists"] = True
                result[key]["content"] = response.text
        except Exception as e:
            result["errors"].append(f"Error checking {check_url}: {str(e)}")

    return result

#extracts data by removing unwanted tags
def extract_content_blocks(html: str) -> list:
    """Extract content blocks for citability analysis."""
    soup = BeautifulSoup(html, "lxml")

    # Remove non-content elements
    for element in soup.find_all(
        ["script", "style", "nav", "footer", "header", "aside"]
    ):
        element.decompose()

    blocks = []
    # Extract content sections (between headings)
    current_heading = None
    current_content = []

    for element in soup.find_all(
        ["h1", "h2", "h3", "h4", "h5", "h6", "p", "ul", "ol", "table", "blockquote"]
    ):
        tag = element.name

        if tag.startswith("h"):
            # Save previous block
            if current_content:
                text = " ".join(current_content)
                word_count = len(text.split())
                blocks.append(
                    {
                        "heading": current_heading,
                        "content": text,
                        "word_count": word_count,
                        "tag_types": list(
                            set(
                                [
                                    e.name
                                    for e in element.find_all_previous(
                                        ["p", "ul", "ol", "table"]
                                    )
                                ]
                            )
                        ),
                    }
                )
            current_heading = element.get_text(strip=True)
            current_content = []
        else:
            text = element.get_text(strip=True)
            if text:
                current_content.append(text)

    # Don't forget the last block
    if current_content:
        text = " ".join(current_content)
        blocks.append(
            {
                "heading": current_heading,
                "content": text,
                "word_count": len(text.split()),
            }
        )

    return blocks


def crawl_sitemap(url: str, max_pages: int = 5000, timeout: int = 20, session: any = None) -> list:
    """Crawl sitemap.xml to discover pages (Industrial Scale: 200)."""
    parsed = urlparse(url)
    sitemap_urls = [
        f"{parsed.scheme}://{parsed.netloc}/sitemap.xml",
        f"{parsed.scheme}://{parsed.netloc}/sitemap_index.xml",
        f"{parsed.scheme}://{parsed.netloc}/sitemap/",
    ]

    discovered_pages = set()
    
    # Use provided session or a temporary one
    import requests
    req = session if session else requests

    for sitemap_url in sitemap_urls:
        try:
            response = req.get(
                sitemap_url, headers=DEFAULT_HEADERS, timeout=timeout
            )
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "lxml")

                # Check for sitemap index
                for sitemap in soup.find_all("sitemap"):
                    loc = sitemap.find("loc")
                    if loc:
                        # Fetch child sitemap
                        try:
                            child_resp = req.get(
                                loc.text.strip(),
                                headers=DEFAULT_HEADERS,
                                timeout=timeout,
                            )
                            if child_resp.status_code == 200:
                                child_soup = BeautifulSoup(child_resp.text, "lxml")
                                for url_tag in child_soup.find_all("url"):
                                    loc_tag = url_tag.find("loc")
                                    if loc_tag:
                                        discovered_pages.add(loc_tag.text.strip())
                                    if len(discovered_pages) >= max_pages:
                                        break
                        except Exception:
                            pass
                    if len(discovered_pages) >= max_pages:
                        break

                # Direct URL entries
                for url_tag in soup.find_all("url"):
                    loc = url_tag.find("loc")
                    if loc:
                        discovered_pages.add(loc.text.strip())
                    if len(discovered_pages) >= max_pages:
                        break

                if discovered_pages:
                    break

        except Exception:
            continue

    return list(discovered_pages)[:max_pages]


def fast_extract_links(url: str, allowed_domains: set, timeout: int = 10, use_playwright: bool = False, session: any = None, user_agent: str = None) -> list:
    """Lightweight link extractor for rapid BFS crawling."""
    import time
    import random
    
    # Anti-blocking: Add randomized jitter
    time.sleep(random.uniform(0.5, 1.5))
    
    links = []
    
    # Optional Playwright for the "Seed" page (homepage) or if session is empty
    if use_playwright and PLAYWRIGHT_AVAILABLE:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                # Use a real context to extract cookies
                context = browser.new_context(user_agent=random.choice(USER_AGENTS))
                page = context.new_page()
                page.set_extra_http_headers(DEFAULT_HEADERS)
                page.goto(url, wait_until="domcontentloaded", timeout=timeout*1000)
                # Scroll a bit to trigger lazy links
                page.evaluate("window.scrollTo(0, document.body.scrollHeight/2)")
                content = page.content()
                
                # Extract Session Cookies for future requests
                cookies = context.cookies()
                
                soup = BeautifulSoup(content, "lxml")
                browser.close()
                for link in soup.find_all("a", href=True):
                    href = urljoin(url, link["href"])
                    href = href.split("#")[0].rstrip("/")
                    
                    if is_internal(href, url, allowed_domains=allowed_domains):
                        links.append(href)
                
                return list(set(links)), cookies
        except Exception:
            pass # Fall back to requests

    # Standard requests approach (sharing session if provided)
    import requests
    target_session = session or requests.Session()
    headers = DEFAULT_HEADERS.copy()
    headers["User-Agent"] = user_agent if user_agent else random.choice(USER_AGENTS)
    
    try:
        resp = target_session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "lxml")
            for link in soup.find_all("a", href=True):
                href = urljoin(url, link["href"])
                href = href.split("#")[0].rstrip("/")
                
                if is_internal(href, url, allowed_domains=allowed_domains):
                    links.append(href)
    except Exception:
        pass
    return list(set(links)), None


def recursive_bfs_crawl(url: str, max_pages: int = 1500, timeout: int = 15, session: any = None, stop_event: any = None) -> list:
    """Strategic BFS discovery that avoids bot-walls and preserves speed."""
    import concurrent.futures
    from urllib.parse import urlparse, urljoin
    
    # 1. Setup Base Context (Root Domain extraction)
    start_url = url.split("#")[0].rstrip("/")
    seed_host = urlparse(start_url).netloc.replace("www.", "")
    # allowed_domains will include any domain we pivot to
    allowed_domains = {seed_host}
    
    visited = {start_url}
    discovered = [start_url]
    queue = []
    
    print(f"[DEBUG] [BFS Crawler] Starting scan for {seed_host} (Max: {max_pages})")
    
    # 2. Browser Handshake (The Secret Sauce)
    print(f"[DEBUG] [BFS Crawler] Performing Handshake with Browser for seed page...")
    res = fetch_page(url, use_playwright=True)
    
    # Update search scope if redirected (e.g. canva.in -> canva.com)
    if res and res.get("url"):
        final_host = urlparse(res["url"]).netloc.replace("www.", "")
        if final_host not in allowed_domains:
            print(f"[DEBUG] [BFS Crawler] Domain Pivot Detected: {seed_host} -> {final_host}. Expanding scope.")
            allowed_domains.add(final_host)

    if res and res.get("internal_links"):
        for link in res["internal_links"]:
            l_url = link["url"].split("#")[0].rstrip("/")
            
            # Match against ANY domain in our allowed set or fuzzy root
            if is_internal(l_url, url, allowed_domains=allowed_domains):
                if l_url not in visited:
                    visited.add(l_url)
                    discovered.append(l_url)
                    queue.append(l_url)
        print(f"[DEBUG] [BFS Crawler] Browser Handshake successful. Discovered {len(discovered)} seed links.")

    # 3. Fast Parallel Extraction
    import requests
    actual_session = session if session else requests.Session()
    if not session: actual_session.headers.update(DEFAULT_HEADERS)
    
    # Inject cookies from handshake
    if res.get("cookies"):
        for cookie in res["cookies"]:
            actual_session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'])

    ua_to_use = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        level = 1
        while queue and len(discovered) < max_pages:
            if stop_event and stop_event.is_set():
                print(f"[DEBUG] [BFS Crawler] Cancellation Signal Received. Stopping crawl.")
                break
                
            batch_size = 10
            batch = queue[:batch_size]
            queue = queue[batch_size:]
            
            # Pass args explicitly to avoid routing session into use_playwright (boolean slot)
            try:
                future_to_url = {executor.submit(fast_extract_links, u, allowed_domains, timeout, False, actual_session, ua_to_use): u for u in batch}
            except RuntimeError:
                print(f"[DEBUG] [BFS Crawler] Executor shutdown detected. Returning discovered links.")
                break
            
            new_additions = 0
            for future in concurrent.futures.as_completed(future_to_url):
                u = future_to_url[future]
                try:
                    new_links, _ = future.result()
                    for link in new_links:
                        # CRITICAL: Strict duplicate prevention and limit enforcement
                        if len(discovered) >= max_pages: break
                        if link not in visited:
                            if is_internal(link, url, allowed_domains=allowed_domains):
                                visited.add(link)
                                discovered.append(link)
                                queue.append(link)
                                new_additions += 1
                except Exception as e:
                    print(f"[DEBUG] [BFS Crawler] Error on {u}: {e}")
                
                if len(discovered) >= max_pages: break
            
            if new_additions > 0:
                print(f"[DEBUG] [BFS Crawler] Batch processed. Discovered {new_additions} NEW links. (Total: {len(discovered)})")
            elif not queue:
                print(f"[DEBUG] [BFS Crawler] SITE EXHAUSTED: No more internal links found after scanning {len(discovered)} pages.")
                break

            if len(discovered) >= max_pages: break

    print(f"[DEBUG] [BFS Crawler] Finished. Discovered {len(discovered)} unique URLs.")
    
    # --- LOG DISCOVERED URLS TO FILE (Rewrite Every Audit) ---
    try:
        if not os.path.exists("scratch"): os.makedirs("scratch")
        with open("scratch/discovered_urls.txt", "w") as f:
            f.write(f"--- DISCOVERED URLS ---\n")
            f.write(f"Total: {len(discovered)}\n\n")
            for d in discovered:
                f.write(f"{d}\n")
        print(f"[DEBUG] [BFS Crawler] URL Discovery log updated: scratch/discovered_urls.txt")
    except Exception as le:
        print(f"[DEBUG] [BFS Crawler] Failed to write URL log: {le}")

    return discovered[:max_pages]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python fetch_page.py <url> [mode]")
        print("Modes: page (default), robots, llms, sitemap, blocks, full")
        sys.exit(1)

    target_url = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else "page"

    if mode == "page":
        data = fetch_page(target_url)
    elif mode == "robots":
        data = fetch_robots_txt(target_url)
    elif mode == "llms":
        data = fetch_llms_txt(target_url)
    elif mode == "bfs":
        print(f"[*] Starting Standalone BFS Discovery for: {target_url}")
        urls = recursive_bfs_crawl(target_url, max_pages=3000)
        data = {
            "target": target_url,
            "total_discovered": len(urls),
            "sample_urls": urls[:10],
            "status": "COMPLETED" if len(urls) > 1 else "FAILED_OR_LIMITED"
        }
    elif mode == "sitemap":
        pages = crawl_sitemap(target_url)
        data = {"pages": pages, "count": len(pages)}
    elif mode == "blocks":
        response = requests.get(target_url, headers=DEFAULT_HEADERS, timeout=30)
        data = extract_content_blocks(response.text)
    elif mode == "full":
        data = {
            "page": fetch_page(target_url),
            "robots": fetch_robots_txt(target_url),
            "llms": fetch_llms_txt(target_url),
            "sitemap": crawl_sitemap(target_url),
        }
    else:
        print(f"Unknown mode: {mode}")
        sys.exit(1)

    print(json.dumps(data, indent=2, default=str))
