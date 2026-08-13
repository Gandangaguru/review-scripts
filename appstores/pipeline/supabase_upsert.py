"""Write app-store reviews into the CANONICAL tables the ReviewIQ app reads:
`reviews` (linked to `businesses` by business_id). platform_reviews is retired.

- Each brand gets one brand-level businesses row (created on first use).
- Dedup on external_review_id, so reruns never duplicate.
"""
import os
import uuid

from supabase import create_client
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

TABLE = "reviews"

SOURCE_LABELS = {
    "google_play": "Google Play",
    "apple_store": "Apple App Store",
}

# sector -> specific industry label (matches businesses.industry conventions)
INDUSTRY_MAP = {
    "banking": "Banking",
    "telecom": "Telecom",
    "qsr": "Fast Food",
    "delivery": "Food Delivery",
    "retail": "Retail",
}

_business_cache = None  # lower(name or brand) -> business id


def _load_businesses():
    global _business_cache
    if _business_cache is not None:
        return _business_cache
    cache = {}
    offset = 0
    while True:
        rows = (supabase.table("businesses")
                .select("id, name, brand, branch_name")
                .range(offset, offset + 999).execute().data)
        for r in rows:
            prefer = not (r.get("branch_name") or "")
            for key in (r.get("brand"), r.get("name")):
                if not key:
                    continue
                k = key.strip().lower()
                if k not in cache or prefer:
                    cache[k] = r["id"]
        if len(rows) < 1000:
            break
        offset += 1000
    _business_cache = cache
    return cache


def _business_id(brand_name: str, industry: str) -> str:
    cache = _load_businesses()
    key = (brand_name or "").strip().lower()
    if key in cache:
        return cache[key]
    new_id = str(uuid.uuid4())
    supabase.table("businesses").insert({
        "id": new_id,
        "name": brand_name,
        "brand": brand_name,
        "industry": industry,
        "country": "ZA",
        "currency": "ZAR",
    }).execute()
    cache[key] = new_id
    return new_id


def upsert_appstore_reviews(records: list):
    records = [r for r in records if r.get("review_id")]
    if not records:
        logger.warning("No records to upsert.")
        return

    ids = [r["review_id"] for r in records]
    existing = set()
    try:
        for i in range(0, len(ids), 100):
            resp = (supabase.table(TABLE)
                    .select("external_review_id")
                    .in_("external_review_id", ids[i:i + 100])
                    .execute())
            existing.update(x["external_review_id"] for x in resp.data)
    except Exception as e:
        logger.error(f"Dedupe lookup failed, aborting to avoid duplicates: {e}")
        return

    new_rows = []
    for r in records:
        if r["review_id"] in existing:
            continue
        industry = INDUSTRY_MAP.get(r.get("sector"), (r.get("sector") or "").title())
        try:
            biz_id = _business_id(r["brand_name"], industry)
        except Exception as e:
            logger.error(f"Could not resolve business for {r['brand_name']}: {e}")
            continue
        new_rows.append({
            "business_id": biz_id,
            "source": SOURCE_LABELS.get(r["source"], r["source"]),
            "rating_raw": r.get("rating"),
            "rating_scale_max": 5,
            "review_text": r.get("review_text") or "",
            "reviewer_name": r.get("author_name") or "Anonymous",
            "date_posted": r.get("review_date"),
            "sentiment_label": r.get("sentiment_label"),
            "external_review_id": r["review_id"],
        })

    if not new_rows:
        logger.info(f"All {len(records)} reviews already in {TABLE} — nothing to insert.")
        return

    logger.info(f"Inserting {len(new_rows)} new reviews into {TABLE} "
                f"({len(existing)} already present)...")
    success = 0
    duplicates = 0
    for i in range(0, len(new_rows), 100):
        chunk = new_rows[i:i + 100]
        try:
            supabase.table(TABLE).insert(chunk).execute()
            success += len(chunk)
        except Exception as e:
            if "23505" not in str(e) and "duplicate key" not in str(e):
                logger.error(f"Insert error for chunk starting at {i}: {e}")
                continue
            for row in chunk:
                try:
                    supabase.table(TABLE).insert(row).execute()
                    success += 1
                except Exception as e2:
                    if "23505" in str(e2) or "duplicate key" in str(e2):
                        duplicates += 1
                    else:
                        logger.error(f"Insert error: {e2}")

    if duplicates:
        logger.info(f"{duplicates} duplicates skipped (already in table)")
    logger.success(f"Inserted {success}/{len(new_rows)} new reviews into {TABLE}.")
