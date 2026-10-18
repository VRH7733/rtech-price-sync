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
    # legrand.co.in's sitemap lists product URLs that answer 404 (checked 16 Oct 2026 in a browser);
    # the live product pages show Legrand's own catalogue photo, named by catalogue number, from
    # assets.legrand.com/pim/PHOTOS-WEB/LG-<number>-WEB-R.jpg, so that photo is fetched directly.
    "legrand": {"names": ["Legrand"], "sites": [], "pim": "https://assets.legrand.com/pim/PHOTOS-WEB/LG-{code}-WEB-R.jpg"},
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
                       r"store-locator|dealers?|csr|sustainability|tag|author|policy|privacy|terms|campaigns?|offers?)(/|$)|"
                       r"\.(pdf|jpe?g|png|webp|gif|svg|zip)$", re.I)
BAD_IMAGE_URL = re.compile(r"logo|placeholder|banner|favicon|sprite|icon|\.svg|\.gif", re.I)
# 400 px (was 600 until 18 Oct 2026): Polycab's per-SKU wire photos are 400x400 and clean; the owner
# wants a photo on every product rather than none, and the shop gallery shows about 600 px.
MIN_SIDE, MAX_RATIO, MIN_PLAIN_BORDER, BIGGER = 400, 1.6, 0.85, 1.5
# range photos (one official photo of a wire range, shared by its sizes): often a wide 530x300 picture,
# shown padded to a white square, never cropped
RANGE_MIN_LONG, RANGE_MAX_RATIO = 400, 2.6
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


# ---------------------------------------------------------------- wires and cables (no model numbers)
WIRE_VARIANT = {"fr", "frls", "frlsh", "lsh", "ls", "hr", "hrfr", "lf", "frlf", "lffr", "zhfr", "hffr", "flame",
                "retardant", "low", "smoke", "halogen", "free", "zero", "heat", "resistant", "lead", "s3", "pvc",
                "xlpe", "e", "ii", "grade"}
WIRE_GENERIC = {"house", "wire", "wires", "cable", "cables", "copper", "insulated", "industrial", "flexible",
                "multistrand", "single", "multi", "core", "electrical", "domestic", "for", "and", "color", "colour",
                "length", "sq", "mm", "sqmm", "meters", "meter", "mtr", "mtrs", "m", "with", "new", "coil", "the",
                "power", "building", "type", "conductor", "unsheathed"}
WIRE_COLOURS = COLOURS - {"silver", "gold"}


def _wire_text(s: str) -> str:
    s = s.lower().replace("\u2013", " ").replace("\u2014", " ").replace("\u00b2", "2")
    s = re.sub(r"\b(wires?)\s*\+", r"\1 plus ", s)
    s = re.sub(r"([a-z])\+(?![a-z])", r"\1plus ", s)  # Maxima+ -> maximaplus; HR+FR stays two words
    return s


def _wire_range(head: str, brand_words: set) -> str:
    toks = re.findall(r"[a-z0-9]+", head)
    out = []
    for t in toks:
        for b in brand_words:  # POLYCABOPTIMA+ -> optimaplus
            if t.startswith(b) and len(t) > len(b) + 2:
                t = t[len(b):]
        if t in brand_words or t in WIRE_GENERIC or t in WIRE_VARIANT:
            continue
        out.append(t)
    return "".join(out)


def wire_key(text: str, brand: str) -> dict | None:
    """Range, size (sq mm), cores, colour, length (m) and FR-type words of a wire or cable name, e.g.
    'Polycab Primma house wire 6 sq mm Blue 90 m' or the brand page 'POLYCABPRIMMA | LF-FR | 6 Sq. MM |
    90 Meters, Copper | Blue'. None when it has no size or no range name (a generic '185 Sq.mm cable')."""
    s = _wire_text(text)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:sq\.?\s*mm\b|sqmm|sq\.?\s*m\.?m\.?|mm2|sq\b)", s)
    if not m:
        return None
    brand_words = {w for w in re.findall(r"[a-z0-9]+", brand.lower())} | {"".join(re.findall(r"[a-z0-9]+", brand.lower()))}
    first_num = re.search(r"\d", s)
    head = s[:first_num.start()] if first_num else s
    if "|" in head:
        head = head.split("|")[0]
    rng = _wire_range(head, brand_words)
    if not rng or len(rng) < 3:
        return None
    tail = s[first_num.start():] if first_num else ""
    colours = [w for w in re.findall(r"[a-z]+", tail) if w in WIRE_COLOURS]
    cores = re.search(r"(\d+(?:\.\d+)?)\s*core", s)
    length = re.search(r"(\d+)\s*(?:m\b|meters?\b|mtrs?\b|metres?\b)", s)
    variant = {w for w in re.findall(r"[a-z0-9]+", s) if w in {"fr", "frls", "frlsh", "lsh", "hrfr", "zhfr", "hffr", "lf"}}
    return {"range": rng, "size": float(m.group(1)), "cores": float(cores.group(1)) if cores else 1.0,
            "colour": colours[-1] if colours else "", "length": int(length.group(1)) if length else 0,
            "variant": variant}


def wire_match(page: dict, ours: dict, same_length: bool = True) -> bool:
    """Same range, size, cores and colour; same length when both say it (unless same_length=False,
    the fallback when the brand shows only another coil length); FR-type words agree when the
    brand page names them (the range name already implies them when it does not)."""
    if not page or not ours:
        return False
    if (page["range"], page["size"], page["cores"], page["colour"]) != (ours["range"], ours["size"], ours["cores"],
                                                                        ours["colour"]):
        return False
    if same_length and page["length"] and ours["length"] and page["length"] != ours["length"]:
        return False
    if page["variant"] and ours["variant"] and not (page["variant"] <= ours["variant"] or ours["variant"] <= page["variant"]):
        return False
    return True


def range_key(text: str, brand: str) -> str:
    """The range name of a brand's range page ('HomeCab-FR', 'Unilay HR FR') or of our title
    ('KEI Homecab 2.5 Sq.mm 1 Core FR ...' -> 'homecab'); '' when there is none."""
    s = _wire_text(text).split("|")[0]
    first_num = re.search(r"\d", s)
    head = s[:first_num.start()] if first_num else s
    brand_words = {w for w in re.findall(r"[a-z0-9]+", brand.lower())} | {"".join(re.findall(r"[a-z0-9]+", brand.lower()))}
    r = _wire_range(head, brand_words)
    return r if len(r) >= 4 else ""


def is_wire(title: str) -> bool:
    return bool(re.search(r"(\d)\s*(sq\.?\s*mm|sqmm|mm2|mm\u00b2)|\b(wire|wires|cable)\b", title.lower()))


BODY_COLOURS = {"pink", "red", "green", "blue", "brown", "black", "grey", "gray", "gold", "golden", "silver", "ivory",
                "pearl", "wood", "wooden", "walnut", "copper", "maroon", "espresso", "nickel", "nicke", "mist", "dusk",
                "matt", "matte", "bronze", "beige", "orange", "yellow", "purple", "violet", "white", "teak", "rosewood",
                "champagne", "smoke", "sand", "cream", "slate", "chrome", "metallic", "rust", "titanium", "aqua"}
FAN_GENERIC = {"havells", "crabtree", "ceiling", "fan", "fans", "with", "remote", "control", "bldc", "sweep", "and",
               "the", "for", "blades", "blade", "speed", "high", "energy", "saving", "star", "rated", "decorative",
               "premium", "underlight", "led", "light", "motor", "copper", "pack"}
LIGHT_COLOUR = re.compile(r"\b(cool|warm|natural|neutral|netural|day)\s*(white|daylight|day\s*light)\b|daylight|"
                          r"white\s+light|\bcdl\b|\bww\b|\bnw\b")


def colour_ok(title: str, page_text: str) -> bool:
    """A product-name match shows the right thing only if every body colour or finish in our title
    (Brown, Pearl White, Wood Mist...) is on the brand page too. Light colours of lamps (Cool White,
    Warm White, Daylight) do not change how the product looks and are ignored."""
    words = set(re.findall(r"[a-z]+", LIGHT_COLOUR.sub(" ", title.lower())))
    theirs = set(re.findall(r"[a-z]+", page_text.lower().replace("-", " ")))
    if not (words & BODY_COLOURS) <= theirs:
        return False
    caps = set(re.findall(r"\b(b22|e27|e14|gu10|gu5)\b", title.lower()))  # lamp bases look different
    if not caps <= set(re.findall(r"[a-z0-9]+", page_text.lower())):
        return False
    if {"fan", "fans"} & words:
        # fan finishes have names of their own (Quartz, Bianco, Flora Sapphire): every descriptive
        # word of our title must be on the brand page
        extra = {w for w in words - theirs if len(w) > 2} - FAN_GENERIC
        return not extra
    return True


class NameIndex:
    """name_match against many titles at once: words -> titles that contain them all."""

    def __init__(self, targets):
        self.targets = targets
        self.post = collections.defaultdict(set)
        self.words = []
        for i, t in enumerate(targets):
            w = set(_name_words(t["name"]))
            self.words.append(w)
            for x in w:
                self.post[x].add(i)

    def matches(self, page_name: str, brand: str) -> list:
        if not page_name:
            return []
        pn = page_name.split("|")[0].split(" - ")[0]
        bw = set(_name_words(brand))
        words = [w for w in _name_words(pn) if w not in bw]
        if len(words) < 2:
            return []
        cand = set.intersection(*(self.post.get(w, set()) for w in set(words)))
        return [(self.targets[i], len(words)) for i in sorted(cand)
                if not any(w in COLOURS and w not in self.words[i] for w in words)]


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


def pad_square(data: bytes, margin: float = 0.06) -> bytes:
    """The picture centred on a white square (nothing cut off), as JPEG."""
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    im.load()
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, im)
    im = im.convert("RGB")
    side = int(max(im.size) * (1 + 2 * margin))
    sq = Image.new("RGB", (side, side), (255, 255, 255))
    sq.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
    buf = io.BytesIO()
    sq.save(buf, "JPEG", quality=92)
    return buf.getvalue()


def assess_range(data: bytes) -> dict:
    """Quality check of a range photo as it will be shown: padded to a white square. The original
    must be at least RANGE_MIN_LONG px on its long side and not a very wide banner, and the padded
    picture must pass the normal check (plain background, product not cut off, not tiny)."""
    q = assess(data)
    if not q["w"]:
        return {"range_ok": False, "range_reason": q["reason"]}
    w, h = q["w"], q["h"]
    if max(w, h) < RANGE_MIN_LONG:
        return {"range_ok": False, "range_reason": f"too small ({w}x{h})"}
    if max(w, h) / min(w, h) > RANGE_MAX_RATIO:
        return {"range_ok": False, "range_reason": f"banner shape ({w}x{h})"}
    pq = assess(pad_square(data))
    return {"range_ok": pq["ok"], "range_reason": pq["reason"]}


def _assess_both(data: bytes) -> dict:
    q = assess(data)
    q.update(assess_range(data) if q["w"] else {"range_ok": False, "range_reason": q["reason"]})
    return q


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


def sitemap_images(xml_bytes: bytes) -> dict:
    """Image sitemap entries (<image:image>): page URL -> (image URLs, image title)."""
    import gzip
    from xml.etree import ElementTree
    if xml_bytes[:2] == b"\x1f\x8b":
        xml_bytes = gzip.decompress(xml_bytes)
    out = {}
    for url in ElementTree.fromstring(xml_bytes).iter():
        if not url.tag.endswith("}url") and url.tag != "url":
            continue
        loc, imgs, title = "", [], ""
        for el in url.iter():
            tag = el.tag.split("}")[-1]
            if tag == "loc" and el.text and not loc and "image" not in el.tag:
                loc = el.text.strip()
            elif tag == "loc" and el.text and "image" in el.tag:
                imgs.append(el.text.strip())
            elif tag == "title" and el.text and "image" in el.tag:
                title = title or el.text.strip()
        if loc and imgs:
            out[loc] = (imgs, title)
    return out


def original_image(url: str) -> str:
    """Magento serves resized copies under /cache/<hash>/; the same file without it is the original.
    Image servers that resize on request ('...jpg?format=webp&width=400') give the uploaded file
    without the query."""
    url = re.sub(r"/cache/[0-9a-f]{32}/", "/", url)
    parts = urlsplit(url)
    if parts.query and all(k.split("=")[0].lower() in ("format", "width", "height", "w", "h", "quality", "mode",
                                                      "rmode", "rnd", "v") for k in parts.query.split("&")):
        url = url.split("?")[0]
    return url


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
    queue, seen, pages, images = list(roots), set(), [], {}
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
        try:
            images.update(sitemap_images(fr.content or fr.text.encode()))
        except Exception:
            pass
        log(f"  sitemap {sm}: {len(got)} pages, {len(children)} child sitemaps")
        pages += got
        queue += children
    return list(dict.fromkeys(pages)), len(seen), images


def _vocab(targets) -> collections.Counter:
    stop = {"with", "and", "for", "pack", "white", "black", "grey", "red", "blue", "green", "yellow", "core",
            "cable", "wire", "inch", "sq", "mm", "of", "the", "type", "single", "double", "pole", "module"}
    c = collections.Counter()
    for t in targets:
        for w in set(re.findall(r"[a-z]{4,}", t["name"].lower())):
            if w not in stop:
                c[w] += 1
    return c


class Wanted:
    """Which brand pages can give one of our products a photo: a model number, a product-name match,
    a wire with the same range/size/colour, or a wire range page of one of our ranges."""

    def __init__(self, targets, all_codes):
        self.all_codes = all_codes
        self.brand = targets[0]["brand"] if targets else ""
        nocode = [t for t in targets if not codes_for(t["name"])]
        self.names = NameIndex(nocode)
        self.wires = [k for k in (wire_key(t["name"], t["brand"]) for t in nocode if is_wire(t["name"])) if k]
        self.wire_set = {(k["range"], k["size"], k["cores"], k["colour"]) for k in self.wires}
        rc = collections.Counter(range_key(t["name"], t["brand"]) for t in nocode if is_wire(t["name"]))
        self.ranges = {r for r in rc if r}
        self.big_ranges = {r for r, n in rc.items() if r and n >= 3}
        self.brand_words = {w for w in re.findall(r"[a-z0-9]+", self.brand.lower())}
        self.slug = {(k["range"], _norm(f"{k['size']:g}"), k["colour"]) for k in self.wires}

    def page(self, name, strong, url="") -> bool:
        if page_codes(strong or "", self.all_codes) or page_codes(url, self.all_codes):
            return True
        if self.names.matches(name, self.brand):
            return True
        k = wire_key(name or "", self.brand)
        if k and (k["range"], k["size"], k["cores"], k["colour"]) in self.wire_set:
            return True
        return bool(name) and not k and range_key(name, self.brand) in self.ranges

    def url_hit(self, url) -> bool:
        path = _wire_text(urlsplit(url).path)
        toks = set(re.findall(r"[a-z0-9]+", path))
        joined = re.sub(r"[^a-z0-9]", "", path)
        words = []
        for t in re.findall(r"[a-z0-9]+", path):
            for b in self.brand_words:
                if t.startswith(b) and len(t) > len(b) + 2:
                    t = t[len(b):]
            words.append(t)
        grams = {"".join(words[i:i + n]) for n in (1, 2, 3) for i in range(len(words) - n + 1)}
        return (any(r in grams and sz in toks and (not c or c in toks) for r, sz, c in self.slug)
                or bool(grams & self.big_ranges))


def prioritise(urls, targets, all_codes, done, wanted=None):
    vocab, brand_words = _vocab(targets), set()
    for t in targets:
        brand_words |= {w.lower() for w in t["brand"].split()}
    first, rest = [], []
    for u in urls:
        if u in done or SKIP_PAGE.search(urlsplit(u).path):
            continue
        if page_codes(u, all_codes) or (wanted and wanted.url_hit(u)):
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

    pim = BRANDS[key].get("pim")
    if pim:
        s = summary["sites"][pim] = {"sitemap_files": 0, "pages_listed": 0, "fetched": 0, "matched": 0,
                                     "images_checked": 0, "stopped": ""}
        try:
            for code in sorted(c for c in all_codes if re.fullmatch(r"\d{6}", c)):
                u = pim.format(code=code)
                if u in cache:
                    continue
                if fetched >= a.max_pages:
                    s["stopped"] = "page limit for this run"
                    break
                ir = fetcher.get(u)
                fetched += 1
                s["fetched"] += 1
                _check(ir, u)
                q = assess(ir.content) if ir.status == "ok" else {
                    "ok": False, "w": 0, "h": 0, "reason": f"{ir.status} {ir.http or ''}", "white": False}
                s["matched"] += ir.status == "ok"
                s["images_checked"] += 1
                out_rows[u] = {"url": u, "status": f"{ir.status}:{ir.http or ''}", "strong": code,
                               "images": json.dumps([dict(q, url=u)]) if ir.status == "ok" else "[]",
                               "fetched": time.strftime("%Y-%m-%d"), "name": ""}
                if fetched % 50 == 0:
                    log(f"  {fetched} catalogue photos checked, {s['matched']} found")
                    _save_pages(a.out, out_rows)
        except Refused as e:
            s["stopped"] = f"STOPPED for this run: {e}"
            log(f"STOP {pim}: {e}")
    wanted = Wanted(targets, all_codes)
    # cached images that failed only a rule that has since changed (600 -> 400 px, range photos):
    # check the image again without opening the page again
    try:
        for u, r in list(out_rows.items()):
            ims = json.loads(r.get("images") or "[]")
            if not ims or any(i.get("ok") for i in ims) or all("range_ok" in i for i in ims):
                continue
            if not wanted.page(r.get("name", ""), r.get("strong", ""), u):
                continue
            if fetched >= a.max_pages:
                break
            again = []
            for im in ims:
                if not im.get("w"):
                    again.append(im)
                    continue
                best = None
                for img in dict.fromkeys([original_image(im["url"]), im["url"]]):
                    ir = fetcher.get(img)
                    fetched += 1
                    try:
                        _check(ir, img)
                    except Refused:
                        if bare_host(urlsplit(img).netloc) == bare_host(urlsplit(u).netloc):
                            raise
                        ir.status = "error"
                    if ir.status != "ok":
                        continue
                    q = dict(_assess_both(ir.content), url=img)
                    if not best or (q["ok"], q["range_ok"], q["w"] * q["h"]) > (best["ok"], best["range_ok"], best["w"] * best["h"]):
                        best = q
                    if q["ok"]:
                        break
                again.append(best or dict(im, range_ok=False, range_reason=im.get("reason", "")))
            r["images"] = json.dumps(again)
            if fetched % 50 == 0:
                log(f"  {fetched} cached images checked again")
                _save_pages(a.out, out_rows)
    except Refused as e:
        summary["recheck_stopped"] = str(e)
        log(f"STOP recheck: {e}")
    for site in BRANDS[key]["sites"]:
        s = summary["sites"][site] = {"sitemap_files": 0, "pages_listed": 0, "fetched": 0, "matched": 0,
                                      "images_checked": 0, "stopped": ""}
        try:
            urls, n, simg = sitemap_urls(fetcher, site, log)
            s["sitemap_files"], s["pages_listed"] = n, len(urls)
            if not urls:
                s["stopped"] = "no published sitemap with pages"
                continue
            # cached pages of our products whose images were never checked (an older rule did not
            # want them) are opened again
            done = {u for u, r in cache.items()
                    if not (r.get("status", "").startswith("ok") and (r.get("images") or "[]") == "[]"
                            and wanted.page(r.get("name", ""), r.get("strong", ""), u))}
            for u in prioritise(urls, targets, all_codes, done, wanted):
                if fetched >= a.max_pages:
                    s["stopped"] = s["stopped"] or "page limit for this run"
                    break
                codes_here = page_codes(u, all_codes)
                sm = simg.get(u, ([], ""))
                sm_imgs = [i for i in sm[0] if any(c in _norm(i) for c in codes_here)]
                if not sm_imgs and sm[0] and not codes_here and wanted.page(sm[1], "", u):
                    sm_imgs = sm[0][:1]  # matched by the product name in the image sitemap
                if sm_imgs:
                    # the sitemap already names this page's product photo: fetch only the photo
                    checked = []
                    for img in dict.fromkeys([original_image(sm_imgs[0]), sm_imgs[0]]):
                        ir = fetcher.get(img)
                        fetched += 1
                        _check(ir, img)
                        s["images_checked"] += 1
                        q = _assess_both(ir.content) if ir.status == "ok" else {
                            "ok": False, "w": 0, "h": 0, "reason": f"{ir.status} {ir.http or ''}", "white": False,
                            "range_ok": False, "range_reason": ""}
                        checked.append(dict(q, url=img))
                        if q["ok"]:
                            break
                    s["matched"] += 1
                    title = sm[1]
                    out_rows[u] = {"url": u, "status": "sitemap", "fetched": time.strftime("%Y-%m-%d"),
                                   "strong": urlsplit(u).path.replace("-", " ").replace("/", " ") + " | " + title,
                                   "images": json.dumps(checked), "name": title}
                    if fetched % 50 == 0:
                        _save_pages(a.out, out_rows)
                    continue
                if simg and u in simg and not codes_here:
                    continue  # an image-sitemap page that matches none of our products: not opened
                fr = fetcher.get(u)
                fetched += 1
                s["fetched"] += 1
                _check(fr, u)
                row = {"url": u, "status": f"{fr.status}:{fr.http or ''}", "strong": "", "images": "[]",
                       "fetched": time.strftime("%Y-%m-%d")}
                if fr.status == "ok":
                    ex = extract_page(fr.text, fr.final_url or u)
                    row["strong"], row["name"] = ex["strong"], ex["name"]
                    if wanted.page(ex["name"], ex["strong"], u):
                        s["matched"] += 1
                        checked = []
                        for img in ex["images"][:3]:
                            host = urlsplit(img).netloc.lower()
                            if (not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,6}(:\d+)?", host)
                                    or re.search(r"undefined|null|none", img, re.I)):
                                checked.append({"ok": False, "w": 0, "h": 0, "reason": "broken image address",
                                                "white": False, "url": img, "range_ok": False, "range_reason": ""})
                                continue
                            best = None
                            for cand in dict.fromkeys([original_image(img), img]):
                                ir = fetcher.get(cand)
                                try:
                                    _check(ir, cand)
                                except Refused:
                                    if bare_host(urlsplit(cand).netloc) == bare_host(urlsplit(u).netloc):
                                        raise  # the brand's own site refused us: stop
                                    ir.status = "error"  # an image server elsewhere: skip this image only
                                s["images_checked"] += 1
                                q = _assess_both(ir.content) if ir.status == "ok" else {
                                    "ok": False, "w": 0, "h": 0, "reason": f"{ir.status} {ir.http or ''}",
                                    "white": False, "range_ok": False, "range_reason": ""}
                                q = dict(q, url=cand)
                                if not best or (q["ok"], q["range_ok"], q["w"] * q["h"]) > (
                                        best["ok"], best["range_ok"], best["w"] * best["h"]):
                                    best = q
                                if q["ok"]:
                                    break
                            checked.append(best)
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
        brand_name = ts[0]["brand"] if ts else ""
        wire_pages, img_keys, range_pages = [], collections.defaultdict(set), collections.defaultdict(list)
        for p in pages:
            pk = wire_key(p.get("name") or "", brand_name)
            if pk:
                wire_pages.append((pk, p))
                for im in json.loads(p.get("images") or "[]"):
                    img_keys[im["url"]].add((pk["range"], pk["size"], pk["cores"], pk["colour"]))
            elif p.get("name"):  # a range page of one of our wire ranges (our side is checked to be a wire)
                rk = range_key(p["name"], brand_name)
                if rk:
                    range_pages[rk].append(p)
        name_hits, nidx = collections.defaultdict(list), NameIndex(ts)
        for p in pages:
            for t2, sc in nidx.matches(p.get("name", ""), brand_name):
                name_hits[t2["sku"]].append((p, sc))
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
                            named_file = c in _norm(urlsplit(im["url"]).path.rsplit("/", 1)[-1])
                            if img_pages[im["url"]] >= SHARED_IMAGE_PAGES and not named_file:
                                why = "brand page image is shared by many pages (not product-specific)"
                            elif not im.get("ok"):
                                why = f"brand image failed quality check: {im.get('reason')}"
                            elif not best or im["w"] * im["h"] > best[1]["w"] * best[1]["h"]:
                                best = (p, im, c)
                    if by_code.get(c) and not best and why.startswith("no brand page"):
                        why = "brand page has no product image"
            how = "model"
            wk = wire_key(t["name"], t["brand"]) if not codes and is_wire(t["name"]) else None
            if not best and wk:  # a wire: the brand's own page for this range, size, cores, colour
                found = []
                for same_length in (True, False):
                    for pk, p in wire_pages:
                        if not wire_match(pk, wk, same_length):
                            continue
                        for im in json.loads(p.get("images") or "[]"):
                            if len(img_keys[im["url"]]) > 1:
                                why = "brand wire photo is shared by different sizes or colours"
                            elif not im.get("ok"):
                                why = f"brand image failed quality check: {im.get('reason')}"
                            else:
                                found.append((im["w"] * im["h"], p, im))
                    if found:
                        break
                if found:
                    _, p, im = max(found, key=lambda x: x[0])
                    best, how = (p, im, f"wire {wk['range']} {wk['size']:g} sq mm {wk['colour']}".strip()), "wire"
                elif why == "no model number in our title":
                    why = "no model number in our title; no brand page for this wire range, size and colour"
            rk = range_key(t["name"], t["brand"]) if not codes and is_wire(t["name"]) else ""
            if not best and rk and rk in range_pages:  # last resort: the range's own photo, padded
                ims = [im for p in range_pages[rk] for im in json.loads(p.get("images") or "[]")
                       if im.get("range_ok")]
                if ims:
                    im = max(ims, key=lambda i: i["w"] * i["h"])
                    p = next(p for p in range_pages[rk] if im in json.loads(p.get("images") or "[]"))
                    best, how = (p, im, f"range {rk}"), "range"
                else:
                    why = "brand range photo failed quality check"
            if not best:  # weaker route, applied only with --allow-name
                scored = []
                for p, sc in name_hits.get(t["sku"], []):
                    good = [im for im in json.loads(p.get("images") or "[]")
                            if im.get("ok") and img_pages[im["url"]] < SHARED_IMAGE_PAGES]
                    if good:
                        scored.append((sc, max(good, key=lambda i: i["w"] * i["h"]), p))
                right = [x for x in scored if colour_ok(t["name"], x[2].get("name", "") + " " + x[2]["url"])]
                if scored and not right:
                    why += "; the brand photo may show another colour"
                scored = right
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
                    if how == "range":
                        if not t["image_src"]:
                            row["action"] = "add-range"
                            row["reason"] = "no image now; the brand's photo of this range, padded to a square"
                        else:
                            row["reason"] = "has an image; range photos never replace an image"
                    elif how == "name":
                        if not t["image_src"]:
                            row["action"], row["reason"] = "add-name", "no image now; matched by product name"
                        elif t["web"] and current_quality.get(t["sku"]) and not current_quality[t["sku"]]["ok"]:
                            row["action"] = "add-name"
                            row["reason"] = f"current image fails: {current_quality[t['sku']]['reason']}; matched by product name"
                        else:
                            row["reason"] = "has an image; product-name matches never replace a good image"
                    elif not t["image_src"]:
                        row["action"], row["reason"] = "add", "no image now" + (
                            "; matched by range, size, cores and colour" if how == "wire" else "")
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
            cq = current_quality.get(t["sku"]) if t["web"] else None
            if cq and row["action"] == "none":
                row["reason"] += (f"; current image {cq['w']}x{cq['h']} "
                                  + ("passes the quality check" if cq["ok"] else f"fails: {cq['reason']}"))
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


def cmd_pad(a):
    """Range photos are shown padded to a white square: fetch each one once (politely), pad it, write
    it to --out-dir and point the plan rows at the copy that will be published under --base-url."""
    import hashlib
    from rtech_sync.config import load_config
    rows = list(csv.DictReader(open(a.plan, newline="")))
    todo = [r for r in rows if r["action"] == "add-range"]
    if not todo:
        print("pad: no range photos in the plan")
        return 0
    cfg = load_config(a.config)
    cfg.fetch.require_contact_email()
    fetcher = BrandFetcher(cfg.fetch)
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    done, failed = {}, set()
    for r in todo:
        src = r["image_url"]
        if src not in done and src not in failed:
            fr = fetcher.get(src)
            try:
                _check(fr, src)
            except Refused as e:
                print(f"pad: stopped, {e}")
                break
            if fr.status != "ok" or not assess_range(fr.content)["range_ok"]:
                failed.add(src)
            else:
                name = hashlib.sha1(src.encode()).hexdigest()[:16] + ".jpg"
                (out / name).write_bytes(pad_square(fr.content))
                done[src] = a.base_url.rstrip("/") + "/" + name
        if src in done:
            r["image_url"] = done[src]
            r["reason"] += f" (brand photo {src})"
        else:
            r["action"], r["reason"] = "none", "range photo could not be fetched or failed the check"
    with open(a.plan, "w", newline="") as fh:
        w = csv.DictWriter(fh, PLAN_FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"pad: {len(done)} range photos padded for {sum(1 for r in todo if r['action'] == 'add-range')} products")
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


def _night_ist(now=None) -> bool:
    """00:30-06:00 IST belongs to the nightly price run (01:00, backup 03:00): no image writes then."""
    import datetime as dt
    t = (now or dt.datetime.now(dt.timezone.utc)) + dt.timedelta(hours=5, minutes=30)
    return (t.hour, t.minute) >= (0, 30) and t.hour < 6


def cmd_apply(a, woo, sleep=time.sleep):
    rows = list(csv.DictReader(open(a.plan, newline="")))
    allowed = ("add", "replace") + (("add-name",) if a.allow_name else ()) + (
        ("add-range",) if getattr(a, "allow_range", False) else ())
    # a range photo must already point at our padded copy (see cmd_pad)
    todo = [r for r in rows if r["action"] in allowed
            and (r["action"] != "add-range" or "/releases/download/" in r["image_url"])]
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
        if _night_ist():
            print("00:30 IST reached: stopping so the nightly price run has the shop; rerun apply later")
            break
        cur = current.get(int(r["id"]))
        if not cur:
            r["result"] = "not on shop"
            continue
        if (r["action"] in ("add", "add-range") or (r["action"] == "add-name" and not r["sku"].upper().startswith("WEB-"))) \
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
    s.add_argument("--allow-range", action="store_true", help="also apply padded range photos (add-range)")
    s = sub.add_parser("pad")
    s.add_argument("--plan", required=True)
    s.add_argument("--out-dir", required=True)
    s.add_argument("--base-url", required=True)
    s.add_argument("--config", default="config.yaml")
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
    if a.cmd == "pad":
        return cmd_pad(a)
    if a.cmd == "remove":
        return cmd_remove(a, _woo())
    return cmd_report(a)


if __name__ == "__main__":
    sys.exit(main())
