import asyncio, httpx
from datetime import datetime

from platform_upsert import save_platform_reviews, make_row, MIN_REVIEW_DATE
from config_businesses import HELLOPETER_BUSINESSES

CUTOFF_DATE = datetime.fromisoformat(MIN_REVIEW_DATE)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'application/json',
    'Referer': 'https://www.hellopeter.com/'
}


async def scrape_reviews(client, business_slug, industry, brand_name=None):
    rows = []
    page = 1
    while True:
        try:
            url = f"https://api.hellopeter.com/consumer/business/{business_slug}/reviews?page={page}"
            r = await client.get(url, headers=HEADERS)
            data = r.json()
            items = data.get('data', [])
            if not items:
                break
            for item in items:
                created = item.get('created_at', '')
                try:
                    review_date = datetime.strptime(created[:10], '%Y-%m-%d')
                except:
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
            if page >= data.get('last_page', 1):
                break
            page += 1
        except Exception as e:
            print(f"  Error on page {page}: {e}")
            break
    return rows


async def main():
    async with httpx.AsyncClient(timeout=30) as client:
        print(f"Scraping {len(HELLOPETER_BUSINESSES)} brands from config_businesses.py")
        print(f"Collecting reviews on/after {MIN_REVIEW_DATE}")
        for biz in HELLOPETER_BUSINESSES:
            rows = await scrape_reviews(client, biz["slug"], biz["industry"], biz["brand_name"])
            saved = save_platform_reviews(rows)
            print(f"  ✅ {biz['brand_name']} → {saved} new reviews saved ({len(rows)} fetched)")

asyncio.run(main())
