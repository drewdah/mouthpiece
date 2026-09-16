"""Baymax entity skin, V1: head and shoulders, white inflatable bust, the two-dot-and-line face.

Speaking: the eye-line thickens with volume and the whole bust breathes with a slow bob.
Listening: the eyes soften into happy arcs. Thinking: a soft pink glow behind the head.
"""
from __future__ import annotations

import math
import time

from .entity import EntitySkin, KEY_COLOR
from .kitt import hex_lerp

WHITE = "#FFFFFF"
SHADE1 = "#EEF0F4"
SHADE2 = "#D8DCE4"
INK = "#101014"


class BaymaxSkin(EntitySkin):
    name = "baymax"
    size = (300, 430)
    accent = "#FF6B8A"

    def __init__(self, accent: str | None = None) -> None:
        super().__init__(accent)
        self.bob = 0.0
        self.tilt = 0.0

    def step_body(self, state: str, dt: float) -> None:
        t = time.monotonic() - self.t0
        target_bob = (2.5 + 5.0 * self.level) * math.sin(t * (1.6 + 1.2 * self.level)) if state == "speaking" \
            else 2.0 * math.sin(t * 0.9)
        self.bob += (target_bob - self.bob) * min(1.0, dt * 8)
        target_tilt = 4.0 * math.sin(t * 1.3) if state == "listening" else 0.0
        self.tilt += (target_tilt - self.tilt) * min(1.0, dt * 4)

    def head_anchor(self, w, top):
        return w / 2 + self.tilt, top + 30 + self.bob

    def paint_body(self, cv, w, top, bottom, *, state, muted):
        cx = w / 2
        by = self.bob
        # thinking glow
        if state == "thinking":
            for i, (r, t) in enumerate(((150, 0.08), (125, 0.14), (100, 0.22))):
                col = hex_lerp(KEY_COLOR, self.accent, t)
                cv.create_oval(cx - r, top + 90 - r * 0.9 + by, cx + r, top + 90 + r * 0.9 + by, fill=col, outline="",
                               stipple="gray50")
        # shoulders / chest: two big rounded lobes and a chest slab
        sy = bottom - 20 + by * 0.4
        for dx, sh in ((-1, SHADE2), (1, SHADE1)):
            cv.create_oval(cx + dx * 82 - 70, sy - 112, cx + dx * 82 + 70, sy + 40, fill=sh, outline="")
        cv.create_oval(cx - 92, sy - 88, cx + 92, sy + 70, fill=SHADE1, outline="")
        cv.create_oval(cx - 84, sy - 96, cx + 84, sy + 40, fill=WHITE, outline="")
        # chest port
        px, py = cx - 34, sy - 30
        cv.create_oval(px - 12, py - 12, px + 12, py + 12, fill=SHADE2, outline=hex_lerp(SHADE2, INK, 0.25))
        cv.create_oval(px - 7, py - 7, px + 7, py + 7, fill=SHADE1, outline="")
        # neck fold
        cv.create_oval(cx - 46, top + 88 + by, cx + 46, top + 124 + by, fill=SHADE2, outline="")
        # head: wide oval with a lit top
        hx = cx + self.tilt
        hy = top + 66 + by
        cv.create_oval(hx - 78, hy - 44, hx + 78, hy + 46, fill=SHADE2, outline="")
        cv.create_oval(hx - 76, hy - 46, hx + 76, hy + 42, fill=WHITE, outline="")
        # face: two dots joined by a line
        eye_dx, eye_y = 34, hy + 2
        line_w = 3.0 + 3.5 * self.level
        squint = 1.0 - min(1.0, self.blink * 1.0)
        if state == "listening" and squint > 0.5:
            # happy arcs
            for dx in (-eye_dx, eye_dx):
                cv.create_arc(hx + dx - 9, eye_y - 8, hx + dx + 9, eye_y + 8, start=20, extent=140, style="arc",
                              outline=INK, width=4)
        else:
            rh = 8 * squint
            for dx in (-eye_dx, eye_dx):
                cv.create_oval(hx + dx - 8, eye_y - rh, hx + dx + 8, eye_y + rh, fill=INK, outline="")
        cv.create_line(hx - eye_dx + 6, eye_y, hx + eye_dx - 6, eye_y, fill=INK, width=line_w)
