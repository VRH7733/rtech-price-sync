"""Polite HTTP fetching: robots.txt compliance, per-host rate limit, request budget.

What this module will NOT do (by design): rotate proxies/IPs, spoof a browser User-Agent,
solve captchas, or retry past a block. A blocked source is reported, never worked around.

Redirects are followed by hand (max 5 hops). Every hop is re-checked against robots.txt, the
per-host rate limit and the "not a search page" rule, and must stay on the same site.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import urljoin, urlsplit

import requests

from .config import FetchCfg
from .robots import RobotsRules
from .urlcheck import bare_host, is_search_url, same_site

BLOCK_MARKERS = (
    "captcha",
    "access denied",
    "are you a robot",
    "unusual traffic",
    "just a moment...",
    "pardon our interruption",
    "request blocked",
)
REDIRECT_CODES = (301, 302, 303, 307, 308)
MAX_REDIRECTS = 5


def looks_blocked(text: str) -> bool:
    low = (text or "")[:20000].lower()
    return any(m in low for m in BLOCK_MARKERS)


@dataclass
class FetchResult:
    url: str
    status: str  # ok | robots_blocked | blocked | error | not_refreshed
    http: Optional[int] = None
    text: str = ""
    content: bytes = b""
    detail: str = ""
    final_url: str = ""


class HostRateLimiter:
    """Guarantees >= min_delay seconds between requests to the same site (thread-safe).
    'www.example.com' and 'example.com' share one slot."""

    def __init__(self, min_delay: float, clock=time.monotonic, sleep=time.sleep):
        self.min_delay = min_delay
        self._clock, self._sleep = clock, sleep
        self._next: dict = {}
        self._lock = threading.Lock()

    def wait(self, host: str, extra_delay: float = 0.0) -> None:
        key = bare_host(host)
        delay = max(self.min_delay, extra_delay)
        with self._lock:
            now = self._clock()
            slot = max(now, self._next.get(key, 0.0))
            self._next[key] = slot + delay
        if slot > now:
            self._sleep(slot - now)


class Fetcher:
    def __init__(
        self,
        cfg: FetchCfg,
        session: Optional[requests.Session] = None,
        limiter: Optional[HostRateLimiter] = None,
        sleep: Callable = time.sleep,
    ):
        self.cfg = cfg
        self.session = session or requests.Session()
        self.limiter = limiter or HostRateLimiter(cfg.min_delay_seconds, sleep=sleep)
        self._sleep = sleep
        self._robots: dict = {}  # host -> RobotsRules | None (None = could not load -> deny)
        self._lock = threading.Lock()
        self.request_log: dict = {}  # host -> count (for the run summary)

    # -- internals ---------------------------------------------------------
    def _headers(self) -> dict:
        return {
            "User-Agent": self.cfg.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.5",
            "Accept-Language": "en-IN,en;q=0.8",
        }

    def _count(self, host: str) -> None:
        with self._lock:
            self.request_log[host] = self.request_log.get(host, 0) + 1

    def _budget_left(self, host: str, budget_key: str) -> bool:
        budget = self.cfg.per_host_request_budget.get(budget_key)
        if budget is None:
            return True
        return self.request_log.get(host, 0) < budget

    def _load_robots(self, scheme: str, host: str) -> Optional[RobotsRules]:
        if host in self._robots:
            return self._robots[host]
        url = f"{scheme}://{host}/robots.txt"
        rules: Optional[RobotsRules]
        try:
            self.limiter.wait(host)
            self._count(host)
            r = self.session.get(
                url, headers=self._headers(), timeout=self.cfg.timeout_seconds, allow_redirects=False
            )
            if r.status_code == 200:
                raw = getattr(r, "content", b"") or b""
                rules = RobotsRules(raw.decode("utf-8-sig", "replace") if raw else r.text)
            elif r.status_code == 429 or r.status_code >= 500 or r.status_code in REDIRECT_CODES:
                rules = None  # cannot read the rules => do not fetch from this host this run
            elif 400 <= r.status_code < 500:
                rules = RobotsRules("")  # RFC 9309: unavailable (4xx) => no restrictions
            else:
                rules = None
        except requests.RequestException:
            rules = None
        self._robots[host] = rules
        return rules

    # -- public ------------------------------------------------------------
    def get(self, url: str, budget_key: str = "") -> FetchResult:
        start_url = url
        for hop in range(MAX_REDIRECTS + 1):
            res, redirect_to = self._get_once(url, budget_key, start_url)
            if redirect_to is None:
                res.final_url = url
                return res
            nxt = urljoin(url, redirect_to)
            if not same_site(start_url, nxt):
                return FetchResult(start_url, "error", detail=f"redirect leaves the site: {nxt}")
            if is_search_url(nxt):
                return FetchResult(start_url, "error", detail=f"redirect to a search page: {nxt}")
            url = nxt
        return FetchResult(start_url, "error", detail="too many redirects")

    def _get_once(self, url: str, budget_key: str, start_url: str):
        """Returns (FetchResult, redirect_target_or_None)."""
        parts = urlsplit(url)
        host = parts.netloc.lower()
        if parts.scheme not in ("http", "https") or not host:
            return FetchResult(start_url, "error", detail="bad url"), None

        rules = self._load_robots(parts.scheme, host)
        if rules is None:
            return FetchResult(start_url, "robots_blocked", detail="robots.txt unavailable (429/5xx/network)"), None
        if not rules.allowed(url):
            return FetchResult(start_url, "robots_blocked", detail=f"disallowed by robots.txt: {parts.path}"), None
        if not self._budget_left(host, budget_key):
            return FetchResult(start_url, "not_refreshed", detail="per-host request budget used up"), None

        extra = rules.crawl_delay or 0.0
        attempts = 1 + max(0, self.cfg.retries)
        last_detail = ""
        for attempt in range(attempts):
            self.limiter.wait(host, extra)
            self._count(host)
            try:
                r = self.session.get(
                    url, headers=self._headers(), timeout=self.cfg.timeout_seconds, allow_redirects=False
                )
            except requests.RequestException as e:
                last_detail = f"network error: {type(e).__name__}"
                if attempt + 1 < attempts:
                    self._sleep(self.cfg.retry_wait_seconds)
                    continue
                return FetchResult(start_url, "error", detail=last_detail), None

            if r.status_code in REDIRECT_CODES:
                loc = r.headers.get("Location", "")
                if not loc:
                    return FetchResult(start_url, "error", http=r.status_code, detail="redirect without Location"), None
                return FetchResult(start_url, "error"), loc
            if r.status_code in (401, 403):
                return FetchResult(start_url, "blocked", http=r.status_code, detail="HTTP %d" % r.status_code), None
            if r.status_code == 429 or r.status_code >= 500:
                last_detail = f"HTTP {r.status_code}"
                if attempt + 1 < attempts:
                    wait = self.cfg.retry_wait_seconds
                    ra = r.headers.get("Retry-After", "")
                    if ra.isdigit():
                        wait = min(max(wait, float(ra)), 120.0)
                    self._sleep(wait)
                    continue
                status = "blocked" if r.status_code == 429 else "error"
                return FetchResult(start_url, status, http=r.status_code, detail=last_detail), None
            if r.status_code != 200:
                return FetchResult(start_url, "error", http=r.status_code, detail=f"HTTP {r.status_code}"), None
            return FetchResult(start_url, "ok", http=200, text=r.text, content=r.content), None
        return FetchResult(start_url, "error", detail=last_detail or "unknown"), None
