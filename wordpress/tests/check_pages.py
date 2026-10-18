#!/usr/bin/env python3
"""Checks the test shop's pages after rtech-ai-seo is active. Exit 1 on any failure.

Usage: check_pages.py <base url> <debug.log path>
"""
import json
import re
import sys
import urllib.request

BASE = sys.argv[1].rstrip("/")
fails = []


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=60) as r:
        return r.status, r.headers.get("content-type", ""), r.read().decode("utf-8", "replace")


def ld(page):
    out = []
    for raw in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', page, re.S):
        d = json.loads(raw)
        nodes = d.get("@graph", [d]) if isinstance(d, dict) else d
        out.extend(nodes)
    return out


def meta(page, name):
    m = re.search(r'<meta[^>]+(?:name|property)="' + re.escape(name) + r'"[^>]+content="([^"]*)"', page)
    return m.group(1) if m else None


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)


site = [n for n in ld(get("/")[2]) if n.get("@type") == "WebSite"]
if site:
    check(site[0].get("name") == "RTechElectricals", f"home: WebSite name ({site[0].get('name')})")

for slug, priced in (("priced-cable", True), ("quote-switch", False)):
    s, _, page = get(f"/product/{slug}/")
    check(s == 200, f"{slug}: HTTP 200")
    nodes = ld(page)
    prods = [n for n in nodes if n.get("@type") == "Product"]
    check(len(prods) == 1, f"{slug}: exactly one Product node (got {len(prods)})")
    if prods:
        p = prods[0]
        print("     Product:", json.dumps(p, ensure_ascii=False)[:700])
        check(p.get("brand", {}).get("name") == "Havells", f"{slug}: brand Havells")
        check(p.get("name", "").startswith("Havells") and "rtechelectricals" not in p.get("name", "").lower(), f"{slug}: product name without the shop name")
        check("HavellsSize" not in p.get("description", "") and "Brand:" not in p.get("description", ""),
              f"{slug}: clean description")
        check(bool(p.get("category")), f"{slug}: category set")
        check("&" not in p.get("category", "") and " and " in p.get("category", ""), f"{slug}: category reads 'and', no &amp;")
        if priced:
            o = p.get("offers", [{}])
            o = o[0] if isinstance(o, list) else o
            check(o.get("itemCondition", "").endswith("NewCondition"), f"{slug}: itemCondition")
            check(o.get("seller", {}).get("name") == "RTechElectricals", f"{slug}: seller name")
        else:
            check("offers" not in p, f"{slug}: no invented offer")
    crumbs = [n for n in nodes if n.get("@type") == "BreadcrumbList"]
    names = [e["item"]["name"] for c in crumbs for e in c.get("itemListElement", [])]
    check(names and not any("&" in n for n in names), f"{slug}: breadcrumb names without &amp; {names}")
    check("Search Engine Optimization by Rank Math" in page or "rank-math" in page, f"{slug}: Rank Math is printing the head")
    title = re.search(r"<title>(.*?)</title>", page, re.S).group(1)
    print("     title:", title)
    check(title.endswith("| RTechElectricals"), f"{slug}: title ends with | RTechElectricals")
    desc = meta(page, "description")
    print("     description:", desc)
    check(desc is not None and "HavellsSize" not in desc and len(desc) <= 160, f"{slug}: meta description clean, <=160")
    check(meta(page, "og:description") == desc, f"{slug}: og:description matches")

s, _, home = get("/")
check(s == 200, "home: HTTP 200")
print("     home description:", meta(home, "description"))
check("Havells" in (meta(home, "description") or ""), "home: description names the main brands")
org = [n for n in ld(home) if n.get("@type") == "Organization"]
if org:
    check(org[0].get("name") == "RTechElectricals", f"home: Organization name ({org[0].get('name')})")

s, ctype, llms = get("/llms.txt")
print(llms)
check(s == 200 and ctype.startswith("text/plain"), "llms.txt: 200 text/plain")
check(llms.startswith("# RTechElectricals"), "llms.txt: heading")
check("Wires & Cables" in llms and "[Havells]" in llms and "Contact Us" in llms, "llms.txt: categories, brands, pages")

log = open(sys.argv[2]).read() if len(sys.argv) > 2 else ""
mine = [l for l in log.splitlines() if "rtech-ai-seo" in l]
for l in mine[:20]:
    print("     log:", l)
check(not mine, "debug.log: no PHP notices, warnings or errors from the plugin")

print(f"\n{len(fails)} failure(s)")
sys.exit(1 if fails else 0)
