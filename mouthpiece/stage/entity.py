"""Entity skins: a character floating on the desktop instead of a dashboard panel.

The window keys out KEY_COLOR so only what the skin draws is visible (plus a stippled drop
shadow). Shared furniture lives here: the comic speech bubble for the bot's current line,
three round controls that fade in above the head on hover, and a transcript strip under the
feet that appears while hovering. Subclasses draw the body in `paint_body` and animate it in
`step_body`; they get the same snapshot the KITT cluster gets (state, levels, captions).
"""
from __future__ import annotations

import math
import time
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass

from .kitt import Button, hex_lerp

KEY_COLOR = "#010203"          # keyed out by the window; never draw with it on purpose
SHADOW = "#101014"
FONT = "Segoe UI"


_FONT_CACHE: dict = {}


def fit_text(text: str, font: tuple, max_px: float) -> str:
    """Truncate with an ellipsis so the rendered width fits max_px."""
    f = _FONT_CACHE.get(font)
    if f is None:
        weight = font[2] if len(font) > 2 else "normal"
        f = _FONT_CACHE[font] = tkfont.Font(family=font[0], size=font[1], weight=weight)
    if f.measure(text) <= max_px:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if f.measure(text[:mid] + "…") <= max_px:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip() + "…"


def rounded_rect(cv, x0, y0, x1, y1, r, **kw):
    """Rounded rectangle as a smoothed polygon (Tk canvas has no native one)."""
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
           x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return cv.create_polygon(pts, smooth=True, **kw)


@dataclass
class BubbleState:
    text: str = ""
    who: str = ""
    shown_at: float = 0.0


class EntitySkin:
    name = "entity"
    size = (300, 420)
    transparent = True
    accent = "#FF6B8A"
    body_light = "#FFFFFF"
    text_on_bubble = "#1A1A1A"

    # layout bands (fractions of height)
    BUBBLE_H = 118
    STRIP_H = 84
    CONTROL_R = 15

    def __init__(self, accent: str | None = None) -> None:
        if accent:
            self.accent = accent
        self.t0 = time.monotonic()
        self.level = 0.0            # smoothed speaker level 0..1
        self.mic = 0.0
        self.blink = 0.0            # 1 = eyes shut
        self._blink_until = 0.0
        self._last_state = "off"
        self.hover_alpha = 0.0      # 0..1 controls/strip visibility
        self.bubble = BubbleState()
        self.buttons: list[Button] = []
        self.pointer = (0, 0)       # last pointer position relative to the window
        self.hovering = False
        self.strip_pinned = False   # click toggles the transcript strip
        self.scroll_lines = 0

    # ---- animation ---------------------------------------------------------
    def step(self, state: str, spk_level: float, mic_level: float, dt: float) -> None:
        k = min(1.0, dt * 60.0)
        target = min(1.0, spk_level * 16.0) if state == "speaking" else 0.0
        atk = 0.35 if target > self.level else 0.12
        self.level += (target - self.level) * min(1.0, atk * k)
        self.mic += (min(1.0, mic_level * 8.0) - self.mic) * min(1.0, 0.2 * k)
        want = 1.0 if (self.hovering or self.strip_pinned) else 0.0
        self.hover_alpha += (want - self.hover_alpha) * min(1.0, 0.25 * k)
        now = time.monotonic()
        # blink on interruption / stop, and a natural blink every few seconds
        if state != self._last_state and self._last_state == "speaking" and state != "speaking":
            self._blink_until = now + 0.18
        if now > self._blink_until and int(now * 10) % 47 == 0 and self.blink < 0.05:
            self._blink_until = now + 0.12
        self.blink = 1.0 if now < self._blink_until else max(0.0, self.blink - 0.4 * k)
        self._last_state = state
        self.step_body(state, dt)

    def step_body(self, state: str, dt: float) -> None:  # override
        pass

    # ---- painting ----------------------------------------------------------
    def paint(self, cv: tk.Canvas, w: int, h: int, *, state: str, muted: bool, bot_display: str,
              captions, hover=None, pressed=None, scroll: int = 0, gated: bool = False,
              response_seq: int = 0) -> None:
        cv.delete("all")
        self.buttons = []
        cv.create_rectangle(0, 0, w, h, fill=KEY_COLOR, outline="")
        # The bubble holds only the current reply. A new response wipes it immediately;
        # that response's text fills it as soon as it arrives.
        if response_seq != getattr(self, "_bubble_seq", 0):
            self._bubble_seq = response_seq
            self.bubble = BubbleState()
        latest = None
        for cap in reversed(captions or []):
            if cap[0] == "you" or (len(cap) > 3 and cap[3] == "system"):
                continue
            if len(cap) > 5 and cap[5] < response_seq:
                break
            latest = cap
            break
        if latest and latest[1] != self.bubble.text:
            self.bubble = BubbleState(text=latest[1], who=latest[0], shown_at=time.monotonic())

        body_top = self.BUBBLE_H
        body_bottom = h - self.STRIP_H
        self.paint_shadow(cv, w, body_top, body_bottom)
        self.paint_body(cv, w, body_top, body_bottom, state=state, muted=muted)
        self.paint_bubble(cv, w, state, bot_display)
        self.paint_strip(cv, w, h, captions, scroll)
        self.paint_controls(cv, w, body_top, state, muted, hover, pressed)
        if gated or muted:
            self.paint_mic_badge(cv, w, body_top, muted)

    def paint_shadow(self, cv, w, top, bottom) -> None:
        cx, cy = w / 2, bottom - 6
        rx = w * 0.30
        cv.create_oval(cx - rx, cy - 10, cx + rx, cy + 10, fill=SHADOW, outline="", stipple="gray50")
        cv.create_oval(cx - rx * 0.8, cy - 7, cx + rx * 0.8, cy + 7, fill=SHADOW, outline="", stipple="gray75")

    def paint_body(self, cv, w, top, bottom, *, state: str, muted: bool) -> None:  # override
        pass

    def head_anchor(self, w: int, top: int) -> tuple[float, float]:
        """Where the bubble tail and the controls hang from. Override if the head isn't centred."""
        return w / 2, top + 24

    def paint_bubble(self, cv, w, state, bot_display) -> None:
        b = self.bubble
        hx, hy = self.head_anchor(w, self.BUBBLE_H)
        fresh = b.text and (time.monotonic() - b.shown_at < 14 or state in ("speaking", "thinking"))
        fill = hex_lerp(self.accent, "#ffffff", 0.82)
        edge = self.accent
        if state == "thinking":
            # thought dots while he works on it
            for i, r in enumerate((4, 6, 9)):
                cy = hy - 14 - i * 16
                cv.create_oval(hx - r + i * 10, cy - r, hx + r + i * 10, cy + r, fill=fill, outline=edge, width=2)
            return
        if not fresh:
            return
        pad = 10
        bw = w - 24
        x0, x1 = 12, 12 + bw
        y1 = hy - 16
        # measure text height by creating it first
        tid = cv.create_text(x0 + pad, 0, text=b.text, anchor="nw", width=bw - 2 * pad,
                             font=(FONT, 9), fill=self.text_on_bubble)
        bb = cv.bbox(tid)
        th = (bb[3] - bb[1]) if bb else 14
        y0 = max(4, y1 - th - 2 * pad)
        cv.delete(tid)
        rounded_rect(cv, x0, y0, x1, y1, 12, fill=fill, outline=edge, width=2)
        cv.create_polygon(hx - 10, y1 - 1, hx + 6, y1 - 1, hx, y1 + 12, fill=fill, outline=edge, width=2, smooth=False)
        cv.create_line(hx - 9, y1, hx + 5, y1, fill=fill, width=3)
        cv.create_text(x0 + pad, y0 + pad, text=b.text, anchor="nw", width=bw - 2 * pad,
                       font=(FONT, 9), fill=self.text_on_bubble)

    def paint_controls(self, cv, w, top, state, muted, hover, pressed) -> None:
        a = self.hover_alpha
        if a < 0.03:
            return
        hx, hy = self.head_anchor(w, top)
        items = [("mic", "UNMUTE" if muted else "MUTE", "amber" if muted else None),
                 ("stop", "STOP", "red" if state == "speaking" else None),
                 ("link", "LEAVE", None)]
        r = self.CONTROL_R
        gap = 12
        total = len(items) * (2 * r) + (len(items) - 1) * gap
        x = hx - total / 2 + r
        y = 20
        for bid, label, tone in items:
            base = {"amber": "#E27F1C", "red": "#C8261B"}.get(tone or "", hex_lerp(self.accent, "#000000", 0.35))
            face = hex_lerp(KEY_COLOR, base, a)
            if pressed == bid:
                face = hex_lerp(face, "#000000", 0.25)
            elif hover == bid:
                face = hex_lerp(face, "#ffffff", 0.15)
            edge = hex_lerp(KEY_COLOR, "#ffffff" if hover == bid else "#000000", a)
            cv.create_oval(x - r, y - r, x + r, y + r, fill=face, outline=edge, width=1)
            cv.create_text(x, y, text=label, font=(FONT, 6, "bold"), fill=hex_lerp(KEY_COLOR, "#ffffff", a))
            self.buttons.append(Button(bid, x - r, y - r, x + r, y + r))
            x += 2 * r + gap

    def paint_mic_badge(self, cv, w, top, muted) -> None:
        hx, hy = self.head_anchor(w, top)
        color = "#C8261B" if muted else "#E5C11E"
        cv.create_oval(hx + 38, top - 2, hx + 52, top + 12, fill=color, outline="#000000")
        cv.create_text(hx + 45, top + 5, text="M" if muted else "H", font=(FONT, 6, "bold"), fill="#111111")

    def paint_strip(self, cv, w, h, captions, scroll) -> None:
        a = self.hover_alpha
        if a < 0.03:
            return
        y0 = h - self.STRIP_H + 6
        y1 = h - 6
        bg = hex_lerp(KEY_COLOR, "#141418", a)
        rounded_rect(cv, 8, y0, w - 8, y1, 10, fill=bg, outline=hex_lerp(KEY_COLOR, self.accent, a * 0.6))
        lines = []
        for cap in (captions or [])[-30:]:
            who, text = cap[0], cap[1]
            kind = cap[3] if len(cap) > 3 else "reply"
            if kind == "system":
                continue
            lines.append((who, text))
        visible = 3
        end = max(0, len(lines) - scroll)
        start = max(0, end - visible)
        y = y0 + 8
        for who, text in lines[start:end]:
            is_bot = who != "you"
            color = hex_lerp(KEY_COLOR, self.accent if is_bot else "#C9C9CF", a)
            line = f"{'YOU' if not is_bot else who.upper()}: {text}".replace("\n", " ")
            line = fit_text(line, (FONT, 8), (w - 8 - 30) - 16)
            cv.create_text(16, y, text=line, anchor="nw", font=(FONT, 8), fill=color)
            y += 22
        self.scroll_lines = len(lines)
        # scroll arrows on the right edge
        ax = w - 22
        for bid, glyph, yy in (("scroll_up", "▲", y0 + 14), ("scroll_down", "▼", y1 - 14)):
            cv.create_text(ax, yy, text=glyph, font=(FONT, 7), fill=hex_lerp(KEY_COLOR, "#8A8A90", a))
            self.buttons.append(Button(bid, ax - 8, yy - 8, ax + 8, yy + 8))

    # ---- hit testing ---------------------------------------------------------
    def button_at(self, x: float, y: float):
        for b in self.buttons:
            if b.hit(x, y):
                return b.id
        return None

    def over_lcd(self, x: float, y: float) -> bool:
        return self.hover_alpha > 0.5 and y > self.size[1] - self.STRIP_H

    # hooks the window calls
    @property
    def lcd_total_lines(self) -> int:
        return self.scroll_lines

    class _LcdCompat:
        @staticmethod
        def max_scroll(total: int, visible: int = 3) -> int:
            return max(0, total - visible)

    lcd = _LcdCompat()
