#!/usr/bin/env python3
"""Official product images from the BRANDS' OWN websites (owner, 16 Oct 2026: authorized dealer for
all brands, "use directly official brand img"). Never marketplace images.

Steps (each a sub-command; the GitHub workflow brand-images.yml runs them in order):

  targets  Read every published shop product (id, SKU, name, brand, current image) -> targets.csv.
  crawl    One brand at a time. robots.txt and the brand's PUBLISHED sitemaps only, through the
           repo's Fetcher (robots rules, >= 6 s per host, honest User-Agent, no search pages).
           Product pages whose URL or title carries one of our model numbers are fetched first,
           then other product-looking pages up to --max-pages. The first refusal (401/403/429,
           captcha page, robots.txt unreadable) stops that brand for the run. For a page that
           matches one of our model numbers its official image(s) are downloaded and checked
           (quality rules below). Results are cached in pages_<brand>.csv so the next run continues.
  plan     Match: a product gets a brand page only if one of its model numbers equals a token of
           that page's title/heading/URL/structured data (certain match), the page names no other
           model of ours (range pages are skipped), and the image passes the quality check and is
           not shared by many pages (site logo/banner). -> plan.csv
  apply    Put the planned images on the shop (WooCommerce downloads them from the brand URL) and
           record the source per product (meta _rte_image_source/_rte_image_url/_rte_image_brand).
  remove   Take one brand's images off again (only images this tool put on), e.g. if it objects.

Quality rule (owner: "clarity and clear, not messy crop"): shorter side >= 600 px, not a banner or
collage shape (long/short <= 1.6), plain border (product not cut off, no busy scene), product fills
a sensible part of the picture. Watermarks cannot be detected reliably; images from the brand's own
site are taken as unwatermarked. An image that fails is skipped, never used.

Which products may change: a product with NO image gets one. The 79 older WEB- products (owner, 16
Oct 2026: "include previous 79 also") get the brand image when their current image fails the same
quality check, or the brand image has at least 1.5x the pixels. Any other product that already has
an image is left alone. Never sends price, stock, status, type or SKU.
"""
from __future__ import annotations

import argparse
import collections
import csv
import io
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

BRANDS = {
    "havells": {"names": ["Havells"], "sites": ["https://www.havells.com"]},
    "legrand": {"names": ["Legrand"], "sites": ["https://www.legrand.co.in"]},
    "polycab": {"names": ["Polycab"], "sites": ["https://polycab.com"]},
    "kei": {"names": ["KEI"], "sites": ["https://www.kei-ind.com"]},
    "rrkabel": {"names": ["RR Kabel"], "sites": ["https://www.rrkabel.com"]},
    # Finolex Cables (wires) and Finolex Industries (pipes, fittings) are separate companies
    "finolex": {"names": ["Finolex"], "sites": ["https://www.finolex.com", "https://www.finolexpipes.com"]},
    "gm": {"names": ["GM"], "sites": ["https://www.gmmodular.com"]},
}
FORBIDDEN = {"regular_price", "sale_price", "price", "stock_status", "stock_quantity", "manage_stock", "type",
             "external_url", "button_text", "status", "sku", "name"}
SKIP_SITEMAP = re.compile(r"blog|news|post|career|investor|media|press|event|author|tag|video|locator|"
                          r"dealer|image|page-sitemap|category|attachment", re.I)
SKIP_PAGE = re.compile(r"/(blog|blogs|news|careers?|investors?|media|press|events?|about|contact|"
                       r"store-locator|dealers?|csr|sustainability|tag|author|policy|privacy|terms)(/|$)|"
                       r"\.(pdf|jpe?g|png|webp|gif|svg|zip)$", re.I)
BAD_IMAGE_URL = re.compile(r"logo|placeholder|banner|favicon|sprite|icon|\.svg|\.gif", re.I)
MIN_SIDE, MAX_RATIO, MIN_PLAIN_BORDER, BIGGER = 600, 1.6, 0.85, 1.5
SHARED_IMAGE_PAGES = 4
PAGE_FIELDS = ["url", "status", "strong", "images", "fetched", "name"]
NAME_STOP = {"buy", "online", "india", "price", "best", "the", "and", "with", "for", "of", "in", "by", "a", "an",
             "product", "products", "details", "shop", "new", "range"}
COLOURS = {"red", "blue", "green", "yellow", "black", "white", "grey", "gray", "brown", "orange", "pink", "ivory",
           "silver", "gold", "beige", "violet", "purple"}
TARGET_FIELDS = ["sku", "id", "brand", "name", "web", "ours", "image_src", "image_id", "has_our_image"]


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", s.upper())


# ---------------------------------------------------------------- model numbers and matching
def codes_for(title: str) -> set:
    """Model numbers in one of our product titles (see import_brand_images.model_codes), plus a
    trailing catalogue number such as 'GM ... Plug Top 16 A, 3002' or 'Finolex ... Reducer, 2201'."""
    from import_brand_images import model_codes
    out = set(model_codes(title))
    m = re.search(r",\s*(\d{4,6})\s*$", title.strip())
    if m:
        out.add(m.group(1))
    return out


def strong_tokens(strong: str) -> set:
    """Tokens of a page's title/heading/URL/structured data, with neighbours joined so that
    '6792 50', 'ahlhgxw-060' or 'HBTM-2' also give 679250, AHLHGXW060, HBTM2."""
    toks = [_norm(t) for t in re.findall(r"[A-Za-z0-9]+", strong)]
    toks = [t for t in toks if t]
    out = set(toks)
    for n in (2, 3):
        for i in range(len(toks) - n + 1):
            out.add("".join(toks[i:i + n]))
    return out


def page_codes(strong: str, all_codes: set) -> set:
    return strong_tokens(strong) & all_codes


def _name_words(s: str) -> list:
    s = re.sub(r"(\d)\.(\d)", r"\1_\2", s.lower())
    return [w for w in re.findall(r"[a-z0-9_]+", s) if w not in NAME_STOP]


def name_match(page_name: str, title: str, brand: str) -> int:
    """Second, weaker route (used only with --allow-name): every word of the brand page's product
    name (brand and filler words left out) is a word of our title, at least 2 words, and no colour
    on the page that our title does not have. Returns the number of words (0 = no match)."""
    if not page_name:
        return 0
    page_name = page_name.split("|")[0].split(" - ")[0]
    bw = set(_name_words(brand))
    words = [w for w in _name_words(page_name) if w not in bw]
    ours = set(_name_words(title))
    if len(words) < 2 or not all(w in ours for w in words):
        return 0
    if any(w in COLOURS and w not in ours for w in words):
        return 0
    return len(words)


# ---------------------------------------------------------------- page parsing
def extract_page(html: str, url: str) -> dict:
    """The strong text (title, h1, og:title, JSON-LD product name/sku/mpn/model, URL path) and the
    official image candidates (JSON-LD product image, og:image, twitter:image, image_src)."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    strong, images = [urlsplit(url).path.replace("-", " ").replace("_", " ").replace("/", " ")], []

    def meta(*names):
        for n in names:
            t = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n})
            if t and t.get("content"):
                yield t["content"].strip()

    if soup.title and soup.title.string:
        strong.append(soup.title.string.strip())
    h1 = soup.find("h1")
    names = []
    if h1:
        strong.append(h1.get_text(" ", strip=True))
        names.append(strong[-1])
    og = list(meta("og:title"))
    strong += og
    for tag in soup.find_all("script", type=re.compile("ld\\+json", re.I)):
        try:
            data = json.loads(tag.string or tag.get_text() or "")
        except ValueError:
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack += node
                continue
            if not isinstance(node, dict):
                continue
            stack += [v for k, v in node.items() if k in ("@graph", "itemListElement", "item", "mainEntity")]
            types = node.get("@type")
            types = types if isinstance(types, list) else [types]
            if "Product" not in types:
                continue
            if isinstance(node.get("name"), str):
                names.insert(0, node["name"])
            for k in ("name", "sku", "mpn", "model", "productID", "gtin13"):
                v = node.get(k)
                if isinstance(v, (str, int)):
                    strong.append(str(v))
            img = node.get("image")
            for v in (img if isinstance(img, list) else [img]):
                if isinstance(v, dict):
                    v = v.get("url") or v.get("contentUrl")
                if isinstance(v, str) and v:
                    images.append(v)
    images += list(meta("og:image:secure_url", "og:image", "twitter:image"))
    link = soup.find("link", rel="image_src")
    if link and link.get("href"):
        images.append(link["href"])
    seen, clean = set(), []
    for u in images:
        u = urljoin(url, u.strip())
        if u.startswith("http") and u not in seen and not BAD_IMAGE_URL.search(urlsplit(u).path):
            seen.add(u)
            clean.append(u)
    name = (names + og + [""])[0]
    return {"strong": " | ".join(s for s in strong if s)[:1500], "images": clean[:4], "name": name[:300]}


# ---------------------------------------------------------------- image quality
def assess(data: bytes) -> dict:
    """Quality check of one image. Returns {"ok", "w", "h", "reason", "white"}."""
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:
        return {"ok": False, "w": 0, "h": 0, "reason": "not an image", "white": False}
    w, h = im.size
    res = {"ok": False, "w": w, "h": h, "reason": "", "white": False}
    if min(w, h) < MIN_SIDE:
        res["reason"] = f"too small ({w}x{h})"
        return res
    if max(w, h) / min(w, h) > MAX_RATIO:
        res["reason"] = f"banner or collage shape ({w}x{h})"
        return res
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, im)
    im = im.convert("RGB")
    im.thumbnail((300, 300))
    tw, th = im.size
    px = im.load()
    f = max(2, int(0.03 * min(tw, th)))
    border = [px[x, y] for y in range(th) for x in range(tw) if x < f or y < f or x >= tw - f or y >= th - f]
    med = tuple(sorted(c[i] for c in border)[len(border) // 2] for i in range(3))

    def far(c):
        return max(abs(c[i] - med[i]) for i in range(3)) > 40

    plain = sum(1 for c in border if not far(c)) / len(border)
    res["white"] = min(med) >= 225
    if plain < MIN_PLAIN_BORDER:
        res["reason"] = "busy background or product cut off at the edge"
        return res
    xs = [x for y in range(th) for x in range(tw) if far(px[x, y])]
    if not xs:
        res["reason"] = "blank image"
        return res
    ys = [y for y in range(th) for x in range(tw) if far(px[x, y])]
    box = (max(xs) - min(xs) + 1) * (max(ys) - min(ys) + 1) / (tw * th)
    if box < 0.06:
        res["reason"] = "product too small in the picture"
        return res
    res["ok"] = True
    return res


# ---------------------------------------------------------------- shop
def _brand_of(p: dict) -> str:
    names = [b.get("name", "") for b in p.get("brands") or []]
    if names:
        return names[0].replace("&amp;", "&")
    low = (p.get("name") or "").lower()
    for cfg in BRANDS.values():
        for n in cfg["names"]:
            if low.startswith(n.lower() + " "):
                return n
    return ""


def cmd_targets(a, woo):
    rows = []
    for p in woo.all("/products", {"status": "publish",
                                   "_fields": "id,sku,name,brands,images,meta_data"}):
        meta = {m.get("key"): m.get("value") for m in p.get("meta_data") or []}
        img = (p.get("images") or [{}])[0]
        rows.append({"sku": p.get("sku") or "", "id": p["id"], "brand": _brand_of(p),
                     "name": (p.get("name") or "").replace("&amp;", "&"),
                     "web": "1" if (p.get("sku") or "").upper().startswith("WEB-") else "",
                     "ours": "1" if "_rte_source" in meta else "",
                     "image_src": img.get("src", ""), "image_id": img.get("id", ""),
                     "has_our_image": "1" if meta.get("_rte_image_url") else ""})
    with open(a.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, TARGET_FIELDS)
        w.writeheader()
        w.writerows(rows)
    c = collections.Counter((r["brand"] or "(none)", bool(r["image_src"])) for r in rows)
    print(f"products: {len(rows)}; WEB-: {sum(1 for r in rows if r['web'])}; "
          f"with an image: {sum(1 for r in rows if r['image_src'])}")
    for (b, has), n in sorted(c.items()):
        print(f"  {b}: {'with' if has else 'without'} image {n}")
    return 0


def load_targets(path) -> list:
    return list(csv.DictReader(open(path, newline="")))


def brand_targets(targets, key) -> list:
    names = {n.lower() for n in BRANDS[key]["names"]}
    return [t for t in targets if t["brand"].lower() in names]


# ---------------------------------------------------------------- crawl
class BrandFetcher:
    """The repo's Fetcher with a User-Agent that says what we fetch these pages for."""

    def __new__(cls, cfg, **kw):
        from rtech_sync.fetcher import Fetcher

        class _F(Fetcher):
            def _headers(self):
                h = super()._headers()
                h["User-Agent"] = (f"rtech-price-sync/0.1 (+mailto:{self.cfg.contact_email}; official product "
                                   "images for rtechelectricals.com, authorized dealer)")
                h["Accept"] = "text/html,application/xml;q=0.9,image/avif,image/webp,image/*;q=0.8,*/*;q=0.5"
                return h
        return _F(cfg, **kw)


class Refused(Exception):
    pass


def _check(fr, what):
    from rtech_sync.fetcher import looks_blocked
    is_image = fr.content[:3] == b"\xff\xd8\xff" or fr.content[:4] in (b"\x89PNG", b"RIFF")
    # a challenge page is small; a full product page may just mention reCAPTCHA on a contact form
    text = fr.text or ""
    challenge = (fr.status == "ok" and not is_image and len(text) < 20000 and "<h1" not in text.lower()
                 and looks_blocked(text))
    if fr.status == "blocked" or challenge:
        raise Refused(f"{what}: {fr.status} {fr.http or ''} {fr.detail}".strip())
    if fr.status == "robots_blocked" and "unavailable" in fr.detail:
        raise Refused(f"{what}: robots.txt could not be read ({fr.detail})")


def resolve_site(fetcher, site, log):
    """The brand's canonical address. The Fetcher does not follow a redirected robots.txt (it then
    reads no rules and fetches nothing), so robots.txt itself is requested once here, following
    redirects on the same site, to find where the site really lives (e.g. www. -> bare host)."""
    from rtech_sync.urlcheck import same_site
    try:
        r = fetcher.session.get(site + "/robots.txt", headers=fetcher._headers(),
                                timeout=fetcher.cfg.timeout_seconds, allow_redirects=True)
    except Exception as e:
        raise Refused(f"robots.txt: network error {type(e).__name__}")
    hops = " -> ".join([str(h.status_code) for h in r.history] + [str(r.status_code)])
    log(f"  robots.txt {site}: HTTP {hops}, final {r.url}")
    if r.status_code in (401, 403, 429):
        raise Refused(f"robots.txt: HTTP {r.status_code}")
    parts = urlsplit(r.url)
    final = f"{parts.scheme}://{parts.netloc}"
    if not same_site(site, final) and r.history:
        # e.g. polycab.com -> www.polycab.com is same_site; a move to another domain is followed
        # only if it is clearly the same brand name
        brand_word = re.sub(r"^www\.", "", urlsplit(site).netloc).split(".")[0]
        if brand_word not in parts.netloc:
            raise Refused(f"robots.txt redirects to another site: {r.url}")
    time.sleep(fetcher.cfg.min_delay_seconds)
    return final


def sitemap_urls(fetcher, site, log, max_files=120):
    site = resolve_site(fetcher, site, log)
    fr = fetcher.get(site + "/robots.txt")
    _check(fr, "robots.txt")
    roots = re.findall(r"(?im)^\s*sitemap\s*:\s*(\S+)", fr.text if fr.status == "ok" else "")
    roots = roots or [site + "/sitemap.xml", site + "/sitemap_index.xml"]
    from rtech_sync.matching import parse_sitemap
    from rtech_sync.urlcheck import same_site
    queue, seen, pages = list(roots), set(), []
    while queue and len(seen) < max_files:
        sm = queue.pop(0)
        if sm in seen or (len(seen) >= len(roots) and SKIP_SITEMAP.search(urlsplit(sm).path)):
            continue
        seen.add(sm)
        fr = fetcher.get(sm)
        _check(fr, sm)
        if fr.status != "ok":
            log(f"  sitemap {sm}: {fr.status} {fr.http or ''} {fr.detail}")
            continue
        try:
            got, children = parse_sitemap(fr.content or fr.text.encode())
        except Exception as e:
            log(f"  sitemap {sm}: cannot parse ({type(e).__name__})")
            continue
        got = [u for u in got if same_site(site, u)]
        log(f"  sitemap {sm}: {len(got)} pages, {len(children)} child sitemaps")
        pages += got
        queue += children
    return list(dict.fromkeys(pages)), len(seen)


def _vocab(targets) -> collections.Counter:
    stop = {"with", "and", "for", "pack", "white", "black", "grey", "red", "blue", "green", "yellow", "core",
            "cable", "wire", "inch", "sq", "mm", "of", "the", "type", "single", "double", "pole", "module"}
    c = collections.Counter()
    for t in targets:
        for w in set(re.findall(r"[a-z]{4,}", t["name"].lower())):
            if w not in stop:
                c[w] += 1
    return c


def prioritise(urls, targets, all_codes, done):
    vocab, brand_words = _vocab(targets), set()
    for t in targets:
        brand_words |= {w.lower() for w in t["brand"].split()}
    first, rest = [], []
    for u in urls:
        if u in done or SKIP_PAGE.search(urlsplit(u).path):
            continue
        if page_codes(u, all_codes):
            first.append(u)
            continue
        words = set(re.findall(r"[a-z]{4,}", urlsplit(u).path.lower())) - brand_words
        score = sum(min(vocab[w], 50) for w in words)
        if score:
            rest.append((-score, u))
    return first + [u for _, u in sorted(rest)]


def _save_pages(path, rows):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, PAGE_FIELDS)
        w.writeheader()
        w.writerows(rows.values())


def cmd_crawl(a):
    from rtech_sync.config import load_config
    from rtech_sync.urlcheck import bare_host
    cfg = load_config(a.config)
    cfg.fetch.require_contact_email()
    fetcher = BrandFetcher(cfg.fetch)
    key = a.brand
    targets = brand_targets(load_targets(a.targets), key)
    all_codes = set()
    for t in targets:
        all_codes |= codes_for(t["name"])
    cache = {}
    if a.previous and Path(a.previous).exists():
        cache = {r["url"]: r for r in csv.DictReader(open(a.previous, newline=""))}
    summary = {"brand": key, "products": len(targets), "with_model_number": sum(1 for t in targets if codes_for(t["name"])),
               "sites": {}, "pages_cached": len(cache)}
    out_rows = dict(cache)
    fetched = 0

    def log(m):
        print(m, flush=True)

    for site in BRANDS[key]["sites"]:
        s = summary["sites"][site] = {"sitemap_files": 0, "pages_listed": 0, "fetched": 0, "matched": 0,
                                      "images_checked": 0, "stopped": ""}
        try:
            urls, n = sitemap_urls(fetcher, site, log)
            s["sitemap_files"], s["pages_listed"] = n, len(urls)
            if not urls:
                s["stopped"] = "no published sitemap with pages"
                continue
            for u in prioritise(urls, targets, all_codes, set(cache)):
                if fetched >= a.max_pages:
                    s["stopped"] = s["stopped"] or "page limit for this run"
                    break
                fr = fetcher.get(u)
                fetched += 1
                s["fetched"] += 1
                _check(fr, u)
                row = {"url": u, "status": f"{fr.status}:{fr.http or ''}", "strong": "", "images": "[]",
                       "fetched": time.strftime("%Y-%m-%d")}
                if fr.status == "ok":
                    ex = extract_page(fr.text, fr.final_url or u)
                    row["strong"], row["name"] = ex["strong"], ex["name"]
                    named = any(name_match(ex["name"], t["name"], t["brand"]) for t in targets)
                    if page_codes(ex["strong"], all_codes) or named:
                        s["matched"] += 1
                        checked = []
                        for img in ex["images"][:3]:
                            host = urlsplit(img).netloc.lower()
                            if (not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,6}(:\d+)?", host)
                                    or re.search(r"undefined|null|none", img, re.I)):
                                checked.append({"ok": False, "w": 0, "h": 0, "reason": "broken image address",
                                                "white": False, "url": img})
                                continue
                            ir = fetcher.get(img)
                            try:
                                _check(ir, img)
                            except Refused:
                                if bare_host(urlsplit(img).netloc) == bare_host(urlsplit(u).netloc):
                                    raise  # the brand's own site refused us: stop
                                ir.status = "error"  # an image server elsewhere: skip this image only
                            s["images_checked"] += 1
                            q = assess(ir.content) if ir.status == "ok" else {
                                "ok": False, "w": 0, "h": 0, "reason": f"{ir.status} {ir.http or ''}", "white": False}
                            checked.append(dict(q, url=img))
                        row["images"] = json.dumps(checked)
                out_rows[u] = row
                if fetched % 50 == 0:
                    log(f"  {fetched} pages fetched, {s['matched']} matched")
                    _save_pages(a.out, out_rows)  # keep progress if the job is stopped
        except Refused as e:
            s["stopped"] = f"STOPPED for this run: {e}"
            log(f"STOP {site}: {e}")
    _save_pages(a.out, out_rows)
    summary["requests_per_host"] = fetcher.request_log
    Path(a.summary).write_text(json.dumps(summary, indent=1))
    log(json.dumps(summary, indent=1))
    for site, v in summary["sites"].items():  # shows as a run annotation (readable without the log)
        log(f"::notice title={key}::{site} listed {v['pages_listed']}, fetched {v['fetched']}, "
            f"matched {v['matched']}, images {v['images_checked']}. {v['stopped']}")
    return 0


# ---------------------------------------------------------------- plan
def plan(targets, pages_by_brand, current_quality=None) -> list:
    """One row per target product: the chosen official image or why there is none."""
    current_quality = current_quality or {}
    rows = []
    for key, pages in pages_by_brand.items():
        ts = brand_targets(targets, key)
        code_skus = collections.defaultdict(set)
        for t in ts:
            for c in codes_for(t["name"]):
                code_skus[c].add(t["sku"])
        all_codes = set(code_skus)
        img_pages = collections.Counter()
        for p in pages:
            for im in json.loads(p.get("images") or "[]"):
                img_pages[im["url"]] += 1
        by_code = collections.defaultdict(list)
        for p in pages:
            found = page_codes(p.get("strong", ""), all_codes)
            if not found:
                continue
            groups = {frozenset(code_skus[c]) for c in found}
            if len(groups) > 1:
                for c in found:
                    by_code[c].append((p, "page names several of our models (range page)"))
                continue
            for c in found:
                by_code[c].append((p, ""))
        for t in ts:
            row = {"sku": t["sku"], "id": t["id"], "brand": t["brand"], "name": t["name"], "code": "",
                   "page_url": "", "image_url": "", "w": "", "h": "", "action": "none", "reason": ""}
            codes = codes_for(t["name"])
            best, why = None, "no model number in our title"
            if codes:
                why = "no brand page with this model number"
                for c in sorted(codes):
                    for p, bad in by_code.get(c, []):
                        if bad:
                            why = bad
                            continue
                        for im in json.loads(p.get("images") or "[]"):
                            if img_pages[im["url"]] >= SHARED_IMAGE_PAGES:
                                why = "brand page image is shared by many pages (not product-specific)"
                            elif not im.get("ok"):
                                why = f"brand image failed quality check: {im.get('reason')}"
                            elif not best or im["w"] * im["h"] > best[1]["w"] * best[1]["h"]:
                                best = (p, im, c)
                    if by_code.get(c) and not best and why.startswith("no brand page"):
                        why = "brand page has no product image"
            how = "model"
            if not best:  # weaker route, applied only with --allow-name
                scored = []
                for p in pages:
                    sc = name_match(p.get("name", ""), t["name"], t["brand"])
                    if not sc:
                        continue
                    good = [im for im in json.loads(p.get("images") or "[]")
                            if im.get("ok") and img_pages[im["url"]] < SHARED_IMAGE_PAGES]
                    if good:
                        scored.append((sc, max(good, key=lambda i: i["w"] * i["h"]), p))
                if scored:
                    top = max(x[0] for x in scored)
                    tops = [x for x in scored if x[0] == top]
                    if len({x[1]["url"] for x in tops}) == 1:
                        best, how = (tops[0][2], tops[0][1], "name: " + tops[0][2].get("name", "")[:80]), "name"
                    else:
                        why += "; product-name match is ambiguous"
            if True:
                if best:
                    p, im, c = best
                    row.update(code=c, page_url=p["url"], image_url=im["url"], w=im["w"], h=im["h"])
                    if how == "name":
                        if not t["image_src"]:
                            row["action"], row["reason"] = "add-name", "no image now; matched by product name"
                        elif t["web"] and current_quality.get(t["sku"]) and not current_quality[t["sku"]]["ok"]:
                            row["action"] = "add-name"
                            row["reason"] = f"current image fails: {current_quality[t['sku']]['reason']}; matched by product name"
                        else:
                            row["reason"] = "has an image; product-name matches never replace a good image"
                    elif not t["image_src"]:
                        row["action"], row["reason"] = "add", "no image now"
                    elif t["has_our_image"]:
                        row["reason"] = "already has an official image from this tool"
                    elif t["web"]:
                        cq = current_quality.get(t["sku"])
                        if cq is None:
                            row["reason"] = "current image could not be checked; kept"
                        elif not cq["ok"]:
                            row["action"], row["reason"] = "replace", f"current image fails: {cq['reason']}"
                        elif im["w"] * im["h"] >= BIGGER * cq["w"] * cq["h"]:
                            row["action"], row["reason"] = "replace", (
                                f"brand image is clearer ({im['w']}x{im['h']} vs {cq['w']}x{cq['h']})")
                        else:
                            row["reason"] = f"current image is good ({cq['w']}x{cq['h']}); kept"
                    else:
                        row["reason"] = "product already has an image; kept"
                else:
                    row["reason"] = why
            rows.append(row)
    return rows


PLAN_FIELDS = ["sku", "id", "brand", "name", "code", "page_url", "image_url", "w", "h", "action", "reason", "result"]


def cmd_plan(a, woo=None):
    targets = load_targets(a.targets)
    pages_by_brand = {}
    for key in BRANDS:
        f = Path(a.pages_dir) / f"pages_{key}.csv"
        if f.exists():
            pages_by_brand[key] = list(csv.DictReader(open(f, newline="")))
    cur = {}
    if a.check_current:
        import requests
        s = requests.Session()
        for t in targets:
            if t["web"] and t["image_src"]:
                try:
                    r = s.get(t["image_src"], timeout=60)
                    cur[t["sku"]] = assess(r.content) if r.status_code == 200 else {
                        "ok": False, "w": 0, "h": 0, "reason": f"HTTP {r.status_code}"}
                except Exception as e:
                    cur[t["sku"]] = {"ok": False, "w": 0, "h": 0, "reason": type(e).__name__}
                time.sleep(1)
    rows = plan(targets, pages_by_brand, cur)
    with open(a.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, PLAN_FIELDS)
        w.writeheader()
        w.writerows(rows)
    c = collections.Counter((r["brand"], r["action"]) for r in rows)
    print("plan:", dict(c))
    return 0


# ---------------------------------------------------------------- apply / remove
def apply_payload(row) -> dict:
    p = {"id": int(row["id"]),
         "images": [{"src": row["image_url"], "alt": row["name"]}],
         "meta_data": [{"key": "_rte_image_source", "value": row["page_url"]},
                       {"key": "_rte_image_url", "value": row["image_url"]},
                       {"key": "_rte_image_brand", "value": row["brand"]}]}
    assert not (FORBIDDEN & set(p))
    return p


def cmd_apply(a, woo, sleep=time.sleep):
    rows = list(csv.DictReader(open(a.plan, newline="")))
    allowed = ("add", "replace") + (("add-name",) if a.allow_name else ())
    todo = [r for r in rows if r["action"] in allowed]
    if a.limit:
        todo = todo[:a.limit]
    ids = [int(r["id"]) for r in todo]
    current = {}
    for i in range(0, len(ids), 100):
        st, data, _ = woo.get("/products", {"include": ",".join(map(str, ids[i:i + 100])), "per_page": 100,
                                            "_fields": "id,images,meta_data"})
        if st != 200:
            raise RuntimeError(f"read failed: HTTP {st}")
        current.update({p["id"]: p for p in data})
    uploaded, done, failed, batch_fail = {}, 0, collections.Counter(), 0
    pending = []

    def flush():
        nonlocal done, batch_fail
        if not pending:
            return
        st, resp = woo.post("/products/batch", {"update": [p for _, p in pending]})
        ok_ids = {x.get("id"): x for x in (resp or {}).get("update", []) if not x.get("error")}
        for r, p in pending:
            got = ok_ids.get(p["id"])
            if st == 200 and got and got.get("images"):
                r["result"] = "done"
                uploaded.setdefault(r["image_url"], got["images"][0]["id"])
                done += 1
            else:
                err = next((x.get("error", {}).get("message", "") for x in (resp or {}).get("update", [])
                            if x.get("id") == p["id"] and x.get("error")), f"HTTP {st}")
                r["result"] = f"failed: {err}"[:200]
                failed["failed"] += 1
        batch_fail = batch_fail + 1 if st != 200 else 0
        pending.clear()
        sleep(3)

    for r in todo:
        cur = current.get(int(r["id"]))
        if not cur:
            r["result"] = "not on shop"
            continue
        if (r["action"] == "add" or (r["action"] == "add-name" and not r["sku"].upper().startswith("WEB-"))) \
                and cur.get("images"):
            r["result"] = "skipped: has an image now"
            continue
        p = apply_payload(r)
        if r["image_url"] in uploaded:  # same official image on another product: reuse, no new download
            p["images"] = [{"id": uploaded[r["image_url"]], "alt": r["name"]}]
            st, resp = woo.post("/products/batch", {"update": [p]})
            r["result"] = "done (reused)" if st == 200 else f"failed: HTTP {st}"
            done += st == 200
            sleep(1)
            continue
        pending.append((r, p))
        if len(pending) >= a.batch:
            flush()
            if batch_fail >= 3:
                print("3 failed batches in a row: stopping")
                break
    flush()
    with open(a.plan, "w", newline="") as fh:
        w = csv.DictWriter(fh, PLAN_FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"images put on: {done}; failed: {sum(failed.values())}")
    return 0


def removal_payload(cur, brand) -> dict | None:
    meta = {m.get("key"): m.get("value") for m in cur.get("meta_data") or []}
    if not meta.get("_rte_image_url") or (meta.get("_rte_image_brand") or "").lower() != brand.lower():
        return None
    return {"id": cur["id"], "images": [],
            "meta_data": [{"key": k, "value": ""} for k in ("_rte_image_source", "_rte_image_url", "_rte_image_brand")]}


def cmd_remove(a, woo):
    items = [p for p in (removal_payload(c, a.brand_name) for c in
                         woo.all("/products", {"status": "any", "_fields": "id,meta_data"})) if p]
    n = 0
    for i in range(0, len(items), 20):
        st, _ = woo.post("/products/batch", {"update": items[i:i + 20]})
        n += len(items[i:i + 20]) if st == 200 else 0
        time.sleep(2)
    print(f"{a.brand_name}: images removed from {n} of {len(items)} products")
    return 0


# ---------------------------------------------------------------- report
def cmd_report(a):
    rows = list(csv.DictReader(open(a.plan, newline="")))
    targets = load_targets(a.targets)
    lines = ["# Official brand images", "", f"Run {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}", ""]
    for f in sorted(Path(a.pages_dir).glob("summary_*.json")):
        s = json.loads(f.read_text())
        for site, v in s["sites"].items():
            lines.append(f"- {s['brand']} {site}: sitemap files {v['sitemap_files']}, pages listed "
                         f"{v['pages_listed']}, fetched {v['fetched']}, with our model numbers {v['matched']}, "
                         f"images checked {v['images_checked']}. {v['stopped']}")
    lines += ["", "| Brand | Products | Official image now | Added/replaced this run | No official image |",
              "|---|---|---|---|---|"]
    by = collections.defaultdict(list)
    for r in rows:
        by[r["brand"]].append(r)
    tot = collections.Counter()
    for b, rs in sorted(by.items()):
        added = sum(1 for r in rs if r.get("result", "").startswith("done"))
        has = sum(1 for r in rs if r.get("result", "").startswith("done") or r["reason"].startswith("already has an official"))
        tot.update(products=len(rs), has=has, added=added)
        lines.append(f"| {b} | {len(rs)} | {has} | {added} | {len(rs) - has} |")
    other = [t for t in targets if not any(t["brand"].lower() in [n.lower() for n in c["names"]] for c in BRANDS.values())]
    lines.append(f"| other brands (no site checked) | {len(other)} | 0 | 0 | {len(other)} |")
    lines.append(f"| **All** | {tot['products'] + len(other)} | {tot['has']} | {tot['added']} | "
                 f"{tot['products'] - tot['has'] + len(other)} |")
    waiting = collections.Counter(r["brand"] for r in rows if r["action"] == "add-name" and not r.get("result"))
    if waiting:
        lines += ["", f"Product-name matches found but not applied (need --allow-name): {sum(waiting.values())} "
                  f"({', '.join(f'{b} {n}' for b, n in waiting.most_common())})"]
        for r in [r for r in rows if r["action"] == "add-name"][:8]:
            lines.append(f"- {r['name']} <- {r['page_url']} ({r['code']})")
    reasons = collections.Counter(r["reason"].split(":")[0] for r in rows if r["action"] == "none")
    lines += ["", "## Why products have no official image", ""]
    lines += [f"- {k}: {v}" for k, v in reasons.most_common()]
    lines += ["", "## Samples", ""]
    for r in [r for r in rows if r.get("result", "").startswith("done")][:15]:
        lines.append(f"- {r['sku']} {r['name']}: {r['image_url']} (from {r['page_url']}, {r['w']}x{r['h']})")
    Path(a.out).write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:40]))
    return 0


def _woo():
    from enrich_products import Woo
    return Woo(os.environ["WC_URL"], os.environ["WC_KEY"], os.environ["WC_SECRET"])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("targets")
    s.add_argument("--out", default="targets.csv")
    s = sub.add_parser("crawl")
    s.add_argument("--brand", required=True, choices=sorted(BRANDS))
    s.add_argument("--targets", required=True)
    s.add_argument("--previous", default="")
    s.add_argument("--out", required=True)
    s.add_argument("--summary", required=True)
    s.add_argument("--max-pages", type=int, default=600)
    s.add_argument("--config", default="config.yaml")
    s = sub.add_parser("plan")
    s.add_argument("--targets", required=True)
    s.add_argument("--pages-dir", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--check-current", action="store_true", help="download the WEB- products' current images")
    s = sub.add_parser("apply")
    s.add_argument("--plan", required=True)
    s.add_argument("--batch", type=int, default=5)
    s.add_argument("--limit", type=int, default=0)
    s.add_argument("--allow-name", action="store_true", help="also apply product-name matches (add-name)")
    s = sub.add_parser("remove")
    s.add_argument("--brand-name", required=True)
    s = sub.add_parser("report")
    s.add_argument("--plan", required=True)
    s.add_argument("--targets", required=True)
    s.add_argument("--pages-dir", required=True)
    s.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "targets":
        return cmd_targets(a, _woo())
    if a.cmd == "crawl":
        return cmd_crawl(a)
    if a.cmd == "plan":
        return cmd_plan(a)
    if a.cmd == "apply":
        return cmd_apply(a, _woo())
    if a.cmd == "remove":
        return cmd_remove(a, _woo())
    return cmd_report(a)


if __name__ == "__main__":
    sys.exit(main())
