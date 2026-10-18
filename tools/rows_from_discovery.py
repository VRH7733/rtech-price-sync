#!/usr/bin/env python3
"""Build catalogue rows from discovered marketplace products (tools/discover.py output).

  python tools/rows_from_discovery.py DISCOVERY_DIR ROWS_DIR --brand Havells --brand "RR Kabel"

Each priced product page fetched from IndustryBuying, HomeRun or Moglix becomes one catalogue row named after
the marketplace title, so the shop lists real products. The same product on the other sites is
attached only when exactly ONE candidate passes the same variant/pack check the daily run uses
(normalise.check_variant on a hint built from the title: product line, sizes, ratings, colour).
Unfetched Moglix pages are matched by URL slug only, never made into rows.

- Rows go to ROWS_DIR/<brand>.csv. Existing files are extended, never rewritten: rows and URLs
  already there are kept, and a product whose URL is already used is skipped.
- New rows are publish=pending_review with no shop product yet; tools/create_drafts.py --live
  creates the product and sets publish=yes.
- SKUs continue the brand's RT-<BRAND4>-NNN numbering.
"""
import argparse
import csv
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))
from match_discovery import SOURCES, load_discovery, passes  # noqa: E402
from rtech_sync.catalogue import load_catalogue, write_catalogue  # noqa: E402
from rtech_sync.models import Row  # noqa: E402
from rtech_sync.normalise import check_variant, normalise_text  # noqa: E402
from seed_to_rows import COLUMNS, code_of  # noqa: E402

COLOURS = ["red", "black", "yellow", "blue", "green", "grey", "gray", "white", "ivory", "brown",
           "orange", "silver", "gold", "beige", "pink", "purple", "violet"]
GENERIC = set("""
wire wires cable cables house single core copper flame retardant fr frls frlf lsh hr pvc insulated
unsheathed industrial multistrand flexible electrical and the with for of to in on mm sqmm series
color colour outer diameter material upvc pp polypropylene type size long short pack non isi box
way ways meters metres meter metre length gang sqm lf ls zh ce isi-marked
""".split())
SPEC = re.compile(r"(?<![0-9a-z.])(\d+(?:\.\d+)?\s?x\s?\d+(?:\.\d+)?(?:mm)?"
                  r"|\d+(?:\.\d+)?(?:sqmm|mm|a|ka|ma|w|v)"
                  r"|\d+(?:\.\d+)?\s?(?:ways?|modules?|cores?|poles?|gang))(?![0-9a-z])")
PACK_M = re.compile(r"\((\d+(?:\.\d+)?)\s*m\)|,\s*(\d+(?:\.\d+)?)\s*m\b", re.I)
PACK_N = re.compile(r"pack\s*of\s*(\d+)", re.I)
CATEGORY = [
    ("Wires & Cables", ("wire", "cable")),
    ("Switchgear", ("mcb", "rccb", "rcbo", "isolator", "changeover", "distribution", " db ", "mccb")),
    ("Modular switches & sockets", ("switch", "socket", "regulator", "plate", "module", "dimmer")),
    ("Pipes & Fittings", ("conduit", "pipe", "bend", "elbow", "tee", "coupler", "junction", "fitting",
                          "box", "casing", "socket")),
    ("Lugs & accessories", ("lug", "gland")),
]


_LEN = re.compile(r"(?<![0-9.x])(\d+(?:\.\d+)?)m(?![0-9a-z])(?!\s?modul)")
_COIL = re.compile(r"(\d+(?:\.\d+)?)\s*m(?:eters?|etres?)?\s*coil", re.I)
_LENGTHY = re.compile(r"wire|cable|cord|pipe|conduit|flex|coil|meter|metre", re.I)  # things sold by length


def pack_of(title: str) -> str:
    m = PACK_N.search(title)
    if m and int(m.group(1)) > 1:
        return f"pack of {m.group(1)}"
    m = _COIL.search(title)  # "(200/300 meter) 4 Sqmm(200m Coil)": the coil is what is sold
    if m:
        return f"{m.group(1)} m"
    m = PACK_M.search(title)  # "(90 m)", ", 90 m"
    if not m and _LENGTHY.search(title):
        m = _LEN.search(normalise_text(title))  # "90 Meters"
    if m:
        return f"{m.group(1) or m.group(2)} m"
    return ""  # "Combined Plate 8 M", "Athena 12M Modular": modules, not metres


def category_of(title: str) -> str:
    low = f" {title.lower()} "
    for cat, words in CATEGORY:
        if any(w in low for w in words):
            return cat
    return ""


def hint_of(brand: str, text: str, pack: str) -> str:
    """Line name + every size/rating + colour, each of which must appear on the other site's page."""
    norm = normalise_text(re.sub(r"(\d)-(core|way|pole|gang|module)", r"\1 \2", text, flags=re.I))
    after = norm.split(normalise_text(brand), 1)[-1]
    words = [w for w in re.findall(r"(?<![0-9a-z])[a-z][a-z0-9+\-]*", after.split("(")[0])
             if w not in GENERIC and w not in COLOURS and not SPEC.fullmatch(w)]
    line = "; ".join(list(dict.fromkeys(words))[:4])  # e.g. "optima+", "deep; circular; tee"
    packnorm = normalise_text(pack).replace(" ", "")
    specs = [s for s in dict.fromkeys(SPEC.findall(norm)) if s != packnorm]
    if not pack and not _LENGTHY.search(text):  # "Combined Plate 8 M": 8 modules, keep it in the hint
        specs += [f"{n}m" for n in dict.fromkeys(re.findall(r"(?<![0-9.x])(\d+)m(?![0-9a-z])", norm))]
    colour = next((c for c in COLOURS if re.search(rf"\b{c}\b", norm)), "")
    return "; ".join(x for x in [line, *specs, colour] if x)


def is_brand_product(title: str, brand: str) -> bool:
    """Made by this brand: the title starts with it ("Havells ...") or says "by Havells".
    "IMO PRECISION CONTROLS ..." is not a Precision product."""
    t, b = normalise_text(title), re.escape(normalise_text(brand))
    return re.match(rf"{b}(?![0-9a-z])", t) is not None or re.search(rf"\bby {b}(?![0-9a-z])", t) is not None


def clean_title(cand) -> str:
    t = re.sub(r"\s+", " ", cand.get("title") or "").strip()
    v = (cand.get("variant") or "").strip()
    if v and normalise_text(v) not in normalise_text(t):
        t = f"{t} {v}"
    return re.sub(r",\s*[A-Z0-9]{6,}$", "", t)  # trailing manufacturer code ", CCP0162501"


def build(brand: str, disc: dict, existing: list) -> list:
    used = {u for r in existing for u in r.urls.values()}
    code = code_of(brand)
    nums = [int(m.group(1)) for r in existing if (m := re.match(rf"RT-{code}-(\d+)$", r.sku))]
    n = max(nums, default=0)
    new = []
    taken = set(used)
    for src in ("industrybuying", "homerun", "moglix"):
        for cand in disc[src]:
            if cand["url"] in taken or not is_brand_product(cand.get("title") or "", brand):
                continue
            if cand.get("fetched") != "yes":
                continue
            if not cand["_in_stock"]:  # 18 Oct 2026: 293 of 301 Moglix-only products made from
                continue  # out-of-stock pages could never get a price; a new product needs one
            if any(passes(r, cand) for r in existing + new if r.variant_hint):
                continue  # already in the catalogue (often a second listing of the same product)
            title = clean_title(cand)
            pack = pack_of(title)
            row = Row(sku="", brand=brand, title=title, pack_size=pack,
                      variant_hint=hint_of(brand, title, pack), mode="priced", publish="pending_review")
            if not row.variant_hint or check_variant(row.variant_hint, pack, cand["_ident"]).status != "ok":
                continue  # cannot describe it well enough to check it every day
            row.urls = {src: cand["url"]}
            taken.add(cand["url"])
            for other in SOURCES:
                if other == src:
                    continue
                ok = [c for c in disc[other] if c["url"] not in taken and passes(row, c)]
                if len(ok) > 1 and any(c["_in_stock"] for c in ok):
                    ok = [c for c in ok if c["_in_stock"]]
                if len(ok) == 1:
                    row.urls[other] = ok[0]["url"]
                    taken.add(ok[0]["url"])
            n += 1
            row.sku = f"RT-{code}-{n:03d}"
            row.category = category_of(title)
            row.match_confidence = "high"
            row.notes = f"from discovery ({', '.join(sorted(row.urls))})"
            new.append(row)
    return new


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("discovery_dir")
    ap.add_argument("rows_dir")
    ap.add_argument("--brand", action="append", required=True)
    a = ap.parse_args(argv)
    disc = load_discovery(a.discovery_dir)
    out = Path(a.rows_dir)
    out.mkdir(parents=True, exist_ok=True)
    for brand in a.brand:
        path = out / f"{brand.lower().replace(' ', '-')}.csv"
        existing = [r for r in load_catalogue(out) if r.source_file.startswith(path.name + ":")] if path.exists() else []
        new = build(brand, disc, existing)
        if not new:
            print(f"{brand}: nothing new")
            continue
        if not path.exists():
            with open(path, "w", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerow(COLUMNS)
        write_catalogue(path, existing + new)
        by = {s: sum(1 for r in new if s in r.urls) for s in SOURCES}
        multi = sum(1 for r in new if len(r.urls) > 1)
        print(f"{brand}: +{len(new)} rows ({multi} on 2+ sites), URLs per site {by}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
