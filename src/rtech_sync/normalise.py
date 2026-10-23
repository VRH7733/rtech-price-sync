"""Text normalisation, variant/pack checking and GST normalisation.

Safety principle: if we cannot positively confirm that a page is the exact variant
and pack we sell, the source is excluded (never guessed).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

_UNIT_SYNONYMS = [
    (re.compile(r"\bsq\.?\s*mm\b|\bsquare\s*mm\b"), "sqmm"),
    (re.compile(r"\b(?:metres?|meters?|mtrs?|mtr)\b"), "m"),
    (re.compile(r"\b(?:millimet(?:er|re)s?)\b"), "mm"),
    (re.compile(r"\b(?:pieces?|pcs|pc)\b"), "pc"),
]


_JOIN_UNIT = re.compile(
    r"(\d)\s+(sqmm|mm|cm|kva|kw|ka|kg|ml|pc|way|pole|amps?|[mgvlwa])(?![a-z])"
)


def normalise_text(s: str) -> str:
    s = (s or "").lower().replace("×", "x").replace(" ", " ")
    for pat, repl in _UNIT_SYNONYMS:
        s = pat.sub(repl, s)
    # product lines are written "Optima+" on one site and "optima-plus"/"Optima Plus" on another
    s = re.sub(r"(?<=[a-z])\s+plus\b", "+", s)
    s = _JOIN_UNIT.sub(r"\1\2", s)  # "90 m" -> "90m" (known units only; "1 red" stays apart)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _token_regex(token: str) -> re.Pattern:
    t = re.escape(normalise_text(token)).replace(r"\ ", r"\s+")
    # not glued to other digits/letters, and "1" must not match inside "1.5"
    return re.compile(r"(?<![0-9a-z.])" + t + r"(?![0-9a-z]|\.\d)")


def contains_token(text_norm: str, token: str) -> bool:
    if not token.strip():
        return False
    return _token_regex(token).search(text_norm) is not None


def split_hint(hint: str) -> list:
    return [t.strip() for t in re.split(r"[;|]", hint or "") if t.strip()]


_QTY = re.compile(r"(?<![0-9a-z.])(\d+(?:\.\d+)?)(m|mm|kg|g|l|ml|pc)(?![0-9a-z])")


# "Pack of 5", "set of 10", "box of 20": the page price is for N items. Seen on real Moglix pages
# (Legrand Mylinc switch "(Pack of 5)", 14 Oct 2026). The row must say the same N, or the price is
# for a different quantity than the one we sell.
_MULTIPACK = re.compile(r"(?<![0-9a-z])(?:pack|set|box|bundle|combo)\s*of\s*(\d+)(?![0-9])")
_ROW_PIECES = re.compile(r"(?<![0-9a-z.])(\d+)pc(?![0-9a-z])")


def _page_pack_counts(text_norm: str) -> set:
    return {int(n) for n in _MULTIPACK.findall(text_norm) if int(n) > 1}


def _row_pack_count(pack_norm: str) -> Optional[int]:
    m = _MULTIPACK.search(pack_norm) or _ROW_PIECES.search(pack_norm)
    return int(m.group(1)) if m else None


def pack_count(pack_size: str, title: str = "") -> int:
    """How many pieces one product we sell holds: from its pack_size, else "Pack of N" in its title."""
    n = _row_pack_count(normalise_text(pack_size or "")) if pack_size else None
    if not n:
        m = _MULTIPACK.search(normalise_text(title or ""))
        n = int(m.group(1)) if m else None
    return n if n and n > 1 else 1


@dataclass
class VariantCheck:
    status: str  # ok | variant_unconfirmed | pack_mismatch
    detail: str = ""


def check_variant(variant_hint: str, pack_size: str, identity_text: str) -> VariantCheck:
    """Confirm the page identity text contains every hint token and the pack size."""
    tokens = split_hint(variant_hint)
    if not tokens and not pack_size.strip():
        return VariantCheck("variant_unconfirmed", "row has no variant_hint/pack_size")
    text = normalise_text(identity_text)
    missing = [t for t in tokens if not contains_token(text, t)]
    if missing:
        return VariantCheck("variant_unconfirmed", "missing: " + ", ".join(missing))
    if pack_size.strip() and not contains_token(text, pack_size):
        want = _QTY.search(normalise_text(pack_size))
        if want:
            unit = want.group(2)
            found = [m for m in _QTY.finditer(text) if m.group(2) == unit]
            if found:
                seen = ", ".join(sorted({m.group(0) for m in found}))
                return VariantCheck("pack_mismatch", f"want {want.group(0)}, page has {seen}")
        page_packs = _page_pack_counts(text)
        row_n = _row_pack_count(normalise_text(pack_size))
        if page_packs and row_n is not None:
            if page_packs != {row_n}:
                seen = ", ".join(f"pack of {n}" for n in sorted(page_packs))
                return VariantCheck("pack_mismatch", f"want '{pack_size}', page sells {seen}")
        else:
            return VariantCheck("variant_unconfirmed", f"pack '{pack_size}' not found on page")
    page_packs = _page_pack_counts(text)
    if page_packs:
        want_n = _row_pack_count(normalise_text(pack_size))
        if len(page_packs) > 1 or want_n not in page_packs:
            seen = ", ".join(f"pack of {n}" for n in sorted(page_packs))
            return VariantCheck("pack_mismatch", f"page sells {seen}; row pack_size '{pack_size}'")
    return VariantCheck("ok")


def to_gst_inclusive(
    price: Decimal,
    page_basis: str,
    gst_pct: Decimal,
    assumed_basis: Optional[str],
) -> tuple:
    """Return (price_incl_gst, status). status is 'ok' or 'tax_unknown'."""
    basis = page_basis if page_basis in ("incl_gst", "excl_gst") else assumed_basis
    if basis == "incl_gst":
        return price, "ok"
    if basis == "excl_gst":
        return (price * (Decimal(1) + gst_pct / Decimal(100))).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        ), "ok"
    return price, "tax_unknown"
