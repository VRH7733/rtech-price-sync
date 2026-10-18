#!/usr/bin/env python3
"""Save a few public pages (robots.txt obeyed, polite pacing, honest User-Agent) so parsers can
be written and tested against REAL pages.

  python tools/save_pages.py OUT_DIR URL [URL ...]

Each page goes to OUT_DIR/<host>__<path>.html. Prints only status lines.
"""
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from rtech_sync.config import load_config  # noqa: E402
from rtech_sync.fetcher import Fetcher  # noqa: E402


def main(argv):
    out, urls = Path(argv[0]), argv[1:]
    cfg = load_config(os.path.join(os.path.dirname(__file__), "..", "config.yaml"))
    cfg.fetch.require_contact_email()
    f = Fetcher(cfg.fetch)
    out.mkdir(parents=True, exist_ok=True)
    lines = []
    for u in urls:
        r = f.get(u)
        p = urlparse(u)
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{p.netloc}__{p.path.strip('/')}")[:150] + ".html"
        print(f"{r.status} {r.http} {u}")
        lines.append(f"{r.status} {r.http} {r.detail} {u} -> {name if r.text else '-'}")
        if r.text:
            (out / name).write_text(r.text, encoding="utf-8")
    with open(out / "_status.txt", "a", encoding="utf-8") as fh:  # Actions logs are not readable here
        fh.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
