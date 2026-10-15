"""The price decision engine. Pure functions, no I/O.

Rules (set by the shop owner):
  * 2+ usable sources, spread < 5%  -> publish the CHEAPEST source price (+ markup, default 0%)
  * 2+ usable sources, spread >= 5% -> HOLD previous price and FLAG ("spread_over_5pct")
  * exactly 1 usable source         -> publish only if within 5% of last published price
  * manual_price set                -> publish it, skip all auto logic
  * below cost_floor                -> hold and flag
  * move > 15% vs last published    -> flag "big_move" (hold only if configured)
  * no validated price for stale_days -> hide the price ("stale")
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_CEILING, Decimal
from typing import Optional

from .config import PricingCfg
from .models import ATTENTION_STATUSES, INFO_STATUSES, PriceState, Row

HUNDRED = Decimal(100)


@dataclass
class Decision:
    sku: str
    action: str  # publish | hold | hide | skip
    price: Optional[Decimal] = None
    flags: list = field(default_factory=list)  # needs the owner's attention
    info: list = field(default_factory=list)  # FYI only
    spread_pct: Optional[Decimal] = None
    cheapest_source: Optional[str] = None
    refreshed: bool = False  # True => price validated this run (updates last_ok)
    note: str = ""


def round_up_rupee(x: Decimal) -> Decimal:
    return x.to_integral_value(rounding=ROUND_CEILING)


def apply_markup(base: Decimal, markup_pct: Decimal) -> Decimal:
    return round_up_rupee(base * (Decimal(1) + markup_pct / HUNDRED))


def pct_change(new: Decimal, old: Decimal) -> Decimal:
    if old <= 0:  # no usable baseline: treat as an infinite move so callers stay conservative
        return Decimal(10) ** 9
    return abs(new - old) / old * HUNDRED


def spread_pct(prices: list) -> Decimal:
    lo, hi = min(prices), max(prices)
    return (hi - lo) / lo * HUNDRED


def decide(
    row: Row,
    results: list,
    state: PriceState,
    cfg: PricingCfg,
    today: date,
) -> Decision:
    if row.mode != "priced" or row.publish != "yes":
        return Decision(sku=row.sku, action="skip", note=f"mode={row.mode} publish={row.publish}")

    # --- manual override -------------------------------------------------
    if row.manual_price is not None:
        return Decision(
            sku=row.sku,
            action="publish",
            price=row.manual_price,
            refreshed=True,
            note="manual_price",
        )

    d = Decision(sku=row.sku, action="hold")

    # --- classify source problems ---------------------------------------
    for r in results:
        if r.status in ATTENTION_STATUSES:
            d.flags.append(f"{r.status}:{r.source}")
        elif r.status in INFO_STATUSES:
            d.info.append(f"{r.status}:{r.source}")

    usable = [r for r in results if r.usable]
    markup = row.markup_pct if row.markup_pct is not None else cfg.default_markup_pct
    candidate: Optional[Decimal] = None

    if not usable:
        statuses = {r.status for r in results}
        if statuses <= {"no_url"}:
            d.flags.append("no_urls")
        elif statuses <= {"no_url", "not_refreshed"}:
            pass  # ran out of time/budget: informational, reported in the run summary
        else:
            d.flags.append("no_sources")
    else:
        cheapest = min(usable, key=lambda r: r.price)
        d.cheapest_source = cheapest.source
        base = cheapest.price
        if len(usable) >= 2:
            d.spread_pct = spread_pct([r.price for r in usable])
            if d.spread_pct >= cfg.spread_flag_pct:
                d.flags.append("spread_over_5pct")
            else:
                candidate = apply_markup(base, markup)
        else:
            c = apply_markup(base, markup)
            if state.price is None or state.price <= 0:
                d.flags.append("single_source_no_baseline")
            elif pct_change(c, state.price) < cfg.single_source_max_move_pct:
                candidate = c
            else:
                d.flags.append("single_source_jump")

    # --- guards on the candidate price ----------------------------------
    if candidate is not None:
        if row.cost_floor is not None and candidate < row.cost_floor:
            d.flags.append("below_cost_floor")
            candidate = None
        elif state.price is not None and state.price > 0:
            if pct_change(candidate, state.price) > cfg.big_move_pct:
                d.flags.append("big_move")
                if cfg.big_move_holds:
                    candidate = None

    if candidate is not None:
        d.action = "publish"
        d.price = candidate
        d.refreshed = True
        return d

    # --- stale guard: never leave an old price on the live site ---------
    ref = state.last_ok or state.first_seen  # rows never validated also go stale (legacy prices)
    if ref is not None and (today - ref).days >= cfg.stale_days:
        d.action = "hide"
        d.flags.append("stale")
    return d
