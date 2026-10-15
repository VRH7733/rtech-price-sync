# CLAUDE.md: rtech-price-sync

Daily price sync for rtechelectricals.com (WooCommerce on Hostinger Premium). Owner: Harshi.

Start here, in this order:
1. `docs/STATUS.md`: what is built, what is NOT verified, next steps.
2. `docs/SPEC.md`: the agreed requirements and the phase/STOP gates. Follow the STOP gates.
3. `README.md`: owner-facing how-to.

Commands: `python -m pytest` (all must pass before and after any change). Dry run:
`PYTHONPATH=src python -m rtech_sync.run`. Live publishing needs `--publish` and the owner's approval.

Non-negotiables (details in SPEC):
- Price rule: spread < 5% => publish the cheapest; >= 5% => hold the old price and flag. Never loosen it.
- Use only Moglix, IndustryBuying, HomeRun, only the catalogue's product URLs, never search pages.
- Obey robots.txt with `src/rtech_sync/robots.py` (do NOT switch to urllib.robotparser: no wildcard
  support). >= 3 s per host. Honest User-Agent. No proxies, browser spoofing, captcha solving. If a
  site blocks you, report it; do not work around it.
- Never put the owner's personal email into requests to third parties. The contact address comes
  from `RTECH_CONTACT_EMAIL` and must be a business address the owner chose.
- Never commit secrets (`.env`, WC keys). Never delete shop products. New site content = DRAFT only.
- Never set `publish=yes` for the owner. Matches go in as `pending_review`.
- Do not change hosting or plans. Report evidence and the cheapest fix instead.
- Add a test for every rule you touch. Parsers need REAL saved pages in `tests/fixtures/` before
  they are trusted (current parser tests use synthetic pages, see `tests/html_samples.py`).
- Be honest in reports: say what was verified against the real sites and what was not.

When the owner is away, do the safe work (fixtures, tests, dry-run analysis), write findings into
`docs/STATUS.md`, and stop at the next STOP gate rather than guessing.
