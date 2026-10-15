"""Shared data types."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

SOURCES = ("moglix", "industrybuying", "homerun")

# A source result problem that means "your catalogue entry may be wrong" -> shown as a flag.
ATTENTION_STATUSES = frozenset(
    {"variant_unconfirmed", "pack_mismatch", "tax_unknown", "parse_failed"}
)
# Problems that are only informational (site down, blocked, no URL ...).
INFO_STATUSES = frozenset(
    {"robots_blocked", "blocked", "error", "out_of_stock", "not_refreshed"}
)

CATALOGUE_COLUMNS = [
    "sku",
    "wc_product_id",
    "wc_variation_id",
    "brand",
    "category",
    "family",
    "title",
    "pack_size",
    "variant_hint",
    "mode",
    "markup_pct",
    "gst_pct",
    "cost_floor",
    "manual_price",
    "publish",
    "match_confidence",
    "url_moglix",
    "url_industrybuying",
    "url_homerun",
    "notes",
]


@dataclass
class Row:
    """One sellable item (a WooCommerce simple product or a variation)."""

    sku: str
    brand: str = ""
    category: str = ""
    family: str = ""
    title: str = ""
    pack_size: str = ""
    variant_hint: str = ""
    mode: str = "priced"  # priced | quote
    wc_product_id: Optional[int] = None
    wc_variation_id: Optional[int] = None
    markup_pct: Optional[Decimal] = None
    gst_pct: Optional[Decimal] = None
    cost_floor: Optional[Decimal] = None
    manual_price: Optional[Decimal] = None
    publish: str = "no"  # yes | no | pending_review
    match_confidence: str = ""
    urls: dict[str, str] = field(default_factory=dict)  # source -> url
    notes: str = ""
    source_file: str = ""


@dataclass
class SourceResult:
    source: str
    status: str  # ok | no_url | robots_blocked | blocked | error | not_refreshed | out_of_stock
    #              | variant_unconfirmed | pack_mismatch | tax_unknown | parse_failed
    price: Optional[Decimal] = None  # GST-inclusive Rs per pack when status == ok
    url: str = ""
    detail: str = ""

    @property
    def usable(self) -> bool:
        return self.status == "ok" and self.price is not None and self.price > 0


@dataclass
class PriceState:
    """What we last published for a row (from data/latest.json)."""

    price: Optional[Decimal] = None
    last_ok: Optional[date] = None  # last day a price was validated and published
    hidden: bool = False
    first_seen: Optional[date] = None  # first day the bot saw this row (starts the stale clock)
    pending: Optional[Decimal] = None  # cheapest mode: a big move held yesterday, waiting to repeat
