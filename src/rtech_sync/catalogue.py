"""Load and validate catalogue/<brand>.csv files."""
from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

from .config import Config
from .models import CATALOGUE_COLUMNS, SOURCES, Row
from .urlcheck import is_search_url

VALID_MODES = {"priced", "quote"}
VALID_PUBLISH = {"yes", "no", "pending_review"}


class CatalogueError(ValueError):
    pass


def _dec(s: str):
    s = (s or "").strip().replace(",", "")
    if not s:
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        raise CatalogueError(f"not a number: {s!r}")


def _int(s: str):
    s = (s or "").strip()
    return int(s) if s else None


def load_catalogue(directory: str | Path) -> list:
    rows: list = []
    for path in sorted(Path(directory).glob("*.csv")):
        with open(path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            missing = [c for c in ("sku", "mode", "publish") if c not in (reader.fieldnames or [])]
            if missing:
                raise CatalogueError(f"{path.name}: missing columns {missing}")
            for i, rec in enumerate(reader, start=2):
                if not (rec.get("sku") or "").strip():
                    continue
                try:
                    row = Row(
                        sku=rec["sku"].strip(),
                        brand=(rec.get("brand") or "").strip(),
                        category=(rec.get("category") or "").strip(),
                        family=(rec.get("family") or "").strip(),
                        title=(rec.get("title") or "").strip(),
                        pack_size=(rec.get("pack_size") or "").strip(),
                        variant_hint=(rec.get("variant_hint") or "").strip(),
                        mode=(rec.get("mode") or "priced").strip().lower(),
                        wc_product_id=_int(rec.get("wc_product_id")),
                        wc_variation_id=_int(rec.get("wc_variation_id")),
                        markup_pct=_dec(rec.get("markup_pct")),
                        gst_pct=_dec(rec.get("gst_pct")),
                        cost_floor=_dec(rec.get("cost_floor")),
                        manual_price=_dec(rec.get("manual_price")),
                        publish=(rec.get("publish") or "no").strip().lower(),
                        match_confidence=(rec.get("match_confidence") or "").strip(),
                        urls={
                            s: (rec.get(f"url_{s}") or "").strip()
                            for s in SOURCES
                            if (rec.get(f"url_{s}") or "").strip()
                        },
                        notes=(rec.get("notes") or "").strip(),
                        source_file=f"{path.name}:{i}",
                    )
                except (CatalogueError, ValueError) as e:
                    raise CatalogueError(f"{path.name} line {i}: {e}")
                rows.append(row)
    return rows


def validate(rows: list, cfg: Config) -> list:
    """Return a list of human-readable problems. Empty list = OK."""
    problems: list = []
    seen: dict = {}
    ids: dict = {}
    for r in rows:
        where = f"{r.sku} ({r.source_file})"
        if r.sku in seen:
            problems.append(f"{where}: duplicate SKU (also {seen[r.sku]})")
        seen[r.sku] = r.source_file
        if r.mode not in VALID_MODES:
            problems.append(f"{where}: mode must be priced|quote, got {r.mode!r}")
        if r.publish not in VALID_PUBLISH:
            problems.append(f"{where}: publish must be yes|no|pending_review, got {r.publish!r}")
        if r.publish == "yes" and r.mode == "priced":
            if r.wc_product_id is None:
                problems.append(f"{where}: publish=yes but wc_product_id is empty")
            if not r.variant_hint and not r.pack_size:
                problems.append(f"{where}: publish=yes needs variant_hint or pack_size")
            if r.manual_price is None and not r.urls:
                problems.append(f"{where}: publish=yes but no source URLs and no manual_price")
        for source, url in r.urls.items():
            parts = urlsplit(url)
            dom = cfg.sources[source].domain
            host = parts.netloc.lower()
            if parts.scheme not in ("http", "https") or not (host == dom or host.endswith("." + dom)):
                problems.append(f"{where}: url_{source} is not on {dom}: {url}")
            if is_search_url(url):
                problems.append(f"{where}: url_{source} looks like a search page (not allowed)")
        for name in ("markup_pct", "gst_pct", "cost_floor", "manual_price"):
            v = getattr(r, name)
            if v is not None and v < 0:
                problems.append(f"{where}: {name} is negative")
        if r.manual_price is not None and r.manual_price <= 0:
            problems.append(f"{where}: manual_price must be above 0 (clear the cell to go automatic)")
        if r.publish == "yes" and r.mode == "priced" and r.wc_product_id is not None:
            key = (r.wc_product_id, r.wc_variation_id)
            if key in ids:
                problems.append(f"{where}: same WooCommerce id {key} as {ids[key]}")
            ids[key] = r.sku
    return problems


def write_catalogue(path: str | Path, rows: list) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CATALOGUE_COLUMNS)
        w.writeheader()
        for r in rows:
            rec = {
                "sku": r.sku,
                "wc_product_id": r.wc_product_id or "",
                "wc_variation_id": r.wc_variation_id or "",
                "brand": r.brand,
                "category": r.category,
                "family": r.family,
                "title": r.title,
                "pack_size": r.pack_size,
                "variant_hint": r.variant_hint,
                "mode": r.mode,
                "markup_pct": "" if r.markup_pct is None else r.markup_pct,
                "gst_pct": "" if r.gst_pct is None else r.gst_pct,
                "cost_floor": "" if r.cost_floor is None else r.cost_floor,
                "manual_price": "" if r.manual_price is None else r.manual_price,
                "publish": r.publish,
                "match_confidence": r.match_confidence,
                "url_moglix": r.urls.get("moglix", ""),
                "url_industrybuying": r.urls.get("industrybuying", ""),
                "url_homerun": r.urls.get("homerun", ""),
                "notes": r.notes,
            }
            w.writerow(rec)
