"""Extract price + identity from a product page.

Order of trust:  JSON-LD  ->  meta tags  ->  embedded Next.js/Shopify JSON.
Embedded-JSON prices must ALSO appear in the visible page text (guards against cents-vs-rupees
mistakes and stale JSON). Site-specific CSS selectors are NOT implemented: they need real HTML
from each site (see docs/STATUS.md).

`identity_text` deliberately contains only the product's own title/attributes (never the whole
page), so "related products" sections cannot confirm a variant by accident.
"""
from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Optional
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup


@dataclass
class Parsed:
    title: Optional[str] = None
    price: Optional[Decimal] = None
    currency: Optional[str] = None
    in_stock: Optional[bool] = None
    tax_basis: str = "unknown"  # incl_gst | excl_gst | unknown
    method: str = "none"  # jsonld | meta | next_data | none
    multi_variant: bool = False
    identity_text: str = ""
    problems: list = field(default_factory=list)
    offer_variant_ids: list = field(default_factory=list)  # ?variant=ID found in JSON-LD offer urls
    variant_count: Optional[int] = None  # from the embedded variant list, when the page has one
    # True when identity_text was built from the selected variant itself; the page <h1>/<title> is
    # then NOT added, because on multi-variant pages it often lists other sizes ("19mm 25mm").
    identity_from_variant: bool = False


# ---------------------------------------------------------------- helpers
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?|\.\d+")


def to_decimal(value) -> Optional[Decimal]:
    """First number found in value, as a positive finite Decimal (else None)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, dict):
        for k in ("amount", "value", "price"):
            if k in value:
                return to_decimal(value[k])
        return None
    try:
        if isinstance(value, (int, float)):
            d = Decimal(str(value))
        else:
            m = _NUM.search(str(value))
            if not m:
                return None
            d = Decimal(m.group(0).replace(",", ""))
    except InvalidOperation:
        return None
    if not d.is_finite():
        return None
    return d if d > 0 else None


def _indian_group(n: int) -> str:
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts) + "," + tail


def price_in_text(text: str, price: Decimal) -> bool:
    """Is this price visible in the page text (any common rupee formatting)?"""
    if price != price.to_integral_value():
        forms = {f"{price:,.2f}", f"{price:.2f}", f"{price.normalize():f}"}
    else:
        n = int(price)
        forms = {str(n), f"{n:,}", _indian_group(n)}
    for f in forms:
        if re.search(r"(?<![\d,.])" + re.escape(f) + r"(?:\.0+)?(?![\d,])", text):
            return True
    return False


_INCL = re.compile(r"incl(?:uding|usive)?\.?\s*(?:of\s*)?(?:all\s*)?(?:gst|taxes|tax)", re.I)
_EXCL = re.compile(
    r"excl(?:uding|usive)?\.?\s*(?:of\s*)?(?:all\s*)?(?:gst|taxes|tax)|\+\s*gst|plus\s*gst", re.I
)


def detect_tax_basis(text: str) -> str:
    inc, exc = bool(_INCL.search(text)), bool(_EXCL.search(text))
    if inc and not exc:
        return "incl_gst"
    if exc and not inc:
        return "excl_gst"
    return "unknown"


def _visible_text(soup: BeautifulSoup) -> str:
    clone = BeautifulSoup(str(soup), "html.parser")
    for t in clone(["script", "style", "noscript"]):
        t.decompose()
    return clone.get_text(" ", strip=True)


def _h1_and_title(soup: BeautifulSoup) -> str:
    bits = []
    for sel in ("h1",):
        for el in soup.select(sel)[:2]:
            bits.append(el.get_text(" ", strip=True))
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        bits.append(og["content"])
    if soup.title and soup.title.string:
        bits.append(soup.title.string)
    return " ".join(bits)


# ---------------------------------------------------------------- JSON-LD
def _jsonld_nodes(soup: BeautifulSoup):
    for s in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        raw = (s.string or s.get_text() or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        queue = deque([data])  # document order matters: first Product wins, duplicates are flagged
        while queue:
            cur = queue.popleft()
            if isinstance(cur, list):
                queue.extend(cur)
            elif isinstance(cur, dict):
                yield cur
                if "@graph" in cur:
                    queue.append(cur["@graph"])


def _types(node: dict) -> list:
    t = node.get("@type", [])
    return [t] if isinstance(t, str) else list(t)


def _from_jsonld(soup: BeautifulSoup) -> Optional[Parsed]:
    found = []
    for node in _jsonld_nodes(soup):
        types = _types(node)
        if "Product" not in types and "ProductGroup" not in types:
            continue
        p = Parsed(method="jsonld", title=node.get("name"))
        attrs = [str(node.get(k, "")) for k in ("name", "sku", "model", "color", "size", "mpn")]
        p.identity_text = " ".join(a for a in attrs if a)

        if "ProductGroup" in types and isinstance(node.get("hasVariant"), list):
            if len(node["hasVariant"]) > 1:
                p.multi_variant = True
        offers = node.get("offers")
        if offers is None and isinstance(node.get("hasVariant"), list):
            offers = [v.get("offers") for v in node["hasVariant"] if isinstance(v, dict)]
        offer_list = []
        stack = [offers]
        while stack:
            o = stack.pop()
            if isinstance(o, list):
                stack.extend(o)
            elif isinstance(o, dict):
                offer_list.append(o)
        prices, stocks = [], []
        for o in offer_list:
            ovid = _variant_id_from_url(str(o.get("url", "")))
            if ovid and ovid not in p.offer_variant_ids:
                p.offer_variant_ids.append(ovid)
            if "AggregateOffer" in _types(o):
                lo, hi = to_decimal(o.get("lowPrice")), to_decimal(o.get("highPrice"))
                if lo is not None:
                    prices.append(lo)
                if lo is not None and hi is not None and lo != hi:
                    p.multi_variant = True
                continue
            pr = to_decimal(o.get("price"))
            if pr is None and isinstance(o.get("priceSpecification"), dict):
                pr = to_decimal(o["priceSpecification"].get("price"))
            if pr is not None:
                prices.append(pr)
            if o.get("priceCurrency"):
                p.currency = o["priceCurrency"]
            av = str(o.get("availability", ""))
            if av:
                stocks.append("InStock" in av or "LimitedAvailability" in av)
        if prices:
            if len(set(prices)) > 1:
                p.multi_variant = True
            p.price = min(prices)
            if stocks:
                p.in_stock = any(stocks)
            found.append(p)
    if not found:
        return None
    first = found[0]
    if len({(f.title, f.price) for f in found}) > 1:
        # several different products described on one page (e.g. a carousel): cannot tell which
        # one the URL is about, so refuse to pick one
        first.multi_variant = True
        first.problems.append("several_products_in_jsonld")
    return first


# ---------------------------------------------------------------- meta tags
def _from_meta(soup: BeautifulSoup) -> Optional[Parsed]:
    for attr, name in (
        ("property", "product:price:amount"),
        ("property", "og:price:amount"),
        ("itemprop", "price"),
        ("name", "twitter:data1"),
    ):
        el = soup.find(attrs={attr: name})
        if el is None:
            continue
        val = el.get("content") or el.get("value") or el.get_text(strip=True)
        price = to_decimal(val)
        if price is None:
            continue
        p = Parsed(method="meta", price=price)
        og = soup.find("meta", attrs={"property": "og:title"})
        p.title = og["content"] if og and og.get("content") else None
        cur = soup.find("meta", attrs={"property": "product:price:currency"})
        if cur and cur.get("content"):
            p.currency = cur["content"]
        avail = soup.find("meta", attrs={"property": "product:availability"})
        if avail and avail.get("content"):
            p.in_stock = avail["content"].lower().replace(" ", "") in ("instock", "in stock")
        p.identity_text = p.title or ""
        return p
    return None


# ---------------------------------------------------------------- Next.js / Shopify embedded JSON
def _walk(obj):
    stack = [obj]
    while stack:
        cur = stack.pop()
        yield cur
        if isinstance(cur, dict):
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)


def _product_dicts(data) -> list:
    out = []
    for cur in _walk(data):
        if isinstance(cur, dict) and isinstance(cur.get("variants"), list):
            vs = [v for v in cur["variants"] if isinstance(v, dict) and "price" in v]
            if vs:
                out.append(cur)
    return out


def _variant_id_from_url(url: str) -> Optional[str]:
    q = parse_qs(urlsplit(url).query)
    v = q.get("variant", [None])[0]
    return str(v) if v else None


def _from_next_data(soup: BeautifulSoup, url: str, visible: str) -> Optional[Parsed]:
    script = soup.find("script", id="__NEXT_DATA__")
    if script is None:
        return None
    try:
        data = json.loads(script.string or script.get_text() or "")
    except json.JSONDecodeError:
        return None
    cands = _product_dicts(data)
    if not cands:
        return None
    handle = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1].lower()
    by_handle = [c for c in cands if str(c.get("handle", "")).lower() == handle]
    if len(by_handle) == 1:
        prod = by_handle[0]
    elif len(cands) == 1:
        prod = cands[0]
    else:
        p = Parsed(method="next_data")
        p.problems.append("next_data_ambiguous_product")
        return p

    variants = [v for v in prod["variants"] if isinstance(v, dict) and "price" in v]
    vid = _variant_id_from_url(url)
    chosen = None
    if vid:
        chosen = next((v for v in variants if str(v.get("id", "")).split("/")[-1] == vid), None)
    elif len(variants) == 1:
        chosen = variants[0]

    p = Parsed(method="next_data", title=prod.get("title") or prod.get("name"))
    p.identity_text = " ".join(
        str(x)
        for x in (prod.get("title"), prod.get("name"), (chosen or {}).get("title"), (chosen or {}).get("sku"))
        if x
    )
    if chosen is None:
        p.multi_variant = len(variants) > 1
        prices = [to_decimal(v.get("price")) for v in variants]
        prices = [x for x in prices if x]
        p.price = min(prices) if prices else None
        if p.price is not None:
            p.problems.append("price_is_lowest_of_variants")
        return p

    raw = to_decimal(chosen.get("price"))
    if raw is None:
        return p
    # Shopify-style payloads may hold cents (42500) or rupees (425.00). Only accept the reading
    # that is actually visible on the page.
    options = [raw]
    if raw == raw.to_integral_value():
        options.append(raw / Decimal(100))
    shown = [o for o in options if price_in_text(visible, o)]
    if not shown:
        p.problems.append("next_data_price_not_visible_on_page")
        return p
    p.price = shown[0]
    ct = chosen.get("compare_at_price")
    if ct is not None:
        p.problems.append("has_compare_at_price")
    return p


# ---------------------------------------------------------------- Next.js App Router (RSC) variant list
# HomeRun (Next.js App Router on Shopify, verified on real pages 14 Oct 2026) has no __NEXT_DATA__.
# The JSON-LD Product carries ONE offer: the variant selected by ?variant=ID, or the default variant
# when the URL has none. The full variant list is only in the `self.__next_f.push([1,"..."])` payload
# as `"variants":{"nodes":[{id,title,sku,price:{amount},selectedOptions,availableForSale}...]}`.
_RSC_PUSH = re.compile(r"self\.__next_f\.push\((\[.*\])\)\s*;?\s*$", re.S)
_RSC_VARIANTS = re.compile(r'"variants":\{"nodes":\[')


def _rsc_payload(soup: BeautifulSoup) -> str:
    parts = []
    for s in soup.find_all("script"):
        raw = (s.string or s.get_text() or "").strip()
        m = _RSC_PUSH.match(raw)
        if not m:
            continue
        try:
            arr = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if len(arr) >= 2 and arr[0] == 1 and isinstance(arr[1], str):
            parts.append(arr[1])
    return "".join(parts)


def _matching_bracket(text: str, start: int) -> int:
    depth, in_str, esc = 0, False, False
    for j in range(start, len(text)):
        c = text[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
            if depth == 0:
                return j
    return -1


def _vid(node: dict) -> str:
    return str(node.get("id", "")).rsplit("/", 1)[-1]


def _rsc_variant_nodes(soup: BeautifulSoup, wanted_ids: list) -> Optional[list]:
    """The variant list that contains one of `wanted_ids` (the page's own product). Pages also hold
    variant lists of related products, so a list is only used if it contains the offer's variant."""
    if not wanted_ids:
        return None
    text = _rsc_payload(soup)
    for m in _RSC_VARIANTS.finditer(text):
        i = m.end() - 1
        j = _matching_bracket(text, i)
        if j < 0:
            continue
        try:
            nodes = json.loads(text[i : j + 1])
        except json.JSONDecodeError:
            continue
        nodes = [n for n in nodes if isinstance(n, dict)]
        if any(_vid(n) in wanted_ids for n in nodes):
            return nodes
    return None


def _apply_variant_list(p: Parsed, soup: BeautifulSoup, url: str) -> None:
    """Make a JSON-LD result safe on pages that sell several variants under one URL."""
    url_vid = _variant_id_from_url(url)
    if url_vid and p.offer_variant_ids and url_vid not in p.offer_variant_ids:
        # the server did not render the variant the catalogue asked for
        p.price = None
        p.problems.append("variant_mismatch_with_url")
        return
    nodes = _rsc_variant_nodes(soup, p.offer_variant_ids)
    if not nodes:
        return
    p.variant_count = len(nodes)
    if len(nodes) > 1 and not url_vid:
        # the price shown is just the default variant's; nobody chose it
        p.multi_variant = True
        p.problems.append("variant_not_selected")
        return
    target = url_vid or p.offer_variant_ids[0]
    node = next((n for n in nodes if _vid(n) == target), None)
    if node is None:
        p.price = None
        p.problems.append("variant_not_in_variant_list")
        return
    node_price = to_decimal(node.get("price"))
    if node_price is None or p.price is None or node_price != p.price:
        p.price = None
        p.problems.append("variant_price_mismatch")
        return
    opts = [str(o.get("value", "")) for o in node.get("selectedOptions") or [] if isinstance(o, dict)]
    extra = [str(node.get("title") or ""), " ".join(opts), str(node.get("sku") or "")]
    p.identity_text = " ".join(x for x in [p.title or ""] + extra if x).strip()
    p.identity_from_variant = len(nodes) > 1
    if node.get("availableForSale") is False:
        p.in_stock = False


# ---------------------------------------------------------------- entry point
def parse_product_page(html: str, url: str = "") -> Parsed:
    soup = BeautifulSoup(html or "", "html.parser")
    visible = _visible_text(soup)
    tax = detect_tax_basis(visible)
    heading = _h1_and_title(soup)

    for fn in (
        lambda: _from_jsonld(soup),
        lambda: _from_meta(soup),
        lambda: _from_next_data(soup, url, visible),
    ):
        p = fn()
        if p is not None and p.method == "jsonld" and p.price is not None:
            _apply_variant_list(p, soup, url)
        if p is not None and (p.price is not None or p.multi_variant or p.problems):
            p.tax_basis = tax
            if not p.identity_from_variant:
                p.identity_text = (p.identity_text + " " + heading).strip()
            if p.method in ("jsonld", "meta") and p.price is not None and not price_in_text(visible, p.price):
                p.problems.append("price_not_visible_in_text")
            return p
    return Parsed(tax_basis=tax, identity_text=heading, problems=["no_price_found"])


# ---------------------------------------------------------------- discovery helper
def page_variants(html: str) -> list:
    """All variants of the page's OWN product (HomeRun/Shopify RSC payload), for URL discovery.

    Returns dicts {id, title, options, sku, price, available}. Empty when the page has no variant
    list. Never used for pricing: the nightly run prices a ?variant=ID URL with parse_product_page.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    p = _from_jsonld(soup)
    if p is None:
        return []
    nodes = _rsc_variant_nodes(soup, p.offer_variant_ids) or []
    out = []
    for n in nodes:
        opts = [str(o.get("value", "")) for o in n.get("selectedOptions") or [] if isinstance(o, dict)]
        out.append({
            "id": _vid(n),
            "title": str(n.get("title") or ""),
            "options": " / ".join(opts),
            "sku": str(n.get("sku") or ""),
            "price": to_decimal(n.get("price")),
            "available": n.get("availableForSale") is not False,
        })
    return out
