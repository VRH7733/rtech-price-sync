"""tools/brand_prices.py on REAL havells.com pages (saved 18 Oct 2026, no network)."""
import importlib.util
from pathlib import Path

from rtech_sync.models import Row

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("brand_prices", ROOT / "tools" / "brand_prices.py")
bp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bp)
FIX = ROOT / "tests" / "fixtures" / "real" / "havells"


def test_mrp_and_offer_price_of_the_main_product_only():
    html = (FIX / "havells_dhabosn3012.html").read_text(encoding="utf-8")
    assert bp.magento_price(html, "DHABOSN3012") == ("2951", "1771")
    html = (FIX / "havells_lhfoajd1tz1t060.html").read_text(encoding="utf-8")
    assert bp.magento_price(html, "LHFOAJD1TZ1T060") == ("3250", "2925")  # not a related product's


def test_page_must_show_the_same_model_number():
    html = (FIX / "havells_dhabosn3012.html").read_text(encoding="utf-8")
    assert bp.magento_price(html, "DHABOSN3015") is None
    assert bp.magento_price(html, "") is None


def test_targets_are_quote_products_or_already_brand_priced_with_a_known_brand_page():
    rows = [Row(sku=s, brand="Havells", publish="yes") for s in ("Q", "P", "B", "N")]
    state = {"Q": {"hidden": True, "price": "100"}, "P": {"price": "100"}, "B": {"price": "2951"}}
    plan = [{"sku": s, "page_url": f"https://havells.com/{s}.html", "code": "X1"} for s in ("Q", "P", "B", "N")]
    plan.append({"sku": "Q", "page_url": "https://www.moglix.com/x", "code": "X1"})  # never a marketplace
    got = bp.targets(rows, state, plan, known={"B": {}})
    assert [t[0] for t in got] == ["Q", "B", "N"]


LEG = ROOT / "tests" / "fixtures" / "real" / "legrand"


def test_legrand_listing_gives_catalogue_number_and_page():
    got = bp.legrand_listing((LEG / "legrand_listing_connected.html").read_text(encoding="utf-8"))
    assert len(got) == 12
    assert got["574200"] == ("https://shop.legrand.co.in/legrand-arteor-connected-socket-outletmodule-"
                             "16a-240va-3680-w-1-module-white")


def test_legrand_product_page_mrp():
    html = (LEG / "legrand_575824.html").read_text(encoding="utf-8")
    assert bp.magento_price(html, "575824") == ("658", "342")
    assert bp.magento_price(html, "575825") is None


def test_legrand_targets_come_from_the_shop_listing_by_catalogue_number():
    rows = [Row(sku="L1", brand="Legrand", publish="yes"), Row(sku="L2", brand="Legrand", publish="yes")]
    plan = [{"sku": "L1", "page_url": "https://assets.legrand.com/x.jpg", "code": "5758 24"},
            {"sku": "L2", "page_url": "", "code": "999999"}]
    got = bp.targets(rows, {}, plan, {}, legrand={"575824": "https://shop.legrand.co.in/arteor-plate"})
    assert got == [("L1", "https://shop.legrand.co.in/arteor-plate", "5758 24")]


class _Fake:
    def __init__(self, pages):
        self.pages, self.got = pages, []

    def get(self, url, budget_key=""):
        from rtech_sync.fetcher import FetchResult
        self.got.append(url)
        t = self.pages.get(url)
        return FetchResult(url, "ok", 200, text=t) if t else FetchResult(url, "error", 404)


def test_legrand_crawl_follows_pages_and_stops_when_nothing_new():
    page = (LEG / "legrand_listing_connected.html").read_text(encoding="utf-8")
    f = _Fake({f"{bp.LEGRAND_SHOP}/switches-accessories?product_list_limit=36&p=1": page,
               f"{bp.LEGRAND_SHOP}/switches-accessories?product_list_limit=36&p=2": page})
    got = bp.legrand_pages(f, log=lambda *_: None)
    assert len(got) == 12
    assert f.got[:3] == [f"{bp.LEGRAND_SHOP}/switches-accessories?product_list_limit=36&p={n}" for n in (1, 2)] + \
        [f"{bp.LEGRAND_SHOP}/protection?product_list_limit=36&p=1"]
    assert not any("/catalog/" in u for u in f.got)
