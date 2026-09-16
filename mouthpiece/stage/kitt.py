"""KITT skin: the voice modulator at the base of the steering column of the 1982 Trans Am.

Ported from the cast-skins desktop plugin (KittClusterAvatar) and pushed closer to the
show's dash: black vinyl panel, a narrow black well holding three tight LED columns
(side 11 segments, centre 15), red-only gradient lit from the centre outward, a 16-segment
scanner bar below, backlit coloured button tiles with black legends on the rails
(the D1/S1/AUTO CRUISE language), amber dash-label typography, and a bottom row of
pressable tiles (NORMAL CRUISE / AUTO CRUISE / PURSUIT in the show; here MUTE / STOP / LEAVE).
"""
from __future__ import annotations

import math
import random
import time
import tkinter as tk
from dataclasses import dataclass

MID_SEGS = 15
SIDE_SEGS = 11
BAR_SEGS = 16

# LED reds (from cast-skins, colour only ever in the red family)
CORE_RED = "#FF1A1A"
TIP_RED = "#6E0810"
TOP_RED = "#FF3A3A"
BOT_RED = "#3A0408"
UNLIT_TOP = "#2A1014"
UNLIT_BOT = "#14080C"

# Dash materials
PANEL_BG = "#0B0B0C"       # black vinyl
PANEL_EDGE = "#26262A"
BEZEL = "#1C1C1F"
WELL_BG = "#000000"
LABEL_AMBER = "#E5B92A"    # the yellow dash lettering
LABEL_DIM = "#7A6A3A"
CAPTION_YOU = "#D9C27A"
CAPTION_BOT = "#FF5A48"

# Backlit button tiles: (face, legend)
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
    size = (340, 250)

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

    # ---- dynamics (voiceLevels from cast-skins, driven by real RMS here) ----
    def step(self, state: str, spk_level: float, mic_level: float, dt: float) -> None:
        t = time.monotonic() - self._t0
        n = self._noise
        if state == "speaking":
            loud = min(1.0, spk_level * 16.0)           # 0.03 RMS ≈ half stack, 0.06 ≈ full
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
              captions: list[tuple[str, str, bool]], hover: str | None = None, pressed: str | None = None) -> None:
        cv.delete("all")
        self.buttons = []
        cv.create_rectangle(0, 0, w, h, fill=PANEL_BG, outline=PANEL_EDGE)
        cv.create_rectangle(1, 1, w - 2, h - 2, fill="", outline=BEZEL)

        pad = 10
        top = pad
        cap_h = 42
        btn_h = 22
        bar_h = 8
        # vertical budget: header 14 · well · 6 · bar · 8 · buttons · 8 · captions
        head_h = 14
        well_top = top + head_h
        well_bottom = h - pad - cap_h - 8 - btn_h - 8 - bar_h - 6
        well_h = max(60, well_bottom - well_top)

        # header: dash lettering
        cv.create_text(pad + 2, top, text=f"{bot_display.upper()}  ·  VOICE SYNTHESIZER", anchor="nw",
                       fill=LABEL_AMBER, font=("Segoe UI", 7, "bold"))
        cv.create_text(w - pad - 2, top, text="2000", anchor="ne", fill=LABEL_DIM, font=("Segoe UI", 7, "bold"))

        # narrow LED well, centred
        col_w, gap, well_pad = 20, 6, 7
        well_w = 3 * col_w + 2 * gap + 2 * well_pad
        wx0 = (w - well_w) / 2
        cv.create_rectangle(wx0 - 2, well_top - 2, wx0 + well_w + 2, well_top + well_h + 2, fill=BEZEL, outline="#333")
        cv.create_rectangle(wx0, well_top, wx0 + well_w, well_top + well_h, fill=WELL_BG, outline="")
        cols = [(SIDE_SEGS, self.side, 0.76), (MID_SEGS, self.mid, 1.0), (SIDE_SEGS, self.side, 0.76)]
        for i, (segs, level, hp) in enumerate(cols):
            x = wx0 + well_pad + i * (col_w + gap)
            ch = (well_h - 2 * well_pad) * hp
            y0 = well_top + well_pad + ((well_h - 2 * well_pad) - ch) / 2
            self._paint_segs(cv, x, y0, col_w, ch, segs, level)

        # tick marks flanking the well, like the dash gauges
        for side in (-1, 1):
            tx = wx0 - 8 if side < 0 else wx0 + well_w + 8
            for j in range(9):
                ty = well_top + 6 + j * (well_h - 12) / 8
                ln = 6 if j % 4 == 0 else 3
                cv.create_line(tx - (ln if side < 0 else 0), ty, tx + (ln if side > 0 else 0), ty, fill=LABEL_DIM)

        # scanner bar under the well
        by0 = well_top + well_h + 10
        bar_w = well_w + 60
        self._paint_bar(cv, (w - bar_w) / 2, by0, bar_w, bar_h, busy=(state == "thinking"), sweeping=(state == "listening"))

        # rails: backlit tiles with black legends
        rail_w = 56
        link_tone = "green" if state not in ("off", "error", "joining") else "amber"
        state_tile = {"in room": ("READY", "dark"), "listening": ("HEARS", "yellow"), "thinking": ("THINK", "amber"),
                      "speaking": ("VOICE", "red"), "joining": ("DIAL", "amber")}.get(state, (state.upper()[:5], "dark"))
        left = [("MIC", "red" if muted else "green"), ("LINK", link_tone), ("AUTO", "amber"), ("S1", "dark")]
        right = [(bot_display[:5].upper(), "red"), state_tile, ("PWR", "green"), ("P2", "dark")]
        self._paint_rail(cv, pad, well_top, rail_w, well_h, left)
        self._paint_rail(cv, w - pad - rail_w, well_top, rail_w, well_h, right)

        # bottom row: pressable tiles
        by = by0 + bar_h + 8
        labels = [("mute", "UNMUTE" if muted else "MUTE", "amber" if muted else "dark"),
                  ("stop", "STOP", "red" if state == "speaking" else "dark"),
                  ("leave", "LEAVE", "dark")]
        bw = (w - 2 * pad - 2 * 6) / 3
        for i, (bid, text, tone) in enumerate(labels):
            x0 = pad + i * (bw + 6)
            self._paint_button(cv, bid, x0, by, bw, btn_h, text, tone, hover == bid, pressed == bid)

        # captions (fixed height so the layout never jumps)
        cy = h - pad - cap_h + 2
        for who, text, final in captions[-2:]:
            is_bot = who != "you"
            color = CAPTION_BOT if is_bot else CAPTION_YOU
            line = f"{who.upper()}: {text}".replace("\n", " ")
            cv.create_text(pad + 2, cy, text=line, anchor="nw", fill=color if final else hex_lerp(color, PANEL_BG, 0.35),
                           font=("Segoe UI", 8), width=w - 2 * pad - 4)
            cy += 19

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

    def _tile(self, cv, x, y, w, h, text, tone, *, hover=False, pressed=False, font_size=6) -> None:
        face, legend = TILES.get(tone, TILES["dark"])
        if pressed:
            face = hex_lerp(face, "#000000", 0.3)
        elif hover:
            face = hex_lerp(face, "#ffffff", 0.18)
        edge = "#ffffff" if hover and not pressed else "#000000"
        cv.create_rectangle(x, y, x + w, y + h, fill=face, outline=edge)
        # a faint backlight highlight along the top edge
        cv.create_line(x + 1, y + 1, x + w - 1, y + 1, fill=hex_lerp(face, "#ffffff", 0.25))
        cv.create_text(x + w / 2, y + h / 2, text=text, fill=legend, font=("Segoe UI", font_size, "bold"))

    def _paint_rail(self, cv, x, y, w, h, items) -> None:
        n = len(items)
        tile_h = 17
        spacing = (h - n * tile_h) / max(1, n - 1) if n > 1 else 0
        for i, (label, tone) in enumerate(items):
            self._tile(cv, x, y + i * (tile_h + spacing), w, tile_h, label, tone)

    def _paint_button(self, cv, bid, x, y, w, h, text, tone, hover, pressed) -> None:
        self._tile(cv, x, y, w, h, text, tone, hover=hover, pressed=pressed, font_size=7)
        self.buttons.append(Button(bid, x, y, x + w, y + h))

    def button_at(self, x: float, y: float) -> str | None:
        for b in self.buttons:
            if b.hit(x, y):
                return b.id
        return None


SKINS = {"kitt": KittSkin}
