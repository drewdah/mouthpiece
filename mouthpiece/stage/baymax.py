"""Baymax entity skin, V2: head and shoulders of the inflatable, modelled on the Big Hero 6 film.

Face: two solid black eyes set low on an egg-shaped head, joined by a thin line that sags a
little in the middle. The line never moves; his expression lives in the eyes. Blinks are a
smooth shutter: the eye is clipped from top and bottom to a slit and back, eased.

States: listening = happy arcs and a gentle side-to-side sway. speaking = nearly still, just
breathing, with the occasional shutter blink. thinking = the projector inside him lights a
soft screen on his belly (a thought bubble with pulsing dots, glowing through the frosted
vinyl) and the head tilts slowly, curious.
"""
from __future__ import annotations

import math
import time

from .entity import EntitySkin, rounded_rect
from .kitt import hex_lerp

WHITE = "#FFFFFF"
SHADE1 = "#EEF0F4"
SHADE2 = "#D8DCE4"
INK = "#101014"
SCREEN = "#D3E6FA"       # projector light seen through the vinyl
CLOUD = "#F5FAFF"
CLOUD_EDGE = "#8DB6E4"

# shutter blink timing (seconds): close, hold shut, open
SHUT_CLOSE, SHUT_HOLD, SHUT_OPEN = 0.08, 0.05, 0.13


def _smooth(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def _rot(px, py, cx, cy, deg):
    a = math.radians(deg)
    dx, dy = px - cx, py - cy
    return cx + dx * math.cos(a) - dy * math.sin(a), cy + dx * math.sin(a) + dy * math.cos(a)


class BaymaxSkin(EntitySkin):
    name = "baymax"
    size = (300, 474)
    accent = "#FF6B8A"
    thinking_dots = False    # the belly screen replaces the thought dots above the head

    def __init__(self, accent: str | None = None) -> None:
        super().__init__(accent)
        self.bob = 0.0
        self.tilt = 0.0          # listening sway (px)
        self.roll = 0.0          # head tilt (degrees), thinking
        self.screen = 0.0        # belly projector brightness 0..1
        self.shutter = 0.0       # 0 = eyes open, 1 = shut
        self._shut_t0 = None
        self._prev_blink = 0.0

    # ---- animation ---------------------------------------------------------
    def step_body(self, state: str, dt: float) -> None:
        now = time.monotonic()
        t = now - self.t0
        # breathing only: he stays still while he talks
        self.bob += (1.5 * math.sin(t * 0.9) - self.bob) * min(1.0, dt * 8)
        target_tilt = 4.0 * math.sin(t * 1.3) if state == "listening" else 0.0
        self.tilt += (target_tilt - self.tilt) * min(1.0, dt * 4)
        target_roll = (7.0 + 1.5 * math.sin(t * 0.8)) if state == "thinking" else 0.0
        self.roll += (target_roll - self.roll) * min(1.0, dt * 2.5)
        want = 1.0 if state == "thinking" else 0.0
        self.screen += (want - self.screen) * min(1.0, dt * (4.0 if want else 6.0))
        # the base class decides WHEN to blink; this turns each blink into an eased shutter
        if self.blink > 0.99 and self._prev_blink <= 0.99 and self._shut_t0 is None:
            self._shut_t0 = now
        self._prev_blink = self.blink
        if self._shut_t0 is not None:
            e = now - self._shut_t0
            if e < SHUT_CLOSE:
                self.shutter = _smooth(e / SHUT_CLOSE)
            elif e < SHUT_CLOSE + SHUT_HOLD:
                self.shutter = 1.0
            elif e < SHUT_CLOSE + SHUT_HOLD + SHUT_OPEN:
                self.shutter = 1.0 - _smooth((e - SHUT_CLOSE - SHUT_HOLD) / SHUT_OPEN)
            else:
                self.shutter, self._shut_t0 = 0.0, None

    def head_anchor(self, w, top):
        return w / 2 + self.tilt, top + 30 + self.bob

    # ---- painting ----------------------------------------------------------
    def paint_body(self, cv, w, top, bottom, *, state, muted):
        cx = w / 2
        by = self.bob
        sy = bottom - 20 + by * 0.4
        # shoulders: two big rounded lobes, kept inside the window so the silhouette closes
        for dx, sh in ((-1, SHADE2), (1, SHADE1)):
            cv.create_oval(cx + dx * 68 - 64, sy - 108, cx + dx * 68 + 64, sy + 40, fill=sh, outline="")
        # torso
        cv.create_oval(cx - 92, sy - 88, cx + 92, sy + 70, fill=SHADE1, outline="")
        cv.create_oval(cx - 84, sy - 96, cx + 84, sy + 40, fill=WHITE, outline="")
        if self.screen > 0.02:
            self.paint_screen(cv, cx, sy)
        # chest access port (his left, the viewer's right), circle with a small chevron
        px, py = cx + 38, sy - 74
        cv.create_oval(px - 11, py - 11, px + 11, py + 11, fill=SHADE1, outline=hex_lerp(SHADE2, INK, 0.2))
        cv.create_line(px - 5, py + 1, px, py - 3, px + 5, py + 1, fill=hex_lerp(SHADE2, INK, 0.35), width=1.5)
        # soft shadow where the head sits on the body
        hx = cx + self.tilt
        hy = top + 64 + by
        cv.create_oval(hx - 42, hy + 30, hx + 42, hy + 52, fill=hex_lerp(WHITE, SHADE1, 0.6), outline="")
        self.paint_head(cv, hx, hy, state)

    def paint_head(self, cv, hx, hy, state):
        pivot = (hx, hy + 44)
        roll = self.roll

        def egg(a, b, ox=0.0, oy=0.0):
            pts = []
            for i in range(36):
                th = 2 * math.pi * i / 36
                s = math.sin(th)
                x = hx + ox + a * math.cos(th) * (1 + 0.07 * s)   # a touch wider low down
                y = hy + oy + b * s
                pts.extend(_rot(x, y, *pivot, roll))
            return pts

        cv.create_polygon(egg(72, 47, 0, 2), fill=SHADE2, outline="", smooth=True)
        cv.create_polygon(egg(70, 47), fill=WHITE, outline="", smooth=True)
        # face: eyes low on the head, a thin sagging line between them
        eye_dx, eye_r = 30, 7.5
        ey = hy + 9
        (lx, ly), (rx, ry) = _rot(hx - eye_dx, ey, *pivot, roll), _rot(hx + eye_dx, ey, *pivot, roll)
        mx, my = _rot(hx, ey + 2.5, *pivot, roll)
        cv.create_line(lx, ly, mx, my, rx, ry, fill=INK, width=2, smooth=True)
        if state == "listening" and self.shutter < 0.5:
            for ex, eyy in ((lx, ly), (rx, ry)):     # happy arcs
                cv.create_arc(ex - 9, eyy - 8, ex + 9, eyy + 8, start=20, extent=140, style="arc",
                              outline=INK, width=4)
            return
        for ex, eyy in ((lx, ly), (rx, ry)):
            self.paint_eye(cv, ex, eyy, eye_r)

    def paint_eye(self, cv, ex, ey, r):
        """Solid eye; a blink clips it from top and bottom to a slit, like a shutter."""
        if self.shutter < 0.02:
            cv.create_oval(ex - r, ey - r, ex + r, ey + r, fill=INK, outline="")
            return
        h = r * (1.0 - self.shutter)
        if h < 1.0:
            cv.create_line(ex - r, ey, ex + r, ey, fill=INK, width=2)
            return
        pts = []
        for i in range(28):
            th = 2 * math.pi * i / 28
            pts.extend((ex + r * math.cos(th), ey + max(-h, min(h, r * math.sin(th)))))
        cv.create_polygon(pts, fill=INK, outline="")

    def paint_screen(self, cv, cx, sy):
        """Projector light on the belly: feathered screen, thought bubble, pulsing dots."""
        a = _smooth(self.screen)
        t = time.monotonic() - self.t0
        x0, x1, y0, y1 = cx - 54, cx + 54, sy - 56, sy - 4
        # feathered edge: rings fading from the screen colour out to the white vinyl
        rings = 6
        for i in range(rings, -1, -1):
            f = (1.0 - i / (rings + 1)) ** 1.6
            e = i * 2.5
            rounded_rect(cv, x0 - e, y0 - e, x1 + e, y1 + e, 12 + e, fill=hex_lerp(WHITE, SCREEN, a * f), outline="")

        def col(c):
            return hex_lerp(hex_lerp(WHITE, SCREEN, a), c, a)

        # thought cloud
        ccx, ccy = cx + 8, y0 + 22
        edge, fill = col(CLOUD_EDGE), col(CLOUD)
        puffs = ((-22, 3, 10), (-9, -6, 12), (8, -7, 12), (22, 1, 10), (8, 8, 11), (-10, 8, 10))
        for dx, dy, r in puffs:          # outline pass, then fill pass hides the inner edges
            cv.create_oval(ccx + dx - r - 1.5, ccy + dy - r - 1.5, ccx + dx + r + 1.5, ccy + dy + r + 1.5,
                           fill=edge, outline="")
        for dx, dy, r in puffs:
            cv.create_oval(ccx + dx - r, ccy + dy - r, ccx + dx + r, ccy + dy + r, fill=fill, outline="")
        # trailing bubbles down toward the corner
        for bx, byy, r in ((cx - 30, y1 - 12, 3.0), (cx - 22, y1 - 20, 4.5)):
            cv.create_oval(bx - r, byy - r, bx + r, byy + r, fill=fill, outline=edge, width=1.5)
        # three dots pulsing in turn
        for i in range(3):
            p = 0.5 + 0.5 * math.sin(t * 4.0 - i * 0.9)
            r = 2.4 + 1.4 * p
            dxp = ccx - 12 + i * 12
            cv.create_oval(dxp - r, ccy + 1 - r, dxp + r, ccy + 1 + r,
                           fill=col(hex_lerp(CLOUD_EDGE, self.accent, p)), outline="")
