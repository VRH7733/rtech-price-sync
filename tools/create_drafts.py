#!/usr/bin/env python3
"""Create WooCommerce products for catalogue rows that have no wc_product_id yet.

  python tools/create_drafts.py CATALOGUE.csv --sku RT-POLY-001 --sku RT-POLY-002          # plan only
  python tools/create_drafts.py CATALOGUE.csv --sku RT-POLY-001 --apply                    # drafts
  python tools/create_drafts.py CATALOGUE.csv --sku RT-POLY-001 --apply --live             # live

--live (owner's go-live approval, 15 Oct 2026): the product is published straight away as an
in-stock "Request a Quote" product (no price). The daily price run then gives it the cheapest
price and turns it into a normal product customers can add to the cart.

Needs WC_URL, WC_KEY, WC_SECRET in the environment (only with --apply).

Rules:
- Without --live a product is created as a "draft" with no price and "out of stock"; shoppers do
  not see a draft.
- A SKU that already exists in the shop is never changed: its id is written to the catalogue.
- Nothing is ever updated or deleted in the shop by this tool.
- Only rows named with --sku are touched (no "all" switch on purpose).
- The new wc_product_id is written back to the catalogue CSV.
"""
import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from rtech_sync.catalogue import load_catalogue, write_catalogue  # noqa: E402
from rtech_sync.publisher import WooClient  # noqa: E402


# shop categories (ids from the 14 Oct 2026 product export)
CATEGORY_IDS = {
    "wires & cables": 25,
    "modular switches & sockets": 24,
    "switchgear": 23,
}


def category_ids(row) -> list:
    cat = (row.category or "").strip().lower()
    if cat == "pipes & fittings":
        return [{"id": 28 if "pipe" in (row.title or "").lower() else 30}]
    return [{"id": CATEGORY_IDS[cat]}] if cat in CATEGORY_IDS else []


def live_payload(row, cfg) -> dict:
    from rtech_sync.publisher import quote_fields
    p = {
        "name": row.title,
        "sku": row.sku,
        "status": "publish",
        "regular_price": "",
        "categories": category_ids(row),
        "short_description": " ".join(x for x in (
            f"Brand: {row.brand}." if row.brand else "",
            f"Pack: {row.pack_size}." if row.pack_size else "",
            "Prices include GST.") if x),
        "meta_data": [{"key": "_rte_source", "value": "rtech-price-sync"}],
    }
    p.update(quote_fields(row.sku, cfg))
    return p


def draft_payload(row) -> dict:
    return {
        "name": row.title,
        "sku": row.sku,
        "type": "simple",
        "status": "draft",
        "regular_price": "",
        "stock_status": "outofstock",
        "meta_data": [{"key": "_rte_source", "value": "rtech-price-sync"}],
    }


def create_drafts(rows, skus, woo, apply: bool, sleep=time.sleep, pause: float = 2.0, live_cfg=None) -> list:
    """Returns (sku, outcome, id) for each requested SKU. Mutates rows' wc_product_id."""
    by_sku = {r.sku: r for r in rows}
    out = []
    for sku in skus:
        r = by_sku.get(sku)
        if r is None:
            out.append((sku, "not_in_catalogue", None))
            continue
        if r.wc_product_id is not None:
            out.append((sku, "already_linked", r.wc_product_id))
            continue
        if not apply:
            out.append((sku, "would_create_draft", None))
            continue
        status, found = woo.get("/products", {"sku": sku, "status": "any"})
        if status != 200:
            out.append((sku, f"lookup_failed_http_{status}", None))
            continue
        if found:
            r.wc_product_id = int(found[0]["id"])
            out.append((sku, "exists_in_shop_linked", r.wc_product_id))
            continue
        payload = live_payload(r, live_cfg) if live_cfg is not None else draft_payload(r)
        status, data = woo.create_product(payload)
        if status in (200, 201) and data.get("id") and data.get("status") == payload["status"]:
            r.wc_product_id = int(data["id"])
            if live_cfg is not None and r.publish != "yes":
                r.publish = "yes"  # owner's go-live approval: the daily run prices it
            out.append((sku, "created_live" if live_cfg is not None else "created_draft", r.wc_product_id))
        else:
            out.append((sku, f"create_failed_http_{status}", None))
        sleep(pause)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("catalogue_csv")
    ap.add_argument("--sku", action="append", required=True)
    ap.add_argument("--apply", action="store_true", help="really create the products (default: plan only)")
    ap.add_argument("--live", action="store_true", help="publish as in-stock Request a Quote products")
    ap.add_argument("--config", default=os.path.join(os.path.dirname(__file__), "..", "config.yaml"))
    a = ap.parse_args(argv)
    path = Path(a.catalogue_csv)
    rows = [r for r in load_catalogue(path.parent) if r.source_file.startswith(path.name + ":")]
    woo = None
    if a.apply:
        woo = WooClient(os.environ["WC_URL"], os.environ["WC_KEY"], os.environ["WC_SECRET"])
    live_cfg = None
    if a.live:
        from rtech_sync.config import load_config
        live_cfg = load_config(a.config, env={"RTECH_CONTACT_EMAIL": "unused@example.com"}).publisher
    results = create_drafts(rows, a.sku, woo, a.apply, live_cfg=live_cfg)
    for sku, outcome, pid in results:
        print(f"{sku}: {outcome}" + (f" (product id {pid})" if pid else ""))
    if a.apply and any(o in ("created_draft", "created_live", "exists_in_shop_linked") for _, o, _ in results):
        write_catalogue(path, rows)
        print(f"wc_product_id written to {path}")
    return 1 if any("failed" in o for _, o, _ in results) else 0


if __name__ == "__main__":
    sys.exit(main())
