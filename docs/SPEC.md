# SPEC: daily price sync for rtechelectricals.com

Owner: Harshi (small electrical supplier, Yelahanka, Bengaluru). The owner starts work about 9 AM IST.
This spec is the agreed requirement. `docs/STATUS.md` says how much of it exists.

## Site and catalogue
- https://rtechelectricals.com, WordPress 7.0.6 + WooCommerce, on **Hostinger Premium shared hosting**.
- On 13 Oct 2026 all 79 products showed a SOLD OUT badge and no price; CTAs were "Check Availability"
  / "Request Project Price" linking to `/request-best-price/?rte_product_sku=WEB-058&rte_cta=availability`
  (SKUs look like `WEB-0xx`). Existing pages: /shop/, /brands/, /bulk-project-orders/, /upload-boq/,
  /request-best-price/. Do not break the quote flow.
- Brands: Polycab, KEI, Finolex, RR Kabel (wires/cables); GM, Hi-Fi, Legrand, Havells (switches, MCBs,
  boards); Sudhakar, Precision, VIP (pipes and fittings: conduit, PVC, CPVC); plus lugs, screws and
  small accessories. GM and Hi-Fi matter most (customers are mostly budget/mid-range). ABB is already
  in the shop: leave ABB alone.
- Bengaluru customers want every variety, so the catalogue will be HUGE (all brands, sizes, colours,
  lengths). Model each product family as a WooCommerce **variable product**; prices live on variations.
- Quote-only (no price): panel boards, raceways, cable trays. Show "Request Quote"; the owner prepares
  drawings (DWG) in-house.
- Add a Services page for electrician and plumber services (North Bengaluru).

## Price rule (owner's words, final)
- Sources: **only** Moglix, IndustryBuying, HomeRun. Product URLs come from the catalogue CSVs.
- Compare the sources. If the difference is **less than 5%**, publish the **cheapest**. If **5% or
  more**, do not publish; keep the old price and **flag it** so the owner can check later and set the
  price. Markup 0% (per-row override allowed). The owner resolves a flag by typing `manual_price`.
- Prices are GST-inclusive Rs per pack. Storefront text: "Indicative price incl. GST. Confirm before
  ordering. Updated <date>".

## Schedule
- Starts **00:00 IST** nightly (`cron: "30 18 * * *"`, GitHub cron is UTC). Target: finished and the
  flags issue posted by ~08:30 IST. If time runs out, stop gracefully, publish what is done, list the
  rows not refreshed. GitHub may start scheduled runs late.
- Design for 5,000 variants; make it configurable.

## Hard rules
- Obey each site's robots.txt programmatically **using the repo's own matcher** (`robots.py`;
  `urllib.robotparser` does not support wildcards). Findings on 14 Oct 2026:
  - IndustryBuying disallows `/product_details/*`, `/search/*`, `/categories*`; sitemaps are published.
  - Moglix disallows `/search*`, `/rfq*`, `/q/*`, and URLs with `?category=`, `?p=` etc. Product pages are not listed.
  - HomeRun disallows only `/search`, `/cart`, `/account`, `/login`, `/order-*`. Product pages are
    `/products/<handle>`, collections `/collections/<handle>`. Next.js on Shopify; variants exist;
    prices depend on the delivery pincode (it showed 560035).
  - Never use search pages. If a source blocks, mark it `blocked`/`robots_blocked` and tell the owner.
- Polite: honest User-Agent with the owner's business contact email (env `RTECH_CONTACT_EMAIL`),
  >= 3 s between requests to one host across all jobs, one backoff retry on 429/5xx. Never shard so the
  rate to one host goes up. No proxy rotation, spoofed browsers, stealth plugins, captcha solving.
- Never commit secrets. GitHub Secrets `WC_URL`, `WC_KEY`, `WC_SECRET`; git-ignored `.env` locally.
- Never delete products. Back up all prices before the first live publish; keep the rollback tool.
- No invented claims on the site: no fake reviews, certifications, years in business or prices.
- Create new site content as DRAFT only. Do not change hosting or plans yourself.
- Do not use the owner's personal email anywhere that is sent to third parties.

## Decision rules per row per run (implemented in `decision.py`)
1. `manual_price` set -> publish it, skip auto logic.
2. 2+ usable sources: spread = (max-min)/min. < 5% -> cheapest x (1+markup), rounded up to next Rs 1.
   >= 5% (exactly 5.00% counts) -> flag `spread_over_5pct`, hold the previous price.
3. Exactly 1 usable source: publish only if within 5% of the last published price; else flag
   `single_source_jump`; no baseline -> `single_source_no_baseline`.
4. 0 usable: hold; flag `no_sources` (or `no_urls`).
5. Below `cost_floor` -> hold, flag `below_cost_floor`.
6. > 15% move vs last published -> flag `big_move` (publish unless `big_move_holds`).
7. Stale guard: no validated price for 3 days (counted from `last_ok`, or `first_seen` if never validated) -> hide price (empty regular_price, meta
   `_rte_price_hidden=1`) and show the "Request price" CTA; flag `stale`; auto-restore on fresh data.
8. Variant confirmed from the page's own title/attributes; if not -> `variant_unconfirmed`;
   different pack -> `pack_mismatch`; GST basis unknown -> `tax_unknown`. Excluded sources are flagged.

## Publisher (gentle on Hostinger shared hosting)
- WooCommerce REST `wc/v3`, products batch or `products/{id}/variations/batch`. Push only changed values.
- Batches <= 25, 2 s pause, backoff on 429/502/503/504/508, stop on repeated failure
  (`publish_throttled`), 401/403 is fatal (firewall/keys). Sets `regular_price`, clears `sale_price`,
  `stock_status=instock`, meta `_rte_price_updated_at`, `_rte_price_hidden`.
- Dry-run is the default; live needs `--publish`.

## Reporting
- `data/latest.json` (state), `data/history/YYYY-MM-DD.csv` (changed rows, 30 days then monthly),
  `data/flags.csv`, `data/summary.md`. A GitHub Issue "Price flags YYYY-MM-DD" (label `price-flag`)
  with a table of SKU, each source's price, spread, reason and clickable URLs.

## Phases and stop gates
- **Phase 0 recon (read-only):** ask the owner in ONE batch (is the repo private; WooCommerce REST keys
  created; delivery pincode, propose 560064; rough product/variant count). Verify GitHub Actions limits
  and Hostinger Premium limits from their docs. Run the `connectivity-test` workflow (firewall test).
  Export the 79 existing products. Find how the SOLD OUT badge and CTA are produced (theme, plugin,
  mu-plugin).
- **Phase 1 build/fix:** real fixtures, parsers, per-brand catalogue CSVs, variable-product model.
  **STOP 1:** show repo state, passing tests, Phase 0 findings.
- **Phase 2 pilot:** one brand (Polycab), >= 100 rows across all three sources incl. pipes, dry run,
  show table (product, each price, spread, decision). Report measured requests per host, runtime,
  projected Actions minutes/month. If over the free allowance or the overnight window, lay out options
  with cost: (a) fewer requests via listing pages, (b) public repo with sensitive columns kept out,
  (c) self-hosted runner on a PC that is on at midnight, (d) paid plan; recommend one.
  **STOP 2:** wait for the owner's decision.
- **Phase 3 automation:** enable the workflow in dry-run; list the secrets/variables to add.
  **STOP 3:** after approval, live-publish 3 products, verify on the site, then enable all.
- **Phase 4 site changes (drafts):** fix stock status so SOLD OUT disappears for priced products;
  quote categories keep Request Quote with a line about in-house drawings; draft variable-product shells
  for missing brands and a "Pipes & Fittings" category; draft the Services page; measure shop speed
  with the bigger catalogue and report whether hosting is the bottleneck (caching first, then upgrade;
  do not upgrade yourself).
- Matching at scale (`tools/match_urls.py`): strict keys brand + model + size/colour/length/class;
  nothing becomes `publish=yes` without the owner's approval.

## Finish
README covers onboarding a brand, reviewing matches, flags, `manual_price`, rollback, pausing.
End with a short report: done, blocked, what the owner needs to do next.
