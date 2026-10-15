"""Flags CSV, GitHub-issue body and run summary."""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

ISSUE_CHAR_LIMIT = 60000  # GitHub issue bodies are capped at 65,536 characters
MAX_DETAILED_ROWS = 120

REASON_HELP = {
    "spread_over_5pct": "Sources differ by 5% or more. Old price kept. Check the links, then type manual_price.",
    "single_source_jump": "Only one source worked and it moved more than 5% from the live price. Old price kept.",
    "single_source_no_baseline": "Only one source and no earlier price to compare with. Not published.",
    "below_cost_floor": "Computed price is below your cost_floor. Old price kept.",
    "big_move": "Price moved more than 15% vs the live price (published unless big_move_holds is true).",
    "stale": "No validated price for several days. Price hidden; shows Request price.",
    "no_sources": "No source gave a usable price today.",
    "no_urls": "Row is publish=yes but has no marketplace URL.",
    "variant_unconfirmed": "A page did not clearly match the variant (size/colour/length). Source excluded.",
    "pack_mismatch": "A page sells a different pack size. Source excluded.",
    "tax_unknown": "Page does not say whether GST is included. Source excluded.",
    "parse_failed": "Could not read a price from the page. Source excluded.",
    "outlier_ignored": "One site costs more than twice the cheapest other site (likely a listing error). That site was ignored.",
    "market_below_manual": "A marketplace is now cheaper than your manual_price. Your price was kept; check it.",
}


def _fmt(p) -> str:
    return "" if p is None else str(p)


def build_flag_rows(items: list) -> list:
    """items: list of dicts with keys row, decision, results."""
    out = []
    for it in items:
        d, row = it["decision"], it["row"]
        if not d.flags:
            continue
        prices = {r.source: r.price for r in it["results"]}
        urls = {r.source: r.url for r in it["results"]}
        out.append(
            {
                "sku": row.sku,
                "brand": row.brand,
                "title": row.title,
                "action": d.action,
                "flags": ";".join(d.flags),
                "info": ";".join(d.info),
                "spread_pct": "" if d.spread_pct is None else f"{d.spread_pct:.2f}",
                "live_price": _fmt(it.get("live_price")),
                "moglix": _fmt(prices.get("moglix")),
                "industrybuying": _fmt(prices.get("industrybuying")),
                "homerun": _fmt(prices.get("homerun")),
                "url_moglix": urls.get("moglix", ""),
                "url_industrybuying": urls.get("industrybuying", ""),
                "url_homerun": urls.get("homerun", ""),
            }
        )
    return out


def write_flags_csv(path: str | Path, flag_rows: list) -> None:
    cols = [
        "sku", "brand", "title", "action", "flags", "info", "spread_pct", "live_price",
        "moglix", "industrybuying", "homerun", "url_moglix", "url_industrybuying", "url_homerun",
    ]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(flag_rows)


def _link(label: str, url: str) -> str:
    return f"[{label}]({url})" if url else ""


def build_issue_body(flag_rows: list, today: str, mode: str, fatal: str = "") -> str:
    lines = [f"# Price flags {today}", "", f"Run mode: **{mode}**. {len(flag_rows)} item(s) need a look.", ""]
    if fatal:
        lines += [f"> **Problem during publishing:** {fatal}", ""]
    if not flag_rows:
        lines.append("Nothing flagged today.")
        return "\n".join(lines)

    reasons = Counter()
    for r in flag_rows:
        for f in r["flags"].split(";"):
            reasons[f.split(":")[0]] += 1
    lines += ["## By reason", "", "| Reason | Count | What it means |", "|---|---|---|"]
    for reason, n in reasons.most_common():
        lines.append(f"| `{reason}` | {n} | {REASON_HELP.get(reason, '')} |")
    brands = Counter(r["brand"] or "(none)" for r in flag_rows)
    lines += ["", "## By brand", "", ", ".join(f"{b}: {n}" for b, n in brands.most_common()), ""]

    detailed = sorted(flag_rows, key=lambda r: -(float(r["spread_pct"] or 0)))[:MAX_DETAILED_ROWS]
    lines += [
        "## Items (largest spread first)",
        "",
        "To resolve one: put your price in `manual_price` for that SKU in `catalogue/<brand>.csv`. "
        "It publishes on the next run. Clear the cell to go back to automatic pricing.",
        "",
        "| SKU | Item | Flags | Spread % | Live | Moglix | IndustryBuying | HomeRun | Links |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in detailed:
        links = " ".join(
            x
            for x in (
                _link("M", r["url_moglix"]),
                _link("IB", r["url_industrybuying"]),
                _link("HR", r["url_homerun"]),
            )
            if x
        )
        title = (r["title"] or "").replace("|", "/")[:60]
        lines.append(
            f"| {r['sku']} | {title} | {r['flags']} | {r['spread_pct']} | {r['live_price']} | "
            f"{r['moglix']} | {r['industrybuying']} | {r['homerun']} | {links} |"
        )
    if len(flag_rows) > len(detailed):
        lines += ["", f"_{len(flag_rows) - len(detailed)} more in `data/flags.csv`._"]
    body = "\n".join(lines)
    if len(body) > ISSUE_CHAR_LIMIT:
        body = body[:ISSUE_CHAR_LIMIT] + "\n\n_(truncated, see data/flags.csv)_"
    return body


def build_summary(stats: dict) -> str:
    keys = [
        ("mode", "Mode"),
        ("rows_total", "Rows in catalogue"),
        ("rows_eligible", "Rows eligible (priced, publish=yes)"),
        ("rows_published", "Prices set"),
        ("rows_changed", "Prices actually changed"),
        ("rows_held", "Held (old price kept)"),
        ("rows_hidden", "Hidden (stale)"),
        ("rows_flagged", "Flagged"),
        ("rows_not_refreshed", "Not refreshed (ran out of time/budget)"),
        ("push_failed", "Publish failures"),
        ("push_throttled", "Publish throttled/abandoned"),
        ("fatal", "Fatal issue"),
        ("runtime_min", "Runtime (minutes)"),
    ]
    lines = ["# Run summary", ""]
    for k, label in keys:
        if k in stats and stats[k] not in ("", None):
            lines.append(f"- {label}: **{stats[k]}**")
    reqs = stats.get("requests_per_host", {})
    if reqs:
        lines.append("- Requests per host: " + ", ".join(f"{h}: {n}" for h, n in sorted(reqs.items())))
    return "\n".join(lines) + "\n"
