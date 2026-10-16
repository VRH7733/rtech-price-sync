#!/usr/bin/env python3
"""Put REAL product images (supplied by the brand or distributor, with permission) on our products.

Usage:
  import_brand_images.py --images-dir DIR --catalogue-dir DIR --plan-out plan.csv [--apply]

Matching, per catalogue SKU, best first:
  1. model number: a model code from our title (e.g. AHLHGXW060, Legrand "6792 50" -> 679250)
     appears in the image's file name;
  2. words: every word of the file name (brand folder name excluded) appears in our title, e.g.
     Havells/life-guard-red.jpg -> all Havells "Life Guard ... Red" cables. More words win.
The brand comes from the first folder under DIR (Havells/, Legrand/ ...) or the file name.

Only products with NO image get one; anything already on a product is left alone. Never use
marketplace images here (owner rule): only files the brand/distributor gave us for our shop.
Env for --apply: WC_URL, WC_KEY, WC_SECRET (products) and WP_USER, WP_APP_PASSWORD (media library;
a WordPress application password, Users > Profile > Application Passwords).
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from rtech_sync.catalogue import load_catalogue  # noqa: E402

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
STOP = {"img", "image", "images", "photo", "pic", "front", "main", "final", "copy", "new", "the", "and",
        "of", "with", "for", "hd", "web", "jpg", "png"}
UNIT_ONLY = re.compile(r"\d+(?:SQMM|MM|M|W|A|HP|KW|V|MA|K|PCS|CORE)")
PAUSE = 2.0


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def model_codes(title: str) -> set:
    out = set()
    for tok in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-./]{3,}[A-Za-z0-9]", title):
        n = _norm(tok)
        if len(n) >= 6 and re.search(r"\d", n) and re.search(r"[A-Z]", n) and not UNIT_ONLY.fullmatch(n):
            out.add(n)
    for m in re.finditer(r"\b(\d{4})\s(\d{2})\b|\b(\d{6})\b", title):
        out.add(m.group(1) + m.group(2) if m.group(1) else m.group(3))
    return out


def _words(s: str) -> list:
    return [w for w in re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", s.lower()) if w not in STOP and len(w) > 1]


def find_images(root: Path) -> list:
    """(path, brand_hint, stem) for every image file under root."""
    out = []
    for p in sorted(root.rglob("*")):
        if p.suffix.lower() in IMAGE_EXT and p.is_file():
            rel = p.relative_to(root).parts
            brand = rel[0] if len(rel) > 1 else ""
            out.append((p, brand, p.stem))
    return out


def plan_matches(rows, images) -> dict:
    """sku -> (image path, how, score)."""
    best = {}
    by_brand = collections.defaultdict(list)
    for r in rows:
        by_brand[r.brand.lower()].append(r)
    for path, brand_hint, stem in images:
        brand = next((b for b in by_brand if b and (b == brand_hint.lower() or stem.lower().startswith(b))), None)
        candidates = by_brand.get(brand, []) if brand else [r for v in by_brand.values() for r in v]
        stem_n = _norm(stem)
        words = [w for w in _words(stem) if not brand or w not in _words(brand)]
        for r in candidates:
            codes = model_codes(r.title)
            if any(c in stem_n for c in codes):
                score, how = 1000 + max(len(c) for c in codes if c in stem_n), "model number"
            elif words and all(re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", r.title.lower())
                               for w in words):
                score, how = len(words), "words"
            else:
                continue
            if r.sku not in best or score > best[r.sku][2]:
                best[r.sku] = (path, how, score)
    return best


class Shop:
    def __init__(self, base, wc_key, wc_secret, wp_user, wp_pass, session=None):
        import requests
        self.base = base.rstrip("/")
        self.s = session or requests.Session()
        self.wc = (wc_key, wc_secret)
        self.wp = (wp_user, wp_pass)

    def products(self, ids):
        out = {}
        for i in range(0, len(ids), 100):
            r = self.s.get(f"{self.base}/wp-json/wc/v3/products", auth=self.wc, timeout=90,
                           params={"include": ",".join(map(str, ids[i:i + 100])), "per_page": 100})
            r.raise_for_status()
            out.update({p["id"]: p for p in r.json()})
            time.sleep(PAUSE / 2)
        return out

    def upload(self, path: Path, alt: str) -> int:
        ctype = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}[
            path.suffix.lower()]
        r = self.s.post(f"{self.base}/wp-json/wp/v2/media", auth=self.wp, timeout=180, data=path.read_bytes(),
                        headers={"Content-Type": ctype,
                                 "Content-Disposition": f'attachment; filename="{path.name}"'})
        if r.status_code not in (200, 201):
            raise RuntimeError(f"media upload {path.name}: HTTP {r.status_code}")
        mid = r.json()["id"]
        self.s.post(f"{self.base}/wp-json/wp/v2/media/{mid}", auth=self.wp, timeout=60, json={"alt_text": alt})
        return mid

    def batch(self, items):
        r = self.s.post(f"{self.base}/wp-json/wc/v3/products/batch", auth=self.wc, timeout=180,
                        json={"update": items})
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--images-dir", required=True)
    ap.add_argument("--catalogue-dir", required=True)
    ap.add_argument("--plan-out", default="brand_images_plan.csv")
    ap.add_argument("--uploaded", default="brand_media_map.json", help="file name -> media id (kept between runs)")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    rows = [r for r in load_catalogue(a.catalogue_dir) if r.wc_product_id and r.publish == "yes"]
    images = find_images(Path(a.images_dir))
    best = plan_matches(rows, images)
    by_sku = {r.sku: r for r in rows}
    with open(a.plan_out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["sku", "title", "image", "matched_by"])
        for sku, (path, how, _) in sorted(best.items()):
            w.writerow([sku, by_sku[sku].title, str(Path(path).relative_to(a.images_dir)), how])
    used = {p for p, _, _ in best.values()}
    print(f"images: {len(images)}, used: {len(used)}, products matched: {len(best)} of {len(rows)}; "
          f"by model number: {sum(1 for v in best.values() if v[1] == 'model number')}")
    if not a.apply:
        return 0
    shop = Shop(os.environ["WC_URL"], os.environ["WC_KEY"], os.environ["WC_SECRET"],
                os.environ["WP_USER"], os.environ["WP_APP_PASSWORD"])
    current = shop.products([by_sku[s].wc_product_id for s in best])
    uploaded = json.loads(Path(a.uploaded).read_text()) if Path(a.uploaded).exists() else {}
    items, done, failed = [], 0, collections.Counter()
    for sku, (path, _, _) in sorted(best.items()):
        cur = current.get(by_sku[sku].wc_product_id)
        if not cur or cur.get("images"):
            failed["already has an image" if cur else "not on shop"] += 1
            continue
        key = str(Path(path).relative_to(a.images_dir))
        if key not in uploaded:
            uploaded[key] = shop.upload(Path(path), by_sku[sku].title)
            Path(a.uploaded).write_text(json.dumps(uploaded, indent=1, sort_keys=True))
            time.sleep(PAUSE)
        items.append({"id": cur["id"], "images": [{"id": uploaded[key]}]})
        if len(items) == 20:
            st, _ = shop.batch(items)
            done += len(items) if st == 200 else 0
            failed["batch failed"] += 0 if st == 200 else len(items)
            items = []
            time.sleep(PAUSE)
    if items:
        st, _ = shop.batch(items)
        done += len(items) if st == 200 else 0
        failed["batch failed"] += 0 if st == 200 else len(items)
    print(f"products given a real image: {done}; not changed: {dict(failed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
