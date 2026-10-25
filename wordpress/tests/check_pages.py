#!/usr/bin/env python3
"""Checks the test shop's pages after rtech-ai-seo is active. Exit 1 on any failure.

Usage: check_pages.py <base url> <debug.log path>
"""
import html
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
        print(f"::error::{msg}")  # an annotation: readable from the run's check results
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
    if crumbs:  # Rank Math's own schema prints no breadcrumb list unless its breadcrumbs are on
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
def types(n):
    t = n.get("@type")
    return t if isinstance(t, list) else [t]


org = [n for n in ld(home) if "Organization" in types(n)]
if org:
    o = org[0]
    print("     Organization:", json.dumps(o, ensure_ascii=False)[:600])
    check(o.get("name") == "RTechElectricals", f"home: Organization name ({o.get('name')})")
    check("Store" in types(o), "home: business is a Store (local business)")
    check(o.get("address", {}).get("postalCode") == "560065" and o["address"].get("addressLocality") == "Bengaluru",
          "home: Bengaluru address with PIN 560065")
    check(o.get("telephone", "").startswith("+91"), "home: phone")

bar = re.search(r'<section class="rtech-brands-bar".*?</section>', home, re.S)
print("     brands bar:", bar.group(0)[:600] if bar else None)
check(bool(bar) and "Authorised dealer for" in bar.group(0) and "We also supply all other major electrical brands" in bar.group(0),
      "home: brands line shown")
check(bool(bar) and '/brand/havells/">Havells</a>' in bar.group(0) and "L&amp;T" in bar.group(0),
      "home: brands line links dealer brands, escapes names")
check(home.count('class="rtech-brands-bar"') == 1, "home: brands line printed once")
check(bool(bar) and 'custom-panel-boards-cable-trays/">custom panel boards and cable trays</a>' in bar.group(0),
      "home: brands line links the published panel boards page")
if org:
    check("all other major electrical brands" in org[0].get("description", ""), "home: business data says all brands supplied")
    names = [o["itemOffered"]["name"] for o in org[0].get("hasOfferCatalog", {}).get("itemListElement", [])]
    check(names == ["Custom electrical panel boards", "Cable trays made to size"], f"home: business data lists the made-to-order work {names}")

s, _, shop = get("/shop/")
if s == 200:
    d = meta(shop, "description") or ""
    print("     shop description:", d)
    check("Havells" in d and "ABB" not in d, "shop: description names the main brands")
s, _, cat = get("/product-category/wires-cables/")
d = meta(cat, "description") or ""
print("     category description:", d)
check(d.startswith("Buy Wires & Cables in Bengaluru") or d.startswith("Buy Wires &amp; Cables in Bengaluru"),
      "category: description says what and where")
check("Havells" in d, "category: description names the brands in it")

t = re.search(r"<title>(.*?)</title>", cat, re.S)
t = html.unescape(t.group(1)) if t else ""
print("     category title:", t)
check(t.startswith("Wires & Cables in Bengaluru") and t.endswith("| RTechElectricals") and len(t) <= 65,
      "category: title says what and where, replaces the saved generic one")

s, _, brand = get("/brand/havells/")
check(s == 200, "brand page: HTTP 200")
t = re.search(r"<title>(.*?)</title>", brand, re.S)
t = html.unescape(t.group(1)) if t else ""
d = html.unescape(meta(brand, "description") or "")
print("     brand title:", t)
print("     brand description:", d)
check(t.startswith("Havells Dealer in Bengaluru") and "Wires" in t, "brand page: title names the brand, city and categories")
check(d.startswith("Buy Havells in Bengaluru") and "Wires & Cables" in d, f"brand page: description ({d})")

if org:
    check(org[0].get("sameAs") == ["https://www.facebook.com/rtech-test", "https://g.page/rtech-test", "https://share.google/cDnzcwB3UO6bpJeWk"],
          f"home: sameAs lists the shop's other pages, drops non-links ({org[0].get('sameAs')})")

s, _, smap = get("/sitemap_index.xml")
locs = re.findall(r"<loc>([^<]+)</loc>", smap)
print("     sitemaps:", locs)
check(any("product_cat-sitemap" in l for l in locs), "sitemap: category pages listed")
check(any("product_brand-sitemap" in l for l in locs), "sitemap: brand pages listed")

s, _, contact = get("/contact-us/")
check("info@ramtechautomation.com" not in contact and "gmail.com" not in contact.lower(), "contact page: old .com and Gmail addresses gone")
check('mailto:info@ramtechautomation.co.in' in contact, "contact page: business email in their place")

s, ctype, llms = get("/llms.txt")
print(llms)
check(s == 200 and ctype.startswith("text/plain"), "llms.txt: 200 text/plain")
check(llms.startswith("# RTechElectricals"), "llms.txt: heading")
check("Wires & Cables" in llms and "[Havells]" in llms and "Contact Us" in llms, "llms.txt: categories, brands, pages")
check("560065" in llms and "Phone: +91" in llms, "llms.txt: address and phone")
check("Also on: https://g.page/rtech-test" in llms, "llms.txt: the shop's other pages")
check("custom electrical panel boards and cable trays" in llms, "llms.txt: made-to-order work")
check("- Authorised dealer for: Havells, Legrand" in llms and "all other major electrical brands" in llms,
      "llms.txt: dealer brands and other brands")

import xml.etree.ElementTree as ET
s, ctype, feed = get("/google-merchant-feed.xml")
print(feed[:2500])
check(s == 200 and "xml" in ctype, f"feed: 200 XML ({s} {ctype})")
G = "{http://base.google.com/ns/1.0}"
try:
    items = ET.fromstring(feed.encode("utf-8")).findall("./channel/item")
except ET.ParseError as e:
    items = []
    check(False, f"feed: valid XML ({e})")
ids = [i.findtext(G + "id") for i in items]
check(ids == ["RT-HAVE-0900"], f"feed: only the priced product with a photo, not hidden, not Request a Quote ({ids})")
if items:
    it = items[0]
    def g(tag):
        return it.findtext(G + tag)
    check(g("title") == "Havells Life Line Plus S3 HRFR 1.5 Sq.mm Wire 90 m & Red", f"feed: title with & ({g('title')})")
    check(g("price") == "1999.00 INR" and g("sale_price") == "1899.00 INR", f"feed: price and sale price ({g('price')} / {g('sale_price')})")
    check(g("availability") == "in_stock" and g("condition") == "new" and g("brand") == "Havells", "feed: availability, condition, brand")
    check(g("link") == BASE + "/product/feed-wire/", f"feed: link ({g('link')})")
    check((g("image_link") or "").endswith("feed-wire.png") and (it.findtext(G + "additional_image_link") or "").endswith("feed-wire-2.png"), "feed: photos")
    check(g("product_type") == "Wires & Cables > House Wires", f"feed: product type ({g('product_type')})")
    check("90 m coil" in (g("description") or ""), "feed: description")
check("1 products listed, 1 in stock" in feed, "feed: count comment")

# 1.1.0: order requests, policy pages
check("send the order request" in llms and "we book Porter or a courier for you" in llms, "llms.txt: how to order, delivery options")

s, _, ship = get("/shipping-delivery-policy/")
for m in re.finditer("24-48", ship):
    print("     24-48 at:", ship[max(0, m.start() - 200):m.start() + 40].replace("\n", " "))
check("We book transport for you" in ship and "24-48" not in ship, "old delivery policy page shows the current terms")
s, _, priv = get("/privacy-policy/")
check("Digital Personal Data Protection Act, 2023" in priv and "Data Protection Board of India" in priv, "privacy page: DPDP rights section")
check("raghavendra" not in priv.lower() and "Kodandaram Kalavanchi" in priv, "privacy page: one grievance officer")
s, _, griev = get("/customer-grievance/")
check("raghavendra" not in griev.lower() and "Grievance Officer: Kodandaram Kalavanchi" in griev, "grievance page: one grievance officer")

import http.cookiejar
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def store(method, path, body=None, nonce=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", **({"Nonce": nonce} if nonce else {})})
    try:
        with opener.open(req, timeout=60) as r:
            return r.status, dict(r.headers), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf-8", "replace")


st, hdr, _ = store("GET", "/wp-json/wc/store/v1/cart")
nonce = hdr.get("Nonce") or hdr.get("nonce")
st, _, prods = store("GET", "/wp-json/wc/store/v1/products?slug=feed-wire")
pid = json.loads(prods)[0]["id"]
st, _, out = store("POST", "/wp-json/wc/store/v1/cart/add-item", {"id": pid, "quantity": 2}, nonce)
check(st in (200, 201), f"cart: add to cart ({st} {out[:200]})")
addr = {"first_name": "Test", "last_name": "Buyer", "address_1": "1 MG Road", "city": "Bengaluru", "state": "KA",
        "postcode": "560001", "country": "IN", "email": "buyer.test@gmail.com"}
st, _, out = store("POST", "/wp-json/wc/store/v1/checkout", {"billing_address": addr, "shipping_address": addr, "payment_method": "cod"}, nonce)
check(st == 400, f"checkout: refused without a phone number ({st} {out[:200]})")
addr["phone"] = "9876543210"
st, _, out = store("POST", "/wp-json/wc/store/v1/checkout", {"billing_address": addr, "shipping_address": addr, "payment_method": "cod"}, nonce)
print("     checkout:", out[:400])
order = json.loads(out) if out.startswith("{") else {}
check(st == 200 and order.get("status") == "processing", f"checkout: order request placed ({st} {order.get('status')})")
redirect = (order.get("payment_result") or {}).get("redirect_url", "")
if redirect:
    req = urllib.request.Request(redirect)
    with opener.open(req, timeout=60) as r:
        thanks = r.read().decode("utf-8", "replace")
    m = re.search(r'href="(https://wa\.me/[^"]+)"', thanks)
    print("     whatsapp:", m.group(1)[:300] if m else None)
    check(m is not None and m.group(1).startswith("https://wa.me/918431877469?text=Order%20request%20%23"), "thank-you page: WhatsApp button to the shop's number")
    check(m is not None and "RT-HAVE-0900" in m.group(1) and "2%20x%20" in m.group(1), "thank-you page: WhatsApp message lists the items")
    check("buyer.test@gmail.com" in thanks, "thank-you page: the customer's own email is not replaced")
mails = open(sys.argv[3]).read() if len(sys.argv) > 3 else ""
print("     mails:", mails[-600:])
check(any("info@ramtechautomation.co.in" in json.dumps(json.loads(l).get("to")) and "order" in json.loads(l).get("subject", "").lower()
          for l in mails.splitlines() if l.strip()), "email: new order goes to the business email")

log = open(sys.argv[2]).read() if len(sys.argv) > 2 else ""
# only lines from the plugin's own file (wp-cli's own deprecation traces name the command "activate rtech-ai-seo")
mine = [l for l in log.splitlines() if "plugins/rtech-ai-seo/" in l]
for l in mine[:20]:
    print("     log:", l)
check(not mine, "debug.log: no PHP notices, warnings or errors from the plugin " + " / ".join(l[-300:] for l in mine[:3]))

print(f"\n{len(fails)} failure(s)")
sys.exit(1 if fails else 0)
