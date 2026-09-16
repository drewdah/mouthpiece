"""Old black LCD readout with red glowing 14-segment text (DSEG14 Classic, OFL).

Rendered with Pillow (Tk cannot load a font file itself), cached per (lines, scroll, size)
so the 30 fps loop only re-renders when the transcript or scroll position changes.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_DIR = Path(__file__).with_name("fonts")
FONT_FILE = FONT_DIR / "DSEG14Classic-Regular.ttf"

LCD_BG = "#070707"
LCD_GHOST = (60, 10, 8)          # unlit segment ghosting
LCD_TEXT = (255, 70, 50)
LCD_GLOW = (255, 40, 20)
STYLES = {                      # style: (colour, glow alpha)
    "you": ((235, 120, 60), 120),
    "bot": ((255, 70, 50), 170),
    "sys": ((150, 105, 45), 0),          # gateway notice: dim amber, no glow, never spoken
    "silent": ((125, 32, 26), 0),        # reply that produced no audio: dim, no glow
}
LINE_H = 17
FONT_PX = 11
PAD_X = 8
PAD_Y = 6


class LcdRenderer:
    def __init__(self) -> None:
        try:
            self.font = ImageFont.truetype(str(FONT_FILE), FONT_PX)
            self.segment = True
        except OSError:
            self.font = ImageFont.truetype("consola.ttf", FONT_PX) if _has("consola.ttf") else ImageFont.load_default()
            self.segment = False
        self.char_w = max(1.0, self.font.getlength("M"))
        self._cache_key = None
        self._cache_img: Image.Image | None = None

    # ---- text layout ------------------------------------------------------
    def wrap(self, captions, width: int) -> list[tuple[str, str]]:
        """Flatten captions into LCD lines: (text, style), wrapped by measured pixel width.

        Caption tuples are (who, text, final[, kind[, id]]). Styles: you / bot / sys / silent.
        DSEG14 quirks: the space glyph is 3 px, "!" is the full blank cell (so word gaps use
        it), and "." is a zero-advance dot on the previous cell.
        """
        avail = width - 2 * PAD_X
        gap = "!" if self.segment else " "
        lines: list[tuple[str, str]] = []
        for cap in captions:
            who, text = cap[0], cap[1]
            kind = cap[3] if len(cap) > 3 else "reply"
            is_bot = who != "you"
            if not is_bot:
                style, tag = "you", "YOU"
            elif kind == "system":
                style, tag = "sys", "SYS"
            elif kind == "silent":
                style, tag = "silent", who[:6]
            else:
                style, tag = "bot", who[:6]
            if self.segment:
                # DSEG has no pictographs: drop anything outside printable ASCII (the notice glyphs)
                text = "".join(ch for ch in text if 32 <= ord(ch) < 127).strip()
            if not text:
                continue
            body = f"{tag}: {text}".replace(chr(10), " ")
            if kind == "silent":
                body += " (NO AUDIO)"
            if self.segment:
                body = body.upper()
            cur = ""
            for wd in body.split():
                while self.font.getlength(wd) > avail:      # a single word longer than the screen
                    cut = max(1, int(len(wd) * avail / self.font.getlength(wd)))
                    lines.append((wd[:cut], style))
                    wd = wd[cut:]
                cand = wd if not cur else cur + gap + wd
                if self.font.getlength(cand) <= avail:
                    cur = cand
                else:
                    lines.append((cur, style))
                    cur = wd
            if cur:
                lines.append((cur, style))
        return lines

    # ---- rendering --------------------------------------------------------
    def render(self, lines: list[tuple[str, str]], scroll: int, width: int, height: int, visible: int = 3) -> Image.Image:
        """scroll = number of lines above the bottom that are hidden (0 = pinned to the newest)."""
        total = len(lines)
        end = max(0, total - scroll)
        start = max(0, end - visible)
        window = lines[start:end]
        key = (tuple(window), width, height, visible, start, total)
        if key == self._cache_key and self._cache_img is not None:
            return self._cache_img

        img = Image.new("RGB", (width, height), LCD_BG)
        # unlit ghost segments so the panel reads as an LCD even when idle
        ghost = Image.new("RGB", (width, height), LCD_BG)
        gd = ImageDraw.Draw(ghost)
        cols = max(8, int((width - 2 * PAD_X) / self.char_w))
        ghost_row = "~" * cols if self.segment else ""
        for i in range(visible):
            y = PAD_Y + i * LINE_H
            if ghost_row:
                gd.text((PAD_X, y), ghost_row, font=self.font, fill=LCD_GHOST)
        img = Image.blend(img, ghost, 0.55)

        if window:
            glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            crisp = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            gd = ImageDraw.Draw(glow)
            cd = ImageDraw.Draw(crisp)
            for i, (text, style) in enumerate(window):
                y = PAD_Y + i * LINE_H
                col, glow_a = STYLES.get(style, STYLES["bot"])
                if glow_a:
                    gd.text((PAD_X, y), text, font=self.font, fill=LCD_GLOW + (glow_a,))
                cd.text((PAD_X, y), text, font=self.font, fill=col + (255,))
            glow = glow.filter(ImageFilter.GaussianBlur(2.5))
            img = Image.alpha_composite(img.convert("RGBA"), glow)
            img = Image.alpha_composite(img, crisp).convert("RGB")
        self._cache_key, self._cache_img = key, img
        return img

    @staticmethod
    def max_scroll(total_lines: int, visible: int = 3) -> int:
        return max(0, total_lines - visible)


def _has(name: str) -> bool:
    try:
        ImageFont.truetype(name, 10)
        return True
    except OSError:
        return False
