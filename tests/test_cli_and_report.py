from pathlib import Path

import html_samples as S
from rtech_sync import report, run as runmod
from rtech_sync.models import CATALOGUE_COLUMNS

ROOT = Path(__file__).resolve().parent.parent


class Pages:
    request_log = {}

    def __init__(self, *_a, **_k):
        pass

    def get(self, url, budget_key=""):
        from rtech_sync.fetcher import FetchResult
        price = {"moglix.com": 1000, "industrybuying.com": 1010, "home-run.co": 1020}
        for dom, p in price.items():
            if dom in url:
                return FetchResult(url, "ok", 200, text=S.jsonld_page(price=str(p), visible_price=f"₹{p:,}"))
        return FetchResult(url, "error")


def make_catalogue(tmp_path):
    cat = tmp_path / "cat"
    cat.mkdir()
    base = {c: "" for c in CATALOGUE_COLUMNS}
    base.update(sku="PC-1", wc_product_id="10", wc_variation_id="100", brand="Polycab", mode="priced",
                publish="yes", variant_hint="1.5 sq mm; red", pack_size="90 m", title="Polycab wire",
                url_moglix="https://www.moglix.com/p/a", url_industrybuying="https://www.industrybuying.com/p/b",
                url_homerun="https://home-run.co/products/c")
    line = ",".join(f'"{base[c]}"' for c in CATALOGUE_COLUMNS)
    (cat / "polycab.csv").write_text(",".join(CATALOGUE_COLUMNS) + "\n" + line + "\n")
    return cat


def test_cli_dry_run_end_to_end(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("RTECH_CONTACT_EMAIL", "shop@example.com")
    monkeypatch.setattr(runmod, "Fetcher", Pages)
    cat, data = make_catalogue(tmp_path), tmp_path / "data"
    code = runmod.main(["--config", str(ROOT / "config.yaml"), "--catalogue", str(cat), "--data", str(data),
                        "--today", "2026-10-14"])
    assert code == 0
    # live config: cheapest of Moglix/HomeRun (Rs 1,000) less 1% (owner, 18 Oct 2026)
    assert (data / "dryrun_plan.csv").read_text().splitlines()[1].startswith("PC-1,publish,990")
    assert not (data / "latest.json").exists()  # dry run must not touch state
    assert "DRY RUN" in capsys.readouterr().out


def test_cli_refuses_to_run_without_contact_email(tmp_path, monkeypatch):
    monkeypatch.delenv("RTECH_CONTACT_EMAIL", raising=False)
    assert runmod.main(["--config", str(ROOT / "config.yaml"), "--catalogue", str(make_catalogue(tmp_path)),
                        "--data", str(tmp_path / "d")]) == 2


def test_cli_publish_requires_woo_env(tmp_path, monkeypatch):
    monkeypatch.setenv("RTECH_CONTACT_EMAIL", "shop@example.com")
    for k in ("WC_URL", "WC_KEY", "WC_SECRET"):
        monkeypatch.delenv(k, raising=False)
    assert runmod.main(["--config", str(ROOT / "config.yaml"), "--catalogue", str(make_catalogue(tmp_path)),
                        "--data", str(tmp_path / "d"), "--publish"]) == 2


def test_cli_rejects_invalid_catalogue(tmp_path, monkeypatch):
    monkeypatch.setenv("RTECH_CONTACT_EMAIL", "shop@example.com")
    cat = make_catalogue(tmp_path)
    f = cat / "polycab.csv"
    f.write_text(f.read_text().replace("https://www.moglix.com/p/a", "https://www.moglix.com/search?q=x"))
    assert runmod.main(["--config", str(ROOT / "config.yaml"), "--catalogue", str(cat),
                        "--data", str(tmp_path / "d")]) == 2


def test_issue_body_stays_under_github_limit_with_many_flags():
    rows = [{"sku": f"S{i}", "brand": "B" + str(i % 7), "title": "x" * 200, "action": "hold",
             "flags": "spread_over_5pct", "info": "", "spread_pct": str(5 + i % 50), "live_price": "100",
             "moglix": "1", "industrybuying": "2", "homerun": "3", "url_moglix": "https://m/" + "a" * 300,
             "url_industrybuying": "https://i/" + "b" * 300, "url_homerun": "https://h/" + "c" * 300}
            for i in range(5000)]
    body = report.build_issue_body(rows, "2026-10-14", "PUBLISH")
    assert len(body) < 65000 and "5000 item(s)" in body and "data/flags.csv" in body


def test_issue_body_empty_is_friendly():
    assert "Nothing flagged" in report.build_issue_body([], "2026-10-14", "DRY RUN")
