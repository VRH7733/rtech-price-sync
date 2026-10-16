# STATUS (updated 15 Oct 2026, LIVE)

## LIVE since 15 Oct 2026 (owner's approvals typed in the project thread)

- Rule: publish the CHEAPEST of HomeRun, Moglix, IndustryBuying every morning (starts 01:00 IST, backup
  03:00 IST if the first did not fire; the 15 Oct 23:30 UTC schedule never fired), one site is
  enough; LiteSpeed purges /product/ etc. at 07:30 IST (Harshi, 16 Oct); `shop-check.yml`
  (read-only) compares the live shop with data/latest.json. No price => in-stock "Request a Quote" product. Code: `decision.py` (rule: cheapest).
- Guards (all send the product to Request a Quote or hold, never to a guessed price):
  outlier_ratio 2 (per product), low outlier, big move >40% held a day, `siblings.py`
  sibling_ratio 2 (single-site wire vs same brand/sqmm/cores/length), needs_second_site
  (IndustryBuying "-ELE." seller listings alone are not trusted: 33 of 33 that another site also
  had were 2-9x dearer, median 4.6x).
- Catalogue: 1,749 rows, 1,730 live products for Polycab, Havells, Legrand, Finolex, KEI, VIP,
  RR Kabel, Hi-Fi, GM (rows built by `tools/rows_from_discovery.py`, products by
  `create-drafts.yml` live=true). Precision and Sudhakar: nothing found.
- Run 38747693016 (15 Oct, verified on the Store API): 654 priced with Add to cart, 1,043 Request
  a Quote, 0 publish failures, 76 min, no blocks or 429s.
- Open: IndustryBuying discovery reached 1,500 of 6,053 brand URLs; `discover.yml` with
  previous=discovery/2026-10-15 continues it. Single-site prices from IndustryBuying "EL." listings
  are still trusted and some look high (not verified).

Read this first. It says what is real, what is a guess, and what to do next.
"Verified" below means checked against the REAL sites, the REAL shop or an official doc, with the
evidence named. Everything else is still a guess.

## Built and tested (292 passed, 2 skipped at go-live; 269 after STOP 2; 251 at STOP 2; 239 at STOP 1; 178 at the starter-kit build)

An independent adversarial review found 15 confirmed bugs (one critical: the parser could take the
price of the wrong Product node in JSON-LD). All were fixed with regression tests in
`tests/test_review_regressions.py`.

| Area | File | Notes |
|---|---|---|
| Price rules | `decision.py` | cheapest if spread < 5%; flag + hold if >= 5%; single-source, manual_price, cost_floor, big_move, stale guard |
| Variant/pack safety | `normalise.py` | a source is used only if the page's OWN title/attributes confirm size/colour/length/pack |
| robots.txt | `robots.py` | own RFC 9309 matcher (wildcards `*` and `$`). Python's `urllib.robotparser` does NOT support wildcards, and Moglix's robots.txt uses them. Do not replace it with robotparser. |
| Polite fetching | `fetcher.py`, `urlcheck.py` | per-host 3 s delay (www and bare host share one slot), Crawl-delay honoured, 1 backoff retry, per-host budget, redirects followed manually (max 5, robots re-checked on every hop, search-page or off-site redirects refused), 403/429 => "blocked" (never worked around) |
| Publisher | `publisher.py` | batches of 25, pauses, backoff on 429/502/503/504/508, stops after repeated failures, dry-run default |
| Run + reports | `run.py`, `report.py` | oldest-refreshed first, time budget, flags CSV, issue body (<65k chars), history rotation |
| Workflows | `.github/workflows/` | nightly 00:00 IST, flip live by repo variable `PUBLISH_MODE`; manual connectivity test |
| Tools | `tools/` | add_url, match_urls, backup_and_rollback, check_connectivity |

## Verified on 14-15 Oct 2026

### Marketplaces (real pages)

| Source | Real fixtures | Parser on real pages | Tax basis | Bot fetch from owner's PC, 15 Oct 05:49 IST |
|---|---|---|---|---|
| HomeRun (home-run.co) | 8 pages, `tests/test_real_homerun.py` | JSON-LD price is right only with `?variant=ID`; URLs without it are refused (`variant_not_selected`) | `incl_gst` ("Incl GST" in the price block) | 14/14 HTTP 200, prices = expected 14/14 |
| IndustryBuying | 6 pages, `tests/test_real_industrybuying.py` | JSON-LD price = incl-GST figure on 6/6, no problems | `incl_gst` ("(Incl. of all taxes)") | 6/6 HTTP 200, prices = expected 6/6 |
| Moglix | 6 pages, `tests/test_real_moglix.py` | JSON-LD price = incl-GST figure on 5/6; the 6th (GM switch) is refused, see below | `incl_gst` ("(Incl. of all taxes)") | 6/6 HTTP 200, 5/6 = browser capture; blue wire 3299 -> 3300 (price changed on Moglix's side, inferred) |

- IndustryBuying product URLs are `/<category>-<brand>-<SKU>`, NOT the robots-blocked
  `/product_details/`. The repo's robots matcher allows all 6 (test). Each variant is its own URL.
- Moglix: each variant is its own `/mp/msn...` URL. "AVAILABLE ON REQUEST" pages are JSON-LD
  `OutOfStock` with no Add to Cart: excluded as `out_of_stock` (3 of 6 sample pages, incl. the GM
  switch and the Legrand pack).
- Moglix GM switch: JSON-LD says 1840 but the page shows only "MRP ₹92" (1840 = 20 x 92, probably a
  box of 20). The existing `price_not_visible_in_text` rule refuses it. This rule is now proven
  necessary on a real page; keep it.
- NEW rule (`normalise.py`, tests in `test_normalise.py` and `test_real_moglix.py`): a page whose
  title says "pack of N" / "set of N" / "box of N" (N > 1) is `pack_mismatch` unless the row's
  `pack_size` says the same N ("pack of 5" or "5 pcs"). Before this, a row with an empty
  `pack_size` would have taken Moglix's 5-pack price as a single-switch price.
- Nothing was blocked: 29/29 requests HTTP 200, no captcha/block markers, robots.txt read on all
  three hosts, no Crawl-delay, min gap 3.000 s per host. Evidence:
  `docs/evidence/bot-check-2026-10-15/` (REPORT.md, results.csv; contact email redacted).
- `assumed_tax_basis: incl_gst` is now set for all three sources in `config.yaml`.
- `tzdata` added to `requirements.txt`: Windows has no IANA time zones, and
  `test_cli_publish_requires_woo_env` failed there without it.

### IndiaMART (look only, reference source, NOT a price source)

Checked 15 Oct in the owner's browser, 4 page views, nothing saved: robots.txt for `User-agent: *`
allows `/proddetail/` and `dir.indiamart.com/impcat/` pages (it disallows `/pd/`, `/proddetail1|2`,
`*/search.html`, `search.mp`) and blocks a list of named crawlers. A category page for 1.5 sq mm
Polycab wire showed 33 seller prices from ₹950 to ₹4,250 per 90 m plus per-roll and per-metre
prices with roll length often missing; a product page shows one seller's price ("₹ 1,905/Roll",
city Pune) and the words "Excluding all taxes" elsewhere on the page. These are seller-entered
asking prices, not a shop price, so they stay out of the price rule (as decided). Useful only as
a "market range" column in a report, if wanted later. Not built.

### GitHub (official docs, read 15 Oct)

- Code repo `rtech-price-sync` is PUBLIC; data repo `rtech-price-data` is PRIVATE.
- Public repos on standard GitHub-hosted runners: Actions minutes are free
  (docs.github.com/en/billing/concepts/product-billing/github-actions). Private repos on Free: 2,000
  min/month, 500 MB artifacts, 10 GB cache per repo.
- Job limit 6 h ("Each job ... up to 6 hours of execution time"); 20 concurrent jobs on Free
  (docs.github.com/en/actions/reference/limits).
- Scheduled runs "can be delayed during periods of high loads" and "some queued jobs may be
  dropped"; our cron is at minute 30, not the busy top of the hour. Scheduled workflows in a PUBLIC
  repo are auto-disabled after 60 days with no repo activity (the nightly data commit goes to the
  DATA repo, so the code repo needs its own activity or a manual re-enable).
- `GITHUB_TOKEN` only covers its own repo, so the private data repo needs `DATA_REPO_TOKEN`
  (already set up: see below).
- GitHub-hosted runners run in Microsoft Azure (relevant to Hostinger's rate limits).

### Hostinger Premium (official docs, read 15 Oct)

- Web Premium: 1 CPU core, 2 GB RAM, 40 PHP workers, PHP max execution 360 s, 400,000 inodes,
  MySQL 50 connections/user; website count depends on purchase date (3 / 25 / 100)
  (hostinger.com/support/6976044-parameters-and-limits-of-hosting-plans-in-hostinger/).
- Hostinger applies server-level rate limits to traffic "from specific network ranges", naming
  Microsoft, returning HTTP 429; not per plan, cannot be turned off; fix = back off and retry
  (hostinger.com/support/429-errors-on-automated-integrations-and-link-previews/). The publisher
  already backs off on 429. Risk for nightly publishing from GitHub (Azure); no numbers published.
- Hostinger CDN can 403 legitimate REST API calls; fixes are lowering its security level or
  disabling the CDN to test (hostinger.com/support/hostinger-cdn-how-to-fix-blocked-legitimate-requests/).
- Not found in official docs: entry-process limits for Web Premium, any user-agent blocking.

### Shop (rtechelectricals.com)

- `connectivity-test` workflow, run 14 Oct 11:47 UTC from a GitHub runner: public REST root HTTP
  200, authenticated `wc/v3/products` HTTP 200, 79 products, "RESULT: reachable and keys work".
  So WooCommerce REST keys exist and work, and the runner was not blocked at that (tiny) volume.
- `export-products` workflow, run 14 Oct 12:02 UTC: success; backup committed to the private data
  repo (counts only in the public log). The 79 products are the export.
- All 79 products (public Store API, 14 Oct): type `variable`, price 0, `is_in_stock` false,
  `is_purchasable` false. Brands: Polycab 45, ABB 15, Legrand 13, Precision 6. The owner has said
  these 79 are placeholders.
- SOLD OUT badge: made by the **Blocksy theme** (`span.out-of-stock-badge`, parent theme blocksy
  2.1.52, child theme `rtechelectricals-child`) because every product's WooCommerce stock status is
  `outofstock`. Additional CSS "RTE P9 quote-only product display 2026-09-10" hides the badge only
  where a quote CTA is shown on a single product page.
- "Check Availability" / "Request Project Price" buttons: made by the custom plugin
  **RTechElectricals P6 Sprint** (`wp-content/plugins/rte-p6-sprint`, module "P608"), read from the
  9 Sep site backup in the owner's Downloads (the live copy may have changed since). It:
  - hard-codes WEB-001..WEB-077, WEB-099, WEB-100: 9 always "Request Project Price", 39 always
    "Check Availability", 31 "Add to Cart" only if safe;
  - filters `woocommerce_is_purchasable`: "safe" needs published + price > 0 + **managed stock with
    quantity > 0** + instock. Setting `stock_status=instock` alone (what `publisher.py` does) will
    NOT bring back Add to Cart for these SKUs, and the 48 quote SKUs stay quote whatever the price;
  - does not touch products outside that SKU list (new products behave as normal WooCommerce).
  Phase 4 must decide this with the owner before any live publish.

## Still NOT verified

1. Behaviour at full volume (about 1,300 rows a night). The Phase 2 pilot (137 rows, 248
   requests) ran from GitHub runner IPs with no blocks; full volume is projected, not measured.
2. Hostinger at publish volume from Azure IPs (see the 429 note above).
3. Moglix has no `expected.json`-style ground truth beyond the 6 captured pages; real catalogue
   rows will hit page types not seen yet (e.g. pages without JSON-LD).
4. `tools/match_urls.py` was tested on synthetic slugs only. The pilot used `tools/discover.py` +
   `tools/match_discovery.py` on the real sitemaps instead.
5. The P6 Sprint plugin was read from a 9 Sep backup, not the live site.
6. Shop-side changes (Phase 4) are not done: SOLD OUT removal, "Request price" display,
   "Indicative price incl. GST" text, variable-product shells, Services page.
7. FIXED 15 Oct: `daily-prices.yml` now reads the catalogue from and commits `data/` to the PRIVATE
   data repo, and opens the flags issue there (verified: pilot run 38694515650, data-repo issue #1).
   The schedule stays off until STOP 3.
8. `publish=yes` rows need `wc_product_id`/`wc_variation_id`; the 79 placeholders will not be used,
   so new products have to be created first (Phase 4 drafts).

## Capacity maths (assumptions: 3 s per request per site, the 3 sites run in parallel)

- One request per product page per site. N products with all 3 URLs => about N x 3 s wall time.
- Measured 15 Oct (29 requests from the owner's PC): mean gap per host 3.9-4.6 s.
- Measured 15 Oct, Phase 2 pilot on GitHub (run 38694515650): 137 rows, 248 requests (Moglix 94,
  IndustryBuying 110, HomeRun 44), fetch 6.4 min, job 7.0 min, about 3.5 s per request on the
  busiest site. Projected with the same URL mix: 1,300 rows ~1 h, 5,000 rows ~3.9 h (inside the
  300 min fetch cap and 6 h job cap, little spare).
- The code repo is PUBLIC, so the nightly job's Actions minutes are free (official docs, above).
  Keep `cost_floor`, `manual_price` and markup columns in the PRIVATE data repo only.
- Fewer requests are possible if a site's collection/listing pages return many prices at once
  (check robots first). Not implemented yet.

## Phase 2 pilot result (prices are in the private data repo, docs/STOP2.md)

- Under the agreed rule, 0 of 137 Polycab rows would publish: 86 single-source, 43 with a spread of
  44% or more, 8 with no usable source. The rule worked as designed; it was not changed.
- IndustryBuying lists some products twice: one listing near list price and one (ELE.FLA.* ids)
  at about 3-5x, with the same title, 90 m, minimum order 1 (checked in a browser 15 Oct).
- Moglix: 72 of 93 Polycab wire URLs were out of stock ("available on request").
- Polycab conduit pipes were found on IndustryBuying only.
- Owner decisions open at STOP 2: price-rule handling of these cases, which wire lines to sell,
  pipes, rows with no source.

## Deviations from the original brief (deliberate)

- `last_ok_date` lives in `data/latest.json`, not in the catalogue CSV, so the bot never edits the
  CSVs you edit by hand (no merge conflicts).
- `gst_pct` column added (default 18) for sources that quote prices excluding GST.
- Manual-price rows are not fetched (`fetch_for_manual_rows: false`) to save requests.
- `big_move` (>15%) flags but still publishes; set `big_move_holds: true` to hold instead.
- A flagged item that stays unresolved for 3 days is hidden (stale guard), by design. The clock
  is `last_ok`, or `first_seen` for rows that never had a validated price.
- Fetching stops after `max_runtime_minutes: 300` so publishing and the commit fit inside the 6 h cap.

## Known weaknesses found by review but NOT fixed

- Tax-basis detection reads the whole page text. On all 20 real pages it gave the right answer
  (`incl_gst`), and a page that says both incl and excl falls back to `assumed_tax_basis`
  (`incl_gst` for all three). Left as is; narrowing to the price block needs per-site selectors.
- `itemprop` price extraction takes the first match (no real page needed it: all 20 had JSON-LD).
- JSON-LD with related-product nodes may over-exclude (multi_variant). Not seen on the 20 real
  pages (each had one Product node).
- A row switched from priced to quote keeps its last live price in the shop. Handle in Phase 4.

## Next steps

1. DONE: STOP 1 answered 15 Oct (pincode 560065, ~1,300 items, business contact address, keys
   read/write, new SKUs, code pushed with the schedule off).
2. DONE: Phase 2 pilot. STOP 2 answered 15 Oct: option B (outlier_ratio 2 + manual_price alert,
   in code and config), all four wire lines, pipes wait for a second source, 8 no-source rows left
   out. Re-run with the guard (run 38698128192): still 0 auto-publishable of 129, because after
   ignoring IB's inflated listings 122 rows are single-source with no earlier price.
3. STOP 3 prep: the owner fills `your_price_incl_gst` in the private
   `catalogue/review/your_prices_2026-10-15.csv`; `tools/import_prices.py` copies it into
   `manual_price`; `create-drafts.yml` (plan-only by default) creates DRAFT products for 3 SKUs;
   then, with the owner's approval, publish those 3 and check them on the site. The nightly
   schedule is still OFF; turning it on (dry run) needs the owner's explicit OK.
4. Phase 3/4 as in SPEC, after deciding how the P6 Sprint plugin and the publisher fit together.
