"""Discover every South African branch of a brand on Google Maps and register
each one as its own row in `businesses` (brand + branch + city + province +
google_place_id).

Why: branch intelligence (ReviewIQ Analytics, one brand in view) compares a
brand's branches, cities and provinces against each other. That is only as
good as branch coverage — on 2026-09-11 KFC had 5 tracked branches, all in the
Western Cape. This script builds the footprint; crawl_google_places.py then
pulls each branch's reviews into that branch's own row.

Usage (from core/):
    python discover_brand_branches.py --brand KFC --dry-run      # see what it finds, writes a CSV, saves nothing
    python discover_brand_branches.py --brand KFC                # register new branches
    python crawl_google_places.py --brand KFC                       # last 31 days of reviews for them

Interrupted, or Apify refused a start? Run the same command again. Every run is
recorded in core/apify_runs/ the moment it starts (see apify_runs.py), so
finished provinces are reused, not paid for twice. A --dry-run keeps that record
too, so the real run afterwards reuses the dry run's datasets. --fresh ignores it.

Cost: one Apify Google Maps Scraper run, places only (no reviews in this step),
one search per province. Check the Apify console for the run's actual cost.
"""
import argparse
import csv
import re
from datetime import datetime, timezone


import apify_runs
from crawl_google_places import APIFY_TOKEN, ACTOR_ID, POLL_SECONDS, check_apify_token, fetch_dataset_items
from platform_upsert import supabase

PROVINCES = [
    "Gauteng", "Western Cape", "KwaZulu-Natal", "Eastern Cape", "Limpopo",
    "Mpumalanga", "Free State", "North West", "Northern Cape",
]
PROVINCE_ALIASES = {
    "kwazulu natal": "KwaZulu-Natal", "kzn": "KwaZulu-Natal", "gp": "Gauteng",
    "wc": "Western Cape", "ec": "Eastern Cape", "fs": "Free State", "nw": "North West",
    "nc": "Northern Cape", "lp": "Limpopo", "mp": "Mpumalanga", "north-west": "North West",
}
RUN_TIMEOUT_MINUTES = 120


def canonical_province(state: str) -> str | None:
    s = (state or "").strip()
    if not s:
        return None
    for p in PROVINCES:
        if s.lower() == p.lower():
            return p
    return PROVINCE_ALIASES.get(s.lower().replace("-", " ").strip()) or PROVINCE_ALIASES.get(s.lower())


def title_matches(title: str, brand: str, aliases: list[str]) -> bool:
    """Word-boundary match: "KFC" matches "KFC Cresta" but not "KFCX Lounge".
    A common-word brand ("Game") can still match an unrelated listing ("Royal
    Game Guesthouse"), so check the category column in the dry-run CSV before
    saving for such brands."""
    t = (title or "").lower()
    return any(re.search(rf"(^|\W){re.escape(a.lower())}(\W|$)", t) for a in [brand, *aliases])


def branch_name_from(title: str, brand: str, aliases: list[str], city: str) -> str:
    name = title or ""
    for a in sorted([brand, *aliases], key=len, reverse=True):
        name = re.sub(rf"^\s*{re.escape(a)}\b[\s\-–|,:]*", "", name, flags=re.I)
    name = name.strip(" -–|,:")
    return name or (city or "").strip() or title


def discovery_bodies(search: str, max_per_search: int, provinces: list[str]) -> dict:
    """One Apify run body per province: a single country-wide search stops at
    the few hundred results Google will show for one query."""
    return {
        province: {
            "searchStringsArray": [search],
            "locationQuery": f"{province}, South Africa",
            "maxCrawledPlacesPerSearch": max_per_search,
            "language": "en",
            "countryCode": "za",
            "maxReviews": 0,
            "maxImages": 0,
            "scrapeContacts": False,
            "skipClosedPlaces": True,
        }
        for province in provinces
    }


def job_name(brand: str) -> str:
    return "discover_" + re.sub(r"[^A-Za-z0-9]+", "_", brand).strip("_")


def existing_place_ids() -> set[str]:
    out, offset = set(), 0
    while True:
        rows = supabase.table("businesses").select("settings").range(offset, offset + 999).execute().data
        for r in rows:
            pid = (r.get("settings") or {}).get("google_place_id")
            if pid:
                out.add(pid)
        if len(rows) < 1000:
            break
        offset += 1000
    return out


def brand_industry(brand: str) -> str | None:
    rows = (supabase.table("businesses").select("industry").ilike("brand", brand)
            .not_.is_("industry", "null").limit(1).execute().data)
    return rows[0]["industry"] if rows else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", required=True, help='Brand as stored in businesses.brand, e.g. "KFC"')
    ap.add_argument("--search", help="Google Maps search text (default: the brand)")
    ap.add_argument("--alias", action="append", default=[], help='Other names on listings, e.g. --alias "Kentucky Fried Chicken"')
    ap.add_argument("--industry", help="Industry label if the brand has no existing row (must exist in industry_labels)")
    ap.add_argument("--max-per-search", type=int, default=500)
    ap.add_argument("--dataset-id", action="append", default=[], help="Re-use finished discovery dataset(s) instead of new runs")
    ap.add_argument("--provinces", help='Comma-separated subset, e.g. "Limpopo,Free State" (default: all 9)')
    ap.add_argument("--max-concurrent", type=int, default=2, help="Apify runs at once (default 2; Apify plan memory caps this)")
    ap.add_argument("--fresh", action="store_true", help="Ignore saved progress in core/apify_runs/ and start new runs")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    check_apify_token()
    brand = args.brand.strip()
    industry = brand_industry(brand) or args.industry
    if not industry:
        raise SystemExit(f"❌ No existing row for {brand} to take an industry from — pass --industry.")

    items = []
    if args.dataset_id:
        for d in args.dataset_id:
            items += fetch_dataset_items(d)
    else:
        provinces = PROVINCES
        if args.provinces:
            provinces = [canonical_province(p) for p in args.provinces.split(",")]
            if None in provinces:
                raise SystemExit(f"❌ Unknown province in --provinces. Use: {', '.join(PROVINCES)}")
        job = job_name(brand)
        if args.fresh:
            apify_runs.discard(job)
        print(f"🔎 Discovering {brand} branches across {len(provinces)} province(s)…")
        datasets = apify_runs.run_jobs(
            APIFY_TOKEN, ACTOR_ID, job,
            discovery_bodies(args.search or brand, args.max_per_search, provinces),
            max_concurrent=args.max_concurrent, poll_seconds=POLL_SECONDS,
            timeout_minutes=RUN_TIMEOUT_MINUTES,
        )
        for province, dataset_id in datasets.items():
            if not dataset_id:
                print(f"  ⚠️ {province}: no results — skipped (run the same command again to retry)")
                continue
            got = fetch_dataset_items(dataset_id)
            print(f"  📦 {province}: {len(got)} places (dataset {dataset_id})")
            items += got

    known = existing_place_ids()
    seen, new_rows, skipped = set(), [], {"not_brand": 0, "not_za": 0, "closed": 0, "known": 0, "dup": 0}
    for it in items:
        pid = it.get("placeId")
        title = it.get("title") or ""
        if not pid or pid in seen:
            skipped["dup"] += 1
            continue
        seen.add(pid)
        if not title_matches(title, brand, args.alias):
            skipped["not_brand"] += 1
            continue
        if (it.get("countryCode") or "").upper() not in ("ZA", ""):
            skipped["not_za"] += 1
            continue
        if it.get("permanentlyClosed"):
            skipped["closed"] += 1
            continue
        if pid in known:
            skipped["known"] += 1
            continue
        city = (it.get("city") or "").strip() or None
        new_rows.append({
            "name": title,
            "brand": brand,
            "branch_name": branch_name_from(title, brand, args.alias, city),
            "city": city,
            "province": canonical_province(it.get("state")),
            "industry": industry,
            "country": "ZA",
            "currency": "ZAR",
            "settings": {
                "google_place_id": pid,
                "maps_url": it.get("url"),
                "address": it.get("address"),
                "lat": (it.get("location") or {}).get("lat"),
                "lng": (it.get("location") or {}).get("lng"),
                "google_rating": it.get("totalScore"),
                "google_reviews_count": it.get("reviewsCount"),
                "category": it.get("categoryName"),
                "discovered_via": "apify-discovery",
                "discovered_at": datetime.now(timezone.utc).isoformat(),
            },
        })

    out = f"discovered_{re.sub(r'[^A-Za-z0-9]+', '_', brand)}.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "branch_name", "city", "province", "category", "google_place_id", "google_reviews_count", "address"])
        for r in new_rows:
            s = r["settings"]
            w.writerow([r["name"], r["branch_name"], r["city"], r["province"], s.get("category"), s["google_place_id"], s["google_reviews_count"], s["address"]])

    by_prov = {}
    for r in new_rows:
        by_prov[r["province"] or "Unknown"] = by_prov.get(r["province"] or "Unknown", 0) + 1
    print(f"\n{len(new_rows)} new {brand} branches · already tracked: {skipped['known']} · "
          f"skipped: {skipped['not_brand']} other businesses, {skipped['closed']} closed, {skipped['not_za']} outside SA, {skipped['dup']} duplicates")
    for p, c in sorted(by_prov.items(), key=lambda x: -x[1]):
        print(f"  {p:<16} {c}")
    print(f"Review list written to {out}")

    if args.dry_run:
        print("Dry run — nothing saved.")
        return
    for i in range(0, len(new_rows), 100):
        supabase.table("businesses").insert(new_rows[i:i + 100]).execute()
    if not args.dataset_id:
        apify_runs.mark_done(job_name(brand))
    print(f"🎉 Registered {len(new_rows)} branches. Next: python crawl_google_places.py --brand \"{brand}\"")


if __name__ == "__main__":
    main()
