"""Parser tests on REAL HomeRun pages (captured 14 Oct 2026 through the owner's Chrome, see
tests/fixtures/real/homerun/expected.json for the independently written ground truth).

Key facts proven by these pages:
- JSON-LD Product has ONE offer: the variant chosen by ?variant=ID, or the default variant.
- The full variant list lives only in the Next.js RSC payload (self.__next_f.push).
- A URL without ?variant= must never yield a price (it is just the default variant's).
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
FX = ROOT / "tests" / "fixtures" / "real" / "homerun"
CFG = load_config(ROOT / "config.yaml", env={"RTECH_CONTACT_EMAIL": "shop@example.com"})
EXPECTED = json.loads((FX / "expected.json").read_text(encoding="utf-8"))
OPTIMA = "https://home-run.co/products/polycab-optima-wire-lf-fr"


def html(name):
    return (FX / name).read_text(encoding="utf-8")


def vid_of(e):
    """Shopify variant id of the variant this fixture's price belongs to (from expected.json notes)."""
    import re

    return re.search(r"variant (\d+)", e["notes"]).group(1)


@pytest.mark.parametrize("e", EXPECTED, ids=[e["file"] for e in EXPECTED])
def test_variant_url_gives_true_selling_price_incl_gst(e):
    url = OPTIMA if "optima" in e["file"] else e["url"].split("?")[0]
    p = parse_product_page(html(e["file"]), f"{url}?variant={vid_of(e)}")
    assert p.price == D(str(e["selling_price"]))
    assert p.price != D(str(e["mrp"]))
    assert p.tax_basis == "incl_gst" == e["tax_basis"]
    assert not p.multi_variant and p.problems == []
    assert p.variant_count and p.variant_count > 1


@pytest.mark.parametrize("e", EXPECTED, ids=[e["file"] for e in EXPECTED])
def test_url_without_variant_is_refused_on_multi_variant_pages(e):
    if "?variant=" in e["url"]:
        pytest.skip("fixture was fetched with an explicit variant")
    p = parse_product_page(html(e["file"]), e["url"])
    assert p.multi_variant and "variant_not_selected" in p.problems
    row = Row(sku="S", mode="priced", publish="yes", variant_hint=e["variant_description"].split(" / ")[0],
              urls={"homerun": e["url"]})
    res = evaluate_source(row, "homerun", FetchResult(e["url"], "ok", 200, text=html(e["file"])), CFG)
    assert res.status == "variant_unconfirmed" and res.price is None


def test_variant_identity_is_the_selected_variant_only():
    p = parse_product_page(html("homerun_polycab_optima_variant_50073590432059.html"),
                           f"{OPTIMA}?variant=50073590432059")
    assert check_variant("2.5 sq mm; black", "180 m", p.identity_text).status == "ok"
    assert check_variant("2.5 sq mm; red", "180 m", p.identity_text).status == "variant_unconfirmed"
    assert check_variant("1.5 sq mm; black", "180 m", p.identity_text).status == "variant_unconfirmed"
    assert check_variant("2.5 sq mm; black", "90 m", p.identity_text).status == "pack_mismatch"


def test_page_heading_listing_other_sizes_cannot_confirm_a_variant():
    # The VIP page <title>/<h1> says "19mm 25mm"; the selected variant is 19 mm.
    p = parse_product_page(html("homerun_vip_conduit_pipe_frls_3m.html"),
                           "https://home-run.co/products/vip-electrical-conduit-pipe-frls-3m-length?variant=49812502511931")
    assert p.price == D(62)
    assert check_variant("19mm; black", "", p.identity_text).status == "ok"
    assert check_variant("25mm", "", p.identity_text).status == "variant_unconfirmed"


def test_url_variant_not_rendered_by_server_is_refused():
    # default-variant HTML, but the catalogue URL asks for another variant
    p = parse_product_page(html("homerun_polycab_optima_default.html"), f"{OPTIMA}?variant=50073590432059")
    assert p.price is None and "variant_mismatch_with_url" in p.problems


def test_offer_price_disagreeing_with_variant_list_is_refused():
    page = html("homerun_polycab_optima_variant_50073590432059.html")
    start = page.index('"@type":"Product"')
    pos = page.index('"price":"8567.0"', start)
    tampered = page[:pos] + '"price":"8000.0"' + page[pos + len('"price":"8567.0"'):]
    p = parse_product_page(tampered, f"{OPTIMA}?variant=50073590432059")
    assert p.price is None and "variant_price_mismatch" in p.problems


def test_mrp_is_never_taken_as_price():
    for e in EXPECTED:
        url = OPTIMA if "optima" in e["file"] else e["url"].split("?")[0]
        p = parse_product_page(html(e["file"]), f"{url}?variant={vid_of(e)}")
        assert p.price < D(str(e["mrp"]))


def test_page_variants_lists_the_products_own_variants_only():
    from rtech_sync.parsers import page_variants

    vs = page_variants(html("homerun_polycab_optima_default.html"))
    ids = {v["id"] for v in vs}
    assert len(vs) > 1 and "50073590432059" in ids and "50073589645627" in ids
    v = next(v for v in vs if v["id"] == "50073590432059")
    assert v["price"] == D(8567)
    # every listed variant prices the same through the nightly parser with ?variant=ID
    p = parse_product_page(html("homerun_polycab_optima_variant_50073590432059.html"),
                           f"{OPTIMA}?variant=50073590432059")
    assert p.price == v["price"]
