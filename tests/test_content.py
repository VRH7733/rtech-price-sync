import importlib.util
import os
from types import SimpleNamespace

import pytest

from rtech_sync.content import classify, headline, plan_row, specs

_spec = importlib.util.spec_from_file_location(
    "enrich_products", os.path.join(os.path.dirname(__file__), "..", "tools", "enrich_products.py"))
ep = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ep)


@pytest.mark.parametrize("title,kind,cat", [
    ("KEI 1.5 Sq.mm 6 Core Flexible FRLS Multistrand Industrial Cable Black (100 m)", "multicore", "Wires & Cables"),
    ("Havells Life Guard 6 Sq.mm 1 Core Flame Retardant Low Smoke Halogen Cable Green (90 m)", "wire", "Wires & Cables"),
    ("Havells WHOJTTKARG08 RG 06 CCS Co-Axial Cable 305 m", "coax", "Wires & Cables"),
    ("Legrand RX³ RCCB Double Pole 100mA (AC Type) 40A", "rccb", "Protection & Switchgear"),
    ("Havells Astura ES White Pearl Ivory 1200 mm Ceiling Fan", "fan", "Fans"),
    ("GM Figo 50 W 6500 K Cool White LED Flood Light", "light", "Lighting"),
    ("Havells HBTM2 Single Phase 0.5 HP Booster Pressure Pump", "pump", "Water Pumps"),
    ("Polycab conduit pipe Super 25 mm Grey (pack of 50)", "pipe", "Rigid Conduits"),
])
def test_classify(title, kind, cat):
    k, _, c = classify(title)
    assert (k, c) == (kind, cat)


def test_specs_only_what_the_title_says():
    s = specs("KEI 1.5 Sq.mm 6 Core Flexible FRLS Multistrand Industrial Cable Black (100 m)", "KEI", "multicore")
    assert s == {"Brand": "KEI", "Size": "1.5 sq mm", "Cores": "6", "Length": "100 m",
                 "Insulation": "FRLS", "Colour": "Black"}
    assert headline(s, "multicore") == "6 core  ·  1.5 sq mm  ·  100 m"
    s = specs("Legrand RX³ RCCB Double Pole 100mA (AC Type) 40A", "Legrand", "rccb")
    assert s["Poles"] == "DP" and s["Sensitivity"] == "100 mA" and s["Current rating"] == "40 A"


def test_tile_name_is_stable_and_shared_by_identical_tiles():
    a = plan_row("Havells 1.5 Sq.mm 1 Core FR Wire Red (90 m)", "Havells")
    b = plan_row("Havells Life Line 1.5 sq mm 1 Core FR House Wire Red 90 m", "Havells")
    assert a["tile_name"] == b["tile_name"] and a["tile_name"].endswith(".webp")
    c = plan_row("Havells 1.5 Sq.mm 1 Core FR Wire Blue (90 m)", "Havells")
    assert c["tile_name"] != a["tile_name"]


IDS = {"categories": {"Wires & Cables": 25, "Fans": 40}, "brands": {"KEI": 7}, "attributes": {"Size": 3}}
PLAN = plan_row("KEI 1.5 Sq.mm 6 Core Flexible FRLS Multistrand Industrial Cable Black (100 m)", "KEI")


def _cur(**kw):
    base = {"id": 11, "name": "KEI cable", "description": "", "short_description":
            "<p>Brand: KEI. Pack: 100 m. Prices include GST.</p>\n", "categories":
            [{"id": 15, "slug": "uncategorized"}], "brands": [], "attributes": [], "images": []}
    base.update(kw)
    return base


def test_fills_only_empty_fields_and_never_price_or_stock():
    p = ep.update_payload(_cur(), PLAN, IDS, "https://x/t.webp", {})
    assert set(p) == {"id", "description", "short_description", "categories", "brands", "attributes",
                      "images", "meta_data"}
    assert p["categories"] == [{"id": 25}] and p["brands"] == [7]
    assert p["images"][0]["src"] == "https://x/t.webp"
    size = [x for x in p["attributes"] if x.get("id") == 3]
    assert size and size[0]["options"] == ["1.5 sq mm"]
    assert not (ep.FORBIDDEN & set(p))


def test_hand_edits_are_kept():
    cur = _cur(description="<p>Harshi wrote this</p>", short_description="<p>my text</p>",
               categories=[{"id": 25, "slug": "wires-cables"}], brands=[{"id": 7}],
               attributes=[{"name": "x"}], images=[{"id": 5}])
    assert ep.update_payload(cur, PLAN, IDS, "u", {}) == {"id": 11}


def test_known_illustration_is_reused_not_uploaded_again():
    p = ep.update_payload(_cur(), PLAN, IDS, "u", {PLAN["tile_name"]: 99})
    assert p["images"][0]["id"] == 99 and "src" not in p["images"][0]


class FakeWoo:
    def __init__(self, products):
        self.products = {p["id"]: p for p in products}
        self.posts = []

    def get(self, path, params=None):
        if path == "/products":
            ids = [int(x) for x in params["include"].split(",")]
            return 200, [self.products[i] for i in ids if i in self.products], {}
        return 200, [{"id": 25, "name": "Wires &amp; Cables"}], {"X-WP-TotalPages": "1"}

    def all(self, path, params=None):
        return self.get(path)[1]

    def post(self, path, payload):
        self.posts.append((path, payload))
        if path == "/products/batch":
            return 200, {"update": [dict(x, images=[{"id": 500 + x["id"]}], permalink="p")
                                    for x in payload["update"]]}
        return 201, {"id": 900 + len(self.posts)}


def _row(sku, pid, title="KEI 1.5 Sq.mm 6 Core Flexible FRLS Multistrand Industrial Cable Black (100 m)"):
    return SimpleNamespace(sku=sku, wc_product_id=pid, title=title, brand="KEI", category="", publish="yes",
                           wc_variation_id=None)


def test_plan_only_writes_nothing(tmp_path):
    woo = FakeWoo([_cur(id=1, meta_data=[{"key": "_rte_source"}])])
    a = SimpleNamespace(apply=False, media_map=str(tmp_path / "m.json"), tile_base_url="https://x")
    result, payloads, _ = ep.run_apply([_row("A", 1)], a, woo, sleep=lambda s: None, log=lambda m: None)
    assert woo.posts == [] and len(payloads) == 1


def test_apply_uploads_each_illustration_once_and_skips_foreign_products(tmp_path):
    ours = [{"key": "_rte_source", "value": "rtech-price-sync"}]
    woo = FakeWoo([_cur(id=1, meta_data=ours), _cur(id=2, meta_data=ours), _cur(id=3, meta_data=[])])
    a = SimpleNamespace(apply=True, media_map=str(tmp_path / "m.json"), tile_base_url="https://x")
    result, _, media = ep.run_apply([_row("A", 1), _row("B", 2), _row("C", 3)], a, woo,
                                    sleep=lambda s: None, log=lambda m: None)
    batches = [p for path, p in woo.posts if path == "/products/batch"]
    assert [len(b["update"]) for b in batches] == [1, 1]
    assert "src" in batches[0]["update"][0]["images"][0]
    assert batches[1]["update"][0]["images"][0] == {"id": 501, "alt": "KEI cable (illustration)"}
    assert result["skipped"]["not ours"] == 1 and media[PLAN["tile_name"]] == 501
    for b in batches:
        for item in b["update"]:
            assert not (ep.FORBIDDEN & set(item))


def test_illustrations_spread_over_16_releases():
    name = PLAN["tile_name"]
    url = ep.tile_url("https://g/releases/download/product-illustrations-{bucket}", name)
    assert url == f"https://g/releases/download/product-illustrations-{name.rsplit('-', 1)[1][0]}/{name}"
    assert ep.tile_bucket(name) in "0123456789abcdef"
