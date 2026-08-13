import time
from datetime import datetime
from google_play_scraper import Sort, reviews
from loguru import logger


def fetch_google_play_reviews(app_id: str, brand_name: str, country: str = "za",
                               lang: str = "en", count: int = 50,
                               min_date: str = None) -> list:
    logger.info(f"[Google Play] Scraping: {brand_name} | {app_id}")
    results = []
    cutoff = datetime.fromisoformat(min_date) if min_date else None
    skipped = 0

    try:
        raw_reviews, _ = reviews(
            app_id,
            lang=lang,
            country=country,
            sort=Sort.NEWEST,
            count=count,
        )

        for r in raw_reviews:
            if cutoff and r.get("at") and r["at"] < cutoff:
                skipped += 1
                continue
            results.append({
                "source":           "google_play",
                "brand_name":       brand_name,
                "external_app_id":  app_id,
                "review_id":        r.get("reviewId", ""),
                "author_name":      r.get("userName", ""),
                "rating":           r.get("score"),
                "review_title":     None,
                "review_text":      r.get("content", ""),
                "review_date":      r.get("at").isoformat() if r.get("at") else None,
                "app_version":      r.get("reviewCreatedVersion", ""),
                "thumbs_up":        r.get("thumbsUpCount", 0),
                "developer_reply":  r.get("replyContent", ""),
                "country":          country.upper(),
                "sentiment_label":  None,
            })

        logger.success(f"[Google Play] {len(results)} reviews fetched for {brand_name}"
                       + (f" ({skipped} skipped, older than {min_date})" if skipped else ""))

    except Exception as e:
        logger.error(f"[Google Play] Failed for {brand_name} ({app_id}): {e}")

    time.sleep(2)
    return results
