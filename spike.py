"""Spike runner: join the bot's room from the terminal, print events, leave on Enter or after --seconds."""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import threading

from mouthpiece.config import Config
from mouthpiece.session import VoiceSession


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bot", default=None)
    ap.add_argument("--seconds", type=float, default=0, help="auto-leave after N seconds (0 = wait for Enter)")
    ap.add_argument("--say", default=None, help="send a typed turn after joining")
    ap.add_argument("--mute", action="store_true", help="join with the mic muted")
    ap.add_argument("-v", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.v else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("livekit").setLevel(logging.WARNING)

    cfg = Config.load()
    bot = cfg.bot(a.bot)
    loop = asyncio.get_running_loop()
    s = VoiceSession(cfg, bot, loop)

    def show(kind, data):
        if kind == "state":
            print(f"[state] {data['state']} {data.get('error', '')}", flush=True)
        elif kind == "transcript":
            print(f"[{data['who']}] {data['text']}", flush=True)
        elif kind in ("joined", "left", "participant", "muted", "agent_error"):
            print(f"[{kind}] {data}", flush=True)

    s.on(show)
    await s.join()
    if s.state.value == "error":
        return 1
    if a.mute:
        await s.set_muted(True)
    if a.say:
        await asyncio.sleep(1)
        await s.send_text(a.say)

    stop = asyncio.Event()
    if a.seconds > 0:
        loop.call_later(a.seconds, stop.set)
    else:
        print("In room. Press Enter to leave.", flush=True)
        threading.Thread(target=lambda: (sys.stdin.readline(), loop.call_soon_threadsafe(stop.set)),
                         daemon=True).start()

    async def meter():
        while not stop.is_set():
            await asyncio.sleep(1.0)
            if s.audio:
                print(f"   mic={s.audio.mic_level:.3f} spk={s.audio.speaker_level:.3f} "
                      f"queued={s.audio.queued_ms():.0f}ms state={s.state.value}", flush=True)

    mt = asyncio.create_task(meter())
    await stop.wait()
    mt.cancel()
    await s.leave()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
