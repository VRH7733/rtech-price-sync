"""Parser + pipeline tests on REAL Moglix pages (captured 14 Oct 2026 through the owner's Chrome; the
ground truth in tests/fixtures/real/moglix/expected.json was written from the raw HTML, not from
rtech_sync.parsers).

Facts these pages prove:
- JSON-LD Product.offers.price is the incl-GST selling price, and the price block says
  "(Incl. of all taxes)". One MSN URL = one variant.
- "AVAILABLE ON REQUEST" pages are JSON-LD OutOfStock: Moglix is not selling them.
- JSON-LD can carry a price that is not on the page (GM switch: 1840 in JSON-LD, page shows MRP 92).
- Titles can say "(Pack of 5)": the price is for the pack.
"""
import json
from decimal import Decimal as D
from pathlib import Path

import pytest
from rtech_sync.config import load_config
from rtech_sync.fetcher import FetchResult
from rtech_sync.models import Row
from rtech_sync.normalise import check_variant
from rtech_sync.parsers import parse_product_page
from rtech_sync.pipeline import evaluate_source

ROOT = Path(__file__).resolve().parent.parent
FX = ROOT / "tests" / "fixtures" / "real" / "moglix"
CFG = load_config(ROOT / "config.yaml", env={"RTECH_CONTACT_EMAIL": "shop@example.com"})
EXPECTED = json.loads((FX / "expected.json").read_text(encoding="utf-8"))["fixtures"]
IDS = [e["file"] for e in EXPECTED]


def html(name):
    return (FX / name).read_text(encoding="utf-8")


def evaluate(e, hint=None, pack=None):
    row = Row(sku="S", mode="priced", publish="yes",
              variant_hint=e["variant_hint"] if hint is None else hint,
              pack_size=e["pack_size"] if pack is None else pack, urls={"moglix": e["url"]})
    return evaluate_source(row, "moglix", FetchResult(e["url"], "ok", 200, text=html(e["file"])), CFG)


def test_config_tax_basis_is_verified_incl_gst():
    assert CFG.sources["moglix"].assumed_tax_basis == "incl_gst"


@pytest.mark.parametrize("e", EXPECTED, ids=IDS)
def test_parser_reads_jsonld_incl_gst_single_variant(e):
    p = parse_product_page(html(e["file"]), e["url"])
    assert p.method == "jsonld" and p.currency == "INR"
    assert p.tax_basis == "incl_gst" == e["tax_basis"]
    assert not p.multi_variant
    assert p.in_stock is e["in_stock"]
    if e["selling_price"] is not None:
        assert p.price == D(e["selling_price"])
        assert p.price != D(e["mrp"]) or e["mrp"] == e["selling_price"]


@pytest.mark.parametrize("e", [e for e in EXPECTED if e["usable"]], ids=lambda e: e["file"])
def test_usable_pages_give_the_true_price(e):
    res = evaluate(e)
    assert res.status == "ok", res.detail
    assert res.price == D(e["selling_price"])


@pytest.mark.parametrize("e", [e for e in EXPECTED if not e["usable"]], ids=lambda e: e["file"])
def test_available_on_request_pages_are_never_used(e):
    res = evaluate(e)
    assert res.status != "ok" and res.price is None


def test_jsonld_price_not_shown_on_page_is_refused():
    e = next(e for e in EXPECTED if "gm_10a" in e["file"])
    p = parse_product_page(html(e["file"]), e["url"])
    assert p.price == D(e["jsonld_price"]) and "price_not_visible_in_text" in p.problems
    res = evaluate(e)
    assert res.status == "parse_failed" and res.price is None


def test_out_of_stock_page_is_excluded_as_out_of_stock():
    e = next(e for e in EXPECTED if "astral" in e["file"])
    assert evaluate(e).status == "out_of_stock"


def test_pack_of_5_page_cannot_price_a_single_switch():
    e = next(e for e in EXPECTED if "pack5" in e["file"])
    for pack in ("", "1 pc", "pack of 10"):
        res = evaluate(e, pack=pack)
        assert res.status == "pack_mismatch" and res.price is None, (pack, res.status, res.detail)
    # a row that really sells the pack of 5 gets past the pack check (then out_of_stock today)
    assert evaluate(e, pack="pack of 5").status == "out_of_stock"
    assert evaluate(e, pack="5 pcs").status == "out_of_stock"


def test_wire_colour_and_length_must_match_the_page():
    red = next(e for e in EXPECTED if e["file"].endswith("_red.html"))
    p = parse_product_page(html(red["file"]), red["url"])
    assert check_variant("1.5 sq mm; red", "90 m", p.identity_text).status == "ok"
    assert check_variant("1.5 sq mm; blue", "90 m", p.identity_text).status == "variant_unconfirmed"
    assert check_variant("2.5 sq mm; red", "90 m", p.identity_text).status == "variant_unconfirmed"
    assert check_variant("1.5 sq mm; red", "180 m", p.identity_text).status == "pack_mismatch"


def test_mcb_selector_buttons_for_other_ratings_do_not_confirm_them():
    # the Havells page shows buttons "Double Pole", "10 Amp", "16 A" ...; identity must not include them
    e = next(e for e in EXPECTED if "havells" in e["file"])
    p = parse_product_page(html(e["file"]), e["url"])
    assert check_variant("63a; single pole", "", p.identity_text).status == "ok"
    assert check_variant("16a; single pole", "", p.identity_text).status == "variant_unconfirmed"
    assert check_variant("63a; double pole", "", p.identity_text).status == "variant_unconfirmed"
