You are continuing the rtech-price-sync project (daily marketplace price sync for rtechelectricals.com). The repo is a tested starter kit. Read, in this order: CLAUDE.md, docs/STATUS.md, docs/SPEC.md, README.md.

Ground rules
- Follow the phases and STOP gates in docs/SPEC.md. At each STOP gate, stop and wait for me.
- Never weaken a test or the price rule (spread < 5% => publish the cheapest; >= 5% => hold the old price and flag).
- All tests must pass before and after every change (`python -m pytest`).
- Be honest in every report: separate what you verified against the REAL sites/shop from what you did not.
- I am in Bengaluru (IST) and start work around 9 AM. Do the safe, offline-capable work first.

Do this now
1. Run `python -m pytest`. Fix environment problems only.
2. Phase 0 (SPEC.md). Ask me everything in ONE AskUserQuestion batch: is the GitHub repo private; have I created WooCommerce REST keys; delivery pincode (propose 560064); rough product/variant count; which BUSINESS email to use as RTECH_CONTACT_EMAIL (never use my personal email). Then verify GitHub Actions limits and Hostinger Premium limits from their official docs, run (or tell me exactly how to run) the connectivity-test workflow, export the 79 existing products once I give you keys, and find out how the SOLD OUT badge and the Check Availability button are produced (theme, plugin or mu-plugin).
3. Real fixtures. Use the repo's own Fetcher (robots.txt, 3 s per host, honest User-Agent) to save 3-5 real product pages per site into tests/fixtures/ (HomeRun, Moglix, IndustryBuying; include a pipe product and a product with many variants). Use parallel subagents, one per site. Make the parsers pass on the real pages without breaking the synthetic tests. Report exactly which sites parse correctly, which do not, and what GST basis each site shows (then set assumed_tax_basis in config.yaml). If IndustryBuying product pages sit under a robots-blocked path, or any site blocks us, STOP and tell me. Do not work around it.
4. Record real findings in docs/STATUS.md (replace the "NOT verified" items you actually verified).
5. STOP 1: show me repo status, test results, Phase 0 findings, and which parsers are verified on real pages. Then wait.

Never: use search pages; rotate proxies or fake a browser; solve captchas; commit secrets; delete shop products; set publish=yes for me; change my hosting plan; publish anything live without my approval at STOP 3.
