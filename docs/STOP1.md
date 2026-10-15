# STOP 1 report (15 Oct 2026)

Work is stopped here until the owner answers the questions at the end. Details and evidence for
every line are in `docs/STATUS.md`.

## Repo state

- Local repo (not pushed): 3 commits on top of the starter kit: Baseline, HomeRun real fixtures,
  and this STOP 1 commit (Moglix + IndustryBuying real-page tests, pack-of-N guard, tax basis,
  tzdata, STATUS, evidence).
- GitHub `VRH7733/rtech-price-sync` (public) has only the two Phase 0 workflows
  (`connectivity-test`, `export-products`) and `tools/export_products.py`. The bot code itself
  is NOT on GitHub yet.
- `python -m pytest`: **239 passed, 2 skipped** (Linux, Python 3.13). The 2 skips are by design
  (HomeRun fixtures fetched with an explicit variant).

## Parsers on real pages

| Source | Verified on real pages | Price basis | Notes |
|---|---|---|---|
| HomeRun | yes, 8 pages + bot re-fetch 14/14 | incl GST | price only with `?variant=ID` URLs |
| IndustryBuying | yes, 6 pages + bot re-fetch 6/6 | incl GST | product URLs are not robots-blocked |
| Moglix | yes, 6 pages + bot re-fetch 6/6 HTTP 200 | incl GST | 3 of 6 sample pages "AVAILABLE ON REQUEST" (out of stock, excluded); one JSON-LD price not on the page (refused); new pack-of-N guard |

Bot fetch from your PC (15 Oct 05:49 IST, the repo's own Fetcher, honest User-Agent): 29/29
HTTP 200, no blocks, min 3.0 s gap per host, prices matched on 25/26 (Moglix blue wire 3299 ->
3300, a Moglix price change). Not verified: full nightly volume, and fetching from GitHub's IPs.

## Phase 0 findings

- WooCommerce REST keys exist and work from a GitHub runner (connectivity-test, 14 Oct: HTTP 200,
  79 products). Product export ran and is in the private data repo.
- GitHub: public repo => Actions minutes free; 6 h job cap; scheduled runs can be late or dropped;
  public-repo schedules switch off after 60 days without repo activity.
- Hostinger Premium: 1 CPU, 2 GB RAM, 40 PHP workers. Hostinger rate-limits traffic from
  Microsoft IP ranges (GitHub runners are on Azure) with HTTP 429 and no published thresholds;
  the publisher already backs off on 429. Hostinger CDN can 403 REST calls.
- SOLD OUT badge: Blocksy theme, because all 79 products are `outofstock` with price 0.
- Check Availability / Request Project Price: your custom plugin "RTechElectricals P6 Sprint"
  (P608). It hard-codes the WEB-001..WEB-100 SKUs and only allows Add to Cart when stock is
  MANAGED with quantity > 0, so the bot setting "in stock" alone would not change those 79.
  New products with new SKUs are not affected by it.
- IndiaMART (look only): seller-entered prices that vary widely (₹950 to ₹4,250 per 90 m for the
  same wire on one category page). It stays a reference only, as decided.
- Found gap: `daily-prices.yml` would put catalogue, prices and the flags issue in the PUBLIC
  code repo. It must be rewired to the private data repo before it is enabled (Phase 3).

## Questions for the owner (one batch)

1. Delivery pincode for HomeRun: you said **560065** earlier (the spec proposed 560064). Use 560065?
2. First live catalogue size: about **1,300** products/variants, as you said. Still right?
3. Contact email: the bot check used the address in your `CONTACT_EMAIL` secret. Is that the
   business address to use for every request? (yes/no)
4. Are the WooCommerce keys **Read/Write**? (The test only read; publishing needs write.)
5. The 79 placeholder products: priced items will be NEW products with new SKUs, so the P6 Sprint
   plugin leaves them alone and the 79 stay as they are (never deleted). Recommended. OK?
6. Push the code to the public GitHub repo now, with the nightly schedule OFF until the Phase 3
   rewiring is done? Recommended: yes.
