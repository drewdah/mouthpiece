"""Spike runner: join the bot's room from the terminal, print events, leave on Enter or after --seconds."""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import threading

# Windows consoles default to cp1252; transcripts can carry emoji.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from mouthpiece.config import Config
from mouthpiece.session import VoiceSession


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bot", default=None)
    ap.add_argument("--seconds", type=float, default=0, help="auto-leave after N seconds (0 = wait for Enter)")
    ap.add_argument("--say", default=None, help="send a typed turn after joining")
    ap.add_argument("--mute", action="store_true", help="join with the mic muted")
    ap.add_argument("--wav", default=None, help="feed this 48k mono int16 WAV as the mic once the agent is ready")
    ap.add_argument("--force", action="store_true", help="test even if another human is already in the room")
    ap.add_argument("-v", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.v else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("livekit").setLevel(logging.WARNING)

    cfg = Config.load()
    # Never collide with the tray: LiveKit kicks the older participant on a duplicate identity.
    if not cfg.identity.endswith("-spike"):
        cfg.identity += "-spike"
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
    # A second human identity in the room opens a second Hermes session; if the model asks that
    # session a clarifying question and the spike leaves, the whole room wedges on the unanswered
    # clarify (happened 2026-09-15). Never test in a room someone is using.
    humans = [p.identity for p in s.room.remote_participants.values() if not p.identity.startswith("hermes-")]
    if humans and not a.force:
        print(f"[abort] room already has {humans}; not testing in an occupied room (use --force)", flush=True)
        await s.leave()
        return 3
    if a.mute:
        await s.set_muted(True)
    if a.say:
        await asyncio.sleep(1)
        await s.send_text(a.say)
    if a.wav:
        import wave
        import numpy as np
        with wave.open(a.wav, "rb") as w:
            assert w.getframerate() == 48000 and w.getnchannels() == 1 and w.getsampwidth() == 2, "need 48k mono 16-bit"
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        await asyncio.wait_for(s.agent_ready.wait(), timeout=15)
        await asyncio.sleep(1.5)  # let the agent's VAD calibrate on silence first
        print(f"[inject] {len(pcm)/48000:.1f}s of speech from {a.wav}", flush=True)
        s.audio.inject = pcm

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
