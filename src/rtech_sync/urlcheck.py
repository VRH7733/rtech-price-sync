"""URL sanity helpers shared by the catalogue validator and the fetcher."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

_SEARCH_PATH = re.compile(r"/(?:catalog)?search|/find|/results?(?:/|$)|/s/", re.I)
_SEARCH_KEYS = {"q", "s", "search", "searchterm", "search_query", "query", "keyword", "keywords", "k"}


def is_search_url(url: str) -> bool:
    parts = urlsplit(url)
    if _SEARCH_PATH.search(parts.path or "") or "search" in (parts.path or "").lower():
        return True
    keys = {k.lower() for k in parse_qs(parts.query)}
    return bool(keys & _SEARCH_KEYS)


def bare_host(host: str) -> str:
    h = host.lower()
    return h[4:] if h.startswith("www.") else h


def same_site(a: str, b: str) -> bool:
    return bare_host(urlsplit(a).netloc) == bare_host(urlsplit(b).netloc)
