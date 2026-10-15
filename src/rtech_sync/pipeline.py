"""Turn one fetched page into a SourceResult for one catalogue row."""
from __future__ import annotations

from typing import Optional

from .config import Config
from .fetcher import FetchResult, looks_blocked
from .models import Row, SourceResult
from .normalise import check_variant, to_gst_inclusive
from .parsers import parse_product_page


def evaluate_source(row: Row, source: str, fr: Optional[FetchResult], cfg: Config) -> SourceResult:
    url = row.urls.get(source, "")
    if not url:
        return SourceResult(source, "no_url")
    if fr is None:
        return SourceResult(source, "not_refreshed", url=url, detail="not attempted this run")
    if fr.status != "ok":
        return SourceResult(source, fr.status, url=url, detail=fr.detail)

    parsed = parse_product_page(fr.text, url)
    if parsed.price is None and not parsed.multi_variant:
        if looks_blocked(fr.text):
            return SourceResult(source, "blocked", url=url, detail="bot-protection page")
        return SourceResult(
            source, "parse_failed", url=url, detail=",".join(parsed.problems) or "no price"
        )
    if parsed.multi_variant:
        return SourceResult(
            source,
            "variant_unconfirmed",
            url=url,
            detail="page covers several variants; use a variant-specific URL",
        )

    if "price_not_visible_in_text" in parsed.problems:
        # structured-data price that shoppers cannot see: possible paise/rupee mix-up, stale
        # JSON or a different variant/pincode. Never trust it.
        return SourceResult(
            source, "parse_failed", url=url, detail="price in page data is not shown on the page"
        )

    vc = check_variant(row.variant_hint, row.pack_size, parsed.identity_text)
    if vc.status != "ok":
        return SourceResult(source, vc.status, url=url, detail=vc.detail)

    if parsed.in_stock is False:
        return SourceResult(source, "out_of_stock", url=url, detail="listed as out of stock")

    gst = row.gst_pct if row.gst_pct is not None else cfg.pricing.default_gst_pct
    price, status = to_gst_inclusive(
        parsed.price, parsed.tax_basis, gst, cfg.sources[source].assumed_tax_basis
    )
    if status != "ok":
        return SourceResult(
            source, "tax_unknown", url=url, detail="page does not say GST incl/excl; set assumed_tax_basis"
        )
    return SourceResult(source, "ok", price=price, url=url, detail=parsed.method)
