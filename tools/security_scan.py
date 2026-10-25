#!/usr/bin/env python3
"""Read-only security check of the owner's own shop, from outside, as any visitor sees it.

Usage: security_scan.py <report.md>
Env:   WC_URL (the shop's address), CONTACT_EMAIL

About 30 ordinary GET/HEAD requests, 1.5 s apart, honest User-Agent. No logins, no forms, no
attack payloads. It checks: WordPress, plugin and theme versions shown in the page source
against the latest on wordpress.org; files that should not be public; user-name leaks;
XML-RPC; security headers; HTTPS.

The code repo is public, so the findings go only to the report (saved in the PRIVATE data
repo); the log says just how many checks ran.
"""
import json
import os
import re
import ssl
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

BASE = os.environ["WC_URL"].rstrip("/")
UA = f"rtech-price-sync security check (owner's own site) (+mailto:{os.environ.get('CONTACT_EMAIL', 'unset')})"
PAUSE = 1.5


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def fetch(url, method="GET", follow=True, limit=400_000):
    opener = urllib.request.build_opener() if follow else urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(url, method=method, headers={"User-Agent": UA})
    time.sleep(PAUSE)
    try:
        with opener.open(req, timeout=25) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read(limit).decode("utf-8", "replace"), r.geturl()
    except urllib.error.HTTPError as e:
        body = e.read(limit).decode("utf-8", "replace") if e.fp else ""
        return e.code, {k.lower(): v for k, v in e.headers.items()}, body, url
    except Exception as e:  # timeouts, resets
        return 0, {}, f"{type(e).__name__}: {e}", url


def vtuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:4])


lines, findings = [], []


def note(sev, text):
    findings.append((sev, text))


st, hdr, home, _ = fetch(BASE + "/")
lines.append(f"Home: HTTP {st}")

# ---- headers
want = {
    "strict-transport-security": "HSTS (forces HTTPS in the browser)",
    "x-content-type-options": "X-Content-Type-Options",
    "x-frame-options": "X-Frame-Options (stops the site being framed for click-jacking)",
    "referrer-policy": "Referrer-Policy",
    "content-security-policy": "Content-Security-Policy",
    "permissions-policy": "Permissions-Policy",
}
for h, label in want.items():
    lines.append(f"Header {h}: {hdr.get(h, 'MISSING')}")
    if h not in hdr and h != "content-security-policy" and h != "permissions-policy":
        note("low", f"Missing security header: {label}")
for h in ("server", "x-powered-by", "x-litespeed-cache", "x-turbo-charged-by"):
    if h in hdr:
        lines.append(f"Header {h}: {hdr[h]}")
if re.search(r"php/\d", hdr.get("x-powered-by", ""), re.I):
    note("low", f"The PHP version is shown to everyone (X-Powered-By: {hdr['x-powered-by']})")

# ---- HTTPS
st2, h2, _, _ = fetch(BASE.replace("https://", "http://") + "/", follow=False)
lines.append(f"http:// -> {st2} {h2.get('location', '')}")
if not (300 <= st2 < 400 and h2.get("location", "").startswith("https://")):
    note("medium", f"Plain http:// is not redirected to https:// (status {st2})")
try:
    host = BASE.split("//", 1)[1].split("/")[0]
    ctx = ssl.create_default_context()
    with socket.create_connection((host, 443), timeout=15) as s, ctx.wrap_socket(s, server_hostname=host) as t:
        cert = t.getpeercert()
        exp = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
        days = (exp - datetime.now(timezone.utc)).days
        lines.append(f"TLS: {t.version()}, certificate valid for {days} more days")
        if days < 14:
            note("high", f"The HTTPS certificate expires in {days} days")
except Exception as e:
    lines.append(f"TLS check failed: {e}")

# ---- versions in the page source
wp_ver = None
m = re.search(r'<meta name="generator" content="WordPress ([\d.]+)', home)
if m:
    wp_ver = m.group(1)
    note("low", f"The WordPress version is shown in the page source ({wp_ver})")
plugins = {}
for slug, ver in re.findall(r"/wp-content/plugins/([a-z0-9_-]+)/[^\"'\s>]*?\?ver=([\d.]+)", home):
    if vtuple(ver) > vtuple(plugins.get(slug, "")):
        plugins[slug] = ver
for slug in set(re.findall(r"/wp-content/plugins/([a-z0-9_-]+)/", home)):
    plugins.setdefault(slug, "")
themes = {}
for slug, ver in re.findall(r"/wp-content/themes/([a-z0-9_-]+)/[^\"'\s>]*?\?ver=([\d.]+)", home):
    themes.setdefault(slug, ver)
gens = re.findall(r'<meta name="generator" content="([^"]+)"', home)
lines.append("Generators: " + "; ".join(gens))

try:
    with urllib.request.urlopen(urllib.request.Request("https://api.wordpress.org/core/version-check/1.7/", headers={"User-Agent": UA}), timeout=20) as r:
        latest_wp = json.load(r)["offers"][0]["current"]
except Exception:
    latest_wp = None
lines.append(f"WordPress shown: {wp_ver or 'hidden'}; latest: {latest_wp}")
if wp_ver and latest_wp and vtuple(wp_ver) < vtuple(latest_wp):
    note("high", f"WordPress {wp_ver} is out of date (latest {latest_wp})")


def latest_on_org(kind, slug):
    url = (f"https://api.wordpress.org/plugins/info/1.2/?action=plugin_information&request[slug]={slug}&request[fields][versions]=0"
           if kind == "plugin" else f"https://api.wordpress.org/themes/info/1.2/?action=theme_information&request[slug]={slug}")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=20) as r:
            d = json.load(r)
            return d.get("version") if isinstance(d, dict) and not d.get("error") else None
    except Exception:
        return None


for kind, items in (("plugin", plugins), ("theme", themes)):
    for slug, ver in sorted(items.items()):
        latest = latest_on_org(kind, slug)
        # the ?ver= of a file is often the plugin version, but not always: report, then judge
        lines.append(f"{kind} {slug}: page shows {ver or '?'}; wordpress.org latest {latest or 'not on wordpress.org'}")
        if ver and latest and vtuple(ver) < vtuple(latest) and vtuple(ver)[:1] == vtuple(latest)[:1]:
            note("medium", f"{kind.title()} '{slug}' may be out of date (page shows {ver}, latest {latest}); check in Dashboard > Updates")

# ---- files and endpoints that should not be public
probes = [
    ("/wp-content/debug.log", "PHP error log"),
    ("/debug.log", "PHP error log"),
    ("/wp-config.php.bak", "backup of the WordPress config (database password)"),
    ("/wp-config.php~", "backup of the WordPress config"),
    ("/wp-config.bak", "backup of the WordPress config"),
    ("/.env", "environment file with passwords"),
    ("/.git/HEAD", "the site's git repository"),
    ("/error_log", "server error log"),
    ("/phpinfo.php", "phpinfo page"),
    ("/info.php", "phpinfo page"),
    ("/wp-content/uploads/", "uploads folder listing"),
    ("/wp-content/plugins/", "plugins folder listing"),
    ("/wp-content/uploads/wc-logs/", "WooCommerce logs folder listing"),
    ("/wp-admin/install.php", "WordPress installer"),
    ("/readme.html", "WordPress readme (shows the version)"),
]
for path, what in probes:
    s, h, body, final = fetch(BASE + path, follow=False)
    shown = s == 200 and len(body) > 0
    if path.endswith("/") and shown:
        shown = "Index of" in body or "<title>Index of" in body
    if path == "/wp-admin/install.php":
        shown = s == 200 and "already installed" not in body.lower() and "install" in body.lower()
    if path == "/readme.html":
        shown = s == 200 and "WordPress" in body
    if path == "/.git/HEAD":
        shown = s == 200 and body.startswith("ref:")
    if path.endswith(".log") or path == "/error_log":
        shown = s == 200 and bool(re.search(r"PHP (Warning|Notice|Fatal|Deprecated)|\[\d\d-\w{3}-\d{4}", body))
    if path.endswith(".php") and "phpinfo" in what:
        shown = s == 200 and "phpinfo()" in body
    if "config" in what or path == "/.env":
        shown = s == 200 and bool(re.search(r"DB_PASSWORD|DB_NAME|APP_KEY|PASSWORD=", body))
    lines.append(f"{path}: HTTP {s}{' EXPOSED' if shown else ''}")
    if shown:
        sev = "high" if any(w in what for w in ("password", "config", "repository", "log", "phpinfo")) else "low"
        note(sev, f"{what} is public at {path}")

# ---- user names
s, h, body, _ = fetch(BASE + "/wp-json/wp/v2/users")
users = []
if s == 200:
    try:
        users = [u.get("slug") for u in json.loads(body) if isinstance(u, dict)]
    except Exception:
        pass
lines.append(f"/wp-json/wp/v2/users: HTTP {s}, {len(users)} user(s) listed")
if users:
    note("medium", f"Login user names are listed publicly at /wp-json/wp/v2/users ({len(users)}): this helps password-guessing attacks")
s, h, body, _ = fetch(BASE + "/?author=1", follow=False)
loc = h.get("location", "")
lines.append(f"/?author=1: HTTP {s} {('-> /author/...' if '/author/' in loc else loc[:80])}")
if "/author/" in loc:
    note("medium", "A login user name is revealed by /?author=1 (redirects to /author/<name>/)")

# ---- XML-RPC
s, h, body, _ = fetch(BASE + "/xmlrpc.php")
lines.append(f"/xmlrpc.php: HTTP {s} {body[:60]!r}")
if s == 405 or "XML-RPC server accepts POST requests only" in body:
    note("medium", "XML-RPC is switched on (/xmlrpc.php): a common route for password-guessing; not needed unless you use the Jetpack or WordPress mobile app")

# ---- login page
s, h, body, _ = fetch(BASE + "/wp-login.php")
lines.append(f"/wp-login.php: HTTP {s}, captcha/2FA hints: {bool(re.search('captcha|recaptcha|turnstile|two-factor|2fa|wordfence|limit login', body, re.I))}")

# ---- report
order = {"high": 0, "medium": 1, "low": 2}
findings.sort(key=lambda f: order[f[0]])
out = [f"# Security check of {BASE}", "", f"Run: {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC. Read-only, from outside.", "", "## Findings", ""]
out += [f"- **{sev}**: {text}" for sev, text in findings] or ["- none"]
out += ["", "## Raw results", ""] + [f"- {l}" for l in lines]
os.makedirs(os.path.dirname(sys.argv[1]) or ".", exist_ok=True)
open(sys.argv[1], "w").write("\n".join(out) + "\n")
print(f"security check done: {len(lines)} results, {len(findings)} findings (details in the private report)")
