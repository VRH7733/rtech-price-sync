"""End-to-end runs with fake marketplaces and a fake WooCommerce."""
import csv
import dataclasses
import json
from datetime import date, timedelta
from decimal import Decimal as D
from pathlib import Path

import html_samples as S
import pytest
from fakes import FakeWoo
from rtech_sync import run as runmod
from rtech_sync.config import load_config
from rtech_sync.fetcher import FetchResult
from rtech_sync.models import Row
from rtech_sync.state import get_price_state, save_state

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 10, 14)
NAME = "Polycab 1.5 sq mm FR PVC Insulated Wire, Red, 90 m"


@pytest.fixture
def cfg():
    c = load_config(ROOT / "config.yaml", env={"RTECH_CONTACT_EMAIL": "shop@example.com"})
    # pages in these tests say "Inclusive of all taxes", but make the assumption explicit too
    return c


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages  # url -> html | FetchResult
        self.request_log = {}
        self.calls = []

    def get(self, url, budget_key=""):
        self.calls.append(url)
        self.request_log[budget_key] = self.request_log.get(budget_key, 0) + 1
        p = self.pages.get(url)
        if p is None:
            return FetchResult(url, "error", detail="404")
        return p if isinstance(p, FetchResult) else FetchResult(url, "ok", 200, text=p)


def make_row(sku="PC-1", **kw):
    base = dict(
        sku=sku, brand="Polycab", title=NAME, variant_hint="1.5 sq mm; red", pack_size="90 m",
        publish="yes", wc_product_id=10, wc_variation_id=100,
        urls={"moglix": "https://www.moglix.com/p/a", "industrybuying": "https://www.industrybuying.com/p/b",
              "homerun": "https://home-run.co/products/c"},
    )
    base.update(kw)
    return Row(**base)


def pages(m, ib, hr):
    def pg(price):
        return None if price is None else S.jsonld_page(price=str(price), visible_price=f"₹{int(price):,}")
    out = {}
    for url, price in (("https://www.moglix.com/p/a", m), ("https://www.industrybuying.com/p/b", ib),
                       ("https://home-run.co/products/c", hr)):
        if price is not None:
            out[url] = pg(price)
    return out


def go(cfg, rows, state, fetcher, woo, publish, today=TODAY, **kw):
    return runmod.run_sync(cfg, rows, state, fetcher, woo, today, publish, sleep=lambda s: None, **kw)


def test_live_run_publishes_cheapest_and_updates_state(cfg, tmp_path):
    state = {"version": 1, "items": {}}
    woo = FakeWoo()
    rr = go(cfg, [make_row()], state, FakeFetcher(pages(1000, 1020, 1030)), woo, publish=True)
    d = rr.items[0]["decision"]
    assert d.action == "publish" and d.price == D(1000) and d.cheapest_source == "moglix"
    assert woo.calls[0][0] == "variations" and woo.calls[0][1] == 10
    assert woo.calls[0][2][0]["id"] == 100 and woo.calls[0][2][0]["regular_price"] == "1000"
    st = get_price_state(state, "PC-1")
    assert st.price == D(1000) and st.last_ok == TODAY and not st.hidden
    runmod.write_outputs(tmp_path, rr, TODAY, True, cfg)
    save_state(tmp_path / "latest.json", state, TODAY)
    assert (tmp_path / "history" / "2026-10-14.csv").read_text().count("PC-1") == 1
    assert json.loads((tmp_path / "latest.json").read_text())["items"]["PC-1"]["price"] == "1000"


def test_spread_over_5pct_holds_price_and_writes_flag(cfg, tmp_path):
    cfg = dataclasses.replace(cfg, pricing=dataclasses.replace(cfg.pricing, rule="spread", big_move_pct=D(15)))
    state = {"version": 1, "items": {"PC-1": {"price": "950", "last_ok": "2026-10-13", "hidden": False}}}
    woo = FakeWoo()
    rr = go(cfg, [make_row()], state, FakeFetcher(pages(1000, 1100, 1010)), woo, publish=True)
    d = rr.items[0]["decision"]
    assert d.action == "hold" and "spread_over_5pct" in d.flags
    assert woo.calls == []
    assert get_price_state(state, "PC-1").price == D(950)  # untouched
    runmod.write_outputs(tmp_path, rr, TODAY, True, cfg)
    flags = list(csv.DictReader(open(tmp_path / "flags.csv")))
    assert flags[0]["sku"] == "PC-1" and flags[0]["moglix"] == "1000" and flags[0]["industrybuying"] == "1100"
    assert "moglix.com/p/a" in (tmp_path / "flags_issue.md").read_text()


def test_dry_run_changes_nothing(cfg, tmp_path):
    state = {"version": 1, "items": {}}
    woo = FakeWoo()
    rr = go(cfg, [make_row()], state, FakeFetcher(pages(1000, 1020, 1030)), woo, publish=False)
    assert woo.calls == [] and state["items"] == {}
    runmod.write_outputs(tmp_path, rr, TODAY, False, cfg)
    assert (tmp_path / "dryrun_plan.csv").exists() and not (tmp_path / "history").exists()
    assert rr.stats["rows_changed"] == 1 and "DRY RUN" in rr.stats["mode"]


def test_unchanged_price_next_day_pushes_nothing_but_refreshes_date(cfg):
    state = {"version": 1, "items": {}}
    f = FakeFetcher(pages(1000, 1020, 1030))
    go(cfg, [make_row()], state, f, FakeWoo(), publish=True)
    woo2 = FakeWoo()
    go(cfg, [make_row()], state, f, woo2, publish=True, today=TODAY + timedelta(days=1))
    assert woo2.calls == []
    assert get_price_state(state, "PC-1").last_ok == TODAY + timedelta(days=1)


def test_price_change_pushes_only_changed_rows(cfg):
    state = {"version": 1, "items": {}}
    rows = [make_row("A", wc_variation_id=1), make_row("B", wc_variation_id=2)]
    f = FakeFetcher(pages(1000, 1020, 1030))
    go(cfg, rows, state, f, FakeWoo(), publish=True)
    f.pages = pages(1010, 1020, 1030)
    woo = FakeWoo()
    go(cfg, rows, state, f, woo, publish=True, today=TODAY + timedelta(days=1))
    assert len(woo.calls[0][2]) == 2  # both moved 1000 -> 1010
    f.pages = pages(1010, 1020, 1030)
    woo = FakeWoo()
    go(cfg, rows, state, f, woo, publish=True, today=TODAY + timedelta(days=2))
    assert woo.calls == []


def test_wrong_variant_page_is_excluded_not_averaged(cfg):
    bad = S.jsonld_page(name="Polycab 2.5 sq mm FR PVC Insulated Wire, Red, 90 m", price="1500", visible_price="₹1,500")
    p = pages(1000, 1020, None)
    p["https://home-run.co/products/c"] = bad
    rr = go(cfg, [make_row()], {"version": 1, "items": {}}, FakeFetcher(p), FakeWoo(), publish=False)
    d = rr.items[0]["decision"]
    assert d.action == "publish" and d.price == D(1000)
    assert "variant_unconfirmed:homerun" in d.flags


def test_tax_unknown_source_excluded_until_assumption_set(cfg):
    # config.yaml now sets incl_gst for every source (verified on real pages); the rule is about a
    # source with NO assumption, so remove Moglix's for this test
    srcs = dict(cfg.sources)
    srcs["moglix"] = dataclasses.replace(srcs["moglix"], assumed_tax_basis=None)
    cfg = dataclasses.replace(cfg, sources=srcs)
    pg = S.jsonld_page(price="1000", tax_text="", visible_price="₹1,000")
    p = {"https://www.moglix.com/p/a": pg, "https://www.industrybuying.com/p/b": S.jsonld_page(price="1010", visible_price="₹1,010")}
    rr = go(cfg, [make_row()], {"version": 1, "items": {}}, FakeFetcher(p), FakeWoo(), publish=False)
    assert "tax_unknown:moglix" in rr.items[0]["decision"].flags


def test_robots_blocked_source_is_info_and_remaining_sources_decide(cfg):
    p = pages(1000, None, 1010)
    p["https://www.industrybuying.com/p/b"] = FetchResult("u", "robots_blocked", detail="disallowed")
    rr = go(cfg, [make_row()], {"version": 1, "items": {}}, FakeFetcher(p), FakeWoo(), publish=False)
    d = rr.items[0]["decision"]
    assert d.action == "publish" and d.price == D(1000) and "robots_blocked:industrybuying" in d.info


def test_three_failed_days_hides_price_then_recovers(cfg):
    state = {"version": 1, "items": {}}
    go(cfg, [make_row()], state, FakeFetcher(pages(1000, 1010, 1020)), FakeWoo(), publish=True)
    dead = FakeFetcher({})
    for n in (1, 2):
        woo = FakeWoo()
        go(cfg, [make_row()], state, dead, woo, publish=True, today=TODAY + timedelta(days=n))
        assert woo.calls == []
    woo = FakeWoo()
    rr = go(cfg, [make_row()], state, dead, woo, publish=True, today=TODAY + timedelta(days=3))
    assert rr.items[0]["decision"].action == "hide"
    assert woo.calls[0][2][0]["regular_price"] == "" and get_price_state(state, "PC-1").hidden
    # idempotent next day
    woo = FakeWoo()
    go(cfg, [make_row()], state, dead, woo, publish=True, today=TODAY + timedelta(days=4))
    assert woo.calls == []
    # recovery
    woo = FakeWoo()
    go(cfg, [make_row()], state, FakeFetcher(pages(1000, 1010, 1020)), woo, publish=True, today=TODAY + timedelta(days=5))
    assert woo.calls[0][2][0]["regular_price"] == "1000" and not get_price_state(state, "PC-1").hidden


def test_failed_publish_does_not_update_state(cfg):
    state = {"version": 1, "items": {}}
    woo = FakeWoo([(200, {"update": [{"id": 100, "error": {"message": "nope"}}]})])
    rr = go(cfg, [make_row()], state, FakeFetcher(pages(1000, 1010, 1020)), woo, publish=True)
    assert get_price_state(state, "PC-1").price is None
    assert "publish_failed" in rr.items[0]["decision"].flags


def test_time_budget_exhausted_marks_not_refreshed_not_flagged(cfg):
    ticks = iter([0] + [10**9] * 100)
    state = {"version": 1, "items": {}}
    rr = go(cfg, [make_row()], state, FakeFetcher(pages(1000, 1010, 1020)), FakeWoo(), publish=False,
            now=lambda: next(ticks))
    d = rr.items[0]["decision"]
    assert d.action == "hold" and d.flags == [] and rr.stats["rows_not_refreshed"] == 1


def test_manual_price_published_without_fetching(cfg):
    no_fetch = dataclasses.replace(cfg, pricing=dataclasses.replace(cfg.pricing, fetch_for_manual_rows=False))
    f = FakeFetcher(pages(1000, 1010, 1020))
    woo = FakeWoo()
    rr = go(no_fetch, [make_row(manual_price=D("1234"))], {"version": 1, "items": {}}, f, woo, publish=True)
    assert f.calls == [] and woo.calls[0][2][0]["regular_price"] == "1234"


def test_manual_price_rows_are_fetched_and_flag_a_cheaper_market(cfg):
    assert cfg.pricing.outlier_ratio == 2
    assert cfg.pricing.fetch_for_manual_rows  # owner's STOP 2 decision: tell me when the market is cheaper
    f = FakeFetcher(pages(1000, 1010, 1020))
    woo = FakeWoo()
    rr = go(cfg, [make_row(manual_price=D("1234"))], {"version": 1, "items": {}}, f, woo, publish=True)
    assert len(f.calls) == 3 and woo.calls[0][2][0]["regular_price"] == "1234"
    assert rr.items[0]["decision"].flags == ["market_below_manual:moglix"]


def test_oldest_refreshed_rows_are_processed_first_and_limit_applies(cfg):
    state = {"version": 1, "items": {
        "A": {"price": "1", "last_ok": "2026-10-13"}, "B": {"price": "1", "last_ok": "2026-10-01"}}}
    rows = [make_row("A", wc_variation_id=1), make_row("B", wc_variation_id=2), make_row("C", wc_variation_id=3)]
    rr = go(cfg, rows, state, FakeFetcher({}), FakeWoo(), publish=False, limit=2)
    assert [it["row"].sku for it in rr.items] == ["C", "B"]  # never-refreshed first, then oldest


def test_row_without_wc_id_is_held_and_flagged(cfg):
    rr = go(cfg, [make_row(wc_product_id=None)], {"version": 1, "items": {}},
            FakeFetcher(pages(1000, 1010, 1020)), FakeWoo(), publish=True)
    d = rr.items[0]["decision"]
    assert d.action == "hold" and "no_wc_id" in d.flags


def test_history_rotation_folds_old_days_into_monthly(tmp_path):
    h = tmp_path / "history"
    h.mkdir()
    (h / "2026-08-01.csv").write_text("sku,old_price,new_price,action\nA,1,2,publish\n")
    (h / "2026-10-13.csv").write_text("sku,old_price,new_price,action\nB,1,2,publish\n")
    runmod.rotate_history(h, 30, date(2026, 10, 14))
    assert not (h / "2026-08-01.csv").exists() and (h / "2026-10-13.csv").exists()
    assert "2026-08-01,A,1,2,publish" in (h / "monthly" / "2026-08.csv").read_text()


# --- pilot dry runs over publish=pending_review rows (never live)
def test_pending_rows_are_skipped_by_default(cfg):
    rows = [make_row(publish="pending_review")]
    rr = go(cfg, rows, {"version": 1, "items": {}}, FakeFetcher(pages(1000, 1020, 1030)), FakeWoo(), publish=False)
    assert rr.items == []


def test_include_pending_evaluates_pending_rows_in_a_dry_run(cfg):
    rows = [make_row(publish="pending_review"), make_row(sku="PC-2", publish="no")]
    woo = FakeWoo()
    rr = go(cfg, rows, {"version": 1, "items": {}}, FakeFetcher(pages(1000, 1020, 1030)), woo,
            publish=False, include_pending=True)
    assert [i["row"].sku for i in rr.items] == ["PC-1"]
    assert rr.items[0]["decision"].price == D(1000)
    assert woo.calls == []


def test_include_pending_is_refused_for_live_runs(cfg):
    with pytest.raises(ValueError):
        go(cfg, [make_row(publish="pending_review")], {"version": 1, "items": {}},
           FakeFetcher(pages(1000, 1020, 1030)), FakeWoo(), publish=True, include_pending=True)
    assert runmod.main(["--include-pending", "--publish"]) == 2


def test_dryrun_plan_shows_rule_decision_and_each_source_for_rows_without_wc_id(cfg, tmp_path):
    rows = [make_row(publish="pending_review", wc_product_id=None, wc_variation_id=None)]
    rr = go(cfg, rows, {"version": 1, "items": {}}, FakeFetcher(pages(1000, 1020, None)), FakeWoo(),
            publish=False, include_pending=True)
    runmod.write_outputs(tmp_path, rr, TODAY, False, cfg)
    rec = list(csv.DictReader(open(tmp_path / "dryrun_plan.csv", encoding="utf-8")))[0]
    assert rec["action"] == "hold" and "no_wc_id" in rec["flags"]
    assert rec["rule_action"] == "publish" and rec["rule_price"] == "1000"
    assert rec["moglix_status"] == "ok" and rec["moglix_price"] == "1000"
    assert rec["industrybuying_price"] == "1020" and rec["homerun_status"] != "ok"


def test_only_new_prices_just_the_products_never_seen_before(cfg):
    state = {"version": 1, "items": {"OLD": {"first_seen": "2026-10-13", "price": "990"}}}
    rows = [make_row(sku="OLD"), make_row(sku="NEW", wc_product_id=11, wc_variation_id=101)]
    rr = go(cfg, rows, state, FakeFetcher(pages(1000, 1020, 1030)), FakeWoo(), publish=True, only_new=True)
    assert [it["row"].sku for it in rr.items] == ["NEW"]
    assert get_price_state(state, "OLD").price == D(990)


def test_seller_listing_only_row_is_not_fetched_and_shows_quote(cfg):
    ele = "https://www.industrybuying.com/cable-ties-legrand-ELE.CAB.1"
    state = {"version": 1, "items": {"SELL": {"first_seen": "2026-10-13", "price": "990"}}}
    rows = [make_row(sku="SELL", urls={"industrybuying": ele}),
            make_row(sku="PAIR", wc_product_id=11, wc_variation_id=101,
                     urls={"industrybuying": ele, "moglix": "https://www.moglix.com/p/a"})]
    f = FakeFetcher(pages(1000, None, None))
    woo = FakeWoo()
    rr = go(cfg, rows, state, f, woo, publish=True)
    assert f.calls.count(ele) == 1  # only for PAIR, which has a second site
    sell = next(it for it in rr.items if it["row"].sku == "SELL")["decision"]
    assert sell.action == "hide" and sell.flags == ["unconfirmed_listing:industrybuying"]
    assert get_price_state(state, "SELL").hidden
    assert rr.stats["rows_not_refreshed"] == 0
