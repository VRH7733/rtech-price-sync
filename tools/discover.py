#!/usr/bin/env python3
"""Find candidate product URLs for a few brands on one marketplace, from its PUBLISHED sitemaps.

  python tools/discover.py --source moglix --brand polycab --brand vip --keyword wire --out out
  python tools/discover.py --source homerun --brand polycab --fetch --max-pages 80 --out out
  python tools/discover.py --source industrybuying --brand havells --fetch --previous old/industrybuying.csv

--skip-catalogue DIR: catalogue rows folder; URLs already used by a product are not fetched or listed.
Candidates are fetched in --brand order (pages whose slug starts with the first brand first), so a
capped run spends its pages on the brands that matter most.

--previous: a CSV from an earlier run. Pages fetched there are copied, not fetched again, so a
second run continues where the first stopped (--max-pages counts only new fetches).

Rules (same as the nightly run): robots.txt is checked for every request by the repo's Fetcher,
>= 3 s per host, honest User-Agent, no search pages. Sitemaps only, plus (with --fetch) the
candidate product pages themselves, capped by --max-pages.

Output: <out>/<source>.csv, one row per candidate URL (HomeRun: one row per variant, as
?variant=ID URLs). Nothing here writes the catalogue: rows are built from this file and reviewed.
"""
import argparse
import csv
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from rtech_sync.config import load_config  # noqa: E402
from rtech_sync.fetcher import Fetcher  # noqa: E402
from rtech_sync.matching import parse_sitemap, slug_text  # noqa: E402
from rtech_sync.parsers import page_variants, parse_product_page  # noqa: E402

ROOT_SITEMAPS = {
    "moglix": "https://www.moglix.com/sitemap_index.xml",
    "industrybuying": "https://www.industrybuying.com/sitemap_index.xml",
    "homerun": "https://home-run.co/sitemap.xml",
}
# child sitemaps that list product pages (seen 15 Oct 2026); others (blog, brand, category) skipped
PRODUCT_SITEMAPS = {
    "moglix": re.compile(r"products", re.I),
    "industrybuying": re.compile(r"sitemap_product_|new_leaf_sku", re.I),
    "homerun": re.compile(r"products", re.I),
}
FIELDS = ["source", "url", "slug", "fetched", "http_status", "title", "variant", "price", "in_stock",
          "tax_basis", "method", "problems", "identity"]


def collect(fetcher, source, brands, keywords, log):
    queue, seen, urls = [ROOT_SITEMAPS[source]], set(), []
    while queue:
        sm = queue.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        if len(seen) > 1 and not PRODUCT_SITEMAPS[source].search(sm):
            continue
        fr = fetcher.get(sm, budget_key=source)
        if fr.status != "ok":
            log(f"skip {sm}: {fr.status} {fr.http} {fr.detail}")
            continue
        try:
            pages, children = parse_sitemap(fr.content or fr.text.encode())
        except Exception as e:  # malformed XML
            log(f"cannot parse {sm}: {type(e).__name__}")
            continue
        n0 = len(urls)
        for u in pages:
            low = u.lower()
            if any(b in low for b in brands) and (not keywords or any(k in low for k in keywords)):
                urls.append(u)
        queue += children
        log(f"{sm}: {len(pages)} pages, {len(children)} child sitemaps, {len(urls) - n0} candidates")
    return sorted(set(urls)), len(seen)


def order_by_brand(urls, brands):
    """First-brand pages first; within a brand, URL order. A slug that only mentions a brand later
    ("high-precision-tape") goes last."""
    def rank(u):
        first = urlparse(u).path.strip("/").split("/")[0].lower()
        return next((i for i, b in enumerate(brands) if first.startswith(b.replace(" ", "-") + "-")), len(brands))
    return sorted(urls, key=lambda u: (rank(u), u))


def catalogue_urls(rows_dir) -> set:
    from rtech_sync.catalogue import load_catalogue
    return {u.split("?variant=")[0] for r in load_catalogue(rows_dir) for u in r.urls.values() if u}


def fetch_rows(fetcher, source, url):
    fr = fetcher.get(url, budget_key=source)
    base = {"source": source, "url": url, "slug": slug_text(url), "fetched": "yes",
            "http_status": f"{fr.status}:{fr.http or ''}"}
    if fr.status != "ok":
        return [base]
    p = parse_product_page(fr.text, url)
    common = dict(base, title=p.title or "", tax_basis=p.tax_basis, method=p.method)
    variants = page_variants(fr.text) if source == "homerun" else []
    if len(variants) > 1:
        out = []
        for v in variants:
            out.append(dict(common, url=f"{url}?variant={v['id']}", variant=v["options"] or v["title"],
                            price=v["price"] or "", in_stock=v["available"],
                            identity=f"{p.title or ''} {v['title']} {v['options']} {v['sku']}".strip()))
        return out
    return [dict(common, price=p.price or "", in_stock=p.in_stock, problems=";".join(p.problems),
                 identity=p.identity_text[:300])]


def load_previous(path) -> dict:
    """Earlier fetched rows by page URL (HomeRun ?variant= rows grouped under their page)."""
    prev = {}
    if not path or not Path(path).exists():
        return prev
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("fetched") == "yes":
                prev.setdefault(r["url"].split("?variant=")[0], []).append({k: r.get(k, "") for k in FIELDS})
    return prev


def plan_rows(urls, prev, fetch, max_pages, fetch_one):
    rows, fetched = [], 0
    for u in urls:
        if u in prev:
            rows += prev[u]
        elif fetch and fetched < max_pages:
            rows += fetch_one(u)
            fetched += 1
        else:
            rows.append({"source": "", "url": u, "slug": slug_text(u), "fetched": "no"})
    return rows, fetched


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", required=True, choices=list(ROOT_SITEMAPS))
    ap.add_argument("--brand", action="append", required=True)
    ap.add_argument("--keyword", action="append", default=[], help="URL must also contain one of these")
    ap.add_argument("--fetch", action="store_true", help="also fetch candidate pages (IB/HomeRun)")
    ap.add_argument("--max-pages", type=int, default=100)
    ap.add_argument("--previous", default="", help="earlier <source>.csv: reuse its fetched pages")
    ap.add_argument("--skip-catalogue", default="", help="catalogue rows dir: skip URLs it already uses")
    ap.add_argument("--out", default="out")
    ap.add_argument("--config", default=os.path.join(os.path.dirname(__file__), "..", "config.yaml"))
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    cfg.fetch.require_contact_email()
    fetcher = Fetcher(cfg.fetch)
    brands = [b.lower() for b in a.brand]
    keywords = [k.lower() for k in a.keyword]

    t0 = time.monotonic()
    urls, n_sitemaps = collect(fetcher, a.source, brands, keywords, print)
    print(f"{a.source}: {len(urls)} candidate URLs from {n_sitemaps} sitemaps")
    if not urls:  # a blocked or empty sitemap must not overwrite earlier results with nothing
        print(f"{a.source}: no candidate URLs; nothing written")
        return 1
    if a.skip_catalogue:
        used = catalogue_urls(a.skip_catalogue)
        n0 = len(urls)
        urls = [u for u in urls if u not in used]
        print(f"{a.source}: {n0 - len(urls)} candidates already in the catalogue, skipped")
    urls = order_by_brand(urls, brands)
    prev = load_previous(a.previous)
    rows, fetched = plan_rows(urls, prev, a.fetch, a.max_pages, lambda u: fetch_rows(fetcher, a.source, u))
    for r in rows:
        r["source"] = a.source
    print(f"{a.source}: {fetched} pages fetched now, {sum(1 for u in urls if u in prev)} reused from --previous")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / f"{a.source}.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    log = getattr(fetcher, "request_log", {})
    print(f"{a.source}: wrote {len(rows)} rows; requests per host {dict(log)}; "
          f"{(time.monotonic() - t0) / 60:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
