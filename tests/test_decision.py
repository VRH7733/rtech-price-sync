from datetime import date, timedelta
from decimal import Decimal as D

from rtech_sync.config import PricingCfg
from rtech_sync.decision import apply_markup, decide, spread_pct
from rtech_sync.models import PriceState, Row, SourceResult

TODAY = date(2026, 10, 14)
CFG = PricingCfg()


def row(**kw):
    base = dict(sku="S1", mode="priced", publish="yes", wc_product_id=1)
    base.update(kw)
    return Row(**base)


def ok(source, price):
    return SourceResult(source, "ok", price=D(str(price)), url=f"https://x/{source}")


def bad(source, status):
    return SourceResult(source, status, url=f"https://x/{source}")


def run(results, state=None, r=None, cfg=CFG):
    return decide(r or row(), results, state or PriceState(), cfg, TODAY)


# ---- the owner's core rule -------------------------------------------------
def test_under_5pct_publishes_the_cheapest():
    d = run([ok("moglix", 104), ok("industrybuying", 100), ok("homerun", 102)])
    assert d.action == "publish" and d.price == D(100) and d.cheapest_source == "industrybuying"
    assert d.flags == []


def test_exactly_5pct_is_flagged_not_published():
    d = run([ok("moglix", 100), ok("homerun", "105.00")], PriceState(price=D(99)))
    assert d.action == "hold" and "spread_over_5pct" in d.flags and d.price is None


def test_just_under_5pct_publishes():
    d = run([ok("moglix", "99.99"), ok("homerun", "104.98")])
    assert d.action == "publish" and d.price == D(100)  # ceil(99.99)


def test_outlier_among_three_flags_the_item():
    d = run([ok("moglix", 100), ok("industrybuying", 102), ok("homerun", 120)])
    assert d.action == "hold" and "spread_over_5pct" in d.flags
    assert d.spread_pct == D(20)


def test_spread_pct_helper():
    assert spread_pct([D(100), D(105)]) == D(5)


# ---- markup & rounding -----------------------------------------------------
def test_rounds_up_to_next_rupee_with_zero_markup():
    d = run([ok("moglix", "425.40"), ok("homerun", "426")])
    assert d.price == D(426)


def test_markup_applies_before_rounding():
    assert apply_markup(D("425.40"), D(10)) == D(468)  # 467.94 rounds up to 468


def test_markup_per_row_override():
    d = run([ok("moglix", 100), ok("homerun", 101)], r=row(markup_pct=D(10)))
    assert d.price == D(110)


# ---- single source ---------------------------------------------------------
def test_single_source_without_baseline_is_not_published():
    d = run([ok("moglix", 100), bad("homerun", "blocked")])
    assert d.action == "hold" and "single_source_no_baseline" in d.flags


def test_single_source_within_5pct_of_live_price_publishes():
    d = run([ok("moglix", 103), bad("homerun", "error")], PriceState(price=D(100), last_ok=TODAY))
    assert d.action == "publish" and d.price == D(103)


def test_single_source_jump_is_held():
    d = run([ok("moglix", 120)], PriceState(price=D(100), last_ok=TODAY))
    assert d.action == "hold" and "single_source_jump" in d.flags


# ---- manual price ----------------------------------------------------------
def test_manual_price_overrides_everything():
    d = run([ok("moglix", 100), ok("homerun", 200)], r=row(manual_price=D(150), cost_floor=D(999)))
    assert d.action == "publish" and d.price == D(150)
    # still published as typed; the owner is only told that a marketplace is cheaper (STOP 2)
    assert d.flags == ["market_below_manual:moglix"]
    d = run([ok("moglix", 160), ok("homerun", 200)], r=row(manual_price=D(150), cost_floor=D(999)))
    assert d.action == "publish" and d.price == D(150) and d.flags == []


# ---- guards ----------------------------------------------------------------
def test_below_cost_floor_holds_and_flags():
    d = run([ok("moglix", 90), ok("homerun", 91)], PriceState(price=D(95)), r=row(cost_floor=D(100)))
    assert d.action == "hold" and "below_cost_floor" in d.flags


def test_big_move_flags_but_still_publishes_by_default():
    d = run([ok("moglix", 130), ok("homerun", 131)], PriceState(price=D(100), last_ok=TODAY))
    assert d.action == "publish" and "big_move" in d.flags


def test_big_move_can_be_configured_to_hold():
    cfg = PricingCfg(big_move_holds=True)
    d = run([ok("moglix", 130), ok("homerun", 131)], PriceState(price=D(100), last_ok=TODAY), cfg=cfg)
    assert d.action == "hold" and "big_move" in d.flags


def test_15pct_exactly_is_not_a_big_move():
    d = run([ok("moglix", 115), ok("homerun", 116)], PriceState(price=D(100), last_ok=TODAY))
    assert "big_move" not in d.flags


# ---- stale guard -----------------------------------------------------------
def test_stale_after_3_days_hides_price():
    st = PriceState(price=D(100), last_ok=TODAY - timedelta(days=3))
    d = run([bad("moglix", "blocked"), bad("homerun", "error")], st)
    assert d.action == "hide" and "stale" in d.flags


def test_not_stale_at_2_days():
    st = PriceState(price=D(100), last_ok=TODAY - timedelta(days=2))
    d = run([bad("moglix", "blocked")], st)
    assert d.action == "hold"


def test_flagged_hold_also_goes_stale_so_old_prices_do_not_linger():
    st = PriceState(price=D(100), last_ok=TODAY - timedelta(days=4))
    d = run([ok("moglix", 100), ok("homerun", 120)], st)
    assert d.action == "hide" and "spread_over_5pct" in d.flags and "stale" in d.flags


def test_fresh_price_restores_a_hidden_row():
    st = PriceState(price=D(100), last_ok=TODAY - timedelta(days=9), hidden=True)
    d = run([ok("moglix", 100), ok("homerun", 101)], st)
    assert d.action == "publish" and d.refreshed


def test_never_published_row_is_never_hidden():
    d = run([bad("moglix", "blocked")], PriceState())
    assert d.action == "hold" and "stale" not in d.flags


# ---- source problems -------------------------------------------------------
def test_variant_problem_is_flagged_but_other_sources_still_publish():
    d = run([ok("moglix", 100), ok("homerun", 101), bad("industrybuying", "variant_unconfirmed")])
    assert d.action == "publish" and "variant_unconfirmed:industrybuying" in d.flags


def test_blocked_source_is_info_only():
    d = run([ok("moglix", 100), ok("homerun", 101), bad("industrybuying", "robots_blocked")])
    assert d.flags == [] and "robots_blocked:industrybuying" in d.info


def test_no_urls_flag():
    d = run([bad("moglix", "no_url"), bad("homerun", "no_url"), bad("industrybuying", "no_url")])
    assert "no_urls" in d.flags


def test_all_not_refreshed_is_not_a_flag():
    d = run([bad("moglix", "not_refreshed"), bad("homerun", "no_url")])
    assert d.flags == [] and d.action == "hold"


def test_no_sources_flag_when_all_failed():
    d = run([bad("moglix", "blocked"), bad("homerun", "error")])
    assert "no_sources" in d.flags


# ---- skipping --------------------------------------------------------------
def test_quote_and_pending_rows_are_skipped():
    assert run([ok("moglix", 1)], r=row(mode="quote")).action == "skip"
    assert run([ok("moglix", 1)], r=row(publish="pending_review")).action == "skip"
    assert run([ok("moglix", 1)], r=row(publish="no")).action == "skip"


# ---- outlier guard and manual-price alert (owner's STOP 2 decision, 15 Oct 2026) ---------------
OUT = PricingCfg(outlier_ratio=D(2))


def test_outlier_guard_is_off_by_default():
    d = run([ok("industrybuying", 15339), ok("homerun", 3089), ok("moglix", 3100)])
    assert d.action == "hold" and "spread_over_5pct" in d.flags
    assert not any(f.startswith("outlier_ignored") for f in d.flags)


def test_listing_over_twice_the_cheapest_other_is_ignored_and_flagged():
    # real case: IB lists the same 90 m coil at 15,339 while HomeRun sells it at 3,089
    d = run([ok("industrybuying", 15339), ok("homerun", 3089), ok("moglix", 3100)], cfg=OUT)
    assert "outlier_ignored:industrybuying" in d.flags
    assert d.action == "publish" and d.price == D(3089) and d.spread_pct < 5


def test_the_5pct_rule_still_applies_to_the_remaining_sources():
    d = run([ok("industrybuying", 15339), ok("homerun", 3089), ok("moglix", 4465)], cfg=OUT)
    assert "outlier_ignored:industrybuying" in d.flags
    assert d.action == "hold" and "spread_over_5pct" in d.flags and d.price is None


def test_dropping_an_outlier_from_two_sources_leaves_a_single_source_hold():
    d = run([ok("industrybuying", 15339), ok("homerun", 3089)], cfg=OUT)
    assert d.flags == ["outlier_ignored:industrybuying", "single_source_no_baseline"]
    assert d.action == "hold"


def test_exactly_twice_is_not_an_outlier():
    d = run([ok("industrybuying", 200), ok("homerun", 100)], cfg=OUT)
    assert not any(f.startswith("outlier_ignored") for f in d.flags)
    assert "spread_over_5pct" in d.flags and d.action == "hold"


def test_the_cheapest_source_is_never_ignored():
    # a suspiciously LOW price is not dropped by this guard; the 5% rule holds it instead
    d = run([ok("industrybuying", 1000), ok("homerun", 3000), ok("moglix", 3050)], cfg=OUT)
    assert "outlier_ignored:homerun" in d.flags and "outlier_ignored:moglix" in d.flags
    assert "single_source_no_baseline" in d.flags and d.action == "hold"


def test_manual_price_is_kept_and_flagged_when_a_marketplace_is_cheaper():
    d = run([ok("industrybuying", 2900), ok("homerun", 3089)], r=row(manual_price=D(3000)), cfg=OUT)
    assert d.action == "publish" and d.price == D(3000)
    assert d.flags == ["market_below_manual:industrybuying"]


def test_manual_price_alert_ignores_outlier_listings_and_quiet_when_cheaper():
    d = run([ok("industrybuying", 900), ok("homerun", 3089), ok("moglix", 3100)],
            r=row(manual_price=D(3000)), cfg=OUT)
    # 900 is the cheapest, so it is never ignored: the owner is told about it
    assert d.flags == ["market_below_manual:industrybuying"]
    d = run([ok("homerun", 3089)], r=row(manual_price=D(3000)), cfg=OUT)
    assert d.action == "publish" and d.price == D(3000) and d.flags == []


# ---- the owner's go-live rule: cheapest of the three (15 Oct 2026) ------------------------------
CH = PricingCfg(rule="cheapest", outlier_ratio=D(2), big_move_pct=D(40))


def test_cheapest_publishes_the_cheapest_whatever_the_spread():
    d = run([ok("moglix", 4465), ok("homerun", 3089)], cfg=CH)
    assert d.action == "publish" and d.price == D(3089) and d.cheapest_source == "homerun"
    assert d.spread_pct > 40 and d.flags == []


def test_cheapest_publishes_a_single_source_without_a_baseline():
    d = run([ok("industrybuying", 9439), bad("moglix", "out_of_stock")], cfg=CH)
    assert d.action == "publish" and d.price == D(9439)


def test_cheapest_ignores_a_listing_over_twice_the_others():
    d = run([ok("industrybuying", 15339), ok("homerun", 3089)], cfg=CH)
    assert d.price == D(3089) and "outlier_ignored:industrybuying" in d.flags


def test_cheapest_ignores_a_price_below_half_of_two_agreeing_sites():
    d = run([ok("industrybuying", 900), ok("homerun", 3089), ok("moglix", 3100)], cfg=CH)
    assert "low_outlier_ignored:industrybuying" in d.flags and d.price == D(3089)


def test_cheapest_holds_a_big_move_one_day_then_publishes_when_it_repeats():
    d = run([ok("homerun", 1500)], PriceState(price=D(3000), last_ok=TODAY), cfg=CH)
    assert d.action == "hold" and "big_move_held" in d.flags and d.pending == D(1500)
    d = run([ok("homerun", 1510)], PriceState(price=D(3000), last_ok=TODAY, pending=D(1500)), cfg=CH)
    assert d.action == "publish" and d.price == D(1510) and "big_move_confirmed" in d.info


def test_cheapest_move_under_40pct_publishes_at_once():
    d = run([ok("homerun", 2000)], PriceState(price=D(3000), last_ok=TODAY), cfg=CH)
    assert d.action == "publish" and d.price == D(2000)


def test_cheapest_with_no_price_keeps_the_old_price_then_becomes_a_quote():
    st = PriceState(price=D(3000), last_ok=TODAY - timedelta(days=1))
    d = run([bad("homerun", "out_of_stock")], st, cfg=CH)
    assert d.action == "hold" and d.price is None
    st = PriceState(price=D(3000), last_ok=TODAY - timedelta(days=3))
    d = run([bad("homerun", "out_of_stock")], st, cfg=CH)
    assert d.action == "hide"


def test_cheapest_still_respects_cost_floor_and_manual_price():
    d = run([ok("homerun", 90)], r=row(cost_floor=D(100)), cfg=CH)
    assert d.action == "hold" and "below_cost_floor" in d.flags
    d = run([ok("homerun", 90)], r=row(manual_price=D(150)), cfg=CH)
    assert d.action == "publish" and d.price == D(150)
