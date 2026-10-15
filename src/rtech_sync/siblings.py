"""Sibling check for single-site wire prices. Pure functions, no I/O.

IndustryBuying lists some wires twice, one listing at 3-5x the real price (seen 15 Oct 2026:
Polycab Suprema 2.5 sqmm 90 m at Rs 9,203 where HomeRun sells the same size for ~Rs 4,500). When
only that listing has the product, the per-product outlier guard has nothing to compare with.

The same wire in the other colours (and other product lines) costs about the same, so a
single-site price is compared with its siblings: same brand, sqmm, cores, coil length and
armouring. A sibling counts only when its price is cross-checked (2+ sites) or comes from a
DIFFERENT site. With at least min_refs such siblings, a price more than `ratio` x their median
(or less than 1/ratio of the median of cross-checked siblings) is not published: the product
shows Request a Quote and is flagged "sibling_outlier:<site>". Same 2x threshold as the owner's outlier guard (15 Oct 2026).
"""
from __future__ import annotations

import re
import statistics
from decimal import Decimal
from typing import Optional

from .normalise import normalise_text

_SQMM = re.compile(r"(?<![0-9.])(\d+(?:\.\d+)?)sqmm")
_CORES = re.compile(r"(?<![0-9.])(\d+)\s?(?:-\s?)?cores?\b")
_LEN = re.compile(r"(?<![0-9.])(\d+(?:\.\d+)?)\s?m\b")


def spec_key(row) -> Optional[tuple]:
    """(brand, sqmm, cores, metres, armoured) for a wire/cable sold by the coil, else None."""
    title = normalise_text(row.title)
    if "wire" not in title and "cable" not in title:
        return None
    sq = _SQMM.search(title)
    length = _LEN.search(normalise_text(row.pack_size or ""))
    if not sq or not length:
        return None
    cores = _CORES.search(title)
    return (row.brand.lower(), sq.group(1), cores.group(1) if cores else "1",
            length.group(1), "armour" in title)


def apply_sibling_guard(items: list, ratio: Decimal, min_refs: int = 2) -> list:
    """items: dicts with "row", "decision", "results" (as built in run.py). Changes the
    decisions of outliers in place to hide (Request a Quote). Returns the SKUs changed."""
    if not ratio or ratio <= 0:
        return []
    groups = {}
    for it in items:
        d = it["decision"]
        key = spec_key(it["row"])
        if key is None or d.action != "publish" or d.price is None:
            continue
        n_sites = sum(1 for x in it["results"] if x.usable)
        groups.setdefault(key, []).append((it, d.cheapest_source, n_sites, d.price))
    changed = []
    for members in groups.values():
        for it, src, n_sites, price in members:
            if n_sites != 1:
                continue
            others = [(s, n, p) for other, s, n, p in members if other is not it]
            # too high: any sibling priced on another site counts. Too low: only cross-checked
            # siblings (2+ sites), so inflated single-site siblings never hide a real low price.
            high = [p for s, n, p in others if n >= 2 or s != src]
            low = [p for s, n, p in others if n >= 2]
            too_high = len(high) >= min_refs and price > statistics.median(high) * ratio
            too_low = len(low) >= min_refs and price * ratio < statistics.median(low)
            if too_high or too_low:
                refs = high if too_high else low
                mid = statistics.median(refs)
                d = it["decision"]
                d.action, d.price, d.pending, d.refreshed = "hide", None, None, False
                d.flags.append(f"sibling_outlier:{src}")
                d.note = f"price {price} vs {len(refs)} same-size siblings, median {mid}"
                changed.append(it["row"].sku)
    return changed


def apply_listing_guard(items: list, patterns: dict) -> list:
    """A price that rests on ONE listing whose URL matches patterns[site] (e.g. IndustryBuying
    "-ELE." seller listings, every one of which that another site also had was 2-9x dearer on
    15 Oct 2026) is not published: the product shows Request a Quote, flag
    "unconfirmed_listing:<site>". With a second site the outlier guard decides instead."""
    changed = []
    if not patterns:
        return changed
    for it in items:
        d = it["decision"]
        usable = [x for x in it["results"] if x.usable]
        if d.action != "publish" or d.price is None or len(usable) != 1:
            continue
        src = usable[0].source
        pat = patterns.get(src)
        if pat and pat in (it["row"].urls.get(src) or ""):
            d.action, d.price, d.pending, d.refreshed = "hide", None, None, False
            d.flags.append(f"unconfirmed_listing:{src}")
            changed.append(it["row"].sku)
    return changed
