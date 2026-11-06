import asyncio, json
from datetime import datetime
from playwright.async_api import async_playwright

from platform_upsert import save_platform_reviews, make_row, MIN_REVIEW_DATE
from config_businesses import HELLOPETER_BUSINESSES

CUTOFF_DATE = datetime.fromisoformat(MIN_REVIEW_DATE)

USER_AGENT = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')


async def fetch_json(page, url):
    """Load the API URL in the real browser so it carries hellopeter.com cookies."""
    for attempt in range(3):
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        body = await resp.text() if resp else ""
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            status = resp.status if resp else "no response"
            print(f"   attempt {attempt + 1}: status {status}, body starts: {body[:120]!r}")
            await page.wait_for_timeout(5000)
    raise RuntimeError("no JSON after 3 attempts")


async def scrape_reviews(page, business_slug, industry, brand_name=None):
    rows = []
    pg = 1
    while True:
        try:
            url = f"https://api.hellopeter.com/consumer/business/{business_slug}/reviews?page={pg}"
            data = await fetch_json(page, url)
            items = data.get('data', [])
            if not items:
                break
            for item in items:
                created = item.get('created_at', '')
                try:
                    review_date = datetime.strptime(created[:10], '%Y-%m-%d')
                except Exception:
                    review_date = datetime.now()
                if review_date < CUTOFF_DATE:
                    return rows  # newest-first: everything after this is older
                rows.append(make_row(
                    source="HelloPeter",
                    platform_review_id=item.get('id'),
                    brand_name=brand_name or item.get('business_name', business_slug),
                    reviewer_name=item.get('authorDisplayName'),
                    rating=item.get('review_rating'),
                    review_title=item.get('review_title'),
                    review_text=item.get('review_content'),
                    review_date=created[:10],
                    review_url=f"https://www.hellopeter.com/{business_slug}/reviews/{item.get('id')}",
                    industry=industry,
                ))
            if pg >= data.get('last_page', 1):
                break
            pg += 1
        except Exception as e:
            print(f"  Error on page {pg}: {e}")
            break
    return rows


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT, locale="en-ZA")
        page = await context.new_page()

        # Visit the main site first so any bot check sets its cookies
        await page.goto("https://www.hellopeter.com/", wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(3000)

        print(f"Scraping {len(HELLOPETER_BUSINESSES)} brands from config_businesses.py")
        print(f"Collecting reviews on/after {MIN_REVIEW_DATE}")
        for biz in HELLOPETER_BUSINESSES:
            rows = await scrape_reviews(page, biz["slug"], biz["industry"], biz["brand_name"])
            saved = save_platform_reviews(rows)
            print(f"  ✅ {biz['brand_name']} → {saved} new reviews saved ({len(rows)} fetched)")

        await browser.close()


asyncio.run(main())
