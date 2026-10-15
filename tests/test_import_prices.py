from decimal import Decimal as D

import pytest

from import_prices import apply_sheet, parse_price
from rtech_sync.models import Row


def test_parse_price_accepts_rupee_formats_and_rejects_bad_values():
    assert parse_price("₹3,089") == D(3089) and parse_price(" 2112.50 ") == D("2112.50")
    assert parse_price("Rs. 1,000") == D(1000) and parse_price("") is None
    for bad in ("abc", "0", "-5"):
        with pytest.raises(ValueError):
            parse_price(bad)


def test_only_filled_prices_change_manual_price_and_publish_is_untouched():
    rows = [Row(sku="A", publish="pending_review"), Row(sku="B", manual_price=D(10)), Row(sku="C")]
    sheet = [{"sku": "A", "your_price_incl_gst": "3,000"}, {"sku": "B", "your_price_incl_gst": "10"},
             {"sku": "C", "your_price_incl_gst": ""}]
    changes, problems = apply_sheet(sheet, rows)
    assert changes == [("A", None, D(3000))] and problems == []
    assert rows[0].manual_price == D(3000) and rows[0].publish == "pending_review"
    assert rows[2].manual_price is None


def test_unknown_sku_and_bad_price_are_reported():
    rows = [Row(sku="A")]
    changes, problems = apply_sheet([{"sku": "Z", "your_price_incl_gst": "5"},
                                     {"sku": "A", "your_price_incl_gst": "x"}], rows)
    assert changes == [] and len(problems) == 2 and rows[0].manual_price is None
