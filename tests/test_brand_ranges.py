"""Range photos for wires (tools/brand_ranges.py and the range route of tools/brand_images.py).
The page tests use REAL brand pages saved 10 Nov 2026 (tests/fixtures/real/ranges/README.md)."""
import importlib.util
import io
import json
import os
import sys

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
_spec = importlib.util.spec_from_file_location("brand_images", os.path.join(HERE, "..", "tools", "brand_images.py"))
bi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bi)
import brand_ranges as br  # noqa: E402

FIX = os.path.join(HERE, "fixtures", "real", "ranges")
R = {r.key: r for _, r in br.all_ranges()}


def _fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


def _png(w, h, bg=(255, 255, 255), box=None, color=(30, 60, 200)):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (w, h), bg)
    ImageDraw.Draw(im).rectangle(box or (w // 4, h // 4, 3 * w // 4, 3 * h // 4), fill=color)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _key(brand, title):
    r, why = br.range_for(brand, title)
    return r.key if r else why


# ---------------------------------------------------------------- which range a title belongs to
# (titles copied from the shop's product list, 25 Oct 2026)

def test_havells_lifeline_ranges_are_told_apart():
    assert _key("havells", "Havells Life Line Plus S3 FR Wire, 90m 4 sqmm / Green") == "havells/lifeline-plus-s3"
    assert _key("havells", "Havells Life Line Plus S3 185 Sq.mm 1 Core HRFR Flexible Electrical Cable "
                           "Annealed Copper 1000 m Black") == "havells/lifeline-plus-s3"
    assert _key("havells", "Havells Life Line Plus 6 Sq.mm 1 Core Flame Retardant HRFR House Cable White, 90 m") \
        == "havells/lifeline-plus-hrfr"
    assert _key("havells", "Havells Lifeline FR Wire, 180m 1.5 Sqmm / Blue") == "havells/lifeline-fr"
    assert _key("havells", "Havells Life Line 2.5 Sq.mm 1 Core Flame Retardant (FR) Industrial Cable Red, 200 m") \
        == "havells/lifeline-fr"
    assert _key("havells", "Havells Life Guard FR-LSH Wire 180 Meters / 4 Sqmm / Black") == "havells/life-guard"
    assert _key("havells", "Havells Life Shield Industrial Flexible Cable Halogen-Free 1 mm² Nominal Area 1 Core "
                           "Red 180 m Length") == "havells/life-shield"
    # Lifeline Plus without HRFR in the title, and Havells' separate 'Life Line S3 FR' range: no guess
    assert not br.range_for("havells", "Havells Life Line Plus 1.5 Sq.mm Cable Red")[0]
    assert not br.range_for("havells", "Havells Life Line S3 FR 10 Sq.mm Cable Red")[0]
    assert not br.range_for("havells", "Havells 0.5 Sq.mm 6 Core Flexible Cable Black (100 m)")[0]


def test_kei_conflame_green_plus_and_multicore_family():
    assert _key("kei", "KEI Conflame Green+ FR-LSH Wire, 90m 1 sqmm / Blue") == "kei/conflame-green-plus"
    assert _key("kei", "KEI Conflame 16 Sq.mm 1 Core Flame Retardant Low Smoke Halogen Industrial Cable Yellow (90 m)") \
        == "kei/conflame"
    assert _key("kei", "KEI FR-LSH Multistrand Cable Conflame -FR-LSH 0.50 Sq. mm 1 Core Red (300 m)") == "kei/conflame"
    fam, _ = br.range_for("kei", "KEI 4 Sq.mm 4 Core Flexible FRLS Multistrand Industrial Cable Black (100 m)")
    assert fam.key == "kei/multicore-flexible" and fam.kind == "family"
    assert br.range_for("kei", "KEI Flexible Industrial Multistranded Cable FRLS PVC Sheathed 4 mm² 19 Core "
                               "Black (100 m)")[0].key == "kei/multicore-flexible"
    # the family photo shows a multicore cable: never for a single core
    assert not br.range_for("kei", "KEI 1.5 Sq.mm 1 Core Flexible FRLSH Multistrand Industrial Cable Red (100 m)")[0]


def test_rr_kabel_range_beats_family_and_superex_variants():
    assert _key("rrkabel", "RR Kabel Unilay HRFR 4 Sq. mm 1 Core Flame Retardant (FR) House Cable Blue (90 m)") \
        == "rrkabel/unilay"
    assert _key("rrkabel", "RR Kabel Superex FR 1.5 Sq.mm 1 Core Flame Retardant (FR) House Cable Yellow (90 m)") \
        == "rrkabel/superex-fr"
    assert _key("rrkabel", "RR Kabel Superex Green HR+FR 1.5 Sq.mm Wire") == "rrkabel/superex-green"
    # names FR-LSH (range) and also says it in words (family): the range wins
    r, _ = br.range_for("rrkabel", "RR Kabel FR-LSH 0.75 Sq. mm 1 Core Flame Retardant Low Smoke Halogen Cable Grey (200 m)")
    assert r.key == "rrkabel/fr-lsh" and r.kind == "range"
    r, _ = br.range_for("rrkabel", "RR Kabel 1.5 Sq.mm 1 Core Flame Retardant Low Smoke Halogen Cable Red (90 m)")
    assert r.key == "rrkabel/fr-lsh-words" and r.kind == "family"
    assert _key("rrkabel", "RR Kabel LSOH FR 2.5 Sq.mm 1 Core Industrial Cable Black (100 m)") == "rrkabel/ls0h-fr"
    assert not br.range_for("rrkabel", "RR Kabel 0.75 Sq.mm 7 Core Industrial Braided Cable Grey (100 m)")[0]


def test_two_ranges_of_the_same_kind_give_nothing(monkeypatch):
    monkeypatch.setitem(br.RANGES, "x", [br.Range("x/a", "A", r"\balpha\b"), br.Range("x/b", "B", r"\bwire\b")])
    r, why = br.range_for("x", "X Alpha house wire 1.5 sq mm Red")
    assert r is None and "several" in why


def test_finolex_and_polycab_ranges():
    assert _key("finolex", "Finolex Silver FR Wire 90 Meters / 4 Sqmm / Green") == "finolex/silver"
    assert _key("finolex", "Finolex Gold 0.75 Sq.mm 1 Core Flame Retardant (FR) Industrial Cable Green (90 m)") \
        == "finolex/gold"
    assert _key("finolex", "Finolex Flamegard FR-LSH Wire 180 Meters / 1.5 Sqmm / Yellow") == "finolex/flamegard"
    assert _key("polycab", "Polycab Maxima+ house wire 1.5 sq mm Blue 90 m") == "polycab/maxima-plus"
    assert _key("polycab", "Polycab Optima+ 16 Sq.mm 1 Core FRLF Wire Blue (90 m)") == "polycab/optima-plus"
    assert not br.range_for("polycab", "Polycab 4 Sq.mm 1 Core FRLF House Cable Black (200 m)")[0]


def test_every_range_page_is_on_the_brands_own_site():
    home = {"havells": "havells.com", "kei": "kei-ind.com", "rrkabel": "rrkabel.com", "finolex": "finolex.com",
            "polycab": "polycab.com"}
    for key, r in br.all_ranges():
        assert key in bi.BRANDS
        for p in r.pages:
            assert bi._brand_domain(bi.urlsplit(p).netloc) == home[key], p
        assert r.pages or r.site_ranges, r.key
        for bad in ("moglix", "industrybuying", "indiamart", "amazon", "flipkart"):
            assert bad not in " ".join(r.pages)


# ---------------------------------------------------------------- the photo on the brand's range page (REAL pages)

def _imgs(fixture, url, key):
    r = R[key]
    return bi.range_page_images(_fixture(fixture), url, r.image, r.name.split())


def test_havells_range_page_lists_only_its_own_range_and_drops_resize_query():
    got = _imgs("havells_lifeline_hrfr.html", "https://havells.com/home-electricals/flexible-cables/lifeline-hrfr.html",
                "havells/lifeline-plus-s3")
    assert got[0]["url"] == "https://havells.com/media/catalog/product/w/h/whffdnka1x50_1.jpg"
    assert all("Plus S3" in g["alt"] for g in got) and len(got) == 7
    # the 'Life Line S3 FR' tile on the same page (another range) and the offer pictures are left out
    assert not any("whffdnrb1010" in g["url"] or "wysiwyg" in g["url"] for g in got)


def test_havells_photo_colour_comes_from_the_file_name():
    got = _imgs("havells_life_guard.html", "https://havells.com/home-electricals/flexible-cables/life-guard-fr-lsh.html",
                "havells/life-guard")
    assert [(g["url"].rsplit("/", 1)[-1], g["colour"]) for g in got] == [("green_6.jpg", "green"), ("black.jpg", "black")]
    fr = _imgs("havells_lifeline_fr.html", "https://havells.com/home-electricals/flexible-cables/lifeline-fr.html",
               "havells/lifeline-fr")
    assert fr and all(g["colour"] == "red" and "lifeline_fr_red" in g["url"] for g in fr)


def test_kei_photo_from_structured_data_not_menu_or_logo():
    got = _imgs("kei_con_flame_frls.html", "https://www.kei-ind.com/cables-and-wires/house-wire/con-flame-frls/",
                "kei/conflame")
    assert [g["url"] for g in got] == ["https://www.kei-ind.com/wp-content/uploads/2018/04/con-flame-product-2.png"]
    fam = _imgs("kei_single_multicore_flexibles.html",
                "https://www.kei-ind.com/cables-and-wires/single-and-multicore-flexibles/", "kei/multicore-flexible")
    assert [g["url"] for g in fam] == ["https://www.kei-ind.com/wp-content/uploads/2018/05/single-multicore-pro.png"]


def test_rr_kabel_page_photo_and_a_related_range_photo_by_file_name():
    url = "https://www.rrkabel.com/products/unilay-hr-fr/"
    assert [g["url"] for g in _imgs("rrkabel_unilay_hr_fr.html", url, "rrkabel/unilay")] == [
        "https://www.rrkabel.com/wp-content/uploads/2023/07/Wire-1-1.png"]
    sup = _imgs("rrkabel_unilay_hr_fr.html", url, "rrkabel/superex-fr")
    assert [g["url"] for g in sup] == [
        "https://www.rrkabel.com/wp-content/uploads/2025/08/Superex-FR-New_Front-Front-Left-.png"]


def test_finolex_photo_in_the_page_body_with_spaces_in_the_file_name():
    got = _imgs("finolex_fr_silver.html",
                "https://www.finolex.com/ProductPage/Prod/House-Wires~Flame-Retardant-FR-Grade-90Mtr-Silver", "finolex/silver")
    assert [g["url"] for g in got] == [
        "https://www.finolex.com/UploadedDocs/Flame%20Retardant%20(FR)%20Grade%20(90Mtr)%20Silver(400x400).png"]


def test_images_on_other_domains_are_never_candidates():
    html = ('<html><body><main><h1>Unilay HR FR</h1>'
            '<img src="https://cdn.moglix.com/unilay-hr-fr.jpg" alt="Unilay">'
            '<img src="https://www.rrkabel.com/wp-content/uploads/unilay-hr-fr.png" alt="Unilay"></main></body></html>')
    got = bi.range_page_images(html, "https://www.rrkabel.com/products/unilay-hr-fr/", "", ["Unilay"])
    assert [g["url"] for g in got] == ["https://www.rrkabel.com/wp-content/uploads/unilay-hr-fr.png"]


# ---------------------------------------------------------------- refusal check (REAL page)

class _FR:
    def __init__(self, status, http=None, text="", content=b"", detail=""):
        self.status, self.http, self.text, self.content, self.detail = status, http, text, content, detail


def test_a_recaptcha_script_on_a_real_page_is_not_a_refusal():
    page = _fixture("polycab_campaign_green_wires.html")
    assert "recaptcha" in page.lower() and "<h1" not in page.lower() and len(page) < 20000
    bi._check(_FR("ok", 200, text=page), "https://polycab.com/campaign/green-wires")  # no Refused
    with pytest.raises(bi.Refused):
        bi._check(_FR("ok", 200, text="<html><title>Just a moment...</title><body>Verify you are human</body></html>"), "p")
    with pytest.raises(bi.Refused):
        bi._check(_FR("ok", 200, text="<html><body><p>Please complete the CAPTCHA</p></body></html>"), "p")


# ---------------------------------------------------------------- choosing the photo for one product

def _im(url, ok=False, range_ok=True, w=600, h=400, colour=""):
    return {"url": url, "ok": ok, "range_ok": range_ok, "w": w, "h": h, "reason": "", "colour": colour}


def _rrow(key, url, imgs, kind="range"):
    return {"range": key, "kind": kind, "url": url, "status": "ok:200", "images": json.dumps(imgs)}


def test_photo_in_our_colour_first_then_the_range_pages_main_photo():
    rng = R["havells/life-guard"]
    rows = [_rrow(rng.key, "https://havells.com/lg.html", [_im("https://h/green_6.jpg", colour="green"),
                                                          _im("https://h/black.jpg", colour="black")])]
    assert bi.choose_range_photo(rng, "black", rows, [])[1]["url"] == "https://h/black.jpg"
    page, im, note = bi.choose_range_photo(rng, "red", rows, [])
    assert im["url"] == "https://h/green_6.jpg" and "shows green" in note
    bad = [_rrow(rng.key, "https://havells.com/lg.html", [_im("https://h/x.jpg", range_ok=False)])]
    assert bi.choose_range_photo(rng, "red", bad, [])[2] == "brand range photo failed quality check"
    assert "no photo" in bi.choose_range_photo(rng, "red", [], [])[2]


def test_polycab_size_without_its_own_page_gets_the_same_range_and_colour():
    rng = R["polycab/optima-plus"]
    pages = [{"url": "https://polycab.com/optima-10-blue", "name": "POLYCABOPTIMA+ | LF-FR | 10 Sq. MM | 90 Meters | BLUE",
              "images": json.dumps([_im("https://cms.polycab.com/o10b.jpg", ok=True, w=400, h=400)])},
             {"url": "https://polycab.com/optima-10-red", "name": "POLYCABOPTIMA+ | LF-FR | 10 Sq. MM | 90 Meters | RED",
              "images": json.dumps([_im("https://cms.polycab.com/o10r.jpg", ok=True, w=400, h=400)])}]
    wire_pages = [(bi.wire_key(p["name"], "Polycab"), p) for p in pages]
    page, im, note = bi.choose_range_photo(rng, "red", [], wire_pages)
    assert im["url"] == "https://cms.polycab.com/o10r.jpg" and "in red" in note


def _t(sku, name, brand, image=""):
    return {"sku": sku, "id": sku[-1], "brand": brand, "name": name, "web": "", "ours": "1",
            "image_src": image, "image_id": "", "has_our_image": ""}


def test_plan_range_and_family_routes():
    targets = [_t("K1", "KEI Conflame 2.5 Sq.mm 1 Core Flame Retardant Low Smoke Halogen Industrial Cable Black (180 m)", "KEI"),
               _t("K2", "KEI 4 Sq.mm 4 Core Flexible FRLS Multistrand Industrial Cable Black (100 m)", "KEI"),
               _t("K3", "KEI Conflame 4 Sq.mm 1 Core Flame Retardant Low Smoke Halogen Industrial Cable Red (90 m)", "KEI",
                  image="https://shop/k3.jpg"),
               _t("K4", "KEI 1.5 Sq.mm 1 Core Flexible FRLSH Multistrand Industrial Cable Red (100 m)", "KEI")]
    ranges = {"kei": [
        _rrow("kei/conflame", "https://www.kei-ind.com/cables-and-wires/house-wire/con-flame-frls/",
              [_im("https://www.kei-ind.com/wp-content/uploads/2018/04/con-flame-product-2.png", w=530, h=300)]),
        _rrow("kei/multicore-flexible", "https://www.kei-ind.com/cables-and-wires/single-and-multicore-flexibles/",
              [_im("https://www.kei-ind.com/wp-content/uploads/2018/05/single-multicore-pro.png", w=423, h=418)],
              kind="family")]}
    rows = {r["sku"]: r for r in bi.plan(targets, {}, {}, ranges)}
    assert rows["K1"]["action"] == "add-range" and rows["K1"]["code"] == "range kei/conflame"
    assert rows["K1"]["page_url"].endswith("/con-flame-frls/") and "padded" in rows["K1"]["reason"]
    assert rows["K2"]["action"] == "add-family" and rows["K2"]["code"] == "family kei/multicore-flexible"
    assert rows["K3"]["action"] == "none"                       # has an image: range photos never replace one
    assert rows["K4"]["action"] == "none"                       # single core: no range, no family


def test_apply_puts_family_photos_on_only_when_allowed(tmp_path, monkeypatch):
    import csv as _csv
    from types import SimpleNamespace as NS
    monkeypatch.setattr(bi, "_night_ist", lambda now=None: False)
    plan = tmp_path / "plan.csv"
    base = dict(brand="KEI", name="KEI 4 Sq.mm 4 Core", code="family kei/multicore-flexible", page_url="https://kei/p",
                image_url="https://github.com/o/r/releases/download/brand-range-images/ab.jpg", w="423", h="418",
                reason="", result="")
    with open(plan, "w", newline="") as fh:
        w = _csv.DictWriter(fh, bi.PLAN_FIELDS)
        w.writeheader()
        w.writerow(dict(base, sku="K1", id="11", action="add-family"))
        w.writerow(dict(base, sku="K2", id="12", action="add-range"))
    sent = []

    class Woo:
        def get(self, path, params):
            return 200, [{"id": int(i), "images": [], "meta_data": []} for i in params["include"].split(",")], {}

        def post(self, path, body):
            sent.extend(body["update"])
            return 200, {"update": [{"id": p["id"], "images": [{"id": 900}]} for p in body["update"]]}

    args = dict(plan=str(plan), limit=0, allow_name=False, allow_range=True, batch=5)
    bi.cmd_apply(NS(**args, allow_family=False), Woo(), sleep=lambda s: None)
    assert [p["id"] for p in sent] == [12]
    bi.cmd_apply(NS(**args, allow_family=True), Woo(), sleep=lambda s: None)
    assert 11 in [p["id"] for p in sent]
    meta = {m["key"]: m["value"] for m in sent[-1]["meta_data"]}
    assert meta["_rte_image_source"] == "https://kei/p" and "_rte_image_url" in meta
    assert not bi.FORBIDDEN & set(sent[-1])


# ---------------------------------------------------------------- crawl of the range pages

def test_crawl_ranges_fetches_only_needed_pages_and_stops_on_refusal():
    from types import SimpleNamespace as NS
    page = _fixture("kei_con_flame_frls.html")
    img = _png(530, 300, box=(20, 40, 510, 260))
    calls = []

    class F:
        def __init__(self, refuse=False):
            self.refuse = refuse

        def get(self, url):
            calls.append(url)
            if self.refuse:
                return _FR("blocked", 403)
            if url.endswith(".png"):
                return NS(**vars(_FR("ok", 200, content=img)), final_url=url)
            return NS(**vars(_FR("ok", 200, text=page)), final_url=url)

    targets = [_t("K1", "KEI Conflame 2.5 Sq.mm 1 Core Flame Retardant Low Smoke Halogen Industrial Cable Black (180 m)", "KEI"),
               _t("K2", "KEI Homecab 2.5 Sq.mm 1 Core FR Cable Blue (180 m)", "KEI", image="https://shop/x.jpg")]
    rows, s = bi.crawl_ranges(F(), "kei", targets, lambda m: None)
    assert calls == ["https://www.kei-ind.com/cables-and-wires/house-wire/con-flame-frls/",
                     "https://www.kei-ind.com/wp-content/uploads/2018/04/con-flame-product-2.png"]  # Homecab not needed
    im = json.loads(rows[0]["images"])[0]
    assert rows[0]["range"] == "kei/conflame" and im["range_ok"] and (im["w"], im["h"]) == (530, 300)
    assert s["with_photo"] == 1 and s["products"] == 1 and not s["stopped"]
    rows, s = bi.crawl_ranges(F(refuse=True), "kei", targets, lambda m: None)
    assert not rows and s["stopped"].startswith("STOPPED")


def test_report_counts_each_route_per_brand():
    rows = [dict(sku="1", brand="KEI", action="add-range", code="range kei/conflame", result="",
                 reason="no image now; the brand's range photo, padded", image_url="https://kei/a.png"),
            dict(sku="2", brand="KEI", action="add-family", code="family kei/multicore-flexible", result="",
                 reason="no image now", image_url="https://kei/b.png"),
            dict(sku="3", brand="Havells", action="add-range", code="range havells/life-guard", result="",
                 reason="no image now; the brand's photo of this range in black, padded", image_url="https://h/black.jpg"),
            dict(sku="4", brand="Havells", action="none", code="", result="", reason="x", image_url="")]
    text = "\n".join(bi.planned_tables(rows))
    assert "| KEI | 0 | 0 | 1 | 1 | 0 | 2 |" in text
    assert "| Havells | 0 | 0 | 1 | 0 | 0 | 1 |" in text
    assert "| range havells/life-guard | 1 | 1 | 1 |" in text
