"""One-off (re-runnable) brand logo fetch → Supabase Storage + brand_assets.

Logos are stored ONCE PER BRAND in the public `brand-logos` bucket and listed in
`public.brand_assets`; the ReviewIQ app shows them via <BrandMark> and falls
back to a monogram for any brand without one.

Domains come from brand_domains.csv (brand,domain,status). Every row starts as
"suggested" — review it: a wrong domain means a wrong logo on a client screen.

For each brand the script tries, in order:
  0. an explicit `logo_url` in brand_domains.csv (paste a known-good image URL)
  1. the web-app manifest icons and apple-touch-icon / icon <link> tags on the
     brand's homepage (bare domain, then www.), largest first
  2. /apple-touch-icon.png
  3. Google's high-res favicon service (256px), then its 128px one, then
     DuckDuckGo's — script-time only; the app never calls any of them
It keeps the first image that is at least MIN_SIZE px, pads it to a square,
resizes to 128×128 and saves WebP. SVG is only used if cairosvg is installed,
and is rasterised — never stored (an SVG can carry script).

Guards (added after the first dry run, 2026-09-11):
  - REDIRECTED SITES ARE SKIPPED. foschini.co.za, markham.co.za, sportscene.co.za
    and totalsports.co.za all redirect to bash.com, so every one of them "got"
    the Bash logo. A homepage that lands on a different domain is reported,
    not used — fix those with --file or a logo_url.
  - Browser-like request headers: several large SA brand sites refuse
    requests that don't look like a browser.
  - Every run writes logo_report.csv (what happened per brand and why), and a
    dry run also writes _review/contact_sheet.png to eyeball in one go.

Usage (from core/):
    python fetch_brand_logos.py --dry-run            # downloads to ./logo_preview/, uploads nothing
    python fetch_brand_logos.py                      # upload + write brand_assets
    python fetch_brand_logos.py --brand KFC          # just one brand
    python fetch_brand_logos.py --missing-only       # skip brands that already have a logo
    python fetch_brand_logos.py --brand "Karreekloof Safari Lodge" --file ~/Downloads/karreekloof.png   # manual
"""
import argparse
import csv
import hashlib
import io
import os
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests
from PIL import Image

from platform_upsert import supabase

BUCKET = "brand-logos"
OUT_SIZE = 128
MIN_SIZE = 64          # below this a favicon looks like mush on a retina tile
TIMEOUT = 15
UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/*,*/*;q=0.8",
    "Accept-Language": "en-ZA,en;q=0.9",
}
try:
    import cairosvg  # optional: lets SVG-only brands work (rasterised, never stored as SVG)
except Exception:
    cairosvg = None
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "brand"


def is_svg_ref(href: str, typ: str = "") -> bool:
    return href.lower().split("?")[0].endswith(".svg") or "svg" in (typ or "")


class IconLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.icons = []  # (score, href)
        self.manifest = None

    def handle_starttag(self, tag, attrs):
        if tag != "link":
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        rel = a.get("rel", "").lower()
        href = a.get("href")
        if href and "manifest" in rel:
            self.manifest = href
            return
        if not href or "icon" not in rel or "mask-icon" in rel:
            return
        if is_svg_ref(href, a.get("type", "")):
            if cairosvg:
                self.icons.append((900, href))   # vector: scales to any size
            return
        size = 0
        m = re.search(r"(\d+)x(\d+)", a.get("sizes", ""))
        if m:
            size = int(m.group(1))
        elif "apple-touch-icon" in rel:
            size = 180
        self.icons.append((size + (1000 if "apple-touch-icon" in rel else 0), href))


def registered(host: str) -> str:
    host = (host or "").lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def candidates(domain: str, notes: list):
    """Yield (source, url). Appends human-readable reasons to `notes`."""
    for host in dict.fromkeys([domain, domain if domain.startswith("www.") else f"www.{domain}"]):
        try:
            r = requests.get(f"https://{host}/", headers=UA, timeout=TIMEOUT, allow_redirects=True)
        except requests.RequestException as e:
            notes.append(f"{host}: unreachable ({e.__class__.__name__})")
            continue
        final = registered(urlparse(r.url).netloc)
        if final != registered(domain):
            notes.append(f"{host}: redirects to {final} — not this brand's own site")
            return  # the icon there belongs to the redirect target (the Bash/TFG case)
        if not r.ok:
            notes.append(f"{host}: HTTP {r.status_code}")
            continue
        if "html" not in r.headers.get("content-type", ""):
            notes.append(f"{host}: not HTML")
            continue
        p = IconLinks()
        p.feed(r.text[:500_000])
        if p.manifest:
            try:
                m = requests.get(urljoin(r.url, p.manifest), headers=UA, timeout=TIMEOUT).json()
                icons = []
                for ic in m.get("icons", []) or []:
                    src = ic.get("src")
                    if not src or (is_svg_ref(src, ic.get("type", "")) and not cairosvg):
                        continue
                    sizes = [int(x.split("x")[0]) for x in str(ic.get("sizes", "")).split() if "x" in x and x.split("x")[0].isdigit()]
                    icons.append((max(sizes or [0]), src))
                for _, src in sorted(icons, reverse=True):
                    yield ("manifest", urljoin(r.url, src))
            except Exception:
                notes.append(f"{host}: manifest unreadable")
        for _, href in sorted(p.icons, reverse=True):
            yield ("apple-touch-icon" if "apple" in href.lower() else "site-icon", urljoin(r.url, href))
        yield ("site-icon", urljoin(r.url, "/apple-touch-icon.png"))
        break
    yield ("google-hires", f"https://t1.gstatic.com/faviconV2?client=SOCIAL&type=FAVICON&fallback_opts=TYPE,SIZE,URL&url=https://{domain}&size=256")
    yield ("google-s2", f"https://www.google.com/s2/favicons?domain={domain}&sz=128")
    yield ("duckduckgo", f"https://icons.duckduckgo.com/ip3/{domain}.ico")


def load_image(data: bytes, url: str = ""):
    head = data[:512].lstrip().lower()
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in data[:2048].lower()):
        if not cairosvg:
            raise ValueError("svg without cairosvg")
        data = cairosvg.svg2png(bytestring=data, output_width=256, output_height=256)
    img = Image.open(io.BytesIO(data))
    if getattr(img, "n_frames", 1) > 1:  # .ico with several sizes → take the largest
        best = None
        for i in range(img.n_frames):
            img.seek(i)
            if best is None or img.size[0] > best.size[0]:
                best = img.copy()
        img = best
    return img.convert("RGBA")


def normalise(img: Image.Image) -> bytes:
    w, h = img.size
    side = max(w, h)
    canvas = Image.new("RGBA", (side, side), (255, 255, 255, 0))
    canvas.paste(img, ((side - w) // 2, (side - h) // 2), img)
    canvas = canvas.resize((OUT_SIZE, OUT_SIZE), Image.LANCZOS)
    buf = io.BytesIO()
    canvas.save(buf, "WEBP", quality=90, method=6)
    return buf.getvalue()


def clean_image_url(url: str) -> str:
    """Accept what people actually paste: a Google Images result link
    (google.com/imgres?imgurl=...) is unwrapped to the image itself, and a
    Cloudflare image-resizing prefix (/cdn-cgi/image/<opts>/) is dropped so we
    get the original file rather than an auto-converted format."""
    from urllib.parse import parse_qs
    u = urlparse(url.strip())
    if "google." in u.netloc and u.path.startswith("/imgres"):
        inner = parse_qs(u.query).get("imgurl", [""])[0]
        if inner:
            url, u = inner, urlparse(inner)
    m = re.match(r"^/cdn-cgi/image/[^/]+(/.*)$", u.path)
    if m:
        url = f"{u.scheme}://{u.netloc}{m.group(1)}"
    return url


def fetch_url(source: str, url: str, notes: list):
    url = clean_image_url(url)
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT)
        if not r.ok or len(r.content) < 200:
            notes.append(f"{source}: HTTP {r.status_code}" if not r.ok else f"{source}: empty")
            return None
        img = load_image(r.content, url)
    except Exception as e:
        notes.append(f"{source}: unreadable ({e.__class__.__name__})")
        return None
    if min(img.size) < MIN_SIZE:
        notes.append(f"{source}: only {img.size[0]}px")
        return None
    return img


def fetch_logo(domain: str, direct_url: str = ""):
    notes = []
    if direct_url:
        img = fetch_url("logo_url", direct_url, notes)
        if img is not None:
            return "logo_url", img, notes
    for source, url in candidates(domain, notes):
        img = fetch_url(source, url, notes)
        if img is not None:
            return source, img, notes
        if notes and "redirects to" in notes[-1]:
            break
    return None, None, notes


def upload(brand: str, domain: str, source: str, webp: bytes, width: int, dry_run: bool):
    digest = hashlib.sha256(webp).hexdigest()
    path = f"{slug(brand)}-{digest[:10]}.webp"     # versioned name → safe to cache forever
    if dry_run:
        os.makedirs("logo_preview", exist_ok=True)
        with open(os.path.join("logo_preview", path), "wb") as f:
            f.write(webp)
        return path
    supabase.storage.from_(BUCKET).upload(
        path, webp, {"content-type": "image/webp", "cache-control": "31536000", "upsert": "true"},
    )
    supabase.table("brand_assets").upsert({
        "brand": brand,
        "logo_path": path,
        "logo_url": f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{path}",
        "source": source,
        "source_domain": domain,
        "width": width,
        "bytes": len(webp),
        "sha256": digest,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).execute()
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="brand_domains.csv")
    ap.add_argument("--brand")
    ap.add_argument("--file", help="Manual logo file for --brand (PNG/JPG/WebP)")
    ap.add_argument("--missing-only", action="store_true")
    # A targeted re-run: the brands that need attention (no logo stored, or a
    # stored logo under 64px) are written to logo_worklist.csv, so one run can
    # cover exactly those instead of 70-odd --brand invocations.
    ap.add_argument("--worklist", nargs="?", const="logo_worklist.csv",
                    help="Only process brands listed in this CSV's `brand` column "
                         "(default logo_worklist.csv)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.file:
        if not args.brand:
            raise SystemExit("❌ --file needs --brand")
        img = load_image(open(os.path.expanduser(args.file), "rb").read())
        webp = normalise(img)
        path = upload(args.brand, "", "manual", webp, img.size[0], args.dry_run)
        print(f"✅ {args.brand}: manual logo → {path} ({len(webp):,} bytes)")
        return

    rows = [r for r in csv.DictReader(open(args.csv)) if (r.get("domain") or "").strip()]
    if args.worklist:
        wanted = {(r.get("brand") or "").strip().lower()
                  for r in csv.DictReader(open(args.worklist))}
        if not wanted:
            raise SystemExit(f"❌ {args.worklist} lists no brands")
        before = len(rows)
        rows = [r for r in rows if r["brand"].strip().lower() in wanted]
        skipped = sorted(wanted - {r["brand"].strip().lower() for r in rows})
        print(f"Worklist {args.worklist}: {len(rows)} of {before} brands selected"
              + (f"; {len(skipped)} listed but have no domain in {args.csv}: "
                 + ", ".join(skipped) if skipped else ""))
    if args.brand:
        rows = [r for r in rows if r["brand"].strip().lower() == args.brand.strip().lower()]
        if not rows:
            raise SystemExit(f"❌ {args.brand} has no domain in {args.csv}")
    have = set()
    if args.missing_only and not args.dry_run:
        have = {r["brand"] for r in supabase.table("brand_assets").select("brand").not_.is_("logo_url", "null").execute().data}

    if args.dry_run and not args.brand and os.path.isdir("logo_preview"):
        import shutil
        shutil.rmtree("logo_preview")   # stale previews would pollute the contact sheet
    cache, ok, failed, total_bytes, report = {}, 0, [], 0, []
    for r in rows:
        brand, domain = r["brand"].strip(), r["domain"].strip().lower()
        direct = (r.get("logo_url") or "").strip()
        if brand in have:
            continue
        print(f"• {brand} ({domain})")
        key = (domain, direct)
        if key not in cache:          # brands sharing a domain (Discovery Bank/Insure) fetch once
            source, img, notes = fetch_logo(domain, direct)
            cache[key] = (source, img, normalise(img) if img else None, notes)
        source, img, webp, notes = cache[key]
        if not webp:
            why = "; ".join(notes[-3:]) or "no candidate"
            print(f"    ✗ {why}")
            failed.append(brand)
            report.append({"brand": brand, "domain": domain, "result": "monogram", "source": "", "source_px": "", "reason": why})
            continue
        path = upload(brand, domain, source, webp, img.size[0], args.dry_run)
        ok += 1
        total_bytes += len(webp)
        low = img.size[0] < 128
        print(f"    ✓ {source}, source {img.size[0]}px{' (low-res)' if low else ''} → {path} ({len(webp):,} bytes)")
        report.append({"brand": brand, "domain": domain, "result": "logo", "source": source,
                       "source_px": img.size[0], "reason": "low-res source — check it looks sharp" if low else ""})

    with open("logo_report.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["brand", "domain", "result", "source", "source_px", "reason"])
        w.writeheader()
        w.writerows(report)

    if args.dry_run and ok:
        contact_sheet()

    print(f"\n{ok} logos {'previewed in ./logo_preview' if args.dry_run else 'stored'}, "
          f"{total_bytes / 1024:.0f} KB total ({(total_bytes / max(ok, 1)) / 1024:.1f} KB avg)")
    print("Per-brand results and reasons: logo_report.csv")
    if args.dry_run and ok:
        print("Eyeball them all at once: _review/contact_sheet.png")
    if failed:
        print(f"No usable logo for {len(failed)} — see logo_report.csv; fix with a logo_url column or --file.")
    no_domain = [r["brand"] for r in csv.DictReader(open(args.csv)) if not (r.get("domain") or "").strip() and r.get("status") != "skip"]
    if no_domain and not args.brand:
        print(f"Need a domain in {args.csv}: {', '.join(no_domain)}")


def contact_sheet():
    from PIL import ImageDraw
    files = sorted(f for f in os.listdir("logo_preview") if f.endswith(".webp"))
    cols, cell, lab = 9, 128, 28
    rows = (len(files) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (cell + 8), rows * (cell + lab + 8)), "white")
    d = ImageDraw.Draw(sheet)
    for i, f in enumerate(files):
        im = Image.open(os.path.join("logo_preview", f)).convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        bg.alpha_composite(im)
        x, y = (i % cols) * (cell + 8) + 4, (i // cols) * (cell + lab + 8) + 4
        sheet.paste(bg.convert("RGB"), (x, y))
        d.text((x, y + cell + 2), f.rsplit("-", 1)[0][:20], fill="black")
    os.makedirs("_review", exist_ok=True)
    sheet.save(os.path.join("_review", "contact_sheet.png"))


if __name__ == "__main__":
    main()
