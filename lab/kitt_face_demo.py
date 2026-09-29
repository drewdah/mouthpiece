"""Drive the KITT face on the real Turing with a scripted state cycle + fake voice.

Close InfoPanel first (it holds the COM port).
    .venv\\Scripts\\python.exe lab\\kitt_face_demo.py [seconds]
"""
import logging
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mouthpiece.display.kitt import KittFace  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
RUN = float(sys.argv[1]) if len(sys.argv) > 1 else 40

SCRIPT = [("off", 4), ("in room", 4), ("listening", 4), ("thinking", 5), ("speaking", 10), ("in room", 3),
          ("error", 3), ("in room", 3)]


class FakeAudio:
    """Syllable-ish envelope: ~4 Hz bursts on a steady TTS loudness."""
    speaker_peak = 0.0

    @property
    def speaker_level(self):
        t = time.monotonic()
        return 0.12 * max(0.0, math.sin(t * 2 * math.pi * 4)) * (0.6 + 0.4 * math.sin(t * 1.3)) + 0.005


audio = FakeAudio()
t_start = time.monotonic()


def source():
    t = (time.monotonic() - t_start) % sum(d for _, d in SCRIPT)
    for state, d in SCRIPT:
        if t < d:
            break
        t -= d
    audio.speaker_peak = audio.speaker_level
    return {"state": state, "muted": state == "thinking", "audio": audio}


face = KittFace({"port": "AUTO", "brightness": 50}, source)

# Instrument flush: bytes and wall time per frame.
frames, orig = [], face.face.flush


def timed_flush(screen, budget=None):
    t0 = time.monotonic()
    sent, n = orig(screen, budget)
    frames.append((sent, n, time.monotonic() - t0))
    return sent, n


face.face.flush = timed_flush
face.start()
time.sleep(RUN)
face.stop()

steady = frames[2:]
if steady:
    busy = [f for f in steady if f[0]]
    print(f"frames {len(steady)} over {RUN:.0f}s -> {len(steady) / RUN:.1f} fps")
    print(f"bytes/frame avg {sum(f[0] for f in steady) / len(steady):.0f}, max {max(f[0] for f in steady)}; "
          f"budget {face.budget}")
    print(f"flush ms avg {1000 * sum(f[2] for f in steady) / len(steady):.1f}, max {1000 * max(f[2] for f in steady):.0f}")
