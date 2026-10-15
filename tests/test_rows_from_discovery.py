from rows_from_discovery import build, category_of, hint_of, pack_of
from rtech_sync.models import Row


def cand(src, url, title, variant="", price="100", fetched="yes"):
    return {"source": src, "url": url, "title": title, "variant": variant, "price": price,
            "fetched": fetched, "http_status": "ok:200", "_ident": f"{title} {variant}", "_in_stock": True}


def test_pack_and_category_from_real_titles():
    assert pack_of("Polycab Optima+ 1.5 Sq.mm 1 Core FRLF Wire Black (90 m)") == "90 m"
    assert pack_of("Polycab Optima+ Wire LF FR 180 Meters / 1.5 Sqmm / Red") == "180 m"
    assert pack_of("Polycab Coupler 32 mm Outer Diameter UPVC Material Black Color (Pack of 24)") == "pack of 24"
    assert category_of("Polycab Coupler 32 mm") == "Pipes & Fittings"
    assert category_of("Havells Euro II 63A Single Pole C Curve MCB") == "Switchgear"


def test_hint_names_line_sizes_and_colour():
    h = hint_of("Polycab", "Polycab Optima+ 1.5 Sq.mm 1 Core FRLF Wire Black (90 m)", "90 m")
    assert h == "optima+; 1.5sqmm; 1 core; black"
    h = hint_of("Polycab", "Polycab Deep Circular Box Tee Type 3 Ways 20 mm Outer Diameter UPVC Black", "")
    assert h.startswith("deep; circular; tee") and "3 ways" in h and "20mm" in h


def test_build_matches_other_sites_only_when_unique_and_skips_known_products():
    disc = {
        "industrybuying": [cand("industrybuying", "ib1", "Polycab Optima+ 1.5 Sq.mm 1 Core FRLF Wire Black (90 m)"),
                           cand("industrybuying", "ib2", "Polycab Optima+ 1.5 Sq.mm 1 Core FRLF Wire Black (90 m)")],
        "homerun": [cand("homerun", "hr1", "Polycab Optima+ Wire 1 Core 90 m", "1.5 sq mm / Black")],
        "moglix": [],
    }
    rows = build("Polycab", disc, [])
    assert len(rows) == 1  # ib2 is the same product listed twice: not a second shop product
    r = rows[0]
    assert r.sku == "RT-POLY-001" and r.publish == "pending_review" and r.category == "Wires & Cables"
    assert r.urls == {"industrybuying": "ib1", "homerun": "hr1"}
    existing = [Row(sku="RT-POLY-007", brand="Polycab", variant_hint=r.variant_hint, pack_size="90 m",
                    urls={"industrybuying": "x"})]
    assert build("Polycab", disc, existing) == []  # already in the catalogue
