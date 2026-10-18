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
