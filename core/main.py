"""HelloPeter crawl (weekly). Drives a browser because HelloPeter retired its public API in 2026-10.

  python main.py                          all brands in config_businesses.py
  python main.py --brand "Burger King"    one brand
  python main.py --dry-run                fetch and count, save nothing
Backfill: REVIEW_LOOKBACK_DAYS=34 python main.py --brand "Burger King"
"""
import sys
from datetime import datetime

from playwright.sync_api import sync_playwright

from platform_upsert import save_platform_reviews, MIN_REVIEW_DATE
from config_businesses import HELLOPETER_BUSINESSES
from hellopeter_scraper import scrape_business

CUTOFF_DATE = datetime.fromisoformat(MIN_REVIEW_DATE)
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/124.0.0.0 Safari/537.36')


def main():
    only = sys.argv[sys.argv.index("--brand") + 1].lower() if "--brand" in sys.argv else None
    dry = "--dry-run" in sys.argv
    businesses = [b for b in HELLOPETER_BUSINESSES if not only or b["brand_name"].lower() == only]
    print(f"Scraping {len(businesses)} brands from config_businesses.py")
    print(f"Collecting reviews on/after {MIN_REVIEW_DATE}{' (dry run, nothing saved)' if dry else ''}")
    empty = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(user_agent=UA, locale="en-ZA").new_page()
        for biz in businesses:
            try:
                rows = scrape_business(page, biz["slug"], biz["industry"], biz["brand_name"], CUTOFF_DATE)
            except Exception as e:
                print(f"  ❌ {biz['brand_name']} → {type(e).__name__}: {str(e)[:120]}")
                empty.append(biz["brand_name"])
                continue
            saved = 0 if dry else save_platform_reviews(rows)
            print(f"  ✅ {biz['brand_name']} → {saved} new reviews saved ({len(rows)} fetched)")
        browser.close()
    if empty:
        print(f"\nFailed: {', '.join(empty)}")
        sys.exit(1)  # makes the GitHub Actions step show red instead of silently saving nothing


if __name__ == "__main__":
    main()
