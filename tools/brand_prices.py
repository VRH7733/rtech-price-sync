#!/usr/bin/env python3
"""Read official MRPs from the brands' own shops for products no marketplace prices.

  python tools/brand_prices.py DATA_REPO_DIR

Owner, 18 Oct 2026 ("option c"): a product with no marketplace price shows the brand's official
MRP instead of Request a Quote (src/rtech_sync/run.py apply_brand_prices; marketplace prices
always win, no discount on MRP).

Which products: Request a Quote products (hidden, or never priced) plus those already priced from
here, whose brand page is known in brand-images/plan.csv (written by the photos tool, one page
per product, matched on the model number). Today: havells.com only.

Rules (same as the marketplaces): robots.txt and its Crawl-delay obeyed by the repo's Fetcher,
>= the configured delay per host, honest User-Agent, only those product pages. A page counts only
when it shows the same model number (its SKU field) and an MRP. Five refusals in a row stop the
brand for the run.

Writes DATA_REPO_DIR/data/brand_prices.json: {"items": {sku: {mrp, price, url, code, date}}}.
Entries not re-read keep their old date (the run ignores them after pricing.brand_price_days).
"""
import csv
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from rtech_sync.catalogue import load_catalogue  # noqa: E402
from rtech_sync.config import load_config  # noqa: E402
from rtech_sync.fetcher import Fetcher  # noqa: E402

HOSTS = {"havells.com": "Havells", "shop.legrand.co.in": "Legrand"}
LEGRAND_SHOP = "https://shop.legrand.co.in"
LEGRAND_CATEGORIES = ("switches-accessories", "protection", "connected-switches", "desktop-power-center",
                      "health-safety")
MAX_LISTING_PAGES = 60  # per category
STOP_AFTER = 5
_AMOUNT = re.compile(r'data-price-amount="([\d.]+)"\s*data-price-type="(\w+)"')
_SKU = re.compile(r'itemprop="sku">\s*([^<\s]+)\s*<')


def _code(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def magento_price(html: str, code: str):
    """(mrp, selling price) from a Magento product page that shows this model number, else None.
    The main product's price box follows "product-info-price"; related products come later."""
    skus = _SKU.findall(html)
    if not code or _code(code) not in {_code(s) for s in skus}:
        return None
    i = html.find("product-info-price")
    if i < 0:
        return None
    found = dict((t, a) for a, t in reversed(_AMOUNT.findall(html[i:i + 6000])))
    final, old = found.get("finalPrice"), found.get("oldPrice")
    mrp = old or final  # no oldPrice: no offer, the regular price is the MRP
    if not mrp or float(mrp) <= 0:
        return None
    return mrp, final or mrp


def legrand_listing(html: str) -> dict:
    """{catalogue number: page URL} from one shop.legrand.co.in category listing page."""
    out = {}
    for item in html.split('class="item product product-item"')[1:]:
        code = re.search(r"/lg-(\d{6})[-_]", item)
        link = re.search(r'class="product-item-link"\s+href="(https://shop\.legrand\.co\.in/[^"?#]+)"', item)
        if code and link:
            out.setdefault(code.group(1), link.group(1))
    return out


def legrand_pages(fetcher, log=print) -> dict:
    pages = {}
    for cat in LEGRAND_CATEGORIES:
        for n in range(1, MAX_LISTING_PAGES + 1):
            fr = fetcher.get(f"{LEGRAND_SHOP}/{cat}?product_list_limit=36&p={n}", budget_key="shop.legrand.co.in")
            if fr.status != "ok" or not fr.text:
                log(f"legrand {cat} p{n}: {fr.status} {fr.http or ''}")
                break
            got = legrand_listing(fr.text)
            new = {c: u for c, u in got.items() if c not in pages}
            pages.update(new)
            if not new or not re.search(r'class="action\s+next"', fr.text):
                break
        log(f"legrand {cat}: {len(pages)} products so far")
    return pages


def targets(rows, state, plan, known, legrand=None):
    by_sku = {r.sku: r for r in rows if r.publish == "yes"}
    out = []
    for p in plan:
        sku, url, code = p.get("sku", ""), p.get("page_url", ""), p.get("code", "")
        row = by_sku.get(sku)
        if row and row.brand == "Legrand" and legrand is not None:
            url = legrand.get(_code(code), "")
        if not row or not url or not code or urlparse(url).netloc not in HOSTS:
            continue
        s = state.get(sku, {})
        quote = s.get("hidden") or not s.get("price")
        if quote or sku in known:
            out.append((sku, url, code))
    return out


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    data = Path(argv[0])
    lines = []

    def print(*a):  # also kept in the data repo: Actions logs cannot be read from the container
        msg = " ".join(str(x) for x in a)
        lines.append(msg)
        sys.stdout.write(msg + "\n")

    cfg = load_config(os.path.join(os.path.dirname(__file__), "..", "config.yaml"))
    cfg.fetch.require_contact_email()
    rows = load_catalogue(data / "catalogue" / "rows")
    state = json.loads((data / "data" / "latest.json").read_text(encoding="utf-8")).get("items", {})
    with open(data / "brand-images" / "plan.csv", newline="", encoding="utf-8") as fh:
        plan = list(csv.DictReader(fh))
    out_path = data / "data" / "brand_prices.json"
    known = {}
    if out_path.exists():
        known = json.loads(out_path.read_text(encoding="utf-8")).get("items", {})
    today = datetime.now(ZoneInfo(cfg.timezone)).date().isoformat()
    fetcher = Fetcher(cfg.fetch)
    legrand = legrand_pages(fetcher, log=print)
    todo = targets(rows, state, plan, known, legrand)
    print(f"{len(todo)} products to read")
    refused, stopped, n_ok, n_bad = {}, set(), 0, 0
    for sku, url, code in todo:
        host = urlparse(url).netloc
        if host in stopped:
            continue
        fr = fetcher.get(url, budget_key=host)
        if fr.status in ("blocked", "robots_blocked"):
            refused[host] = refused.get(host, 0) + 1
            if refused[host] >= STOP_AFTER:
                stopped.add(host)
                print(f"{host}: {STOP_AFTER} refusals in a row, stopped for this run")
            continue
        refused[host] = 0
        got = magento_price(fr.text, code) if fr.status == "ok" and fr.text else None
        if not got:
            n_bad += 1
            print(f"{sku}: no MRP for {code} ({fr.status} {fr.http or ''})")
            continue
        mrp, price = got
        known[sku] = {"mrp": mrp, "price": price, "url": url, "code": code, "date": today}
        n_ok += 1
    out_path.write_text(json.dumps({"items": dict(sorted(known.items()))}, indent=1) + "\n", encoding="utf-8")
    print(f"brand MRPs read: {n_ok}; without an MRP: {n_bad}; stopped: {sorted(stopped) or 'none'}; "
          f"requests per host {dict(getattr(fetcher, 'request_log', {}))}")
    (data / "data" / "brand_prices_log.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
