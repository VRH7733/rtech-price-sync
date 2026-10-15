#!/usr/bin/env python3
"""Suggest marketplace URLs for catalogue rows by reading each site's PUBLISHED sitemaps.

  python tools/match_urls.py --brand polycab --source homerun
  python tools/match_urls.py --brand polycab --source moglix --max-sitemaps 40

Behaviour:
  * only reads sitemap files (robots.txt is checked for every request, 3 s per-host delay)
  * high-confidence match: writes the URL into the row's url_<source> cell ONLY if empty, and sets
    publish=pending_review, match_confidence=high. Never sets publish=yes.
  * low confidence: nothing is written; candidates go to review/<brand>_<source>.csv
  * to keep the crawl small it only follows child sitemaps whose URL mentions the brand, plus a
    capped number of others (--max-sitemaps)

STATUS: not yet run against the real sitemaps (build sandbox had no access). Expect to tune it.
"""
import argparse
import csv
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from rtech_sync.catalogue import load_catalogue, write_catalogue  # noqa: E402
from rtech_sync.config import load_config  # noqa: E402
from rtech_sync.fetcher import Fetcher  # noqa: E402
from rtech_sync.matching import best_candidates, decide_match, parse_sitemap  # noqa: E402

ROOT_SITEMAPS = {
    "moglix": "https://www.moglix.com/sitemap_index.xml",
    "industrybuying": "https://www.industrybuying.com/sitemap_index.xml",
    "homerun": "https://home-run.co/sitemap.xml",
}


def collect_urls(fetcher: Fetcher, source: str, brand: str, max_sitemaps: int) -> list:
    queue, seen, urls, n_other = [ROOT_SITEMAPS[source]], set(), [], 0
    while queue:
        sm = queue.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        mentions = brand.lower() in sm.lower()
        if len(seen) > 1 and not mentions:
            if n_other >= max_sitemaps:
                continue
            n_other += 1
        fr = fetcher.get(sm, budget_key=source)
        if fr.status != "ok":
            print(f"  skip {sm}: {fr.status} {fr.detail}")
            continue
        try:
            pages, children = parse_sitemap(fr.content)
        except Exception as e:  # malformed XML etc.
            print(f"  cannot parse {sm}: {e}")
            continue
        urls += [u for u in pages if brand.lower() in u.lower()]
        queue += children
    return urls


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", required=True)
    ap.add_argument("--source", required=True, choices=list(ROOT_SITEMAPS))
    ap.add_argument("--catalogue", default="catalogue")
    ap.add_argument("--max-sitemaps", type=int, default=30)
    ap.add_argument("--config", default=os.path.join(os.path.dirname(__file__), "..", "config.yaml"))
    a = ap.parse_args()
    cfg = load_config(a.config)
    cfg.fetch.require_contact_email()
    fetcher = Fetcher(cfg.fetch)

    path = Path(a.catalogue) / f"{a.brand.lower()}.csv"
    rows = load_catalogue(a.catalogue)
    mine = [r for r in rows if r.source_file.startswith(path.name + ":")]
    if not mine:
        print(f"No rows found in {path}")
        return 1
    urls = collect_urls(fetcher, a.source, a.brand, a.max_sitemaps)
    print(f"{len(urls)} candidate URLs mention '{a.brand}'")

    review = []
    wrote = 0
    for r in mine:
        if a.source in r.urls:
            continue
        cands = best_candidates(r, urls)
        url, conf = decide_match(cands)
        if url:
            r.urls[a.source] = url
            r.publish = "pending_review" if r.publish != "yes" else r.publish
            r.match_confidence = "high"
            wrote += 1
        for c in cands:
            review.append([r.sku, r.title, r.variant_hint, r.pack_size, a.source, c.url, c.score,
                           c.confidence, ";".join(c.missing)])
    write_catalogue(path, [r for r in rows if r.source_file.startswith(path.name + ":")])
    out = Path("review")
    out.mkdir(exist_ok=True)
    rp = out / f"{a.brand.lower()}_{a.source}.csv"
    with open(rp, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["sku", "title", "variant_hint", "pack_size", "source", "candidate_url", "score",
                    "confidence", "missing_tokens"])
        w.writerows(review)
    print(f"Wrote {wrote} high-confidence URLs into {path} (publish=pending_review).")
    print(f"Review the rest in {rp}. Nothing is live until you set publish=yes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
