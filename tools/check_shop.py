#!/usr/bin/env python3
"""Read-only check of what customers see on the shop after a price run.

Usage: check_shop.py <latest.json> <report.md> [sample_pages]
Env:   WC_URL (the shop's address), CONTACT_EMAIL

1. Reads every product from the public Store API and compares it with the run's own record
   (latest.json): a product the run priced should be a simple product at that price, one it
   left without a price should show the Request a Quote button.
2. Opens a random sample of public product pages, the pages customers see through the
   LiteSpeed cache, and checks the shown price (or quote button) the same way.

Only counts go to the log (the code repo is public). SKUs and prices go to the report,
which the workflow saves in the private data repo.
"""
import html
import json
import os
import random
import re
import sys
import time
import urllib.request
from decimal import Decimal, InvalidOperation

BASE = os.environ["WC_URL"].rstrip("/")
UA = f"rtech-price-sync/0.1 (+mailto:{os.environ.get('CONTACT_EMAIL', 'unset')})"
PAUSE_SECONDS = 1.5
QUOTE = "request a quote"


def expected_state(latest: dict) -> dict:
    """sku -> Decimal price the shop should show, or None for Request a Quote."""
    out = {}
    for sku, st in latest.get("items", {}).items():
        price = st.get("price")
        out[sku] = None if st.get("hidden") or not price else Decimal(str(price))
    return out


def store_state(p: dict):
    """(price or None, is_quote) of one Store API product."""
    prices = p.get("prices") or {}
    raw = prices.get("price") or ""
    price = None
    if raw and Decimal(raw) != 0:  # the Store API gives "0" for a product with no price
        price = Decimal(raw) / (Decimal(10) ** int(prices.get("currency_minor_unit", 2)))
    text = ((p.get("add_to_cart") or {}).get("text") or "").lower()
    return price, p.get("type") == "external" and QUOTE in text


def page_state(page: str):
    """(price or None, is_quote) of a product page's main price block and button."""
    m = re.search(r'<p[^>]*class="[^"]*\bprice\b[^"]*"[^>]*>(.*?)</p>', page, re.S)
    price = None
    if m:
        ins = re.search(r"<ins[^>]*>(.*?)</ins>", m.group(1), re.S)  # sale price
        text = re.sub(r"<[^>]+>", "", html.unescape(ins.group(1) if ins else m.group(1)))
        amt = re.search(r"(?:₹|Rs\.?)\s*([\d,]+(?:\.\d+)?)", text)
        if amt:
            try:
                price = Decimal(amt.group(1).replace(",", ""))
            except InvalidOperation:
                price = None
    button = re.search(r'<[^>]*single_add_to_cart_button[^>]*>(.*?)</', page, re.S)
    quote = bool(button) and QUOTE in html.unescape(button.group(1)).lower()
    return price, quote


def verdict(want, got_price, got_quote) -> str:
    if want is None:
        return "ok_quote" if got_quote and got_price is None else "should_be_quote"
    if got_price is None:
        return "missing_price"
    return "ok_price" if got_price == want else "wrong_price"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", "replace"), resp.headers


def store_products():
    items, page = [], 1
    while True:
        body, headers = get(f"{BASE}/wp-json/wc/store/v1/products?per_page=100&page={page}")
        items.extend(json.loads(body))
        if page >= int(headers.get("X-WP-TotalPages", "1")):
            return items
        page += 1
        time.sleep(PAUSE_SECONDS)


def tally(rows):
    out = {}
    for _, v, *_ in rows:
        out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items()))


def main(latest_path, report_path, sample=40):
    want = expected_state(json.load(open(latest_path)))
    products = [p for p in store_products() if p.get("sku") in want]
    api_rows, links = [], {}
    for p in products:
        price, quote = store_state(p)
        api_rows.append((p["sku"], verdict(want[p["sku"]], price, quote), want[p["sku"]], price))
        links[p["sku"]] = p.get("permalink")
    shop_priced = sum(1 for p in products if store_state(p)[0] is not None)
    shop_quote = sum(1 for p in products if store_state(p)[1])

    rng = random.Random()
    picks = rng.sample(sorted(links), min(sample, len(links)))
    page_rows = []
    for sku in picks:
        time.sleep(PAUSE_SECONDS)
        try:
            body, headers = get(links[sku])
        except Exception as err:  # report, never retry around a block
            page_rows.append((sku, f"fetch_failed {type(err).__name__}", want[sku], None, ""))
            continue
        price, quote = page_state(body)
        cache = headers.get("x-litespeed-cache", "")
        page_rows.append((sku, verdict(want[sku], price, quote), want[sku], price, cache))

    lines = ["# Shop check", "",
             f"- Products in the run's record: {len(want)}; found on the shop: {len(products)}",
             f"- Shop now: {shop_priced} with a price, {shop_quote} with Request a Quote",
             f"- Store API vs run record: {tally(api_rows)}",
             f"- {len(page_rows)} random product pages vs run record: {tally(page_rows)}", "",
             "| page check | sku | verdict | expected | shown | cache |", "|---|---|---|---|---|---|"]
    for sku, v, w, g, c in page_rows:
        lines.append(f"| page | {sku} | {v} | {w} | {g} | {c} |")
    for sku, v, w, g in api_rows:
        if not v.startswith("ok"):
            lines.append(f"| api | {sku} | {v} | {w} | {g} | |")
    os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
    with open(report_path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print(lines[2]); print(lines[3]); print(lines[4]); print(lines[5])


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 40)
