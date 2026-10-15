"""Candidate URL matching from sitemap/listing URLs. Pure functions + a sitemap reader.

Nothing here writes publish=yes. High-confidence matches are written with publish=pending_review
and low-confidence ones go to a review queue; the owner approves in bulk.

STATUS: logic is unit-tested on synthetic slugs only. It has NOT been tried on the real
Moglix / IndustryBuying / HomeRun sitemaps (they were unreachable from the build sandbox).
"""
from __future__ import annotations

import gzip
import re
from dataclasses import dataclass
from urllib.parse import urlsplit
from xml.etree import ElementTree

from .models import Row
from .normalise import normalise_text, split_hint

_SLUG_JUNK = {"buy", "online", "at", "best", "price", "india", "in", "the", "and", "of", "for", "with"}


def slug_text(url: str) -> str:
    path = urlsplit(url).path
    parts = [p for p in path.split("/") if p]
    # Moglix product URLs end in an id ("/<name-slug>/mp/msn2qrg0ab50gd"): use the longest
    # hyphenated segment, which is the product name on all three sites
    named = [p for p in parts if "-" in p]
    last = max(named, key=len) if named else (parts[-1] if parts else "")
    last = re.sub(r"\.(html?|php)$", "", last)
    return normalise_text(re.sub(r"[-_+]+", " ", last))


def _tokens(text: str) -> set:
    return {t for t in re.split(r"[^a-z0-9.]+", text) if t and t not in _SLUG_JUNK}


@dataclass
class Candidate:
    url: str
    score: float
    confidence: str  # high | low
    missing: list


def score(row: Row, url: str) -> Candidate:
    slug = slug_text(url)
    slug_tokens = _tokens(slug)
    if not row.brand or row.brand.lower() not in slug:
        return Candidate(url, 0.0, "low", ["brand"])
    hint_tokens = [normalise_text(t) for t in split_hint(row.variant_hint)]
    if row.pack_size:
        hint_tokens.append(normalise_text(row.pack_size))
    missing = []
    for t in hint_tokens:
        # slugs write "1.5" as "1-5", so a decimal point may appear as a space in the slug
        pat = re.escape(t).replace(r"\.", r"[\s.]").replace(r"\ ", r"\s*")
        if not re.search(r"(?<![0-9a-z.])" + pat + r"(?![0-9a-z])", slug):
            missing.append(t)
    title_tokens = _tokens(normalise_text(row.family or row.title))
    overlap = len(title_tokens & slug_tokens) / len(title_tokens) if title_tokens else 0.0
    hint_ok = 1.0 - (len(missing) / len(hint_tokens)) if hint_tokens else 0.0
    sc = round(0.6 * hint_ok + 0.4 * overlap, 3)
    conf = "high" if (not missing and hint_tokens and overlap >= 0.6) else "low"
    return Candidate(url, sc, conf, missing)


def best_candidates(row: Row, urls: list, top: int = 3) -> list:
    cands = [score(row, u) for u in urls]
    cands = [c for c in cands if c.score > 0]
    cands.sort(key=lambda c: -c.score)
    return cands[:top]


def decide_match(cands: list) -> tuple:
    """(url or None, confidence). Accept as 'high' only if the best is high and clearly ahead."""
    if not cands:
        return None, "none"
    best = cands[0]
    if best.confidence == "high" and (len(cands) == 1 or best.score - cands[1].score >= 0.15):
        return best.url, "high"
    return None, "low"


def parse_sitemap(xml_bytes: bytes) -> tuple:
    """Return (page_urls, child_sitemap_urls). Handles gzip and sitemap indexes."""
    if xml_bytes[:2] == b"\x1f\x8b":
        xml_bytes = gzip.decompress(xml_bytes)
    root = ElementTree.fromstring(xml_bytes)
    ns = {"s": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}
    q = "s:" if ns else ""
    locs = [e.text.strip() for e in root.findall(f".//{q}loc", ns) if e.text]
    if root.tag.endswith("sitemapindex"):
        return [], locs
    return locs, []
