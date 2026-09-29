"""Wheatley on the desk panel: the Portal 2 personality core, close up, next to
a test-chamber sign that carries the clock, the PC's load and the voice state.

His expression lives in the optic: two shell-coloured shutters slide in from top
and bottom, independently and at an angle (the asymmetric squint), and the pupil
darts and dilates. Only the pupil and the lids move, never the whole iris: an
iris shift would repaint ~35 KB, three frames of the link budget.

States: off = shutters closed. in room = relaxed half-lids, slow drifts.
listening = wide open, pupil up. thinking = tilted squint, quick darts.
speaking = lids ride the voice, pupil pulses. error = the optic goes red.
Portrait (320x480): sign card under him. Landscape (480x320): tall sign beside him.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from PIL import Image

from .panel import FrameDiff, Pen, PanelFace, clock_text, hexrgb, lerp

BG = (27, 31, 39)
PANEL = (33, 38, 48)
SHELL = (230, 232, 236)
SHELL_LO = (180, 185, 195)
SHELL_HI = (246, 247, 249)
SEAM = (124, 130, 141)
SOCKET = (22, 24, 29)
SOCKET_RIM = (58, 62, 70)
HANDLE = (62, 68, 80)
HANDLE_HI = (138, 144, 156)
SIGN = (236, 236, 232)
SIGN_INK = (18, 18, 18)
SIGN_DIM = (196, 196, 190)
RED = ((70, 6, 6), (240, 40, 36), (255, 196, 170))
LIGHT, UI_SB = "segoeuil.ttf", "seguisb.ttf"
ICONS = ("listen", "think", "speak", "mute", "error")


@dataclass
class Layout:
    w: int
    h: int
    eye: tuple[float, float]       # sphere centre
    R: float                        # sphere radius
    card: tuple[int, int, int, int]
    tall: bool                      # sign stacked vertically (landscape)


PORTRAIT = Layout(320, 480, (160, 170), 138, (10, 326, 310, 470), False)
LANDSCAPE = Layout(480, 320, (162, 160), 136, (324, 12, 470, 308), True)


class WheatleyFace(PanelFace):
    name = "wheatley"

    def __init__(self, cfg: dict, source, orientation: str = "portrait") -> None:
        super().__init__(cfg, source)
        self.L = LANDSCAPE if orientation == "landscape" else PORTRAIT
        self.blue = (43, 108, 255)
        self._rng = random.Random(11)
        self._t = None
        self.look = [0.0, 0.0]
        self._dart = [0.0, 0.0]
        self._next_dart = 0.0
        self.lid_top, self.lid_bot, self.lid_tilt = 1.0, 1.0, 0.0
        self._lid_target = (1.0, 1.0, 0.0)
        self._next_lid = 0.0
        self.pupil = 0.5
        self._cache: dict[str, tuple] = {}

    # ---- geometry ----------------------------------------------------------------
    @property
    def er(self) -> float:            # iris radius
        return self.L.R * 0.56

    def _boxes(self):
        cx, cy = self.L.eye
        r = int(self.L.R * 0.72) + 2
        x0, y0, x1, y1 = self.L.card
        return {"eye": (int(cx - r), int(cy - r), int(cx + r), int(cy + r)),
                "clock": (x0 + 6, y0 + 4, x1 - 6, y0 + (80 if self.L.tall else 74)),
                "bars": self._bars_box(),
                "icons": self._icons_box()}

    def _bars_box(self):
        x0, y0, x1, y1 = self.L.card
        return (x0 + 8, y0 + 88, x1 - 8, y0 + 124) if self.L.tall else (x0 + 8, y0 + 80, x1 - 8, y0 + 104)

    def _icons_box(self):
        x0, y0, x1, y1 = self.L.card
        return (x0 + 6, y0 + 128, x1 - 6, y1 - 34) if self.L.tall else (x0 + 6, y0 + 106, x1 - 6, y1 - 4)

    def _icon_cells(self):
        x0, y0, x1, y1 = self._icons_box()
        if self.L.tall:
            s, gap = 38, 8
            rows = ((0, 1, 2), (3, 4))
            cells = {}
            top = (y0 + y1 - 2 * s - gap) / 2 - 8
            for r, row in enumerate(rows):
                total = len(row) * s + (len(row) - 1) * gap
                sx = (x0 + x1 - total) / 2
                for i, k in enumerate(row):
                    cells[ICONS[k]] = (sx + i * (s + gap), top + r * (s + gap), s)
            return cells
        s = 30
        gap = (x1 - x0 - 5 * s) / 6
        return {k: (x0 + gap + i * (s + gap), y0 + 2, s) for i, k in enumerate(ICONS)}

    # ---- static scene ----------------------------------------------------------------
    def _scene(self) -> Image.Image:
        L = self.L
        pen = Pen.canvas((0, 0, L.w, L.h), BG)
        for gx in range(0, L.w, 40):                      # test-chamber wall panels
            for gy in range(0, L.h, 40):
                pen.rect(gx + 1, gy + 1, gx + 39, gy + 39, fill=PANEL)
        cx, cy = L.eye
        R = L.R
        # handles: arcs hinged at the sphere's sides, behind the shell
        for side, swing in ((-1, -18), (1, 18)):
            pivot = 180 if side < 0 else 0
            base = pivot + swing
            for w_, col in ((14, HANDLE), (4, HANDLE_HI)):
                pen.arc(cx, cy, R + 14, R + 14, -(base + 50), -(base - 50), col, w_)
            for ang in (base - 50, base + 50):
                a = math.radians(ang)
                pen.circle(cx + (R + 14) * math.cos(a), cy - (R + 14) * math.sin(a), 8, fill=HANDLE, outline=HANDLE_HI)
            pen.circle(cx + side * R, cy, 7, fill=SEAM, outline=(42, 46, 54))
        # shell, lit from the upper left
        pen.circle(cx, cy, R, fill=SHELL_LO, outline=(138, 143, 153), width=2)
        pen.ellipse(cx - 1, cy - 4, R - 7, R - 9, fill=SHELL)
        pen.ellipse(cx - 18, cy - 22, R * 0.62, R * 0.58, fill=lerp(SHELL, SHELL_HI, 0.7))
        # seams: meridian and a front equator arc; the black port under the optic
        pen.line([(cx, cy - R + 3), (cx, cy + R - 3)], SEAM, 2)
        pen.arc(cx, cy, R - 3, R * 0.35, 0, 180, SEAM, 1.2)
        pen.rrect(cx - 7, cy + R * 0.76, cx + 7, cy + R * 0.94, 2, fill=(21, 23, 27), outline=SOCKET_RIM)
        # optic socket
        so = self.L.R * 0.72
        pen.circle(cx, cy, so, fill=SOCKET_RIM, outline=(90, 95, 105), width=2)
        pen.circle(cx, cy, so - 6, fill=SOCKET)
        self._sign(pen)
        return pen.img

    def _sign(self, pen: Pen) -> None:
        x0, y0, x1, y1 = self.L.card
        pen.rrect(x0, y0, x1, y1, 4, fill=SIGN)
        if self.L.tall:
            pen.line([(x0 + 10, y0 + 82), (x1 - 10, y0 + 82)], SIGN_INK, 1.5)
            pen.line([(x0 + 10, y1 - 30), (x1 - 10, y1 - 30)], SIGN_INK, 1.5)
            pen.text((x0 + x1) / 2, y1 - 15, "W H E A T L E Y", SIGN_INK, UI_SB, 11, anchor="mm")
        else:
            pen.line([(x0 + 10, y0 + 76), (x1 - 10, y0 + 76)], SIGN_INK, 1.5)

    def build(self) -> FrameDiff:
        style = self.style() or {}
        self.blue = hexrgb(style.get("accent", "#2B6CFF"))
        self.scene3 = self._scene()
        bg = self.scene3.resize((self.L.w, self.L.h), Image.LANCZOS)
        boxes = self._boxes()
        order = ["eye", "icons", "clock", "bars"]

        def priority(x, y):
            for i, k in enumerate(order):
                b = boxes[k]
                if b[0] <= x < b[2] and b[1] <= y < b[3]:
                    return i
            return len(order)

        self._frame = bg.copy()
        self._cache.clear()
        return FrameDiff(bg, priority)

    # ---- animation ------------------------------------------------------------------
    def _animate(self, state: str, level: float, now: float) -> None:
        dt = 1 / 12 if self._t is None else max(0.0, min(0.5, now - self._t))
        self._t = now
        rng = self._rng
        k = min(1.0, dt * 6)
        if now > self._next_dart:
            fast = state in ("thinking", "speaking")
            self._next_dart = now + (0.35 if fast else 1.8) + rng.random() * 1.2
            amp = 9.0 if state == "thinking" else 6.0 if state == "speaking" else 4.0
            self._dart = [rng.uniform(-amp, amp), rng.uniform(-amp * 0.6, amp * 0.6)]
        if state in ("off", "error"):
            self._dart = [0.0, 0.0]
        self.look[0] += (self._dart[0] - self.look[0]) * k
        self.look[1] += (self._dart[1] - self.look[1]) * k

        if state == "off":
            self._lid_target = (1.0, 1.0, 0.0)
        elif now > self._next_lid:
            if state == "listening":
                pose, hold = (rng.uniform(0.0, 0.08), rng.uniform(0.0, 0.06), rng.uniform(-4, 4)), 1.2
            elif state == "thinking":
                pose, hold = (rng.uniform(0.35, 0.6), rng.uniform(0.15, 0.35),
                              rng.choice([-1, 1]) * rng.uniform(8, 18)), 0.9
            elif state == "speaking":
                pose, hold = (rng.uniform(0.05, 0.35), rng.uniform(0.05, 0.25), rng.uniform(-12, 12)), 0.5
            elif state == "error":
                pose, hold = (0.45, 0.3, -10.0), 3.0
            else:
                pose, hold = (rng.uniform(0.15, 0.35), rng.uniform(0.1, 0.25), rng.uniform(-6, 6)), 2.4
            self._lid_target = pose
            self._next_lid = now + hold + rng.random() * 0.6
        lt, lb, tilt = self._lid_target
        if state == "speaking":
            lt, lb = max(0.0, lt - 0.3 * level), max(0.0, lb - 0.2 * level)
        kl = min(1.0, dt * 7)
        self.lid_top += (lt - self.lid_top) * kl
        self.lid_bot += (lb - self.lid_bot) * kl
        self.lid_tilt += (tilt - self.lid_tilt) * min(1.0, dt * 5)
        tp = 0.45 + 0.5 * level if state == "speaking" else 0.62 if state == "listening" else 0.5
        self.pupil += (tp - self.pupil) * min(1.0, dt * 8)

    # ---- per frame ----------------------------------------------------------------------
    def _region(self, key: str, sig, paint) -> None:
        if self._cache.get(key) == sig:
            return
        self._cache[key] = sig
        box = self._boxes()[key]
        pen = Pen.over(self.scene3, box)
        paint(pen)
        self._frame.paste(pen.done(), box[:2])

    def update(self, state: str, muted: bool, level: float, now: float) -> None:
        self._animate(state, level, now)
        red = state == "error"
        dim = state == "off"
        q = lambda v, n=2: round(v * n) / n                       # noqa: E731 - quantise: no repaint for sub-pixel moves
        sig = (red, dim, q(self.look[0]), q(self.look[1]), q(self.pupil, 40), q(self.lid_top, 60),
               q(self.lid_bot, 60), q(self.lid_tilt, 1))
        self._region("eye", sig, lambda pen: self._paint_eye(pen, red, dim))
        hm, ap = clock_text()
        self._region("clock", (hm, ap), lambda pen: self._paint_clock(pen, hm, ap))
        st = self.stats
        cpu, gpu = int(st.cpu / 5), int(st.gpu / 5)
        self._region("bars", (cpu, gpu), lambda pen: self._paint_bars(pen, cpu, gpu))
        lit = {"listening": "listen", "thinking": "think", "speaking": "speak", "error": "error"}.get(state)
        self._region("icons", (lit, muted), lambda pen: self._paint_icons(pen, lit, muted))
        self.face.draw(self._frame)

    # ---- optic -------------------------------------------------------------------------------
    def _paint_eye(self, pen: Pen, red: bool, dim: bool) -> None:
        cx, cy = self.L.eye
        er = self.er
        deep, mid, core = RED if red else ((8, 32, 79), self.blue, (191, 224, 255))
        if dim:
            deep, mid, core = lerp(deep, (0, 0, 0), 0.5), lerp(mid, (0, 0, 0), 0.6), lerp(core, (0, 0, 0), 0.6)
        pen.circle(cx, cy, er + 5, fill=lerp(SOCKET, mid, 0.18))          # faint glow in the socket
        rings = 12
        for i in range(rings):
            f = i / (rings - 1)
            col = lerp(deep, mid, min(1.0, f * 1.1))
            if f > 0.62:
                col = lerp(col, core, (f - 0.62) / 0.38 * 0.85)
            pen.circle(cx, cy, er * (1.0 - 0.78 * f), fill=col)
        px, py = cx + self.look[0], cy + self.look[1]
        pr = er * 0.24 * (0.6 + 0.8 * self.pupil)
        pen.circle(px, py, pr, fill=(4, 16, 42) if not red else (30, 0, 0))
        pen.ellipse(cx - er * 0.26, cy - er * 0.42, er * 0.14, er * 0.10, fill=(232, 242, 255))
        # shutters: shell-coloured chords from top and bottom, tilted (PIL angles run clockwise)
        lr = er + 8
        for lid, centre in ((self.lid_top, 270), (self.lid_bot, 90)):
            if lid < 0.02:
                continue
            # lid = how far the shutter's straight edge reaches toward the centre (1 = halfway)
            ext = 2 * math.degrees(math.acos(1.0 - min(1.0, lid))) + (2 if lid > 0.98 else 0)
            a0 = centre + self.lid_tilt - ext / 2
            pen.chord(cx, cy, lr, a0, a0 + ext, fill=SHELL, outline=SHELL_LO, width=2)

    # ---- sign ---------------------------------------------------------------------------------
    def _paint_clock(self, pen: Pen, hm: str, ap: str) -> None:
        x0, y0, x1, y1 = self.L.card
        if self.L.tall:
            pen.text(x0 + 10, y0 + 2, hm, SIGN_INK, LIGHT, 50)
            pen.text(x1 - 10, y0 + 66, ap, SIGN_INK, UI_SB, 12, anchor="rm")
        else:
            pen.text(x0 + 12, y0 - 2, hm, SIGN_INK, LIGHT, 62)
            pen.text(x1 - 12, y0 + 22, "WHEATLEY", SIGN_INK, UI_SB, 11, anchor="rm")
            pen.text(x1 - 12, y0 + 46, ap, SIGN_INK, UI_SB, 16, anchor="rm")

    def _paint_bars(self, pen: Pen, cpu: int, gpu: int) -> None:
        x0, y0, x1, y1 = self._bars_box()
        rows = ((("CPU", cpu), y0 + 6), (("GPU", gpu), y0 + (24 if self.L.tall else 17)))
        for (label, n), y in rows:
            pen.text(x0 + 2, y, label, SIGN_INK, UI_SB, 8, anchor="lm")
            bx0, bx1 = x0 + 24, x1 - 2
            step = (bx1 - bx0) / 20
            for i in range(20):
                pen.rect(bx0 + i * step, y - 2.5, bx0 + i * step + step * 0.62, y + 2.5,
                         fill=SIGN_INK if i < n else SIGN_DIM)

    def _paint_icons(self, pen: Pen, lit, muted: bool) -> None:
        for name, (x, y, s) in self._icon_cells().items():
            on = name == lit or (name == "mute" and muted)
            pen.rrect(x, y, x + s, y + s, 3, fill=SIGN_INK if on else SIGN_DIM)
            getattr(self, f"_icon_{name}")(pen, x + s / 2, y + s / 2, s, SIGN if on else (236, 236, 232))

    # pictograms, drawn around (cx, cy) in a cell of size s
    def _icon_listen(self, pen, cx, cy, s, c):
        pen.circle(cx + s * 0.18, cy, s * 0.09, fill=c)
        for r in (0.2, 0.34):
            pen.arc(cx + s * 0.18, cy, s * r, s * r, 135, 225, c, s * 0.06)

    def _icon_think(self, pen, cx, cy, s, c):
        teeth, ro, ri = 8, s * 0.34, s * 0.25
        pts = []
        for i in range(teeth * 4):
            a = 2 * math.pi * i / (teeth * 4)
            r = ro if (i % 4) in (0, 1) else ri
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        pen.polygon(pts, fill=c)
        pen.circle(cx, cy, s * 0.1, fill=SIGN_INK if c == SIGN else SIGN_DIM)

    def _icon_speak(self, pen, cx, cy, s, c):
        pen.rrect(cx - s * 0.32, cy - s * 0.26, cx + s * 0.32, cy + s * 0.14, s * 0.1, fill=c)
        pen.polygon([(cx - s * 0.14, cy + s * 0.1), (cx - s * 0.2, cy + s * 0.32), (cx + s * 0.04, cy + s * 0.1)], fill=c)

    def _icon_mute(self, pen, cx, cy, s, c):
        pen.rrect(cx - s * 0.1, cy - s * 0.3, cx + s * 0.1, cy + s * 0.06, s * 0.1, fill=c)
        pen.arc(cx, cy - s * 0.06, s * 0.19, s * 0.19, 0, 180, c, s * 0.05)
        pen.line([(cx, cy + s * 0.13), (cx, cy + s * 0.28)], c, s * 0.05)
        pen.line([(cx - s * 0.3, cy - s * 0.3), (cx + s * 0.3, cy + s * 0.3)], c, s * 0.07)

    def _icon_error(self, pen, cx, cy, s, c):
        pen.polygon([(cx, cy - s * 0.32), (cx + s * 0.34, cy + s * 0.28), (cx - s * 0.34, cy + s * 0.28)], fill=c)
        bg = SIGN_INK if c == SIGN else SIGN_DIM
        pen.line([(cx, cy - s * 0.12), (cx, cy + s * 0.1)], bg, s * 0.07)
        pen.circle(cx, cy + s * 0.19, s * 0.04, fill=bg)
