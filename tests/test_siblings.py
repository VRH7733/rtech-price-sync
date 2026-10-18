"""Sibling guard: a single-site wire price far from the same size in other colours/lines."""
from decimal import Decimal as D

from rtech_sync.decision import Decision
from rtech_sync.models import Row, SourceResult
from rtech_sync.siblings import apply_sibling_guard, spec_key


def item(sku, title, prices, pack="90 m", brand="Polycab"):
    results = [SourceResult(s, "ok", price=D(p)) for s, p in prices.items()]
    src = min(prices, key=lambda s: D(prices[s]))
    d = Decision(sku, "publish", price=D(prices[src]), cheapest_source=src, refreshed=True)
    return {"row": Row(sku=sku, brand=brand, title=title, pack_size=pack), "decision": d, "results": results}


def wire(colour):
    return f"Polycab Suprema FR House Cable 2.5 Sq. mm 1 Core {colour}"


def test_key_is_brand_size_cores_length_armour():
    assert spec_key(Row(sku="a", brand="Polycab", title=wire("Red"), pack_size="90 m")) == \
        ("polycab", "2.5", "1", "90", False)
    assert spec_key(Row(sku="a", brand="KEI", title="KEI 4 Core 6 sqmm armoured cable", pack_size="100 m")) == \
        ("kei", "6", "4", "100", True)
    assert spec_key(Row(sku="a", brand="Legrand", title="Legrand 6 Module Plate", pack_size="")) is None


def test_inflated_single_site_price_becomes_quote():
    items = [item("A", wire("Black"), {"industrybuying": "9203"}),
             item("B", wire("Red"), {"homerun": "4400"}),
             item("C", wire("Blue"), {"homerun": "4500", "moglix": "4600"}),
             item("D", wire("Green"), {"industrybuying": "4450"})]
    assert apply_sibling_guard(items, D(2)) == ["A"]
    d = items[0]["decision"]
    assert d.action == "hide" and d.price is None and d.flags == ["sibling_outlier:industrybuying"]
    assert all(it["decision"].action == "publish" for it in items[1:])


def test_inflated_siblings_never_hide_a_real_low_price():
    items = [item("A", wire("Black"), {"homerun": "4400"}),
             item("B", wire("Red"), {"industrybuying": "13000"}),
             item("C", wire("Blue"), {"industrybuying": "14000"})]
    assert apply_sibling_guard(items, D(2)) == []  # B and C have only each other (same site)


def test_suspiciously_low_price_needs_cross_checked_siblings():
    items = [item("A", wire("Black"), {"industrybuying": "900"}),
             item("B", wire("Red"), {"homerun": "4400", "moglix": "4500"}),
             item("C", wire("Blue"), {"homerun": "4500", "industrybuying": "4700"})]
    assert apply_sibling_guard(items, D(2)) == ["A"]


def test_needs_two_references_and_same_length_and_can_be_off():
    one_ref = [item("A", wire("Black"), {"industrybuying": "9203"}), item("B", wire("Red"), {"homerun": "4400"})]
    assert apply_sibling_guard(one_ref, D(2)) == []
    other_len = [item("A", wire("Black"), {"industrybuying": "9203"}, pack="180 m"),
                 item("B", wire("Red"), {"homerun": "4400"}), item("C", wire("Blue"), {"homerun": "4500"})]
    assert apply_sibling_guard(other_len, D(2)) == []
    full = [item("A", wire("Black"), {"industrybuying": "9203"}),
            item("B", wire("Red"), {"homerun": "4400"}), item("C", wire("Blue"), {"homerun": "4500"})]
    assert apply_sibling_guard(full, D(0)) == [] and full[0]["decision"].action == "publish"
    assert apply_sibling_guard(full, D(2)) == ["A"]


def test_seller_listing_alone_becomes_quote_but_counts_with_a_second_site():
    from rtech_sync.siblings import apply_listing_guard
    pats = {"industrybuying": "-ELE."}
    alone = item("A", "Legrand Cable Tie 357mm (Pack of 100 Pcs)", {"industrybuying": "18879"}, pack="pack of 100")
    alone["row"].urls = {"industrybuying": "https://www.industrybuying.com/cable-ties-legrand-ELE.CAB.133447955"}
    own = item("B", "Polycab wire", {"industrybuying": "4465"})
    own["row"].urls = {"industrybuying": "https://www.industrybuying.com/x-polycab-EL.CA.HO.HA.169619"}
    pair = item("C", "Polycab wire", {"industrybuying": "4800", "homerun": "4875"})
    pair["row"].urls = {"industrybuying": "https://x/y-ELE.FLA.1", "homerun": "https://h/z"}
    assert apply_listing_guard([alone, own, pair], pats) == ["A"]
    d = alone["decision"]
    assert d.action == "hide" and d.price is None and d.flags == ["unconfirmed_listing:industrybuying"]
    assert apply_listing_guard([own], {}) == []


def test_config_loads_the_seller_listing_rule():
    from pathlib import Path
    from rtech_sync.config import load_config
    cfg = load_config(Path(__file__).resolve().parent.parent / "config.yaml", env={"RTECH_CONTACT_EMAIL": "x@example.com"})
    assert cfg.pricing.needs_second_site == {"industrybuying": "-ELE."} and cfg.pricing.sibling_ratio == 2


def test_cable_price_impossible_for_its_copper_becomes_quote():
    from rtech_sync.siblings import apply_cable_guard
    kei = "KEI 400 Sq.mm 1 Core HRFR Flexible Cable Black (100 m)"
    items = [item("KEI-332", kei, {"industrybuying": "4060805"}, pack="100 m"),  # Rs 101 per sq mm-m
             item("OK", wire("Red"), {"homerun": "4400"}),  # 2.5 sq mm x 90 m: Rs 19.6
             item("SPK", "Finolex Speaker Cable, 100m 1.5 Sqmm", {"moglix": "5841"}, pack="100 m"),  # Rs 38.9
             item("CTL", "Havells Unarmoured 2XY LT Control Cable 61 Core 2.5 Sq.mm",
                  {"industrybuying": "13569500"}, pack=""),
             item("TWO", kei, {"industrybuying": "4060805", "moglix": "4100000"}, pack="100 m"),
             item("PLATE", "Legrand 6 Module Plate", {"industrybuying": "999999"}, pack="")]
    assert apply_cable_guard(items, D(50)) == ["KEI-332", "CTL"]
    assert items[0]["decision"].flags == ["cable_price_per_metre:industrybuying"]
    assert items[3]["decision"].flags == ["cable_length_unknown:industrybuying"]
    assert all(it["decision"].action == "publish" for it in items[1:3] + items[4:])  # two sites: outlier guard's job
    assert apply_cable_guard([item("X", kei, {"industrybuying": "4060805"}, pack="100 m")], D(0)) == []


def test_live_config_has_the_cable_guard():
    from pathlib import Path
    from rtech_sync.config import load_config
    cfg = load_config(Path(__file__).resolve().parents[1] / "config.yaml", env={"RTECH_CONTACT_EMAIL": "a@b.co"})
    assert cfg.pricing.cable_max_per_sqmm_metre == D(50)
