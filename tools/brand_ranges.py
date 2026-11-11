"""Wire and cable RANGES of each brand, and the brand's OWN page that shows the range photo.

Owner (10 Nov 2026): manufacturers allow their images but send no packs; use only manufacturer-owned
images, and for wires the brand's photo of the RANGE for every size and colour of that range (the
padded range-photo method approved on 18 Oct for KEI and RR Kabel). Never photos shot by other sellers
(Moglix, IndustryBuying, IndiaMART, marketplace listings) and never AI-made or AI-redrawn photos.

Each entry was checked by hand against the brand's site (pages saved 10 Nov 2026 through the
save-pages workflow; the ones the tests use are in tests/fixtures/real/ranges/). A product gets a
range photo only when its title matches exactly ONE entry of its brand (a `range` entry wins over a
`family` entry), so a title that fits two ranges gets nothing.

kind:
  range   our title names the brand's range (Lifeline Plus S3, Conflame, Unilay ...).
  family  our title names no range, only a construction the brand sells under ONE page (KEI's
          "Single Core / Multicore Flexible Cables"). Weaker: applied only with --allow-family.
pages:  the brand's own pages with the range photo (fetched by `crawl --ranges`, robots.txt obeyed).
image:  regex the photo's file name or alt text must match, when the page shows several products
        (Havells range pages list the range's own products; RR Kabel shows related products).
site_ranges: the brand's per-size wire pages of this range (wire_key range names in pages_<brand>.csv,
        e.g. Polycab's 'etira'); their photos are used when no range page photo passes.
cores:  'multi' = only multicore products (the photo shows a multicore cable).
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Range:
    key: str
    name: str
    title: str
    pages: tuple = ()
    kind: str = "range"
    exclude: str = ""
    require: str = ""
    image: str = ""
    site_ranges: tuple = ()
    cores: str = ""


HAVELLS_FLEX = "https://havells.com/home-electricals/flexible-cables/"
KEI_HW = "https://www.kei-ind.com/cables-and-wires/house-wire/"
RR = "https://www.rrkabel.com/products/"
FINOLEX_HW = "https://www.finolex.com/ProductPage/Prod/House-Wires~"

RANGES = {
    "havells": [
        Range("havells/lifeline-plus-s3", "Lifeline Plus S3 (HRFR)", r"\blife ?line plus s ?3\b",
              (HAVELLS_FLEX + "lifeline-hrfr.html",), image=r"plus s ?3|whffdnka", site_ranges=("lifelineplus",)),
        # the HRFR range; Havells sells it today as Lifeline Plus S3 (page title 'Lifeline (HRFR)')
        Range("havells/lifeline-plus-hrfr", "Lifeline Plus (HRFR)", r"\blife ?line plus\b", (HAVELLS_FLEX + "lifeline-hrfr.html",),
              exclude=r"plus s ?3", require=r"\bhr ?fr\b", image=r"plus s ?3|whffdnka", site_ranges=("lifelineplus",)),
        Range("havells/lifeline-fr", "Lifeline FR", r"\blife ?line\b", (HAVELLS_FLEX + "lifeline-fr.html",),
              exclude=r"\bplus\b|\bs ?3\b|\bhr ?fr\b", image=r"life ?line[ _]?fr"),
        Range("havells/life-guard", "Life Guard (FR-LSH)", r"\blife ?guard\b", (HAVELLS_FLEX + "life-guard-fr-lsh.html",),
              image=r"life ?guard"),
        Range("havells/life-shield", "Life Shield (HFFR)", r"\blife ?shield\b", (HAVELLS_FLEX + "life-shield-hffr.html",),
              image=r"life ?shield"),
    ],
    "kei": [
        # KEI's ConFlame-FRLS page shows the ConFlame Green+ box
        Range("kei/conflame-green-plus", "ConFlame Green+", r"\bcon ?flame green ?plus\b", (KEI_HW + "con-flame-frls/",)),
        Range("kei/conflame", "ConFlame-FRLS", r"\bcon ?flame\b", (KEI_HW + "con-flame-frls/",),
              exclude=r"\bgreen ?plus\b"),  # 'Green+', not the colour green (a green ConFlame wire is ConFlame)
        Range("kei/homecab", "HomeCab-FR", r"\bhome ?cab\b", (KEI_HW + "home-cab-fr/",)),
        Range("kei/banfire", "BanFire-ZHFR", r"\bban ?fire\b", (KEI_HW + "ban-fire-zhfr/",)),
        Range("kei/multicore-flexible", "Single Core / Multicore Flexible Cables", r"\bflexible\b.*\bmultistrand",
              ("https://www.kei-ind.com/cables-and-wires/single-and-multicore-flexibles/",), kind="family", cores="multi",
              exclude=r"con ?flame|home ?cab|ban ?fire"),
    ],
    "rrkabel": [
        Range("rrkabel/unilay", "Unilay HR FR", r"\bunilay\b", (RR + "unilay-hr-fr/",), image=r"wire-1-1|unilay"),
        Range("rrkabel/superex-green", "Superex Green HR+FR", r"\bsuperex green\b", (RR + "superex-green-hrfr/",),
              image=r"superex-green"),
        # RR Kabel's Superex FR photo is shown (by file name) on its Unilay page; Superex FR has no page in the sitemap
        Range("rrkabel/superex-fr", "Superex FR", r"\bsuperex\b", (RR + "unilay-hr-fr/",), exclude=r"\bsuperex green\b",
              image=r"superex-fr"),
        Range("rrkabel/ratnaflex", "Ratnaflex Multicore Cable (IS 694)", r"\bratnaflex\b", (RR + "ratnaflex-multicore-cable-is-694/",)),
        Range("rrkabel/fr-hsf", "FR-HSF", r"\bfr ?hsf\b", (RR + "fr-hsf/",), exclude=r"mahashield"),
        Range("rrkabel/fr-lsh", "RR Kabel FR-LSH", r"\bfr ?lsh\b", (RR + "rr-kabel-fr-lsh/",), exclude=r"\bls ?[o0] ?h\b|zero"),
        Range("rrkabel/fr-lsh-words", "RR Kabel FR-LSH", r"flame retardant low smoke halogen", (RR + "rr-kabel-fr-lsh/",),
              kind="family", exclude=r"\bls ?[o0] ?h\b|zero|unilay|superex|ratnaflex|braided|shielded"),
        Range("rrkabel/ls0h-fr", "LS0H FR", r"\bls ?[o0] ?h\b", (RR + "ls0h-fr/",), exclude=r"firex|ebxl"),
    ],
    "finolex": [
        Range("finolex/silver", "Flame Retardant (FR) Grade Silver", r"\bsilver\b", (FINOLEX_HW + "Flame-Retardant-FR-Grade-90Mtr-Silver",)),
        Range("finolex/gold", "Flame Retardant (FR) Grade Gold", r"\bgold\b", (FINOLEX_HW + "Flame-Retardant-FR-Grade-90Mtr-Gold",)),
        Range("finolex/flamegard", "Flamegard FR-LSH", r"\bflame ?gard\b", (FINOLEX_HW + "Flame-Retardant-Low-Smoke-FRLSH",)),
    ],
    # Polycab has a page per size and colour (pages_polycab.csv); a size it does not show gets the
    # photo of the same range in the same colour, else the range's photo
    "polycab": [
        Range("polycab/maxima-plus", "Maxima+ Green Wire", r"\bmaxima ?plus\b", site_ranges=("maximaplusgreen", "maximaplus")),
        Range("polycab/etira", "Etira House Wires", r"\betira\b", site_ranges=("etira",)),
        Range("polycab/optima-plus", "Optima+", r"\boptima ?plus\b", site_ranges=("optimaplus",)),
        Range("polycab/primma", "Primma", r"\bprimma\b", site_ranges=("primma",)),
        Range("polycab/suprema", "Suprema", r"\bsuprema\b", site_ranges=("suprema",)),
    ],
}


def norm_title(title: str) -> str:
    s = title.lower().replace("–", " ").replace("—", " ").replace("²", "2")
    s = re.sub(r"\+", " plus ", s)
    s = re.sub(r"[^a-z0-9.]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def cores_of(title: str) -> float:
    s = title.lower()
    m = re.search(r"(\d+(?:\.\d+)?)\s*core", s)
    if m:
        return float(m.group(1))
    if re.search(r"\b(double|twin|two)\s+core", s):
        return 2.0
    if re.search(r"\btriple\s+core", s):
        return 3.0
    return 1.0


def entry_matches(r: Range, title: str) -> bool:
    s = norm_title(title)
    if not re.search(r.title, s):
        return False
    if r.exclude and re.search(r.exclude, s):
        return False
    if r.require and not re.search(r.require, s):
        return False
    if r.cores == "multi" and cores_of(title) <= 1:
        return False
    return True


def range_for(brand_key: str, title: str) -> tuple:
    """(Range, "") for exactly one match; (None, why) otherwise. A `range` entry wins over `family`
    entries; two entries of the same kind (other ranges, not the same page) = ambiguous."""
    hits = [r for r in RANGES.get(brand_key, []) if entry_matches(r, title)]
    if not hits:
        return None, ""
    for kind in ("range", "family"):
        k = [r for r in hits if r.kind == kind]
        if len(k) == 1:
            return k[0], ""
        if len(k) > 1:
            return None, "title fits several brand ranges: " + ", ".join(r.name for r in k)
    return None, ""


def all_ranges():
    for key, rs in RANGES.items():
        for r in rs:
            yield key, r
