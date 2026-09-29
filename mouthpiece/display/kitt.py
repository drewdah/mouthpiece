"""The KITT face on a Turing 3.5" screen, driven straight from the voice session.

Runs on its own thread at ~12 fps. Each frame decides which sprite every slot
should show (scanner lamps, voice-box segments, mode lamps, LED bars, digits)
and the tile face sends only what changed, within the link's byte budget.

Enable with config  "turing": {"port": "AUTO", "brightness": 50}
"""
from __future__ import annotations

import logging
import math
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from .tiles import Atlas, TileFace
from .turing import BYTES_PER_SEC, TuringRevA

log = logging.getLogger("mouthpiece.kitt")

SHEET = Path(__file__).resolve().parent / "sheets" / "kitt.json"
FPS = 12

# Layout (must match make_kitt_sheet.py).
BOX_W, BOX_GAP = 96, 8
VOICE_X0, VOICE_MID_Y, COL_W, COL_GAP, SEG_PITCH = 39, 137, 58, 34, 13
ROWS = (9, 13, 9)                      # left, centre, right column segment counts
SCAN_X0, SCAN_Y, SCAN_PITCH, LAMPS = 14, 246, 37, 8
BOUNCE = list(range(LAMPS)) + list(range(LAMPS - 2, 0, -1))
MODE_Y = 292
BAR_X, BAR_SEGS, BAR_PITCH = 56, 25, 10
CPU_BAR_Y, GPU_BAR_Y = 352, 380
DIGIT_Y = 434
CLOCK_X, CLOCK_W = 222, 86

# Voice states (mouthpiece.session.State values).
SPEED = {"in room": 0.5, "listening": 0.5, "speaking": 0.5, "thinking": 1.0, "joining": 1.0, "error": 1.0}
LAMP_FOR = {"listening": "listen", "thinking": "think", "speaking": "speak"}

Source = Callable[[], dict]   # -> {"state": str, "muted": bool, "audio": AudioIO | None}


def box_x(i: int) -> int:
    return (320 - (3 * BOX_W + 2 * BOX_GAP)) // 2 + i * (BOX_W + BOX_GAP)


class Stats:
    """CPU/RAM via psutil, GPU via NVML; sampled once a second, all optional."""

    def __init__(self) -> None:
        self.cpu = self.ram = self.gpu = self.gpu_temp = 0.0
        self._next = 0.0
        try:
            import psutil
            self._psutil = psutil
            psutil.cpu_percent(None)
        except Exception:
            self._psutil = None
        try:
            import pynvml
            pynvml.nvmlInit()
            self._nv, self._gpu_h = pynvml, pynvml.nvmlDeviceGetHandleByIndex(0)
        except Exception:
            self._nv = None

    def poll(self) -> None:
        now = time.monotonic()
        if now < self._next:
            return
        self._next = now + 1.0
        if self._psutil:
            self.cpu = self._psutil.cpu_percent(None)
            self.ram = self._psutil.virtual_memory().percent
        if self._nv:
            try:
                self.gpu = self._nv.nvmlDeviceGetUtilizationRates(self._gpu_h).gpu
                self.gpu_temp = self._nv.nvmlDeviceGetTemperature(self._gpu_h, 0)
            except Exception:
                pass


class VoiceMeter:
    """Speaker RMS -> 0..1 with auto-gain, so a steady TTS voice still shows syllables.

    Tracks a slowly decaying reference peak (dB) and maps the last 24 dB below
    it onto the voice box; fast attack, softer release.
    """

    RANGE_DB = 24.0

    def __init__(self) -> None:
        self.ref_db = -20.0
        self.value = 0.0

    def update(self, rms: float) -> float:
        db = 20 * math.log10(max(rms, 1e-5))
        self.ref_db = max(db, self.ref_db - 0.4, -30.0)
        target = max(0.0, min(1.0, (db - (self.ref_db - self.RANGE_DB)) / self.RANGE_DB))
        self.value = target if target > self.value else self.value * 0.55 + target * 0.45
        return self.value


class KittFace:
    def __init__(self, cfg: dict, source: Source) -> None:
        self.cfg = cfg or {}
        self.source = source
        self.screen = TuringRevA(self.cfg.get("port", "AUTO"))
        self.face: Optional[TileFace] = None      # built on the face thread (registry may be slow)
        self.stats = Stats()
        self.meter = VoiceMeter()
        self.budget = int(BYTES_PER_SEC / FPS * 0.9)
        self._pos = 0.0
        self._stop = threading.Event()
        self._blank = False
        self._thread: Optional[threading.Thread] = None

    # ---- sheet -------------------------------------------------------------
    def _sheet(self) -> Path:
        """KITT's colours from the cast registry (cast/kitt/style.yaml, folder set by
        config turing.registry), baked into a cached sheet; the bundled sheet if no
        registry is configured or it isn't reachable."""
        from .registry import load_style
        style = load_style("kitt", self.cfg.get("registry"))
        if style:
            try:
                from ..config import user_dir
                from .make_kitt_sheet import build
                path = build(user_dir() / "faces" / "kitt", style)
                log.info("KITT face colours from cast registry (accent %s)", style.get("accent"))
                return path
            except Exception:
                log.exception("building KITT sheet from registry failed; using bundled sheet")
        return SHEET

    # ---- layout ------------------------------------------------------------
    def _build(self) -> None:
        self.face = TileFace(Atlas(self._sheet()))
        f = self.face
        f.slot("mute", 150, 12, 0, "mute_off")
        for i, name in enumerate(("listen", "think", "speak")):
            f.slot(f"mode_{name}", box_x(i), MODE_Y, 0, f"lamp_{name}_off")
        for c, rows in enumerate(ROWS):
            x = VOICE_X0 + c * (COL_W + COL_GAP)
            for r in range(rows):
                y = VOICE_MID_Y + (r - rows // 2) * SEG_PITCH - 4
                f.slot(f"voice_{c}_{r}", x, y, 1, "voice_off")
        for n in range(LAMPS):
            f.slot(f"scan_{n}", SCAN_X0 + n * SCAN_PITCH, SCAN_Y, 2, "scan_x")
        for label, y in (("cpu", CPU_BAR_Y), ("gpu", GPU_BAR_Y)):
            for s in range(BAR_SEGS):
                f.slot(f"bar_{label}_{s}", BAR_X + s * BAR_PITCH, y, 5, f"seg_{self._seg_color(s)}_off")
        for i in range(3):
            f.slot(f"readout_{i}", box_x(i) + 4, DIGIT_Y, 4, self._number(0))
        f.slot("clock", CLOCK_X, 11, 4, self._clock())

    def _number(self, val: float) -> str:
        """Readout tile: the value's digits, kerned and centred in the box."""
        digits = [f"big_{ch}" for ch in str(int(round(max(0, min(999, val)))))]
        return self.face.atlas.compose(digits, BOX_W - 8, 30, gap=3)

    def _clock(self) -> str:
        now = time.localtime()
        hm = time.strftime("%I:%M", now).lstrip("0")
        parts = ["small_colon" if ch == ":" else f"small_{ch}" for ch in hm]
        parts += ["small_sp", f"small_{time.strftime('%p', now)}"]
        return self.face.atlas.compose(parts, CLOCK_W, 20, gap=2, align="right")

    @staticmethod
    def _seg_color(s: int) -> str:
        frac = s / BAR_SEGS
        return "g" if frac < 0.6 else "a" if frac < 0.85 else "r"

    # ---- per-frame state -----------------------------------------------------
    def _update(self, state: str, muted: bool, audio) -> None:
        f = self.face
        f.set("mute", "mute_on" if muted else "mute_off")
        lit_mode = LAMP_FOR.get(state)
        for name in ("listen", "think", "speak"):
            f.set(f"mode_{name}", f"lamp_{name}_{'on' if name == lit_mode else 'off'}")

        # Voice box: only while speaking, from the bot's real audio.
        level = 0.0
        if state == "speaking" and audio is not None:
            peak = getattr(audio, "speaker_peak", audio.speaker_level)
            audio.speaker_peak = 0.0
            level = self.meter.update(peak)
        else:
            self.meter.value = 0.0
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
        st.poll()
        for label, pct in (("cpu", st.cpu), ("gpu", st.gpu)):
            lit = round(pct / 100 * BAR_SEGS)
            for s in range(BAR_SEGS):
                f.set(f"bar_{label}_{s}", f"seg_{self._seg_color(s)}_{'on' if s < lit else 'off'}")
        for i, val in enumerate((st.cpu, st.gpu_temp, st.ram)):
            f.set(f"readout_{i}", self._number(val))
        f.set("clock", self._clock())

    # ---- thread --------------------------------------------------------------
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="kitt-face", daemon=True)
        self._thread.start()

    def stop(self, blank: bool = False) -> None:
        """Stop driving the panel. blank=True switches the backlight off (hidden);
        otherwise KITT is left drawn in his asleep state (Mouthpiece quitting)."""
        self._blank = blank
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)

    def _connect(self) -> None:
        self.screen.open()
        self.screen.brightness(int(self.cfg.get("brightness", 50)))
        self.screen.blit(self.face.atlas.background, 0, 0)     # the one full-screen draw (~2 s)
        self.face.invalidate()

    def _run(self) -> None:
        period = 1.0 / FPS
        self._build()
        while not self._stop.is_set():
            try:
                self._connect()
                log.info("KITT face running (budget %d bytes/frame)", self.budget)
                while not self._stop.is_set():
                    t0 = time.monotonic()
                    src = self.source()
                    self._update(src.get("state", "off"), bool(src.get("muted")), src.get("audio"))
                    self.face.flush(self.screen, self.budget)
                    self._stop.wait(max(0.0, period - (time.monotonic() - t0)))
                if self._blank:
                    self.screen.screen_off()
                else:
                    self._update("off", False, None)             # leave KITT asleep
                    self.face.flush(self.screen)
            except Exception as e:
                log.warning("KITT face: %s; retrying in 15 s", e)
                self._stop.wait(15)
            finally:
                self.screen.close()
