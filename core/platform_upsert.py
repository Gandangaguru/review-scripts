"""Shared saver: all scrapers in this repo write to the CANONICAL tables the
ReviewIQ app reads: `reviews` (linked to `businesses` by business_id).

(platform_reviews is retired — the dashboard never reads it.)

- Each brand gets one brand-level row in `businesses` (created on first use).
- Reviews dedupe on external_review_id, so reruns never duplicate.
- Only reviews dated on/after MIN_REVIEW_DATE are saved.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

TABLE = "reviews"

# Rolling window instead of a fixed date: on a recurring (weekly) schedule a
# hardcoded cutoff would mean every run re-fetches all history from that date
# forever. 10 days gives a weekly cron a buffer against a missed/delayed run;
# save_platform_reviews() dedupes on external_review_id so the overlap is free.
REVIEW_LOOKBACK_DAYS = 10
MIN_REVIEW_DATE = (datetime.now(timezone.utc) - timedelta(days=REVIEW_LOOKBACK_DAYS)).strftime("%Y-%m-%d")

# specific industry -> consolidated bucket (used by dashboards / kept for reference)
CONSOLIDATED = {
    "Banking": "Financial Services",
    "Insurance": "Financial Services",
    "Financial Services": "Financial Services",
    "Ecommerce": "Retail & Ecommerce",
    "Retail": "Retail & Ecommerce",
    "Restaurants": "Food & Dining",
    "Fast Food": "Food & Dining",
    "ISP": "Technology & Connectivity",
    "Telecom": "Technology & Connectivity",
    "Automotive": "Automotive",
    "Car Dealership": "Automotive",
    "Filling Station": "Petroleum",
    "Health & Medical": "Healthcare",
    "Transportation & Logistics": "Transport & Logistics",
    "Real Estate": "Real Estate",
    "Travel and Tourism": "Travel & Tourism",
}

HELLOPETER_INDUSTRIES = {
    "banking": "Banking",
    "retail": "Retail",
    "restaurants-bars": "Restaurants",
    "financial-services": "Financial Services",
    "internet-telecoms": "ISP",
    "insurance": "Insurance",
    "health-medical": "Health & Medical",
    "automotive": "Automotive",
    "transportation-logistics": "Transportation & Logistics",
    "real-estate": "Real Estate",
}


def min_review_datetime() -> datetime:
    return datetime.fromisoformat(MIN_REVIEW_DATE).replace(tzinfo=timezone.utc)


def make_row(
    *,
    source: str,
    platform_review_id: str,
    brand_name: str,
    rating,
    review_text: str,
    review_date: str,
    industry: str,
    reviewer_name: str = "Anonymous",
    review_title: str = None,
    review_url: str = None,
    city: str = "",
    province: str = "",
    branch: str = "",
    country_code: str = "ZA",
    original_language: str = "en",
    business_id: str = None,
    platform_response: str = None,
    response_at: str = None,
) -> dict:
    """Normalized intermediate record; save_platform_reviews maps it to the
    canonical schema. New keyword args are optional, so existing scrapers
    don't need edits.

    business_id: link the review to this exact `businesses` row (a specific
        branch) instead of resolving by brand name. Branch-level sources
        (Google Places — one listing per store) MUST pass it: resolving by
        brand name sends every store's reviews to the brand-level row, and
        the branch is lost.
    platform_response / response_at: the business's public reply, if any.
    """
    return {
        "source": source,
        "platform_review_id": str(platform_review_id),
        "brand_name": brand_name,
        "reviewer_name": reviewer_name or "Anonymous",
        "rating": rating,
        "review_title": review_title or None,
        "review_text": review_text or "",
        "review_date": review_date,
        "review_url": review_url,
        "industry": industry,
        "city": city,
        "province": province,
        "branch": branch,
        "country_code": country_code,
        "original_language": original_language,
        "sentiment": None,
        "business_id": business_id,
        "platform_response": platform_response or None,
        "response_at": response_at or None,
    }


# ---- businesses lookup / creation -----------------------------------------

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
            prefer = not (r.get("branch_name") or "")  # brand-level rows win
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


# ---- saving ---------------------------------------------------------------

def save_platform_reviews(rows: list) -> int:
    """Dedup on external_review_id, link brands to businesses, insert into
    the canonical reviews table. Returns inserted count."""
    rows = [r for r in rows if r.get("platform_review_id")]
    if not rows:
        return 0

    ids = [r["platform_review_id"] for r in rows]
    existing = set()
    try:
        for i in range(0, len(ids), 100):
            resp = (supabase.table(TABLE)
                    .select("external_review_id")
                    .in_("external_review_id", ids[i:i + 100])
                    .execute())
            existing.update(x["external_review_id"] for x in resp.data)
    except Exception as e:
        print(f"  ⚠️ Dedupe lookup failed, aborting to avoid duplicates: {e}")
        return 0

    new_rows = []
    for r in rows:
        if r["platform_review_id"] in existing:
            continue
        try:
            biz_id = r.get("business_id") or _business_id(r["brand_name"], r.get("industry"))
        except Exception as e:
            print(f"  ⚠️ Could not resolve business for {r['brand_name']}: {e}")
            continue
        new_rows.append({
            "business_id": biz_id,
            "source": r["source"],
            "rating_raw": r.get("rating"),
            "rating_scale_max": 5,
            "review_text": r.get("review_text") or "",
            "reviewer_name": r.get("reviewer_name") or "Anonymous",
            "date_posted": r.get("review_date"),
            "sentiment_label": r.get("sentiment"),
            "external_review_id": r["platform_review_id"],
            **({"platform_response": r["platform_response"], "is_responded": True}
               if r.get("platform_response") else {}),
            **({"response_at": r["response_at"]} if r.get("response_at") else {}),
        })

    inserted = 0
    duplicates = 0
    for i in range(0, len(new_rows), 100):
        chunk = new_rows[i:i + 100]
        try:
            supabase.table(TABLE).insert(chunk).execute()
            inserted += len(chunk)
        except Exception as e:
            if "23505" not in str(e) and "duplicate key" not in str(e):
                print(f"  ⚠️ Insert error: {e}")
                continue
            for row in chunk:
                try:
                    supabase.table(TABLE).insert(row).execute()
                    inserted += 1
                except Exception as e2:
                    if "23505" in str(e2) or "duplicate key" in str(e2):
                        duplicates += 1
                    else:
                        print(f"  ⚠️ Insert error: {e2}")
    if duplicates:
        print(f"  ℹ️ {duplicates} duplicates skipped (already in table)")
    return inserted
