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
    def wrap(self, captions: list[tuple[str, str, bool]], width: int) -> list[tuple[str, bool]]:
        """Flatten captions into LCD lines: (text, is_bot), wrapped by measured pixel width.

        DSEG14 quirks: the space glyph is 3 px, "!" is the full blank cell (so word gaps use
        it), and "." is a zero-advance dot on the previous cell.
        """
        avail = width - 2 * PAD_X
        gap = "!" if self.segment else " "
        lines: list[tuple[str, bool]] = []
        for who, text, final in captions:
            is_bot = who != "you"
            tag = "KITT" if is_bot else "YOU"
            body = f"{tag}: {text}".replace(chr(10), " ")
            if self.segment:
                body = body.upper()
            cur = ""
            for wd in body.split():
                while self.font.getlength(wd) > avail:      # a single word longer than the screen
                    cut = max(1, int(len(wd) * avail / self.font.getlength(wd)))
                    lines.append((wd[:cut], is_bot))
                    wd = wd[cut:]
                cand = wd if not cur else cur + gap + wd
                if self.font.getlength(cand) <= avail:
                    cur = cand
                else:
                    lines.append((cur, is_bot))
                    cur = wd
            if cur:
                lines.append((cur, is_bot))
        return lines

    # ---- rendering --------------------------------------------------------
    def render(self, lines: list[tuple[str, bool]], scroll: int, width: int, height: int, visible: int = 3) -> Image.Image:
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
            for i, (text, is_bot) in enumerate(window):
                y = PAD_Y + i * LINE_H
                col = LCD_TEXT if is_bot else (235, 120, 60)
                gd.text((PAD_X, y), text, font=self.font, fill=LCD_GLOW + (170,))
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
