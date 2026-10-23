#!/usr/bin/env python3
"""Summarise Lighthouse JSON reports: scores, Core Web Vitals and the biggest savings.

Usage: lighthouse_summary.py <dir of N.json> <report.md>
"""
import glob
import json
import os
import sys

METRICS = ("first-contentful-paint", "largest-contentful-paint", "total-blocking-time",
           "cumulative-layout-shift", "speed-index", "server-response-time")


def main(src, out):
    lines = ["# Site speed (Lighthouse, mobile)", ""]
    for path in sorted(glob.glob(os.path.join(src, "*.json"))):
        try:
            r = json.load(open(path))
        except ValueError:
            lines += [f"## {path}: no report", ""]
            continue
        a = r.get("audits", {})
        lines += [f"## {r.get('finalDisplayedUrl') or r.get('requestedUrl')}", ""]
        if r.get("runtimeError"):
            lines.append(f"- error: {r['runtimeError']}")
        for k, c in r.get("categories", {}).items():
            lines.append(f"- {k}: {round((c.get('score') or 0) * 100)}")
        for m in METRICS:
            if m in a:
                lines.append(f"- {a[m].get('title')}: {a[m].get('displayValue')}")
        opps = []
        for k, v in a.items():
            d = v.get("details") or {}
            ms = d.get("overallSavingsMs") or 0
            if v.get("score") is not None and v["score"] < 0.9 and (ms > 100 or d.get("overallSavingsBytes", 0) > 50000):
                opps.append((ms, d.get("overallSavingsBytes", 0), v.get("title"), k, d.get("items", [])[:4]))
        lines.append("- biggest savings:")
        for ms, by, title, k, items in sorted(opps, key=lambda o: (-o[0], -o[1]))[:8]:
            urls = [str(i.get("url", ""))[-90:] for i in items if isinstance(i, dict) and i.get("url")]
            lines.append(f"  - {title} ({k}): ~{int(ms)} ms, ~{int(by / 1024)} KiB; {urls}")
        fails = [v.get("title") for v in a.values()
                 if v.get("score") == 0 and v.get("scoreDisplayMode") == "binary"]
        lines.append(f"- failed checks: {fails[:15]}")
        lines.append("")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    open(out, "w").write("\n".join(lines) + "\n")
    print("\n".join(l for l in lines if l.startswith("## ") or l.startswith("- performance")))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
