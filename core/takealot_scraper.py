import requests
import time
from datetime import datetime

from platform_upsert import save_platform_reviews, make_row, MIN_REVIEW_DATE

# ── CONFIG ──────────────────────────────────────────────────────────────────
MAX_PRODUCTS_PER_DEPT = 200
REVIEWS_PER_PRODUCT = 200

cutoff_date = datetime.fromisoformat(MIN_REVIEW_DATE)

DATE_FORMATS = ["%d %b %Y", "%d %B %Y", "%Y-%m-%d", "%d/%m/%Y"]


def parse_review_date(raw):
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(str(raw).strip(), fmt)
        except (ValueError, TypeError):
            continue
    return None

DEPARTMENTS = [
    {"name": "Appliances",            "query": "defy hisense samsung washing machine fridge"},
    {"name": "Baby & Toddler",        "query": "pampers huggies johnsons baby formula"},
    {"name": "Beauty",                "query": "loreal nivea neutrogena garnier vaseline olay"},
    {"name": "Clothing & Shoes",      "query": "nike adidas puma converse sneakers"},
    {"name": "Electronics",           "query": "hisense samsung sony jbl apple skyworth tcl"},
    {"name": "Groceries & Household", "query": "sunlight omo domestos dettol handy andy"},
    {"name": "Health & Personal Care","query": "panado disprin usn omega centrum"},
    {"name": "Homeware",              "query": "russell hobbs defy smeg utensil sets le creuset"},
]

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-ZA,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.takealot.com/",
    "Origin": "https://www.takealot.com",
    "Connection": "keep-alive",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
})


def warm_up():
    try:
        session.get("https://www.takealot.com/", timeout=10)
        print("🔥 Session warmed up\n")
        time.sleep(2)
    except:
        pass


def get_products(query, max_products=MAX_PRODUCTS_PER_DEPT):
    products = []
    seen_plids = set()
    rows = 30
    start = 0
    max_offset = 300

    while len(products) < max_products and start < max_offset:
        url = (
            f"https://api.takealot.com/rest/v-1-9-0/searches/products"
            f"?newsearch=true&qsearch={requests.utils.quote(query)}"
            f"&rows={rows}&start={start}&sort=BestSeller"
        )
        try:
            resp = session.get(url, timeout=15)
            if resp.status_code != 200:
                print(f"  ⚠️ HTTP {resp.status_code}")
                break
            data = resp.json()
            results = data.get("sections", {}).get("products", {}).get("results", [])
            if not results:
                break
            print(f"  🔍 Found {len(results)} products at offset {start}")
            for item in results:
                pv = item.get("product_views", {})
                if not pv:
                    continue
                core = pv.get("core", {})
                buybox = pv.get("buybox_summary", {})
                review_summary = pv.get("review_summary", {})

                plid = str(core.get("id", ""))
                if not plid or plid in seen_plids:
                    continue
                seen_plids.add(plid)

                review_count = review_summary.get("review_count", 0) or 0
                if review_count == 0:
                    continue

                products.append({
                    "title": core.get("title", ""),
                    "slug": core.get("slug", ""),
                    "plid": plid,
                    "brand": core.get("brand", ""),
                    "price": (buybox.get("prices") or [0])[0],
                    "review_count": review_count,
                })
                if len(products) >= max_products:
                    break
            start += rows
            time.sleep(1)
        except Exception as e:
            print(f"  ❌ Error: {e}")
            break

    return products


def get_reviews(plid, slug, dept_name, brand="", p_title="", max_reviews=REVIEWS_PER_PRODUCT):
    reviews = []
    page = 1

    while len(reviews) < max_reviews:
        url = (
            f"https://api.takealot.com/rest/v-1-9-0/product-reviews/plid/{plid}"
            f"?page={page}&page_size=10&sort=NewestFirst"
        )
        try:
            resp = session.get(url, timeout=15)
            if resp.status_code != 200:
                break

            data = resp.json()
            items = data.get("reviews") or []
            if not items:
                break

            for r in items:
                rating = r.get("rating", 0)
                try:
                    rating = int(rating)
                except:
                    continue
                if not (1 <= rating <= 5):
                    continue

                parsed = parse_review_date(r.get("date", ""))
                if parsed and parsed < cutoff_date:
                    return reviews  # NewestFirst: rest are older

                reviews.append(make_row(
                    source="Takealot",
                    platform_review_id=r.get("uuid", ""),
                    brand_name=brand if brand else p_title,
                    reviewer_name=r.get("customer_name", "Anonymous"),
                    rating=rating,
                    review_text=r.get("text", ""),
                    review_date=parsed.date().isoformat() if parsed else r.get("date", ""),
                    review_url=f"https://www.takealot.com/{slug}",
                    industry="Ecommerce",
                ))
                if len(reviews) >= max_reviews:
                    return reviews
            page += 1
            time.sleep(0.3)
        except Exception as e:
            print(f"  ❌ Review error for PLID{plid}: {e}")
            break

    return reviews


def save_reviews(reviews):
    return save_platform_reviews(reviews)


def debug_reviews(plid):
    url = f"https://api.takealot.com/rest/v-1-9-0/product-reviews/plid/{plid}?page=1&page_size=10&sort=NewestFirst"
    resp = session.get(url, timeout=15)
    data = resp.json()
    print(f"Status: {resp.status_code}")
    print(f"Top-level keys: {list(data.keys())}")
    for key in ["results", "reviews", "product_reviews"]:
        items = data.get(key)
        if items:
            print(f"  → '{key}' has {len(items)} items")
            print(f"  → First item keys: {list(items[0].keys())}")
            break
    else:
        print("  → Raw response:", str(data)[:500])


def main():
    print("🛒 Starting Takealot scraper...")
    print(f"📅 Cutoff date: {cutoff_date.strftime('%d %B %Y')}\n")
    warm_up()

    total_reviews = 0
    total_products = 0

    for dept in DEPARTMENTS:
        print(f"📦 Department: {dept['name']}")
        products = get_products(dept["query"])

        if not products:
            print("  ⚪ No products found\n")
            continue

        print(f"  ✅ {len(products)} unique products with reviews found")

        for p in products:
            plid = p.get("plid")
            slug = p.get("slug")
            title = p.get("title", "Unknown")
            if not plid:
                continue

            print(f"  🔄 {title[:50]} (PLID{plid})")
            reviews = get_reviews(plid, slug, dept["name"], p.get("brand", ""))
            if reviews:
                saved = save_reviews(reviews)
                total_reviews += saved
                total_products += 1
                print(f"  ⭐ → {saved} recent reviews saved")
            else:
                print(f"  ➖ → no recent reviews")

            time.sleep(0.8)
        print()

    print(f"🎉 Done! {total_reviews} reviews saved from {total_products} products across {len(DEPARTMENTS)} departments.")


if __name__ == "__main__":
    main()
