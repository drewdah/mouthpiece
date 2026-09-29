"""The KITT face on a Turing 3.5" screen, driven straight from the voice session.

Each frame decides which sprite every slot should show (scanner lamps,
voice-box segments, mode lamps, LED bars, digits) and the tile face sends only
what changed, within the link's byte budget. Portrait (320x480) and landscape
(480x320) layouts live in make_kitt_sheet.py, shared with the sheet generator.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from .make_kitt_sheet import BAR_SEG, LAYOUTS, KittLayout
from .panel import PanelFace
from .tiles import Atlas, TileFace

log = logging.getLogger("mouthpiece.kitt")

SHEETS = Path(__file__).resolve().parent / "sheets"

COL_W, SEG_PITCH = 58, 13
ROWS = (9, 13, 9)                      # left, centre, right column segment counts
LAMPS = 8
BOUNCE = list(range(LAMPS)) + list(range(LAMPS - 2, 0, -1))
CLOCK_W = 86
BAR_PITCH = BAR_SEG[0] + 2

# Voice states (mouthpiece.session.State values).
SPEED = {"in room": 0.5, "listening": 0.5, "speaking": 0.5, "thinking": 1.0, "joining": 1.0, "error": 1.0}
LAMP_FOR = {"listening": "listen", "thinking": "think", "speaking": "speak"}


class KittFace(PanelFace):
    name = "kitt"

    def __init__(self, cfg: dict, source, orientation: str = "portrait") -> None:
        super().__init__(cfg, source)
        self.orientation = orientation if orientation in LAYOUTS else "portrait"
        self.L: KittLayout = LAYOUTS[self.orientation]
        self._pos = 0.0

    # ---- sheet -------------------------------------------------------------
    def _sheet(self) -> Path:
        """KITT's colours from the cast registry (cast/kitt/style.yaml, folder set by
        config turing.registry), baked into a cached sheet; the bundled sheet if no
        registry is configured or it isn't reachable."""
        style = self.style()
        if style:
            try:
                from ..config import user_dir
                from .make_kitt_sheet import build
                path = build(user_dir() / "faces" / "kitt", style, self.orientation)
                log.info("KITT face colours from cast registry (accent %s)", style.get("accent"))
                return path
            except Exception:
                log.exception("building KITT sheet from registry failed; using bundled sheet")
        return SHEETS / f"kitt{self.L.suffix}.json"

    # ---- layout ------------------------------------------------------------
    def build(self) -> TileFace:
        L = self.L
        self.face = f = TileFace(Atlas(self._sheet()))
        f.slot("mute", *L.mute, 0, "mute_off")
        for (x, y), name in zip(L.lamps, ("listen", "think", "speak")):
            f.slot(f"mode_{name}", x, y, 0, f"lamp_{name}_off")
        for c, rows in enumerate(ROWS):
            x = L.voice_x0 + c * (COL_W + L.col_gap)
            for r in range(rows):
                y = L.voice_mid_y + (r - rows // 2) * SEG_PITCH - 4
                f.slot(f"voice_{c}_{r}", x, y, 1, "voice_off")
        for n in range(LAMPS):
            f.slot(f"scan_{n}", L.scan_x0 + n * L.scan_pitch, L.scan_y, 2, "scan_x")
        for label, _, bx, y in L.bars:
            for s in range(L.bar_segs):
                f.slot(f"bar_{label}_{s}", bx + s * BAR_PITCH, y, 5, f"seg_{self._seg_color(s)}_off")
        for i, (*_, pos, _w, _a) in enumerate(L.readouts):
            f.slot(f"readout_{i}", *pos, 4, self._number(i, 0))
        f.slot("clock", *L.clock, 4, self._clock())
        return f

    def _number(self, i: int, val: float) -> str:
        """Readout tile: the value's digits, kerned, placed as the layout says."""
        *_, width, align = self.L.readouts[i]
        digits = [f"big_{ch}" for ch in str(int(round(max(0, min(999, val)))))]
        return self.face.atlas.compose(digits, width, 30, gap=3, align=align)

    def _clock(self) -> str:
        now = time.localtime()
        hm = time.strftime("%I:%M", now).lstrip("0")
        parts = ["small_colon" if ch == ":" else f"small_{ch}" for ch in hm]
        parts += ["small_sp", f"small_{time.strftime('%p', now)}"]
        return self.face.atlas.compose(parts, CLOCK_W, 20, gap=2, align="right")

    def _seg_color(self, s: int) -> str:
        frac = s / self.L.bar_segs
        return "g" if frac < 0.6 else "a" if frac < 0.85 else "r"

    # ---- per-frame state -----------------------------------------------------
    def update(self, state: str, muted: bool, level: float, now: float) -> None:
        f = self.face
        f.set("mute", "mute_on" if muted else "mute_off")
        lit_mode = LAMP_FOR.get(state)
        for name in ("listen", "think", "speak"):
            f.set(f"mode_{name}", f"lamp_{name}_{'on' if name == lit_mode else 'off'}")

        # Voice box: only while speaking, from the bot's real audio.
        for c, rows in enumerate(ROWS):
            reach = (rows // 2 + 1) * level * (1.0 if c == 1 else 0.85)
            for r in range(rows):
                on = level > 0.02 and abs(r - rows // 2) < reach
                f.set(f"voice_{c}_{r}", "voice_on" if on else "voice_off")

        # Scanner.
        speed = SPEED.get(state)
        if speed is None:                                   # off: all lamps dark
            for n in range(LAMPS):
                f.set(f"scan_{n}", "scan_x")
        else:
            tag = "a" if state == "error" else "r"
            self._pos = (self._pos + speed) % len(BOUNCE)
            i = int(self._pos)
            levels = [0] * LAMPS
            for k, lvl in enumerate((4, 3, 2, 1)):
                p = BOUNCE[(i - k) % len(BOUNCE)]
                levels[p] = max(levels[p], lvl)
            for n in range(LAMPS):
                f.set(f"scan_{n}", f"scan_{tag}{levels[n]}")

        # Stats (sampled 1/s) and clock.
        st = self.stats
        for label, pct in (("CPU", st.cpu), ("GPU", st.gpu)):
            lit = round(pct / 100 * self.L.bar_segs)
            for s in range(self.L.bar_segs):
                f.set(f"bar_{label}_{s}", f"seg_{self._seg_color(s)}_{'on' if s < lit else 'off'}")
        for i, val in enumerate((st.cpu, st.gpu_temp, st.ram)):
            f.set(f"readout_{i}", self._number(i, val))
        f.set("clock", self._clock())
