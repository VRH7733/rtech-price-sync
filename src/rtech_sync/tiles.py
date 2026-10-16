"""Our own product-type illustration (no marketplace or brand artwork, no logos).

Needs Pillow and the Inter font (Ubuntu package fonts-inter); only the enrich-products workflow uses it.
"""
from __future__ import annotations

import math
import os

from PIL import Image, ImageDraw, ImageFont

from .content import WIRE_COLOUR_HEX

W = 800
BG = "#f4f6f8"
INK = "#1d2733"
MUTED = "#5b6875"
ACCENT = "#0b6bcb"
F = os.environ.get("RTE_FONT_PREFIX", "/usr/share/fonts/opentype/inter/Inter-")


def font(weight, size):
    return ImageFont.truetype(f"{F}{weight}.otf", size)


def _coil(d, c, col):
    cx, cy = c
    for i in range(6):
        r = 160 - i * 18
        d.ellipse([cx - r, cy - r * 0.6, cx + r, cy + r * 0.6], outline=col, width=12)
        d.arc([cx - r, cy - r * 0.6, cx + r, cy + r * 0.6], 20, 160, fill="#00000030", width=3)
    d.line([cx + 158, cy + 10, cx + 240, cy + 90], fill=col, width=12)
    d.ellipse([cx + 230, cy + 80, cx + 250, cy + 100], fill="#c8873a")


def _section(d, c, col, cores=3, armour=False):
    cx, cy = c
    if armour:
        d.ellipse([cx - 170, cy - 170, cx + 170, cy + 170], fill="#9aa4ad")
    d.ellipse([cx - 150, cy - 150, cx + 150, cy + 150], fill="#2f3a45")
    d.ellipse([cx - 128, cy - 128, cx + 128, cy + 128], fill="#e9edf1")
    palette = ["#d32f2f", "#f9c400", "#1565c0", "#212121", "#2e7d32", "#6d4c41", "#8a8a8a"]
    n = max(1, min(int(cores or 3), 7))
    rr = 46 if n <= 4 else 34
    for i in range(n):
        a = 2 * math.pi * i / n - math.pi / 2
        x, y = (cx, cy) if n == 1 else (cx + 62 * math.cos(a), cy + 62 * math.sin(a))
        d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=palette[i % len(palette)])
        d.ellipse([x - rr * 0.45, y - rr * 0.45, x + rr * 0.45, y + rr * 0.45], fill="#c8873a")


def _coax(d, c, col):
    cx, cy = c
    for r, f in [(150, "#2f3a45"), (120, "#c0c6cc"), (100, "#f2f2f2"), (34, "#c8873a")]:
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=f)


def _breaker(d, c, col, poles=1):
    cx, cy = c
    n = max(1, min(int(poles), 4))
    w = 90
    x0 = cx - n * w / 2
    for i in range(n):
        x = x0 + i * w
        d.rounded_rectangle([x + 4, cy - 170, x + w - 4, cy + 170], 14, fill="#ffffff", outline="#b8c1ca", width=4)
        d.rounded_rectangle([x + 24, cy - 60, x + w - 24, cy + 30], 8, fill=col)
        d.rectangle([x + 18, cy - 150, x + w - 18, cy - 120], fill="#d8dee4")
        d.rectangle([x + 18, cy + 120, x + w - 18, cy + 150], fill="#d8dee4")


def _box(d, c, col):
    cx, cy = c
    d.rounded_rectangle([cx - 170, cy - 170, cx + 170, cy + 170], 18, fill="#ffffff", outline="#b8c1ca", width=5)
    d.rounded_rectangle([cx - 130, cy - 70, cx + 130, cy + 10], 8, fill="#d8dee4")
    for i in range(6):
        x = cx - 120 + i * 42
        d.rectangle([x, cy - 60, x + 30, cy], fill=ACCENT)
    d.ellipse([cx + 120, cy + 110, cx + 140, cy + 130], fill="#b8c1ca")


def _switch(d, c, col):
    cx, cy = c
    d.rounded_rectangle([cx - 160, cy - 160, cx + 160, cy + 160], 30, fill="#ffffff", outline="#cfd6dd", width=5)
    d.rounded_rectangle([cx - 70, cy - 100, cx + 70, cy + 100], 18, fill="#eef1f4", outline="#cfd6dd", width=4)
    d.rounded_rectangle([cx - 20, cy - 70, cx + 20, cy - 30], 6, fill=ACCENT)


def _plate(d, c, col, modules=4):
    cx, cy = c
    d.rounded_rectangle([cx - 210, cy - 120, cx + 210, cy + 120], 26, fill="#ffffff", outline="#cfd6dd", width=5)
    m = max(1, min(int(modules or 4), 8))
    span = 360 / m
    for i in range(m):
        x = cx - 180 + i * span
        d.rounded_rectangle([x + 6, cy - 80, x + span - 6, cy + 80], 8, fill="#eef1f4", outline="#d8dee4", width=3)


def _fan(d, c, col):
    cx, cy = c
    for k in range(3):
        a = 2 * math.pi * k / 3 - math.pi / 2
        pts = []
        for t in range(0, 21):
            u = t / 20
            ang = a + (u - 0.5) * 0.55
            r = 40 + 150 * math.sin(math.pi * u) ** 0.4 if 0 < u < 1 else 40
            pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
        d.polygon(pts, fill="#8fa3b5")
    d.ellipse([cx - 46, cy - 46, cx + 46, cy + 46], fill="#2f3a45")
    d.rectangle([cx - 8, cy - 190, cx + 8, cy - 46], fill="#2f3a45")


def _bulb(d, c, col):
    cx, cy = c
    d.ellipse([cx - 120, cy - 170, cx + 120, cy + 60], fill="#fff4c2", outline="#e8c95a", width=6)
    d.polygon([(cx - 70, cy + 30), (cx + 70, cy + 30), (cx + 48, cy + 100), (cx - 48, cy + 100)], fill="#fff4c2")
    for i in range(4):
        y = cy + 105 + i * 18
        d.rounded_rectangle([cx - 50, y, cx + 50, y + 12], 5, fill="#9aa4ad")
    d.polygon([(cx - 20, cy + 178), (cx + 20, cy + 178), (cx, cy + 196)], fill="#2f3a45")


def _pump(d, c, col):
    cx, cy = c
    d.rounded_rectangle([cx - 180, cy - 80, cx + 40, cy + 80], 30, fill=ACCENT)
    for i in range(6):
        d.line([cx - 160 + i * 34, cy - 70, cx - 160 + i * 34, cy + 70], fill="#0a58a6", width=6)
    d.ellipse([cx + 20, cy - 100, cx + 180, cy + 100], fill="#2f3a45")
    d.rectangle([cx + 80, cy - 160, cx + 120, cy - 90], fill="#2f3a45")
    d.rectangle([cx - 190, cy + 80, cx + 190, cy + 110], fill="#5b6875")


def _pipe(d, c, col):
    cx, cy = c
    d.rounded_rectangle([cx - 230, cy - 40, cx + 200, cy + 40], 10, fill=col if col != "#f5f5f5" else "#e2e6ea", outline="#9aa4ad", width=4)
    d.ellipse([cx + 170, cy - 40, cx + 230, cy + 40], fill="#d8dee4", outline="#9aa4ad", width=4)
    d.ellipse([cx + 188, cy - 22, cx + 212, cy + 22], fill="#5b6875")


def _fitting(d, c, col):
    cx, cy = c
    d.arc([cx - 160, cy - 160, cx + 160, cy + 160], 180, 270, fill="#9aa4ad", width=80)
    d.rectangle([cx - 200, cy, cx - 120, cy + 80], fill="#9aa4ad")
    d.rectangle([cx, cy - 200, cx + 80, cy - 120], fill="#9aa4ad")


def _heater(d, c, col):
    cx, cy = c
    d.rounded_rectangle([cx - 110, cy - 180, cx + 110, cy + 160], 60, fill="#ffffff", outline="#cfd6dd", width=6)
    d.ellipse([cx - 30, cy - 40, cx + 30, cy + 20], fill=ACCENT)
    d.rectangle([cx - 50, cy + 160, cx - 30, cy + 200], fill="#9aa4ad")
    d.rectangle([cx + 30, cy + 160, cx + 50, cy + 200], fill="#9aa4ad")


def _plug(d, c, col):
    cx, cy = c
    d.rounded_rectangle([cx - 110, cy - 90, cx + 110, cy + 110], 30, fill="#2f3a45")
    d.rectangle([cx - 60, cy - 190, cx - 30, cy - 90], fill="#9aa4ad")
    d.rectangle([cx + 30, cy - 190, cx + 60, cy - 90], fill="#9aa4ad")
    d.polygon([(cx + 10, cy - 50), (cx - 40, cy + 20), (cx, cy + 20), (cx - 15, cy + 80), (cx + 45, cy), (cx + 5, cy)], fill="#f9c400")


DRAW = {"wire": _coil, "multicore": _section, "armoured": _section, "coax": _coax, "mcb": _breaker,
        "rccb": _breaker, "isolator": _breaker, "db": _box, "starter": _box, "switch": _switch,
        "plate": _plate, "fan": _fan, "light": _bulb, "pump": _pump, "pipe": _pipe, "fitting": _fitting,
        "heater": _heater}


def _fit(d, text, weight, size, maxw):
    while size > 18:
        f = font(weight, size)
        if d.textlength(text, font=f) <= maxw:
            return f
        size -= 2
    return font(weight, size)


def render(ti: dict, out_path: str) -> None:
    """ti: content.tile_inputs(...)."""
    kind = ti["kind"]
    im = Image.new("RGB", (W, W), BG)
    d = ImageDraw.Draw(im)
    colour = (ti.get("colour") or "").lower()
    col = WIRE_COLOUR_HEX.get(colour, "#c62828" if kind == "wire" else ACCENT)
    fn = DRAW.get(kind, _plug)
    centre = (W // 2, 270)
    if kind in ("multicore", "armoured"):
        fn(d, centre, col, ti.get("cores") or 3, kind == "armoured")
    elif kind in ("mcb", "rccb", "isolator"):
        p = (ti.get("poles") or "1")[0]
        fn(d, centre, col, int(p) if p.isdigit() else {"S": 1, "D": 2, "T": 3, "F": 4}.get(p, 1))
    elif kind == "plate":
        fn(d, centre, col, ti.get("modules") or 4)
    else:
        fn(d, centre, col)
    d.rectangle([0, 520, W, W], fill="#ffffff")
    d.text((48, 548), (ti.get("brand") or "").upper(), font=font("Bold", 34), fill=ACCENT)
    d.text((48, 596), ti["label"], font=font("Medium", 30), fill=MUTED)
    if ti.get("head"):
        d.text((48, 648), ti["head"], font=_fit(d, ti["head"], "Bold", 54, W - 96), fill=INK)
    if colour in WIRE_COLOUR_HEX:
        d.ellipse([W - 96, 552, W - 52, 596], fill=WIRE_COLOUR_HEX[colour], outline="#9aa4ad", width=2)
    d.text((48, 742), "Illustration, not a product photo  ·  rtechelectricals.com", font=font("Regular", 22), fill="#8a96a3")
    im.save(out_path, "WEBP", quality=82, method=6)
