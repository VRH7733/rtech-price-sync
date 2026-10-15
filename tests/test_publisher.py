from decimal import Decimal as D

from fakes import FakeWoo
from rtech_sync.config import PublisherCfg
from rtech_sync.publisher import META_HIDDEN, Update, build_payload, publish_updates

CFG = PublisherCfg(batch_size=25, pause_seconds=2, backoff_seconds=(5, 15), stop_after_consecutive_failures=2)


def upd(i, price="100", pid=10, vid=None):
    return Update(f"S{i}", pid, vid if vid is not None else None, None if price is None else D(price), "2026-10-14")


def no_sleep_log():
    log = []
    return log, log.append


def test_payload_for_price_forces_instock_and_clears_sale_price():
    p = build_payload(upd(1, "450.00", vid=55))
    assert p["id"] == 55 and p["regular_price"] == "450" and p["sale_price"] == "" and p["stock_status"] == "instock"
    assert {"key": META_HIDDEN, "value": "0"} in p["meta_data"]


def test_payload_keeps_paise():
    assert build_payload(upd(1, "450.50"))["regular_price"] == "450.50"


def test_payload_for_hidden_price_empties_price_and_sets_flag():
    p = build_payload(upd(1, None))
    assert p["regular_price"] == "" and {"key": META_HIDDEN, "value": "1"} in p["meta_data"]
    assert "stock_status" not in p


def test_dry_run_makes_no_calls():
    woo = FakeWoo()
    rep = publish_updates(woo, [upd(1)], CFG, dry_run=True)
    assert woo.calls == [] and rep.published == ["S1"]


def test_batches_of_25_with_pauses_between_batches():
    woo = FakeWoo()
    log, sleep = no_sleep_log()
    ups = [upd(i, vid=1000 + i) for i in range(60)]
    rep = publish_updates(woo, ups, CFG, dry_run=False, sleep=sleep)
    assert [len(c[2]) for c in woo.calls] == [25, 25, 10]
    assert all(c[0] == "variations" and c[1] == 10 for c in woo.calls)
    assert log == [2, 2] and len(rep.published) == 60


def test_simple_products_use_products_endpoint_and_groups_are_separate():
    woo = FakeWoo()
    ups = [upd(1), upd(2, pid=20, vid=200), upd(3, pid=21, vid=210)]
    publish_updates(woo, ups, CFG, dry_run=False, sleep=lambda s: None)
    kinds = sorted((c[0], c[1]) for c in woo.calls)
    assert kinds == [("products", None), ("variations", 20), ("variations", 21)]


def test_508_backs_off_then_succeeds():
    woo = FakeWoo([(508, {}), (503, {}), (200, None)])
    log, sleep = no_sleep_log()
    rep = publish_updates(woo, [upd(1)], CFG, dry_run=False, sleep=sleep)
    assert log == [5, 15] and rep.published == ["S1"] and rep.requests == 3


def test_persistent_errors_stop_publishing_and_report_throttled():
    # backoff (5,15) => 3 attempts per batch; two failed batches => stop
    woo = FakeWoo([(508, {})] * 20)
    ups = [upd(i, vid=100 + i) for i in range(100)]  # 4 batches
    rep = publish_updates(woo, ups, CFG, dry_run=False, sleep=lambda s: None)
    assert "publish_throttled" in rep.fatal
    assert rep.published == []
    assert len(rep.throttled) == 50  # batches 3 and 4 never attempted
    assert len(rep.failed) == 50


def test_403_is_fatal_immediately_and_not_retried():
    woo = FakeWoo([(403, {})])
    rep = publish_updates(woo, [upd(1), upd(2, pid=20, vid=2)], CFG, dry_run=False, sleep=lambda s: None)
    assert "firewall" in rep.fatal and len(woo.calls) == 1
    assert sorted(rep.throttled) == ["S1", "S2"]


def test_item_level_error_is_recorded_but_others_succeed():
    data = {"update": [{"id": 1000}, {"id": 1001, "error": {"code": "x", "message": "invalid price"}}]}
    woo = FakeWoo([(200, data)])
    rep = publish_updates(woo, [upd(0, vid=1000), upd(1, vid=1001)], CFG, dry_run=False, sleep=lambda s: None)
    assert rep.published == ["S0"] and rep.failed == {"S1": "invalid price"}


def test_missing_result_for_item_counts_as_failure():
    woo = FakeWoo([(200, {"update": []})])
    rep = publish_updates(woo, [upd(0)], CFG, dry_run=False, sleep=lambda s: None)
    assert rep.failed and not rep.published
