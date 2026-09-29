r"""Render desk-panel faces without hardware: a contact sheet of states per bot
and orientation, plus the byte cost each frame would put on the link.

    .venv\Scripts\python.exe lab\panel_preview.py [kitt baymax wheatley] [--gif]
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mouthpiece.display.faces import face_class  # noqa: E402

REGISTRY = "//silo.local/mysticspark/Projects/house-presence/cast"
OUT = Path(__file__).resolve().parent / "panel"
STATES = [("off", 0.0), ("in room", 0.0), ("listening", 0.0), ("thinking", 0.0),
          ("speaking", 0.8), ("joining", 0.0), ("error", 0.0)]


class FakeStats:
    cpu, gpu, gpu_temp, ram = 34.0, 52.0, 58.0, 61.0

    def poll(self):
        pass


class Meter:
    """Counts what a flush would send."""
    def __init__(self):
        self.bytes = 0

    def blit(self, img, x, y):
        self.bytes += img.width * img.height * 2


def sheet(bot: str, orientation: str) -> Path:
    face = face_class(bot)({"registry": REGISTRY}, lambda: {},
                           orientation=orientation)
    face.stats = FakeStats()
    face.face = face.build()
    shots = []
    for state, level in STATES:
        t = 10.0
        # run a second of frames so animations settle (speaking fills the trace)
        for i in range(24):
            face.update(state, state == "listening" and False, level * (0.5 + 0.5 * ((i % 3) == 0)), t + i / 12)
        img = face.face.render()
        shots.append((state, img))
    muted = face.preview("in room", muted=True, now=40.0)
    shots.append(("in room, muted", muted))
    w, h = shots[0][1].size
    cols = 4
    rows = (len(shots) + cols - 1) // cols
    pad, label = 12, 22
    out = Image.new("RGB", (cols * (w + pad) + pad, rows * (h + label + pad) + pad), (40, 42, 48))
    d = ImageDraw.Draw(out)
    f = ImageFont.truetype(r"C:\Windows\Fonts\segoeui.ttf", 15)
    for i, (name, img) in enumerate(shots):
        x = pad + (i % cols) * (w + pad)
        y = pad + (i // cols) * (h + label + pad)
        d.text((x, y), name, fill=(220, 220, 220), font=f)
        out.paste(img, (x, y + label))
    OUT.mkdir(exist_ok=True)
    path = OUT / f"{bot}_{orientation}.png"
    out.save(path)
    return path


def costs(bot: str, orientation: str, seconds: float = 30) -> str:
    """Simulate a scripted session against the budget: bytes per frame."""
    face = face_class(bot)({}, lambda: {}, orientation=orientation)
    face.stats = FakeStats()
    face.face = face.build()
    face.face.invalidate(face.face.background)
    script = [("in room", 4), ("listening", 4), ("thinking", 5), ("speaking", 10), ("error", 3), ("in room", 4)]
    import math
    per_state, t = {}, 0.0
    for state, dur in script:
        n = int(dur * 12)
        for i in range(n):
            lvl = 0.8 * max(0.0, math.sin(t * 2 * math.pi * 4)) if state == "speaking" else 0.0
            face.update(state, False, lvl, t)
            m = Meter()
            face.face.flush(m, face.budget)
            per_state.setdefault(state, []).append(m.bytes)
            t += 1 / 12
    lines = [f"{bot} {orientation}: budget {face.budget} B/frame"]
    for s, v in per_state.items():
        backlog = len(face.face.dirty())
        lines.append(f"  {s:10s} avg {sum(v) / len(v):7.0f}  max {max(v):6d}")
    return "\n".join(lines)


def main() -> None:
    bots = [a for a in sys.argv[1:] if not a.startswith("--")] or ["kitt", "baymax", "wheatley"]
    for bot in bots:
        for o in ("portrait", "landscape"):
            print(sheet(bot, o))
            print(costs(bot, o))
            if "--gif" in sys.argv:
                print(gif(bot, o))


class Glass:
    """A fake panel: applies blits to an image, like the real glass would show."""
    def __init__(self, img):
        self.img = img.copy()

    def blit(self, img, x, y):
        self.img.paste(img, (x, y))


def gif(bot: str, orientation: str) -> Path:
    import math
    face = face_class(bot)({"registry": REGISTRY}, lambda: {},
                           orientation=orientation)
    face.stats = FakeStats()
    face.face = face.build()
    glass = Glass(face.face.background)
    face.face.invalidate(face.face.background)
    script = [("off", 1.5), ("joining", 1.5), ("in room", 3), ("listening", 3), ("thinking", 4), ("speaking", 6),
              ("error", 2.5), ("in room", 2)]
    frames, t = [], 0.0
    for state, dur in script:
        for i in range(int(dur * 12)):
            # syllable-ish voice: ~4 Hz bursts with pauses between phrases
            lvl = 0.0
            if state == "speaking" and (t % 2.2) < 1.7:
                lvl = max(0.0, math.sin(t * 2 * math.pi * 3.7)) * (0.6 + 0.4 * math.sin(t * 1.3))
            face.update(state, False, lvl, t)
            face.face.flush(glass, face.budget)
            f = glass.img.copy()
            ImageDraw.Draw(f).text((6, f.height - 16), state, fill=(120, 120, 120),
                                   font=ImageFont.truetype(r"C:\Windows\Fonts\segoeui.ttf", 11))
            frames.append(f)
            t += 1 / 12
    path = OUT / f"{bot}_{orientation}.gif"
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=83, loop=0, optimize=True)
    return path


if __name__ == "__main__":
    main()
