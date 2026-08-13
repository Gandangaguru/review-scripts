import asyncio
import hashlib
import re
from datetime import datetime
from playwright.async_api import async_playwright

from platform_upsert import (
    supabase, save_platform_reviews, make_row, MIN_REVIEW_DATE,
)

BASE_URL = "https://www.autotrader.co.za"
DEALERS_URL = f"{BASE_URL}/car-dealers"
TOTAL_PAGES = 148
CUTOFF_DATE = datetime.fromisoformat(MIN_REVIEW_DATE)

def parse_date(date_str):
    formats = [
        "%d %B %Y",       # 15 March 2026
        "%B %d, %Y",      # March 15, 2026
        "%d/%m/%Y",       # 15/03/2026
        "%Y-%m-%d",       # 2026-03-15
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except:
            continue
    return None

def is_in_range(date_str):
    parsed = parse_date(date_str)
    if parsed:
        return parsed >= CUTOFF_DATE
    return False

def is_before_cutoff(date_str):
    parsed = parse_date(date_str)
    if parsed:
        return parsed < CUTOFF_DATE
    return False

def review_fingerprint(dealer_id, reviewer, date_str, text):
    """Autotrader reviews have no native ID — build a stable one."""
    raw = f"{dealer_id}|{reviewer}|{date_str}|{(text or '')[:100]}"
    return "at-" + hashlib.md5(raw.encode()).hexdigest()

async def scrape_dealer_list(page, page_num):
    url = f"{DEALERS_URL}?pagenumber={page_num}"
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(2000)

    dealers = []
    cards = await page.query_selector_all(".e-dealer-tile, [class*='dealer-tile'], [class*='DealerTile']")

    for card in cards:
        try:
            name_el = await card.query_selector("h2, h3, [class*='name'], [class*='Name']")
            name = await name_el.inner_text() if name_el else None

            link_el = await card.query_selector("a")
            href = await link_el.get_attribute("href") if link_el else None

            location_el = await card.query_selector("[class*='location'], [class*='Location'], [class*='address']")
            location = await location_el.inner_text() if location_el else None

            rating_el = await card.query_selector("[class*='rating'], [class*='Rating'], [class*='score']")
            rating_text = await rating_el.inner_text() if rating_el else None
            avg_rating = None
            if rating_text:
                match = re.search(r"[\d.]+", rating_text)
                avg_rating = float(match.group()) if match else None

            review_count_el = await card.query_selector("[class*='review'], [class*='Review']")
            review_count_text = await review_count_el.inner_text() if review_count_el else None
            review_count = None
            if review_count_text:
                match = re.search(r"\d+", review_count_text)
                review_count = int(match.group()) if match else None

            # Extract slug and dealer_id from URL
            slug, dealer_id = None, None
            if href:
                match = re.search(r"/dealer/([^/]+)/(\d+)", href)
                if match:
                    slug = match.group(1)
                    dealer_id = match.group(2)

            if name and dealer_id:
                dealers.append({
                    "name": name.strip(),
                    "slug": slug,
                    "dealer_id": dealer_id,
                    "location": location.strip() if location else None,
                    "avg_rating": avg_rating,
                    "review_count": review_count,
                    "url": f"{BASE_URL}{href}" if href else None,
                    "is_active": True
                })
        except Exception as e:
            continue

    return dealers

async def scrape_dealer_reviews(page, dealer):
    url = f"{dealer['url']}#Reviews"
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)
    except:
        return []

    reviews = []
    stop_scraping = False

    while not stop_scraping:
        review_cards = await page.query_selector_all(
            "[class*='review-item'], [class*='ReviewItem'], [class*='review-card'], [class*='ReviewCard']"
        )

        if not review_cards:
            break

        for card in review_cards:
            try:
                date_el = await card.query_selector("[class*='date'], [class*='Date'], time")
                date_str = await date_el.inner_text() if date_el else ""

                if is_before_cutoff(date_str):
                    stop_scraping = True
                    break

                if not is_in_range(date_str):
                    continue

                reviewer_el = await card.query_selector("[class*='author'], [class*='Author'], [class*='reviewer'], [class*='name']")
                reviewer_name = await reviewer_el.inner_text() if reviewer_el else "Anonymous"

                rating_el = await card.query_selector("[class*='rating'], [class*='Rating'], [aria-label*='star']")
                rating_text = await rating_el.get_attribute("aria-label") if rating_el else None
                if not rating_text:
                    rating_text = await rating_el.inner_text() if rating_el else None
                rating = None
                if rating_text:
                    match = re.search(r"\d", rating_text)
                    rating = int(match.group()) if match else None

                text_el = await card.query_selector("[class*='text'], [class*='Text'], [class*='body'], [class*='Body'], p")
                review_text = await text_el.inner_text() if text_el else None

                response_el = await card.query_selector("[class*='response'], [class*='Response'], [class*='reply']")
                owner_response = await response_el.inner_text() if response_el else None

                if review_text:
                    parsed_date = parse_date(date_str)
                    reviews.append(make_row(
                        source="Autotrader",
                        platform_review_id=review_fingerprint(
                            dealer["dealer_id"], reviewer_name, date_str, review_text
                        ),
                        brand_name=dealer["name"],
                        reviewer_name=reviewer_name.strip() if reviewer_name else "Anonymous",
                        rating=rating,
                        review_text=review_text.strip(),
                        review_date=parsed_date.date().isoformat() if parsed_date else date_str.strip(),
                        review_url=dealer.get("url"),
                        industry="Car Dealership",
                    ))

            except Exception as e:
                continue

        # Try to load more reviews
        try:
            load_more = await page.query_selector(
                "button[class*='load-more'], button[class*='LoadMore'], button[class*='show-more']"
            )
            if load_more and not stop_scraping:
                await load_more.click()
                await page.wait_for_timeout(2000)
            else:
                break
        except:
            break

    return reviews

async def save_dealers(dealers):
    if not dealers:
        return
    try:
        supabase.table("autotrader_dealers").upsert(dealers, on_conflict="dealer_id").execute()
    except Exception as e:
        print(f"  ⚠️ Error saving dealers: {e}")

async def save_reviews(reviews):
    if not reviews:
        return
    save_platform_reviews(reviews)

async def main():
    print(f"🚗 Starting Autotrader scraper (reviews on/after {MIN_REVIEW_DATE})...\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        page = await context.new_page()

        # Phase 1: Scrape dealer list
        print("📋 Phase 1: Collecting dealers...")
        all_dealers = []

        for page_num in range(1, TOTAL_PAGES + 1):
            print(f"  Page {page_num}/{TOTAL_PAGES}", end="\r")
            dealers = await scrape_dealer_list(page, page_num)
            if dealers:
                all_dealers.extend(dealers)
                await save_dealers(dealers)
            await asyncio.sleep(1)  # polite delay

        print(f"\n  ✅ Found {len(all_dealers)} dealers\n")

        # Phase 2: Scrape reviews per dealer
        print("⭐ Phase 2: Scraping 2026 reviews...")
        total_reviews = 0

        for i, dealer in enumerate(all_dealers, 1):
            reviews = await scrape_dealer_reviews(page, dealer)
            if reviews:
                await save_reviews(reviews)
                total_reviews += len(reviews)
                print(f"  ✅ {dealer['name']} → {len(reviews)} reviews saved")
            else:
                print(f"  ⚪ {dealer['name']} → no 2026 reviews")

            await asyncio.sleep(1.5)  # polite delay between dealers

        await browser.close()

    print(f"\n🎉 Done! {total_reviews} total 2026 reviews saved from {len(all_dealers)} dealers.")

if __name__ == "__main__":
    asyncio.run(main())
