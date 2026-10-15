"""Daily run: fetch -> evaluate -> decide -> publish -> report.

    PYTHONPATH=src python -m rtech_sync.run                 # DRY RUN (default, changes nothing)
    PYTHONPATH=src python -m rtech_sync.run --publish       # live: updates WooCommerce
"""
from __future__ import annotations

import argparse
import dataclasses
import csv
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from . import report
from .catalogue import CatalogueError, load_catalogue, validate
from .config import Config, ConfigError, load_config
from .siblings import apply_sibling_guard
from .decision import decide
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


def _fetch_all(tasks: list, fetcher: Fetcher, deadline: float, now: Callable) -> dict:
    """tasks: (row, source, url). One worker per host so per-host pacing is never exceeded."""
    by_source: dict = defaultdict(list)
    for t in tasks:
        by_source[t[1]].append(t)
    results: dict = {}

    def worker(source: str):
        for row, src, url in by_source[source]:
            if now() > deadline:
                return
            results[(row.sku, src)] = fetcher.get(url, budget_key=src)

    if by_source:
        with ThreadPoolExecutor(max_workers=len(by_source)) as ex:
            list(ex.map(worker, list(by_source)))
    return results


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
) -> RunResult:
    started = now()
    deadline = started + cfg.fetch.max_runtime_minutes * 60
    rr = RunResult()

    if include_pending and publish:
        raise ValueError("include_pending is for dry runs only")
    ok_publish = ("yes", "pending_review") if include_pending else ("yes",)
    eligible = [r for r in rows if r.mode == "priced" and r.publish in ok_publish]
    if only_brands:
        wanted = {b.lower() for b in only_brands}
        eligible = [r for r in eligible if r.brand.lower() in wanted]
    # oldest-validated first, so a time/budget shortfall rotates fairly across days
    far_past = date(1970, 1, 1)
    eligible.sort(key=lambda r: (get_price_state(state, r.sku).last_ok or far_past, r.sku))
    if limit:
        eligible = eligible[:limit]

    tasks = []
    for r in eligible:
        if r.manual_price is not None and not cfg.pricing.fetch_for_manual_rows:
            continue
        for s in cfg.sources:
            if s in r.urls:
                tasks.append((r, s, r.urls[s]))
    fetched = _fetch_all(tasks, fetcher, deadline, now)

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
        # pilot dry run: judge a pending row as if it were approved (nothing is published)
        as_row = dataclasses.replace(r, publish="yes") if include_pending and r.publish == "pending_review" else r
        d = decide(as_row, results, ps, cfg.pricing, today)
        if internal_error:
            d.flags.append("internal_error")
        rr.items.append({"row": r, "decision": d, "results": results, "live_price": ps.price, "ps": ps})
        if publish and ps.first_seen is None:
            set_item(state, r.sku, first_seen=today.isoformat())

    if cfg.pricing.rule == "cheapest":
        apply_sibling_guard(rr.items, cfg.pricing.sibling_ratio)

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
        if any(x.status == "not_refreshed" for x in it["results"])
        and not any(x.usable for x in it["results"])
    )
    rr.stats = {
        "mode": "PUBLISH (live)" if publish else "DRY RUN (nothing changed)",
        "rows_total": len(rows),
        "rows_eligible": len(eligible),
        "rows_published": sum(d.action == "publish" for d in decisions),
        "rows_changed": len(rr.updates) if not publish else len(rr.changed),
        "rows_held": sum(d.action == "hold" for d in decisions),
        "rows_hidden": sum(d.action == "hide" for d in decisions),
        "rows_flagged": len(flagged),
        "rows_not_refreshed": not_refreshed,
        "push_failed": len(rr.publish_report.failed),
        "push_throttled": len(rr.publish_report.throttled),
        "fatal": rr.publish_report.fatal,
        "runtime_min": round((now() - started) / 60, 1),
        "requests_per_host": dict(fetcher.request_log),
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--catalogue", default="catalogue")
    ap.add_argument("--data", default="data")
    ap.add_argument("--publish", action="store_true", help="live run (default is dry-run)")
    ap.add_argument("--brand", action="append", help="limit to a brand (repeatable)")
    ap.add_argument("--limit", type=int, help="limit number of rows (testing)")
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
    fetcher = Fetcher(cfg.fetch)
    try:
        rr = run_sync(cfg, rows, state, fetcher, woo, today, args.publish, args.brand, args.limit,
                      include_pending=args.include_pending)
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
