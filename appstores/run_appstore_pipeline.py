from config_apps import (
    SA_APPS, REVIEWS_PER_APP, COUNTRY_CODE, LANG_CODE, MIN_REVIEW_DATE,
)
from scrapers.google_play_scraper import fetch_google_play_reviews
from scrapers.apple_store_scraper import fetch_apple_store_reviews
from pipeline.supabase_upsert import upsert_appstore_reviews
from loguru import logger


def main():
    logger.info(f"Collecting reviews dated on/after {MIN_REVIEW_DATE}")

    for app in SA_APPS:
        all_records = []

        if app.get("google_play_id"):
            gp_records = fetch_google_play_reviews(
                app_id=app["google_play_id"],
                brand_name=app["brand_name"],
                country=COUNTRY_CODE,
                lang=LANG_CODE,
                count=REVIEWS_PER_APP,
                min_date=MIN_REVIEW_DATE,
            )
            all_records.extend(gp_records)

        if app.get("apple_app_id") and app.get("apple_app_name"):
            as_records = fetch_apple_store_reviews(
                app_id=app["apple_app_id"],
                app_name=app["apple_app_name"],
                brand_name=app["brand_name"],
                country=COUNTRY_CODE,
                count=REVIEWS_PER_APP,
                min_date=MIN_REVIEW_DATE,
            )
            all_records.extend(as_records)

        # Enrich each review with sector and country from config
        for r in all_records:
            r["sector"] = app.get("sector")
            r["country"] = app.get("country", COUNTRY_CODE)

        upsert_appstore_reviews(all_records)
        logger.info(
            f"✅ Completed: {app['brand_name']} — {len(all_records)} total records"
        )


if __name__ == "__main__":
    main()
