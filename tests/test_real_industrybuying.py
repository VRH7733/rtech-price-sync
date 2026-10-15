"""Parser + pipeline tests on REAL IndustryBuying pages (captured 14 Oct 2026 through the owner's
Chrome; ground truth in tests/fixtures/real/industrybuying/expected.json was written from the raw
HTML, not from rtech_sync.parsers).

Facts these pages prove:
- Product URLs are /<category>-<brand>-<SKU> (NOT the robots-blocked /product_details/), and the
  repo's robots matcher allows them.
- JSON-LD Product.offers.price is the incl-GST price; the block says "(Incl. of all taxes)".
- Each variant is its own URL/SKU; sibling-variant and related-product prices appear in the page
  text but never in this product's identity.
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
from rtech_sync.robots import RobotsRules

ROOT = Path(__file__).resolve().parent.parent
FX = ROOT / "tests" / "fixtures" / "real" / "industrybuying"
CFG = load_config(ROOT / "config.yaml", env={"RTECH_CONTACT_EMAIL": "shop@example.com"})
EXPECTED = json.loads((FX / "expected.json").read_text(encoding="utf-8"))["fixtures"]
IDS = [e["file"] for e in EXPECTED]


def html(name):
    return (FX / name).read_text(encoding="utf-8")


def test_config_tax_basis_is_verified_incl_gst():
    assert CFG.sources["industrybuying"].assumed_tax_basis == "incl_gst"


@pytest.mark.parametrize("e", EXPECTED, ids=IDS)
def test_parser_gives_true_incl_gst_price(e):
    p = parse_product_page(html(e["file"]), e["url"])
    assert p.method == "jsonld" and p.currency == "INR" and p.problems == []
    assert p.price == D(e["selling_price"])
    assert p.price != D(e["price_excl_gst"])
    if e["mrp"] and e["mrp"] != e["selling_price"]:
        assert p.price != D(e["mrp"])
    assert p.tax_basis == "incl_gst" == e["tax_basis"]
    assert p.multi_variant is e["multi_variant_page"] is False
    assert p.in_stock is e["in_stock"]


@pytest.mark.parametrize("e", EXPECTED, ids=IDS)
def test_product_urls_are_allowed_by_live_robots(e):
    rules = RobotsRules((FX / "robots_industrybuying_live.txt").read_text(encoding="utf-8"))
    assert rules.allowed(e["url"])
    assert not rules.allowed("https://www.industrybuying.com/product_details/x")


@pytest.mark.parametrize("e", EXPECTED, ids=IDS)
def test_identity_carries_the_page_sku(e):
    sku = e["variant_description"].rsplit("SKU ", 1)[1]
    p = parse_product_page(html(e["file"]), e["url"])
    assert sku in p.identity_text


def test_wire_end_to_end_ok_and_wrong_colour_refused():
    e = next(e for e in EXPECTED if "1_5sqmm" in e["file"])
    fr = FetchResult(e["url"], "ok", 200, text=html(e["file"]))
    row = Row(sku="S", mode="priced", publish="yes", variant_hint="1.5 sq mm; red", pack_size="90 m",
              urls={"industrybuying": e["url"]})
    res = evaluate_source(row, "industrybuying", fr, CFG)
    assert res.status == "ok" and res.price == D(5073)
    row.variant_hint = "1.5 sq mm; yellow"  # a sibling colour listed under EXPLORE OTHER VARIANTS
    assert evaluate_source(row, "industrybuying", fr, CFG).status == "variant_unconfirmed"


def test_sibling_variant_sizes_in_page_text_do_not_confirm_a_variant():
    # the 2.5 sq mm black page lists other sizes/colours; only its own must confirm
    e = next(e for e in EXPECTED if "2_5sqmm" in e["file"])
    p = parse_product_page(html(e["file"]), e["url"])
    assert check_variant("2.5 sq mm; black", "90 m", p.identity_text).status == "ok"
    assert check_variant("0.75 sq mm; yellow", "90 m", p.identity_text).status == "variant_unconfirmed"
    assert check_variant("2.5 sq mm; black", "180 m", p.identity_text).status in ("pack_mismatch", "variant_unconfirmed")
