"""Daily run: fetch -> evaluate -> decide -> publish -> report.

    PYTHONPATH=src python -m rtech_sync.run                 # DRY RUN (default, changes nothing)
    PYTHONPATH=src python -m rtech_sync.run --publish       # live: updates WooCommerce
"""
from __future__ import annotations

import argparse
import dataclasses
import csv
import json
import os
import sys
import time
import zlib
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from . import report
from .catalogue import CatalogueError, load_catalogue, validate
from .config import Config, ConfigError, load_config
from .siblings import apply_cable_guard, apply_listing_guard, apply_sibling_guard, seller_listing_only
from .decision import Decision, decide
from .fetcher import Fetcher
from .models import SourceResult
from .pipeline import evaluate_source
from .publisher import PublishReport, Update, WooClient, publish_updates
from .state import get_price_state, load_state, save_state, set_item


@dataclass
class RunResult:
    items: list = field(default_factory=list)  # dicts: row, decision, results, live_price
    updates: list = field(default_factory=list)
    publish_report: PublishReport = field(default_factory=PublishReport)
    stats: dict = field(default_factory=dict)
    changed: list = field(default_factory=list)  # (sku, old, new, action)


# A site that refuses this many pages in a row (HTTP 401/403/429 or a block page) is not asked
# again in this run: its remaining products keep their last price (hold) until it answers again.
STOP_AFTER_BLOCKS = 5


def _fetch_all(tasks: list, fetcher: Fetcher, deadline: float, now: Callable,
               stopped: Optional[dict] = None) -> dict:
    """tasks: (row, source, url). One worker per host so per-host pacing is never exceeded.
    stopped (out): source -> number of pages left unasked after the site kept refusing us."""
    by_source: dict = defaultdict(list)
    for t in tasks:
        by_source[t[1]].append(t)
    results: dict = {}
    stopped = stopped if stopped is not None else {}

    def worker(source: str):
        in_a_row = 0
        todo = by_source[source]
        for i, (row, src, url) in enumerate(todo):
            if now() > deadline:
                return
            res = fetcher.get(url, budget_key=src)
            results[(row.sku, src)] = res
            in_a_row = in_a_row + 1 if res.status == "blocked" else 0
            if in_a_row >= STOP_AFTER_BLOCKS:
                stopped[source] = len(todo) - i - 1
                print(f"{source}: {in_a_row} pages refused in a row; not asking it again this run")
                return

    if by_source:
        with ThreadPoolExecutor(max_workers=len(by_source)) as ex:
            list(ex.map(worker, list(by_source)))
    return results


KEEP_STATUSES = {"blocked", "robots_blocked"}


def last_seen(item: dict) -> dict:
    """source -> (price, date) of the last REAL reading. Older state has only "sources"
    (the last usable prices), dated by last_ok."""
    seen = {}
    ref = item.get("last_ok") or item.get("first_seen")
    for src, price in (item.get("sources") or {}).items():
        if ref and price:
            seen[src] = (price, ref)
    for src, v in (item.get("seen") or {}).items():
        seen[src] = (v["price"], v["date"])
    return seen


def keep_blocked_prices(results: list, item: dict, stopped, today: date, max_days: int) -> list:
    """While a site refuses us (blocked, or not asked because it kept refusing or is no longer
    used: `stopped`), use its last
    real price for this product if it is at most max_days old. Changes results in place;
    returns [(source, date of the kept price)]."""
    if max_days <= 0:
        return []
    seen = last_seen(item)
    kept = []
    for i, res in enumerate(results):
        refused = res.status in KEEP_STATUSES or (res.status == "not_refreshed" and res.source in stopped)
        if not refused or res.source not in seen:
            continue
        price, when = seen[res.source]
        if (today - date.fromisoformat(when)).days > max_days:
            continue
        results[i] = SourceResult(res.source, "ok", price=Decimal(price), url=res.url,
                                  detail=f"kept: last real price from {when} (site refusing us)")
        kept.append((res.source, when))
    return kept


def record_seen(state: dict, sku: str, results: list, today: date) -> None:
    """Remember each source's last REAL price and its date (kept prices keep their old date)."""
    item = state["items"].setdefault(sku, {})
    seen = {k: dict(v) for k, v in (item.get("seen") or {}).items()}
    for src, (price, when) in last_seen(item).items():
        seen.setdefault(src, {"price": price, "date": when})
    for res in results:
        if res.usable and not res.detail.startswith("kept:"):
            seen[res.source] = {"price": str(res.price), "date": today.isoformat()}
    if seen:
        item["seen"] = seen


def fresh_brand_price(bp: Optional[dict], today: date, max_days: int) -> Optional[Decimal]:
    """The brand's official MRP for a product, if read within max_days (0 = off)."""
    if not bp or max_days <= 0:
        return None
    try:
        seen, mrp = date.fromisoformat(bp["date"]), Decimal(str(bp["mrp"]))
    except (KeyError, ValueError, ArithmeticError, TypeError):
        return None
    if mrp <= 0 or not 0 <= (today - seen).days <= max_days:
        return None
    return mrp.to_integral_value()


def apply_brand_prices(items: list, brand_prices: dict, today: date, max_days: int) -> int:
    """Owner, 18 Oct 2026 (option c): a product no marketplace can price shows the brand's own
    MRP from its official shop instead of Request a Quote. Only where the shop would otherwise show
    Request a Quote (hidden, or held with no price live); never instead of a marketplace price,
    never over a held move. No discount on MRP."""
    n = 0
    for it in items:
        d, ps = it["decision"], it.get("ps")
        quote = d.action == "hide" or (
            d.action == "hold" and d.pending is None and (ps is None or ps.hidden or ps.price is None))
        bp = brand_prices.get(it["row"].sku)
        mrp = fresh_brand_price(bp, today, max_days)
        if not quote or mrp is None:
            continue
        d.action, d.price, d.refreshed = "publish", mrp, True
        d.info.append(f"brand_mrp:{bp.get('url', '')}")
        n += 1
    return n


def checked_today(row, ps, today: date, every: int) -> bool:
    """Each product is checked on one day in `every` (fixed by its SKU, so the shares stay even
    and predictable). A held big move is re-checked the next day, and a product never priced
    yet is checked at once."""
    if every <= 1 or ps.pending or ps.first_seen is None:
        return True
    return zlib.crc32(row.sku.encode()) % every == today.toordinal() % every


def run_sync(
    cfg: Config,
    rows: list,
    state: dict,
    fetcher: Fetcher,
    woo: Optional[WooClient],
    today: date,
    publish: bool,
    only_brands: Optional[list] = None,
    limit: Optional[int] = None,
    now: Callable = time.monotonic,
    sleep: Callable = time.sleep,
    include_pending: bool = False,
    only_new: bool = False,
    all_products: bool = False,
    brand_prices: Optional[dict] = None,
    kept_only: bool = False,
) -> RunResult:
    started = now()
    deadline = started + cfg.fetch.max_runtime_minutes * 60
    rr = RunResult()

    if include_pending and publish:
        raise ValueError("include_pending is for dry runs only")
    ok_publish = ("yes", "pending_review") if include_pending else ("yes",)
    eligible = [r for r in rows if r.mode == "priced" and r.publish in ok_publish]
    if only_new:  # products the bot has never priced (e.g. created after the morning run began)
        eligible = [r for r in eligible if get_price_state(state, r.sku).first_seen is None]
    brand_prices = brand_prices or {}
    brand_only: set = set()  # not checked today, but its brand MRP keeps it priced (no requests)
    if kept_only:  # re-judge without any request: products no site is asked about (kept prices),
        # and Request a Quote products that have a fresh brand MRP
        keep = []
        for r in eligible:
            ps = get_price_state(state, r.sku)
            if not any(s in r.urls and s not in cfg.fetch.skip_sources for s in cfg.sources):
                keep.append(r)
            elif (ps.hidden or ps.price is None) and fresh_brand_price(
                    brand_prices.get(r.sku), today, cfg.pricing.brand_price_days):
                brand_only.add(r.sku)
                keep.append(r)
        eligible = keep
    if cfg.fetch.check_every_days > 1 and not all_products and not only_new and not kept_only:
        todays = [r for r in eligible if checked_today(r, get_price_state(state, r.sku), today,
                                                        cfg.fetch.check_every_days)]
        picked = {r.sku for r in todays}
        for r in eligible:
            ps = get_price_state(state, r.sku)
            if (r.sku not in picked and (ps.hidden or ps.price is None)
                    and fresh_brand_price(brand_prices.get(r.sku), today, cfg.pricing.brand_price_days)):
                brand_only.add(r.sku)
                todays.append(r)
        eligible = todays
    if only_brands:
        wanted = {b.lower() for b in only_brands}
        eligible = [r for r in eligible if r.brand.lower() in wanted]
    # oldest-validated first, so a time/budget shortfall rotates fairly across days
    far_past = date(1970, 1, 1)
    eligible.sort(key=lambda r: (get_price_state(state, r.sku).last_ok or far_past, r.sku))
    if limit:
        eligible = eligible[:limit]

    # a row whose only listing needs a second site cannot get a price today: skip the request
    seller_only = {}
    if cfg.pricing.rule == "cheapest":
        for r in eligible:
            src = seller_listing_only(r, cfg.sources, cfg.pricing.needs_second_site)
            if src:
                seller_only[r.sku] = src

    tasks = []
    for r in eligible:
        if r.manual_price is not None and not cfg.pricing.fetch_for_manual_rows:
            continue
        if r.sku in seller_only or r.sku in brand_only:
            continue
        for s in cfg.sources:
            if s in r.urls and s not in cfg.fetch.skip_sources:
                tasks.append((r, s, r.urls[s]))
    stopped: dict = {}
    fetched = _fetch_all(tasks, fetcher, deadline, now, stopped)

    for r in eligible:
        ps = get_price_state(state, r.sku)
        internal_error = ""
        try:
            results = [evaluate_source(r, s, fetched.get((r.sku, s)), cfg) for s in cfg.sources]
        except Exception as e:  # one bad page must never abort the whole run
            internal_error = f"{type(e).__name__}"
            results = [
                SourceResult(s, "error", url=r.urls.get(s, ""), detail="internal: " + internal_error)
                for s in cfg.sources
            ]
        kept = keep_blocked_prices(results, state["items"].get(r.sku, {}),
                                   set(stopped) | set(cfg.fetch.skip_sources), today,
                                   cfg.pricing.keep_blocked_days)
        # pilot dry run: judge a pending row as if it were approved (nothing is published)
        as_row = dataclasses.replace(r, publish="yes") if include_pending and r.publish == "pending_review" else r
        d = decide(as_row, results, ps, cfg.pricing, today)
        if internal_error:
            d.flags.append("internal_error")
        for src, seen in kept:
            d.info.append(f"kept_last:{src}:{seen}")
        rr.items.append({"row": r, "decision": d, "results": results, "live_price": ps.price, "ps": ps})
        if publish and ps.first_seen is None:
            set_item(state, r.sku, first_seen=today.isoformat())

    for it in rr.items:
        src = seller_only.get(it["row"].sku)
        if src:
            d = it["decision"]
            d.action, d.price, d.pending, d.refreshed = "hide", None, None, False
            d.flags = [f"unconfirmed_listing:{src}"]
            d.note = "only listing is a seller listing; not fetched"
    if cfg.pricing.rule == "cheapest":
        apply_sibling_guard(rr.items, cfg.pricing.sibling_ratio)
        apply_listing_guard(rr.items, cfg.pricing.needs_second_site)
        apply_cable_guard(rr.items, cfg.pricing.cable_max_per_sqmm_metre)
    for it in rr.items:
        if it["row"].sku in brand_only:  # not fetched today: only its brand MRP can price it
            it["decision"] = Decision(it["row"].sku, "hide", note="not checked today")
    brand_priced = apply_brand_prices(rr.items, brand_prices, today, cfg.pricing.brand_price_days)

    for it in rr.items:
        r, d, ps = it["row"], it["decision"], it["ps"]

        # what the price rule decided, before "no WooCommerce id" blocks publishing (pilot table)
        rr.items[-1]["rule_action"], rr.items[-1]["rule_price"] = d.action, d.price
        if r.wc_product_id is None:
            d.flags.append("no_wc_id")
            d.action, d.price = "hold", None  # cannot publish without a WooCommerce id
            continue
        if d.action == "publish" and (ps.price != d.price or ps.hidden):
            rr.updates.append(Update(r.sku, r.wc_product_id, r.wc_variation_id, d.price, today.isoformat()))
        elif d.action == "hide" and not ps.hidden:
            rr.updates.append(Update(r.sku, r.wc_product_id, r.wc_variation_id, None, today.isoformat()))

    rr.publish_report = publish_updates(woo, rr.updates, cfg.publisher, dry_run=not publish, sleep=sleep)
    ok = set(rr.publish_report.published)
    pushed_skus = {u.sku for u in rr.updates}

    # If a new price could not be pushed and the old one is already stale, try to hide it,
    # so an out-of-date price is not left live just because publishing is failing.
    if publish and not rr.publish_report.fatal:
        failed_or_throttled = set(rr.publish_report.failed) | set(rr.publish_report.throttled)
        late = []
        for it in rr.items:
            r, d, ps = it["row"], it["decision"], it["ps"]
            ref = ps.last_ok or ps.first_seen
            if (
                d.action == "publish" and r.sku in failed_or_throttled and not ps.hidden
                and ref is not None and (today - ref).days >= cfg.pricing.stale_days
            ):
                late.append(Update(r.sku, r.wc_product_id, r.wc_variation_id, None, today.isoformat()))
                d.flags.append("stale_publish_failed")
        if late:
            rep2 = publish_updates(woo, late, cfg.publisher, dry_run=False, sleep=sleep)
            for sku in rep2.published:
                set_item(state, sku, hidden=True)
                rr.publish_report.failed.pop(sku, None)

    for it in rr.items:
        r, d, ps = it["row"], it["decision"], it["ps"]
        if r.sku in rr.publish_report.failed:
            d.flags.append("publish_failed")
        if r.sku in rr.publish_report.throttled:
            d.flags.append("publish_throttled")
        applied = (r.sku in ok) or (r.sku not in pushed_skus)
        if r.sku in pushed_skus and r.sku in ok:
            rr.changed.append((r.sku, ps.price, d.price, d.action))
        if not publish:
            continue
        record_seen(state, r.sku, it["results"], today)  # before "sources" is replaced below
        snapshot = {x.source: str(x.price) for x in it["results"] if x.usable}
        if snapshot:
            set_item(state, r.sku, sources=snapshot)
        set_item(state, r.sku, pending=d.pending if d.pending is not None else "")
        if d.action == "publish" and applied:
            set_item(state, r.sku, price=d.price, last_ok=today.isoformat(), hidden=False)
        elif d.action == "hide" and applied:
            set_item(state, r.sku, hidden=True)

    decisions = [it["decision"] for it in rr.items]
    flagged = [d for d in decisions if d.flags]
    not_refreshed = sum(
        1
        for it in rr.items
        if any(x.status == "not_refreshed" and x.source not in cfg.fetch.skip_sources for x in it["results"])
        and not any(x.usable for x in it["results"])
        and it["row"].sku not in seller_only and it["row"].sku not in brand_only
    )
    rr.stats = {
        "mode": "PUBLISH (live)" if publish else "DRY RUN (nothing changed)",
        "rows_total": len(rows),
        "rows_eligible": len(eligible),
        "rows_published": sum(d.action == "publish" for d in decisions),
        "rows_changed": len(rr.updates) if not publish else len(rr.changed),
        "rows_held": sum(d.action == "hold" for d in decisions),
        "rows_hidden": sum(d.action == "hide" for d in decisions),
        "rows_brand_mrp": brand_priced,
        "rows_flagged": len(flagged),
        "rows_not_refreshed": not_refreshed,
        "push_failed": len(rr.publish_report.failed),
        "push_throttled": len(rr.publish_report.throttled),
        "fatal": rr.publish_report.fatal,
        "runtime_min": round((now() - started) / 60, 1),
        "requests_per_host": dict(fetcher.request_log),
        "sources_stopped_after_blocks": dict(stopped),
    }
    return rr


def write_outputs(data_dir: Path, rr: RunResult, today: date, publish: bool, cfg: Config) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    flag_rows = report.build_flag_rows(rr.items)
    report.write_flags_csv(data_dir / "flags.csv", flag_rows)
    mode = rr.stats["mode"]
    issue = data_dir / "flags_issue.md"
    issue.unlink(missing_ok=True)  # never reuse yesterday's issue text
    if flag_rows or rr.stats.get("fatal"):  # no issue on a quiet day
        issue.write_text(
            report.build_issue_body(flag_rows, today.isoformat(), mode, rr.stats.get("fatal", "")),
            encoding="utf-8",
        )
    (data_dir / "summary.md").write_text(report.build_summary(rr.stats), encoding="utf-8")

    if publish:
        hist = data_dir / "history"
        hist.mkdir(parents=True, exist_ok=True)
        hist_file = hist / f"{today.isoformat()}.csv"
        existed = hist_file.exists()  # a second run on the same day appends instead of overwriting
        with open(hist_file, "a", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            if not existed:
                w.writerow(["sku", "old_price", "new_price", "action"])
            for sku, old, new, action in rr.changed:
                w.writerow([sku, old if old is not None else "", new if new is not None else "", action])
        rotate_history(hist, cfg.publisher.history_keep_days, today)
    else:
        with open(data_dir / "dryrun_plan.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            srcs = list(cfg.sources)
            w.writerow(["sku", "action", "new_price", "live_price", "spread_pct", "cheapest", "flags", "info",
                        "rule_action", "rule_price", "title"]
                       + [f"{s}_{k}" for s in srcs for k in ("status", "price")])
            for it in rr.items:
                d = it["decision"]
                by_src = {res.source: res for res in it["results"]}
                rp = it.get("rule_price")
                w.writerow([
                    d.sku, d.action, d.price if d.price is not None else "",
                    it["live_price"] if it["live_price"] is not None else "",
                    "" if d.spread_pct is None else f"{d.spread_pct:.2f}",
                    d.cheapest_source or "", ";".join(d.flags), ";".join(d.info),
                    it.get("rule_action", d.action), "" if rp is None else rp, it["row"].title,
                ] + [x for s in srcs for x in (
                    by_src[s].status if s in by_src else "",
                    "" if s not in by_src or by_src[s].price is None else by_src[s].price)])


def rotate_history(hist_dir: Path, keep_days: int, today: date) -> None:
    """Keep the last N daily files; fold older ones into history/monthly/YYYY-MM.csv."""
    monthly = hist_dir / "monthly"
    for f in sorted(hist_dir.glob("????-??-??.csv")):
        try:
            d = date.fromisoformat(f.stem)
        except ValueError:
            continue
        if (today - d).days <= keep_days:
            continue
        monthly.mkdir(exist_ok=True)
        target = monthly / f"{f.stem[:7]}.csv"
        with open(f, newline="", encoding="utf-8") as src:
            lines = list(csv.reader(src))
        if not lines:  # empty/corrupt daily file: just drop it
            f.unlink()
            continue
        new_file = not target.exists()
        with open(target, "a", newline="", encoding="utf-8") as out:
            w = csv.writer(out)
            if new_file:
                w.writerow(["date"] + lines[0])
            for rec in lines[1:]:
                w.writerow([f.stem] + rec)
        f.unlink()


def load_brand_prices(path: Path) -> dict:
    """{sku: {"mrp", "url", "date"}} written by tools/brand_prices.py; missing or broken = none."""
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("items", {})
    except (FileNotFoundError, ValueError, AttributeError):
        return {}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--catalogue", default="catalogue")
    ap.add_argument("--data", default="data")
    ap.add_argument("--publish", action="store_true", help="live run (default is dry-run)")
    ap.add_argument("--brand", action="append", help="limit to a brand (repeatable)")
    ap.add_argument("--limit", type=int, help="limit number of rows (testing)")
    ap.add_argument("--only-new", action="store_true", help="only rows the bot has never priced")
    ap.add_argument("--all-products", action="store_true", help="check every product, not today's share")
    ap.add_argument("--kept-only", action="store_true",
                    help="only products no site is asked about (re-judge kept prices; sends no requests)")
    ap.add_argument("--today", help="override date YYYY-MM-DD (testing)")
    ap.add_argument("--include-pending", action="store_true",
                    help="dry run only: also evaluate publish=pending_review rows (pilot)")
    args = ap.parse_args(argv)
    if args.include_pending and args.publish:
        print("ERROR: --include-pending cannot be used with --publish", file=sys.stderr)
        return 2

    try:
        cfg = load_config(args.config)
        cfg.fetch.require_contact_email()
        rows = load_catalogue(args.catalogue)
    except (ConfigError, CatalogueError, FileNotFoundError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    problems = validate(rows, cfg)
    if problems:
        print("Catalogue problems:\n  " + "\n  ".join(problems[:50]), file=sys.stderr)
        return 2

    today = date.fromisoformat(args.today) if args.today else datetime.now(ZoneInfo(cfg.timezone)).date()
    woo = None
    if args.publish:
        miss = [k for k in ("WC_URL", "WC_KEY", "WC_SECRET") if not os.environ.get(k)]
        if miss:
            print(f"ERROR: --publish needs env vars {miss}", file=sys.stderr)
            return 2
        woo = WooClient(os.environ["WC_URL"], os.environ["WC_KEY"], os.environ["WC_SECRET"])

    data_dir = Path(args.data)
    state = load_state(data_dir / "latest.json")
    brand_prices = load_brand_prices(data_dir / "brand_prices.json")
    fetcher = Fetcher(cfg.fetch)
    try:
        rr = run_sync(cfg, rows, state, fetcher, woo, today, args.publish, args.brand, args.limit,
                      include_pending=args.include_pending, only_new=args.only_new,
                      all_products=args.all_products, brand_prices=brand_prices,
                      kept_only=args.kept_only)
    finally:
        # Save state FIRST: it records what is already live. Losing it would make tomorrow's run
        # compare against old prices and old dates.
        if args.publish:
            save_state(data_dir / "latest.json", state, today)
    try:
        write_outputs(data_dir, rr, today, args.publish, cfg)
    except Exception as e:  # reports are secondary; never fail the run for them
        print(f"WARNING: could not write reports: {type(e).__name__}: {e}", file=sys.stderr)
    print(report.build_summary(rr.stats))
    return 3 if rr.stats.get("fatal") else 0


if __name__ == "__main__":
    sys.exit(main())
