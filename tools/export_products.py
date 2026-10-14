#!/usr/bin/env python3
"""Read-only export of all WooCommerce products and variations to JSON.

Usage: export_products.py <output_dir>
Env:   WC_URL, WC_KEY, WC_SECRET, CONTACT_EMAIL
Prints only counts. Product data goes to files, never to the log.
"""
import base64
import collections
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ["WC_URL"].rstrip("/")
AUTH = base64.b64encode(
    f"{os.environ['WC_KEY']}:{os.environ['WC_SECRET']}".encode()
).decode()
UA = f"rtech-price-sync/0.1 (+mailto:{os.environ.get('CONTACT_EMAIL', 'unset')})"
PAUSE_SECONDS = 1.5


def get(path):
    """GET with one backoff retry on 429/5xx. Returns (json, headers)."""
    url = f"{BASE}/wp-json/wc/v3/{path}"
    for attempt in (1, 2):
        req = urllib.request.Request(
            url, headers={"Authorization": f"Basic {AUTH}", "User-Agent": UA}
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp), resp.headers
        except urllib.error.HTTPError as err:
            if attempt == 1 and err.code in (429, 500, 502, 503, 508):
                time.sleep(20)
                continue
            raise
    raise RuntimeError("unreachable")


def paged(path):
    items, page = [], 1
    while True:
        sep = "&" if "?" in path else "?"
        data, headers = get(f"{path}{sep}per_page=100&page={page}")
        items.extend(data)
        total_pages = int(headers.get("X-WP-TotalPages", "1"))
        if page >= total_pages:
            return items
        page += 1
        time.sleep(PAUSE_SECONDS)


def main(out_dir):
    products = paged("products")
    time.sleep(PAUSE_SECONDS)
    n_variations = 0
    for product in products:
        if product.get("type") == "variable":
            product["_variations"] = paged(f"products/{product['id']}/variations")
            n_variations += len(product["_variations"])
            time.sleep(PAUSE_SECONDS)

    today = datetime.date.today().isoformat()
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, f"products-{today}.json"), "w") as fh:
        json.dump(
            {"exported_at": today, "count": len(products), "products": products},
            fh,
            indent=1,
        )

    meta_keys = collections.Counter()
    for product in products:
        for meta in product.get("meta_data", []):
            meta_keys[meta.get("key")] += 1
        for var in product.get("_variations", []):
            for meta in var.get("meta_data", []):
                meta_keys["var:" + str(meta.get("key"))] += 1
    summary = {
        "products": len(products),
        "variations": n_variations,
        "by_type": collections.Counter(p.get("type") for p in products),
        "by_status": collections.Counter(p.get("status") for p in products),
        "by_stock_status": collections.Counter(p.get("stock_status") for p in products),
        "variation_stock_status": collections.Counter(
            v.get("stock_status")
            for p in products
            for v in p.get("_variations", [])
        ),
        "products_with_empty_price": sum(1 for p in products if not p.get("price")),
        "variations_with_empty_price": sum(
            1 for p in products for v in p.get("_variations", []) if not v.get("price")
        ),
        "manage_stock_true": sum(1 for p in products if p.get("manage_stock")),
        "meta_keys": dict(meta_keys),
    }
    with open(os.path.join(out_dir, f"summary-{today}.json"), "w") as fh:
        json.dump(summary, fh, indent=1)
    print(f"exported {len(products)} products and {n_variations} variations")


if __name__ == "__main__":
    main(sys.argv[1])
