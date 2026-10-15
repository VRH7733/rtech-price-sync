from decimal import Decimal as D

import html_samples as S
from rtech_sync.parsers import (
    detect_tax_basis,
    parse_product_page,
    price_in_text,
    to_decimal,
)


def test_to_decimal_variants():
    assert to_decimal("₹ 1,906.50") == D("1906.50")
    assert to_decimal(425) == D(425)
    assert to_decimal({"amount": "12.5"}) == D("12.5")
    assert to_decimal("free") is None and to_decimal(0) is None and to_decimal(None) is None


def test_price_in_text_formats():
    assert price_in_text("Price ₹1,906 only", D(1906))
    assert price_in_text("Price 1906.00", D(1906))
    assert price_in_text("₹12,34,567", D(1234567))
    assert not price_in_text("₹11,906", D(1906))
    assert not price_in_text("₹1,9060", D(1906))


def test_tax_basis_detection():
    assert detect_tax_basis("Inclusive of all taxes") == "incl_gst"
    assert detect_tax_basis("Price excl. GST") == "excl_gst"
    assert detect_tax_basis("₹100 + GST") == "excl_gst"
    assert detect_tax_basis("nothing here") == "unknown"
    assert detect_tax_basis("inclusive of GST, excluding GST on freight") == "unknown"


def test_jsonld_product():
    p = parse_product_page(S.jsonld_page(), "https://www.moglix.com/x")
    assert p.method == "jsonld" and p.price == D("1906.00") and p.in_stock is True
    assert p.tax_basis == "incl_gst" and not p.multi_variant
    assert "90 m" in p.identity_text and "price_not_visible_in_text" not in p.problems


def test_identity_text_excludes_related_products_section():
    p = parse_product_page(S.jsonld_page(), "u")
    assert "180 m" not in p.identity_text


def test_jsonld_out_of_stock():
    p = parse_product_page(S.jsonld_page(availability="https://schema.org/OutOfStock"), "u")
    assert p.in_stock is False


def test_jsonld_price_not_on_page_is_noted():
    p = parse_product_page(S.jsonld_page(visible_price="₹2,999"), "u")
    assert "price_not_visible_in_text" in p.problems


def test_aggregate_offer_means_multi_variant():
    p = parse_product_page(S.multi_variant_page(), "u")
    assert p.multi_variant


def test_meta_tags():
    p = parse_product_page(S.meta_page(), "u")
    assert p.method == "meta" and p.price == D("2100") and p.tax_basis == "excl_gst"


def test_next_data_single_variant_price_confirmed_on_page():
    p = parse_product_page(S.next_data_page(), "https://home-run.co/products/kei-homecab-90mtr-wire")
    assert p.method == "next_data" and p.price == D("1906.00") and not p.multi_variant


def test_next_data_cents_are_converted_only_if_page_shows_rupees():
    p = parse_product_page(S.next_data_page(cents=True), "https://home-run.co/products/kei-homecab-90mtr-wire")
    assert p.price == D("1906")  # 190600 cents -> 1906 because the page shows 1,906


def test_next_data_price_not_visible_is_rejected():
    p = parse_product_page(S.next_data_page(visible="₹ 999"), "https://home-run.co/products/kei-homecab-90mtr-wire")
    assert p.price is None and "next_data_price_not_visible_on_page" in p.problems


def test_next_data_many_variants_without_variant_param_is_multi_variant():
    vs = [{"id": "1", "title": "A", "price": "100.00"}, {"id": "2", "title": "B", "price": "200.00"}]
    p = parse_product_page(S.next_data_page(variants=vs), "https://home-run.co/products/kei-homecab-90mtr-wire")
    assert p.multi_variant


def test_next_data_variant_param_selects_variant():
    vs = [{"id": "gid://shopify/ProductVariant/1", "title": "A", "price": "100.00"},
          {"id": "gid://shopify/ProductVariant/2", "title": "B", "price": "1906.00"}]
    p = parse_product_page(S.next_data_page(variants=vs), "https://home-run.co/products/kei-homecab-90mtr-wire?variant=2")
    assert p.price == D("1906.00") and not p.multi_variant and "B" in p.identity_text


def test_no_price_found():
    p = parse_product_page("<html><body><h1>Hello</h1></body></html>", "u")
    assert p.price is None and "no_price_found" in p.problems


def test_broken_json_ld_does_not_crash():
    html = '<html><script type="application/ld+json">{not json</script><h1>x</h1></html>'
    assert parse_product_page(html, "u").price is None
