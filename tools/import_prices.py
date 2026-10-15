#!/usr/bin/env python3
"""Copy the owner's prices from a filled price sheet into catalogue manual_price.

  python tools/import_prices.py SHEET.csv CATALOGUE.csv            # shows what would change
  python tools/import_prices.py SHEET.csv CATALOGUE.csv --write

SHEET.csv needs the columns sku and your_price_incl_gst (as in catalogue/review/your_prices_*.csv).
Blank prices are skipped. A price must be a positive number (commas and the rupee sign are
allowed). Only manual_price changes; publish stays as it is (the owner sets publish=yes).
"""
import argparse
import csv
import os
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from rtech_sync.catalogue import load_catalogue, write_catalogue  # noqa: E402


def parse_price(text: str):
    t = re.sub(r"[₹,\s]|^rs\.?", "", (text or "").strip(), flags=re.I)
    if not t:
        return None
    try:
        p = Decimal(t)
    except InvalidOperation:
        raise ValueError(f"not a number: {text!r}")
    if p <= 0:
        raise ValueError(f"price must be above 0: {text!r}")
    return p


def apply_sheet(sheet_rows, rows):
    """Returns (changes, problems). Mutates rows' manual_price."""
    by_sku = {r.sku: r for r in rows}
    changes, problems = [], []
    for rec in sheet_rows:
        sku = (rec.get("sku") or "").strip()
        try:
            price = parse_price(rec.get("your_price_incl_gst", ""))
        except ValueError as e:
            problems.append(f"{sku}: {e}")
            continue
        if price is None:
            continue
        r = by_sku.get(sku)
        if r is None:
            problems.append(f"{sku}: not in the catalogue")
            continue
        if r.manual_price != price:
            changes.append((sku, r.manual_price, price))
            r.manual_price = price
    return changes, problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sheet")
    ap.add_argument("catalogue_csv")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    path = Path(a.catalogue_csv)
    rows = [r for r in load_catalogue(path.parent) if r.source_file.startswith(path.name + ":")]
    with open(a.sheet, newline="", encoding="utf-8-sig") as fh:
        changes, problems = apply_sheet(csv.DictReader(fh), rows)
    for sku, old, new in changes:
        print(f"{sku}: manual_price {old if old is not None else '(none)'} -> {new}")
    for p in problems:
        print("PROBLEM", p)
    if problems:
        print("Nothing written: fix the problems first.")
        return 1
    if a.write and changes:
        write_catalogue(path, rows)
        print(f"{len(changes)} prices written to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
