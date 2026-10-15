"""tools/discover.py on fake sitemaps + a REAL HomeRun page (no network)."""
import importlib.util
from pathlib import Path

from rtech_sync.fetcher import FetchResult

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("discover", ROOT / "tools" / "discover.py")
discover = importlib.util.module_from_spec(spec)
spec.loader.exec_module(discover)

INDEX = b"""<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://www.moglix.com/sitemap_blog.xml</loc></sitemap>
<sitemap><loc>https://www.moglix.com/sitemap_001_products_image1.xml</loc></sitemap></sitemapindex>"""
PRODUCTS = b"""<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://www.moglix.com/polycab-etira-1-sqmm-90m-red-single-core-fr-cable/mp/msn1</loc></url>
<url><loc>https://www.moglix.com/polycab-63a-mcb/mp/msn2</loc></url>
<url><loc>https://www.moglix.com/havells-wire-1-sqmm/mp/msn3</loc></url></urlset>"""


class Fake:
    def __init__(self, pages):
        self.pages, self.got = pages, []

    def get(self, url, budget_key=""):
        self.got.append(url)
        body = self.pages.get(url)
        if body is None:
            return FetchResult(url, "error", 404)
        if isinstance(body, bytes):
            return FetchResult(url, "ok", 200, content=body)
        return FetchResult(url, "ok", 200, text=body, content=body.encode())


def test_collect_reads_only_product_sitemaps_and_filters_brand_and_keyword():
    f = Fake({"https://www.moglix.com/sitemap_index.xml": INDEX,
              "https://www.moglix.com/sitemap_001_products_image1.xml": PRODUCTS})
    urls, _ = discover.collect(f, "moglix", ["polycab"], ["sqmm"], lambda *_: None)
    assert urls == ["https://www.moglix.com/polycab-etira-1-sqmm-90m-red-single-core-fr-cable/mp/msn1"]
    assert "https://www.moglix.com/sitemap_blog.xml" not in f.got


def test_homerun_page_becomes_one_row_per_variant_url():
    page = (ROOT / "tests/fixtures/real/homerun/homerun_polycab_optima_default.html").read_text(encoding="utf-8")
    url = "https://home-run.co/products/polycab-optima-wire-lf-fr"
    rows = discover.fetch_rows(Fake({url: page}), "homerun", url)
    assert len(rows) > 1 and all("?variant=" in r["url"] for r in rows)
    r = next(r for r in rows if r["url"].endswith("50073590432059"))
    assert float(r["price"]) == 8567
