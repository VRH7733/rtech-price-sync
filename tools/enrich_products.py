#!/usr/bin/env python3
"""Fill the empty parts of our product pages: specs, description, category, brand, illustration.

Usage:
  enrich_products.py render --catalogue-dir DIR --tiles-dir OUT [selection]
  enrich_products.py apply  --catalogue-dir DIR --tile-base-url URL[{bucket}] --media-map JSON --report MD
                            [selection] [--apply]
Selection: --sku RT-... (repeatable) | --sample N (spread across product types) | --all

Content comes only from our own catalogue (src/rtech_sync/content.py), never from marketplaces.
Only fields that are EMPTY on the shop are filled (or the one-line short description our
create_drafts wrote), so anything Harshi edited by hand is left alone. Price, stock, type and
button fields are never sent (owned by the daily price run). Only products carrying our
_rte_source meta are touched. Without --apply nothing is written: the report shows the plan.
Env for apply: WC_URL, WC_KEY, WC_SECRET.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import html
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from rtech_sync.catalogue import load_catalogue  # noqa: E402
from rtech_sync.content import ILLUSTRATION_NOTE, plan_row  # noqa: E402

CONTENT_VERSION = "1"
FORBIDDEN = {"regular_price", "sale_price", "price", "stock_status", "stock_quantity", "manage_stock",
             "type", "external_url", "button_text", "status", "sku", "name"}
# filterable on the shop (global attributes); the rest are product-level
GLOBAL_ATTRS = ["Size", "Cores", "Length", "Colour", "Current rating", "Poles", "Modules", "Wattage",
                "Sweep", "Power"]
OUR_SHORT = re.compile(r"^\s*<p>\s*Brand:.*Prices include GST\.\s*</p>\s*$", re.S)
PAUSE = 2.0
STOP_AFTER_FAILED_BATCHES = 3


def _text(h: str) -> str:
    return re.sub(r"<[^>]+>", "", h or "").strip()


def select(rows, skus=None, sample=0, all_rows=False):
    live = [r for r in rows if r.wc_product_id and r.publish == "yes" and not r.wc_variation_id]
    if skus:
        want = set(skus)
        return [r for r in live if r.sku in want]
    if all_rows:
        return live
    if sample:
        by_kind = collections.defaultdict(list)
        for r in sorted(live, key=lambda r: hashlib.sha1(r.sku.encode()).hexdigest()):
            by_kind[plan_row(r.title, r.brand, r.category)["kind"]].append(r)
        out, i = [], 0
        while len(out) < sample and any(i < len(v) for v in by_kind.values()):
            for k in sorted(by_kind):
                if i < len(by_kind[k]) and len(out) < sample:
                    out.append(by_kind[k][i])  # lists are in hash order, so brands are mixed
            i += 1
        return list({r.sku: r for r in out}.values())
    raise SystemExit("choose --sku, --sample N or --all")


def tile_bucket(name: str) -> str:
    """0-f from the name's hash: GitHub allows only 1,000 files per release, so they are spread over 16."""
    return name.rsplit("-", 1)[1][0]


def tile_url(base: str, name: str) -> str:
    """base may contain {bucket}, e.g. .../releases/download/product-illustrations-{bucket}"""
    return base.replace("{bucket}", tile_bucket(name)).rstrip("/") + "/" + name


# categories this tool created; only these may be corrected by --replace-ours
OUR_CATEGORIES = {"Fans", "Lighting", "Water Pumps", "Water Heaters", "Home Appliances", "Lugs & Accessories",
                  "Other Electricals"}


def update_payload(current: dict, plan: dict, ids: dict, tile_url: str, media_map: dict,
                   replace_ours: bool = False, illustrations: bool = False) -> dict:
    """What to send for one product: only the parts that are empty on the shop.
    replace_ours: also redo what THIS tool wrote earlier (product carries _rte_content), to fix a
    wrong classification. Hand-made content on products without that mark is never replaced."""
    ours = replace_ours and any(m.get("key") == "_rte_content" for m in current.get("meta_data", []))
    if ours:
        current = dict(current, description="", short_description="", attributes=[], images=[])
        names = {html.unescape(c.get("name", "")) for c in current.get("categories") or []}
        if names and names <= OUR_CATEGORIES and plan["category"] not in names:
            current["categories"] = []
    p = {"id": current["id"]}
    if not _text(current.get("description")):
        p["description"] = plan["description"]
    sd = current.get("short_description") or ""
    if not _text(sd) or OUR_SHORT.match(sd):
        p["short_description"] = plan["short_description"]
    cats = current.get("categories") or []
    if not cats or all(c.get("slug") == "uncategorized" for c in cats):
        p["categories"] = [{"id": ids["categories"][plan["category"]]}]
    if not current.get("brands") and plan["brand"] in ids["brands"]:
        p["brands"] = [ids["brands"][plan["brand"]]]
    if not current.get("attributes"):
        attrs = []
        for pos, (k, v) in enumerate((k, v) for k, v in plan["specs"].items() if k != "Brand"):
            a = {"position": pos, "visible": True, "variation": False, "options": [v]}
            if k in ids["attributes"]:
                a["id"] = ids["attributes"][k]
            else:
                a["name"] = k
            attrs.append(a)
        if attrs:
            p["attributes"] = attrs
    # Harshi, 16 Oct 2026: the drawings looked poor, so products get no picture until real ones exist
    if illustrations and not current.get("images"):
        name = plan["tile_name"]
        alt = f"{html.unescape(current.get('name') or '')} (illustration)"
        if name in media_map:
            p["images"] = [{"id": media_map[name], "alt": alt}]
        else:
            p["images"] = [{"src": tile_url, "alt": alt, "name": name.rsplit(".", 1)[0]}]
    if len(p) > 1:
        p["meta_data"] = [{"key": "_rte_content", "value": CONTENT_VERSION}]
    bad = FORBIDDEN & set(p)
    if bad:
        raise AssertionError(f"refusing to send price/stock fields: {bad}")
    return p


class Woo:
    def __init__(self, base, key, secret, session=None, timeout=90):
        import requests
        self.base = base.rstrip("/") + "/wp-json/wc/v3"
        self.auth = (key, secret)
        self.s = session or requests.Session()
        self.timeout = timeout

    def _retry(self, fn):
        """The shop sometimes drops a connection when busy: wait and try again (3 tries)."""
        import requests
        for wait in (20, 60, None):
            try:
                r = fn()
                if r.status_code in (429, 500, 502, 503, 504, 508) and wait:
                    time.sleep(wait)
                    continue
                return r
            except (requests.ConnectionError, requests.Timeout):
                if not wait:
                    raise
                time.sleep(wait)

    def get(self, path, params=None):
        r = self._retry(lambda: self.s.get(self.base + path, params=params or {}, auth=self.auth,
                                           timeout=self.timeout))
        try:
            return r.status_code, r.json(), r.headers
        except ValueError:
            return r.status_code, None, r.headers

    def post(self, path, payload):
        # GETs are safe to repeat; a batch update is too (it sets fields, never adds), so retry both
        r = self._retry(lambda: self.s.post(self.base + path, json=payload, auth=self.auth, timeout=self.timeout))
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {}

    def all(self, path, params=None):
        out, page = [], 1
        while True:
            st, data, h = self.get(path, dict(params or {}, per_page=100, page=page))
            if st != 200 or not isinstance(data, list):
                raise RuntimeError(f"GET {path} failed: HTTP {st}")
            out += data
            if page >= int(h.get("X-WP-TotalPages", "1") or 1):
                return out
            page += 1
            time.sleep(PAUSE / 2)


def ensure_terms(woo, plans, apply, log):
    """Ids of the categories, brands and global attributes the plans need; creates missing ones."""
    ids = {"categories": {}, "brands": {}, "attributes": {}}
    created = collections.Counter()
    for kind, path, wanted in (
        ("categories", "/products/categories", {p["category"] for p in plans}),
        ("brands", "/products/brands", {p["brand"] for p in plans if p["brand"]}),
        ("attributes", "/products/attributes", {k for p in plans for k in p["specs"]} & set(GLOBAL_ATTRS)),
    ):
        have = woo.all(path) if kind != "attributes" else woo.get(path)[1] or []
        by_name = {html.unescape(t["name"]).strip().lower(): t["id"] for t in have}
        for name in sorted(wanted):
            if name.lower() in by_name:
                ids[kind][name] = by_name[name.lower()]
                continue
            created[kind] += 1
            if not apply:
                ids[kind][name] = -1
                continue
            body = {"name": name}
            if kind == "attributes":
                body.update({"type": "select", "order_by": "name", "has_archives": False})
            st, data = woo.post(path, body)
            if st not in (200, 201) or "id" not in (data or {}):
                raise RuntimeError(f"could not create {kind[:-1]} {name!r}: HTTP {st}")
            ids[kind][name] = data["id"]
            time.sleep(PAUSE / 2)
    log(f"taxonomy: to create {dict(created)}")
    return ids, created


def run_apply(rows, a, woo, sleep=time.sleep, log=print):
    media_map = json.loads(Path(a.media_map).read_text()) if Path(a.media_map).exists() else {}
    plans = {r.sku: plan_row(r.title, r.brand, r.category) for r in rows}
    ids, created = ensure_terms(woo, list(plans.values()), a.apply, log)
    current = {}
    pid = [r.wc_product_id for r in rows]
    for i in range(0, len(pid), 100):
        st, data, _ = woo.get("/products", {"include": ",".join(map(str, pid[i:i + 100])), "per_page": 100})
        if st != 200:
            raise RuntimeError(f"GET products failed: HTTP {st}")
        current.update({p["id"]: p for p in data})
        sleep(PAUSE / 2)
    stats, payloads, skipped = collections.Counter(), [], collections.Counter()
    for r in rows:
        cur = current.get(r.wc_product_id)
        if not cur:
            skipped["not on shop"] += 1
            continue
        if not any(m.get("key") == "_rte_source" for m in cur.get("meta_data", [])):
            skipped["not ours"] += 1
            continue
        plan = plans[r.sku]
        p = update_payload(cur, plan, ids, tile_url(a.tile_base_url, plan["tile_name"]), media_map,
                           replace_ours=getattr(a, "replace_ours", False),
                           illustrations=getattr(a, "illustrations", False))
        if len(p) == 1:
            skipped["already complete"] += 1
            continue
        for k in p:
            if k not in ("id", "meta_data"):
                stats[k] += 1
        payloads.append((r, plan, p))
    log(f"products to update: {len(payloads)}; fields: {dict(stats)}; skipped: {dict(skipped)}")
    result = {"updated": [], "failed": {}, "stats": stats, "skipped": skipped, "created": created}
    if not a.apply:
        return result, payloads, media_map

    # pass 1: one product per new illustration (WordPress downloads it); pass 2: everyone else reuses it
    first, rest, seen = [], [], set()
    for r, plan, p in payloads:
        src = p.get("images", [{}])[0].get("src")
        if src and plan["tile_name"] not in seen:
            seen.add(plan["tile_name"])
            first.append((r, plan, p))
        else:
            rest.append((r, plan, p))
    failed_in_a_row = 0
    for batch_size, group in ((5, first), (20, rest)):
        for i in range(0, len(group), batch_size):
            chunk = group[i:i + batch_size]
            items = []
            for r, plan, p in chunk:
                if "images" in p and "src" in p["images"][0] and plan["tile_name"] in media_map:
                    p["images"] = [{"id": media_map[plan["tile_name"]], "alt": p["images"][0]["alt"]}]
                items.append(p)
            st, data = woo.post("/products/batch", {"update": items})
            answers = {x.get("id"): x for x in (data or {}).get("update", [])} if st == 200 else {}
            ok_any = False
            for r, plan, p in chunk:
                ans = answers.get(p["id"])
                if not ans or "error" in ans:
                    result["failed"][r.sku] = (ans or {}).get("error", {}).get("message", f"HTTP {st}")[:200]
                    continue
                ok_any = True
                result["updated"].append((r.sku, ans.get("permalink", "")))
                if ans.get("images") and plan["tile_name"] not in media_map and "images" in p:
                    media_map[plan["tile_name"]] = ans["images"][0]["id"]
            failed_in_a_row = 0 if ok_any else failed_in_a_row + 1
            if failed_in_a_row >= STOP_AFTER_FAILED_BATCHES:
                result["fatal"] = f"stopped after {failed_in_a_row} failed batches in a row (HTTP {st})"
                Path(a.media_map).write_text(json.dumps(media_map, indent=1, sort_keys=True))
                return result, payloads, media_map
            Path(a.media_map).write_text(json.dumps(media_map, indent=1, sort_keys=True))
            sleep(PAUSE)
    return result, payloads, media_map


def removal_payload(current: dict, our_image_ids: set):
    """Take OUR drawing off a product (only if every image on it is one of ours) and drop the
    'picture is an illustration' line from its description. Anything else is left alone."""
    if not any(m.get("key") == "_rte_content" for m in current.get("meta_data", [])):
        return None
    imgs = current.get("images") or []
    p = {"id": current["id"]}
    if imgs and all(i.get("id") in our_image_ids for i in imgs):
        p["images"] = []
    desc = current.get("description") or ""
    if ILLUSTRATION_NOTE in desc:
        p["description"] = desc.replace(ILLUSTRATION_NOTE, "").rstrip()
    return p if len(p) > 1 else None


def run_remove(rows, a, woo, sleep=time.sleep, log=print):
    media_map = json.loads(Path(a.media_map).read_text()) if Path(a.media_map).exists() else {}
    ours = set(media_map.values())
    result = {"updated": [], "failed": {}, "stats": collections.Counter(), "skipped": collections.Counter(),
              "created": {}}
    pid = [r.wc_product_id for r in rows]
    by_id = {r.wc_product_id: r for r in rows}
    payloads = []
    for i in range(0, len(pid), 100):
        st, data, _ = woo.get("/products", {"include": ",".join(map(str, pid[i:i + 100])), "per_page": 100})
        if st != 200:
            raise RuntimeError(f"GET products failed: HTTP {st}")
        for cur in data:
            p = removal_payload(cur, ours)
            if p is None:
                result["skipped"]["nothing of ours"] += 1
                continue
            for k in p:
                if k != "id":
                    result["stats"][k] += 1
            payloads.append((by_id[cur["id"]], None, p))
        sleep(PAUSE / 2)
    log(f"products to change: {len(payloads)}; fields: {dict(result['stats'])}; skipped: {dict(result['skipped'])}")
    if not a.apply:
        return result, payloads
    failed_in_a_row = 0
    for i in range(0, len(payloads), 20):
        chunk = payloads[i:i + 20]
        st, data = woo.post("/products/batch", {"update": [p for _, _, p in chunk]})
        answers = {x.get("id"): x for x in (data or {}).get("update", [])} if st == 200 else {}
        ok_any = False
        for r, _, p in chunk:
            ans = answers.get(p["id"])
            if not ans or "error" in ans:
                result["failed"][r.sku] = (ans or {}).get("error", {}).get("message", f"HTTP {st}")[:200]
            else:
                ok_any = True
                result["updated"].append((r.sku, ans.get("permalink", "")))
        failed_in_a_row = 0 if ok_any else failed_in_a_row + 1
        if failed_in_a_row >= STOP_AFTER_FAILED_BATCHES:
            result["fatal"] = f"stopped after {failed_in_a_row} failed batches in a row (HTTP {st})"
            break
        sleep(PAUSE)
    return result, payloads


def verify(woo, rows):
    """Re-read the products and count what a customer now sees."""
    c = collections.Counter()
    pid = [r.wc_product_id for r in rows]
    for i in range(0, len(pid), 100):
        st, data, _ = woo.get("/products", {"include": ",".join(map(str, pid[i:i + 100])), "per_page": 100})
        for p in data or []:
            c["checked"] += 1
            c["has image"] += bool(p.get("images"))
            c["has description"] += bool(_text(p.get("description")))
            c["has category"] += not all(x.get("slug") == "uncategorized" for x in p.get("categories") or [{}])
            c["has brand"] += bool(p.get("brands"))
            c["has specs"] += bool(p.get("attributes"))
            if p.get("images") and c["image opens"] + c["image broken"] < 3:
                try:
                    ok = woo.s.get(p["images"][0]["src"], timeout=30).status_code == 200
                except Exception:  # noqa: BLE001 - any failure means a customer would not see it
                    ok = False
                c["image opens" if ok else "image broken"] += 1
        time.sleep(PAUSE / 2)
    return c


def write_report(path, a, result, payloads, checked):
    lines = [f"# Product content run ({'APPLIED' if a.apply else 'plan only'})", "",
             f"- Products selected: {len(payloads) + sum(result['skipped'].values())}",
             f"- To update: {len(payloads)}; fields: {dict(result['stats'])}",
             f"- Skipped: {dict(result['skipped'])}",
             f"- New categories/brands/attributes: {dict(result['created'])}"]
    if a.apply:
        lines += [f"- Updated: {len(result['updated'])}; failed: {len(result['failed'])}"]
        if result.get("fatal"):
            lines += [f"- STOPPED: {result['fatal']}"]
        if checked:
            lines += [f"- Shop now (re-read): {dict(checked)}"]
        lines += ["", "## Failures", ""] + [f"- {k}: {v}" for k, v in result["failed"].items()]
        lines += ["", "## Updated pages", ""] + [f"- {s} {u}" for s, u in result["updated"][:60]]
    else:
        lines += ["", "## Plan (first 40)", "", "| sku | category | image | specs |", "|---|---|---|---|"]
        for r, plan, p in payloads[:40]:
            if plan is None:  # removal run
                lines.append(f"| {r.sku} | (keep) | {'remove drawing' if 'images' in p else '(keep)'} | |")
                continue
            spec = "; ".join(f"{k} {v}" for k, v in plan["specs"].items() if k != "Brand")
            lines.append(f"| {r.sku} | {plan['category'] if 'categories' in p else '(keep)'} | "
                         f"{plan['tile_name'] if 'images' in p else '(keep)'} | {spec} |")
    Path(path).write_text("\n".join(lines) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["render", "apply"])
    ap.add_argument("--catalogue-dir", required=True)
    ap.add_argument("--sku", action="append", default=[])
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--tiles-dir")
    ap.add_argument("--tile-base-url", default="")
    ap.add_argument("--media-map", default="media_map.json")
    ap.add_argument("--report", default="enrich_report.md")
    ap.add_argument("--selection-out", help="write the selected SKUs here (render mode)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--remove-illustrations", action="store_true",
                    help="take our drawings off the selected products (keeps text, specs, categories)")
    ap.add_argument("--illustrations", action="store_true", help="also add our drawings (off since 16 Oct)")
    ap.add_argument("--replace-ours", action="store_true",
                    help="redo content this tool wrote before (needs --sku); fixes misclassified products")
    a = ap.parse_args(argv)
    if a.replace_ours and not a.sku:
        raise SystemExit("--replace-ours only with --sku")
    rows = select(load_catalogue(a.catalogue_dir), a.sku, a.sample, a.all)
    print(f"selected {len(rows)} products")
    if a.mode == "render":
        from rtech_sync.tiles import render
        out = Path(a.tiles_dir)
        out.mkdir(parents=True, exist_ok=True)
        made = 0
        for r in rows:
            plan = plan_row(r.title, r.brand, r.category)
            f = out / plan["tile_name"]
            if not f.exists():
                render(plan["tile"], str(f))
                made += 1
        if a.selection_out:
            Path(a.selection_out).write_text(" ".join(r.sku for r in rows))
        print(f"illustrations rendered: {made}")
        return 0
    woo = Woo(os.environ["WC_URL"], os.environ["WC_KEY"], os.environ["WC_SECRET"])
    if a.remove_illustrations:
        result, payloads = run_remove(rows, a, woo)
    else:
        result, payloads, _ = run_apply(rows, a, woo)
    checked = verify(woo, rows) if a.apply else None
    write_report(a.report, a, result, payloads, checked)
    print(f"updated {len(result['updated'])}, failed {len(result['failed'])}")
    if checked:
        print(f"shop now: {dict(checked)}")
    return 1 if result.get("fatal") else 0


if __name__ == "__main__":
    sys.exit(main())
