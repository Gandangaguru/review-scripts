import json
import re
import time
import urllib.request
from datetime import datetime, timezone
from typing import List, Dict

from loguru import logger

# Apple retired the old customer-reviews RSS feed (it now returns empty for
# all apps). This scraper uses the App Store website's own API instead:
# it loads the app's public page, extracts the embedded API token, then
# pages through reviews.

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
PAGE_SIZE = 20
MAX_PAGES = 25  # safety cap: 25 * 20 = 500 reviews


TOKEN_PATTERNS = [
    r"token%22%3A%22(eyJ[^%]+?)%22",          # URL-encoded "token":"eyJ..."
    r'"token"\s*:\s*"(eyJ[^"]+)"',            # plain JSON "token":"eyJ..."
    r"Bearer\s+(eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)",
    r"(eyJhbGci[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)",  # any JWT
]


def _read(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def _find_token(text: str) -> str | None:
    for pattern in TOKEN_PATTERNS:
        m = re.search(pattern, text)
        if m:
            return m.group(1)
    return None


def _get_token(country: str, app_name: str, app_id: str) -> str:
    url = f"https://apps.apple.com/{country}/app/{app_name}/id{app_id}"
    html = _read(url)

    token = _find_token(html)
    if token:
        return token

    # Newer App Store pages keep the API token inside their JS bundles.
    scripts = re.findall(r'src="(/assets/[^"]+\.js)"', html)
    scripts += re.findall(r'data-src="(/assets/[^"]+\.js)"', html)
    for src in scripts[:5]:
        try:
            token = _find_token(_read(f"https://apps.apple.com{src}"))
            if token:
                return token
        except Exception:
            continue

    raise RuntimeError("could not extract App Store API token from page or JS bundles")


def _fetch_page(country: str, app_id: str, token: str, offset: int) -> dict:
    url = (
        f"https://amp-api.apps.apple.com/v1/catalog/{country}/apps/{app_id}/reviews"
        f"?l=en-GB&offset={offset}&limit={PAGE_SIZE}&platform=web"
        f"&additionalPlatforms=appletv,ipad,iphone,mac"
    )
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "Origin": "https://apps.apple.com",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_apple_store_reviews(
    app_id: str,
    app_name: str,
    brand_name: str,
    country: str = "za",
    count: int = 50,
    min_date: str = None,
) -> List[Dict]:
    """
    Fetch latest reviews from the App Store web API.
    Only returns reviews dated on/after min_date (ISO string), if given.
    """
    logger.info(f"[Apple Store] Scraping: {brand_name} | {app_name} | id={app_id}")
    results: List[Dict] = []
    cutoff = (
        datetime.fromisoformat(min_date).replace(tzinfo=timezone.utc)
        if min_date
        else None
    )
    skipped = 0

    try:
        token = _get_token(country, app_name, app_id)

        offset = 0
        for _ in range(MAX_PAGES):
            if len(results) >= count:
                break
            data = _fetch_page(country, app_id, token, offset)
            entries = data.get("data", [])
            if not entries:
                break

            page_all_old = True
            for e in entries:
                a = e.get("attributes", {})
                raw_date = a.get("date")
                r_date = (
                    datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                    .astimezone(timezone.utc)
                    if raw_date
                    else None
                )
                if cutoff and r_date and r_date < cutoff:
                    skipped += 1
                    continue
                page_all_old = False
                if len(results) >= count:
                    break

                results.append({
                    "source": "apple_store",
                    "brand_name": brand_name,
                    "external_app_id": str(app_id),
                    "review_id": str(e.get("id", "")),
                    "author_name": a.get("userName", ""),
                    "rating": a.get("rating"),
                    "review_title": a.get("title", ""),
                    "review_text": a.get("review", ""),
                    "review_date": r_date.isoformat() if r_date else None,
                    "app_version": "",
                    "thumbs_up": None,
                    "developer_reply": (a.get("developerResponse") or {}).get("body", ""),
                    "country": country.upper(),
                    "sentiment_label": None,
                })

            if page_all_old or not data.get("next"):
                break  # reviews are newest-first; the rest are older
            offset += PAGE_SIZE
            time.sleep(1)

        logger.success(
            f"[Apple Store] {len(results)} reviews fetched for {brand_name}"
            + (f" ({skipped} skipped, older than {min_date})" if skipped else "")
        )

    except Exception as e:
        logger.error(f"[Apple Store] Failed for {brand_name} ({app_name}): {e}")

    time.sleep(2)
    return results
