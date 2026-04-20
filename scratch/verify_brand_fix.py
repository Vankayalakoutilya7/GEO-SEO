import sys
import os
from pathlib import Path
import json

# Add scripts to path
sys.path.append(str(Path(__file__).parent.parent / "scripts"))
from brand_scanner import generate_brand_report

def test_brand_detection():
    brand = "TestBrand"
    domain = "testbrand.com"
    mock_links = [
        {"url": "https://www.youtube.com/@TestBrandOfficial", "text": "YouTube"},
        {"url": "https://www.reddit.com/r/TestBrand", "text": "Reddit"},
        {"url": "https://en.wikipedia.org/wiki/TestBrand_Company", "text": "Wikipedia"}
    ]
    
    print(f"Testing brand detection for {brand} with mock links...")
    report = generate_brand_report(brand, domain, external_links=mock_links)
    
    # Check YouTube
    yt = report["platforms"]["youtube"]
    print(f"YouTube detected: {yt.get('has_channel')} - {yt.get('official_url', 'None')}")
    
    # Check Reddit
    rd = report["platforms"]["reddit"]
    print(f"Reddit detected: {rd.get('has_subreddit')} - {rd.get('official_url', 'None')}")
    
    # Check Wikipedia
    wk = report["platforms"]["wikipedia"]
    print(f"Wikipedia detected: {wk.get('has_wikipedia_page')} - {wk.get('official_url', 'None')}")
    
    # Assertions
    assert yt["has_channel"] == True
    assert rd["has_subreddit"] == True
    assert wk["has_wikipedia_page"] == True
    print("\nSUCCESS: All platforms correctly detected from external links!")

if __name__ == "__main__":
    try:
        test_brand_detection()
    except Exception as e:
        print(f"\nFAILURE: {e}")
        sys.exit(1)
