#!/usr/bin/env python3
"""
Fetch and parse web pages for GEO analysis.
Extracts HTML, text content, meta tags, headers, and structured data.
"""

import sys
import json
import re
from urllib.parse import urljoin, urlparse

try:
    # Used to make HTTP connections to the target websites. It downloads the raw HTML content of pages, fetches robots.txt and sitemaps, and maintains cross-request sessions (to hold cookies and prevent blocks) when crawling.
    import requests
    # Used to parse the raw HTML that requests downloads. It surgically extracts the exact elements the SEO agents need—pulling <h1> tags, scraping body text while ignoring noise (like <script> or footer tags), extracting internal links for the crawler, and isolating hidden JSON-LD structured data.
    from bs4 import BeautifulSoup
except ImportError:
    print("WARNING: Required packages (requests, bs4) not installed. Crawling functions will be disabled.")

try:
    #Unlike requests, Playwright executes JavaScript and renders the page exactly as a real user would see it.
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

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

#what content to take and store
def fetch_page(url: str, timeout: int = 30, use_playwright: bool = False, session: requests.Session = None) -> dict:
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
                data = json.loads(script.string)
                result["structured_data"].append(data)
            except (json.JSONDecodeError, TypeError):
                result["errors"].append("Invalid JSON-LD detected")

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
        parsed_url = urlparse(url)
        base_domain = parsed_url.netloc
        for link in soup.find_all("a", href=True):
            href = urljoin(url, link["href"])
            # Remove fragments (#section) for cleaner discovery
            href = href.split("#")[0].rstrip("/")
            link_text = link.get_text(strip=True)
            parsed_href = urlparse(href)
            if parsed_href.netloc == base_domain:
                result["internal_links"].append({"url": href, "text": link_text})
            elif parsed_href.scheme in ("http", "https"):
                result["external_links"].append({"url": href, "text": link_text})

        # Text content — decompose non-content elements (destructive)
        for element in soup.find_all(["script", "style", "nav", "footer", "header"]):
            element.decompose()
        text = soup.get_text(separator=" ", strip=True)
        result["text_content"] = text
        result["word_count"] = len(text.split())

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
    # Playwright Fallback if requested or if SSR seems missing
    if (use_playwright or not result.get("has_ssr_content")) and PLAYWRIGHT_AVAILABLE:
        try:
            with sync_playwright() as p:
                # Use a real user agent to bypass basic bot filters
                real_ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                
                browser = p.chromium.launch(headless=True)
                
                # Launch with stealth-like context (v4 Elite Stealth)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800},
                    device_scale_factor=1,
                    is_mobile=False,
                    has_touch=False,
                    locale="en-US",
                    timezone_id="America/New_York",
                )
                
                # Ultimate Webdriver Masking
                page = context.new_page()
                page.add_init_script("delete Object.getPrototypeOf(navigator).webdriver")
                
                # Visit with human-like jitter
                page.goto(url, wait_until="domcontentloaded", timeout=timeout*1000)
                page.wait_for_timeout(2000) # Wait for anti-bot to settle
                
                # Human Interaction Simulation
                page.mouse.wheel(0, 500)
                page.wait_for_timeout(1000)
                
                # Capture session state for handover
                result["cookies"] = context.cookies()
                result["browser_ua"] = context.evaluate("navigator.userAgent")
                
                rendered_content = page.content()
                rendered_soup = BeautifulSoup(rendered_content, "lxml")
                rendered_text = rendered_soup.get_text(separator=" ", strip=True)
                
                # Check for bot detection text in the rendered page
                if "are you a human" in rendered_text.lower() or "captcha" in rendered_text.lower():
                    result["bot_detected"] = True
                    # If still blocked, try one last aggressive scroll
                    page.mouse.wheel(0, -500)
                    page.wait_for_timeout(1000)
                    rendered_content = page.content()
                    rendered_soup = BeautifulSoup(rendered_content, "lxml")
                    rendered_text = rendered_soup.get_text(separator=" ", strip=True)
                
                # Final content capture
                if len(rendered_text) > len(result["text_content"]) * 1.5:
                    result["has_ssr_content"] = False
                    result["rendering_wall_detected"] = True
                    result["text_content"] = rendered_text
                    result["word_count"] = len(rendered_text.split())
                    result["title"] = rendered_soup.title.string if rendered_soup.title else result["title"]
                
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


def crawl_sitemap(url: str, max_pages: int = 5000, timeout: int = 20) -> list:
    """Crawl sitemap.xml to discover pages (Industrial Scale: 200)."""
    parsed = urlparse(url)
    sitemap_urls = [
        f"{parsed.scheme}://{parsed.netloc}/sitemap.xml",
        f"{parsed.scheme}://{parsed.netloc}/sitemap_index.xml",
        f"{parsed.scheme}://{parsed.netloc}/sitemap/",
    ]

    discovered_pages = set()

    for sitemap_url in sitemap_urls:
        try:
            response = requests.get(
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
                            child_resp = requests.get(
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


def fast_extract_links(url: str, base_domain: str, timeout: int = 10, use_playwright: bool = False, session: requests.Session = None) -> list:
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
                    parsed_href = urlparse(href)
                    if base_domain in parsed_href.netloc.replace("www.", ""):
                        links.append(href)
                
                return list(set(links)), cookies
        except Exception:
            pass # Fall back to requests

    # Standard requests approach (sharing session if provided)
    import requests
    target_session = session or requests.Session()
    headers = DEFAULT_HEADERS.copy()
    headers["User-Agent"] = random.choice(USER_AGENTS)
    
    try:
        resp = target_session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "lxml")
            for link in soup.find_all("a", href=True):
                href = urljoin(url, link["href"])
                href = href.split("#")[0].rstrip("/")
                parsed_href = urlparse(href)
                # Check if it's an internal link
                if base_domain in parsed_href.netloc.replace("www.", ""):
                    links.append(href)
    except Exception:
        pass
    return list(set(links)), None


def recursive_bfs_crawl(start_url: str, max_pages: int = 3000, timeout: int = 10) -> list:
    """Fallback recursive BFS crawler to discover internal links if sitemap is missing."""
    import concurrent.futures
    parsed_root = urlparse(start_url)
    base_domain = parsed_root.netloc.replace("www.", "")

    start_clean = start_url.split('#')[0].rstrip('/')
    visited = set([start_clean])
    queue = [start_clean]
    discovered = [start_clean]
    
    print(f"[DEBUG] [BFS Crawler] Starting fast recursive crawl for {base_domain} (Max: {max_pages})")
    
    # Shared Session for Cookie Persistence (Stealth Mode)
    import requests
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        while queue and len(discovered) < max_pages:
            # Process in small batches (5) to protect IP from blocking
            batch = queue[:5]
            queue = queue[5:]
            
            # Use Playwright only for the very first page of BFS discovery (the seed)
            # to ensure we get past Initial challenge screens and capture cookies.
            is_seed = (len(discovered) <= 1)
            future_to_url = {executor.submit(fast_extract_links, u, base_domain, timeout, use_playwright=is_seed, session=session): u for u in batch}
            for future in concurrent.futures.as_completed(future_to_url):
                try:
                    new_links, cookies = future.result()
                    
                    # If this was the seed run, prime the session with extracted cookies
                    if cookies:
                        for cookie in cookies:
                            session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'])
                        print(f"[DEBUG] [BFS Crawler] Session primed with {len(cookies)} cookies.")
                    for link in new_links:
                        if link not in visited:
                            visited.add(link)
                            discovered.append(link)
                            queue.append(link)
                            if len(discovered) >= max_pages:
                                break
                except Exception:
                    pass
                if len(discovered) >= max_pages:
                    break

    print(f"[DEBUG] [BFS Crawler] Finished. Discovered {len(discovered)} unique URLs.")
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
