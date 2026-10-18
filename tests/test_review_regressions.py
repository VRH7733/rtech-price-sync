"""Regression tests for bugs found by the independent review (14 Oct 2026)."""
import dataclasses
import json
from datetime import date, timedelta
from decimal import Decimal as D
from pathlib import Path

import html_samples as S
import pytest
from fakes import FakeClock, FakeResp, FakeSession, FakeWoo
from rtech_sync import run as runmod
from rtech_sync.catalogue import validate
from rtech_sync.config import FetchCfg, PricingCfg, PublisherCfg, load_config
from rtech_sync.decision import decide, pct_change
from rtech_sync.fetcher import FetchResult, Fetcher, HostRateLimiter
from rtech_sync.models import PriceState, Row, SourceResult
from rtech_sync.normalise import check_variant, normalise_text
from rtech_sync.parsers import parse_product_page, to_decimal
from rtech_sync.pipeline import evaluate_source
from rtech_sync.publisher import Update, build_payload, publish_updates
from rtech_sync.robots import RobotsRules
from rtech_sync.state import get_price_state
from rtech_sync.urlcheck import is_search_url

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 10, 14)
CFG = load_config(ROOT / "config.yaml", env={"RTECH_CONTACT_EMAIL": "shop@example.com"})
# day-by-day profile (check every product daily, hide after 3 missed days); see test_run_e2e
CFG = dataclasses.replace(CFG, fetch=dataclasses.replace(CFG.fetch, check_every_days=1, skip_sources=()),
                          pricing=dataclasses.replace(CFG.pricing, stale_days=3, default_markup_pct=D(0)))
# the earlier 5%-agreement rule, still supported (config pricing.rule: spread)
SPREAD = dataclasses.replace(CFG.pricing, rule="spread", big_move_pct=D(15))


def row(**kw):
    base = dict(sku="S1", mode="priced", publish="yes", wc_product_id=1, wc_variation_id=11,
                variant_hint="1.5 sq mm; red", pack_size="90 m",
                urls={"moglix": "https://www.moglix.com/p"})
    base.update(kw)
    return Row(**base)


def ev(html, source="moglix"):
    return evaluate_source(row(), source, FetchResult("u", "ok", 200, text=html), CFG)


# ---- 1. wrong Product node ------------------------------------------------------------------
def test_two_products_in_jsonld_graph_are_refused_not_picked_by_order():
    graph = {"@graph": [
        {"@type": "Product", "name": "Polycab 1.5 sq mm Red 90 m", "offers": {"@type": "Offer", "price": "1000"}},
        {"@type": "Product", "name": "Polycab 4 sq mm Red 90 m", "offers": {"@type": "Offer", "price": "3000"}}]}
    html = ('<html><body><h1>Polycab 1.5 sq mm Red 90 m</h1>₹1,000 Inclusive of all taxes ₹3,000'
            f'<script type="application/ld+json">{json.dumps(graph)}</script></body></html>')
    assert ev(html).status == "variant_unconfirmed"


def test_single_product_still_works_in_document_order():
    assert ev(S.jsonld_page()).status == "ok"


# ---- 2. visible price guard -----------------------------------------------------------------
def test_jsonld_price_not_shown_on_page_is_rejected():
    html = S.jsonld_page(price="100000", visible_price="Rs 1,000")
    assert ev(html).status == "parse_failed"


def test_meta_price_not_shown_on_page_is_rejected():
    html = S.meta_page(price="999999")
    assert ev(html).status == "parse_failed"


# ---- 3. redirects ---------------------------------------------------------------------------
H = "https://home-run.co"


def fetcher_with(routes, robots="User-agent: *\nDisallow: /secret\nDisallow: /search\n"):
    clock = FakeClock()
    sess = FakeSession({f"{H}/robots.txt": FakeResp(200, robots), **routes})
    cfg = FetchCfg(min_delay_seconds=3, contact_email="shop@example.com")
    return Fetcher(cfg, session=sess, limiter=HostRateLimiter(3, clock.time, clock.sleep), sleep=clock.sleep), sess, clock


def test_redirect_to_search_page_is_refused():
    f, sess, _ = fetcher_with({f"{H}/p/old": FakeResp(302, headers={"Location": "/search?q=wire"})})
    r = f.get(f"{H}/p/old")
    assert r.status == "error" and "search" in r.detail and f"{H}/search?q=wire" not in sess.calls


def test_redirect_into_robots_disallowed_path_is_not_fetched():
    f, sess, _ = fetcher_with({f"{H}/p/old": FakeResp(301, headers={"Location": "/secret/x"}),
                               f"{H}/secret/x": FakeResp(200, "secret")})
    r = f.get(f"{H}/p/old")
    assert r.status == "robots_blocked" and f"{H}/secret/x" not in sess.calls


def test_redirect_off_site_is_refused():
    f, sess, _ = fetcher_with({f"{H}/p/old": FakeResp(302, headers={"Location": "https://evil.example/x"})})
    assert f.get(f"{H}/p/old").status == "error"
    assert "https://evil.example/x" not in sess.calls


def test_redirect_hops_are_rate_limited_and_followed():
    f, sess, clock = fetcher_with({f"{H}/p/a": FakeResp(301, headers={"Location": "/p/b"}),
                                   f"{H}/p/b": FakeResp(200, "final")})
    r = f.get(f"{H}/p/a")
    assert r.status == "ok" and r.text == "final" and r.final_url == f"{H}/p/b"
    assert sum(clock.sleeps) >= 6  # robots, hop 1, hop 2 each >= 3 s apart


def test_redirect_loop_is_stopped():
    f, _, _ = fetcher_with({f"{H}/p/a": FakeResp(302, headers={"Location": "/p/a"})})
    assert f.get(f"{H}/p/a").detail == "too many redirects"


def test_www_and_bare_host_share_a_rate_limit_slot():
    clock = FakeClock()
    lim = HostRateLimiter(3, clock.time, clock.sleep)
    lim.wait("www.example.com")
    lim.wait("example.com")
    assert clock.sleeps == [3]


def test_robots_429_means_do_not_fetch():
    clock = FakeClock()
    sess = FakeSession({f"{H}/robots.txt": FakeResp(429), f"{H}/p": FakeResp(200, "x")})
    f = Fetcher(FetchCfg(contact_email="a@b.c"), session=sess,
                limiter=HostRateLimiter(3, clock.time, clock.sleep), sleep=clock.sleep)
    assert f.get(f"{H}/p").status == "robots_blocked" and f"{H}/p" not in sess.calls


def test_robots_bom_is_stripped():
    r = RobotsRules("﻿User-agent: *\nDisallow: /p/")
    assert not r.allowed("https://x.com/p/1")


def test_robots_bom_bytes_decoded_by_fetcher():
    clock = FakeClock()
    body = FakeResp(200, "")
    body.content = "﻿User-agent: *\nDisallow: /p/\n".encode("utf-8")
    sess = FakeSession({f"{H}/robots.txt": body, f"{H}/p/1": FakeResp(200, "x")})
    f = Fetcher(FetchCfg(contact_email="a@b.c"), session=sess,
                limiter=HostRateLimiter(3, clock.time, clock.sleep), sleep=clock.sleep)
    assert f.get(f"{H}/p/1").status == "robots_blocked"


def test_robots_agent_group_needs_exact_token_not_substring():
    r = RobotsRules("User-agent: rtech\nDisallow: /\n\nUser-agent: *\nAllow: /\n")
    assert r.allowed("https://x.com/a")


def test_robots_percent_encoding_normalised():
    assert not RobotsRules("User-agent: *\nDisallow: /caf%C3%A9\n").allowed("https://x.com/café")
    assert not RobotsRules("User-agent: *\nDisallow: /café\n").allowed("https://x.com/caf%C3%A9")


# ---- 5. timing -----------------------------------------------------------------------------
def test_fetch_deadline_leaves_room_to_publish_inside_the_job_cap():
    assert CFG.fetch.max_runtime_minutes <= 300


# ---- 6. state safety and isolation -----------------------------------------------------------
class OneFetcher:
    request_log = {}

    def get(self, url, budget_key=""):
        return FetchResult(url, "ok", 200, text=S.jsonld_page(price="1000", visible_price="₹1,000"))


def test_one_row_crashing_does_not_abort_the_run(monkeypatch):
    real = runmod.evaluate_source

    def boom(r, s, fr, cfg):
        if r.sku == "BAD":
            raise ValueError("boom")
        return real(r, s, fr, cfg)

    monkeypatch.setattr(runmod, "evaluate_source", boom)
    rows = [row(sku="BAD", wc_variation_id=1, urls={"moglix": "https://www.moglix.com/a"}),
            row(sku="OK", wc_variation_id=2, urls={"moglix": "https://www.moglix.com/b"})]
    state = {"version": 1, "items": {"OK": {"price": "1000", "last_ok": TODAY.isoformat()}}}
    rr = runmod.run_sync(CFG, rows, state, OneFetcher(), FakeWoo(), TODAY, False, sleep=lambda s: None)
    by = {it["row"].sku: it["decision"] for it in rr.items}
    assert "internal_error" in by["BAD"].flags and by["OK"].action == "publish"


def test_nan_price_in_page_data_does_not_crash():
    ld = '{"@type":"Product","name":"x","offers":{"@type":"Offer","price":NaN}}'
    html = f'<html><body><h1>x</h1><script type="application/ld+json">{ld}</script></body></html>'
    assert parse_product_page(html, "u").price is None
    assert to_decimal(float("nan")) is None and to_decimal(float("inf")) is None


def test_state_is_saved_even_if_report_writing_fails(tmp_path, monkeypatch):
    from rtech_sync.models import CATALOGUE_COLUMNS
    cat = tmp_path / "cat"
    cat.mkdir()
    b = {c: "" for c in CATALOGUE_COLUMNS}
    b.update(sku="S1", wc_product_id="1", wc_variation_id="11", brand="Polycab", mode="priced", publish="yes",
             variant_hint="1.5 sq mm; red", pack_size="90 m", url_moglix="https://www.moglix.com/a",
             url_homerun="https://home-run.co/products/x")
    (cat / "p.csv").write_text(",".join(CATALOGUE_COLUMNS) + "\n" + ",".join(f'"{b[c]}"' for c in CATALOGUE_COLUMNS) + "\n")
    monkeypatch.setenv("RTECH_CONTACT_EMAIL", "shop@example.com")
    monkeypatch.setenv("WC_URL", "https://x.test")
    monkeypatch.setenv("WC_KEY", "k")
    monkeypatch.setenv("WC_SECRET", "s")
    monkeypatch.setattr(runmod, "Fetcher", lambda cfg: OneFetcher())
    monkeypatch.setattr(runmod, "WooClient", lambda *a, **k: FakeWoo())
    monkeypatch.setattr(runmod, "write_outputs", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    data = tmp_path / "data"
    code = runmod.main(["--config", str(ROOT / "config.yaml"), "--catalogue", str(cat), "--data", str(data),
                        "--publish", "--today", "2026-10-14"])
    assert code == 0
    assert json.loads((data / "latest.json").read_text())["items"]["S1"]["price"] == "990"  # live -1%


def test_rotate_history_survives_empty_old_file(tmp_path):
    h = tmp_path / "history"
    h.mkdir()
    (h / "2026-08-01.csv").write_text("")
    runmod.rotate_history(h, 30, TODAY)
    assert not (h / "2026-08-01.csv").exists()


def test_second_run_same_day_appends_history(tmp_path):
    from test_run_e2e import FakeFetcher, make_row, pages
    state = {"version": 1, "items": {}}
    rr = runmod.run_sync(CFG, [make_row()], state, FakeFetcher(pages(1000, 1010, 1020)), FakeWoo(), TODAY, True,
                         sleep=lambda s: None)
    runmod.write_outputs(tmp_path, rr, TODAY, True, CFG)
    runmod.write_outputs(tmp_path, rr, TODAY, True, CFG)
    text = (tmp_path / "history" / "2026-10-14.csv").read_text()
    assert text.count("sku,old_price") == 1 and text.count("PC-1") == 2


def test_no_issue_file_on_a_quiet_day_and_stale_one_is_removed(tmp_path):
    from test_run_e2e import FakeFetcher, make_row, pages
    (tmp_path / "flags_issue.md").write_text("yesterday")
    rr = runmod.run_sync(CFG, [make_row()], {"version": 1, "items": {}}, FakeFetcher(pages(1000, 1010, 1020)),
                         FakeWoo(), TODAY, False, sleep=lambda s: None)
    runmod.write_outputs(tmp_path, rr, TODAY, False, CFG)
    assert not (tmp_path / "flags_issue.md").exists()


# ---- 7. publisher on non-batch answers ------------------------------------------------------
class WafWoo(FakeWoo):
    def _respond(self, items):
        return 200, {}  # e.g. maintenance/WAF page that is not JSON


def test_200_without_update_list_counts_as_failure_and_stops():
    cfg = PublisherCfg(batch_size=25, stop_after_consecutive_failures=2)
    ups = [Update(f"S{i}", 10, 100 + i, D(5), "d") for i in range(200)]
    woo = WafWoo()
    rep = publish_updates(woo, ups, cfg, dry_run=False, sleep=lambda s: None)
    assert len(woo.calls) == 2 and rep.fatal and not rep.published


def test_json_list_answer_does_not_crash():
    class ListWoo(FakeWoo):
        def _respond(self, items):
            return 200, [1, 2]
    rep = publish_updates(ListWoo(), [Update("S", 1, None, D(5), "d")], PublisherCfg(), dry_run=False,
                          sleep=lambda s: None)
    assert "S" in rep.failed


# ---- 8. zero prices -------------------------------------------------------------------------
def test_manual_price_zero_is_rejected_by_validation():
    problems = validate([row(manual_price=D(0))], CFG)
    assert any("manual_price must be above 0" in p for p in problems)


def test_zero_baseline_does_not_crash_single_source():
    d = decide(row(), [SourceResult("moglix", "ok", price=D(100))], PriceState(price=D(0)), SPREAD, TODAY)
    assert "single_source_no_baseline" in d.flags and pct_change(D(1), D(0)) > 1000
    d = decide(row(), [SourceResult("moglix", "ok", price=D(100))], PriceState(price=D(0)), CFG.pricing, TODAY)
    assert d.action == "publish" and d.price == D(100)  # cheapest rule: a zero baseline is no baseline


# ---- 9. old prices must not stay live ----------------------------------------------------------
def test_never_validated_row_is_hidden_after_stale_days():
    st = PriceState(price=None, last_ok=None, first_seen=TODAY - timedelta(days=3))
    d = decide(row(), [SourceResult("moglix", "error")], st, SPREAD, TODAY)
    assert d.action == "hide" and "stale" in d.flags
    d = decide(row(), [SourceResult("moglix", "error")], st, CFG.pricing, TODAY)
    assert d.action == "hide" and "stale" in d.info  # cheapest rule: shown as Request a Quote


def test_first_seen_is_recorded_in_live_runs_only():
    from test_run_e2e import FakeFetcher, make_row
    st = {"version": 1, "items": {}}
    runmod.run_sync(CFG, [make_row()], st, FakeFetcher({}), FakeWoo(), TODAY, True, sleep=lambda s: None)
    assert get_price_state(st, "PC-1").first_seen == TODAY
    st2 = {"version": 1, "items": {}}
    runmod.run_sync(CFG, [make_row()], st2, FakeFetcher({}), FakeWoo(), TODAY, False, sleep=lambda s: None)
    assert st2["items"] == {}


def test_failed_publish_of_stale_row_falls_back_to_hiding_the_old_price():
    from test_run_e2e import FakeFetcher, make_row, pages
    st = {"version": 1, "items": {"PC-1": {"price": "900", "last_ok": (TODAY - timedelta(days=5)).isoformat()}}}
    woo = FakeWoo([(200, {"update": [{"id": 100, "error": {"message": "invalid price"}}]}), (200, None)])
    rr = runmod.run_sync(CFG, [make_row()], st, FakeFetcher(pages(1000, 1010, 1020)), woo, TODAY, True,
                         sleep=lambda s: None)
    assert len(woo.calls) == 2 and woo.calls[1][2][0]["regular_price"] == ""
    assert get_price_state(st, "PC-1").hidden and "stale_publish_failed" in rr.items[0]["decision"].flags


# ---- 10. payload does not overwrite more than asked --------------------------------------------
def test_payload_options_can_leave_stock_and_sale_price_alone():
    cfg = PublisherCfg(set_instock=False, clear_sale_price=False)
    p = build_payload(Update("S", 1, 2, D(100), "d"), cfg)
    assert "stock_status" not in p and "sale_price" not in p and p["regular_price"] == "100"
    assert build_payload(Update("S", 1, 2, None, "d"), cfg).get("sale_price") is None


def test_default_payload_sets_instock_and_clears_sale():
    p = build_payload(Update("S", 1, 2, D(100), "d"))
    assert p["stock_status"] == "instock" and p["sale_price"] == ""


# ---- 11. duplicate Woo ids -------------------------------------------------------------------
def test_duplicate_woo_ids_across_skus_are_rejected():
    probs = validate([row(sku="A"), row(sku="B")], CFG)
    assert any("same WooCommerce id" in p for p in probs)


# ---- 12-14 parsing / url / token edge cases -------------------------------------------------
def test_to_decimal_takes_first_number_only():
    assert to_decimal("₹1,906 ₹2,500") == D("1906")
    assert to_decimal("1906 /- 18% GST") == D("1906")
    assert to_decimal("Rs. 1,906.50 only") == D("1906.50")


@pytest.mark.parametrize("url", [
    "https://www.moglix.com/search?searchTerm=x", "https://x.com/catalogsearch/result?q=wire",
    "https://x.com/p?s=wire", "https://x.com/p?q=wire", "https://x.com/search/wire", "https://x.com/shop?keyword=wire"])
def test_search_style_urls_detected(url):
    assert is_search_url(url)


@pytest.mark.parametrize("url", [
    "https://home-run.co/products/kei-homecab-90mtr-wire", "https://www.moglix.com/polycab-wire/mp/msn1234"])
def test_product_urls_not_mistaken_for_search(url):
    assert not is_search_url(url)


def test_pack_of_one_red_keeps_colour_matchable():
    assert normalise_text("Pack of 1 Red") == "pack of 1 red"
    assert check_variant("red", "", "Polycab wire Pack of 1 Red").status == "ok"


def test_bare_number_hint_does_not_match_inside_decimal():
    assert check_variant("1", "", "Polycab 1.5 sqmm wire").status == "variant_unconfirmed"
    assert check_variant("2", "", "Polycab 2 core wire").status == "ok"


def test_units_still_join_after_the_fix():
    assert normalise_text("90 m coil, 3 way, 1.5 sq mm, 20 mm") == "90m coil, 3way, 1.5sqmm, 20mm"


# ---- suspected items we chose to make strict ------------------------------------------------
def test_single_source_exactly_5pct_move_is_held_like_a_5pct_spread():
    d = decide(row(), [SourceResult("moglix", "ok", price=D(105))], PriceState(price=D(100), last_ok=TODAY),
               SPREAD, TODAY)
    assert d.action == "hold" and "single_source_jump" in d.flags
