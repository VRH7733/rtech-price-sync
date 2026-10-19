#!/usr/bin/env python3
"""Read-only check of what search engines and AI assistants can read on the shop.

Usage: seo_audit.py <report.md>
Env:   WC_URL (the shop's address), CONTACT_EMAIL

Opens about 20 PUBLIC pages, slowly, with the honest User-Agent: the home page, robots.txt,
llms.txt, the sitemaps, the REST index (it names the installed plugins' namespaces), the shop page
and a few product pages (some priced, some Request a Quote). For each page it records the title,
meta description, canonical, Open Graph tags, the JSON-LD types and the full Product JSON-LD.
It never pretends to be a search engine or AI crawler. The log gets status lines only; the full
report goes to the PRIVATE data repo.
"""
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ["WC_URL"].rstrip("/")
UA = f"rtech-price-sync/0.1 (+mailto:{os.environ.get('CONTACT_EMAIL', 'unset')})"
PAUSE_SECONDS = 2.0
HEADERS_KEPT = ("server", "x-litespeed-cache", "x-robots-tag", "cf-ray", "content-type",
                "x-powered-by", "link", "platform", "x-turbo-charged-by", "cache-control")


def get(url):
    """(status, headers dict, body) without raising on HTTP errors."""
    time.sleep(PAUSE_SECONDS)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, \
                resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        return err.code, {k.lower(): v for k, v in err.headers.items()}, \
            err.read().decode("utf-8", "replace")
    except Exception as err:  # report, never retry around a block
        return f"failed {type(err).__name__}", {}, ""


def meta(page, attr, name):
    for tag in re.findall(r"<meta\b[^>]*>", page, re.I):
        if re.search(rf'{attr}\s*=\s*["\']{re.escape(name)}["\']', tag, re.I):
            m = re.search(r'content\s*=\s*"([^"]*)"|content\s*=\s*\'([^\']*)\'', tag, re.I)
            if m:
                return html.unescape(m.group(1) if m.group(1) is not None else m.group(2))
    return None


def json_ld(page):
    out = []
    for raw in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', page, re.S | re.I):
        try:
            out.append(json.loads(raw))
        except ValueError:
            out.append({"_unparsed": raw[:300]})
    return out


def ld_types(blocks):
    types = []

    def walk(node):
        if isinstance(node, list):
            for n in node:
                walk(n)
        elif isinstance(node, dict):
            t = node.get("@type")
            if t:
                types.extend(t if isinstance(t, list) else [t])
            for k in ("@graph",):
                if k in node:
                    walk(node[k])
    walk(blocks)
    return types


def describe(page):
    title = re.search(r"<title[^>]*>(.*?)</title>", page, re.S | re.I)
    canon = re.search(r'<link[^>]*rel=["\']canonical["\'][^>]*href=["\']([^"\']+)', page, re.I)
    h1 = re.findall(r"<h1[^>]*>(.*?)</h1>", page, re.S | re.I)
    lang = re.search(r"<html[^>]*\blang=[\"']([^\"']+)", page, re.I)
    gens = re.findall(r'<meta[^>]*name=["\']generator["\'][^>]*content=["\']([^"\']+)', page, re.I)
    markers = [m for m in ("yoast", "rank-math", "rankmath", "aioseo", "seopress", "the-seo-framework",
                           "litespeed", "schema", "woocommerce-structured-data")
               if m in page.lower()]
    blocks = json_ld(page)
    return {
        "lang": lang.group(1) if lang else None,
        "title": html.unescape(re.sub(r"\s+", " ", title.group(1)).strip()) if title else None,
        "meta description": meta(page, "name", "description"),
        "meta robots": meta(page, "name", "robots"),
        "canonical": canon.group(1) if canon else None,
        "og:title": meta(page, "property", "og:title"),
        "og:description": meta(page, "property", "og:description"),
        "og:image": meta(page, "property", "og:image"),
        "og:type": meta(page, "property", "og:type"),
        "twitter:card": meta(page, "name", "twitter:card"),
        "h1": [re.sub(r"<[^>]+>", "", h).strip()[:120] for h in h1][:3],
        "generator": gens,
        "site verification": {n: meta(page, "name", n) for n in (
            "google-site-verification", "msvalidate.01", "yandex-verification", "p:domain_verify",
            "facebook-domain-verification") if meta(page, "name", n)},
        "analytics tags": [m for m in ("googletagmanager.com", "gtag(", "google-analytics.com", "clarity.ms",
                                       "site-kit") if m in page],
        "markers in html": markers,
        "json-ld types": ld_types(blocks),
        "_blocks": blocks,
        "bytes": len(page),
    }


def section(lines, name, url, status, headers, body=None, info=None, full_ld=False, raw=False):
    lines += [f"## {name}", "", f"- URL: {url}", f"- HTTP: {status}"]
    for h in HEADERS_KEPT:
        if h in headers:
            lines.append(f"- header {h}: {headers[h][:300]}")
    if info:
        for k, v in info.items():
            if not k.startswith("_"):
                lines.append(f"- {k}: {v}")
        if full_ld and info.get("_blocks"):
            lines += ["", "```json", json.dumps(info["_blocks"], indent=1, ensure_ascii=False)[:12000], "```"]
    if raw and body is not None:
        lines += ["", "```", body[:6000], "```"]
    elif status != 200 and body:
        # a refusal page usually names who refused (host firewall, CDN, security plugin)
        lines += ["", "refusal body (start):", "```", re.sub(r"\s+", " ", body)[:1500], "```"]
    lines.append("")
    print(f"{name}: HTTP {status}")


def main(report_path):
    lines = ["# SEO / AI readability audit", "", f"- Run: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}", ""]

    s, h, b = get(BASE + "/")
    section(lines, "Home page", BASE + "/", s, h, b, describe(b) if s == 200 else None, full_ld=True)

    for path in ("/robots.txt", "/llms.txt", "/llms-full.txt", "/ai.txt"):
        s, h, b = get(BASE + path)
        section(lines, path, BASE + path, s, h, b, raw=(s == 200))

    for path in ("/sitemap_index.xml", "/wp-sitemap.xml", "/sitemap.xml", "/product-sitemap.xml"):
        s, h, b = get(BASE + path)
        locs = re.findall(r"<loc>([^<]+)</loc>", b) if s == 200 else []
        section(lines, path, BASE + path, s, h)
        lines[-1:-1] = [f"- <loc> entries: {len(locs)}; first: {locs[:12]}"]

    s, h, b = get(BASE + "/wp-json/")
    ns = []
    if s == 200:
        try:
            d = json.loads(b)
            ns = d.get("namespaces", [])
            lines_extra = [f"- site name: {d.get('name')}", f"- description: {d.get('description')}",
                           f"- url: {d.get('url')}", f"- namespaces: {ns}"]
        except ValueError:
            lines_extra = ["- not JSON"]
    else:
        lines_extra = []
    section(lines, "REST index (installed plugin namespaces)", BASE + "/wp-json/", s, h)
    lines[-1:-1] = lines_extra

    s, h, b = get(BASE + "/shop/")
    section(lines, "Shop page", BASE + "/shop/", s, h, b, describe(b) if s == 200 else None)

    # The public Store API and core REST routes the shop checks use, recorded one by one.
    for path in ("/wp-json/wc/store/v1/products?per_page=1", "/wp-json/wp/v2/types",
                 "/wp-json/wc/store/v1/products/categories?per_page=1"):
        s, h, b = get(BASE + path)
        section(lines, f"REST {path}", BASE + path, s, h, b)

    # Product pages: 3 with a price and 3 without, from the public Store API.
    picks = []
    for params, want in (("on_sale=false&orderby=price&order=desc", "priced"), ("orderby=date&order=asc", "any")):
        s, h, b = get(f"{BASE}/wp-json/wc/store/v1/products?per_page=40&{params}")
        if s != 200:
            continue
        for p in json.loads(b):
            price = (p.get("prices") or {}).get("price") or "0"
            priced = price not in ("", "0")
            if want == "priced" and priced and sum(1 for x in picks if x[1]) < 3:
                picks.append((p["permalink"], True, p.get("sku")))
            if want == "any" and not priced and sum(1 for x in picks if not x[1]) < 3:
                picks.append((p["permalink"], False, p.get("sku")))
    if not picks:  # Store API refused: take product pages from the sitemap instead
        s, h, b = get(BASE + "/product-sitemap1.xml")
        section(lines, "/product-sitemap1.xml", BASE + "/product-sitemap1.xml", s, h, b)
        for url in (re.findall(r"<loc>([^<]+/product/[^<]+)</loc>", b) if s == 200 else [])[:4]:
            picks.append((url, None, "from sitemap"))
    # a category page too
    s, h, b = get(f"{BASE}/wp-json/wc/store/v1/products/categories?per_page=5&orderby=count&order=desc")
    if s == 200:
        cats = [c for c in json.loads(b) if c.get("count")]
        if cats:
            s, h, b = get(cats[0]["permalink"])
            section(lines, f"Category page ({cats[0]['name']})", cats[0]["permalink"], s, h, b,
                    describe(b) if s == 200 else None)
    for url, priced, sku in picks:
        s, h, b = get(url)
        section(lines, f"Product page ({ {True: 'priced', False: 'Request a Quote', None: 'sitemap'}[priced] }, {sku})", url, s, h, b,
                describe(b) if s == 200 else None, full_ld=True)

    os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
    with open(report_path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"pages checked: {len(picks) + 12}; namespaces: {len(ns)}")


if __name__ == "__main__":
    main(sys.argv[1])
