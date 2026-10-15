"""WooCommerce REST publisher, gentle enough for shared hosting (Hostinger Premium).

* pushes only changed items, in small batches with pauses
* backs off on 429/502/503/504/508 ("Resource Limit Reached") and stops cleanly if errors persist
* never deletes anything; it only sets price, stock status and two meta keys
* dry-run is the default; the caller must pass dry_run=False
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, Optional

import requests

from .config import PublisherCfg

META_UPDATED = "_rte_price_updated_at"
META_HIDDEN = "_rte_price_hidden"


@dataclass
class Update:
    sku: str
    product_id: int
    variation_id: Optional[int]
    price: Optional[Decimal]  # None => hide price
    date: str

    @property
    def hidden(self) -> bool:
        return self.price is None


def build_payload(u: Update, cfg: Optional[PublisherCfg] = None) -> dict:
    cfg = cfg or PublisherCfg()
    target = u.variation_id if u.variation_id else u.product_id
    meta = [
        {"key": META_UPDATED, "value": u.date},
        {"key": META_HIDDEN, "value": "1" if u.hidden else "0"},
    ]
    if u.hidden:
        # Empty price = WooCommerce shows no price and hides add-to-cart. The theme
        # shows "Request price" for items with _rte_price_hidden=1 (Phase 4 task).
        payload = {"id": target, "regular_price": "", "meta_data": meta}
        if cfg.clear_sale_price:
            payload["sale_price"] = ""
        return payload
    payload = {
        "id": target,
        "regular_price": format(u.price.normalize(), "f") if u.price == u.price.to_integral_value()
        else format(u.price, "f"),
        "meta_data": meta,
    }
    if cfg.clear_sale_price:
        payload["sale_price"] = ""
    if cfg.set_instock:
        payload["stock_status"] = "instock"
    return payload


class WooClient:
    def __init__(self, base_url: str, key: str, secret: str, session=None, timeout: float = 60):
        self.base = base_url.rstrip("/") + "/wp-json/wc/v3"
        self.auth = (key, secret)
        self.session = session or requests.Session()
        self.timeout = timeout

    def _post(self, path: str, payload: dict):
        r = self.session.post(
            self.base + path, json=payload, auth=self.auth, timeout=self.timeout
        )
        try:
            data = r.json()
        except ValueError:
            data = {}
        return r.status_code, data

    def get(self, path: str, params: Optional[dict] = None):
        r = self.session.get(
            self.base + path, params=params or {}, auth=self.auth, timeout=self.timeout
        )
        try:
            data = r.json()
        except ValueError:
            data = None
        return r.status_code, data

    def batch_products(self, items: list):
        return self._post("/products/batch", {"update": items})

    def create_product(self, payload: dict):
        """Used only by tools/create_drafts.py, which always sends status=draft."""
        if payload.get("status") != "draft":
            raise ValueError("create_product only creates drafts")
        return self._post("/products", payload)

    def batch_variations(self, product_id: int, items: list):
        return self._post(f"/products/{product_id}/variations/batch", {"update": items})


@dataclass
class PublishReport:
    published: list = field(default_factory=list)  # skus
    failed: dict = field(default_factory=dict)  # sku -> message
    throttled: list = field(default_factory=list)  # skus not attempted / abandoned
    requests: int = 0
    fatal: str = ""


def _send(fn: Callable, cfg: PublisherCfg, sleep: Callable, report: PublishReport):
    status, data = None, {}
    for attempt in range(len(cfg.backoff_seconds) + 1):
        report.requests += 1
        try:
            status, data = fn()
        except requests.RequestException as e:
            status, data = None, {"message": type(e).__name__}
        if status is not None and status < 400:
            return status, data
        retryable = status is None or status in cfg.backoff_statuses
        if retryable and attempt < len(cfg.backoff_seconds):
            sleep(cfg.backoff_seconds[attempt])
            continue
        break
    return status, data


def publish_updates(
    client: Optional[WooClient],
    updates: list,
    cfg: PublisherCfg,
    dry_run: bool = True,
    sleep: Callable = time.sleep,
) -> PublishReport:
    report = PublishReport()
    if dry_run or client is None:
        report.published = [u.sku for u in updates]
        return report

    # group: variations by parent product, simple products together
    groups: dict = {}
    for u in updates:
        key = u.product_id if u.variation_id else None
        groups.setdefault(key, []).append(u)

    consecutive_failures = 0
    stopped = False
    first = True
    for key, items in groups.items():
        for i in range(0, len(items), cfg.batch_size):
            chunk = items[i : i + cfg.batch_size]
            if stopped:
                report.throttled.extend(u.sku for u in chunk)
                continue
            if not first:
                sleep(cfg.pause_seconds)
            first = False
            payload = [build_payload(u, cfg) for u in chunk]
            if key is None:
                call = lambda p=payload: client.batch_products(p)
            else:
                call = lambda p=payload, k=key: client.batch_variations(k, p)
            status, data = _send(call, cfg, sleep, report)

            if status in (401, 403):
                report.fatal = f"auth/firewall error HTTP {status}: check keys or Hostinger firewall"
                stopped = True
                report.throttled.extend(u.sku for u in chunk)
                continue
            if status is None or status >= 400:
                consecutive_failures += 1
                for u in chunk:
                    report.failed[u.sku] = f"HTTP {status}"
                if consecutive_failures >= cfg.stop_after_consecutive_failures:
                    report.fatal = f"publish_throttled after {consecutive_failures} failed batches"
                    stopped = True
                continue
            if not isinstance(data, dict) or not isinstance(data.get("update"), list):
                # HTTP 200 but not a WooCommerce batch answer (WAF/maintenance page?): count as failure
                consecutive_failures += 1
                for u in chunk:
                    report.failed[u.sku] = "unparseable response (HTTP %s)" % status
                if consecutive_failures >= cfg.stop_after_consecutive_failures:
                    report.fatal = f"publish_throttled after {consecutive_failures} bad responses"
                    stopped = True
                continue
            consecutive_failures = 0
            results = {}
            for item in data["update"]:
                if isinstance(item, dict):
                    results[item.get("id")] = item
            for u in chunk:
                tid = u.variation_id if u.variation_id else u.product_id
                item = results.get(tid)
                if item is None or "error" in item:
                    msg = ((item or {}).get("error") or {}).get("message", "no result returned")
                    report.failed[u.sku] = msg
                else:
                    report.published.append(u.sku)
    return report
