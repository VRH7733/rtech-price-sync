"""tools/owner_photos.py: the owner's photos from the workbook (or a folder) onto the shop."""
import argparse
import csv
import datetime as dt
import importlib.util
import io
import os
import zipfile

import pytest

pytest.importorskip("PIL")
_spec = importlib.util.spec_from_file_location(
    "owner_photos", os.path.join(os.path.dirname(__file__), "..", "tools", "owner_photos.py"))
op = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(op)

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
IMG = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"


def _png(w, h, color=(200, 30, 30)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


def _cell(ref, text):
    return f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'


def _book(tmp_path, rows_xml, extra_parts=None, sheet_rels=""):
    """A minimal xlsx: one sheet 'Havells' with header PHOTO | Product name | SKU."""
    parts = {
        "xl/workbook.xml": f'<workbook xmlns="{MAIN}" xmlns:r="{REL}"><sheets>'
                           f'<sheet name="Havells" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": f'<Relationships xmlns="{PKG}"><Relationship Id="rId1" '
                                      f'Type="{REL}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": f'<worksheet xmlns="{MAIN}"><sheetData>'
                                    f'<row r="1">{_cell("A1", "PHOTO (paste picture here)")}{_cell("B1", "Product name")}'
                                    f'{_cell("C1", "SKU")}</row>{rows_xml}</sheetData></worksheet>',
    }
    if sheet_rels:
        parts["xl/worksheets/_rels/sheet1.xml.rels"] = sheet_rels
    parts.update(extra_parts or {})
    p = tmp_path / "book.xlsx"
    with zipfile.ZipFile(p, "w") as z:
        for k, v in parts.items():
            z.writestr(k, v)
    return p


def _rich_parts(images):
    """Excel 'Place in Cell' parts for len(images) pictures (vm 1..n -> image1..n)."""
    n = len(images)
    parts = {
        "xl/metadata.xml":
            f'<metadata xmlns="{MAIN}" xmlns:xlrd="http://schemas.microsoft.com/office/spreadsheetml/2017/richdata">'
            '<metadataTypes count="1"><metadataType name="XLRICHVALUE"/></metadataTypes>'
            f'<futureMetadata name="XLRICHVALUE" count="{n}">'
            + "".join(f'<bk><extLst><ext uri="x"><xlrd:rvb i="{i}"/></ext></extLst></bk>' for i in range(n))
            + f'</futureMetadata><valueMetadata count="{n}">'
            + "".join(f'<bk><rc t="1" v="{i}"/></bk>' for i in range(n)) + "</valueMetadata></metadata>",
        "xl/richData/rdrichvaluestructure.xml":
            '<rvStructures xmlns="http://schemas.microsoft.com/office/spreadsheetml/2017/richdata" count="1">'
            '<s t="_localImage"><k n="_rvRel:LocalImageIdentifier" t="i"/><k n="CalcOrigin" t="i"/></s></rvStructures>',
        "xl/richData/rdrichvalue.xml":
            '<rvData xmlns="http://schemas.microsoft.com/office/spreadsheetml/2017/richdata">'
            + "".join(f'<rv s="0"><v>{i}</v><v>5</v></rv>' for i in range(n)) + "</rvData>",
        "xl/richData/richValueRel.xml":
            f'<richValueRels xmlns="http://schemas.microsoft.com/office/spreadsheetml/2022/richvaluerel" xmlns:r="{REL}">'
            + "".join(f'<rel r:id="rId{i + 1}"/>' for i in range(n)) + "</richValueRels>",
        "xl/richData/_rels/richValueRel.xml.rels":
            f'<Relationships xmlns="{PKG}">' + "".join(
                f'<Relationship Id="rId{i + 1}" Type="{IMG}" Target="../media/image{i + 1}.png"/>' for i in range(n))
            + "</Relationships>",
    }
    for i, data in enumerate(images):
        parts[f"xl/media/image{i + 1}.png"] = data
    return parts


def test_place_in_cell_pictures_are_matched_to_their_rows_sku(tmp_path):
    rows = ('<row r="2"><c r="A2" t="e" vm="1"><v>#VALUE!</v></c>' + _cell("B2", "Havells MCB") + _cell("C2", "RT-HAVE-0001") + "</row>"
            '<row r="3">' + _cell("B3", "No photo yet") + _cell("C3", "RT-HAVE-0002") + "</row>"
            '<row r="4"><c r="A4" t="e" vm="2"><v>#VALUE!</v></c>' + _cell("B4", "Havells fan") + _cell("C4", "RT-HAVE-0003") + "</row>")
    book = _book(tmp_path, rows, _rich_parts([_png(800, 600), _png(900, 900, (0, 0, 200))]))
    found, problems = op.read_workbook(book)
    assert [(f["sku"], f["row"]) for f in found] == [("RT-HAVE-0001", 2), ("RT-HAVE-0003", 4)]
    assert found[1]["data"] == _png(900, 900, (0, 0, 200)) and not problems


def test_picture_placed_over_the_photo_cell_counts_for_that_row(tmp_path):
    xdr = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
    a = "http://schemas.openxmlformats.org/drawingml/2006/main"

    def anchor(r0, c0, r1, c1, rid):
        return (f'<xdr:twoCellAnchor><xdr:from><xdr:col>{c0}</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{r0}</xdr:row>'
                f'<xdr:rowOff>0</xdr:rowOff></xdr:from><xdr:to><xdr:col>{c1}</xdr:col><xdr:colOff>0</xdr:colOff>'
                f'<xdr:row>{r1}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to><xdr:pic><xdr:blipFill>'
                f'<a:blip r:embed="{rid}"/></xdr:blipFill></xdr:pic><xdr:clientData/></xdr:twoCellAnchor>')
    drawing = (f'<xdr:wsDr xmlns:xdr="{xdr}" xmlns:a="{a}" xmlns:r="{REL}">'
               + anchor(1, 0, 1, 0, "rId1")      # inside A2
               + anchor(2, 0, 4, 0, "rId2")      # A3..A5: middle is A4
               + anchor(1, 2, 1, 2, "rId1")      # in the SKU column: not used
               + "</xdr:wsDr>")
    parts = {"xl/drawings/drawing1.xml": drawing,
             "xl/drawings/_rels/drawing1.xml.rels":
                 f'<Relationships xmlns="{PKG}"><Relationship Id="rId1" Type="{IMG}" Target="../media/a.png"/>'
                 f'<Relationship Id="rId2" Type="{IMG}" Target="../media/b.png"/></Relationships>',
             "xl/media/a.png": _png(700, 700), "xl/media/b.png": _png(1000, 800)}
    rels = (f'<Relationships xmlns="{PKG}"><Relationship Id="rId1" Type="{REL}/drawing" '
            f'Target="../drawings/drawing1.xml"/></Relationships>')
    rows = "".join(f'<row r="{r}">' + _cell(f"C{r}", f"RT-HAVE-00{r}") + "</row>" for r in (2, 3, 4, 5))
    found, problems = op.read_workbook(_book(tmp_path, rows, parts, rels))
    assert sorted(f["sku"] for f in found) == ["RT-HAVE-002", "RT-HAVE-004"]
    assert any("outside the PHOTO column" in p for p in problems)


def test_wps_cell_pictures_are_read(tmp_path):
    xdr = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
    a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    cellimages = (f'<etc:cellImages xmlns:etc="http://www.wps.cn/officeDocument/2017/etCustomData" '
                  f'xmlns:xdr="{xdr}" xmlns:a="{a}" xmlns:r="{REL}"><etc:cellImage><xdr:pic><xdr:nvPicPr>'
                  f'<xdr:cNvPr id="2" name="ID_ABC123"/></xdr:nvPicPr><xdr:blipFill><a:blip r:embed="rId1"/>'
                  f'</xdr:blipFill></xdr:pic></etc:cellImage></etc:cellImages>')
    parts = {"xl/cellimages.xml": cellimages,
             "xl/_rels/cellimages.xml.rels": f'<Relationships xmlns="{PKG}"><Relationship Id="rId1" Type="{IMG}" '
                                             f'Target="media/image1.png"/></Relationships>',
             "xl/media/image1.png": _png(600, 600)}
    rows = ('<row r="2"><c r="A2" t="str"><f>_xlfn.DISPIMG("ID_ABC123",1)</f><v>=DISPIMG("ID_ABC123",1)</v></c>'
            + _cell("C2", "RT-KEI-0007") + "</row>")
    found, _ = op.read_workbook(_book(tmp_path, rows, parts))
    assert [f["sku"] for f in found] == ["RT-KEI-0007"]


def test_prepare_makes_an_upright_white_square_and_rejects_small_or_broken():
    jpg, w, h, why = op.prepare(_png(1600, 900))
    from PIL import Image
    im = Image.open(io.BytesIO(jpg))
    assert not why and (w, h) == (1600, 900) and im.size == (1200, 1200) and im.format == "JPEG"
    assert im.getpixel((5, 5))[0] > 240  # padding is white
    assert "too small" in op.prepare(_png(300, 500))[3]
    assert "too small" in op.prepare(_png(1200, 590))[3]  # the shop shows 600x600: under 600 is blurry
    assert op.prepare(_png(600, 600))[0] is not None
    assert op.prepare(b"not an image")[0] is None


def test_extract_writes_jpegs_named_by_sku_and_keeps_only_the_first_photo_per_sku(tmp_path):
    folder = tmp_path / "phone"
    folder.mkdir()
    (folder / "RT-HAVE-0001.jpg").write_bytes(_png(800, 800))
    (folder / "RT-HAVE-0009.png").write_bytes(_png(200, 200))   # too small
    rows = ('<row r="2"><c r="A2" t="e" vm="1"><v>#VALUE!</v></c>' + _cell("C2", "RT-HAVE-0001") + "</row>")
    book = _book(tmp_path, rows, _rich_parts([_png(800, 600)]))
    out, man = tmp_path / "out", tmp_path / "manifest.csv"
    rc = op.cmd_extract(argparse.Namespace(xlsx=str(book), folder=str(folder), out_dir=str(out), manifest=str(man)))
    rows = list(csv.DictReader(open(man)))
    assert rc == 0 and os.listdir(out) == ["RT-HAVE-0001.jpg"]
    assert [(r["sku"], r["status"]) for r in rows] == [("RT-HAVE-0001", "ok"), ("RT-HAVE-0001", "skip"),
                                                       ("RT-HAVE-0009", "skip")]
    assert "second photo" in rows[1]["reason"] and "too small" in rows[2]["reason"]
    assert "low resolution" in rows[0]["reason"]  # 800x600: used, but flagged for a retake


def test_a_sharp_photo_is_not_flagged(tmp_path):
    folder = tmp_path / "phone"
    folder.mkdir()
    (folder / "RT-KEI-0001.jpg").write_bytes(_png(1500, 1200))
    man = tmp_path / "m.csv"
    op.cmd_extract(argparse.Namespace(xlsx="", folder=str(folder), out_dir=str(tmp_path / "o"), manifest=str(man)))
    r = next(csv.DictReader(open(man)))
    assert r["status"] == "ok" and r["reason"] == ""


class FakeWoo:
    def __init__(self, products):
        self.products, self.posts = products, []

    def get(self, path, params=None):
        return 200, [p for p in self.products if p["sku"] == params["sku"]], {}

    def post(self, path, payload):
        self.posts.append(payload)
        return 200, {"update": [{"id": u["id"], "images": [{"id": 9}]} for u in payload["update"]]}


def _manifest(tmp_path, skus):
    p = tmp_path / "m.csv"
    with open(p, "w", newline="") as fh:
        w = csv.DictWriter(fh, op.MANIFEST_FIELDS)
        w.writeheader()
        for s in skus:
            w.writerow({"sku": s, "file": op.safe_name(s), "source": "x", "status": "ok"})
    return p


DAY = dt.datetime(2026, 11, 11, 6, 0, tzinfo=dt.timezone.utc)  # 11:30 IST


def _args(man, **kw):
    return argparse.Namespace(manifest=str(man), base_url="https://github.com/o/r/releases/download/owner-photos-1/",
                              limit=kw.get("limit", 0), overwrite=kw.get("overwrite", False), dry_run=kw.get("dry_run", False))


def test_apply_puts_photos_on_products_without_one_and_writes_only_images_and_meta(tmp_path):
    woo = FakeWoo([{"id": 1, "sku": "RT-A", "name": "A", "images": []},
                   {"id": 2, "sku": "RT-B", "name": "B", "images": [{"id": 5}]}])
    man = _manifest(tmp_path, ["RT-A", "RT-B", "RT-C"])
    op.cmd_apply(_args(man), woo, sleep=lambda s: None, now=DAY)
    assert len(woo.posts) == 1
    u = woo.posts[0]["update"][0]
    assert u["id"] == 1 and u["images"][0]["src"].endswith("/owner-photos-1/RT-A.jpg")
    assert set(u) == {"id", "images", "meta_data"}
    assert {m["key"]: m["value"] for m in u["meta_data"]}["_rte_image_brand"] == "owner"
    res = [r["result"] for r in csv.DictReader(open(man))]
    assert res[0].startswith("done") and "already has a photo" in res[1] and res[2] == "no product with this SKU"


def test_apply_overwrite_dry_run_and_night_stop(tmp_path):
    woo = FakeWoo([{"id": 2, "sku": "RT-B", "name": "B", "images": [{"id": 5}]}])
    man = _manifest(tmp_path, ["RT-B"])
    op.cmd_apply(_args(man, dry_run=True, overwrite=True), woo, sleep=lambda s: None, now=DAY)
    assert not woo.posts and "would put on product 2" in next(csv.DictReader(open(man)))["result"]
    op.cmd_apply(_args(man, overwrite=True), woo, sleep=lambda s: None, now=DAY)
    assert len(woo.posts) == 1
    night = dt.datetime(2026, 11, 10, 20, 0, tzinfo=dt.timezone.utc)  # 01:30 IST
    woo2 = FakeWoo([{"id": 3, "sku": "RT-N", "name": "N", "images": []}])
    op.cmd_apply(_args(_manifest(tmp_path, ["RT-N"])), woo2, sleep=lambda s: None, now=night)
    assert not woo2.posts
