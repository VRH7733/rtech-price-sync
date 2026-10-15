#!/usr/bin/env python3
"""Back up every WooCommerce price before the first live publish, and restore on demand.

  python tools/backup_and_rollback.py backup                 # -> data/backup/products_YYYY-MM-DD.json
  python tools/backup_and_rollback.py restore FILE           # DRY RUN: shows what would be restored
  python tools/backup_and_rollback.py restore FILE --apply   # actually restores

Needs env WC_URL, WC_KEY, WC_SECRET. Backups hold prices only (no customer data). data/backup is
git-ignored; keep a copy somewhere safe too. Restore sets regular_price, sale_price and
stock_status back and removes our hidden flag. It never deletes products.
"""
import argparse
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from rtech_sync.config import PublisherCfg  # noqa: E402
from rtech_sync.publisher import META_HIDDEN, META_UPDATED, WooClient  # noqa: E402


def _client() -> WooClient:
    return WooClient(os.environ["WC_URL"], os.environ["WC_KEY"], os.environ["WC_SECRET"])


def _paged(client: WooClient, path: str):
    page = 1
    while True:
        status, data = client.get(path, {"per_page": 100, "page": page})
        if status != 200 or not data:
            if status != 200:
                raise SystemExit(f"GET {path} page {page} failed: HTTP {status}")
            return
        yield from data
        page += 1
        time.sleep(1)


def backup(out_dir: Path) -> Path:
    c = _client()
    items = []
    for p in _paged(c, "/products"):
        items.append({"kind": "product", "id": p["id"], "parent": None, "sku": p.get("sku"),
                      "type": p.get("type"), "regular_price": p.get("regular_price"),
                      "sale_price": p.get("sale_price"), "stock_status": p.get("stock_status")})
        if p.get("type") == "variable":
            for v in _paged(c, f"/products/{p['id']}/variations"):
                items.append({"kind": "variation", "id": v["id"], "parent": p["id"], "sku": v.get("sku"),
                              "regular_price": v.get("regular_price"), "sale_price": v.get("sale_price"),
                              "stock_status": v.get("stock_status")})
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"products_{date.today().isoformat()}.json"
    path.write_text(json.dumps({"created": date.today().isoformat(), "items": items}, indent=1))
    print(f"Backed up {len(items)} items to {path}")
    return path


def restore(file: Path, apply: bool) -> None:
    items = json.loads(file.read_text())["items"]
    print(f"{len(items)} items in backup. {'APPLYING' if apply else 'DRY RUN (add --apply)'}")
    if not apply:
        return
    c, cfg = _client(), PublisherCfg()
    simple = [i for i in items if i["kind"] == "product"]
    by_parent: dict = {}
    for i in items:
        if i["kind"] == "variation":
            by_parent.setdefault(i["parent"], []).append(i)

    def payload(i):
        return {"id": i["id"], "regular_price": i["regular_price"] or "", "sale_price": i["sale_price"] or "",
                "stock_status": i["stock_status"] or "instock",
                "meta_data": [{"key": META_HIDDEN, "value": "0"}, {"key": META_UPDATED, "value": ""}]}

    for k in range(0, len(simple), cfg.batch_size):
        st, _ = c.batch_products([payload(i) for i in simple[k:k + cfg.batch_size]])
        print("products batch ->", st)
        time.sleep(cfg.pause_seconds)
    for parent, vs in by_parent.items():
        for k in range(0, len(vs), cfg.batch_size):
            st, _ = c.batch_variations(parent, [payload(i) for i in vs[k:k + cfg.batch_size]])
            print(f"variations of {parent} ->", st)
            time.sleep(cfg.pause_seconds)


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("backup")
    r = sub.add_parser("restore")
    r.add_argument("file")
    r.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    for k in ("WC_URL", "WC_KEY", "WC_SECRET"):
        if not os.environ.get(k):
            print(f"Set {k} first (see .env.example)")
            return 2
    if a.cmd == "backup":
        backup(Path("data/backup"))
    else:
        restore(Path(a.file), a.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
