"""Baymax on the desk panel: head and shoulders of the inflatable, with the
projector screen on his belly (as in Big Hero 6, where he shows scans there).

The expression lives in the eyes (never the line between them): shutter blinks,
happy arcs while listening, shut while off, droopy "low battery" lids on error.
The belly screen carries the state: a scan of the PC while idle, a heart-monitor
trace riding his voice while speaking, a thought cloud while thinking, a
battery warning on error, a beating heart while joining. Portrait (320x480) and
landscape (480x320) share one drawing, reproportioned.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from PIL import Image, ImageFilter

from .panel import FrameDiff, Pen, PanelFace, clock_text, hexrgb, lerp

WHITE = (244, 245, 248)
SHADE1 = (226, 229, 236)
SHADE2 = (200, 205, 216)
INK = (16, 16, 20)
SCREEN = (211, 230, 250)      # projector light seen through the vinyl
SCREEN_INK = (58, 84, 118)
GRID = (190, 214, 240)
CLOUD = (245, 250, 255)
CLOUD_EDGE = (141, 182, 228)
UI = "segoeui.ttf"
UI_SB = "seguisb.ttf"
SHUT_CLOSE, SHUT_HOLD, SHUT_OPEN = 0.08, 0.05, 0.13


def _smooth(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


@dataclass
class Layout:
    w: int
    h: int
    head: tuple[float, float, float, float]      # cx, cy, a, b (egg half-width / half-height)
    eye_dx: float
    eye_r: float
    torso: tuple[float, float, float, float]      # cx, cy, rx, ry of a superellipse (square shoulders)
    arm: tuple[float, float, float, float, float]  # left arm: cx, cy, rx, ry, tilt (deg); right is mirrored
    screen: tuple[int, int, int, int]
    port: tuple[float, float]                      # chest access port
    belly: tuple[float, float, float, float] | None = None   # pear shape: belly wider than the shoulders


# The head sits straight on the body (no neck): the dome's top hides behind it
# and the chin rests just above the shoulder line.
PORTRAIT = Layout(320, 480, (160, 138, 100, 64), 43, 11.5, (160, 450, 122, 262),
                  (34, 360, 40, 132, 11), (66, 276, 254, 402), (220, 238), (160, 510, 138, 250))
LANDSCAPE = Layout(480, 320, (240, 94, 92, 60), 40, 11, (240, 440, 184, 298),
                   (66, 300, 52, 124, 13), (148, 196, 332, 300), (320, 186))


class BaymaxFace(PanelFace):
    name = "baymax"

    def __init__(self, cfg: dict, source, orientation: str = "portrait") -> None:
        super().__init__(cfg, source)
        self.L = LANDSCAPE if orientation == "landscape" else PORTRAIT
        self.accent = (255, 107, 138)
        self.bg = (12, 12, 18)
        self.muted_c = (192, 160, 176)
        self._rng = random.Random(7)
        self._next_blink = 0.0
        self._blink_t0 = None
        self._trace: list[float] = []
        self._cursor = 0
        self._beat = 0.0
        self._cache: dict[str, tuple] = {}

    # ---- colours -----------------------------------------------------------------
    def _colours(self) -> None:
        style = self.style() or {}
        pal = style.get("palette", {})
        self.accent = hexrgb(style.get("accent", "#FF6B8A"))
        self.bg = hexrgb(pal.get("bg", "#0C0C12"))
        self.muted_c = hexrgb(pal.get("muted", "#C0A0B0"))

    # ---- geometry ------------------------------------------------------------------
    def _egg(self, dx=0.0, dy=0.0, grow=0.0):
        cx, cy, a, b = self.L.head
        pts = []
        for i in range(72):
            th = 2 * math.pi * i / 72
            s = math.sin(th)
            pts.append((cx + dx + (a + grow) * math.cos(th) * (1 + 0.07 * s), cy + dy + (b + grow) * s))
        return pts

    def _arm(self, side: int, grow: float = 0.0, shift: float = 0.0):
        """One arm as a tilted ellipse; side -1 = viewer's left, +1 mirrored."""
        x, y, rx, ry, tilt = self.L.arm
        if side > 0:
            x = self.L.w - x
        a = math.radians(-tilt * side)
        ox = -side * rx * shift                      # sheen sits toward the outer edge
        pts = []
        for i in range(60):
            t = 2 * math.pi * i / 60
            px, py = (rx + grow) * math.cos(t) + ox, (ry + grow) * math.sin(t)
            pts.append((x + px * math.cos(a) - py * math.sin(a), y + px * math.sin(a) + py * math.cos(a)))
        return pts

    def _dome(self, dy=0.0, grow=0.0, n=3.4):
        """Torso outline: a superellipse, so the shoulders are broad and square-ish."""
        cx, cy, rx, ry = self.L.torso
        pts = []
        for i in range(120):
            t = 2 * math.pi * i / 120
            c, s = math.cos(t), math.sin(t)
            pts.append((cx + (rx + grow) * math.copysign(abs(c) ** (2 / n), c),
                        cy + dy + (ry + grow) * math.copysign(abs(s) ** (2 / n), s)))
        return pts

    def _eyes(self):
        cx, cy, a, b = self.L.head
        ey = cy + b * 0.2
        return (cx - self.L.eye_dx, ey), (cx + self.L.eye_dx, ey)

    def _boxes(self):
        (lx, ey), (rx, _) = self._eyes()
        r = self.L.eye_r
        eyes = (int(lx - r - 6), int(ey - r - 8), int(rx + r + 7), int(ey + r + 8))
        return {
            "eyes": eyes,
            "screen": tuple(v + d for v, d in zip(self.L.screen, (-8, -8, 8, 8))),
            "clock": (self.L.w - 120, 0, self.L.w, 34),
            "mute": (self.L.w // 2 - 40, 4, self.L.w // 2 + 40, 30),
        }

    # ---- static scene ----------------------------------------------------------------
    def _scene(self) -> Image.Image:
        """Everything that never changes, at supersampled resolution."""
        L = self.L
        pen = Pen.canvas((0, 0, L.w, L.h), self.bg)
        # arms hang from the shoulders, tops tucked under the shoulder curve, angled out a little
        for side in (-1, 1):
            pen.polygon(self._arm(side, 1.5), fill=SHADE2)
            pen.polygon(self._arm(side), fill=SHADE1)
            pen.polygon(self._arm(side, -9, 0.45), fill=lerp(SHADE1, WHITE, 0.6))    # soft sheen on the vinyl
        crease = lerp(SHADE2, INK, 0.12)                # where the arms tuck against the body
        pen.polygon(self._dome(2, 2.5), fill=crease)
        if L.belly:
            bx, by, brx, bry = L.belly
            pen.ellipse(bx, by + 2, brx + 2.5, bry + 2.5, fill=crease)
        pen.polygon(self._dome(), fill=WHITE)
        if L.belly:
            pen.ellipse(bx, by, brx, bry, fill=WHITE)
        # chest access port: a circle with a small chevron
        px, py = L.port
        pen.circle(px, py, 11, fill=SHADE1, outline=lerp(SHADE2, INK, 0.2), width=1.2)
        pen.line([(px - 5, py + 2), (px, py - 3), (px + 5, py + 2)], lerp(SHADE2, INK, 0.35), 1.6)
        # the head: a shaded rim (reads as its shadow on the body), then the white egg
        pen.polygon(self._egg(0, 3, 1.5), fill=SHADE2)
        pen.polygon(self._egg(), fill=WHITE)
        pen.text(12, 7, "BAYMAX", self.accent, UI_SB, 17)
        return pen.img

    def _screen_light(self, scene3: Image.Image) -> Image.Image:
        """The belly with the projector on: a feathered pale-blue screen and a faint grid."""
        x0, y0, x1, y1 = self._boxes()["screen"]
        S = Pen.S
        glow = Image.new("L", ((x1 - x0) * S, (y1 - y0) * S), 0)
        from PIL import ImageDraw
        m = 8 * S
        ImageDraw.Draw(glow).rounded_rectangle((m, m, glow.width - m, glow.height - m), radius=12 * S, fill=255)
        glow = glow.filter(ImageFilter.GaussianBlur(4 * S))
        lit = scene3.crop((x0 * S, y0 * S, x1 * S, y1 * S))
        lit.paste(Image.new("RGB", lit.size, SCREEN), (0, 0), glow)
        pen = Pen(lit, (x0, y0))
        sx0, sy0, sx1, sy1 = self.L.screen
        for gx in range(sx0 + 14, sx1 - 6, 14):
            pen.line([(gx, sy0 + 6), (gx, sy1 - 6)], GRID, 0.6)
        for gy in range(sy0 + 14, sy1 - 6, 14):
            pen.line([(sx0 + 6, gy), (sx1 - 6, gy)], GRID, 0.6)
        return lit

    def build(self) -> FrameDiff:
        self._colours()
        self.scene3 = self._scene()
        self.screen3 = self._screen_light(self.scene3)
        bg = self.scene3.resize((self.L.w, self.L.h), Image.LANCZOS)
        boxes = self._boxes()
        order = ["eyes", "mute", "screen", "clock"]

        def priority(x, y):
            for i, k in enumerate(order):
                b = boxes[k]
                if b[0] <= x < b[2] and b[1] <= y < b[3]:
                    return i
            return len(order)

        self._frame = bg.copy()
        self._cache.clear()
        return FrameDiff(bg, priority)

    # ---- per frame ---------------------------------------------------------------------
    def _region(self, key: str, sig, paint) -> None:
        """Repaint one region only when what it shows (sig) changed."""
        if self._cache.get(key) == sig:
            return
        self._cache[key] = sig
        box = self._boxes()[key]
        base = self.screen3 if key == "screen" and sig[0] != "off" else None
        pen = Pen(base.copy(), box[:2]) if base is not None else Pen.over(self.scene3, box)
        paint(pen)
        self._frame.paste(pen.done(), box[:2])

    def _shutter(self, state: str, now: float) -> float:
        if state == "off":
            return 1.0
        if self._blink_t0 is None and now >= self._next_blink:
            self._blink_t0 = now
            self._next_blink = now + 3.5 + self._rng.random() * 4.0
        if self._blink_t0 is None:
            return 0.0
        e = now - self._blink_t0
        if e < SHUT_CLOSE:
            return _smooth(e / SHUT_CLOSE)
        if e < SHUT_CLOSE + SHUT_HOLD:
            return 1.0
        if e < SHUT_CLOSE + SHUT_HOLD + SHUT_OPEN:
            return 1.0 - _smooth((e - SHUT_CLOSE - SHUT_HOLD) / SHUT_OPEN)
        self._blink_t0 = None
        return 0.0

    def update(self, state: str, muted: bool, level: float, now: float) -> None:
        shut = round(self._shutter(state, now), 1)
        mode = "happy" if state == "listening" and shut < 0.5 else "droop" if state == "error" else "open"
        self._region("eyes", (mode, shut), lambda pen: self._paint_eyes(pen, mode, shut))
        self._region("mute", (muted,), lambda pen: self._paint_mute(pen, muted))
        hm, ap = clock_text()
        self._region("clock", (hm, ap), lambda pen: pen.text(self.L.w - 12, 7, f"{hm} {ap}", self.muted_c, UI_SB, 17,
                                                             anchor="ra"))
        self._screen(state, level, now)
        self.face.draw(self._frame)

    # ---- eyes ----------------------------------------------------------------------------
    def _paint_eyes(self, pen: Pen, mode: str, shut: float) -> None:
        (lx, ey), (rx, _) = self._eyes()
        r = self.L.eye_r
        pen.line([(lx, ey), ((lx + rx) / 2, ey + r * 0.3), (rx, ey)], INK, 2.6)
        for ex in (lx, rx):
            if mode == "happy":
                pen.arc(ex, ey + 5, r + 2, r + 1, 195, 345, INK, 5)
            elif shut > 0.9:
                pen.line([(ex - r, ey), (ex + r, ey)], INK, 3)
            elif mode == "droop":                       # low battery: lids half down
                pen.chord(ex, ey, r, 0, 180, fill=INK)
                pen.line([(ex - r - 1, ey), (ex + r + 1, ey)], INK, 2)
            else:
                h = r * (1.0 - shut)
                pts = [(ex + r * math.cos(t), ey + max(-h, min(h, r * math.sin(t))))
                       for t in (2 * math.pi * i / 40 for i in range(40))]
                pen.polygon(pts, fill=INK)

    def _paint_mute(self, pen: Pen, muted: bool) -> None:
        if not muted:
            return
        c = self.L.w // 2
        pen.rrect(c - 36, 7, c + 36, 28, 10, fill=self.accent)
        pen.text(c, 17.5, "MIC OFF", self.bg, UI_SB, 13, anchor="mm")

    # ---- belly screen --------------------------------------------------------------------
    def _screen(self, state: str, level: float, now: float) -> None:
        kind = {"off": "off", "speaking": "ecg", "thinking": "think", "error": "battery",
                "joining": "heart"}.get(state, "scan")
        if kind == "ecg":
            self._advance_trace(level)
            sig = (kind, self._cursor, tuple(self._trace))
        elif kind == "think":
            sig = (kind, int(now * 8))
        elif kind == "heart":
            sig = (kind, int(now * 8))
        elif kind == "battery":
            sig = (kind, int(now * 2) % 2)
        elif kind == "scan":
            st = self.stats
            sig = (kind, round(st.cpu), round(st.gpu_temp), round(st.ram))
        else:
            sig = (kind,)
        if kind != "ecg":
            self._trace = []
        self._region("screen", sig, lambda pen: getattr(self, f"_paint_{kind}")(pen, now))

    def _paint_off(self, pen: Pen, now: float) -> None:
        pass

    def _advance_trace(self, level: float) -> None:
        """Heart-monitor sweep: a few new columns per frame, spiking with his voice."""
        sx0, sy0, sx1, sy1 = self.L.screen
        width = sx1 - sx0 - 20
        if not self._trace:
            self._trace = [0.0] * width
            self._cursor = 0
        for _ in range(5):
            i = self._cursor
            phase = i % 18
            if level > 0.05 and phase in (6, 7, 8):
                v = {6: 0.35, 7: -1.0, 8: 0.55}[phase] * level
            else:
                v = 0.04 * math.sin(i * 0.9) * (level > 0.05)
            self._trace[i] = v
            self._cursor = (i + 1) % width

    def _paint_ecg(self, pen: Pen, now: float) -> None:
        sx0, sy0, sx1, sy1 = self.L.screen
        mid, amp = (sy0 + sy1) / 2, (sy1 - sy0) * 0.4
        x0 = sx0 + 10
        gap = 10
        seg = []
        for i, v in enumerate(self._trace):
            if 0 <= (i - self._cursor) % len(self._trace) < gap:
                if len(seg) > 1:
                    pen.line(seg, self.accent, 2.2)
                seg = []
                continue
            seg.append((x0 + i, mid + v * amp))
        if len(seg) > 1:
            pen.line(seg, self.accent, 2.2)
        hx = x0 + (self._cursor - 1) % len(self._trace)
        pen.circle(hx, mid + self._trace[(self._cursor - 1) % len(self._trace)] * amp, 2.6, fill=self.accent)

    def _cloud(self, pen: Pen, ccx: float, ccy: float, k: float) -> None:
        puffs = ((-22, 3, 10), (-9, -6, 12), (8, -7, 12), (22, 1, 10), (8, 8, 11), (-10, 8, 10))
        for dx, dy, r in puffs:
            pen.circle(ccx + dx * k, ccy + dy * k, (r + 1.6) * k, fill=CLOUD_EDGE)
        for dx, dy, r in puffs:
            pen.circle(ccx + dx * k, ccy + dy * k, r * k, fill=CLOUD)

    def _paint_think(self, pen: Pen, now: float) -> None:
        sx0, sy0, sx1, sy1 = self.L.screen
        k = min(sx1 - sx0, (sy1 - sy0) * 1.6) / 90
        ccx, ccy = (sx0 + sx1) / 2 + 6 * k, (sy0 + sy1) / 2 - 6 * k
        self._cloud(pen, ccx, ccy, k)
        for bx, by, r in ((-30, 26, 3.0), (-22, 18, 4.5)):
            pen.circle(ccx + bx * k, ccy + by * k, r * k, fill=CLOUD, outline=CLOUD_EDGE, width=1.5)
        for i in range(3):
            p = 0.5 + 0.5 * math.sin(now * 4.0 - i * 0.9)
            pen.circle(ccx + (-12 + i * 12) * k, ccy + 1 * k, (2.4 + 1.4 * p) * k,
                       fill=lerp(CLOUD_EDGE, self.accent, p))

    def _heart(self, pen: Pen, cx: float, cy: float, s: float, fill) -> None:
        pts = []
        for i in range(48):
            t = 2 * math.pi * i / 48
            x = 16 * math.sin(t) ** 3
            y = -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))
            pts.append((cx + x * s / 16, cy + y * s / 16))
        pen.polygon(pts, fill=fill)

    def _paint_heart(self, pen: Pen, now: float) -> None:
        sx0, sy0, sx1, sy1 = self.L.screen
        beat = max(0.0, math.sin(now * 2 * math.pi * 1.1)) ** 4
        s = (sy1 - sy0) * (0.24 + 0.05 * beat)
        self._heart(pen, (sx0 + sx1) / 2, (sy0 + sy1) / 2, s, lerp(self.accent, (255, 170, 190), beat))

    def _paint_battery(self, pen: Pen, now: float) -> None:
        sx0, sy0, sx1, sy1 = self.L.screen
        cx, cy = (sx0 + sx1) / 2, (sy0 + sy1) / 2 - 8
        bw, bh = (sx1 - sx0) * 0.42, (sy1 - sy0) * 0.34
        pen.rrect(cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2, 5, outline=SCREEN_INK, width=2.4)
        pen.rrect(cx + bw / 2 + 1, cy - bh / 5, cx + bw / 2 + 6, cy + bh / 5, 2, fill=SCREEN_INK)
        if int(now * 2) % 2 == 0:
            pen.rrect(cx - bw / 2 + 5, cy - bh / 2 + 5, cx - bw / 2 + 5 + bw * 0.18, cy + bh / 2 - 5, 2,
                      fill=(208, 48, 80))
        pen.text(cx, sy1 - 16, "LOW BATTERY", SCREEN_INK, UI_SB, 12, anchor="mm")

    def _paint_scan(self, pen: Pen, now: float) -> None:
        """Idle: a quiet vitals scan of the PC."""
        sx0, sy0, sx1, sy1 = self.L.screen
        st = self.stats
        rows = (("CPU", st.cpu, f"{st.cpu:.0f}%"), ("GPU", min(100, st.gpu_temp), f"{st.gpu_temp:.0f}°"),
                ("RAM", st.ram, f"{st.ram:.0f}%"))
        pad = 16
        top = sy0 + (sy1 - sy0) * 0.18
        step = (sy1 - sy0 - (top - sy0) * 2) / 2
        bar0, bar1 = sx0 + pad + 34, sx1 - pad - 42
        for i, (label, pct, text) in enumerate(rows):
            y = top + i * step
            pen.text(sx0 + pad, y, label, SCREEN_INK, UI_SB, 12, anchor="lm")
            pen.rrect(bar0, y - 3, bar1, y + 3, 3, fill=GRID)
            if pct > 0.5:
                pen.rrect(bar0, y - 3, bar0 + (bar1 - bar0) * pct / 100, y + 3, 3, fill=self.accent)
            pen.text(sx1 - pad, y, text, SCREEN_INK, UI_SB, 12, anchor="rm")
