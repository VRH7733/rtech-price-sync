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
    assert "too small" in bi.assess(_png(400, 400))["reason"]
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
    assert rows["C"]["reason"] == "no model number in our title"
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
    with pytest.raises(bi.Refused):
        bi._check(_FR("robots_blocked", detail="robots.txt unavailable (429/5xx/network)"), "page")
    bi._check(_FR("robots_blocked", detail="disallowed by robots.txt: /x"), "page")  # just skipped
    bi._check(_FR("ok", 200, text="captcha", content=b"\xff\xd8\xff\xe0rest"), "image")  # image bytes
