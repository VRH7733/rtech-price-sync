import importlib.util
import os
from decimal import Decimal
from pathlib import Path

os.environ.setdefault("WC_URL", "https://shop.example")
_spec = importlib.util.spec_from_file_location(
    "check_shop", Path(__file__).resolve().parents[1] / "tools" / "check_shop.py")
cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cs)


def test_expected_state_quote_for_hidden_or_unpriced():
    latest = {"items": {"A": {"price": "1990", "hidden": False},
                        "B": {"price": "500", "hidden": True},
                        "C": {"pending": ""}}}
    assert cs.expected_state(latest) == {"A": Decimal("1990"), "B": None, "C": None}


def test_store_state_reads_minor_units_and_quote_button():
    priced = {"type": "simple", "prices": {"price": "199000", "currency_minor_unit": 2},
              "add_to_cart": {"text": "Add to cart"}}
    quote = {"type": "external", "prices": {"price": "0", "currency_minor_unit": 2},
             "add_to_cart": {"text": "Request a Quote"}}
    assert cs.store_state(priced) == (Decimal("1990"), False)
    assert cs.store_state(quote) == (None, True)


def test_page_state_reads_sale_price_and_quote_button():
    sale = ('<p class="price"><del><bdi><span>&#8377;</span>2,500.00</bdi></del> '
            '<ins><bdi><span class="woocommerce-Price-currencySymbol">&#8377;</span>1,990.00</bdi></ins></p>'
            '<button class="single_add_to_cart_button button">Add to cart</button>')
    assert cs.page_state(sale) == (Decimal("1990.00"), False)
    quote = ('<p class="price"></p><a href="x" class="single_add_to_cart_button button alt">'
             'Request a Quote</a><footer>Request a Quote</footer>')
    assert cs.page_state(quote) == (None, True)
    # a site-wide "Request a Quote" link alone is not the product's button
    assert cs.page_state('<p class="price"></p><footer>Request a Quote</footer>') == (None, False)


def test_verdict():
    assert cs.verdict(None, None, True) == "ok_quote"
    assert cs.verdict(None, Decimal(5), False) == "should_be_quote"
    assert cs.verdict(Decimal(5), Decimal(5), False) == "ok_price"
    assert cs.verdict(Decimal(5), Decimal(6), False) == "wrong_price"
    assert cs.verdict(Decimal(5), None, True) == "missing_price"


def test_refusal_is_logged_and_tried_once_more(monkeypatch, capsys):
    import io
    import urllib.error
    calls = []

    def fake_open(req, timeout=60):
        calls.append(req.full_url)
        if len(calls) == 1:
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {"Server": "hcdn", "X-Other": "x"},
                                         io.BytesIO(b"<html>Access denied</html>"))

        class R(io.BytesIO):
            headers = {"X-WP-TotalPages": "1"}

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        return R(b"[]")
    monkeypatch.setattr(cs.urllib.request, "urlopen", fake_open)
    monkeypatch.setattr(cs.time, "sleep", lambda s: None)
    body, _ = cs.get("https://shop.example/x")
    assert body == "[]" and len(calls) == 2
    err = capsys.readouterr().err
    assert "HTTP 403" in err and "hcdn" in err and "Access denied" in err and "x-other" not in err
