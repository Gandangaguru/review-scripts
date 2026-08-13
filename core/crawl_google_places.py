"""Monthly Google Places review crawl via Apify.

Unlike the old google_maps_banks_loader.py (which just re-read one static,
one-off Apify dataset — never re-crawled anything), this script:

1. Pulls every business in `businesses` that has a google_place_id.
2. Starts a fresh compass/crawler-google-places Apify run against those
   place IDs, asking only for reviews from the last GOOGLE_PLACES_LOOKBACK_DAYS.
3. Polls until the run finishes, then reads its dataset and upserts new
   reviews via the shared platform_upsert helpers (dedup on
   external_review_id, so re-running is always safe).

Each business's own `industry` is used (the old script hardcoded "Banking"
for every place, which was wrong for the ~150 non-bank businesses).

Runs monthly (not weekly like HelloPeter/Takealot) — Apify usage here is
capped to a monthly cadence, so the lookback window is sized to a month
plus a buffer rather than reusing platform_upsert's 10-day weekly window.
"""
import argparse
import os
import time
from datetime import datetime

import requests
from dotenv import load_dotenv

from platform_upsert import make_row, save_platform_reviews, supabase

load_dotenv()

APIFY_TOKEN = os.getenv("APIFY_TOKEN")
ACTOR_ID = "compass~crawler-google-places"  # Google Maps Scraper (Compass)
POLL_SECONDS = 15
RUN_TIMEOUT_MINUTES = 60
GOOGLE_PLACES_LOOKBACK_DAYS = 35  # ~1 month + buffer for a monthly cron


def fetch_target_businesses() -> list[dict]:
    """{place_id, brand_name, industry} for every business with a Google Place ID."""
    targets = []
    offset = 0
    while True:
        rows = (
            supabase.table("businesses")
            .select("brand, name, industry, settings")
            .range(offset, offset + 999)
            .execute()
            .data
        )
        for r in rows:
            place_id = (r.get("settings") or {}).get("google_place_id")
            if place_id:
                targets.append(
                    {
                        "place_id": place_id,
                        "brand_name": r.get("brand") or r.get("name") or "Unknown",
                        "industry": r.get("industry") or "Uncategorized",
                    }
                )
        if len(rows) < 1000:
            break
        offset += 1000
    return targets


def start_run(place_ids: list[str]) -> dict:
    url = f"https://api.apify.com/v2/acts/{ACTOR_ID}/runs"
    payload = {
        "placeIds": place_ids,
        "maxReviews": 5000,
        "reviewsSort": "newest",
        "reviewsStartDate": f"{GOOGLE_PLACES_LOOKBACK_DAYS} days",
        "language": "en",
        "scrapeReviewsPersonalData": False,
    }
    resp = requests.post(url, params={"token": APIFY_TOKEN}, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()["data"]


def wait_for_run(run_id: str) -> dict:
    url = f"https://api.apify.com/v2/actor-runs/{run_id}"
    deadline = time.time() + RUN_TIMEOUT_MINUTES * 60
    while time.time() < deadline:
        resp = requests.get(url, params={"token": APIFY_TOKEN}, timeout=30)
        resp.raise_for_status()
        data = resp.json()["data"]
        status = data["status"]
        if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
            return data
        print(f"  ⏳ run {run_id}: {status} — checking again in {POLL_SECONDS}s")
        time.sleep(POLL_SECONDS)
    raise TimeoutError(f"Apify run {run_id} did not finish within {RUN_TIMEOUT_MINUTES} minutes")


def fetch_dataset_items(dataset_id: str) -> list[dict]:
    url = f"https://api.apify.com/v2/datasets/{dataset_id}/items"
    resp = requests.get(
        url, params={"token": APIFY_TOKEN, "format": "json", "clean": "true"}, timeout=60
    )
    resp.raise_for_status()
    return resp.json()


def map_reviews_for_item(item: dict, business_by_place_id: dict) -> list[dict]:
    place_id = item.get("placeId") or item.get("place_id")
    target = business_by_place_id.get(place_id) or {}
    brand_name = target.get("brand_name") or item.get("title") or "Unknown"
    industry = target.get("industry") or "Uncategorized"

    rows = []
    for r in item.get("reviews") or []:
        published_raw = r.get("publishedAtDate") or r.get("publishedAt")
        if not published_raw:
            continue
        try:
            published_at = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
        except Exception:
            continue

        review_id = r.get("reviewId") or r.get("reviewHash")
        if not review_id:
            continue

        rows.append(
            make_row(
                source="Google Places",
                platform_review_id=review_id,
                brand_name=brand_name,
                reviewer_name=r.get("reviewerName") or r.get("name"),
                rating=r.get("rating") or r.get("stars"),
                review_text=r.get("text") or r.get("textTranslated") or "",
                review_date=published_at.date().isoformat(),
                review_url=item.get("url"),
                city=item.get("city") or "",
                country_code=item.get("countryCode") or "ZA",
                industry=industry,
            )
        )
    return rows


def ingest_items(items: list[dict], business_by_place_id: dict) -> int:
    total = 0
    for idx, item in enumerate(items, start=1):
        rows = map_reviews_for_item(item, business_by_place_id)
        if not rows:
            continue
        inserted = save_platform_reviews(rows)
        total += inserted
        print(f"  [{idx}/{len(items)}] {item.get('title', '?')} → {inserted} new reviews")
    return total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset-id",
        help=(
            "Ingest an already-finished Apify dataset instead of starting a new "
            "run (e.g. one triggered manually from the Apify console). Find it "
            "in the Apify console under Storage > Datasets, or on the run's "
            "Output tab."
        ),
    )
    args = parser.parse_args()

    targets = fetch_target_businesses()
    if not targets:
        print("No businesses with a google_place_id found — nothing to crawl.")
        return
    business_by_place_id = {t["place_id"]: t for t in targets}

    if args.dataset_id:
        print(f"📍 Ingesting existing Apify dataset {args.dataset_id} (no new run started)...")
        items = fetch_dataset_items(args.dataset_id)
    else:
        print("📍 Starting Google Places crawl...")
        place_ids = list(business_by_place_id.keys())
        print(
            f"Found {len(place_ids)} businesses with a Google Place ID "
            f"(reviews from the last {GOOGLE_PLACES_LOOKBACK_DAYS} days)"
        )
        run = start_run(place_ids)
        print(f"  ▶️ Apify run {run['id']} started, waiting for it to finish...")
        run = wait_for_run(run["id"])
        if run["status"] != "SUCCEEDED":
            raise RuntimeError(f"Apify run finished with status {run['status']}")
        items = fetch_dataset_items(run["defaultDatasetId"])

    print(f"Got {len(items)} place records from Apify")
    total = ingest_items(items, business_by_place_id)
    print(f"🎉 Done. Inserted {total} new Google Places reviews.")


if __name__ == "__main__":
    main()
