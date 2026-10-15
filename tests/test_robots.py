from pathlib import Path

from rtech_sync.robots import RobotsRules

FIX = Path(__file__).parent / "fixtures"


def rules(name):
    return RobotsRules((FIX / name).read_text())


def test_moglix_search_and_wildcards_blocked():
    r = rules("robots_moglix.txt")
    assert not r.allowed("https://www.moglix.com/search?searchTerm=wire")
    assert not r.allowed("https://www.moglix.com/search/wire")
    assert not r.allowed("https://www.moglix.com/some-category?p=2")  # '/*?p='
    assert not r.allowed("https://www.moglix.com/x?category=1")
    assert not r.allowed("https://www.moglix.com/rfq/123")
    assert not r.allowed("https://www.moglix.com/checkout")


def test_moglix_product_page_allowed():
    r = rules("robots_moglix.txt")
    assert r.allowed("https://www.moglix.com/polycab-wire/mp/msn1234567")
    assert r.allowed("https://www.moglix.com/sitemap_index.xml")


def test_industrybuying_product_details_blocked_but_sitemap_ok():
    r = rules("robots_industrybuying.txt")
    assert not r.allowed("https://www.industrybuying.com/product_details/123")
    assert not r.allowed("https://www.industrybuying.com/search/wire")
    assert not r.allowed("https://www.industrybuying.com/categories/electrical")
    assert not r.allowed("https://www.industrybuying.com/?q=wire")
    assert r.allowed("https://www.industrybuying.com/sitemap_index.xml")
    assert r.allowed("https://www.industrybuying.com/polycab-wire-ELE.1/")


def test_homerun_products_allowed_search_blocked():
    r = rules("robots_homerun.txt")
    assert r.allowed("https://home-run.co/products/kei-homecab-90mtr-wire")
    assert r.allowed("https://home-run.co/collections/wires")
    assert not r.allowed("https://home-run.co/search")
    assert not r.allowed("https://home-run.co/cart")
    assert not r.allowed("https://home-run.co/account/orders")


def test_most_specific_group_wins_over_star():
    r = RobotsRules("User-agent: *\nDisallow: /\n\nUser-agent: rtech-price-sync\nAllow: /\n")
    assert r.allowed("https://x.com/anything")


def test_longest_match_and_allow_wins_ties():
    r = RobotsRules("User-agent: *\nDisallow: /a\nAllow: /a/b\nDisallow: /a/b/c\n")
    assert not r.allowed("https://x.com/a/z")
    assert r.allowed("https://x.com/a/b/x")
    assert not r.allowed("https://x.com/a/b/c/d")


def test_dollar_anchor():
    r = RobotsRules("User-agent: *\nDisallow: /*.pdf$\n")
    assert not r.allowed("https://x.com/doc.pdf")
    assert r.allowed("https://x.com/doc.pdf.html")


def test_empty_disallow_and_empty_file_allow_everything():
    assert RobotsRules("User-agent: *\nDisallow:\n").allowed("https://x.com/a")
    assert RobotsRules("").allowed("https://x.com/a")


def test_crawl_delay_read():
    assert RobotsRules("User-agent: *\nCrawl-delay: 7\n").crawl_delay == 7.0


def test_case_insensitive_directives_and_comments():
    r = RobotsRules("USER-AGENT: *\nDISALLOW: /x # private\n")
    assert not r.allowed("https://x.com/x/1")
