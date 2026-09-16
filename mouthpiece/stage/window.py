"""The stage: a frameless, always-on-top panel that appears while in a room.

Tk must own the thread it was created on, so the stage runs the process's main thread
(pystray is started detached). It never touches the session directly: every frame it
pulls a plain-dict snapshot from the app (state, levels, captions) and paints.
"""
from __future__ import annotations

import json
import logging
import time
import tkinter as tk
from typing import Callable, Optional

from .kitt import SKINS, KittSkin

log = logging.getLogger("mouthpiece.stage")

DEFAULT_W, DEFAULT_H = 340, 300
FPS = 30

Snapshot = dict  # {state, muted, spk_level, mic_level, bot_display, accent, skin, captions:[(who,text,final)], visible}


class StageWindow:
    def __init__(self, feed: Callable[[], Snapshot], *, actions: Optional[dict] = None, menu_items=None, on_close=None,
                 config_path=None, config_raw: Optional[dict] = None) -> None:
        self.feed = feed
        self.actions = actions or {}      # button id -> callable
        self.hover: Optional[str] = None
        self.pressed: Optional[str] = None
        self.scroll = 0                   # LCD lines hidden below the view (0 = newest)
        self._caption_count = 0
        self.menu_items = menu_items or []
        self.on_close = on_close
        self.config_path = config_path
        self.config_raw = config_raw if config_raw is not None else {}
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-alpha", 0.96)
        except tk.TclError:
            pass
        self.root.configure(bg="#0A0406")
        self.w, self.h = DEFAULT_W, DEFAULT_H
        self.cv = tk.Canvas(self.root, width=self.w, height=self.h, highlightthickness=0, bd=0, bg="#0A0406")
        self.cv.pack()
        self.skin = KittSkin()
        self._skin_name = "kitt"
        self._visible = False
        self._drag = None
        self._last = time.monotonic()
        self._place()
        self.cv.bind("<ButtonPress-1>", self._press)
        self.cv.bind("<B1-Motion>", self._motion)
        self.cv.bind("<ButtonRelease-1>", self._release)
        self.cv.bind("<Button-3>", self._popup)
        self.cv.bind("<Motion>", self._hover)
        self.cv.bind("<Leave>", lambda e: self._set_hover(None))
        self.cv.bind("<MouseWheel>", self._wheel)
        self.root.after(int(1000 / FPS), self._tick)

    # ---- placement ------------------------------------------------------
    def _place(self) -> None:
        pos = self.config_raw.get("stage_pos")
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        if isinstance(pos, list) and len(pos) == 2:
            x, y = int(pos[0]), int(pos[1])
            x = max(0, min(x, sw - self.w)); y = max(0, min(y, sh - self.h))
        else:
            x, y = sw - self.w - 24, sh - self.h - 72   # bottom-right, above the taskbar
        self.root.geometry(f"{self.w}x{self.h}+{x}+{y}")

    def _save_pos(self) -> None:
        if not self.config_path:
            return
        try:
            self.config_raw["stage_pos"] = [self.root.winfo_x(), self.root.winfo_y()]
            self.config_path.write_text(json.dumps(self.config_raw, indent=2), encoding="utf-8")
        except Exception:
            log.debug("save stage pos failed", exc_info=True)

    # ---- mouse ----------------------------------------------------------
    def _set_hover(self, bid: Optional[str]) -> None:
        if bid != self.hover:
            self.hover = bid
            self.cv.configure(cursor="hand2" if bid else "")

    def _hover(self, e) -> None:
        if self._drag is None:
            self._set_hover(self.skin.button_at(e.x, e.y))

    def _wheel(self, e) -> None:
        if self.skin.over_lcd(e.x, e.y) or self.skin.button_at(e.x, e.y) in ("scroll_up", "scroll_down"):
            self._scroll_by(1 if e.delta > 0 else -1)

    def _scroll_by(self, n: int) -> None:
        from .kitt import LCD_LINES
        mx = self.skin.lcd.max_scroll(self.skin.lcd_total_lines, LCD_LINES)
        self.scroll = max(0, min(mx, self.scroll + n))

    def _press(self, e) -> None:
        bid = self.skin.button_at(e.x, e.y)
        if bid:
            self.pressed = bid
            return
        self._drag = (e.x_root, e.y_root, self.root.winfo_x(), self.root.winfo_y(), False)

    def _motion(self, e) -> None:
        if not self._drag:
            return
        x0, y0, wx, wy, _ = self._drag
        dx, dy = e.x_root - x0, e.y_root - y0
        if abs(dx) > 3 or abs(dy) > 3:
            self._drag = (x0, y0, wx, wy, True)
            self.root.geometry(f"+{wx + dx}+{wy + dy}")

    def _release(self, e) -> None:
        if self.pressed:
            bid, self.pressed = self.pressed, None
            if self.skin.button_at(e.x, e.y) == bid:
                if bid == "scroll_up":
                    self._scroll_by(1)
                    return
                if bid == "scroll_down":
                    self._scroll_by(-1)
                    return
                fn = self.actions.get(bid)
                if fn:
                    try:
                        fn()
                    except Exception:
                        log.exception("button %s failed", bid)
            return
        if not self._drag:
            return
        moved = self._drag[4]
        self._drag = None
        if moved:
            self._save_pos()

    def _popup(self, e) -> None:
        m = tk.Menu(self.root, tearoff=0, bg="#12080A", fg="#F2F0EE", activebackground="#5A1018",
                    activeforeground="#ffffff", bd=0)
        for label, fn in self.menu_items:
            if label is None:
                m.add_separator()
            else:
                m.add_command(label=label() if callable(label) else label, command=fn)
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    # ---- frame loop -----------------------------------------------------
    def _tick(self) -> None:
        try:
            snap = self.feed()
            self._frame(snap)
        except Exception:
            log.exception("stage frame failed")
        self.root.after(int(1000 / FPS), self._tick)

    def _frame(self, snap: Snapshot) -> None:
        want = bool(snap.get("visible"))
        if want and not self._visible:
            self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", True)
            self._visible = True
        elif not want and self._visible:
            self.root.withdraw()
            self._visible = False
        if not self._visible:
            return
        skin_name = snap.get("skin") or "kitt"
        if skin_name != self._skin_name:
            self.skin = SKINS.get(skin_name, KittSkin)(snap.get("accent") or "#FF1A1A")
            self._skin_name = skin_name
            sw, sh = getattr(self.skin, "size", (DEFAULT_W, DEFAULT_H))
            if (sw, sh) != (self.w, self.h):
                self.w, self.h = sw, sh
                self.cv.configure(width=sw, height=sh)
                self.root.geometry(f"{sw}x{sh}")
        now = time.monotonic()
        dt, self._last = now - self._last, now
        self.skin.step(snap.get("state", "off"), float(snap.get("spk_level", 0.0)), float(snap.get("mic_level", 0.0)),
                       min(dt, 0.1))
        captions = snap.get("captions") or []
        n = len(captions)
        if n != self._caption_count:
            # new line arrived: stay pinned to the newest unless the user scrolled up
            self._caption_count = n
            if n == 0:
                self.scroll = 0
        self.skin.paint(self.cv, self.w, self.h, state=snap.get("state", "off"), muted=bool(snap.get("muted")),
                        bot_display=snap.get("bot_display", "BOT"), captions=captions,
                        hover=self.hover, pressed=self.pressed, scroll=self.scroll)

    # ---- lifecycle ------------------------------------------------------
    def mainloop(self) -> None:
        self.root.mainloop()

    def close(self) -> None:
        """Thread-safe request to end the Tk loop."""
        try:
            self.root.after(0, self.root.destroy)
        except Exception:
            pass
