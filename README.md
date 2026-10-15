# rtech-price-sync

Every night a GitHub Action looks up each product's price on Moglix, IndustryBuying and HomeRun,
compares them, and updates the price on **rtechelectricals.com** (WooCommerce).

**The pricing rule (set by the owner):**

| Situation | What happens |
|---|---|
| 2+ sites agree within **less than 5%** | the **cheapest** price is published (markup 0%, rounded up to the next rupee) |
| sites differ by **5% or more** | **nothing is published**, the old price stays, and the item is **flagged** for you |
| only 1 site worked | published only if within 5% of the live price, otherwise flagged |
| you type a `manual_price` | that price is published and the marketplaces are not checked for that row |
| price would drop below your `cost_floor` | held and flagged |
| no fresh price for 3 days | price is hidden (shows "Request price") so an old price never lingers |

> Status: **starter kit.** The rules, safety checks, publisher and workflow are built and tested
> (132 tests). The page parsers are tested on *synthetic* pages only. Read `docs/STATUS.md`
> before trusting it with real money.

## One-time setup (about 15 minutes)

1. Create a **private** GitHub repo and push this folder to it.
2. In WooCommerce: *Settings > Advanced > REST API > Add key* (Read/Write). Copy the key and secret.
3. In the GitHub repo: *Settings > Secrets and variables > Actions*
   - **Secrets:** `WC_URL` (`https://rtechelectricals.com`), `WC_KEY`, `WC_SECRET`
   - **Variables:** `RTECH_CONTACT_EMAIL` (a business email; it is shown to the marketplaces in the
     User-Agent so they can contact you), `PUBLISH_MODE` = `dry-run` (change to `publish` to go live)
4. Run the **connectivity-test** workflow (Actions tab). It checks that GitHub can reach your shop
   and the three marketplaces. If it fails, fix that first (see `docs/STATUS.md`).
5. Back up prices: `python tools/backup_and_rollback.py backup` (needs the same keys in `.env`).

## Daily life

- The job starts at **00:00 IST** (cron `30 18 * * *`; GitHub can start it up to an hour late).
- Check the **Issues** tab each morning: *Price flags YYYY-MM-DD* lists every item that needs a look,
  with clickable links to the three product pages and each site's price.
- To fix a flagged item: open `catalogue/<brand>.csv`, put your price in the `manual_price` column
  for that SKU, commit. It goes live on the next run. Clear the cell to return to automatic pricing.
- To pause everything: set the repo variable `PUBLISH_MODE` to `dry-run` (it still collects data
  but changes nothing on the shop), or disable the workflow.
- To undo: `python tools/backup_and_rollback.py restore data/backup/products_<date>.json --apply`.

## Adding products

Each brand has a file `catalogue/<brand>.csv`. Copy `catalogue/_template.csv.example`.
Key columns: `sku`, `wc_product_id` (+ `wc_variation_id` for variable products), `variant_hint`
(what identifies the exact item, separated by `;`, e.g. `1.5 sq mm; red`), `pack_size` (e.g. `90 m`),
the three `url_*` columns (exact **product page** URLs, never search pages), and `publish`.

`publish` has three values: `no` (ignored), `pending_review` (matched but not approved) and `yes`
(live). Nothing publishes until you set `yes`.

Check one URL before adding it:

    python tools/add_url.py --source moglix --url "https://www.moglix.com/..." --hint "1.5 sq mm; red" --pack "90 m"

Suggest URLs from the sites' own sitemaps (suggestions only, you approve):

    python tools/match_urls.py --brand polycab --source homerun

## Run locally

    pip install -r requirements.txt
    python -m pytest                       # all tests
    export RTECH_CONTACT_EMAIL=you@yourbusiness.in
    PYTHONPATH=src python -m rtech_sync.run            # dry run, changes nothing
    PYTHONPATH=src python -m rtech_sync.run --publish  # live (needs WC_URL, WC_KEY, WC_SECRET)

Outputs go to `data/`: `flags.csv`, `flags_issue.md`, `summary.md`, `dryrun_plan.csv` (dry run) or
`history/YYYY-MM-DD.csv` + `latest.json` (live).

## What this will never do

It reads only the product URLs you list, obeys each site's `robots.txt`, waits 3 seconds between
requests to the same site, and identifies itself honestly. If a site blocks it, the source is
reported as blocked. It does not rotate proxies, fake a browser or solve captchas.

## Layout

    config.yaml            thresholds, delays, budgets
    catalogue/*.csv        one file per brand (you edit these)
    src/rtech_sync/        decision.py (the rules), parsers.py, fetcher.py, robots.py, publisher.py, run.py ...
    tools/                 add_url, match_urls, backup_and_rollback, check_connectivity
    data/                  written by the bot: latest.json, history/, flags.csv
    docs/SPEC.md           the full requirements
    docs/STATUS.md         what is done, what is not, what to do next
    CLAUDE.md              instructions for Claude Code
