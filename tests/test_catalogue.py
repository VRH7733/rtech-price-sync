from pathlib import Path

import pytest
from rtech_sync.catalogue import CatalogueError, load_catalogue, validate, write_catalogue
from rtech_sync.config import load_config
from rtech_sync.models import CATALOGUE_COLUMNS

ROOT = Path(__file__).resolve().parent.parent
HEADER = ",".join(CATALOGUE_COLUMNS)


@pytest.fixture
def cfg():
    return load_config(ROOT / "config.yaml", env={"RTECH_CONTACT_EMAIL": "a@b.c"})


def write(tmp_path, *lines, name="polycab.csv"):
    (tmp_path / name).write_text(HEADER + "\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return tmp_path


def rec(**kw):
    base = {c: "" for c in CATALOGUE_COLUMNS}
    base.update(sku="P1", wc_product_id="10", brand="Polycab", mode="priced", publish="yes",
                variant_hint="1.5 sq mm", url_homerun="https://home-run.co/products/x")
    base.update(kw)
    return ",".join(f'"{base[c]}"' for c in CATALOGUE_COLUMNS)


def test_valid_catalogue_loads_and_validates(tmp_path, cfg):
    rows = load_catalogue(write(tmp_path, rec()))
    assert rows[0].urls == {"homerun": "https://home-run.co/products/x"} and validate(rows, cfg) == []


def test_search_url_rejected(tmp_path, cfg):
    rows = load_catalogue(write(tmp_path, rec(url_moglix="https://www.moglix.com/search?searchTerm=wire")))
    assert any("search" in p for p in validate(rows, cfg))


def test_wrong_domain_rejected(tmp_path, cfg):
    rows = load_catalogue(write(tmp_path, rec(url_moglix="https://evil.example.com/p")))
    assert any("not on moglix.com" in p for p in validate(rows, cfg))


def test_lookalike_domain_rejected(tmp_path, cfg):
    rows = load_catalogue(write(tmp_path, rec(url_moglix="https://notmoglix.com/p")))
    assert any("not on moglix.com" in p for p in validate(rows, cfg))


def test_duplicate_sku_and_missing_wc_id_and_missing_hint(tmp_path, cfg):
    rows = load_catalogue(write(tmp_path, rec(), rec(), rec(sku="P2", wc_product_id="", variant_hint="")))
    probs = " | ".join(validate(rows, cfg))
    assert "duplicate SKU" in probs and "wc_product_id" in probs and "variant_hint" in probs


def test_bad_values_rejected(tmp_path, cfg):
    rows = load_catalogue(write(tmp_path, rec(mode="sale", publish="maybe", markup_pct="-5")))
    probs = " | ".join(validate(rows, cfg))
    assert "mode must be" in probs and "publish must be" in probs and "negative" in probs


def test_non_numeric_price_is_a_clear_error(tmp_path):
    with pytest.raises(CatalogueError):
        load_catalogue(write(tmp_path, rec(manual_price="abc")))


def test_pending_review_rows_need_nothing(tmp_path, cfg):
    rows = load_catalogue(write(tmp_path, rec(publish="pending_review", wc_product_id="", variant_hint="")))
    assert validate(rows, cfg) == []


def test_quote_rows_need_no_urls(tmp_path, cfg):
    rows = load_catalogue(write(tmp_path, rec(mode="quote", url_homerun="", variant_hint="")))
    assert validate(rows, cfg) == []


def test_roundtrip_write(tmp_path):
    rows = load_catalogue(write(tmp_path, rec(manual_price="99.5", cost_floor="10")))
    out = tmp_path / "out.csv"
    write_catalogue(out, rows)
    again = load_catalogue(tmp_path)  # loads polycab.csv + out.csv
    assert [r.manual_price for r in again if r.source_file.startswith("out")][0] == rows[0].manual_price


def test_thousands_separator_in_numbers_accepted(tmp_path):
    rows = load_catalogue(write(tmp_path, rec(manual_price="1,234.50")))
    assert str(rows[0].manual_price) == "1234.50"
