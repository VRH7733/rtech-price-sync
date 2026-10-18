import importlib.util
import io
import json
import os

_spec = importlib.util.spec_from_file_location(
    "brand_images", os.path.join(os.path.dirname(__file__), "..", "tools", "brand_images.py"))
bi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bi)


def _png(w, h, bg=(255, 255, 255), box=None, color=(30, 60, 200)):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(im)
    d.rectangle(box or (w // 4, h // 4, 3 * w // 4, 3 * h // 4), fill=color)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def test_quality_accepts_clear_product_on_plain_background():
    q = bi.assess(_png(1000, 1000))
    assert q["ok"] and q["white"] and (q["w"], q["h"]) == (1000, 1000)


def test_quality_rejects_small_banner_cropped_and_busy():
    assert "too small" in bi.assess(_png(300, 300))["reason"]
    assert bi.assess(_png(400, 400))["ok"]  # 400 px is accepted since 18 Oct 2026
    assert "banner" in bi.assess(_png(1920, 600))["reason"]
    cut = bi.assess(_png(1000, 1000, box=(0, 0, 999, 600)))  # product runs off the edges
    assert not cut["ok"]
    assert not bi.assess(b"<html>not an image</html>")["ok"]
    tiny = bi.assess(_png(1000, 1000, box=(490, 490, 520, 520)))
    assert not tiny["ok"] and "too small in the picture" in tiny["reason"]


def test_codes_include_trailing_catalogue_number():
    assert "3002" in bi.codes_for("GM 3 Pin Plug Top 16 A White, Orange, 3002")
    assert "AHLHGXW060" in bi.codes_for("Havells AHLHGXW060 Batten Holder (White)")
    assert not bi.codes_for("Havells Life Line 1.5 Sq.mm 1 Core Cable Red (90 m)")


def test_codes_match_whole_tokens_only():
    codes = {"AHLHGXW060", "679250"}
    assert bi.page_codes("/products/ahlhgxw-060-batten | Havells Batten", codes) == {"AHLHGXW060"}
    assert bi.page_codes("Myrius 6792 50 Buzzer", codes) == {"679250"}
    assert not bi.page_codes("AHLHGXW0601 holder", codes)  # a longer, different model


PAGE = """<html><head><title>Havells AHLHGXW060 Batten | Havells India</title>
<meta property="og:image" content="/media/ahlhgxw060.jpg">
<script type="application/ld+json">{"@type":"Product","name":"Batten","sku":"AHLHGXW060",
"image":["https://www.havells.com/media/ahlhgxw060-large.jpg","https://www.havells.com/logo.png"]}</script>
</head><body><h1>Havells Batten</h1></body></html>"""


def test_extract_page_finds_structured_data_and_official_images():
    ex = bi.extract_page(PAGE, "https://www.havells.com/p/batten.html")
    assert "AHLHGXW060" in ex["strong"]
    assert ex["images"] == ["https://www.havells.com/media/ahlhgxw060-large.jpg",
                            "https://www.havells.com/media/ahlhgxw060.jpg"]  # logo dropped


def _t(sku, name, image="", web="", ours="1", has_our=""):
    return {"sku": sku, "id": "1", "brand": "Havells", "name": name, "web": web, "ours": ours,
            "image_src": image, "image_id": "", "has_our_image": has_our}


def _page(url, strong, ok=True, w=1000, h=1000, img=None):
    return {"url": url, "strong": strong, "images": json.dumps(
        [{"url": img or url + ".jpg", "ok": ok, "w": w, "h": h, "reason": "" if ok else "too small"}])}


def test_plan_certain_matches_only_and_keeps_existing_images():
    targets = [_t("A", "Havells AHLHGXW060 Batten Holder"),
               _t("B", "Havells ABCDE12345 Switch", image="https://shop/x.jpg"),
               _t("C", "Havells Life Line 1.5 Sq.mm Cable"),
               _t("D", "Havells QWERTY1234 Fan"),
               _t("E", "Havells ZXCVB9876 Light"), _t("F", "Havells POIUY5432 Light")]
    pages = [_page("https://h/ahlhgxw060", "AHLHGXW060"), _page("https://h/abcde12345", "ABCDE12345"),
             _page("https://h/qwerty1234", "QWERTY1234", ok=False),
             _page("https://h/range", "ZXCVB9876 POIUY5432")]
    rows = {r["sku"]: r for r in bi.plan(targets, {"havells": pages})}
    assert rows["A"]["action"] == "add" and rows["A"]["page_url"] == "https://h/ahlhgxw060"
    assert rows["B"]["action"] == "none" and "already has an image" in rows["B"]["reason"]
    assert rows["C"]["reason"].startswith("no model number in our title")
    assert rows["D"]["action"] == "none" and "quality" in rows["D"]["reason"]
    assert rows["E"]["action"] == "none" and "range page" in rows["E"]["reason"]


def test_plan_skips_images_shared_by_many_pages():
    targets = [_t(f"S{i}", f"Havells ABCDE1234{i} Switch") for i in range(5)]
    pages = [_page(f"https://h/{i}", f"ABCDE1234{i}", img="https://h/site-default.jpg") for i in range(5)]
    rows = bi.plan(targets, {"havells": pages})
    assert all(r["action"] == "none" and "shared" in r["reason"] for r in rows)


def test_web_products_replaced_only_when_brand_image_is_clearer():
    targets = [_t("WEB-1", "Havells AHLHGXW060 Batten", image="https://shop/a.jpg", web="1", ours=""),
               _t("WEB-2", "Havells ABCDE12345 Switch", image="https://shop/b.jpg", web="1", ours=""),
               _t("WEB-3", "Havells QWERT12345 Fan", image="https://shop/c.jpg", web="1", ours="")]
    pages = [_page("https://h/1", "AHLHGXW060"), _page("https://h/2", "ABCDE12345"), _page("https://h/3", "QWERT12345")]
    cur = {"WEB-1": {"ok": False, "w": 300, "h": 300, "reason": "too small (300x300)"},
           "WEB-2": {"ok": True, "w": 900, "h": 900, "reason": ""},
           "WEB-3": {"ok": True, "w": 600, "h": 600, "reason": ""}}
    rows = {r["sku"]: r for r in bi.plan(targets, {"havells": pages}, cur)}
    assert rows["WEB-1"]["action"] == "replace"
    assert rows["WEB-2"]["action"] == "none"
    assert rows["WEB-3"]["action"] == "replace"  # 1000x1000 is >= 1.5x the pixels of 600x600


def test_apply_payload_records_source_and_never_price_or_stock():
    p = bi.apply_payload({"id": "7", "image_url": "https://h/i.jpg", "name": "X", "page_url": "https://h/p",
                          "brand": "Havells"})
    assert p["images"] == [{"src": "https://h/i.jpg", "alt": "X"}]
    meta = {m["key"]: m["value"] for m in p["meta_data"]}
    assert meta == {"_rte_image_source": "https://h/p", "_rte_image_url": "https://h/i.jpg",
                    "_rte_image_brand": "Havells"}
    assert not (bi.FORBIDDEN & set(p))


def test_removal_only_takes_off_this_tools_images_for_that_brand():
    mine = {"id": 1, "meta_data": [{"key": "_rte_image_url", "value": "u"}, {"key": "_rte_image_brand", "value": "Havells"}]}
    assert bi.removal_payload(mine, "havells")["images"] == []
    assert bi.removal_payload(mine, "Legrand") is None
    assert bi.removal_payload({"id": 2, "meta_data": []}, "Havells") is None


class _FR:
    def __init__(self, status, http=None, text="", content=b"", detail=""):
        self.status, self.http, self.text, self.content, self.detail = status, http, text, content, detail


def test_refusal_stops_the_brand():
    import pytest
    with pytest.raises(bi.Refused):
        bi._check(_FR("blocked", 403), "page")
    with pytest.raises(bi.Refused):
        bi._check(_FR("ok", 200, text="Please complete the captcha"), "page")
    bi._check(_FR("ok", 200, text="<html>" + "x" * 30000 + "recaptcha on the contact form</html>"), "page")
    bi._check(_FR("ok", 200, text="<html><h1>Green wires</h1><form>reCAPTCHA</form></html>"), "page")
    with pytest.raises(bi.Refused):
        bi._check(_FR("robots_blocked", detail="robots.txt unavailable (429/5xx/network)"), "page")
    bi._check(_FR("robots_blocked", detail="disallowed by robots.txt: /x"), "page")  # just skipped
    bi._check(_FR("ok", 200, text="captcha", content=b"\xff\xd8\xff\xe0rest"), "image")  # image bytes


def test_resolve_site_follows_a_redirected_robots_txt_and_stops_on_refusal():
    import pytest
    from types import SimpleNamespace as NS

    class Resp:
        def __init__(self, code, url, history=()):
            self.status_code, self.url, self.history = code, url, list(history)

    def fetcher(resp):
        return NS(session=NS(get=lambda *a, **k: resp), _headers=lambda: {},
                  cfg=NS(timeout_seconds=5, min_delay_seconds=0))

    moved = Resp(200, "https://havells.com/robots.txt", [Resp(301, "https://www.havells.com/robots.txt")])
    assert bi.resolve_site(fetcher(moved), "https://www.havells.com", print) == "https://havells.com"
    with pytest.raises(bi.Refused):
        bi.resolve_site(fetcher(Resp(403, "https://www.havells.com/robots.txt")), "https://www.havells.com", print)
    away = Resp(200, "https://other.example/robots.txt", [Resp(301, "x")])
    with pytest.raises(bi.Refused):
        bi.resolve_site(fetcher(away), "https://www.havells.com", print)


def test_crawl_end_to_end_with_a_fake_site(tmp_path, monkeypatch):
    import csv as _csv
    from types import SimpleNamespace as NS
    img = _png(1000, 1000)
    sitemap = (b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
               b'<url><loc>https://www.gmmodular.com/p/plug-top-3002</loc></url>'
               b'<url><loc>https://www.gmmodular.com/blog/news</loc></url></urlset>')
    page = ('<html><head><title>GM Plug Top 3002</title><meta property="og:image" content="https://gmmodular.comundefined">'
            '<script type="application/ld+json">{"@type":"Product","sku":"3002","image":"https://cdn.gmmodular.com/3002.png"}'
            '</script></head><body><h1>Plug Top</h1></body></html>')
    calls = []

    class FakeF:
        cfg = NS(timeout_seconds=5, min_delay_seconds=0)
        request_log = {}
        session = NS(get=lambda *a, **k: NS(status_code=200, url="https://www.gmmodular.com/robots.txt", history=[]))

        def _headers(self):
            return {}

        def get(self, url):
            calls.append(url)
            if url.endswith("robots.txt"):
                return _FR("ok", 200, text="Sitemap: https://www.gmmodular.com/sitemap.xml")
            if url.endswith("sitemap.xml"):
                return _FR("ok", 200, content=sitemap, text="")
            if url.endswith(".png"):
                return _FR("ok", 200, content=img, text="")
            return NS(**vars(_FR("ok", 200, text=page)), final_url=url)

    monkeypatch.setattr(bi, "BrandFetcher", lambda cfg: FakeF())
    monkeypatch.setattr(bi.time, "sleep", lambda s: None)
    monkeypatch.setenv("RTECH_CONTACT_EMAIL", "info@example.co.in")
    targets = tmp_path / "t.csv"
    with open(targets, "w", newline="") as fh:
        w = _csv.DictWriter(fh, bi.TARGET_FIELDS)
        w.writeheader()
        w.writerow({"sku": "G1", "id": "5", "brand": "GM", "name": "GM 3 Pin Plug Top 16 A White, Orange, 3002"})
    out, summ = tmp_path / "p.csv", tmp_path / "s.json"
    cfgp = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
    bi.main(["crawl", "--brand", "gm", "--targets", str(targets), "--out", str(out), "--summary", str(summ),
             "--config", cfgp])
    assert "https://www.gmmodular.com/blog/news" not in calls
    rows = list(_csv.DictReader(open(out)))
    imgs = json.loads(rows[0]["images"])
    assert [i["ok"] for i in imgs] == [True, False] and imgs[1]["reason"] == "broken image address"
    plan = bi.plan(bi.load_targets(targets), {"gm": rows})
    assert plan[0]["action"] == "add" and plan[0]["image_url"] == "https://cdn.gmmodular.com/3002.png"


def test_name_match_is_strict():
    t = "Havells Life Line Plus S3 HRFR 1.5 Sq.mm 1 Core Cable Red (90 m)"
    assert bi.name_match("Havells Life Line Plus S3 HRFR Cable", t, "Havells") == 6
    assert bi.name_match("Life Line Plus S3 HRFR Cable | Havells India", t, "Havells") == 6
    assert not bi.name_match("Life Guard FR-LSH Cable", t, "Havells")       # other range
    assert not bi.name_match("Life Line Plus S3 HRFR Cable Blue", t, "Havells")  # other colour
    assert not bi.name_match("Cable", t, "Havells")                         # too vague
    assert not bi.name_match("1.5 sq mm cable", "Havells 15 sq mm cable", "Havells")


def test_plan_name_route_is_separate_and_most_specific_wins():
    targets = [_t("W1", "Havells Life Line Plus S3 HRFR 1.5 Sq.mm 1 Core Cable Red (90 m)"),
               _t("W2", "Havells Life Line Plus S3 HRFR 2.5 Sq.mm 1 Core Cable Blue (90 m)", image="https://shop/x.jpg")]
    pages = [dict(_page("https://h/lifeline", "Life Line"), name="Life Line Cable"),
             dict(_page("https://h/lifeline-plus-red", "Life Line Plus"), name="Life Line Plus S3 HRFR Cable")]
    rows = {r["sku"]: r for r in bi.plan(targets, {"havells": pages})}
    assert rows["W1"]["action"] == "add-name" and rows["W1"]["page_url"] == "https://h/lifeline-plus-red"
    assert rows["W2"]["action"] == "none"  # has an image, and the page shows another colour


def test_legrand_catalogue_photo_by_number(tmp_path, monkeypatch):
    import csv as _csv
    from types import SimpleNamespace as NS
    img = _png(1752, 2400 * 1752 // 1752 if False else 1752)
    calls = []

    class FakeF:
        cfg = NS(timeout_seconds=5, min_delay_seconds=0)
        request_log = {}

        def get(self, url):
            calls.append(url)
            if "679250" in url:
                return _FR("ok", 200, content=img, text="")
            return _FR("error", 404, detail="HTTP 404")

    monkeypatch.setattr(bi, "BrandFetcher", lambda cfg: FakeF())
    monkeypatch.setenv("RTECH_CONTACT_EMAIL", "info@example.co.in")
    targets = tmp_path / "t.csv"
    with open(targets, "w", newline="") as fh:
        w = _csv.DictWriter(fh, bi.TARGET_FIELDS)
        w.writeheader()
        w.writerow({"sku": "L1", "id": "5", "brand": "Legrand", "name": "Legrand Buzzer Myrius Classic White 1 Module, 6792 50"})
        w.writerow({"sku": "L2", "id": "6", "brand": "Legrand", "name": "Legrand Bell Myrius White, 6792 99"})
    out, summ = tmp_path / "p.csv", tmp_path / "s.json"
    cfgp = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
    bi.main(["crawl", "--brand", "legrand", "--targets", str(targets), "--out", str(out), "--summary", str(summ),
             "--config", cfgp])
    assert calls == ["https://assets.legrand.com/pim/PHOTOS-WEB/LG-679250-WEB-R.jpg",
                     "https://assets.legrand.com/pim/PHOTOS-WEB/LG-679299-WEB-R.jpg"]
    rows = {r["sku"]: r for r in bi.plan(bi.load_targets(targets), {"legrand": list(_csv.DictReader(open(out)))})}
    assert rows["L1"]["action"] == "add" and rows["L1"]["image_url"].endswith("LG-679250-WEB-R.jpg")
    assert rows["L2"]["action"] == "none"


def test_image_sitemap_gives_the_photo_without_opening_the_page():
    xml = (b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
           b'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1"><url>'
           b'<loc>https://havells.com/fancy-jumbo-batten-holder-metal-ring-ahlhgxw060.html</loc>'
           b'<image:image><image:loc>https://havells.com/media/catalog/product/cache/206c61f8e794cc73ece691a73796356e/'
           b'import/Switches/AHLHGXW060.jpg</image:loc><image:title>Fancy Jumbo Batten Holder</image:title></image:image>'
           b'</url></urlset>')
    got = bi.sitemap_images(xml)
    imgs, title = got["https://havells.com/fancy-jumbo-batten-holder-metal-ring-ahlhgxw060.html"]
    assert title == "Fancy Jumbo Batten Holder"
    assert bi.original_image(imgs[0]) == "https://havells.com/media/catalog/product/import/Switches/AHLHGXW060.jpg"


def test_image_named_by_the_model_number_may_appear_on_several_pages():
    targets = [_t("H1", "Havells Donato Espresso GHBCMAKS080")]
    img = "https://havells.com/media/catalog/product/import/Appliances/GHBCMAKS080.jpg"
    pages = [_page(f"https://havells.com/donato-espresso-ghbcmaks080{s}.html", "GHBCMAKS080", img=img)
             for s in ("", "-c", "-1", "-2", "-3")]
    assert bi.plan(targets, {"havells": pages})[0]["action"] == "add"


def test_no_image_writes_during_the_nightly_price_window():
    import datetime as dt
    utc = dt.timezone.utc
    assert not bi._night_ist(dt.datetime(2026, 10, 16, 18, 0, tzinfo=utc))   # 23:30 IST
    assert bi._night_ist(dt.datetime(2026, 10, 16, 19, 0, tzinfo=utc))       # 00:30 IST
    assert not bi._night_ist(dt.datetime(2026, 10, 17, 1, 0, tzinfo=utc))    # 06:30 IST


def test_wire_key_reads_range_size_colour_and_length():
    k = bi.wire_key("Polycab Maxima+ Green Wire HR FR-LSH LF 180 Meters / 6 Sqmm / Green", "Polycab")
    assert (k["range"], k["size"], k["colour"], k["length"]) == ("maximaplusgreen", 6.0, "green", 180)
    p = bi.wire_key("POLYCABMAXIMA+ Green Wire | 6 Sq. MM | 180 Meters | GREEN", "Polycab")
    assert bi.wire_match(p, k)
    assert bi.wire_key("Polycab Green Wire | HR FR-LSH LF | 6 Sq. MM | 180 Meters | GREEN", "Polycab")["range"] == "green"
    assert not bi.wire_key("Polycab 185 Sq.mm 1 Core FR Industrial Flexible Cable Blue (100 m)", "Polycab")  # no range
    other = bi.wire_key("POLYCABMAXIMA+ Green Wire | 6 Sq. MM | 90 Meters | GREEN", "Polycab")
    assert not bi.wire_match(other, k)                    # other length
    blue = bi.wire_key("POLYCABMAXIMA+ Green Wire | 6 Sq. MM | 180 Meters | BLUE", "Polycab")
    assert not bi.wire_match(blue, k)                     # other colour
    assert bi.range_key("HomeCab–FR", "KEI") == bi.range_key("KEI Homecab 2.5 Sq.mm 1 Core FR Cable", "KEI") == "homecab"
    assert bi.range_key("Flamex HR+FR", "RR Kabel") == bi.range_key("RR Kabel Flamex HRFR 1.5 Sq.mm 1 Core", "RR Kabel") == "flamex"
    assert bi.range_key("SUPEREX GREEN HR + FR", "RR Kabel") != bi.range_key("RR Kabel Superex FR 1.5 Sq.mm", "RR Kabel")


def _wt(sku, name, image=""):
    return dict(_t(sku, name, image=image), brand="Polycab")


def test_plan_wire_route_needs_the_exact_wire_page():
    targets = [_wt("W1", "Polycab Primma house wire 6 sq mm Blue 90 m"),
               _wt("W2", "Polycab Primma house wire 6 sq mm Red 90 m"),
               _wt("W3", "Polycab Primma house wire 4 sq mm Blue 90 m")]
    pages = [dict(_page("https://p/primma-6-blue", "", w=400, h=400), name="POLYCABPRIMMA | LF-FR | 6 Sq. MM | 90 Meters, Copper | Blue"),
             dict(_page("https://p/primma-4-blue", "", ok=False, w=300, h=300), name="POLYCABPRIMMA | LF-FR | 4 Sq. MM | 90 Meters, Copper | Blue")]
    rows = {r["sku"]: r for r in bi.plan(targets, {"polycab": pages})}
    assert rows["W1"]["action"] == "add" and rows["W1"]["page_url"] == "https://p/primma-6-blue"
    assert rows["W2"]["action"] == "none"                         # no red page: no photo of another colour
    assert rows["W3"]["action"] == "none" and "quality" in rows["W3"]["reason"]


def test_plan_range_photo_only_for_products_without_an_image():
    targets = [dict(_t("K1", "KEI Homecab 2.5 Sq.mm 1 Core FR Cable Blue (180 m)"), brand="KEI"),
               dict(_t("K2", "KEI Homecab 4 Sq.mm 1 Core FR Cable Red (180 m)", image="https://shop/k.jpg"), brand="KEI"),
               dict(_t("K3", "KEI Conflame 1.5 Sq.mm 1 Core FR Cable Red (90 m)"), brand="KEI")]
    img = {"url": "https://kei/home-cab.png", "ok": False, "w": 530, "h": 301, "reason": "too small (530x301)",
           "range_ok": True, "range_reason": ""}
    bad = dict(img, url="https://kei/conflame.png", range_ok=False, range_reason="banner shape")
    pages = [{"url": "https://kei/cables-and-wires/house-wire/home-cab-fr/", "strong": "", "name": "HomeCab–FR",
              "images": json.dumps([img])},
             {"url": "https://kei/cables-and-wires/house-wire/con-flame-frls/", "strong": "", "name": "ConFlame-FRLS",
              "images": json.dumps([bad])}]
    rows = {r["sku"]: r for r in bi.plan(targets, {"kei": pages})}
    assert rows["K1"]["action"] == "add-range" and rows["K1"]["image_url"] == "https://kei/home-cab.png"
    assert rows["K2"]["action"] == "none"
    assert rows["K3"]["action"] == "none" and "range photo failed" in rows["K3"]["reason"]


def test_range_photo_is_padded_not_cropped():
    from PIL import Image
    wide = _png(530, 300, box=(20, 40, 510, 260))
    q = bi.assess_range(wide)
    assert q["range_ok"], q
    sq = Image.open(io.BytesIO(bi.pad_square(wide)))
    assert sq.width == sq.height >= 530
    assert not bi.assess_range(_png(300, 200))["range_ok"]            # too small even padded
    assert not bi.assess_range(_png(1600, 300))["range_ok"]           # a banner


def test_original_image_drops_resize_query_only():
    assert bi.original_image("https://cms.polycab.com/media/a/b_img_01.jpg?format=webp") == "https://cms.polycab.com/media/a/b_img_01.jpg"
    assert bi.original_image("https://x/img?id=55") == "https://x/img?id=55"


def test_apply_puts_range_photos_on_only_from_our_padded_copy(tmp_path, monkeypatch):
    import csv as _csv
    from types import SimpleNamespace as NS
    monkeypatch.setattr(bi, "_night_ist", lambda now=None: False)
    plan = tmp_path / "plan.csv"
    rows = [dict(sku="K1", id="11", brand="KEI", name="KEI Homecab 2.5", code="range homecab", page_url="https://kei/p",
                 image_url="https://kei/home-cab.png", w="530", h="301", action="add-range", reason="", result=""),
            dict(sku="K2", id="12", brand="KEI", name="KEI Homecab 4", code="range homecab", page_url="https://kei/p",
                 image_url="https://github.com/o/r/releases/download/brand-range-images/ab.jpg", w="530", h="301",
                 action="add-range", reason="", result="")]
    with open(plan, "w", newline="") as fh:
        w = _csv.DictWriter(fh, bi.PLAN_FIELDS)
        w.writeheader()
        w.writerows(rows)
    sent = []

    class Woo:
        def get(self, path, params):
            return 200, [{"id": int(i), "images": [], "meta_data": []} for i in params["include"].split(",")], {}

        def post(self, path, body):
            sent.extend(body["update"])
            return 200, {"update": [{"id": p["id"], "images": [{"id": 900}]} for p in body["update"]]}

    bi.cmd_apply(NS(plan=str(plan), limit=0, allow_name=False, allow_range=True, batch=5), Woo(), sleep=lambda s: None)
    assert [p["id"] for p in sent] == [12]
    assert not bi.FORBIDDEN & set(sent[0])
    got = {r["sku"]: r["result"] for r in _csv.DictReader(open(plan))}
    assert got == {"K1": "", "K2": "done"}


def test_wire_route_falls_back_to_another_coil_length_of_the_same_wire():
    targets = [_wt("W1", "Polycab Optima+ Wire LF FR 180 Meters / 6 Sqmm / Green")]
    pages = [dict(_page("https://p/optima-6-green-90", "", w=400, h=400),
                  name="POLYCABOPTIMA+ | LF-FR | 6 Sq. MM | 90 Meters, Copper | GREEN"),
             dict(_page("https://p/optima-6-blue-180", "", w=400, h=400),
                  name="POLYCABOPTIMA+ | LF-FR | 6 Sq. MM | 180 Meters, Copper | BLUE")]
    row = bi.plan(targets, {"polycab": pages})[0]
    assert row["action"] == "add" and row["page_url"] == "https://p/optima-6-green-90"


def test_url_hit_needs_a_whole_range_name():
    w = bi.Wanted([_wt("W1", "Polycab Etira house wire 6 sq mm Green 90 m"),
                   _wt("W2", "Polycab Etira house wire 4 sq mm Green 90 m"),
                   _wt("W3", "Polycab Etira house wire 2.5 sq mm Green 90 m"),
                   _wt("W4", "Polycab Multicore 4 sq mm cable")], set())
    assert w.url_hit("https://polycab.com/etira-house-wires-fr-6-sq-mm-90-meters-copper-green/c-5016/p-54545")
    assert w.url_hit("https://polycab.com/etira-house-wires/c-5016")                 # the range page
    assert not w.url_hit("https://polycab.com/polycab-instrumentation-300-mc-st/a-3905/p-54768")
    assert not w.url_hit("https://polycab.com/multicore-flexible/x")                 # a 1-product range


def test_name_route_never_shows_another_colour():
    assert bi.colour_ok("Havells Supernova 36 W Glamtube 3000 K Warm White", "Supernova Glamtube /lhewajpgpv1a036-c.html")
    assert not bi.colour_ok("Havells Fusion ES Pearl Ivory 1400 mm Ceiling Fan", "Fusion ES /fusion-es-1400-mm.html")
    assert bi.colour_ok("Havells Fusion ES Pearl Ivory 1400 mm Ceiling Fan", "Fusion ES /fusion-es-1400mm-pearl-ivory.html")
    targets = [_t("F1", "Havells Fusion ES Pearl Ivory 1400 mm Ceiling Fan"),
               _t("F2", "Havells Fusion ES Silver Blue 1400 mm Ceiling Fan")]
    pages = [dict(_page("https://h/fusion-es-pearl-ivory.html", "x"), name="Fusion ES"),
             dict(_page("https://h/fusion-es-brown.html", "x"), name="Fusion ES")]
    rows = {r["sku"]: r for r in bi.plan(targets, {"havells": pages})}
    assert rows["F1"]["action"] == "add-name" and rows["F1"]["page_url"].endswith("pearl-ivory.html")
    assert rows["F2"]["action"] == "none" and "another colour" in rows["F2"]["reason"]
    assert not bi.colour_ok("Havells Andria ES Quartz 1200 mm Ceiling Fan", "Andria ES /fhcad2sebr48-c.html")
