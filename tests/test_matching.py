import gzip

from rtech_sync.matching import best_candidates, decide_match, parse_sitemap, score, slug_text
from rtech_sync.models import Row

ROW = Row(sku="P1", brand="Polycab", family="FR PVC Insulated Wire", title="Polycab FR PVC Insulated Wire",
          variant_hint="1.5 sq mm; red", pack_size="90 m")
GOOD = "https://shop.example/polycab-1-5-sqmm-fr-pvc-insulated-wire-red-90m"
WRONG_SIZE = "https://shop.example/polycab-2-5-sqmm-fr-pvc-insulated-wire-red-90m"
WRONG_COLOUR = "https://shop.example/polycab-1-5-sqmm-fr-pvc-insulated-wire-blue-90m"
WRONG_PACK = "https://shop.example/polycab-1-5-sqmm-fr-pvc-insulated-wire-red-180m"
WRONG_BRAND = "https://shop.example/havells-1-5-sqmm-fr-pvc-insulated-wire-red-90m"


def test_slug_text():
    assert slug_text(GOOD) == "polycab 1 5sqmm fr pvc insulated wire red 90m"


def test_exact_slug_is_high_confidence():
    c = score(ROW, GOOD)
    assert c.confidence == "high" and c.missing == []


def test_wrong_size_colour_pack_brand_are_not_high():
    for u in (WRONG_SIZE, WRONG_COLOUR, WRONG_PACK, WRONG_BRAND):
        assert score(ROW, u).confidence == "low", u


def test_decimal_in_slug_does_not_match_11_5():
    assert score(ROW, "https://s/polycab-11-5-sqmm-fr-pvc-insulated-wire-red-90m").confidence == "low"


def test_best_candidate_chosen_and_accepted_only_if_clearly_ahead():
    cands = best_candidates(ROW, [WRONG_SIZE, GOOD, WRONG_COLOUR])
    assert cands[0].url == GOOD
    assert decide_match(cands) == (GOOD, "high")


def test_ambiguous_duplicates_are_not_auto_accepted():
    dup = GOOD + "-v2"
    url, conf = decide_match(best_candidates(ROW, [GOOD, dup]))
    assert url is None and conf == "low"


def test_no_candidates():
    assert decide_match(best_candidates(ROW, [WRONG_BRAND])) == (None, "none")


def test_parse_sitemap_urlset_and_index_and_gzip():
    urlset = b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://a/1</loc></url><url><loc>https://a/2</loc></url></urlset>'
    index = b'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>https://a/s1.xml</loc></sitemap></sitemapindex>'
    assert parse_sitemap(urlset) == (["https://a/1", "https://a/2"], [])
    assert parse_sitemap(index) == ([], ["https://a/s1.xml"])
    assert parse_sitemap(gzip.compress(urlset))[0] == ["https://a/1", "https://a/2"]
