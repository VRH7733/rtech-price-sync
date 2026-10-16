import importlib.util
import os
from types import SimpleNamespace

_spec = importlib.util.spec_from_file_location(
    "import_brand_images", os.path.join(os.path.dirname(__file__), "..", "tools", "import_brand_images.py"))
ib = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ib)


def _r(sku, brand, title):
    return SimpleNamespace(sku=sku, brand=brand, title=title)


ROWS = [
    _r("H1", "Havells", "Havells AHLHGXW060 Batten Holder (White)"),
    _r("L1", "Legrand", "Legrand Buzzer Myrius Classic White 1 Module, 6792 50"),
    _r("H2", "Havells", "Havells Life Guard 6 Sq.mm 1 Core Flame Retardant Low Smoke Halogen Cable Red (90 m)"),
    _r("H3", "Havells", "Havells Life Guard 2.5 Sq.mm 1 Core Flame Retardant Low Smoke Halogen Cable Blue (90 m)"),
    _r("H4", "Havells", "Havells Life Line 1.5 Sq.mm 1 Core Cable Red (90 m)"),
]


def test_model_codes():
    assert "AHLHGXW060" in ib.model_codes(ROWS[0].title)
    assert "679250" in ib.model_codes(ROWS[1].title)
    assert not ib.model_codes(ROWS[2].title)  # sizes like 90m or 6sqmm are not model numbers


def test_matching_by_model_number_and_by_words(tmp_path):
    for rel in ["Havells/AHLHGXW060_front.jpg", "Legrand/6792-50.png", "Havells/life-guard-red.jpg",
                "Havells/life-guard.jpg"]:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    best = ib.plan_matches(ROWS, ib.find_images(tmp_path))
    assert best["H1"][0].name == "AHLHGXW060_front.jpg" and best["H1"][1] == "model number"
    assert best["L1"][0].name == "6792-50.png"
    assert best["H2"][0].name == "life-guard-red.jpg"  # more specific file wins
    assert best["H3"][0].name == "life-guard.jpg"
    assert "H4" not in best  # "Life Line" is a different range
