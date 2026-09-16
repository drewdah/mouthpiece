"""KITT skin: the voice modulator at the base of the steering column of the 1982 Trans Am.

Ported from the cast-skins desktop plugin (KittClusterAvatar) and pushed toward the show's
dash: black vinyl panel, a narrow black well holding three tight LED columns (side 11
segments, centre 15) lit red from the centre outward, a 16-segment scanner bar below,
backlit coloured tiles with black legends on the rails (the D1/S1/AUTO CRUISE language),
amber dash lettering, and a separate bezelled LCD readout at the bottom with red glowing
14-segment transcript text, three lines visible, scroll arrows on its right edge.

Clickable tiles: MIC (mute/unmute), LINK (leave), the state tile while VOICE (stop talking),
and the LCD scroll arrows. Hover is subtle: slightly brighter face, light edge, hand cursor.
"""
from __future__ import annotations

import math
import random
import time
import tkinter as tk
from dataclasses import dataclass

from PIL import ImageTk

from .lcd import LINE_H, PAD_Y, LcdRenderer

MID_SEGS = 15
SIDE_SEGS = 11
BAR_SEGS = 16
LCD_LINES = 3

CORE_RED = "#FF1A1A"
TIP_RED = "#6E0810"
TOP_RED = "#FF3A3A"
BOT_RED = "#3A0408"
UNLIT_TOP = "#2A1014"
UNLIT_BOT = "#14080C"

PANEL_BG = "#0B0B0C"
PANEL_EDGE = "#26262A"
BEZEL = "#1C1C1F"
BEZEL_HI = "#3A3A40"
WELL_BG = "#000000"
LABEL_AMBER = "#E5B92A"
LABEL_DIM = "#7A6A3A"

TILES = {
    "red": ("#C8261B", "#1A0604"),
    "amber": ("#E27F1C", "#1F1004"),
    "yellow": ("#E5C11E", "#1F1A04"),
    "green": ("#2D9A3E", "#061A08"),
    "dark": ("#242427", "#8A8A90"),
}


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def hex_lerp(a: str, b: str, t: float) -> str:
    t = max(0.0, min(1.0, t))
    A, B = _hex(a), _hex(b)
    return "#%02x%02x%02x" % tuple(round(A[i] + (B[i] - A[i]) * t) for i in range(3))


@dataclass
class Button:
    id: str
    x0: float
    y0: float
    x1: float
    y1: float

    def hit(self, x: float, y: float) -> bool:
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1


class KittSkin:
    name = "kitt"
    size = (340, 300)

    def __init__(self, accent: str = CORE_RED) -> None:
        self.accent = accent
        self.mid = 0.0
        self.side = 0.0
        self.head = int(BAR_SEGS * 0.4)
        self.dir = 1
        self._last_chase = 0.0
        self._t0 = time.monotonic()
        self._noise = [random.random() for _ in range(4)]
        self.buttons: list[Button] = []
        self.lcd = LcdRenderer()
        self._lcd_photo = None
        self.lcd_rect = (0, 0, 0, 0)
        self.lcd_total_lines = 0

    # ---- dynamics -----------------------------------------------------------
    def step(self, state: str, spk_level: float, mic_level: float, dt: float) -> None:
        t = time.monotonic() - self._t0
        n = self._noise
        if state == "speaking":
            loud = min(1.0, spk_level * 16.0)
            s1 = max(0.0, math.sin(t * 9.5 + n[0] * 1.3))
            s2 = max(0.0, math.sin(t * 3.8 + n[1] * 1.6))
            s3 = abs(math.sin(t * 17.0 + n[2]))
            speech = 0.55 * s1 + 0.3 * s2 + 0.15 * s3
            target = min(1.0, (0.45 + 0.55 * speech) * loud) if loud > 0.02 else 0.0
            atk_up, atk_dn = 0.28, 0.09
        elif state == "listening":
            target = min(0.35, mic_level * 6.0)
            atk_up, atk_dn = 0.2, 0.08
        else:
            target = 0.0
            atk_up, atk_dn = 0.2, 0.06
        k = dt * 60.0
        atk = atk_up if target > self.mid else atk_dn
        self.mid += (target - self.mid) * min(1.0, atk * k)
        side_target = min(1.0, self.mid * (0.88 + 0.12 * min(1.0, self.mid)))
        atk_s = atk_up * 0.95 if side_target > self.side else atk_dn
        self.side += (side_target - self.side) * min(1.0, atk_s * k)

        now = time.monotonic()
        period = 0.07 if state == "thinking" else (0.16 if state == "listening" else None)
        if period is not None and now - self._last_chase >= period:
            self._last_chase = now
            nxt = self.head + self.dir
            if nxt >= BAR_SEGS - 1:
                self.dir, nxt = -1, BAR_SEGS - 1
            elif nxt <= 0:
                self.dir, nxt = 1, 0
            self.head = nxt
        elif period is None:
            self.head = int(BAR_SEGS * 0.4)

    # ---- painting -----------------------------------------------------------
    def paint(self, cv: tk.Canvas, w: int, h: int, *, state: str, muted: bool, bot_display: str,
              captions: list[tuple[str, str, bool]], hover: str | None = None, pressed: str | None = None,
              scroll: int = 0) -> None:
        cv.delete("all")
        self.buttons = []
        cv.create_rectangle(0, 0, w, h, fill=PANEL_BG, outline=PANEL_EDGE)
        cv.create_rectangle(1, 1, w - 2, h - 2, fill="", outline=BEZEL)

        pad = 10
        head_h = 14
        bar_h = 8
        lcd_h = 2 * PAD_Y + LCD_LINES * LINE_H      # 78
        lcd_bezel = 6
        lcd_block = lcd_h + 2 * lcd_bezel
        well_top = pad + head_h
        well_bottom = h - pad - lcd_block - 10 - bar_h - 8
        well_h = max(60, well_bottom - well_top)

        # header lettering
        cv.create_text(pad + 2, pad, text=f"{bot_display.upper()}  ·  VOICE SYNTHESIZER", anchor="nw",
                       fill=LABEL_AMBER, font=("Segoe UI", 7, "bold"))
        cv.create_text(w - pad - 2, pad, text="2000", anchor="ne", fill=LABEL_DIM, font=("Segoe UI", 7, "bold"))

        # narrow LED well
        col_w, gap, well_pad = 20, 6, 7
        well_w = 3 * col_w + 2 * gap + 2 * well_pad
        wx0 = (w - well_w) / 2
        cv.create_rectangle(wx0 - 2, well_top - 2, wx0 + well_w + 2, well_top + well_h + 2, fill=BEZEL, outline="#333")
        cv.create_rectangle(wx0, well_top, wx0 + well_w, well_top + well_h, fill=WELL_BG, outline="")
        for i, (segs, level, hp) in enumerate([(SIDE_SEGS, self.side, 0.76), (MID_SEGS, self.mid, 1.0),
                                                (SIDE_SEGS, self.side, 0.76)]):
            x = wx0 + well_pad + i * (col_w + gap)
            ch = (well_h - 2 * well_pad) * hp
            y0 = well_top + well_pad + ((well_h - 2 * well_pad) - ch) / 2
            self._paint_segs(cv, x, y0, col_w, ch, segs, level)
        for side in (-1, 1):
            tx = wx0 - 8 if side < 0 else wx0 + well_w + 8
            for j in range(9):
                ty = well_top + 6 + j * (well_h - 12) / 8
                ln = 6 if j % 4 == 0 else 3
                cv.create_line(tx - (ln if side < 0 else 0), ty, tx + (ln if side > 0 else 0), ty, fill=LABEL_DIM)

        # scanner bar
        by0 = well_top + well_h + 10
        bar_w = well_w + 60
        self._paint_bar(cv, (w - bar_w) / 2, by0, bar_w, bar_h, busy=(state == "thinking"), sweeping=(state == "listening"))

        # rails: tiles, some clickable
        rail_w = 56
        link_tone = "green" if state not in ("off", "error", "joining") else "amber"
        speaking = state == "speaking"
        state_tile = {"in room": ("READY", "dark"), "listening": ("HEARS", "yellow"), "thinking": ("THINK", "amber"),
                      "speaking": ("VOICE", "red"), "joining": ("DIAL", "amber")}.get(state, (state.upper()[:5], "dark"))
        mic_label = ("UNMUTE" if muted else "MUTE") if hover == "mic" else "MIC"
        link_label = "LEAVE" if hover == "link" else "LINK"
        stop_label = "STOP" if (hover == "stop" and speaking) else state_tile[0]
        left = [("mic", mic_label, "red" if muted else "green"), ("link", link_label, link_tone),
                (None, "AUTO", "amber"), (None, "S1", "dark")]
        right = [(None, bot_display[:5].upper(), "red"), ("stop" if speaking else None, stop_label, state_tile[1]),
                 (None, "PWR", "green"), (None, "P2", "dark")]
        self._paint_rail(cv, pad, well_top, rail_w, well_h, left, hover, pressed)
        self._paint_rail(cv, w - pad - rail_w, well_top, rail_w, well_h, right, hover, pressed)

        # LCD readout block
        ly0 = h - pad - lcd_block
        self._paint_lcd(cv, pad, ly0, w - 2 * pad, lcd_block, lcd_bezel, captions, scroll, hover, pressed)

    def _paint_lcd(self, cv, x, y, w, h, bezel, captions, scroll, hover, pressed) -> None:
        arrow_w = 18
        # bezel: dark plastic frame with a highlight edge, screen recessed inside
        cv.create_rectangle(x, y, x + w, y + h, fill=BEZEL, outline=BEZEL_HI)
        cv.create_line(x + 1, y + 1, x + w - 1, y + 1, fill="#4A4A52")
        sx, sy = x + bezel, y + bezel
        sw, sh = w - 2 * bezel - arrow_w - 4, h - 2 * bezel
        cv.create_rectangle(sx - 1, sy - 1, sx + sw + 1, sy + sh + 1, fill="#000000", outline="#000000")
        lines = self.lcd.wrap(captions, int(sw))
        self.lcd_total_lines = len(lines)
        scroll = max(0, min(scroll, self.lcd.max_scroll(len(lines), LCD_LINES)))
        img = self.lcd.render(lines, scroll, int(sw), int(sh), LCD_LINES)
        self._lcd_photo = ImageTk.PhotoImage(img)
        cv.create_image(sx, sy, image=self._lcd_photo, anchor="nw")
        self.lcd_rect = (sx, sy, sx + sw, sy + sh)
        # scroll arrows on the right edge
        ax = sx + sw + 4
        ah = (sh - 4) / 2
        can_up = scroll < self.lcd.max_scroll(len(lines), LCD_LINES)
        can_down = scroll > 0
        self._tile(cv, ax, sy, arrow_w, ah, "▲", "dark" if can_up else "dark", hover=(hover == "scroll_up"),
                   pressed=(pressed == "scroll_up"), font_size=7, legend_override=None if can_up else "#3A3A40")
        self._tile(cv, ax, sy + ah + 4, arrow_w, ah, "▼", "dark", hover=(hover == "scroll_down"),
                   pressed=(pressed == "scroll_down"), font_size=7, legend_override=None if can_down else "#3A3A40")
        self.buttons.append(Button("scroll_up", ax, sy, ax + arrow_w, sy + ah))
        self.buttons.append(Button("scroll_down", ax, sy + ah + 4, ax + arrow_w, sy + sh))

    def _paint_segs(self, cv, x, y, w, h, count, level) -> None:
        mid = (count - 1) / 2
        lv = max(0.0, min(1.0, level))
        lit_radius = mid + 0.05 if lv >= 0.97 else lv * mid
        seg_h = h / count
        for i in range(count):
            dist = abs(i - mid)
            on = lv > 0.02 and dist <= lit_radius + 0.001
            sy = y + i * seg_h
            if on:
                u = min(1.0, dist / max(lit_radius, 0.001)) if lit_radius > 0 else 0.0
                face = hex_lerp(self.accent, TIP_RED, u * 0.92)
                topc = hex_lerp(TOP_RED, face, 0.55 + 0.25 * u)
                botc = hex_lerp(face, BOT_RED, 0.45)
                third = seg_h / 3
                cv.create_rectangle(x, sy, x + w, sy + third, fill=topc, outline="")
                cv.create_rectangle(x, sy + third, x + w, sy + 2 * third, fill=face, outline="")
                cv.create_rectangle(x, sy + 2 * third, x + w, sy + seg_h - 1, fill=botc, outline="")
            else:
                cv.create_rectangle(x, sy, x + w, sy + seg_h / 2, fill=UNLIT_TOP, outline="")
                cv.create_rectangle(x, sy + seg_h / 2, x + w, sy + seg_h - 1, fill=UNLIT_BOT, outline="")
            cv.create_line(x, sy + seg_h - 1, x + w, sy + seg_h - 1, fill="#000000")

    def _paint_bar(self, cv, x, y, w, h, *, busy: bool, sweeping: bool) -> None:
        seg_w = (w - (BAR_SEGS - 1) * 2) / BAR_SEGS
        idle = {int(BAR_SEGS * 0.35), int(BAR_SEGS * 0.4), int(BAR_SEGS * 0.45)}
        for i in range(BAR_SEGS):
            sx = x + i * (seg_w + 2)
            strength = 0.0
            if busy or sweeping:
                d = abs(i - self.head)
                strength = {0: 1.0, 1: 0.55, 2: 0.25}.get(d, 0.0) * (0.6 if sweeping else 1.0)
            elif i in idle:
                strength = 0.35
            color = hex_lerp(WELL_BG, self.accent, strength) if strength > 0 else hex_lerp(WELL_BG, self.accent, 0.12)
            cv.create_rectangle(sx, y, sx + seg_w, y + h, fill=color, outline="")

    def _tile(self, cv, x, y, w, h, text, tone, *, hover=False, pressed=False, font_size=6, legend_override=None) -> None:
        face, legend = TILES.get(tone, TILES["dark"])
        if legend_override:
            legend = legend_override
        if pressed:
            face = hex_lerp(face, "#000000", 0.25)
        elif hover:
            face = hex_lerp(face, "#ffffff", 0.10)
        edge = "#9A9AA0" if hover and not pressed else "#000000"
        cv.create_rectangle(x, y, x + w, y + h, fill=face, outline=edge)
        cv.create_line(x + 1, y + 1, x + w - 1, y + 1, fill=hex_lerp(face, "#ffffff", 0.25))
        cv.create_text(x + w / 2, y + h / 2, text=text, fill=legend, font=("Segoe UI", font_size, "bold"))

    def _paint_rail(self, cv, x, y, w, h, items, hover, pressed) -> None:
        n = len(items)
        tile_h = 17
        spacing = (h - n * tile_h) / max(1, n - 1) if n > 1 else 0
        for i, (bid, label, tone) in enumerate(items):
            ty = y + i * (tile_h + spacing)
            self._tile(cv, x, ty, w, tile_h, label, tone, hover=(bid is not None and hover == bid),
                       pressed=(bid is not None and pressed == bid))
            if bid:
                self.buttons.append(Button(bid, x, ty, x + w, ty + tile_h))

    def button_at(self, x: float, y: float) -> str | None:
        for b in self.buttons:
            if b.hit(x, y):
                return b.id
        return None

    def over_lcd(self, x: float, y: float) -> bool:
        x0, y0, x1, y1 = self.lcd_rect
        return x0 <= x <= x1 and y0 <= y <= y1


SKINS = {"kitt": KittSkin}
