"""HelloPeter scraper for the 2026-10 site rebuild.

HelloPeter dropped the public JSON API (api.hellopeter.com/consumer/...) that main.py used to call.
Reviews now arrive two ways, both in Next.js "flight" (RSC) format:
  1. embedded in the business page HTML (the newest ~8 reviews), inside self.__next_f.push([1,"..."]) calls;
  2. as the response to a POST (a Next server action) when the "Next" button is pressed.
So this drives a real browser (Playwright), reads the first page, then presses "Next" and reads each response
until it reaches reviews older than the cutoff. Nothing here depends on the build-specific server-action id.
"""
import hashlib
import json
import os
import re
from datetime import datetime


_PUSH = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')
_TEXT_ROW = re.compile(r'(?m)(?:^|(?<=\n))([0-9a-f]+):T([0-9a-f]+),')
_REVIEW_OBJ = re.compile(r'\{"id":\s*"[0-9a-f\-]{36}"')
_DECODER = json.JSONDecoder()
DEBUG = bool(os.getenv("HP_DEBUG"))


def stream_from_html(html: str) -> str:
    """Join the flight chunks embedded in a page's HTML."""
    return "".join(json.loads(m.group(1)) for m in _PUSH.finditer(html))


def _text_refs(stream: str) -> dict:
    """Long strings are sent out of line as `<ref>:T<hex byte length>,<text>`; map ref -> text."""
    refs = {}
    for m in _TEXT_ROW.finditer(stream):
        n = int(m.group(2), 16)
        raw = stream[m.end():m.end() + n + 8].encode("utf-8")[:n]
        refs[m.group(1)] = raw.decode("utf-8", errors="ignore")
    return refs


def parse_reviews(stream: str) -> list:
    """Every review object found in a flight stream, with `$ref` strings resolved. Deduped by id."""
    refs = _text_refs(stream)
    found, seen = [], set()

    def take(r):
        if isinstance(r, dict) and r.get("id") and not r.get("createdAtIso") and r.get("submittedAt"):
            r["createdAtIso"] = r["submittedAt"]  # the paging response names the date differently
        if isinstance(r, dict) and r.get("id") and r.get("createdAtIso") and r["id"] not in seen:
            seen.add(r["id"])
            for k in ("content", "title"):
                v = r.get(k)
                if isinstance(v, str) and v.startswith("$") and v[1:] in refs:
                    r[k] = refs[v[1:]]
            found.append(r)

    # Any JSON object that starts with a uuid id and carries a createdAtIso is a review, wherever it sits
    # (the page embeds them under "reviews", the server action may wrap them differently).
    for m in _REVIEW_OBJ.finditer(stream):
        try:
            obj, _ = _DECODER.raw_decode(stream[m.start():])
        except ValueError:
            continue
        take(obj)
    # The paging response (a Next server action) names things differently and its objects do not start
    # with "id". Find each object by its date field and walk back to the brace that opens it.
    for m in re.finditer(r'"submittedAt"', stream):
        lo = max(0, m.start() - 6000)
        for st in [i for i in range(m.start(), lo, -1) if stream[i] == "{"][:80]:
            try:
                obj, end = _DECODER.raw_decode(stream[st:])
            except ValueError:
                continue
            if isinstance(obj, dict) and "submittedAt" in obj and end > m.start() - st:
                obj.setdefault("id", _first(obj, ("id", "reviewId", "review_id", "uuid", "permalink", "slug"))
                               or "hp-" + hashlib.sha1((str(obj["submittedAt"]) + str(obj.get("title")) + str(obj.get("content"))[:80]).encode()).hexdigest()[:20])
                take(obj)
                break
    return found


def _first(d: dict, keys):
    for k in keys:
        if d.get(k):
            return d[k]
    return None


def _reply_text(resp):
    if not resp:
        return None
    if isinstance(resp, str):
        return resp
    if isinstance(resp, dict):
        for k in ("content", "text", "message", "body"):
            if resp.get(k):
                return str(resp[k])
    return None


def to_row(r: dict, business_slug: str, industry: str, brand_name: str):
    from platform_upsert import make_row  # imported here so the parser can be tested without Supabase
    iso = r.get("createdAtIso") or ""
    if not iso:
        return None
    reply = r.get("businessResponse")
    return make_row(
        source="HelloPeter",
        platform_review_id=r["id"],
        brand_name=brand_name,
        reviewer_name=((r.get("reviewer") or {}).get("name") if isinstance(r.get("reviewer"), dict) else None)
        or _first(r, ("authorDisplayName", "authorName", "reviewerName", "displayName", "userName", "author")) or "Anonymous",
        rating=r.get("rating"),
        review_title=r.get("title"),
        review_text=r.get("content") if isinstance(r.get("content"), str) else "",
        review_date=iso[:10],
        review_url=f"https://www.hellopeter.com/{business_slug}/reviews/{_first(r, ('permalink', 'slug', 'id'))}",
        industry=industry,
        platform_response=_reply_text(reply),
        response_at=(reply.get("createdAtIso") if isinstance(reply, dict) else None),
        source_url_exact=True,
    )


def _is_server_action(resp) -> bool:
    """The Next server action behind the 'Next' button; analytics/ad POSTs (often empty 204s) are ignored."""
    req = resp.request
    if req.method != "POST" or "hellopeter.com" not in resp.url:
        return False
    return "next-action" in req.headers or "text/x-component" in (resp.headers.get("content-type") or "")


def scrape_business(page, slug: str, industry: str, brand_name: str, cutoff: datetime, max_clicks: int = 80) -> list:
    """Newest-first: read the page, press Next until the oldest review seen is before `cutoff`."""
    captured = []

    def on_response(resp):
        # Read the body immediately: it is gone once the page re-renders.
        if _is_server_action(resp):
            try:
                captured.append(resp.text())
            except Exception:
                pass

    page.on("response", on_response)
    page.goto(f"https://www.hellopeter.com/{slug}", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_selector('a[href*="/reviews/"]', timeout=30000)
    by_id = {r["id"]: r for r in parse_reviews(stream_from_html(page.content()))}

    def oldest():
        ds = [r["createdAtIso"][:10] for r in by_id.values() if r.get("createdAtIso")]
        return min(ds) if ds else None

    clicks = 0
    while clicks < max_clicks:
        o = oldest()
        if not o or datetime.fromisoformat(o) < cutoff:
            break
        btn = page.get_by_role("button", name="Next")
        if btn.count() == 0 or not btn.first.is_enabled():
            if DEBUG:
                print(f"  [debug] no usable Next button (count={btn.count()})")
            break
        before = len(captured)
        try:
            btn.first.click()
            for _ in range(60):  # up to ~15 s for the paging response to arrive
                if len(captured) > before:
                    break
                page.wait_for_timeout(250)
        except Exception as e:
            print(f"  paging stopped after {clicks} pages: {e}")
            break
        if len(captured) == before:
            print(f"  paging stopped after {clicks} pages: no response to Next")
            break
        body = captured[-1]
        fresh = parse_reviews(body)
        if DEBUG:
            print(f"  [debug] click {clicks + 1}: bytes={len(body)} reviews={len(fresh)}")
            if fresh:
                print(f"  [debug] keys: {sorted(fresh[0].keys())}")
            for m_ in re.finditer(r'(?m)^[0-9a-f]+:[\[{]', body):
                print(f"  [debug] row at {m_.start()}: {body[m_.start():m_.start() + 700]!r}")
                break
            k = body.find('"submittedAt"')
            if k >= 0:
                print(f"  [debug] before submittedAt: {body[max(0, k - 250):k]!r}")
        clicks += 1
        added = 0
        for r in fresh:
            if r["id"] not in by_id:
                by_id[r["id"]] = r
                added += 1
        if not added:
            if DEBUG:
                print("  [debug] response held no new reviews; stopping")
            break
        page.wait_for_timeout(600)

    page.remove_listener("response", on_response)
    rows = []
    for r in by_id.values():
        iso = (r.get("createdAtIso") or "")[:10]
        if iso and datetime.fromisoformat(iso) >= cutoff:
            row = to_row(r, slug, industry, brand_name)
            if row:
                rows.append(row)
    return rows
