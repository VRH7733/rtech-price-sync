# rtech-price-sync bot fetch check (from this PC)

Run: 2026-10-15, 05:48:52 to 05:49:47 IST, from DESKTOP-6QNT62G on this PC's own connection.
Code: `rtech-price-sync-2026-10-15.zip`, unzipped to `%USERPROFILE%\rtech-bot-check\rtech-price-sync` (not modified).
Script: `%USERPROFILE%\rtech-bot-check\bot_check.py` (outside `src/`). It calls `Fetcher.get(url, budget_key=site)` and then
`rtech_sync.parsers.parse_product_page()` with the repo's own config (`config.yaml`: 3 s per host, 1 retry, 20 s retry wait).

User-Agent sent on every request (from `FetchCfg.user_agent`, `RTECH_CONTACT_EMAIL=<business email from RTECH_CONTACT_EMAIL>`):

```
rtech-price-sync/0.1 (+mailto:<business email from RTECH_CONTACT_EMAIL>; price comparison for rtechelectricals.com)
```

No browser, proxy, browser User-Agent, captcha solving or search page was used. rtechelectricals.com was not contacted.

## Setup

- venv on Python 3.13.1 (`pyproject.toml` needs >= 3.12; the PC's default `python` is 3.11.9, so `py -3.13` was used).
- `pip install -r requirements.txt`, then `python -m pytest`: first run **1 failed, 196 passed, 2 skipped**. The failure was
  `tests/test_cli_and_report.py::test_cli_publish_requires_woo_env` with `ZoneInfoNotFoundError: 'No time zone found with key Asia/Kolkata'`,
  because Windows ships no IANA time-zone database. Environment fix only: `pip install tzdata` in the venv.
  Second run: **197 passed, 2 skipped** (both skips: `tests/test_real_homerun.py:53: fixture was fetched with an explicit variant`).
  Note: `tzdata` is not in `requirements.txt`, so a fresh Windows install will hit the same failure.

## URLs checked (26)

| Site | URLs | Where they came from |
|---|---|---|
| HomeRun (home-run.co) | 14 | 8 entries in `tests/fixtures/real/homerun/expected.json`, plus the `?variant=<id>` form for the 6 entries whose URL had no variant (id taken from "Shopify variant <id>" in `notes`) |
| IndustryBuying | 6 | `tests/fixtures/real/industrybuying/expected.json` (same 6 URLs are in `rtechfx_industrybuying_bundle_1792000295623.json`) |
| Moglix | 6 | `rtechfx_moglix_bundle_1792000337984.json`. `tests/fixtures/real/moglix/` has no `expected.json`, so there is no ground-truth price for Moglix |

The robots.txt entries in the two bundles were not fetched as pages; the Fetcher reads robots.txt itself (once per host).
Bundles were checked at the start and again at the end: the same two files both times (last modified 2026-10-14 23:21 and 23:22 IST), no new ones.

## Per-site results

"Browser price" = the same parser run on the HTML captured earlier in the owner's Chrome (fixture or bundle).
"Expected" = `selling_price` in `expected.json`.

### HomeRun: real pages, HTTP 200, prices match on 14/14

| Page | HTTP | Bot price | Expected | Browser price |
|---|---|---|---|---|
| polycab-optima-wire-lf-fr | 200 | 2112 | 2112 | 2112 |
| …?variant=50073589252411 | 200 | 2112 | 2112 | 2112 |
| …?variant=50073590432059 | 200 | 8567 | 8567 | 8567 |
| …?variant=50073589645627 | 200 | 4875 | 4875 | 4875 |
| vip-electrical-conduit-pipe-frls-3m-length (and ?variant=49812502511931) | 200, 200 | 62, 62 | 62 | 62 |
| legrand-myrius-nextgen-switch-6a-1-module (and ?variant=49877995520315) | 200, 200 | 80, 80 | 80 | 80 |
| legrand-myrius-nextgen-6a-3-pin-socket… (and ?variant=49447316422971) | 200, 200 | 143, 143 | 143 | 143 |
| miniature-circuit-breaker-mcb-c60h-c-curve (and ?variant=49716838990139) | 200, 200 | 196, 196 | 196 | 196 |
| anchor-roma-switch-10a-1-module-white (and ?variant=49881302139195) | 200, 200 | 49, 49 | 49 | 49 |

All parsed by `jsonld`, tax basis `incl_gst`. The 6 URLs without `?variant=` are reported `multi_variant=True` with problem
`variant_not_selected`; the `?variant=` URLs have no problems. Same result on the browser-captured HTML, so this is the parser's
designed behaviour, not a bot/browser difference.

### IndustryBuying: real pages, HTTP 200, prices match on 6/6

| Page | HTTP | Bot price | Expected | Browser price |
|---|---|---|---|---|
| polycab wire 1.5 sqmm 90 m (EL.CA.HO.HA.169562) | 200 | 5073 | 5073 | 5073 |
| polycab wire 2.5 sqmm 90 m black (EL.CA.HO.HA.169587) | 200 | 7050 | 7050 | 7050 |
| salzer conduit (ELE.CAB.36831976) | 200 | 164 | 164 | 164 |
| finolex pipe (PLU.TAN.105418338) | 200 | 124 | 124 | 124 |
| anchor switch (ELE.DOM.32724933) | 200 | 420 | 420 | 420 |
| schneider MCB (EL.CI.MI.197390) | 200 | 778 | 778 | 778 |

All `jsonld`, `incl_gst`, single variant, no parser problems.

### Moglix: real pages, HTTP 200, prices match on 5/6 (the 6th changed on Moglix's side)

| Page | HTTP | Bot price | Browser price (14 Oct) |
|---|---|---|---|
| polycab etira 1.5 sqmm 90 m red (msnq94pz41yek0) | 200 | 3299 | 3299 |
| polycab etira 1.5 sqmm 90 m blue (msnl5gl0831pk4) | 200 | **3300** | **3299** |
| astral cpvc 40 mm pipe (msn2r5q9uoet73) | 200 | 984 | 984 |
| gm 10a 1-way switch (msn2qrg0ab50gd) | 200 | 1840 | 1840 |
| havells 63a SP C MCB (msn2vdxtgrv4af) | 200 | 679 | 679 |
| legrand mylinc 6a pack of 5 (msn2qo41yo2msj) | 200 | 678 | 678 |

The blue-wire difference is in the page itself, not the bot: the bot-fetched page's JSON-LD says `"price":"3300"` and its visible
text says "₹3,300 (Incl. of all taxes) ₹2,795 + ₹505 GST", where the 14 Oct browser capture said "₹3,299 … ₹2,795 + ₹504 GST".
So the parser read what Moglix showed at fetch time. I did not re-check it in a browser today (browser use was out of scope),
so "Moglix changed the price" is an inference from the two HTML files, not a side-by-side check.

All `jsonld`, `incl_gst`. The GM switch has problem `price_not_visible_in_text` on both the bot HTML and the browser HTML (same
result both ways). There is no Moglix `expected.json`, so Moglix prices are compared only with the parsed browser capture.

## Blocking

Nothing was blocked. 29 of 29 requests returned HTTP 200: no 403, no 429, no 5xx, no redirects, no retries.
No block marker from `fetcher.BLOCK_MARKERS` ("captcha", "access denied", "are you a robot", "unusual traffic",
"just a moment...", "pardon our interruption", "request blocked") appeared anywhere in any of the 26 saved pages
(checked the first 20,000 characters, which is what `looks_blocked()` checks, and the full page).
robots.txt was read with HTTP 200 on all three hosts; every URL was "allowed" for this bot; none set a Crawl-delay.

## Requests per host and gaps

Gaps are measured client-side as the time between the starts of consecutive `requests.Session.get()` calls to the same host
(`time.monotonic()`, recorded by a logging wrapper around a plain `requests.Session` passed into `Fetcher`).

| Host | Requests | robots.txt | Pages | Min gap | Mean gap | Max gap |
|---|---|---|---|---|---|---|
| home-run.co | 15 | 1 | 14 | 3.000 s | 3.890 s | 8.552 s |
| www.industrybuying.com | 7 | 1 | 6 | 3.000 s | 4.551 s | 7.195 s |
| www.moglix.com | 7 | 1 | 6 | 3.000 s | 4.053 s | 7.447 s |

These counts match the Fetcher's own `request_log`: `{'home-run.co': 15, 'www.industrybuying.com': 7, 'www.moglix.com': 7}`.
Fetching took 54.9 s in total. Full per-request timestamps are in `request_log.json`.

## What I verified and what I did not

Verified: the repo's own Fetcher, with its honest User-Agent, robots.txt check and 3 s spacing, got HTTP 200 real product pages
(no block page) from all three sites from this PC at 05:49 IST; the parser's price on the bot HTML equals `expected.json` on all
20 URLs that have an expected price (14 HomeRun including the added ?variant= forms, 6 IndustryBuying) and equals the parsed browser capture on 25 of 26 URLs.

Not verified: behaviour at the real run's scale (thousands of requests per host, `per_host_request_budget` 5,500) or at night
from a GitHub Actions runner IP, which these sites may treat differently from a home connection; Moglix ground-truth prices
(there is no `expected.json`); whether the Moglix blue-wire change to 3300 is still current; anything about publishing to
WooCommerce (not part of this check).

## Files

- `results.csv`: one row per URL (site, url, fetch status, http, robots verdict, html length, block markers, parser method/price/tax_basis/multi_variant/problems, expected selling_price, browser-parsed price)
- `homerun\`, `industrybuying\`, `moglix\`: raw HTML of every fetched page (26 files)
- `request_log.json`: every request with timestamp and status, plus gap stats
- `run_console.txt`: console output of the run
