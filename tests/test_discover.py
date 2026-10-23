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


def test_previous_run_pages_are_reused_and_only_new_pages_count(tmp_path):
    import csv
    from discover import FIELDS, load_previous, plan_rows
    old = tmp_path / "industrybuying.csv"
    with open(old, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerow({"source": "industrybuying", "url": "https://x/a", "fetched": "yes", "price": "10"})
        w.writerow({"source": "industrybuying", "url": "https://x/b", "fetched": "no"})
        w.writerow({"source": "homerun", "url": "https://x/c?variant=1", "fetched": "yes", "price": "5"})
        w.writerow({"source": "homerun", "url": "https://x/c?variant=2", "fetched": "yes", "price": "6"})
    prev = load_previous(old)
    got = []
    rows, n = plan_rows(["https://x/a", "https://x/b", "https://x/c", "https://x/d"], prev, True, 1,
                        lambda u: got.append(u) or [{"url": u, "fetched": "yes"}])
    assert got == ["https://x/b"] and n == 1  # a and c reused, d over the cap
    assert [r["url"] for r in rows] == ["https://x/a", "https://x/b", "https://x/c?variant=1",
                                        "https://x/c?variant=2", "https://x/d"]
    assert rows[0]["price"] == "10" and rows[-1]["fetched"] == "no"
    assert load_previous("") == {} and load_previous(tmp_path / "missing.csv") == {}


def test_blocked_sitemap_writes_nothing_so_earlier_results_survive(tmp_path, monkeypatch):
    monkeypatch.setenv("RTECH_CONTACT_EMAIL", "shop@example.com")
    monkeypatch.setattr(discover, "Fetcher", lambda cfg: Fake({}))  # every sitemap fails (e.g. 403)
    out = tmp_path / "out"
    rc = discover.main(["--source", "industrybuying", "--brand", "havells", "--out", str(out)])
    assert rc == 1 and not (out / "industrybuying.csv").exists()


def test_capped_run_fetches_first_brand_first_and_skips_catalogue_urls(tmp_path):
    urls = ["https://www.moglix.com/high-precision-havells-tape/mp/1",
            "https://www.moglix.com/havells-mcb/mp/2",
            "https://www.moglix.com/legrand-switch/mp/3",
            "https://www.moglix.com/havells-fan/mp/4",
            "https://www.moglix.com/rr-kabel-wire/mp/5"]
    assert discover.order_by_brand(urls, ["legrand", "havells", "rr kabel"]) == [
        "https://www.moglix.com/legrand-switch/mp/3", "https://www.moglix.com/havells-fan/mp/4",
        "https://www.moglix.com/havells-mcb/mp/2", "https://www.moglix.com/rr-kabel-wire/mp/5",
        "https://www.moglix.com/high-precision-havells-tape/mp/1"]
    rows = tmp_path / "rows"
    rows.mkdir()
    (rows / "havells.csv").write_text(
        "sku,brand,title,mode,publish,url_moglix\nRT-HAVE-001,Havells,MCB,priced,yes,https://www.moglix.com/havells-mcb/mp/2\n",
        encoding="utf-8")
    assert "https://www.moglix.com/havells-mcb/mp/2" in discover.catalogue_urls(rows)


def test_interleave_covers_every_brand_and_pack_copies_are_dropped():
    m = "https://www.moglix.com/"
    urls = [m + "anchor-fan-1200-mm/mp/1", m + "anchor-fan-1200-mm-pack-of-2/mp/2",
            m + "anchor-switch/mp/3", m + "schneider-mcb/mp/4", m + "wipro-led-bulb-pack-of-3/mp/5",
            m + "ladder-with-schneider-logo/mp/6"]
    kept = discover.drop_pack_copies(urls)
    assert m + "anchor-fan-1200-mm-pack-of-2/mp/2" not in kept
    assert m + "wipro-led-bulb-pack-of-3/mp/5" in kept  # no single listing: kept
    assert discover.interleave_brands(kept, ["anchor", "schneider", "wipro"]) == [
        m + "anchor-fan-1200-mm/mp/1", m + "schneider-mcb/mp/4", m + "wipro-led-bulb-pack-of-3/mp/5",
        m + "anchor-switch/mp/3", m + "ladder-with-schneider-logo/mp/6"]
