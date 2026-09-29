"""Drive the desk panels on real hardware: each bot in turn, through a scripted
state cycle with a fake voice, swapping faces the way Mouthpiece does.

Mouthpiece must not be holding the port(s): quit it or turn Faces > Desk panel off.
    .venv\\Scripts\\python.exe lab\\panel_demo.py [--panel 1-10.1.4:landscape ...] [--bots baymax,wheatley] [--secs 30]
Without --panel it uses the panels in config.json's turing section.
"""
import argparse
import json
import logging
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mouthpiece.display.host import DeskPanels  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

SCRIPT = [("off", 3), ("joining", 3), ("in room", 4), ("listening", 4), ("thinking", 5), ("speaking", 8),
          ("in room", 2), ("error", 3)]


class FakeAudio:
    """Syllable-ish envelope: ~4 Hz bursts on a steady TTS loudness, with phrase pauses."""
    speaker_peak = 0.0

    @property
    def speaker_level(self):
        t = time.monotonic()
        if t % 2.2 > 1.7:
            return 0.002
        return 0.12 * max(0.0, math.sin(t * 2 * math.pi * 3.7)) * (0.6 + 0.4 * math.sin(t * 1.3)) + 0.005


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", action="append", help="PORT:orientation, e.g. 1-10.1.4:landscape")
    ap.add_argument("--bots", default="kitt,baymax,wheatley")
    ap.add_argument("--secs", type=float, default=sum(d for _, d in SCRIPT))
    ap.add_argument("--brightness", type=int, default=50)
    a = ap.parse_args()

    if a.panel:
        cfg = {"brightness": a.brightness,
               "panels": [dict(zip(("port", "orientation"), p.rsplit(":", 1))) for p in a.panel]}
    else:
        cfg = json.loads((Path(__file__).resolve().parent.parent / "config.json").read_text())["turing"]

    bots = a.bots.split(",")
    audio = FakeAudio()
    t0 = time.monotonic()

    def bot():
        return bots[int((time.monotonic() - t0) // a.secs) % len(bots)]

    def source():
        t = (time.monotonic() - t0) % a.secs % sum(d for _, d in SCRIPT)
        for state, d in SCRIPT:
            if t < d:
                break
            t -= d
        audio.speaker_peak = audio.speaker_level
        return {"state": state, "muted": state == "listening" and bot() == "kitt", "audio": audio}

    panels = DeskPanels(cfg, source, bot)
    panels.start()
    try:
        time.sleep(a.secs * len(bots) + 8)
    except KeyboardInterrupt:
        pass
    panels.stop()


if __name__ == "__main__":
    main()
