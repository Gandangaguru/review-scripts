# ReviewIQ review crawlers

Single home for the scripts that keep `businesses`/`reviews` in Supabase
(project `skhfzgdbwwbdtgwaosox`) up to date. All scrapers write to the same
canonical tables — no `platform_reviews`, that table is retired.

Live at: `github.com/Gandangaguru/review-scripts`

## Status

| Source | Location | Cadence | Status |
|---|---|---|---|
| HelloPeter | `core/main.py` | Weekly (Mon) | **Confirmed working** — first run added 3,315 new reviews |
| Takealot | `core/takealot_scraper.py` | Weekly (Mon) | **Confirmed working** — first run added 5 new reviews |
| Google Play | `appstores/scrapers/google_play_scraper.py` | Weekly (Mon) | **Confirmed working** — first run added 787 new reviews |
| Google Places | `core/crawl_google_places.py` (via Apify) | Monthly (1st) | **Confirmed working** — recovered a manually-triggered Apify run via `--dataset-id`, adding 7,542 new reviews. Scheduled monthly run uses the same code path. |
| Apple App Store | `appstores/scrapers/apple_store_scraper.py` | **On hold** | Relied on scraping an undocumented auth token out of Apple's page/JS bundles; Apple changed that structure and it now fails for every app. Disabled in `run_appstore_pipeline.py` (commented out, not deleted) so the weekly run doesn't waste time on it. Revisit if a working approach is found. |
| Autotrader (dealer reviews) | `core/autotrader_scraper.py` | **On hold** | Code + `autotrader_dealers` table exist and work, but the Playwright headless-browser approach (~148 dealer pages + every dealer's review page) is slow/costly. `weekly-autotrader-crawl.yml` has no schedule trigger — manual-only until a more efficient approach (e.g. an underlying API, like HelloPeter/Takealot use) is found. |
| Tripadvisor / Booking.com / Airbnb / Hotels.com | `reviewiq-hospitality` (separate folder, not moved here) | — | **Explicitly paused in code**, target tables don't exist in Supabase yet. Not wired in. Revisit as its own project. |
| Cars.co.za dealer reviews (separate service) | `cars-review-ingestion` (separate folder, not moved here) | — | **Out of scope by request.** Different architecture (FastAPI + Redis worker + Playwright), untested against production DB, unverified selectors. Not the same as Autotrader above. |

## Setup (done)

Repo is pushed, secrets (`SUPABASE_URL`, `SUPABASE_KEY`, `APIFY_TOKEN`) are set
in the GitHub repo's Settings → Secrets and variables → Actions, and every
active source (HelloPeter, Takealot, Google Play, Google Places) has been
confirmed to actually write data. Nothing left to configure — it now runs on
schedule: weekly Mondays for the first three, monthly on the 1st for Google
Places.

`core/crawl_google_places.py` also accepts `--dataset-id <id>` to ingest an
already-finished Apify dataset instead of starting a new run — useful if a
crawl is ever triggered manually from the Apify console outside this repo's
schedule. Needs `core/.env` locally with `SUPABASE_URL`, `SUPABASE_KEY`,
`APIFY_TOKEN` matching **the Apify account the run actually happened under**
(a token from a different account will 401 even with the right dataset ID).

## Structure

```
core/                    HelloPeter, Takealot, Google Places, Autotrader — share platform_upsert.py
  main.py                HelloPeter
  takealot_scraper.py    Takealot
  crawl_google_places.py Google Places (triggers a fresh Apify run each month)
  autotrader_scraper.py  Autotrader dealer reviews (on hold — Playwright headless browser)
  platform_upsert.py     shared Supabase writer (dedup, business lookup/creation)
  config_businesses.py   HelloPeter brand list

appstores/                Google Play (+ Apple App Store, on hold)
  run_appstore_pipeline.py
  config_apps.py          app list + IDs
  scrapers/                google_play_scraper.py, apple_store_scraper.py (unused for now)
  pipeline/supabase_upsert.py

.github/workflows/
  weekly-review-crawl.yml         HelloPeter + Takealot + Google Play, Mondays
  weekly-autotrader-crawl.yml     Autotrader — ON HOLD, manual trigger only, no schedule
  monthly-google-places-crawl.yml Google Places, 1st of the month
```

## Old folders

The originals (`reviewiq-hellopeter-scraper`, `reviewiq-appstores`) still
exist on disk but are now redundant — everything here is a clean copy with
the same fixes (rolling review-date windows instead of hardcoded cutoffs,
Google Places actually re-crawling instead of re-reading a stale dataset).
Safe to archive/delete once you've confirmed this location works.
