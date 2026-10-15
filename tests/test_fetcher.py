import requests
from fakes import FakeClock, FakeResp, FakeSession
from rtech_sync.config import FetchCfg
from rtech_sync.fetcher import Fetcher, HostRateLimiter, looks_blocked

CFG = FetchCfg(min_delay_seconds=3, retries=1, retry_wait_seconds=20,
               per_host_request_budget={"homerun": 3}, contact_email="shop@example.com")
ROBOTS = "User-agent: *\nDisallow: /search\nDisallow: /*?p=\n"
HOME = "https://home-run.co"


def make(routes, cfg=CFG):
    clock = FakeClock()
    sess = FakeSession({f"{HOME}/robots.txt": FakeResp(200, ROBOTS), **routes})
    f = Fetcher(cfg, session=sess, limiter=HostRateLimiter(cfg.min_delay_seconds, clock.time, clock.sleep),
                sleep=clock.sleep)
    return f, sess, clock


def test_fetches_allowed_page_and_sends_honest_user_agent():
    f, sess, _ = make({f"{HOME}/products/a": FakeResp(200, "<html>ok</html>")})
    r = f.get(f"{HOME}/products/a", "homerun")
    assert r.status == "ok" and "ok" in r.text
    assert "shop@example.com" in f.cfg.user_agent and f.cfg.user_agent.startswith("rtech-price-sync/")


def test_robots_disallowed_page_is_never_requested():
    f, sess, _ = make({f"{HOME}/search": FakeResp(200, "x")})
    r = f.get(f"{HOME}/search", "homerun")
    assert r.status == "robots_blocked" and f"{HOME}/search" not in sess.calls


def test_wildcard_query_rule_enforced():
    f, sess, _ = make({})
    assert f.get(f"{HOME}/collections/x?p=2", "homerun").status == "robots_blocked"


def test_robots_5xx_means_do_not_fetch():
    clock = FakeClock()
    sess = FakeSession({f"{HOME}/robots.txt": FakeResp(503)})
    f = Fetcher(CFG, session=sess, limiter=HostRateLimiter(3, clock.time, clock.sleep), sleep=clock.sleep)
    assert f.get(f"{HOME}/products/a", "homerun").status == "robots_blocked"
    assert f"{HOME}/products/a" not in sess.calls


def test_robots_404_means_allowed():
    clock = FakeClock()
    sess = FakeSession({f"{HOME}/robots.txt": FakeResp(404), f"{HOME}/products/a": FakeResp(200, "ok")})
    f = Fetcher(CFG, session=sess, limiter=HostRateLimiter(3, clock.time, clock.sleep), sleep=clock.sleep)
    assert f.get(f"{HOME}/products/a", "homerun").status == "ok"


def test_three_second_gap_between_requests_to_same_host():
    f, sess, clock = make({f"{HOME}/products/a": FakeResp(200, "a"), f"{HOME}/products/b": FakeResp(200, "b")})
    f.get(f"{HOME}/products/a", "homerun")
    t_a = clock.t
    f.get(f"{HOME}/products/b", "homerun")
    # robots.txt fetch, then page a, then page b: every request is >= 3 s after the previous one
    assert sum(clock.sleeps) >= 6 - 1e-9 and clock.t - t_a >= 0


def test_403_is_reported_as_blocked_and_not_retried():
    f, sess, _ = make({f"{HOME}/products/a": FakeResp(403)})
    r = f.get(f"{HOME}/products/a", "homerun")
    assert r.status == "blocked" and sess.calls.count(f"{HOME}/products/a") == 1


def test_429_then_success_retries_once_after_waiting():
    f, sess, clock = make({f"{HOME}/products/a": [FakeResp(429, headers={"Retry-After": "30"}), FakeResp(200, "ok")]})
    r = f.get(f"{HOME}/products/a", "homerun")
    assert r.status == "ok" and 30 in clock.sleeps


def test_persistent_429_is_blocked_not_hammered():
    f, sess, _ = make({f"{HOME}/products/a": FakeResp(429)})
    r = f.get(f"{HOME}/products/a", "homerun")
    assert r.status == "blocked" and sess.calls.count(f"{HOME}/products/a") == 2


def test_5xx_then_error():
    f, sess, _ = make({f"{HOME}/products/a": FakeResp(500)})
    assert f.get(f"{HOME}/products/a", "homerun").status == "error"


def test_network_error_retries_then_reports_error():
    f, sess, _ = make({f"{HOME}/products/a": requests.ConnectionError("boom")})
    r = f.get(f"{HOME}/products/a", "homerun")
    assert r.status == "error" and sess.calls.count(f"{HOME}/products/a") == 2


def test_budget_exhaustion_returns_not_refreshed():
    f, sess, _ = make({f"{HOME}/products/{c}": FakeResp(200, c) for c in "abcd"})
    # budget=3 includes the robots.txt request
    statuses = [f.get(f"{HOME}/products/{c}", "homerun").status for c in "abcd"]
    assert statuses.count("ok") == 2 and "not_refreshed" in statuses


def test_crawl_delay_is_respected():
    clock = FakeClock()
    sess = FakeSession({f"{HOME}/robots.txt": FakeResp(200, "User-agent: *\nCrawl-delay: 10\n"),
                        f"{HOME}/products/a": FakeResp(200, "a"), f"{HOME}/products/b": FakeResp(200, "b")})
    f = Fetcher(CFG, session=sess, limiter=HostRateLimiter(3, clock.time, clock.sleep), sleep=clock.sleep)
    f.get(f"{HOME}/products/a", "x")
    f.get(f"{HOME}/products/b", "x")
    assert max(clock.sleeps) >= 10


def test_non_http_url_rejected():
    f, _, _ = make({})
    assert f.get("ftp://x/y").status == "error"


def test_looks_blocked_markers():
    assert looks_blocked("<title>Just a moment...</title>")
    assert not looks_blocked("<html>Polycab wire</html>")
