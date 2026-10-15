#!/usr/bin/env python3
"""Check ONE pasted marketplace URL before putting it in the catalogue.

  python tools/add_url.py --source moglix --url https://www.moglix.com/... \
      --hint "1.5 sqmm; red" --pack "90 m"

Shows: robots.txt verdict, parsed price, tax basis, whether the variant/pack is confirmed.
Makes 2 requests (robots.txt + the page). Writes nothing.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from rtech_sync.config import load_config  # noqa: E402
from rtech_sync.fetcher import Fetcher  # noqa: E402
from rtech_sync.models import Row  # noqa: E402
from rtech_sync.pipeline import evaluate_source  # noqa: E402
from rtech_sync.parsers import parse_product_page  # noqa: E402


def inspect_url(source: str, url: str, hint: str, pack: str, cfg, fetcher) -> dict:
    row = Row(sku="TEST", variant_hint=hint, pack_size=pack, urls={source: url}, publish="yes")
    fr = fetcher.get(url, budget_key=source)
    res = evaluate_source(row, source, fr, cfg)
    out = {"fetch_status": fr.status, "fetch_detail": fr.detail, "result_status": res.status,
           "result_detail": res.detail, "price_incl_gst": str(res.price) if res.price else None}
    if fr.status == "ok":
        p = parse_product_page(fr.text, url)
        out.update(parse_method=p.method, raw_price=str(p.price), tax_basis=p.tax_basis,
                   title=p.title, multi_variant=p.multi_variant, problems=p.problems,
                   identity_text=p.identity_text[:200])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, choices=["moglix", "industrybuying", "homerun"])
    ap.add_argument("--url", required=True)
    ap.add_argument("--hint", default="")
    ap.add_argument("--pack", default="")
    ap.add_argument("--config", default=os.path.join(os.path.dirname(__file__), "..", "config.yaml"))
    a = ap.parse_args()
    cfg = load_config(a.config)
    cfg.fetch.require_contact_email()
    info = inspect_url(a.source, a.url, a.hint, a.pack, cfg, Fetcher(cfg.fetch))
    for k, v in info.items():
        print(f"{k:16}: {v}")
    return 0 if info["result_status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
