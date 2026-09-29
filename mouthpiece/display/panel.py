"""Generic desk-panel face: the thread, driver, stats, clock and budgeted flush
that every cast member's face shares. A bot's face module only decides what the
glass should look like each frame.

Two ways to describe the glass (both expose flush / invalidate / render):
  TileFace  (tiles.py)  named slots showing sprite-sheet frames (KITT's dash)
  FrameDiff (here)      a whole frame image; only changed 8x8 blocks are sent,
                        tightened to the changed pixels (organic faces: Baymax,
                        Wheatley), so drawing can be procedural.
Either way a frame never sends more than the link's per-frame byte budget;
leftovers go out on later frames.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from typing import Callable, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .turing import BYTES_PER_SEC, TuringRevA

log = logging.getLogger("mouthpiece.panel")

FPS = 12
W, H = 320, 480
Source = Callable[[], dict]   # -> {"state": str, "muted": bool, "audio": AudioIO | None}


# ---- shared inputs ------------------------------------------------------------
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
    it onto 0..1; fast attack, softer release.
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


def clock_text(now: Optional[time.struct_time] = None) -> tuple[str, str]:
    now = now or time.localtime()
    return time.strftime("%I:%M", now).lstrip("0"), time.strftime("%p", now)


# ---- drawing helpers for procedural faces ------------------------------------------
FONTS = r"C:\Windows\Fonts"


def font(name: str, size: float, variation: Optional[str] = None) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(f"{FONTS}\\{name}", int(round(size)))
    if variation:
        f.set_variation_by_name(variation)
    return f


def hexrgb(v: str) -> tuple[int, int, int]:
    v = v.lstrip("#")
    return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))


def lerp(a, b, t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))


class Pen:
    """ImageDraw in panel coordinates on a supersampled canvas (anti-aliasing by
    drawing at SxS and downsampling). `origin` is the canvas's top-left in panel
    coordinates, so a region can be redrawn on its own."""

    S = 3

    def __init__(self, img: Image.Image, origin: tuple[int, int] = (0, 0)) -> None:
        self.img = img
        self.d = ImageDraw.Draw(img)
        self.ox, self.oy = origin

    @classmethod
    def canvas(cls, box: tuple[int, int, int, int], fill=(0, 0, 0)) -> "Pen":
        x0, y0, x1, y1 = box
        return cls(Image.new("RGB", ((x1 - x0) * cls.S, (y1 - y0) * cls.S), fill), (x0, y0))

    @classmethod
    def over(cls, base: Image.Image, box: tuple[int, int, int, int]) -> "Pen":
        """A supersampled canvas holding `base` (a full-size 2D scene at S x) cropped to box."""
        S = cls.S
        return cls(base.crop(tuple(v * S for v in box)), (box[0], box[1]))

    def p(self, x: float, y: float) -> tuple[float, float]:
        return (x - self.ox) * self.S, (y - self.oy) * self.S

    def pts(self, points) -> list[tuple[float, float]]:
        return [self.p(x, y) for x, y in points]

    def ellipse(self, cx, cy, rx, ry, fill=None, outline=None, width=1):
        (x0, y0), (x1, y1) = self.p(cx - rx, cy - ry), self.p(cx + rx, cy + ry)
        self.d.ellipse((x0, y0, x1, y1), fill=fill, outline=outline, width=int(round(width * self.S)))

    def circle(self, cx, cy, r, **kw):
        self.ellipse(cx, cy, r, r, **kw)

    def rrect(self, x0, y0, x1, y1, r, fill=None, outline=None, width=1):
        (a, b), (c, d) = self.p(x0, y0), self.p(x1, y1)
        self.d.rounded_rectangle((a, b, c, d), radius=r * self.S, fill=fill, outline=outline,
                                 width=int(round(width * self.S)))

    def rect(self, x0, y0, x1, y1, fill=None, outline=None, width=1):
        (a, b), (c, d) = self.p(x0, y0), self.p(x1, y1)
        self.d.rectangle((a, b, c, d), fill=fill, outline=outline, width=int(round(width * self.S)))

    def line(self, points, fill, width=1, joint="curve"):
        self.d.line(self.pts(points), fill=fill, width=max(1, int(round(width * self.S))), joint=joint)

    def polygon(self, points, fill=None, outline=None):
        self.d.polygon(self.pts(points), fill=fill, outline=outline)

    def arc(self, cx, cy, rx, ry, start, end, fill, width=1):
        (x0, y0), (x1, y1) = self.p(cx - rx, cy - ry), self.p(cx + rx, cy + ry)
        self.d.arc((x0, y0, x1, y1), start, end, fill=fill, width=int(round(width * self.S)))

    def chord(self, cx, cy, r, start, end, fill=None, outline=None, width=1):
        (x0, y0), (x1, y1) = self.p(cx - r, cy - r), self.p(cx + r, cy + r)
        self.d.chord((x0, y0, x1, y1), start, end, fill=fill, outline=outline, width=int(round(width * self.S)))

    def text(self, x, y, s, fill, fnt_name, size, anchor="la", variation=None):
        """size in panel pixels; anchor as in PIL (la = left/ascender, rs = right/baseline...)."""
        f = font(fnt_name, size * self.S, variation)
        self.d.text(self.p(x, y), s, fill=fill, font=f, anchor=anchor)

    def textlength(self, s, fnt_name, size, variation=None) -> float:
        return self.d.textlength(s, font=font(fnt_name, size * self.S, variation)) / self.S

    def done(self) -> Image.Image:
        w, h = self.img.size
        return self.img.resize((w // self.S, h // self.S), Image.LANCZOS)


# ---- frame-diff surface ----------------------------------------------------------
class FrameDiff:
    """The glass as a whole image. flush() sends only what differs from what is
    already on the glass: 8x8 blocks, merged into row runs and tightened to the
    changed pixels, most important region first, within the byte budget."""

    BLOCK = 8

    def __init__(self, background: Image.Image, priority: Optional[Callable[[int, int], int]] = None) -> None:
        self.background = background.convert("RGB")
        self.frame = self.background.copy()
        self.shown: Optional[np.ndarray] = None
        self.priority = priority or (lambda x, y: 5)

    def draw(self, frame: Image.Image) -> None:
        self.frame = frame

    def invalidate(self, glass: Optional[Image.Image] = None) -> None:
        """Forget what is on the glass (or set it, e.g. after blitting the background)."""
        self.shown = None if glass is None else np.asarray(glass.convert("RGB")).copy()

    def dirty(self) -> list[tuple[int, int, int, int]]:
        cur = np.asarray(self.frame)
        if self.shown is None:
            return [(0, 0, cur.shape[1], cur.shape[0])]
        diff = np.any(cur != self.shown, axis=2)
        B = self.BLOCK
        h, w = diff.shape
        blocks = diff.reshape(h // B, B, w // B, B).any(axis=(1, 3))
        rects = []
        for by, row in enumerate(blocks):
            bx = 0
            while bx < len(row):
                if not row[bx]:
                    bx += 1
                    continue
                start = bx
                while bx < len(row) and row[bx]:
                    bx += 1
                x0, x1, y0 = start * B, bx * B, by * B
                sub = diff[y0:y0 + B, x0:x1]
                ys, xs = np.nonzero(sub.any(axis=1))[0], np.nonzero(sub.any(axis=0))[0]
                rects.append((x0 + xs[0], y0 + ys[0], x0 + xs[-1] + 1, y0 + ys[-1] + 1))
        return self._merge(rects)

    @staticmethod
    def _merge(rects):
        """Join rects stacked directly on top of each other with the same x span."""
        out: list[list[int]] = []
        for r in sorted(rects, key=lambda r: (r[0], r[2], r[1])):
            last = out[-1] if out else None
            if last and last[0] == r[0] and last[2] == r[2] and r[1] <= last[3] + FrameDiff.BLOCK:
                last[3] = max(last[3], r[3])
            else:
                out.append(list(r))
        return [tuple(r) for r in out]

    @staticmethod
    def _bands(rects, budget):
        """Cut rects that alone exceed the budget into horizontal bands that fit."""
        out = []
        for x0, y0, x1, y1 in rects:
            rows = max(1, budget // max(1, (x1 - x0) * 2)) if budget else y1 - y0
            for y in range(y0, y1, rows):
                out.append((x0, y, x1, min(y1, y + rows)))
        return out

    def flush(self, screen, budget: Optional[int] = None) -> tuple[int, int]:
        rects = self._bands(self.dirty(), budget)
        rects.sort(key=lambda r: (self.priority(r[0], r[1]), r[1], r[0]))
        if self.shown is None:
            self.shown = np.zeros((self.frame.height, self.frame.width, 3), np.uint8)
        cur = np.asarray(self.frame)
        sent = count = 0
        for x0, y0, x1, y1 in rects:
            cost = (x1 - x0) * (y1 - y0) * 2
            if budget is not None and count and sent + cost > budget:
                continue
            screen.blit(self.frame.crop((x0, y0, x1, y1)), x0, y0)
            self.shown[y0:y1, x0:x1] = cur[y0:y1, x0:x1]
            sent += cost
            count += 1
        return sent, count

    def render(self) -> Image.Image:
        return self.frame.copy()


# ---- the face thread ------------------------------------------------------------
class PanelFace:
    """Base for one bot's face on the Turing panel. Subclasses set `name` and
    implement build() -> surface (TileFace or FrameDiff) and update(state, muted,
    level, now), which sets what the surface should show."""

    name = "face"

    def __init__(self, cfg: dict, source: Source) -> None:
        self.cfg = cfg or {}
        self.source = source
        self.screen: Optional[TuringRevA] = None
        self.face = None                          # the surface, built on the face thread
        self.stats = Stats()
        self.meter = VoiceMeter()
        self.budget = int(BYTES_PER_SEC / FPS * 0.9)
        self._stop = threading.Event()
        self._blank = False
        self._thread: Optional[threading.Thread] = None

    # ---- to implement --------------------------------------------------------
    def build(self):
        raise NotImplementedError

    def update(self, state: str, muted: bool, level: float, now: float) -> None:
        raise NotImplementedError

    def style(self) -> Optional[dict]:
        """This bot's colours from the cast registry (cast/<name>/style.yaml)."""
        from .registry import load_style
        return load_style(self.name, self.cfg.get("registry"))

    # ---- shared ----------------------------------------------------------------
    def level(self, state: str, audio) -> float:
        """Voice level 0..1 while speaking, from the bot's real audio."""
        if state == "speaking" and audio is not None:
            peak = getattr(audio, "speaker_peak", audio.speaker_level)
            audio.speaker_peak = 0.0
            return self.meter.update(peak)
        self.meter.value = 0.0
        return 0.0

    def step(self, state: str, muted: bool = False, audio=None, now: Optional[float] = None) -> None:
        """One frame of face logic (no I/O); previews call this directly."""
        self.stats.poll()
        self.update(state, muted, self.level(state, audio), time.monotonic() if now is None else now)

    def preview(self, state: str, muted: bool = False, level: float = 0.0, now: float = 0.0) -> Image.Image:
        if self.face is None:
            self.face = self.build()
        self.update(state, muted, level, now)
        return self.face.render()

    # ---- thread ----------------------------------------------------------------
    def start(self, screen: Optional[TuringRevA] = None) -> None:
        self.screen = screen or TuringRevA(self.cfg.get("port", "AUTO"))
        self._thread = threading.Thread(target=self._run, name=f"{self.name}-face", daemon=True)
        self._thread.start()

    def stop(self, blank: bool = False, close: bool = True) -> None:
        """Stop driving the panel. blank=True switches the backlight off (hidden);
        otherwise the face is left drawn in its asleep state (Mouthpiece quitting).
        close=False keeps the port open for the next face (bot switch)."""
        self._blank = blank
        self._keep_open = not close
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)

    def _connect(self) -> None:
        scr = self.screen
        if scr.ser is None:
            scr.open()
            scr.brightness(int(self.cfg.get("brightness", 50)))
        bg = self.face.background
        scr.blit(bg, 0, 0)                                  # the one full-screen draw (~2 s)
        self.face.invalidate(bg)

    def _run(self) -> None:
        period = 1.0 / FPS
        self._keep_open = False
        self.face = self.build()
        while not self._stop.is_set():
            try:
                self._connect()
                log.info("%s face running (budget %d bytes/frame)", self.name, self.budget)
                while not self._stop.is_set():
                    t0 = time.monotonic()
                    src = self.source()
                    self.step(src.get("state", "off"), bool(src.get("muted")), src.get("audio"))
                    self.face.flush(self.screen, self.budget)
                    self._stop.wait(max(0.0, period - (time.monotonic() - t0)))
                if self._blank:
                    self.screen.screen_off()
                elif not self._keep_open:
                    self.step("off")                          # leave the face asleep
                    self.face.flush(self.screen)
            except Exception as e:
                log.warning("%s face: %s; retrying in 15 s", self.name, e)
                self.screen.close()
                self._stop.wait(15)
            finally:
                if not self._keep_open:
                    self.screen.close()
