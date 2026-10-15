#!/usr/bin/env python3
"""Phase 0 connectivity test. Run it from GitHub Actions (workflow 'connectivity-test').

Checks, with a polite User-Agent and 3 requests to the marketplaces (robots.txt only):
  1. can the runner read your WooCommerce REST API (Hostinger firewall / auth)?
  2. can the runner reach each marketplace's robots.txt (is the runner IP blocked)?
It changes nothing. If something is blocked, it tells you; it never tries to get around it.
"""
import os
import sys
import time

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from rtech_sync.config import load_config  # noqa: E402


def main() -> int:
    cfg = load_config(os.path.join(os.path.dirname(__file__), "..", "config.yaml"))
    cfg.fetch.require_contact_email()
    ua = {"User-Agent": cfg.fetch.user_agent}
    ok = True

    wc = os.environ.get("WC_URL", "").rstrip("/")
    if not (wc and os.environ.get("WC_KEY") and os.environ.get("WC_SECRET")):
        print("WooCommerce: SKIPPED (WC_URL / WC_KEY / WC_SECRET not set)")
        ok = False
    else:
        try:
            r = requests.get(
                wc + "/wp-json/wc/v3/products",
                params={"per_page": 1},
                auth=(os.environ["WC_KEY"], os.environ["WC_SECRET"]),
                headers=ua,
                timeout=60,
            )
            print(f"WooCommerce REST read: HTTP {r.status_code}")
            hints = {
                401: "Keys wrong or REST API keys lack permission.",
                403: "Blocked: Hostinger firewall / security plugin may be blocking GitHub IPs. "
                "Ask Hostinger support or your security plugin to allow the API path.",
                404: "REST API path not found: check permalinks (must not be 'Plain') and WC_URL.",
                508: "Hostinger 'Resource Limit Reached': the plan is too small for this load.",
            }
            if r.status_code != 200:
                ok = False
                print("  ->", hints.get(r.status_code, "Unexpected response."))
        except requests.RequestException as e:
            ok = False
            print(f"WooCommerce REST read: FAILED ({type(e).__name__}). Network or firewall issue.")

    for name, src in cfg.sources.items():
        host = "https://www." + src.domain if name != "homerun" else "https://" + src.domain
        time.sleep(3)
        try:
            r = requests.get(host + "/robots.txt", headers=ua, timeout=30)
            note = "reachable" if r.status_code == 200 else "NOT OK (runner may be blocked)"
            print(f"{name} robots.txt: HTTP {r.status_code} -> {note}")
            ok = ok and r.status_code == 200
        except requests.RequestException as e:
            ok = False
            print(f"{name} robots.txt: FAILED ({type(e).__name__})")
    print("RESULT:", "all good" if ok else "something is blocked or missing, see above")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
