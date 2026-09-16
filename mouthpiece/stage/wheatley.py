"""Wheatley entity skin, V2: modelled on the Portal 2 personality core.

Sphere with panel seams and a black port at the bottom; a big dark optic socket with a blue
iris whose pupil dilates with volume; two shell-coloured eyelid shutters that slide in from
top and bottom independently and at an angle (that asymmetric squint is where his
expressions live); two hinged handles on the sides that swing as he talks; and the whole eye
assembly rolls with the head.

States: listening = wide open, lids retracted, optic drifts toward the cursor. thinking = tilted
squint, eye darts. speaking = lids ride the speech energy (open on peaks), pupil pulses,
handles swing, head rolls. idle = relaxed half-lids with slow drifts and blinks.
"""
from __future__ import annotations

import math
import random
import time

from .entity import EntitySkin, KEY_COLOR
from .kitt import hex_lerp

SHELL = "#E6E8EC"
SHELL_LO = "#B4B9C3"
SHELL_HI = "#F6F7F9"
SEAM = "#7C828D"
SOCKET = "#1C1E23"
SOCKET_RIM = "#3A3E46"
HANDLE = "#3E4450"
HANDLE_HI = "#8A909C"
BLUE = "#2B6CFF"
BLUE_DEEP = "#08204F"
BLUE_CORE = "#BFE0FF"


def _rot(px, py, cx, cy, deg):
    a = math.radians(deg)
    dx, dy = px - cx, py - cy
    return cx + dx * math.cos(a) - dy * math.sin(a), cy + dx * math.sin(a) + dy * math.cos(a)


class WheatleySkin(EntitySkin):
    name = "wheatley"
    size = (300, 420)
    accent = "#2B6CFF"

    def __init__(self, accent: str | None = None) -> None:
        super().__init__(accent)
        self._rng = random.Random(11)
        self.look = [0.0, 0.0]
        self.dart = [0.0, 0.0]
        self._next_dart = 0.0
        self.roll = 0.0                 # head roll (deg)
        self.lid_top = 0.25             # 0 open .. 1 closed
        self.lid_bot = 0.15
        self.lid_tilt = 0.0             # deg
        self._lid_target = (0.25, 0.15, 0.0)
        self._next_lid = 0.0
        self.handle = [-20.0, 20.0]     # swing offsets (deg) for left / right handle
        self._handle_target = [-20.0, 20.0]
        self._next_handle = 0.0
        self.pupil = 0.5

    # ---- animation -----------------------------------------------------------
    def step_body(self, state: str, dt: float) -> None:
        now = time.monotonic()
        t = now - self.t0
        k = min(1.0, dt * 6)
        rng = self._rng

        # gaze: cursor pull + occasional darts
        px, py = self.pointer
        cx, cy = self.size[0] / 2, self.BUBBLE_H + 120
        dx, dy = px - cx, py - cy
        d = math.hypot(dx, dy) or 1.0
        pull = min(1.0, d / 260.0) * (14.0 if self.hovering else 7.0)
        if state == "listening":
            pull *= 1.4
        tx, ty = dx / d * pull, dy / d * pull
        if now > self._next_dart:
            self._next_dart = now + (0.35 if state in ("thinking", "speaking") else 1.6) + rng.random() * 1.2
            amp = 9.0 if state == "thinking" else (6.0 if state == "speaking" else 3.0)
            self.dart = [rng.uniform(-amp, amp), rng.uniform(-amp * 0.6, amp * 0.6)]
        self.look[0] += (tx + self.dart[0] - self.look[0]) * k
        self.look[1] += (ty + self.dart[1] - self.look[1]) * k

        # eyelids: pick a new pose every so often, per state; speaking rides the energy
        if now > self._next_lid:
            if state == "listening":
                pose = (rng.uniform(0.0, 0.08), rng.uniform(0.0, 0.06), rng.uniform(-4, 4))
                hold = 1.2
            elif state == "thinking":
                pose = (rng.uniform(0.35, 0.6), rng.uniform(0.15, 0.35), rng.choice([-1, 1]) * rng.uniform(8, 18))
                hold = 0.9
            elif state == "speaking":
                pose = (rng.uniform(0.05, 0.4), rng.uniform(0.05, 0.3), rng.uniform(-14, 14))
                hold = 0.45
            else:
                pose = (rng.uniform(0.15, 0.35), rng.uniform(0.1, 0.25), rng.uniform(-6, 6))
                hold = 2.2
            self._lid_target = pose
            self._next_lid = now + hold + rng.random() * 0.6
        lt, lb, tilt = self._lid_target
        if state == "speaking":
            lt = max(0.0, lt - 0.3 * self.level)      # open up on loud syllables
            lb = max(0.0, lb - 0.2 * self.level)
        blink = self.blink
        lt, lb = max(lt, blink), max(lb, blink * 0.9)
        kl = min(1.0, dt * (14 if blink > 0 else 7))
        self.lid_top += (lt - self.lid_top) * kl
        self.lid_bot += (lb - self.lid_bot) * kl
        self.lid_tilt += (tilt - self.lid_tilt) * min(1.0, dt * 5)

        # head roll
        target_roll = math.sin(t * 0.7) * 3.0
        if state == "speaking":
            target_roll += math.sin(t * 2.3) * 5.0 * (0.4 + self.level)
        elif state == "thinking":
            target_roll += self.lid_tilt * 0.4
        self.roll += (target_roll - self.roll) * min(1.0, dt * 3)

        # handles: swing to new positions, more often and further while speaking
        if now > self._next_handle:
            spread = 45 if state == "speaking" else 18
            self._handle_target = [rng.uniform(-spread, spread) - 15, rng.uniform(-spread, spread) + 15]
            self._next_handle = now + (0.5 if state == "speaking" else 2.5) + rng.random()
        for i in range(2):
            self.handle[i] += (self._handle_target[i] - self.handle[i]) * min(1.0, dt * (5 if state == "speaking" else 2))

        # pupil
        tp = 0.45 + 0.5 * self.level if state == "speaking" else (0.62 if state == "listening" else 0.5)
        self.pupil += (tp - self.pupil) * min(1.0, dt * 8)

    def head_anchor(self, w, top):
        return w / 2, top + 14

    # ---- painting --------------------------------------------------------------
    def paint_body(self, cv, w, top, bottom, *, state, muted):
        cx, cy = w / 2, top + 122
        R = 96
        roll = self.roll

        # handles: hinged at the left/right poles of the sphere, swinging as arcs behind the shell
        for side, swing in ((-1, self.handle[0]), (1, self.handle[1])):
            pivot = 180 if side < 0 else 0
            base = pivot + (swing if side < 0 else -swing) + roll
            box = (cx - R - 16, cy - R - 16, cx + R + 16, cy + R + 16)
            start = base - 50
            cv.create_arc(*box, start=start, extent=100, style="arc", outline=HANDLE, width=14)
            cv.create_arc(*box, start=start + 3, extent=94, style="arc", outline=HANDLE_HI, width=4)
            for ang in (start, start + 100):
                a = math.radians(ang)
                ex, ey = cx + (R + 16) * math.cos(a), cy - (R + 16) * math.sin(a)
                cv.create_oval(ex - 8, ey - 8, ex + 8, ey + 8, fill=HANDLE, outline=HANDLE_HI)
            # hinge bolt on the shell
            hx_, hy_ = _rot(cx + side * R, cy, cx, cy, -roll)
            cv.create_oval(hx_ - 7, hy_ - 7, hx_ + 7, hy_ + 7, fill=SEAM, outline="#2A2E36")

        # shell with a darker rim and a lit upper-left (stippled so it reads as shading, not a shape)
        cv.create_oval(cx - R, cy - R, cx + R, cy + R, fill=SHELL_LO, outline="#8A8F99", width=2)
        cv.create_oval(cx - R + 7, cy - R + 5, cx + R - 9, cy + R - 13, fill=SHELL, outline="")
        cv.create_oval(cx - R + 16, cy - R + 12, cx + R - 30, cy + R - 40, fill=SHELL_HI, outline="", stipple="gray25")

        # panel seams (rolled with the head): meridian seam and an equator seam
        top_pt = _rot(cx, cy - R + 3, cx, cy, roll)
        bot_pt = _rot(cx, cy + R - 3, cx, cy, roll)
        cv.create_line(*top_pt, *bot_pt, fill=SEAM, width=2)
        cv.create_arc(cx - R + 3, cy - R * 0.35, cx + R - 3, cy + R * 0.35, start=180 + roll, extent=180,
                      style="arc", outline=SEAM, width=1)
        # black port at the bottom of the meridian
        px_, py_ = _rot(cx, cy + R * 0.72, cx, cy, roll)
        pts = [_rot(px_ + dx, py_ + dy, px_, py_, roll) for dx, dy in ((-7, -14), (7, -14), (7, 14), (-7, 14))]
        cv.create_polygon([c for p in pts for c in p], fill="#15171B", outline="#3A3E46")

        # optic socket (big dark ring) + iris, offset by gaze
        ox, oy = cx + self.look[0], cy + self.look[1]
        er = 54
        cv.create_oval(ox - er - 12, oy - er - 12, ox + er + 12, oy + er + 12, fill=SOCKET_RIM, outline="#5A5F69", width=2)
        cv.create_oval(ox - er - 6, oy - er - 6, ox + er + 6, oy + er + 6, fill=SOCKET, outline="")
        rings = 10
        for i in range(rings):
            f = i / (rings - 1)
            r = er * (1.0 - 0.78 * f)
            col = hex_lerp(BLUE_DEEP, BLUE, min(1.0, f * 1.1))
            if f > 0.62:
                col = hex_lerp(col, BLUE_CORE, (f - 0.62) / 0.38 * 0.85)
            cv.create_oval(ox - r, oy - r, ox + r, oy + r, fill=col, outline="")
        pr = er * 0.24 * (0.6 + 0.8 * self.pupil)
        cv.create_oval(ox - pr, oy - pr, ox + pr, oy + pr, fill="#04102A", outline="")
        cv.create_oval(ox - er * 0.36, oy - er * 0.50, ox - er * 0.12, oy - er * 0.30, fill="#E8F2FF", outline="")

        # eyelid shutters: shell-coloured chords sliding in from top and bottom, tilted
        box = (ox - er - 7, oy - er - 7, ox + er + 7, oy + er + 7)
        tilt = self.lid_tilt + roll * 0.5
        for lid, centre in ((self.lid_top, 90), (self.lid_bot, 270)):
            if lid < 0.02:
                continue
            ext = 180 * min(1.0, lid)
            cv.create_arc(*box, start=centre + tilt - ext / 2, extent=ext, style="chord", fill=SHELL_LO, outline="#8A8F99")
            cv.create_arc(*box, start=centre + tilt - ext / 2 + 2, extent=max(0, ext - 4), style="chord",
                          fill=SHELL, outline="")

        # thinking halo
        if state == "thinking":
            cv.create_oval(cx - R - 10, cy - R - 10, cx + R + 10, cy + R + 10, outline=hex_lerp(KEY_COLOR, BLUE, 0.5),
                           width=3, stipple="gray50")
