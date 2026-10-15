#!/usr/bin/env python3
"""Turn rows of the starter seed list (data repo: catalogue/seed/priority_catalogue_seed.csv) into
catalogue rows the nightly run can read (catalogue/rows/<brand>.csv), one file per brand.

  python tools/seed_to_rows.py SEED.csv OUT_DIR --brand Polycab --brand VIP

- New SKUs RT-<BRAND>-<NNN> (the owner decided on 15 Oct 2026 that priced items are NEW products,
  so the custom P6 Sprint plugin, which only knows WEB-0xx SKUs, leaves them alone).
- variant_hint = the seed's identifying words, without the pack (that goes in pack_size) and
  without generic words that product pages do not repeat ("single core copper").
- Everything starts as publish=no with no URLs. URLs come from tools/match_discovery.py.
- An existing output file is never overwritten.
"""
import argparse
import csv
import re
import sys
from pathlib import Path

COLUMNS = ["sku", "wc_product_id", "wc_variation_id", "brand", "category", "family", "title",
           "pack_size", "variant_hint", "mode", "markup_pct", "gst_pct", "cost_floor", "manual_price",
           "publish", "match_confidence", "url_moglix", "url_industrybuying", "url_homerun", "notes"]
GENERIC = re.compile(r"^(single core copper|copper flexible|schedule/sdr tbd|single core)$", re.I)
PACK = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*m\b", re.I)


def pack_of(seed_pack: str) -> str:
    m = PACK.match(seed_pack or "")
    return f"{m.group(1)} m" if m else ""  # "1 pc" / "pack varies": pages rarely say it


def hint_of(seed_hint: str, pack: str) -> str:
    out = []
    for part in re.split(r"[,;]", seed_hint or ""):
        t = part.strip()
        if not t or GENERIC.match(t) or (pack and t.replace(" ", "") == pack.replace(" ", "")):
            continue
        # "20 mm bend" -> "20 mm; bend": each word group must appear on the page on its own
        m = re.match(r"^(\d+(?:\.\d+)?\s*mm)\s+(.+)$", t)
        out += [m.group(1), m.group(2)] if m else [t]
    return "; ".join(x.lower() for x in out)


def code_of(brand: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", brand.upper())[:4] or "GEN"


def convert(seed_rows, brands):
    wanted = {b.lower() for b in brands}
    by_brand = {}
    for r in seed_rows:
        if r["brand"].lower() not in wanted:
            continue
        rows = by_brand.setdefault(r["brand"], [])
        pack = pack_of(r.get("pack_size", ""))
        rows.append({
            "sku": f"RT-{code_of(r['brand'])}-{len(rows) + 1:03d}",
            "brand": r["brand"], "category": r["category"], "family": r["family"], "title": r["title"],
            "pack_size": pack, "variant_hint": hint_of(r.get("variant_hint", ""), pack),
            "mode": "priced", "publish": "no",
            "notes": f"seed tier {r.get('tier', '')}; {r.get('notes', '')}".strip("; "),
        })
    return by_brand


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("seed")
    ap.add_argument("out_dir")
    ap.add_argument("--brand", action="append", required=True)
    a = ap.parse_args(argv)
    with open(a.seed, newline="", encoding="utf-8-sig") as fh:
        seed = list(csv.DictReader(fh))
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for brand, rows in convert(seed, a.brand).items():
        path = out / f"{brand.lower().replace(' ', '-')}.csv"
        if path.exists():
            print(f"{path} exists: not overwritten", file=sys.stderr)
            continue
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {len(rows)} rows to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
