"""KITT instrument-cluster skin, ported from the cast-skins desktop plugin (KittClusterAvatar).

Geometry: three vertical LED wells (side 11 segments at 76% height, mid 15 at 100%),
lit from the centre outward by level. Colour stays in the red family: saturated core,
deeper crimson at the tips, never white. Below: a 16-segment racing bar that chases
while the bot is thinking and glows softly at rest. Side rails carry status chips.
"""
from __future__ import annotations

import math
import random
import time
import tkinter as tk

MID_SEGS = 15
SIDE_SEGS = 11
BAR_SEGS = 16

CORE_RED = "#FF1A1A"
TIP_RED = "#6E0810"
TOP_RED = "#FF3A3A"
BOT_RED = "#3A0408"
UNLIT_TOP = "#2A1014"
UNLIT_BOT = "#14080C"
WELL_BG = "#000000"
PANEL_BG = "#0A0406"
PANEL_EDGE = "#2A0A0E"

CHIP_TONES = {
    "r": ("#5a1010", "#ff6a6a", "#2a0808"),
    "g": ("#1a3a14", "#8fd88f", "#0a1a08"),
    "y": ("#3a3a10", "#e8e070", "#222208"),
    "k": ("#1a1a1a", "#777777", "#111111"),
}


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def hex_lerp(a: str, b: str, t: float) -> str:
    t = max(0.0, min(1.0, t))
    A, B = _hex(a), _hex(b)
    return "#%02x%02x%02x" % tuple(round(A[i] + (B[i] - A[i]) * t) for i in range(3))


class KittSkin:
    name = "kitt"

    def __init__(self, accent: str = CORE_RED) -> None:
        self.accent = accent
        self.mid = 0.0
        self.side = 0.0
        self.head = int(BAR_SEGS * 0.4)
        self.dir = 1
        self._last_chase = 0.0
        self._t0 = time.monotonic()
        self._noise = [random.random() for _ in range(4)]

    # ---- dynamics (from voiceLevels in cast-skins, driven by real RMS here) ----
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
            target = min(0.35, mic_level * 6.0)         # faint pulse so you see it hears you
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

        busy = state == "thinking"
        now = time.monotonic()
        if busy and now - self._last_chase >= 0.07:
            self._last_chase = now
            nxt = self.head + self.dir
            if nxt >= BAR_SEGS - 1:
                self.dir, nxt = -1, BAR_SEGS - 1
            elif nxt <= 0:
                self.dir, nxt = 1, 0
            self.head = nxt
        elif state == "listening" and now - self._last_chase >= 0.16:
            self._last_chase = now
            nxt = self.head + self.dir
            if nxt >= BAR_SEGS - 1:
                self.dir, nxt = -1, BAR_SEGS - 1
            elif nxt <= 0:
                self.dir, nxt = 1, 0
            self.head = nxt
        elif not busy and state != "listening":
            self.head = int(BAR_SEGS * 0.4)

    # ---- painting -----------------------------------------------------------
    def paint(self, cv: tk.Canvas, w: int, h: int, *, state: str, muted: bool, bot_display: str,
              captions: list[tuple[str, str, bool]]) -> None:
        cv.delete("all")
        cv.create_rectangle(0, 0, w, h, fill=PANEL_BG, outline=PANEL_EDGE)

        rail_w = 46
        pad = 10
        cap_h = 44 if captions else 0
        bar_h = 10
        well_top = pad
        well_bottom = h - pad - cap_h - bar_h - 8
        well_h = max(40, well_bottom - well_top)
        inner_x0 = pad + rail_w + 6
        inner_x1 = w - pad - rail_w - 6
        inner_w = inner_x1 - inner_x0
        col_w = int(inner_w * 0.24)
        gap = (inner_w - 3 * col_w) / 2

        # wells: side, mid, side
        cols = [
            (inner_x0, SIDE_SEGS, self.side, 0.76),
            (inner_x0 + col_w + gap, MID_SEGS, self.mid, 1.0),
            (inner_x0 + 2 * (col_w + gap), SIDE_SEGS, self.side, 0.76),
        ]
        for x, segs, level, hp in cols:
            ch = well_h * hp
            y0 = well_top + (well_h - ch) / 2
            cv.create_rectangle(x, y0, x + col_w, y0 + ch, fill=WELL_BG, outline="")
            self._paint_segs(cv, x + 1, y0 + 1, col_w - 2, ch - 2, segs, level)

        # racing bar
        by0 = well_bottom + 4
        self._paint_bar(cv, inner_x0, by0, inner_w, bar_h, busy=(state == "thinking"), sweeping=(state == "listening"))

        # rails
        left = [("MIC", "r" if muted else "g"), ("LINK", "g" if state not in ("off", "error", "joining") else "y"),
                ("AUTO", "y")]
        state_chip = {"in room": ("READY", "k"), "listening": ("HEARS", "y"), "thinking": ("THINK", "y"),
                      "speaking": ("VOICE", "r"), "joining": ("DIAL", "y")}.get(state, (state.upper()[:5], "k"))
        right = [(bot_display[:6].upper(), "r"), state_chip, ("PWR", "g")]
        self._paint_rail(cv, pad, well_top, rail_w, well_h, left)
        self._paint_rail(cv, w - pad - rail_w, well_top, rail_w, well_h, right)

        # captions
        if captions:
            cy = h - pad - cap_h + 4
            for who, text, final in captions[-2:]:
                is_bot = who != "you"
                color = "#ff8080" if is_bot else "#b09090"
                label = f"{who.upper()}: " if not is_bot else f"{who.upper()}: "
                line = (label + text).replace("\n", " ")
                cv.create_text(pad + 2, cy, text=line, anchor="nw", fill=color if final else hex_lerp(color, PANEL_BG, 0.3),
                               font=("Segoe UI", 9), width=w - 2 * pad - 4)
                cy += 20

    def _paint_segs(self, cv: tk.Canvas, x: float, y: float, w: float, h: float, count: int, level: float) -> None:
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
                top = hex_lerp(TOP_RED, face, 0.55 + 0.25 * u)
                bot = hex_lerp(face, BOT_RED, 0.45)
                third = seg_h / 3
                cv.create_rectangle(x, sy, x + w, sy + third, fill=top, outline="")
                cv.create_rectangle(x, sy + third, x + w, sy + 2 * third, fill=face, outline="")
                cv.create_rectangle(x, sy + 2 * third, x + w, sy + seg_h - 1, fill=bot, outline="")
            else:
                cv.create_rectangle(x, sy, x + w, sy + seg_h / 2, fill=UNLIT_TOP, outline="")
                cv.create_rectangle(x, sy + seg_h / 2, x + w, sy + seg_h - 1, fill=UNLIT_BOT, outline="")
            cv.create_line(x, sy + seg_h - 1, x + w, sy + seg_h - 1, fill="#000000")

    def _paint_bar(self, cv: tk.Canvas, x: float, y: float, w: float, h: float, *, busy: bool, sweeping: bool) -> None:
        seg_w = (w - (BAR_SEGS - 1) * 2) / BAR_SEGS
        idle = {int(BAR_SEGS * 0.35), int(BAR_SEGS * 0.4), int(BAR_SEGS * 0.45)}
        for i in range(BAR_SEGS):
            sx = x + i * (seg_w + 2)
            strength = 0.0
            if busy or sweeping:
                d = abs(i - self.head)
                strength = {0: 1.0, 1: 0.55, 2: 0.25}.get(d, 0.0)
                if sweeping:
                    strength *= 0.6
            elif i in idle:
                strength = 0.35
            color = hex_lerp(PANEL_BG, self.accent, strength) if strength > 0 else hex_lerp(PANEL_BG, self.accent, 0.09)
            cv.create_rectangle(sx, y, sx + seg_w, y + h, fill=color, outline="")

    def _paint_rail(self, cv: tk.Canvas, x: float, y: float, w: float, h: float, items: list[tuple[str, str]]) -> None:
        n = len(items)
        chip_h = 18
        spacing = (h - n * chip_h) / max(1, n - 1) if n > 1 else 0
        for i, (label, tone) in enumerate(items):
            bg, fg, bd = CHIP_TONES.get(tone, CHIP_TONES["k"])
            cy = y + i * (chip_h + spacing)
            cv.create_rectangle(x, cy, x + w, cy + chip_h, fill=bg, outline=bd)
            cv.create_text(x + w / 2, cy + chip_h / 2, text=label, fill=fg, font=("Segoe UI", 6, "bold"))


SKINS = {"kitt": KittSkin}
