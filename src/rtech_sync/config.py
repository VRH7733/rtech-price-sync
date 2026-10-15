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
    default_markup_pct: Decimal = Decimal("0")
    default_gst_pct: Decimal = Decimal("18")
    stale_days: int = 3
    fetch_for_manual_rows: bool = False


@dataclass(frozen=True)
class FetchCfg:
    min_delay_seconds: float = 3.0
    timeout_seconds: float = 25.0
    retries: int = 1
    retry_wait_seconds: float = 20.0
    max_runtime_minutes: float = 450.0
    per_host_request_budget: dict = field(default_factory=dict)
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
        default_markup_pct=_dec(p, "default_markup_pct", Decimal("0")),
        default_gst_pct=_dec(p, "default_gst_pct", Decimal("18")),
        stale_days=int(p.get("stale_days", 3)),
        fetch_for_manual_rows=bool(p.get("fetch_for_manual_rows", False)),
    )
    fetch = FetchCfg(
        min_delay_seconds=float(f.get("min_delay_seconds", 3)),
        timeout_seconds=float(f.get("timeout_seconds", 25)),
        retries=int(f.get("retries", 1)),
        retry_wait_seconds=float(f.get("retry_wait_seconds", 20)),
        max_runtime_minutes=float(f.get("max_runtime_minutes", 450)),
        per_host_request_budget=dict(f.get("per_host_request_budget", {})),
        contact_email=env.get("RTECH_CONTACT_EMAIL") or PLACEHOLDER_EMAIL,
    )
    publisher = PublisherCfg(
        batch_size=int(pub.get("batch_size", 25)),
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
