"""Product page content from OUR OWN catalogue data: type, shop category, specs, text, illustration key.

Everything here is derived from the catalogue title and brand (facts we already hold). Nothing is
copied from marketplace or brand pages (owner rule: never copy marketplace text or images).
Only claims that are true for every product are written; specs appear only when the title states them.
"""
from __future__ import annotations

import hashlib
import html
import re

COLOURS = ["red", "black", "blue", "yellow", "green", "white", "grey", "gray", "brown", "orange",
           "ivory", "silver", "gold", "beige", "pearl white", "satin dusk", "charcoal grey"]
WIRE_COLOUR_HEX = {"red": "#d32f2f", "black": "#212121", "blue": "#1565c0", "yellow": "#f9c400",
                   "green": "#2e7d32", "white": "#f5f5f5", "grey": "#8a8a8a", "gray": "#8a8a8a",
                   "brown": "#6d4c41", "orange": "#ef6c00", "ivory": "#f3ecd8"}

# (type key, label, shop category, pattern) - first match wins, so specific before general
TYPES = [
    ("coax", "Co-axial / data cable", "Wires & Cables", r"co-?\s?axial|cctv|\brg[- ]?11|\b4\s?\+\s?1\b|\brg[- ]?6|\bcat ?6|\bcat ?5|\blan cable|telephone cable"),
    ("armoured", "Armoured cable", "Wires & Cables", r"armou?red|\b2xwy|\byfy|\bxlpe"),
    ("multicore", "Multicore / control cable", "Wires & Cables", r"\b([2-9]|[1-9]\d)\s*core|control cable|braided|multicore|submersible.*cable|flat cable"),
    ("wire", "House wire", "Wires & Cables", r"\bwire\b|sq\.?\s*mm|sqmm|1\s*core|house cable|flexible cable|single core"),
    ("pipe", "Conduit pipe", "Rigid Conduits", r"conduit pipe|\bpipe\b|trunking|casing|flexible conduit"),
    ("fitting", "Conduit fitting", "Conduit Fittings", r"fan box|bend|coupler|circular box|junction box|\btee\b|elbow|saddle|reducer|adaptor.*mm|inspection"),
    ("lug", "Lug / accessory", "Lugs & Accessories", r"\blugs?\b|gland|ferrule|tape|cable tie|thimble"),
    ("rccb", "RCCB / RCBO", "Protection & Switchgear", r"rccb|rcbo|elcb|residual current"),
    ("mcb", "MCB", "Protection & Switchgear", r"\bmcb\b|miniature circuit"),
    ("isolator", "Isolator / changeover", "Protection & Switchgear", r"isolator|changeover|change over|\bmccb\b|switch disconnector|fuse"),
    ("db", "Distribution board", "Distribution Boards & Enclosures", r"distribution board|\bdb\b|enclosure|spn|tpn"),
    ("starter", "Motor starter / contactor", "Industrial Control", r"induction motor|\bmotor\b|starter|contactor|control auxiliar|overload|relay|timer|mpcb|push button|indicator lamp"),
    ("switch", "Switch / socket", "Switches & Sockets", r"regulator"),  # fan regulators are not fans
    ("fan", "Fan", "Fans", r"\bfans?\b"),
    ("pump", "Water pump", "Water Pumps", r"\bpumps?\b|monoblock|submersible"),
    ("heater", "Water heater", "Water Heaters", r"water heater|geyser|immersion"),
    ("plate", "Modular plate / box", "Modular Plates & Boxes", r"\bplates?\b|concealed box|metal box|surface box|modular box|gang box|\bframe\b"),
    ("switch", "Switch / socket", "Switches & Sockets", r"extension board|multi plug|adaptor|spike|switch|socket|buzzer|regulator|dimmer|bell push|usb charger|blank|\bmodule\b|connector|indicator"),
    ("light", "Lighting", "Lighting", r"\bled\b|light|lamp|wall washer|well glass|torch|driver|gobleto|e27|bulb|batten|tube|downlight|panel|spot|flood|lumin|cfl|holder"),
    ("appliance", "Home appliance", "Home Appliances", r"cooler|kettle|iron|purifier|mixer|toaster|chimney|stabili[sz]er|inverter|\bups\b|doorbell|bell"),
]


def classify(title: str):
    t = title.lower()
    for key, label, cat, pat in TYPES:
        if re.search(pat, t):
            return key, label, cat
    return "other", "Electrical product", "Other Electricals"


def _num(m):
    return m.group(1).rstrip("0").rstrip(".") if "." in m.group(1) else m.group(1)


def specs(title: str, brand: str, kind: str) -> dict:
    t = title.lower().replace("sq. mm", "sq mm")
    s = {"Brand": brand}
    if (m := re.search(r"(\d+(?:\.\d+)?)\s*(?:sq\.?\s*mm|sqmm|sq mm|mm2|mm²)", t)):
        s["Size"] = f"{_num(m)} sq mm"
    if (m := re.search(r"(\d+)\s*core", t)):
        s["Cores"] = m.group(1)
    if kind in ("wire", "multicore", "armoured", "coax"):
        if (m := re.search(r"(\d+)\s*(?:m|mtr|mtrs|meters?|metres?)\b(?!m)", t)):
            s["Length"] = f"{m.group(1)} m"
        for k, v in [("fr-lsh", "FR-LSH"), ("frlsh", "FR-LSH"), ("frls", "FRLS"), ("hffr", "HFFR"),
                     ("zhfr", "ZHFR"), ("hrfr", "HRFR"), ("hr fr", "HRFR"), ("lszh", "LSZH"),
                     ("low smoke", "FR-LSH"), ("flame retardant", "FR"), ("fr", "FR")]:
            if re.search(r"\b" + re.escape(k) + r"\b", t):
                s["Insulation"] = v
                break
    if (m := re.search(r"(\d+(?:\.\d+)?)\s*a\b", t)) and kind in ("mcb", "rccb", "isolator", "switch", "starter", "db"):
        s["Current rating"] = f"{_num(m)} A"
    for w, n in (("single pole", "SP"), ("double pole", "DP"), ("triple pole", "TP"), ("four pole", "FP")):
        if w in t:
            s["Poles"] = n
    if (m := re.search(r"\b(sp|dp|tp|fp|spn|tpn|1p|2p|3p|4p)\b|(\d)\s*pole", t)):
        s["Poles"] = (m.group(1) or m.group(2) + "P").upper()
    if (m := re.search(r"(\d+)\s*(?:ma)\b", t)):
        s["Sensitivity"] = f"{m.group(1)} mA"
    if (m := re.search(r"\b(\d+)\s*(?:m|module|modules)\b", t)) and kind in ("plate", "switch"):
        s["Modules"] = m.group(1)
    if (m := re.search(r"(\d+(?:\.\d+)?)\s*w\b", t)) and kind in ("light", "fan", "heater", "appliance"):
        s["Wattage"] = f"{_num(m)} W"
    if (m := re.search(r"(\d{3,4})\s*mm", t)) and kind == "fan":
        s["Sweep"] = f"{m.group(1)} mm"
    if kind == "fan" and "bldc" in t:
        s["Motor"] = "BLDC"
    if (m := re.search(r"(\d+(?:\.\d+)?)\s*hp\b", t)):
        s["Power"] = f"{_num(m)} HP"
    elif (m := re.search(r"(\d+(?:\.\d+)?)\s*kw\b", t)):
        s["Power"] = f"{_num(m)} kW"
    if (m := re.search(r"(\d+(?:\.\d+)?)\s*(?:mm)\b", t)) and kind in ("pipe", "fitting"):
        s["Diameter"] = f"{_num(m)} mm"
    if (m := re.search(r"\b(b22|e27|e14|g9|gu10)\b", t)):
        s["Base"] = m.group(1).upper()
    if (m := re.search(r"\bip\s?(\d{2})\b", t)):
        s["IP rating"] = f"IP{m.group(1)}"
    for c in sorted(COLOURS, key=len, reverse=True):
        if re.search(r"\b" + c + r"\b", t):
            s["Colour"] = c.title()
            break
    if (m := re.search(r"pack of (\d+)", t)):
        s["Pack"] = f"{m.group(1)} pcs"
    return s


def headline(s: dict, kind: str) -> str:
    keys = {"wire": ["Size", "Length"], "multicore": ["Cores", "Size", "Length"], "armoured": ["Cores", "Size"],
            "coax": ["Length"], "mcb": ["Current rating", "Poles"], "rccb": ["Current rating", "Poles", "Sensitivity"],
            "isolator": ["Current rating", "Poles"], "fan": ["Sweep", "Motor"], "light": ["Wattage", "Base"],
            "pump": ["Power"], "plate": ["Modules"], "switch": ["Current rating", "Modules"],
            "pipe": ["Diameter"], "fitting": ["Diameter"], "heater": ["Wattage"]}.get(kind, [])
    out = []
    for k in keys:
        if k in s:
            out.append(f"{s[k]} core" if k == "Cores" else f"{s[k]} module" if k == "Modules" else s[k])
    return "  ·  ".join(out)


# shop categories a classified type goes to when the product is still "Uncategorized"
CATALOGUE_CATEGORY_HINT = {"lugs & accessories": "Lugs & Accessories", "pipes & fittings": "Conduit Fittings"}


def shop_category(row_category: str, kind: str, cat: str) -> str:
    hint = CATALOGUE_CATEGORY_HINT.get((row_category or "").strip().lower())
    return hint if hint and kind == "other" else cat


def spec_rows(s: dict) -> list:
    return [(k, v) for k, v in s.items() if v]


def long_description(title: str, label: str, s: dict) -> str:
    rows = "".join(f"<tr><th>{html.escape(k)}</th><td>{html.escape(v)}</td></tr>" for k, v in spec_rows(s))
    return (f"<p>{html.escape(title)}.</p><p>Product type: {html.escape(label)}.</p>"
            f"<h2>Specifications</h2><table class=\"rte-specs\"><tbody>{rows}</tbody></table>"
            "<h2>Buying from RTech Electricals</h2>"
            "<ul><li>Prices shown include GST.</li>"
            "<li>For bulk quantities, a different length or delivery to site, use Request a Quote and we reply with our best price.</li>"
            "<li>Please check the brand, model and specification against your requirement before ordering.</li></ul>")


# written into descriptions while products carried our drawings (16 Oct 2026); removed with them
ILLUSTRATION_NOTE = "<p><small>The picture is an illustration of the product type, not a photo of this exact item.</small></p>"


def short_description(s: dict) -> str:
    items = "".join(f"<li>{html.escape(k)}: {html.escape(v)}</li>" for k, v in spec_rows(s))
    return f"<ul class=\"rte-keyspecs\">{items}</ul><p>Prices include GST.</p>"


def tile_inputs(kind: str, label: str, s: dict) -> dict:
    """Exactly what the illustration shows; identical inputs share one image."""
    return {"kind": kind, "label": label, "brand": s.get("Brand", ""), "head": headline(s, kind),
            "colour": s.get("Colour") if kind in ("wire", "pipe", "multicore") else None,
            "cores": s.get("Cores") if kind in ("multicore", "armoured") else None,
            "poles": s.get("Poles") if kind in ("mcb", "rccb", "isolator") else None,
            "modules": s.get("Modules") if kind == "plate" else None}


def tile_name(ti: dict) -> str:
    key = "|".join(str(ti[k]) for k in sorted(ti))
    slug = re.sub(r"[^a-z0-9]+", "-", f"{ti['brand']} {ti['kind']} {ti['head']}".lower()).strip("-")[:60]
    return f"{slug}-{hashlib.sha1(key.encode()).hexdigest()[:8]}.webp"


def plan_row(title: str, brand: str, row_category: str = "") -> dict:
    kind, label, cat = classify(title)
    s = specs(title, brand, kind)
    ti = tile_inputs(kind, label, s)
    return {"kind": kind, "label": label, "category": shop_category(row_category, kind, cat),
            "brand": brand, "specs": s, "description": long_description(title, label, s),
            "short_description": short_description(s), "tile": ti, "tile_name": tile_name(ti)}
