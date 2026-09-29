"""Generate the KITT face sprite sheet: sheets/kitt.png + kitt.json + kitt_bg.png
(and kitt_landscape.* for the 480x320 layout).

The sheet is the portable part of a face: a PNG atlas plus a JSON index of
named frames ({"frames": {name: [x, y, w, h]}}), and a full-size background
that is drawn once. Any renderer (this one, an ESP32, a web page) can rebuild
the same face from these files. Repaint kitt.png by hand if you like; keep the
frame names and sizes.

Usage: python -m mouthpiece.display.make_kitt_sheet
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "sheets"

BLACK = (0, 0, 0)
FONT_PATH = r"C:\Windows\Fonts\bahnschrift.ttf"

# Colours come from the cast registry (cast/<id>/style.yaml); these are the
# fallback when the registry isn't reachable. apply_style() overrides them.
RED = (255, 26, 26)          # accent
RED_DIM = (48, 6, 3)         # palette.accent_dim
RED_LINE = (110, 16, 8)      # palette.accent_line
AMBER = (255, 170, 0)        # palette.warn
AMBER_DIM = (60, 38, 0)
GREEN = (60, 220, 90)        # palette.ok
GREEN_DIM = (10, 45, 18)


def _hex(v: str) -> tuple[int, int, int]:
    v = v.lstrip("#")
    return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))


def apply_style(style: dict) -> None:
    """Take accent + palette from a registry style.yaml (dict). Dim variants of
    warn/ok are derived so the registry only carries the semantic colours."""
    global RED, RED_DIM, RED_LINE, AMBER, AMBER_DIM, GREEN, GREEN_DIM
    pal = style.get("palette", {})
    RED = _hex(style.get("accent", "#FF1A1A"))
    RED_DIM = _hex(pal["accent_dim"]) if "accent_dim" in pal else tuple(int(c * 0.19) for c in RED)
    RED_LINE = _hex(pal["accent_line"]) if "accent_line" in pal else tuple(int(c * 0.43) for c in RED)
    AMBER = _hex(pal.get("warn", "#FFAA00"))
    AMBER_DIM = tuple(int(c * 0.235) for c in AMBER)
    GREEN = _hex(pal.get("ok", "#3CDC5A"))
    GREEN_DIM = tuple(int(c * 0.2) for c in GREEN)

# ---- layouts (shared with kitt.py) ------------------------------------------
BOX_W, BOX_GAP = 96, 8
SCAN_LAMP = (32, 24)
VOICE_SEG = (58, 9)
BAR_SEG = (8, 16)
BIG_DIGIT = (18, 30)
SMALL_DIGIT = (11, 20)


def box_x(i, w=320):
    return (w - (3 * BOX_W + 2 * BOX_GAP)) // 2 + i * (BOX_W + BOX_GAP)


@dataclass
class KittLayout:
    w: int
    h: int
    voice_panel: tuple[int, int, int, int]
    voice_x0: int
    col_gap: int
    scan_box: tuple[int, int, int, int]
    scan_x0: int
    scan_pitch: int
    lamp: tuple[int, int]                              # mode lamp size
    lamps: list[tuple[int, int]]                       # listen, think, speak positions
    bars: list[tuple[str, int, int, int]]              # label, label x, bar x, y (segment top)
    bar_segs: int
    readouts: list[tuple[str, tuple[int, int, int, int], tuple[int, int], int, str]]
    #          label, box, digits tile pos, digits tile width, align
    clock: tuple[int, int]
    mute: tuple[int, int]
    voice_mid_y: int = 137
    scan_y: int = 246
    suffix: str = ""
    lamp_font: int = 15


PORTRAIT = KittLayout(
    320, 480, (10, 46, 310, 228), 39, 34, (4, 234, 316, 282), 14, 37,
    (96, 40), [(box_x(i), 292) for i in range(3)],
    [("CPU", 12, 56, 352), ("GPU", 12, 56, 380)], 25,
    [(label, (box_x(i), 410, box_x(i) + BOX_W, 472), (box_x(i) + 4, 434), BOX_W - 8, "center")
     for i, label in enumerate(("CPU %", "GPU °C", "RAM %"))],
    (222, 11), (150, 12))

LANDSCAPE = KittLayout(
    480, 320, (8, 46, 290, 228), 42, 20, (4, 234, 476, 282), 22, 58,
    (54, 34), [(298 + i * 60, 46) for i in range(3)],
    [("CPU", 12, 44, 294), ("GPU", 246, 278, 294)], 18,
    [(label, (298, y, 472, y + 42), (384, y + 6), 80, "right")
     for label, y in (("CPU %", 88), ("GPU °C", 136), ("RAM %", 184))],
    (382, 11), (208, 12), suffix="_landscape", lamp_font=13)

LAYOUTS = {"portrait": PORTRAIT, "landscape": LANDSCAPE}


def font(size, style="SemiBold Condensed"):
    f = ImageFont.truetype(FONT_PATH, size)
    f.set_variation_by_name(style)
    return f


def scale(c, k):
    return tuple(min(255, int(v * k)) for v in c)


def rect(size, fill, radius=0):
    img = Image.new("RGB", size, BLACK)
    ImageDraw.Draw(img).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=fill)
    return img


def glyph(ch, size, color, fnt):
    img = Image.new("RGB", size, BLACK)
    d = ImageDraw.Draw(img)
    if ch.strip():
        l, t, r, b = d.textbbox((0, 0), ch, font=fnt)
        d.text(((size[0] - (r - l)) / 2 - l, (size[1] - (b - t)) / 2 - t), ch, fill=color, font=fnt)
    return img


def frames(L: KittLayout = PORTRAIT) -> dict[str, Image.Image]:
    LAMP = L.lamp
    f: dict[str, Image.Image] = {}
    # Scanner lamp brightness levels (x = offline, 0 = resting, 4 = head), red and amber.
    for tag, color in (("r", RED), ("a", AMBER)):
        for lvl, k in enumerate((0.07, 0.12, 0.25, 0.5, 1.0)):
            f[f"scan_{tag}{lvl}"] = rect(SCAN_LAMP, scale(color, k), radius=4)
    f["scan_x"] = rect(SCAN_LAMP, scale(RED, 0.03), radius=4)
    # Voice box segments.
    f["voice_on"] = rect(VOICE_SEG, RED)
    f["voice_off"] = rect(VOICE_SEG, RED_DIM)
    # Mode lamps.
    lf = font(L.lamp_font, "Bold Condensed")
    for name, (on, off) in (("listen", (GREEN, GREEN_DIM)), ("think", (AMBER, AMBER_DIM)), ("speak", (RED, RED_DIM))):
        for lit in (True, False):
            img = Image.new("RGB", LAMP, BLACK)
            d = ImageDraw.Draw(img)
            d.rounded_rectangle((0, 0, LAMP[0] - 1, LAMP[1] - 1), radius=5,
                                fill=on if lit else BLACK, outline=on if lit else off, width=2)
            label = name.upper()
            tw = d.textlength(label, font=lf)
            d.text(((LAMP[0] - tw) / 2, (LAMP[1] - L.lamp_font) / 2 - 2), label,
                   fill=BLACK if lit else scale(off, 2.2), font=lf)
            f[f"lamp_{name}_{'on' if lit else 'off'}"] = img
    # LED bar segments.
    for tag, (on, off) in (("g", (GREEN, GREEN_DIM)), ("a", (AMBER, AMBER_DIM)), ("r", (RED, RED_DIM))):
        f[f"seg_{tag}_on"] = rect(BAR_SEG, on)
        f[f"seg_{tag}_off"] = rect(BAR_SEG, off)
    # Digits: big amber (readouts), small red (clock).
    big, small = font(30), font(20)
    for ch in "0123456789 ":
        key = "sp" if ch == " " else ch
        f[f"big_{key}"] = glyph(ch, BIG_DIGIT, AMBER, big)
        f[f"small_{key}"] = glyph(ch, SMALL_DIGIT, RED, small)
    f["small_colon"] = glyph(":", (6, SMALL_DIGIT[1]), RED, small)
    for ap in ("AM", "PM"):
        f[f"small_{ap}"] = glyph(ap, (24, SMALL_DIGIT[1]), RED, font(15))
    # MIC OFF tag.
    tag = rect((64, 22), RED, radius=4)
    d = ImageDraw.Draw(tag)
    tf = font(14, "Bold Condensed")
    d.text(((64 - d.textlength("MIC OFF", font=tf)) / 2, 2), "MIC OFF", fill=BLACK, font=tf)
    f["mute_on"] = tag
    f["mute_off"] = Image.new("RGB", (64, 22), BLACK)
    return f


def background(L: KittLayout = PORTRAIT) -> Image.Image:
    bg = Image.new("RGB", (L.w, L.h), BLACK)
    d = ImageDraw.Draw(bg)
    d.text((12, 8), "K.I.T.T.", fill=RED, font=font(24, "Bold Condensed"))
    d.line([(12, 38), (L.w - 12, 38)], fill=RED_LINE, width=1)
    d.rounded_rectangle(L.voice_panel, radius=6, outline=RED_LINE, width=1)
    d.rounded_rectangle(L.scan_box, radius=4, outline=RED_LINE, width=1)
    for label, lx, _, y in L.bars:
        d.text((lx, y - 1), label, fill=AMBER, font=font(14))
    for label, (x0, y0, x1, y1), _, _, align in L.readouts:
        d.rounded_rectangle((x0, y0, x1, y1), radius=4, outline=AMBER_DIM, width=1)
        if align == "center":
            tw = d.textlength(label, font=font(12))
            d.text((x0 + (x1 - x0 - tw) / 2, y0 + 5), label, fill=AMBER, font=font(12))
        else:
            d.text((x0 + 8, (y0 + y1) / 2), label, fill=AMBER, font=font(12), anchor="lm")
    return bg


def pack(named: dict[str, Image.Image], width: int = 512) -> tuple[Image.Image, dict]:
    """Shelf packer: rows of frames, tallest first. 1px gutter to avoid bleed."""
    order = sorted(named, key=lambda k: (-named[k].height, k))
    x = y = row_h = 0
    index = {}
    for k in order:
        w, h = named[k].size
        if x + w > width:
            x, y, row_h = 0, y + row_h + 1, 0
        index[k] = [x, y, w, h]
        x += w + 1
        row_h = max(row_h, h)
    sheet = Image.new("RGB", (width, y + row_h), (255, 0, 255))   # magenta = unused
    for k, (fx, fy, _, _) in index.items():
        sheet.paste(named[k], (fx, fy))
    return sheet, index


def build(out: Path, style: dict | None = None, orientation: str = "portrait") -> Path:
    """Write kitt{suffix}.png/.json/_bg.png into `out`; returns the index path."""
    if style:
        apply_style(style)
    L = LAYOUTS[orientation]
    name = f"kitt{L.suffix}"
    out.mkdir(parents=True, exist_ok=True)
    sheet, index = pack(frames(L))
    sheet.save(out / f"{name}.png")
    background(L).save(out / f"{name}_bg.png")
    (out / f"{name}.json").write_text(json.dumps({"image": f"{name}.png", "background": f"{name}_bg.png",
                                                  "size": [L.w, L.h], "frames": index}, indent=1))
    return out / f"{name}.json"


def main() -> None:
    from .registry import load_style
    style = load_style("kitt")
    for orientation in LAYOUTS:
        idx = build(OUT, style, orientation)
        print(f"{idx} ({'registry style' if style else 'fallback colours'})")


if __name__ == "__main__":
    main()
