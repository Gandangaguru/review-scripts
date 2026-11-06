import asyncio, os, re
from datetime import datetime, timedelta
from playwright.async_api import async_playwright

from platform_upsert import save_platform_reviews, make_row, MIN_REVIEW_DATE
from config_businesses import HELLOPETER_BUSINESSES

# Date window. For a backfill, set HP_FROM / HP_TO (YYYY-MM-DD, HP_TO inclusive).
# Left blank (the weekly schedule), it uses the normal rolling window.
DATE_FROM = datetime.fromisoformat(os.getenv("HP_FROM") or MIN_REVIEW_DATE)
DATE_TO = (datetime.fromisoformat(os.getenv("HP_TO")) + timedelta(days=1)
           if os.getenv("HP_TO") else datetime.max)

MAX_PAGES = 200  # safety cap per brand
UUID_RE = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$")

USER_AGENT = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')

# Reads every review card on the current page of a brand's HelloPeter profile.
EXTRACT_JS = r"""
() => [...document.querySelectorAll('.space-y-4 > div')]
  .filter(c => c.querySelector('a[href*="/reviews/"]'))
  .map(c => {
    const d = c.querySelector('.sm\\:flex') || c;
    const href = d.querySelector('a[href*="/reviews/"]').getAttribute('href');
    const stars = [...d.querySelectorAll('svg.lucide-star')];
    const spans = [...d.querySelectorAll('span.text-xs')].map(s => s.textContent.trim());
    return {
      href,
      author: d.querySelector('a.font-semibold')?.textContent.trim() || null,
      date: spans[spans.length - 1] || '',
      title: d.querySelector('h3')?.textContent.trim() || null,
      text: d.querySelector('p.text-sm')?.textContent.trim() || '',
      rating: stars.filter(s => getComputedStyle(s).color !== 'rgb(229, 231, 235)').length,
    };
  })
"""

WAIT_NEW_PAGE_JS = """
(prev) => {
  const a = document.querySelector('.space-y-4 > div a[href*="/reviews/"]');
  return a && a.getAttribute('href') !== prev;
}
"""


async def scrape_brand(page, slug, industry, brand_name):
    rows, seen = [], set()
    await page.goto(f"https://www.hellopeter.com/{slug}", wait_until="domcontentloaded", timeout=60000)
    try:
        await page.wait_for_selector('a[href*="/reviews/"]', timeout=20000)
    except Exception:
        print(f"  ⚠️ {brand_name}: no reviews found on page (check slug '{slug}')")
        return rows

    oldest = None
    for page_no in range(1, MAX_PAGES + 1):
        cards = await page.evaluate(EXTRACT_JS)
        if not cards:
            break
        for c in cards:
            m = UUID_RE.search(c["href"])
            if not m or m.group(1) in seen:
                continue
            seen.add(m.group(1))
            try:
                dt = datetime.strptime(c["date"], "%d %b %Y, %H:%M")
            except ValueError:
                continue
            oldest = dt if oldest is None or dt < oldest else oldest
            if DATE_FROM <= dt < DATE_TO:
                rows.append(make_row(
                    source="HelloPeter",
                    platform_review_id=m.group(1),
                    brand_name=brand_name,
                    reviewer_name=c["author"],
                    rating=c["rating"] or None,
                    review_title=c["title"],
                    review_text=c["text"],
                    review_date=dt.strftime("%Y-%m-%d"),
                    review_url="https://www.hellopeter.com" + c["href"],
                    industry=industry,
                ))
        if oldest and oldest < DATE_FROM:
            break  # newest-first: we've gone past the window

        nxt = page.get_by_role("button", name="Next")
        if await nxt.count() == 0 or await nxt.first.is_disabled():
            break
        await nxt.first.evaluate("b => b.click()")  # JS click: ad banners can't block it
        try:
            await page.wait_for_function(WAIT_NEW_PAGE_JS, arg=cards[0]["href"], timeout=20000)
        except Exception:
            print(f"  ⚠️ {brand_name}: page {page_no + 1} didn't load, stopping here")
            break

    reached = oldest.strftime("%Y-%m-%d") if oldest else "n/a"
    print(f"  {brand_name}: {page_no} pages read, oldest review seen {reached}")
    return rows


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT, locale="en-ZA")
        page = await context.new_page()

        to_label = os.getenv("HP_TO") or "today"
        print(f"Scraping {len(HELLOPETER_BUSINESSES)} brands, window {DATE_FROM.date()} → {to_label}")
        for biz in HELLOPETER_BUSINESSES:
            try:
                rows = await scrape_brand(page, biz["slug"], biz["industry"], biz["brand_name"])
            except Exception as e:
                print(f"  ⚠️ {biz['brand_name']}: {e}")
                continue
            saved = save_platform_reviews(rows)
            print(f"  ✅ {biz['brand_name']} → {saved} new reviews saved ({len(rows)} in window)")

        await browser.close()


asyncio.run(main())
