"""tools/seed_to_rows.py and tools/match_discovery.py (offline)."""
import csv
import importlib.util
from pathlib import Path

from rtech_sync.catalogue import load_catalogue

ROOT = Path(__file__).resolve().parent.parent


def tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


seed_to_rows, match_discovery = tool("seed_to_rows"), tool("match_discovery")

SEED = [
    {"tier": "1", "brand": "Polycab", "category": "Wires & Cables", "family": "House wire (FR)",
     "title": "Polycab FR PVC house wire 1.5 sq mm Red 90 m", "pack_size": "90 m coil",
     "variant_hint": "single core copper, 1.5 sq mm, Red, 90 m", "notes": ""},
    {"tier": "2", "brand": "VIP", "category": "Pipes & Fittings", "family": "Conduit fittings",
     "title": "VIP conduit bend 20 mm", "pack_size": "1 pc", "variant_hint": "20 mm bend", "notes": ""},
]


def write_disc(d, rows):
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "x.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["source", "url", "fetched", "http_status", "price", "in_stock", "identity"])
        w.writeheader()
        w.writerows(rows)


def test_seed_rows_get_new_skus_clean_hints_and_no_urls(tmp_path):
    by = seed_to_rows.convert(SEED, ["Polycab", "VIP"])
    p, v = by["Polycab"][0], by["VIP"][0]
    assert p["sku"] == "RT-POLY-001" and p["pack_size"] == "90 m" and p["variant_hint"] == "1.5 sq mm; red"
    assert v["sku"] == "RT-VIP-001" and v["pack_size"] == "" and v["variant_hint"] == "20 mm; bend"
    assert p["publish"] == "no" and "url_moglix" not in p


def test_moglix_slug_decimal_is_restored_only_for_impossible_sizes():
    s = match_discovery.slug_identity("https://www.moglix.com/polycab-etira-15-sqmm-90m-red-fr-cable/mp/msn1")
    assert "1.5sqmm" in s.replace(" ", "")
    assert "10sqmm" in match_discovery.slug_identity("https://www.moglix.com/polycab-10-sqmm-90m/mp/x").replace(" ", "")


def test_unique_match_is_written_ambiguous_and_multicore_are_not(tmp_path):
    rows_dir = tmp_path / "rows"
    rows_dir.mkdir()
    seed_to_rows.main([str(_seed_file(tmp_path)), str(rows_dir), "--brand", "Polycab"])
    write_disc(tmp_path / "disc", [
        # Moglix: two different lines pass for the same size/colour/length -> ambiguous
        {"source": "moglix", "url": "https://www.moglix.com/polycab-etira-15-sqmm-90m-red-single-core-fr/mp/a", "fetched": "no"},
        {"source": "moglix", "url": "https://www.moglix.com/polycab-maxima-15-sqmm-90m-red-fr/mp/b", "fetched": "no"},
        # IndustryBuying: one single-core page passes; a 3-core cable page must not
        {"source": "industrybuying", "url": "https://www.industrybuying.com/x-polycab-1", "fetched": "yes",
         "http_status": "ok:200", "price": "5073", "in_stock": "True",
         "identity": "Polycab Optima+ 1.5 Sq.mm 1 Core FRLF Wire Red (90 m)"},
        {"source": "industrybuying", "url": "https://www.industrybuying.com/x-polycab-2", "fetched": "yes",
         "http_status": "ok:200", "price": "9000", "in_stock": "True",
         "identity": "Polycab 3 Core 1.5 Sq.mm Flexible Cable Red (90 m)"},
    ])
    review = []
    rows = load_catalogue(rows_dir)
    n = match_discovery.match(rows, match_discovery.load_discovery(tmp_path / "disc"), review)
    r = rows[0]
    assert n == 1 and r.urls.get("industrybuying") == "https://www.industrybuying.com/x-polycab-1"
    assert not r.urls.get("moglix") and len(review) == 2
    assert r.publish == "pending_review" and r.publish != "yes"


def _seed_file(tmp_path):
    p = tmp_path / "seed.csv"
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(SEED[0]))
        w.writeheader()
        w.writerows(SEED)
    return p
