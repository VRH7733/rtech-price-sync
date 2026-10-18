"""Configuration loading."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Optional

import yaml

PLACEHOLDER_EMAIL = "CHANGE_ME@example.com"


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class PricingCfg:
    spread_flag_pct: Decimal = Decimal("5")
    big_move_pct: Decimal = Decimal("15")
    big_move_holds: bool = False
    single_source_max_move_pct: Decimal = Decimal("5")
    # a source priced more than this many times the cheapest OTHER usable source is ignored as a
    # listing error and flagged (owner's STOP 2 decision, 15 Oct 2026). 0 = off.
    outlier_ratio: Decimal = Decimal("0")
    # "spread": the original rule (publish the cheapest only when all sources agree within
    # spread_flag_pct). "cheapest": the owner's 15 Oct 2026 go-live rule: publish the cheapest
    # trusted source every day, one source is enough, a big move must repeat the next day.
    rule: str = "spread"
    # cheapest rule: a single-site wire price more than this many times the median of the same
    # size in other colours/lines (priced elsewhere) is not published. 0 = off. See siblings.py.
    sibling_ratio: Decimal = Decimal("0")
    # cheapest rule: {site: URL part}. A listing whose URL contains it is only trusted when a
    # second site also has the product (siblings.apply_listing_guard). Empty = off.
    needs_second_site: dict = field(default_factory=dict)
    default_markup_pct: Decimal = Decimal("0")
    default_gst_pct: Decimal = Decimal("18")
    stale_days: int = 3
    # a site that refuses us (blocked) keeps its last real price for this many days (0 = off)
    keep_blocked_days: int = 0
    # a product no marketplace prices shows its brand's official MRP read within this many days
    # (data/brand_prices.json, tools/brand_prices.py). 0 = off.
    brand_price_days: int = 0
    fetch_for_manual_rows: bool = False


@dataclass(frozen=True)
class FetchCfg:
    min_delay_seconds: float = 3.0
    timeout_seconds: float = 25.0
    retries: int = 1
    retry_wait_seconds: float = 20.0
    max_runtime_minutes: float = 450.0
    per_host_request_budget: dict = field(default_factory=dict)
    # each product is checked once every this many days (a share of the catalogue each day)
    check_every_days: int = 1
    # sources the run no longer asks at all (their last real prices may still be kept)
    skip_sources: tuple = ()
    contact_email: str = PLACEHOLDER_EMAIL

    @property
    def user_agent(self) -> str:
        return (
            f"rtech-price-sync/0.1 (+mailto:{self.contact_email}; "
            "price comparison for rtechelectricals.com)"
        )

    def require_contact_email(self) -> None:
        if not self.contact_email or self.contact_email == PLACEHOLDER_EMAIL:
            raise ConfigError(
                "Set RTECH_CONTACT_EMAIL (business address) before fetching real sites."
            )


@dataclass(frozen=True)
class PublisherCfg:
    batch_size: int = 25
    pause_seconds: float = 2.0
    backoff_seconds: tuple = (5, 15, 45, 120)
    backoff_statuses: tuple = (429, 502, 503, 504, 508)
    stop_after_consecutive_failures: int = 3
    history_keep_days: int = 30
    set_instock: bool = True  # force stock_status=instock on priced items (fixes the SOLD OUT badge)
    clear_sale_price: bool = True  # an old sale_price would override the synced regular_price
    # quote_external: a product without a price becomes a WooCommerce "external" product whose
    # button says quote_button_text and links to quote_url (in stock, no SOLD OUT badge). A price
    # turns it back into a "simple" product. Off = the original hide (empty price only).
    quote_external: bool = False
    quote_button_text: str = "Request a Quote"
    quote_url: str = ""  # {sku} is replaced by the product's SKU


@dataclass(frozen=True)
class SourceCfg:
    name: str
    domain: str
    assumed_tax_basis: Optional[str] = None  # None | incl_gst | excl_gst


@dataclass(frozen=True)
class Config:
    site_url: str
    timezone: str
    pricing: PricingCfg
    fetch: FetchCfg
    publisher: PublisherCfg
    sources: dict


def _dec(d: dict, key: str, default: Decimal) -> Decimal:
    return Decimal(str(d[key])) if key in d and d[key] is not None else default


def load_config(path: str | Path = "config.yaml", env: Optional[dict] = None) -> Config:
    env = os.environ if env is None else env
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    p = raw.get("pricing", {})
    f = raw.get("fetch", {})
    pub = raw.get("publisher", {})
    site = raw.get("site", {})

    pricing = PricingCfg(
        spread_flag_pct=_dec(p, "spread_flag_pct", Decimal("5")),
        big_move_pct=_dec(p, "big_move_pct", Decimal("15")),
        big_move_holds=bool(p.get("big_move_holds", False)),
        single_source_max_move_pct=_dec(p, "single_source_max_move_pct", Decimal("5")),
        outlier_ratio=_dec(p, "outlier_ratio", Decimal("0")),
        sibling_ratio=_dec(p, "sibling_ratio", Decimal("0")),
        needs_second_site={str(k): str(v) for k, v in (p.get("needs_second_site") or {}).items()},
        rule=str(p.get("rule", "spread")),
        default_markup_pct=_dec(p, "default_markup_pct", Decimal("0")),
        default_gst_pct=_dec(p, "default_gst_pct", Decimal("18")),
        stale_days=int(p.get("stale_days", 3)),
        keep_blocked_days=int(p.get("keep_blocked_days", 0)),
        brand_price_days=int(p.get("brand_price_days", 0)),
        fetch_for_manual_rows=bool(p.get("fetch_for_manual_rows", False)),
    )
    fetch = FetchCfg(
        min_delay_seconds=float(f.get("min_delay_seconds", 3)),
        timeout_seconds=float(f.get("timeout_seconds", 25)),
        retries=int(f.get("retries", 1)),
        retry_wait_seconds=float(f.get("retry_wait_seconds", 20)),
        max_runtime_minutes=float(f.get("max_runtime_minutes", 450)),
        per_host_request_budget=dict(f.get("per_host_request_budget", {})),
        check_every_days=max(1, int(f.get("check_every_days", 1))),
        skip_sources=tuple(f.get("skip_sources") or ()),
        contact_email=env.get("RTECH_CONTACT_EMAIL") or PLACEHOLDER_EMAIL,
    )
    publisher = PublisherCfg(
        batch_size=int(pub.get("batch_size", 25)),
        quote_external=bool(pub.get("quote_external", False)),
        quote_button_text=str(pub.get("quote_button_text", "Request a Quote")),
        quote_url=str(pub.get("quote_url", "")),
        pause_seconds=float(pub.get("pause_seconds", 2)),
        backoff_seconds=tuple(pub.get("backoff_seconds", (5, 15, 45, 120))),
        backoff_statuses=tuple(pub.get("backoff_statuses", (429, 502, 503, 504, 508))),
        stop_after_consecutive_failures=int(pub.get("stop_after_consecutive_failures", 3)),
        history_keep_days=int(pub.get("history_keep_days", 30)),
        set_instock=bool(pub.get("set_instock", True)),
        clear_sale_price=bool(pub.get("clear_sale_price", True)),
    )
    sources = {
        name: SourceCfg(
            name=name,
            domain=str(cfg["domain"]),
            assumed_tax_basis=cfg.get("assumed_tax_basis"),
        )
        for name, cfg in (raw.get("sources") or {}).items()
    }
    if not sources:
        raise ConfigError("config.yaml has no sources")
    return Config(
        site_url=site.get("base_url", "https://rtechelectricals.com"),
        timezone=site.get("timezone", "Asia/Kolkata"),
        pricing=pricing,
        fetch=fetch,
        publisher=publisher,
        sources=sources,
    )
