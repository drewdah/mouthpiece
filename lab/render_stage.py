"""Render an entity skin through its states to a contact sheet, on a fake clock.

    .venv\\Scripts\\python lab\\render_stage.py baymax
    .venv\\Scripts\\python lab\\render_stage.py wheatley

Writes lab/stage_<skin>_sheet.png. The skin's see-through key colour is swapped for grey so
the silhouette edges are visible. Opens a small window on screen for a moment per frame
(ImageGrab needs it on screen); don't move the mouse over it while it runs.
"""
from __future__ import annotations

import sys
import tkinter as tk
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageGrab  # noqa: E402

from mouthpiece.stage import baymax, entity, wheatley  # noqa: E402

KEY = (1, 2, 3)
BG = (107, 114, 128)
FPS = 30

LONG = ("Of course. Here is what I found. The kitchen lights have been on since this morning, the back door "
        "is locked, and the thermostat is holding at sixty eight degrees. Kira's calendar shows a lab until six, "
        "and your dentist appointment moved to Thursday at ten. On a scale of one to ten, how would you rate "
        "your stress about that? I can remind you on Wednesday evening, and again an hour before you need "
        "to leave, if that would help.")
SHORT = "Hello. I am Baymax, your personal healthcare companion."


class Clock:
    now = 1000.0


CLOCK = Clock()
FAKE_TIME = types.SimpleNamespace(monotonic=lambda: CLOCK.now, time=lambda: CLOCK.now)
for mod in (entity, baymax, wheatley):
    mod.time = FAKE_TIME


def caption(text, seq=1):
    return [("Baymax", text, True, "reply", 0, seq)]


# (label, state, seconds to run first, caption text, force a blink N seconds before the grab)
SCENES = [
    ("idle", "idle", 1.0, None, None),
    ("listening", "listening", 1.5, None, None),
    ("speaking (short)", "speaking", 1.0, SHORT, None),
    ("speaking (long reply)", "speaking", 1.0, LONG, None),
    ("blink: closing", "speaking", 1.0, SHORT, 0.05),
    ("blink: shut", "speaking", 1.0, SHORT, 0.10),
    ("blink: opening", "speaking", 1.0, SHORT, 0.25),
    ("thinking 0.4 s", "thinking", 0.4, None, None),
    ("thinking 2 s", "thinking", 2.0, None, None),
    ("thinking 3.3 s", "thinking", 3.3, None, None),
]


def render(skin_cls, name):
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    w, h = skin_cls.size
    root.geometry(f"{w}x{h}+40+40")
    cv = tk.Canvas(root, width=w, height=h, highlightthickness=0, bd=0, bg="#010203")
    cv.pack()
    root.update()
    frames = []
    for label, state, secs, text, blink_before in SCENES:
        CLOCK.now = 1000.0
        skin = skin_cls()
        skin.step("idle", 0.0, 0.0, 1 / FPS)        # settle
        n = int(secs * FPS)
        for i in range(n):
            CLOCK.now += 1 / FPS
            if blink_before is not None and abs((n - i) / FPS - blink_before) < 0.5 / FPS:
                skin._blink_until = CLOCK.now + 0.12   # the base class's own blink trigger
            level = 0.35 + 0.25 * ((i % 7) / 7) if state == "speaking" else 0.0
            skin.step(state, level / 16, 0.0, 1 / FPS)
        skin.paint(cv, w, h, state=state, muted=False, bot_display=name.upper(),
                   captions=caption(text) if text else [], response_seq=1)
        root.update()
        x, y = cv.winfo_rootx(), cv.winfo_rooty()
        img = ImageGrab.grab(bbox=(x, y, x + w, y + h)).convert("RGB")
        px = img.load()
        for yy in range(h):
            for xx in range(w):
                if px[xx, yy] == KEY:
                    px[xx, yy] = BG
        frames.append((label, img))
    root.destroy()
    cols = 5
    rows = (len(frames) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (w + 10) + 10, rows * (h + 34) + 10), (40, 42, 48))
    d = ImageDraw.Draw(sheet)
    for i, (label, img) in enumerate(frames):
        cx, cy = 10 + (i % cols) * (w + 10), 10 + (i // cols) * (h + 34)
        d.text((cx + 4, cy + 4), label, fill=(235, 235, 240))
        sheet.paste(img, (cx, cy + 22))
    out = ROOT / "lab" / f"stage_{name}_sheet.png"
    sheet.save(out)
    print(out)


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "baymax"
    render({"baymax": baymax.BaymaxSkin, "wheatley": wheatley.WheatleySkin}[which], which)
