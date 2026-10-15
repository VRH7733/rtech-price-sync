"""Randomised invariant checks on the decision engine (seeded, no extra dependencies)."""
import random
from datetime import date, timedelta
from decimal import Decimal as D

from rtech_sync.config import PricingCfg
from rtech_sync.decision import decide
from rtech_sync.models import PriceState, Row, SourceResult

TODAY = date(2026, 10, 14)
CFG = PricingCfg()
STATUSES = ["ok", "ok", "ok", "blocked", "robots_blocked", "error", "no_url", "variant_unconfirmed",
            "pack_mismatch", "tax_unknown", "out_of_stock", "not_refreshed", "parse_failed"]


def rand_case(rng):
    results = []
    for s in ("moglix", "industrybuying", "homerun"):
        st = rng.choice(STATUSES)
        price = D(rng.randint(50, 5000)) / D(rng.choice([1, 10, 100])) if st == "ok" else None
        results.append(SourceResult(s, st, price=price))
    last = rng.choice([None, D(rng.randint(50, 5000))])
    last_ok = rng.choice([None, TODAY, TODAY - timedelta(days=rng.randint(1, 10))])
    row = Row(sku="X", mode="priced", publish="yes", wc_product_id=1,
              markup_pct=rng.choice([None, D(0), D(5), D(12)]),
              cost_floor=rng.choice([None, None, D(rng.randint(50, 5000))]),
              manual_price=rng.choice([None, None, None, D(rng.randint(10, 9000))]))
    return row, results, PriceState(price=last, last_ok=last_ok, hidden=rng.random() < 0.2)


def test_invariants_hold_over_20000_random_cases():
    rng = random.Random(20261014)
    for _ in range(20000):
        row, results, st = rand_case(rng)
        d = decide(row, results, st, CFG, TODAY)
        usable = [r.price for r in results if r.usable]
        assert d.action in ("publish", "hold", "hide")
        if d.action == "publish":
            assert d.price is not None and d.price > 0 and d.refreshed
            if row.manual_price is not None:
                assert d.price == row.manual_price
            else:
                assert usable, "published without any usable source"
                lo = min(usable)
                if len(usable) >= 2:
                    spread = (max(usable) - lo) / lo * 100
                    assert spread < 5, (usable, d)
                assert d.price >= lo  # never below the cheapest source (rounded up, markup >= 0)
                assert d.price == d.price.to_integral_value()
                if row.cost_floor is not None:
                    assert d.price >= row.cost_floor
                if len(usable) == 1:
                    assert st.price is not None and abs(d.price - st.price) / st.price * 100 <= 5
        else:
            assert d.price is None and not d.refreshed
            if len(usable) >= 2 and row.manual_price is None:
                lo = min(usable)
                if (max(usable) - lo) / lo * 100 >= 5:
                    assert "spread_over_5pct" in d.flags
        if d.action == "hide":
            assert st.last_ok is not None and (TODAY - st.last_ok).days >= CFG.stale_days
        # a hold with an old validated price must never leave it live beyond stale_days
        if d.action == "hold" and st.last_ok is not None:
            assert (TODAY - st.last_ok).days < CFG.stale_days


def test_invariants_with_the_outlier_guard_on():
    cfg = PricingCfg(outlier_ratio=D(2))
    rng = random.Random(20261015)
    for _ in range(20000):
        row, results, st = rand_case(rng)
        d = decide(row, results, st, cfg, TODAY)
        usable = [r for r in results if r.usable]
        ignored = {f.split(":")[1] for f in d.flags if f.startswith("outlier_ignored:")}
        for r in usable:  # only a source over 2x the cheapest other one is ever ignored
            if r.source in ignored:
                assert r.price > 2 * min(o.price for o in usable if o is not r)
        trusted = [r.price for r in usable if r.source not in ignored]
        if usable:
            assert min(r.price for r in usable) in trusted  # the cheapest is never ignored
        if d.action == "publish" and row.manual_price is None:
            lo = min(trusted)
            if len(trusted) >= 2:
                assert (max(trusted) - lo) / lo * 100 < 5, (trusted, d)
            assert d.price >= lo
            if len(trusted) == 1:
                assert st.price is not None and abs(d.price - st.price) / st.price * 100 <= 5
        if d.action != "publish" and row.manual_price is None and len(trusted) >= 2:
            lo = min(trusted)
            if (max(trusted) - lo) / lo * 100 >= 5:
                assert "spread_over_5pct" in d.flags
