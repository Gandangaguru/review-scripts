# ReviewIQ review crawlers

Single home for the scripts that keep `businesses`/`reviews` in Supabase
(project `skhfzgdbwwbdtgwaosox`) up to date. All scrapers write to the same
canonical tables — no `platform_reviews`, that table is retired.

## Status

| Source | Location | Cadence | Status |
|---|---|---|---|
| HelloPeter | `core/main.py` | Weekly (Mon) | Ready |
| Takealot | `core/takealot_scraper.py` | Weekly (Mon) | Ready |
| Google Places | `core/crawl_google_places.py` (via Apify) | Monthly (1st) | Ready |
| Google Play | `appstores/scrapers/google_play_scraper.py` | Weekly (Mon) | Ready |
| Apple App Store | `appstores/scrapers/apple_store_scraper.py` | Weekly (Mon) | Ready |
| Autotrader (dealer reviews) | `core/autotrader_scraper.py` | **On hold** | Code + `autotrader_dealers` table exist and work, but the Playwright headless-browser approach (~148 dealer pages + every dealer's review page) is slow/costly. Workflow (`weekly-autotrader-crawl.yml`) has no schedule trigger — manual-only until a more efficient approach (e.g. an underlying API, like HelloPeter/Takealot use) is found. |
| Tripadvisor / Booking.com / Airbnb / Hotels.com | `reviewiq-hospitality` (separate folder, not moved here) | — | **Explicitly paused in code**, target tables don't exist in Supabase yet. Not wired in. Revisit as its own project. |
| Cars.co.za dealer reviews (separate service) | `cars-review-ingestion` (separate folder, not moved here) | — | **Out of scope by request.** Different architecture (FastAPI + Redis worker + Playwright), untested against production DB, unverified selectors. Not the same as Autotrader above. |

## What's blocking automation right now

Nothing runs on a schedule until this repo is pushed to GitHub — that step
can't be done from here (the sandbox this was built in can't reliably run
git against a synced folder). From your own Terminal:

```bash
cd ~/reviewiq-scripts
git init
git add .
git commit -m "Weekly/monthly review crawl automation"
```

Then create an empty GitHub repo and:

```bash
git remote add origin <your repo URL>
git branch -M main
git push -u origin main
```

In the GitHub repo → **Settings → Secrets and variables → Actions**, add:
- `SUPABASE_URL`
- `SUPABASE_KEY`
- `APIFY_TOKEN` (only used by the monthly Google Places workflow)

Copy the values from your local `.env` files — don't paste them anywhere else.

Once pushed, use the **Actions** tab → pick a workflow → **Run workflow** to
test manually before waiting for the schedule.

## Structure

```
core/                    HelloPeter, Takealot, Google Places, Autotrader — share platform_upsert.py
  main.py                HelloPeter
  takealot_scraper.py    Takealot
  crawl_google_places.py Google Places (triggers a fresh Apify run each month)
  autotrader_scraper.py  Autotrader dealer reviews (Playwright headless browser)
  platform_upsert.py     shared Supabase writer (dedup, business lookup/creation)
  config_businesses.py   HelloPeter brand list

appstores/                Google Play + Apple App Store
  run_appstore_pipeline.py
  config_apps.py          app list + IDs
  scrapers/                google_play_scraper.py, apple_store_scraper.py
  pipeline/supabase_upsert.py

.github/workflows/
  weekly-review-crawl.yml         HelloPeter + Takealot + Google Play + Apple, Mondays
  weekly-autotrader-crawl.yml     Autotrader, Mondays (separate job — much longer runtime)
  monthly-google-places-crawl.yml Google Places, 1st of the month
```

## Old folders

The originals (`reviewiq-hellopeter-scraper`, `reviewiq-appstores`) still
exist on disk but are now redundant — everything here is a clean copy with
the same fixes (rolling review-date windows instead of hardcoded cutoffs,
Google Places actually re-crawling instead of re-reading a stale dataset).
Safe to archive/delete once you've confirmed this location works.
