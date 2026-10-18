#!/usr/bin/env python3
"""Fill url_<source> cells of catalogue rows from discovery files (tools/discover.py output).

  python tools/match_discovery.py ROWS_DIR DISCOVERY_DIR [--brand Polycab] [--review review.csv]

A row gets a URL for a source only when EXACTLY ONE candidate passes the same variant/pack check
the nightly run uses (normalise.check_variant) on the candidate's own title (fetched pages) or
URL slug (Moglix, not fetched). Two or more passing candidates (e.g. two Polycab wire lines in the
same size and colour) are NOT guessed: they go to the review file. Matched rows become
publish=pending_review, never publish=yes. Cells that already hold a URL are left alone.
Out-of-stock candidates are skipped when an in-stock one also passes.
"""
import argparse
import csv
import os
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from rtech_sync.catalogue import load_catalogue, write_catalogue  # noqa: E402
from rtech_sync.matching import slug_text  # noqa: E402
from rtech_sync.normalise import check_variant, normalise_text  # noqa: E402

SOURCES = ("moglix", "industrybuying", "homerun")
# Moglix slugs drop the decimal point: "etira-15-sqmm" is 1.5 sq mm. Only the house-wire sizes
# that cannot be real whole numbers are restored (there is no 15 or 25 sq mm house wire, but there
# IS a 10 sq mm and a 16 sq mm one, so "10"/"16" are left alone).
_SLUG_DECIMALS = {"075": "0.75", "15": "1.5", "25": "2.5"}
_MULTI_CORE = re.compile(r"(?<![0-9.])([2-9]|1[0-9])\s*c(?:ore)?\b")


def slug_identity(url: str) -> str:
    s = slug_text(url)
    return re.sub(r"(?<![0-9.])(075|15|25)(?=\s*sqmm)", lambda m: _SLUG_DECIMALS[m.group(1)], s)


def load_discovery(directory):
    out = {s: [] for s in SOURCES}
    for path in sorted(Path(directory).glob("*.csv")):
        with open(path, newline="", encoding="utf-8") as fh:
            for rec in csv.DictReader(fh):
                src = rec.get("source", "")
                if src not in out:
                    continue
                if rec.get("fetched") == "yes":
                    if not rec.get("http_status", "").startswith("ok") or not rec.get("price"):
                        continue
                    ident = rec.get("identity") or rec.get("title") or ""
                else:
                    ident = slug_identity(rec["url"])
                rec["_ident"] = ident
                rec["_in_stock"] = str(rec.get("in_stock", "")).lower() != "false"
                out[src].append(rec)
    return out


def has_brand(text_norm: str, brand: str) -> bool:
    """The brand as a whole word ("gm" must not match inside "gms" or "sigma")."""
    b = re.escape(normalise_text(brand))
    return re.search(rf"(?<![0-9a-z]){b}(?![0-9a-z])", text_norm) is not None


def passes(row, cand) -> bool:
    ident = cand["_ident"]
    norm = normalise_text(ident)
    if not has_brand(norm, row.brand):
        return False
    if "core" not in row.variant_hint and _MULTI_CORE.search(norm):
        return False  # a single-core house-wire row never takes a multi-core cable page
    return check_variant(row.variant_hint, row.pack_size, ident).status == "ok"


def match(rows, disc, review):
    used = {u for r in rows for u in r.urls.values()}
    proposals = []
    for r in rows:
        if r.mode != "priced":
            continue
        for src in SOURCES:
            if r.urls.get(src):
                continue
            ok = [c for c in disc[src] if c["url"] not in used and passes(r, c)]
            if len(ok) > 1 and any(c["_in_stock"] for c in ok):
                ok = [c for c in ok if c["_in_stock"]]
            if len(ok) == 1:
                proposals.append((r, src, ok[0]["url"]))
            for c in ok if len(ok) > 1 else []:
                review.append([r.sku, r.title, r.variant_hint, r.pack_size, src, c["url"],
                               c.get("price", ""), c["_ident"][:120], f"{len(ok)} candidates pass"])
    # a page that fits two rows belongs to neither: guessing would give one of them a wrong price
    claims = Counter(u for _, _, u in proposals)
    n = 0
    for r, src, u in proposals:
        if claims[u] > 1:
            review.append([r.sku, r.title, r.variant_hint, r.pack_size, src, u, "", "",
                           f"{claims[u]} rows fit this page"])
            continue
        r.urls[src] = u
        if r.publish == "no":
            r.publish = "pending_review"
        r.match_confidence = "high"
        n += 1
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rows_dir")
    ap.add_argument("discovery_dir")
    ap.add_argument("--brand", action="append")
    ap.add_argument("--review", default="review.csv")
    a = ap.parse_args(argv)
    disc = load_discovery(a.discovery_dir)
    print("candidates:", {s: len(v) for s, v in disc.items()})
    review, total = [], 0
    for path in sorted(Path(a.rows_dir).glob("*.csv")):
        rows = load_catalogue_file(path)
        if a.brand and not any(r.brand.lower() in {b.lower() for b in a.brand} for r in rows):
            continue
        n = match(rows, disc, review)
        write_catalogue(path, rows)
        by_src = {s: sum(1 for r in rows if r.urls.get(s)) for s in SOURCES}
        print(f"{path.name}: {len(rows)} rows, +{n} URLs, rows with a URL per source {by_src}")
        total += n
    with open(a.review, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["sku", "title", "variant_hint", "pack_size", "source", "candidate_url", "price",
                    "candidate_identity", "why"])
        w.writerows(review)
    print(f"{total} URLs written; {len(review)} ambiguous candidates in {a.review}")
    return 0


def load_catalogue_file(path):
    tmp = Path(path)
    return [r for r in load_catalogue(tmp.parent) if r.source_file.startswith(tmp.name + ":")]


if __name__ == "__main__":
    sys.exit(main())
