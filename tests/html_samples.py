"""SYNTHETIC page samples. They imitate common structures (JSON-LD, meta tags, Next.js/Shopify
JSON) - they are NOT copies of the real marketplace pages, which were unreachable when this repo
was built. Real fixtures must be added in Phase 1 (see docs/STATUS.md)."""
import json


def jsonld_page(name="Polycab 1.5 sq mm FR PVC Insulated Wire, Red, 90 m", price="1906.00",
                tax_text="Inclusive of all taxes", availability="https://schema.org/InStock",
                visible_price="₹1,906"):
    ld = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": name,
        "sku": "ABC123",
        "offers": {"@type": "Offer", "price": price, "priceCurrency": "INR", "availability": availability},
    }
    return f"""<html><head><title>{name} | Shop</title>
<script type="application/ld+json">{json.dumps(ld)}</script></head>
<body><h1>{name}</h1><div class="price">{visible_price}</div><p>{tax_text}</p>
<section>Related: Polycab 2.5 sq mm Wire 180 m ₹5,200</section></body></html>"""


def multi_variant_page():
    ld = {
        "@type": "Product", "name": "KEI Homecab FR Wire",
        "offers": {"@type": "AggregateOffer", "lowPrice": "1906", "highPrice": "5200", "priceCurrency": "INR"},
    }
    return f"""<html><body><h1>KEI Homecab FR Wire</h1>
<script type="application/ld+json">{json.dumps(ld)}</script><p>20 Options</p></body></html>"""


def meta_page(title="Finolex 1.5 sq mm Wire Red 90 m", price="2100"):
    return f"""<html><head><meta property="og:title" content="{title}">
<meta property="product:price:amount" content="{price}"><meta property="product:price:currency" content="INR">
</head><body><h1>{title}</h1><span>₹2,100</span><small>Price is exclusive of GST</small></body></html>"""


def next_data_page(handle="kei-homecab-90mtr-wire", variants=None, visible="₹ 1,906", cents=False):
    variants = variants or [{"id": "gid://shopify/ProductVariant/111", "title": "1.5 sqmm / Red", "price": "1906.00"}]
    if cents:
        variants = [dict(v, price=str(int(float(v["price"]) * 100))) for v in variants]
    data = {"props": {"pageProps": {"product": {"handle": handle, "title": "KEI Homecab FR Wire, 90m",
                                                  "variants": variants}}}}
    return f"""<html><body><h1>KEI Homecab FR Wire, 90m</h1><div>{visible}</div>
<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></body></html>"""


BLOCKED_PAGE = "<html><head><title>Just a moment...</title></head><body>Checking your browser. captcha</body></html>"
