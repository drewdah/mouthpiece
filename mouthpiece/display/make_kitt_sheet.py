"""Generate the KITT face sprite sheet: sheets/kitt.png + kitt.json + kitt_bg.png.

The sheet is the portable part of a face: a PNG atlas plus a JSON index of
named frames ({"frames": {name: [x, y, w, h]}}), and a full-size background
that is drawn once. Any renderer (this one, an ESP32, a web page) can rebuild
the same face from these files. Repaint kitt.png by hand if you like; keep the
frame names and sizes.

Usage: python -m mouthpiece.display.make_kitt_sheet
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "sheets"

W, H = 320, 480
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

# ---- layout constants shared with kitt.py (keep in sync) -------------------
BOX_W, BOX_GAP = 96, 8
SCAN_LAMP = (32, 24)
VOICE_SEG = (58, 9)
LAMP = (96, 40)
BAR_SEG = (8, 16)
BIG_DIGIT = (18, 30)
SMALL_DIGIT = (11, 20)


def font(size, style="SemiBold Condensed"):
    f = ImageFont.truetype(FONT_PATH, size)
    f.set_variation_by_name(style)
    return f


def box_x(i):
    return (W - (3 * BOX_W + 2 * BOX_GAP)) // 2 + i * (BOX_W + BOX_GAP)


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


def frames() -> dict[str, Image.Image]:
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
    lf = font(15, "Bold Condensed")
    for name, (on, off) in (("listen", (GREEN, GREEN_DIM)), ("think", (AMBER, AMBER_DIM)), ("speak", (RED, RED_DIM))):
        for lit in (True, False):
            img = Image.new("RGB", LAMP, BLACK)
            d = ImageDraw.Draw(img)
            d.rounded_rectangle((0, 0, LAMP[0] - 1, LAMP[1] - 1), radius=5,
                                fill=on if lit else BLACK, outline=on if lit else off, width=2)
            label = name.upper()
            tw = d.textlength(label, font=lf)
            d.text(((LAMP[0] - tw) / 2, 10), label, fill=BLACK if lit else scale(off, 2.2), font=lf)
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


def background() -> Image.Image:
    bg = Image.new("RGB", (W, H), BLACK)
    d = ImageDraw.Draw(bg)
    d.text((12, 8), "K.I.T.T.", fill=RED, font=font(24, "Bold Condensed"))
    d.line([(12, 38), (W - 12, 38)], fill=RED_LINE, width=1)
    d.rounded_rectangle((10, 46, 310, 228), radius=6, outline=RED_LINE, width=1)
    d.rounded_rectangle((4, 234, W - 4, 282), radius=4, outline=RED_LINE, width=1)
    d.text((12, 351), "CPU", fill=AMBER, font=font(14))
    d.text((12, 379), "GPU", fill=AMBER, font=font(14))
    for i, label in enumerate(["CPU %", "GPU °C", "RAM %"]):
        x = box_x(i)
        d.rounded_rectangle((x, 410, x + BOX_W, 472), radius=4, outline=AMBER_DIM, width=1)
        tw = d.textlength(label, font=font(12))
        d.text((x + (BOX_W - tw) / 2, 415), label, fill=AMBER, font=font(12))
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


def build(out: Path, style: dict | None = None) -> Path:
    """Write kitt.png/kitt.json/kitt_bg.png into `out`; returns the index path."""
    if style:
        apply_style(style)
    out.mkdir(parents=True, exist_ok=True)
    sheet, index = pack(frames())
    sheet.save(out / "kitt.png")
    background().save(out / "kitt_bg.png")
    (out / "kitt.json").write_text(json.dumps({"image": "kitt.png", "background": "kitt_bg.png",
                                               "size": [W, H], "frames": index}, indent=1))
    return out / "kitt.json"


def main() -> None:
    from .registry import load_style
    style = load_style("kitt")
    idx = build(OUT, style)
    print(f"{idx} ({'registry style' if style else 'fallback colours'})")


if __name__ == "__main__":
    main()
