"""The owner's own product photos onto the shop (owner, 11 Nov 2026: "place the pictures in that
column ... then run script and update in website").

The owner fills `products-without-photo.xlsx` (one row per product, a PHOTO column next to the SKU)
by pasting or inserting a photo of the real product into the PHOTO cell of its row. Also accepted:
a folder of photos named by SKU (RT-HAVE-905.jpg).

Sub-commands:
  extract  Read the workbook (and/or folder), find each row's photo, check it, make a square
           1200 px JPEG named <SKU>.jpg, and write manifest.csv (one line per photo found, with the
           reason when a photo is not used). Runs on the owner's PC; nothing is sent anywhere.
  apply    Put the photos on the shop: WooCommerce downloads each JPEG from --base-url (a release
           of this public repo, see owner-photos.yml). Products that already have a photo are
           skipped unless --overwrite. Records meta _rte_image_source=owner-photo,
           _rte_image_url, _rte_image_brand=owner (so `brand_images.py remove --brand-name owner`
           takes them all off again). Only images and that meta are written: never prices, stock,
           names or status.

Workbook pictures that are understood:
  - Excel 365 "Place in Cell" (rich value images, xl/richData),
  - pictures placed over the cell (drawing anchors; the cell under the picture's middle counts),
  - WPS Office cell images (=DISPIMG("ID_...",1), xl/cellimages.xml).
"""
from __future__ import annotations

import argparse
import collections
import csv
import io
import os
import posixpath
import re
import sys
import time
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "rv": "http://schemas.microsoft.com/office/spreadsheetml/2017/richdata",
    "rvr": "http://schemas.microsoft.com/office/spreadsheetml/2022/richvaluerel",
    "xlrd": "http://schemas.microsoft.com/office/spreadsheetml/2017/richdata",
}
R_ID = "{%s}id" % NS["r"]
R_EMBED = "{%s}embed" % NS["r"]

MIN_SIDE = 400          # shorter side in pixels; phone photos are 1000+ px
OUT_SIDE = 1200         # square JPEG put on the shop
MANIFEST_FIELDS = ["sku", "file", "source", "w", "h", "status", "reason", "result"]
FORBIDDEN = {"regular_price", "sale_price", "price", "stock_status", "stock_quantity", "manage_stock", "type",
             "external_url", "button_text", "status", "sku", "name"}
SKU_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$")


# ---------------------------------------------------------------- workbook reading
def _col_index(ref: str) -> int:
    """'C12' -> 2 (0-based column)."""
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def _row_index(ref: str) -> int:
    """'C12' -> 11 (0-based row)."""
    return int(re.search(r"\d+", ref).group(0)) - 1


def _rels(z: zipfile.ZipFile, part: str) -> dict:
    """Relationship id -> absolute part name for one part."""
    d, f = posixpath.split(part)
    rp = posixpath.join(d, "_rels", f + ".rels")
    if rp not in z.namelist():
        return {}
    out = {}
    for r in ET.fromstring(z.read(rp)).findall("rel:Relationship", NS):
        t = r.get("Target")
        out[r.get("Id")] = t.lstrip("/") if t.startswith("/") else posixpath.normpath(posixpath.join(d, t))
    return out


def _shared_strings(z) -> list:
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    out = []
    for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
        out.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
    return out


def _sheets(z) -> list:
    """[(sheet name, part name)] in workbook order."""
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = _rels(z, "xl/workbook.xml")
    return [(s.get("name"), rels[s.get(R_ID)]) for s in wb.find("m:sheets", NS)]


def _rich_value_images(z) -> dict:
    """Excel 'Place in Cell' pictures: value-metadata index (the cell's vm, 1-based) -> media part."""
    names = z.namelist()
    if "xl/metadata.xml" not in names or "xl/richData/rdrichvalue.xml" not in names:
        return {}
    # rich value index -> image (through the structure's _rvRel:LocalImageIdentifier key)
    keys = {}
    if "xl/richData/rdrichvaluestructure.xml" in names:
        for i, s in enumerate(ET.fromstring(z.read("xl/richData/rdrichvaluestructure.xml"))):
            keys[i] = [k.get("n") for k in s]
    rel_targets = []
    for relpart in ("xl/richData/richValueRel.xml",):
        if relpart in names:
            rels = _rels(z, relpart)
            rel_targets = [rels.get(r.get(R_ID)) for r in ET.fromstring(z.read(relpart))]
    rv_image = {}
    for i, rv in enumerate(ET.fromstring(z.read("xl/richData/rdrichvalue.xml"))):
        vals = [v.text for v in rv]
        k = keys.get(int(rv.get("s", "0")), [])
        pos = k.index("_rvRel:LocalImageIdentifier") if "_rvRel:LocalImageIdentifier" in k else 0
        try:
            rv_image[i] = rel_targets[int(vals[pos])]
        except (ValueError, IndexError, TypeError):
            continue
    # cell vm (1-based) -> valueMetadata block -> futureMetadata "XLRICHVALUE" block -> rich value index
    md = ET.fromstring(z.read("xl/metadata.xml"))
    types = [t.get("name") for t in md.find("m:metadataTypes", NS)] if md.find("m:metadataTypes", NS) is not None else []
    future = []
    for fm in md.findall("m:futureMetadata", NS):
        if fm.get("name") == "XLRICHVALUE":
            for bk in fm.findall("m:bk", NS):
                rvb = bk.find(".//xlrd:rvb", NS)
                future.append(int(rvb.get("i")) if rvb is not None else None)
    out = {}
    vmeta = md.find("m:valueMetadata", NS)
    if vmeta is None:
        return out
    for n, bk in enumerate(vmeta.findall("m:bk", NS), start=1):
        rc = bk.find("m:rc", NS)
        if rc is None:
            continue
        t = int(rc.get("t")) - 1
        if 0 <= t < len(types) and types[t] == "XLRICHVALUE":
            fi = int(rc.get("v"))
            if fi < len(future) and future[fi] is not None and future[fi] in rv_image:
                out[n] = rv_image[future[fi]]
    return out


def _wps_cell_images(z) -> dict:
    """WPS Office cell pictures: picture id ('ID_...') -> media part."""
    part = "xl/cellimages.xml"
    if part not in z.namelist():
        return {}
    rels = _rels(z, part)
    out = {}
    for pic in ET.fromstring(z.read(part)).iter("{%s}pic" % NS["xdr"]):
        c = pic.find(".//xdr:cNvPr", NS)
        b = pic.find(".//a:blip", NS)
        if c is not None and b is not None and b.get(R_EMBED) in rels:
            out[c.get("name")] = rels[b.get(R_EMBED)]
    return out


def _drawing_images(z, sheet_part) -> list:
    """Pictures placed over cells: [(row, col, media part)] by the cell under the picture's middle."""
    out = []
    for rid, target in _rels(z, sheet_part).items():
        if "/drawings/" not in target or target not in z.namelist():
            continue
        drels = _rels(z, target)
        root = ET.fromstring(z.read(target))
        for anchor in list(root):
            tag = anchor.tag.split("}")[1]
            b = anchor.find(".//a:blip", NS)
            if b is None or b.get(R_EMBED) not in drels:
                continue
            fr = anchor.find("xdr:from", NS)
            if fr is None:
                continue
            r0, c0 = int(fr.find("xdr:row", NS).text), int(fr.find("xdr:col", NS).text)
            if tag == "twoCellAnchor" and anchor.find("xdr:to", NS) is not None:
                to = anchor.find("xdr:to", NS)
                r1, c1 = int(to.find("xdr:row", NS).text), int(to.find("xdr:col", NS).text)
                row, col = (r0 + r1) // 2, (c0 + c1) // 2
            else:
                row, col = r0, c0
            out.append((row, col, drels[b.get(R_EMBED)]))
    return out


def read_workbook(path) -> tuple:
    """All photos in the workbook: ([{sheet, row, sku, data}], [problems])."""
    found, problems = [], []
    with zipfile.ZipFile(path) as z:
        ss = _shared_strings(z)
        rich = _rich_value_images(z)
        wps = _wps_cell_images(z)
        for name, part in _sheets(z):
            root = ET.fromstring(z.read(part))
            cells = {}
            pics_in_cells = []
            for c in root.iter("{%s}c" % NS["m"]):
                ref = c.get("r")
                v, f = c.find("m:v", NS), c.find("m:f", NS)
                text = ""
                if c.get("t") == "s" and v is not None:
                    text = ss[int(v.text)]
                elif c.get("t") == "inlineStr":
                    text = "".join(t.text or "" for t in c.iter("{%s}t" % NS["m"]))
                elif v is not None:
                    text = v.text or ""
                cells[(_row_index(ref), _col_index(ref))] = text.strip()
                if c.get("vm") and int(c.get("vm")) in rich:
                    pics_in_cells.append((_row_index(ref), _col_index(ref), rich[int(c.get("vm"))]))
                elif f is not None and f.text and "DISPIMG" in f.text:
                    m = re.search(r'DISPIMG\(\s*"([^"]+)"', f.text)
                    if m and m.group(1) in wps:
                        pics_in_cells.append((_row_index(ref), _col_index(ref), wps[m.group(1)]))
            header_row = next((r for r in sorted({r for r, _ in cells}) if any(
                cells.get((r, c), "").upper() == "SKU" for c in range(60))), None)
            if header_row is None:
                continue
            heads = {c: cells.get((header_row, c), "") for c in range(60)}
            sku_col = next(c for c, h in heads.items() if h.upper() == "SKU")
            photo_col = next((c for c, h in heads.items() if h.upper().startswith("PHOTO")), None)
            pics = pics_in_cells + _drawing_images(z, part)
            for row, col, media in pics:
                if row <= header_row:
                    continue
                if photo_col is not None and col != photo_col:
                    problems.append(f"{name}!row {row + 1}: picture outside the PHOTO column, not used")
                    continue
                sku = cells.get((row, sku_col), "")
                if not sku:
                    problems.append(f"{name}!row {row + 1}: picture on a row without a SKU, not used")
                    continue
                found.append({"sheet": name, "row": row + 1, "sku": sku, "data": z.read(media)})
    return found, problems


def read_folder(path) -> list:
    """Photos named by SKU: RT-HAVE-905.jpg (also .jpeg .png .webp .heic if Pillow can read it)."""
    out = []
    for p in sorted(Path(path).iterdir()):
        if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"):
            out.append({"sheet": "folder", "row": p.name, "sku": p.stem.strip(), "data": p.read_bytes()})
    return out


# ---------------------------------------------------------------- photo check and conversion
def prepare(data: bytes) -> tuple:
    """(jpeg bytes or None, w, h, reason). Turns the photo upright (EXIF), puts it on a white square,
    1200 px. Rejects unreadable and small pictures."""
    from PIL import Image, ImageOps
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:
        return None, 0, 0, "not a picture Pillow can read"
    im = ImageOps.exif_transpose(im)
    w, h = im.size
    if min(w, h) < MIN_SIDE:
        return None, w, h, f"too small ({w}x{h}); needs at least {MIN_SIDE} px on the short side"
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, im)
    im = im.convert("RGB")
    side = max(w, h)
    sq = Image.new("RGB", (side, side), (255, 255, 255))
    sq.paste(im, ((side - w) // 2, (side - h) // 2))
    sq = sq.resize((OUT_SIDE, OUT_SIDE), Image.LANCZOS) if side != OUT_SIDE else sq
    buf = io.BytesIO()
    sq.save(buf, "JPEG", quality=88, optimize=True, progressive=True)
    return buf.getvalue(), w, h, ""


def safe_name(sku: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", sku) + ".jpg"


def cmd_extract(a) -> int:
    photos, problems = [], []
    if a.xlsx:
        f, p = read_workbook(a.xlsx)
        photos += f
        problems += p
    if a.folder:
        photos += read_folder(a.folder)
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    seen, rows = {}, []
    for ph in photos:
        sku = ph["sku"]
        src = f"{ph['sheet']}!{ph['row']}"
        row = {"sku": sku, "file": "", "source": src, "w": "", "h": "", "status": "skip", "reason": "", "result": ""}
        if not SKU_RE.match(sku):
            row["reason"] = "SKU looks wrong"
        elif sku.upper() in seen:
            row["reason"] = f"second photo for this SKU (first: {seen[sku.upper()]}); only the first is used"
        else:
            jpg, w, h, why = prepare(ph["data"])
            row.update(w=w, h=h)
            if jpg:
                name = safe_name(sku)
                (out / name).write_bytes(jpg)
                row.update(file=name, status="ok")
                seen[sku.upper()] = src
            else:
                row["reason"] = why
        rows.append(row)
    with open(a.manifest, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, MANIFEST_FIELDS)
        w.writeheader()
        w.writerows(rows)
    ok = sum(1 for r in rows if r["status"] == "ok")
    print(f"photos found: {len(rows)}; usable: {ok}; not used: {len(rows) - ok}")
    for r in rows:
        if r["status"] != "ok":
            print(f"  not used: {r['source']} {r['sku']}: {r['reason']}")
    for p in problems:
        print("  " + p)
    return 0 if ok else 1


# ---------------------------------------------------------------- apply
def apply_payload(pid: int, url: str, name: str) -> dict:
    p = {"id": pid,
         "images": [{"src": url, "alt": name}],
         "meta_data": [{"key": "_rte_image_source", "value": "owner-photo"},
                       {"key": "_rte_image_url", "value": url},
                       {"key": "_rte_image_brand", "value": "owner"}]}
    assert not (FORBIDDEN & set(p))
    return p


def _night_ist(now=None) -> bool:
    """00:30-06:00 IST belongs to the nightly price run: no image writes then."""
    import datetime as dt
    t = (now or dt.datetime.now(dt.timezone.utc)) + dt.timedelta(hours=5, minutes=30)
    return (t.hour, t.minute) >= (0, 30) and t.hour < 6


def cmd_apply(a, woo, sleep=time.sleep, now=None) -> int:
    rows = list(csv.DictReader(open(a.manifest, newline="", encoding="utf-8")))
    todo = [r for r in rows if r["status"] == "ok"]
    if a.limit:
        todo = todo[:a.limit]
    base = a.base_url.rstrip("/")
    done = skipped = failed = 0
    for i, r in enumerate(todo):
        if _night_ist(now):
            print("00:30 IST reached: stopping so the nightly price run has the shop; run again later")
            break
        st, data, _ = woo.get("/products", {"sku": r["sku"], "_fields": "id,name,images", "status": "any"})
        if st != 200 or not isinstance(data, list):
            r["result"] = f"failed: lookup HTTP {st}"
            failed += 1
            continue
        if not data:
            r["result"] = "no product with this SKU"
            skipped += 1
            continue
        prod = data[0]
        if prod.get("images") and not a.overwrite:
            r["result"] = "skipped: product already has a photo"
            skipped += 1
            continue
        if a.dry_run:
            r["result"] = f"would put on product {prod['id']}"
            continue
        payload = apply_payload(int(prod["id"]), f"{base}/{r['file']}", prod.get("name", r["sku"]))
        st, resp = woo.post("/products/batch", {"update": [payload]})
        got = next((x for x in (resp or {}).get("update", []) if x.get("id") == prod["id"]), {})
        if st == 200 and got.get("images") and not got.get("error"):
            r["result"] = f"done: product {prod['id']}"
            done += 1
        else:
            r["result"] = f"failed: {(got.get('error') or {}).get('message') or f'HTTP {st}'}"[:200]
            failed += 1
        sleep(2)
    with open(a.manifest, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, MANIFEST_FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"{'dry run: ' if a.dry_run else ''}photos put on: {done}; skipped: {skipped}; failed: {failed}"
          f"; checked {len(todo)} of {len([r for r in rows if r['status'] == 'ok'])}")
    return 0


def _woo():
    from enrich_products import Woo
    return Woo(os.environ["WC_URL"], os.environ["WC_KEY"], os.environ["WC_SECRET"])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("extract")
    s.add_argument("--xlsx", default="")
    s.add_argument("--folder", default="")
    s.add_argument("--out-dir", required=True)
    s.add_argument("--manifest", required=True)
    s = sub.add_parser("apply")
    s.add_argument("--manifest", required=True)
    s.add_argument("--base-url", required=True)
    s.add_argument("--limit", type=int, default=0)
    s.add_argument("--overwrite", action="store_true", help="also replace photos already on the product")
    s.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "extract":
        if not (a.xlsx or a.folder):
            ap.error("give --xlsx and/or --folder")
        return cmd_extract(a)
    return cmd_apply(a, _woo())


if __name__ == "__main__":
    sys.exit(main())
