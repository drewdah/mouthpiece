"""Wheatley entity skin, V1: spherical personality core with two handle arcs and a blue optic.

Speaking: the aperture (pupil) opens with volume and the iris jitters.
Thinking: eyelid shutters narrow. Listening: the optic tracks the cursor a little.
"""
from __future__ import annotations

import math
import random
import time

from .entity import EntitySkin, KEY_COLOR
from .kitt import hex_lerp

SHELL = "#E9EBEF"
SHELL_DARK = "#B9BEC8"
SEAM = "#6F7580"
HANDLE = "#3D4350"
BLUE = "#2B6CFF"
BLUE_DEEP = "#0B2E8A"
BLUE_LIGHT = "#9CC0FF"


class WheatleySkin(EntitySkin):
    name = "wheatley"
    size = (300, 420)
    accent = "#2B6CFF"

    def __init__(self, accent: str | None = None) -> None:
        super().__init__(accent)
        self.look = [0.0, 0.0]      # optic offset
        self.jit = [0.0, 0.0]
        self.shutter = 0.0          # 0 open .. 1 closed
        self.roll = 0.0
        self._rng = random.Random(7)

    def step_body(self, state: str, dt: float) -> None:
        k = min(1.0, dt * 6)
        # look toward the cursor (window coords), clamped
        px, py = self.pointer
        cx, cy = self.size[0] / 2, self.BUBBLE_H + 120
        dx, dy = px - cx, py - cy
        d = math.hypot(dx, dy) or 1.0
        amt = min(1.0, d / 260.0) * (14.0 if self.hovering else 8.0)
        tx, ty = dx / d * amt, dy / d * amt
        if state == "listening":
            tx, ty = tx * 1.3, ty * 1.3
        self.look[0] += (tx - self.look[0]) * k
        self.look[1] += (ty - self.look[1]) * k
        # jitter while speaking
        if state == "speaking":
            self.jit[0] = self._rng.uniform(-1, 1) * 2.5 * self.level
            self.jit[1] = self._rng.uniform(-1, 1) * 2.5 * self.level
        else:
            self.jit[0] *= 0.7
            self.jit[1] *= 0.7
        target_shutter = 0.55 if state == "thinking" else (0.15 if state == "listening" else 0.0)
        self.shutter += (target_shutter - self.shutter) * min(1.0, dt * 5)
        t = time.monotonic() - self.t0
        target_roll = math.sin(t * 0.8) * (3.0 if state != "speaking" else 6.0)
        self.roll += (target_roll - self.roll) * min(1.0, dt * 3)

    def head_anchor(self, w, top):
        return w / 2, top + 14

    def paint_body(self, cv, w, top, bottom, *, state, muted):
        cx, cy = w / 2, top + 120
        R = 96
        # handles (two arcs, top-left and bottom-right like the reference)
        for start in (100, 280):
            box = (cx - R - 14, cy - R - 14, cx + R + 14, cy + R + 14)
            cv.create_arc(*box, start=start + self.roll, extent=80, style="arc", outline=HANDLE, width=16)
            cv.create_arc(*box, start=start + self.roll + 4, extent=72, style="arc",
                          outline=hex_lerp(HANDLE, "#ffffff", 0.3), width=5)
            for ang in (start + self.roll, start + self.roll + 80):   # end caps
                a = math.radians(ang)
                ex, ey = cx + (R + 14) * math.cos(a), cy - (R + 14) * math.sin(a)
                cv.create_oval(ex - 9, ey - 9, ex + 9, ey + 9, fill=HANDLE, outline=hex_lerp(HANDLE, "#ffffff", 0.3))
        # shell
        cv.create_oval(cx - R, cy - R, cx + R, cy + R, fill=SHELL_DARK, outline=SEAM, width=2)
        cv.create_oval(cx - R + 6, cy - R + 4, cx + R - 10, cy + R - 14, fill=SHELL, outline="")
        # seams
        cv.create_arc(cx - R + 3, cy - R + 3, cx + R - 3, cy + R - 3, start=200 + self.roll, extent=120, style="arc",
                      outline=SEAM, width=1)
        # optic housing
        ox, oy = cx + self.look[0] + self.jit[0], cy + self.look[1] + self.jit[1]
        er = 52
        cv.create_oval(ox - er - 8, oy - er - 8, ox + er + 8, oy + er + 8, fill="#2A2D34", outline="#15171B", width=2)
        # blue lens: radial gradient rings
        aperture = 0.55 + 0.45 * self.level
        rings = 9
        for i in range(rings):
            f = i / (rings - 1)
            r = er * (1.0 - 0.72 * f)
            col = hex_lerp(BLUE_DEEP, BLUE, f * 0.9)
            if f > 0.7:
                col = hex_lerp(col, BLUE_LIGHT, (f - 0.7) / 0.3 * 0.6)
            cv.create_oval(ox - r, oy - r, ox + r, oy + r, fill=col, outline="")
        # pupil + glint
        pr = er * 0.28 * aperture
        cv.create_oval(ox - pr, oy - pr, ox + pr, oy + pr, fill="#06122E", outline="")
        cv.create_oval(ox - er * 0.42, oy - er * 0.52, ox - er * 0.12, oy - er * 0.30, fill="#DCE9FF", outline="")
        # eyelid shutters (shell-coloured pie slices from top and bottom)
        s = max(self.shutter, self.blink)
        if s > 0.02:
            ext = 180 * s
            box = (ox - er - 8, oy - er - 8, ox + er + 8, oy + er + 8)
            cv.create_arc(*box, start=90 - ext / 2, extent=ext, style="chord", fill=SHELL_DARK, outline=SEAM)
            cv.create_arc(*box, start=270 - ext / 2, extent=ext, style="chord", fill=SHELL_DARK, outline=SEAM)
        # thinking: faint blue halo
        if state == "thinking":
            cv.create_oval(cx - R - 10, cy - R - 10, cx + R + 10, cy + R + 10, outline=hex_lerp(KEY_COLOR, BLUE, 0.5),
                           width=3, stipple="gray50")
