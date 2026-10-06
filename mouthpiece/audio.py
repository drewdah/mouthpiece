"""Audio I/O: Windows default (or configured) devices <-> LiveKit frames.

Capture: sounddevice InputStream (48 kHz mono int16, 10 ms blocks) -> APM (AEC/NS)
         -> rtc.AudioSource (published as the mic track).
Playback: remote agent AudioStream frames -> ring buffer -> sounddevice OutputStream.
          Each played block is fed to the APM reverse stream so echo cancellation
          knows what the speakers emitted (matters for the open-speaker case).
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from typing import Optional

import numpy as np
import sounddevice as sd
from livekit import rtc

log = logging.getLogger("mouthpiece.audio")

RATE = 48_000
CHANNELS = 1
FRAME = RATE // 100  # 10 ms = 480 samples, what the APM wants

# Backpressure. Both directions are fed by a real-time clock and drained by
# something that can stall (the event loop / LiveKit publish for the mic, the
# output device for the speaker). Unbounded, a stall turned into tens of GB of
# queued frames and a GC death spiral; bounded, a stall just drops audio.
MAX_MIC_INFLIGHT = 20                # capture_frame calls queued on the loop (200 ms)
MAX_PLAY_SAMPLES = RATE * 3          # agent audio buffered for the speaker (3 s)


def _rms(x: np.ndarray) -> float:
    if x.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(x.astype(np.float32) ** 2)) / 32768.0)


class AudioIO:
    def __init__(self, loop: asyncio.AbstractEventLoop, *, input_device=None, output_device=None,
                 echo_cancellation=True, noise_suppression=True, auto_gain_control=False) -> None:
        self.loop = loop
        self.input_device = input_device
        self.output_device = output_device
        self.source = rtc.AudioSource(RATE, CHANNELS)
        self.apm = rtc.AudioProcessingModule(
            echo_cancellation=echo_cancellation,
            noise_suppression=noise_suppression,
            high_pass_filter=True,
            auto_gain_control=auto_gain_control,
        )
        self.muted = False
        # Echo guard: when True, the mic is silenced toward the agent for the whole of the bot's
        # turn: while the agent says it is speaking, while its audio is still queued or audible,
        # and for a tail after that. The tail covers the output path (e.g. Voicemeeter) and the
        # room: with only a short tail after the last loud frame, the bot's last words reached
        # the mic after the guard opened, and it answered itself. Kills barge-in, but also kills
        # the bot hearing itself.
        self.gate_while_playing = True
        self.gate_tail_s = 1.2
        self.agent_speaking = False   # set by the session from the agent's speaking state
        self.gated = False        # True while the guard is currently silencing the mic
        self.mic_level = 0.0      # 0..1 RMS of what we send
        self.speaker_level = 0.0  # 0..1 RMS of what we play
        self.speaker_peak = 0.0   # max speaker_level since a reader last reset it (desk face)
        self._play = deque()      # int16 numpy chunks from the agent
        self._play_samples = 0    # total samples in _play
        self._play_lock = threading.Lock()
        self._mic_inflight = 0    # capture_frame calls not yet finished on the loop
        self._mic_lock = threading.Lock()
        self._mic_dropped = 0
        self._play_dropped = 0
        self._next_drop_log = 0.0
        self._carry = np.zeros(0, dtype=np.int16)
        self._in: Optional[sd.InputStream] = None
        self._out: Optional[sd.OutputStream] = None
        self._underruns = 0
        self._captured = 0
        self._last_play_ts = 0.0
        # Test hook: when set, this int16 array is fed as the mic instead of the device (spike --wav).
        self.inject: Optional[np.ndarray] = None
        self._inject_pos = 0

    # ---- lifecycle -------------------------------------------------------
    def start(self) -> None:
        self._in = sd.InputStream(samplerate=RATE, channels=CHANNELS, dtype="int16", blocksize=FRAME,
                                  device=self.input_device, callback=self._on_input)
        self._out = sd.OutputStream(samplerate=RATE, channels=CHANNELS, dtype="int16", blocksize=FRAME,
                                    device=self.output_device, callback=self._on_output)
        self._in.start()
        self._out.start()
        log.info("audio started in=%s out=%s", self._name(self._in.device, "input"), self._name(self._out.device, "output"))

    def stop(self) -> None:
        for s in (self._in, self._out):
            if s is not None:
                try:
                    s.stop(); s.close()
                except Exception:
                    pass
        self._in = self._out = None
        with self._play_lock:
            self._play.clear()
            self._play_samples = 0
        log.info("audio stopped (captured=%d frames, underruns=%d, dropped mic=%d play=%d)",
                 self._captured, self._underruns, self._mic_dropped, self._play_dropped)

    def _drop_warning(self) -> None:
        now = time.monotonic()
        if now >= self._next_drop_log:
            self._next_drop_log = now + 30
            log.warning("audio falling behind: dropped mic=%d play=%d frames so far (mic in flight %d, play queued %.1f s)",
                        self._mic_dropped, self._play_dropped, self._mic_inflight, self._play_samples / RATE)

    @staticmethod
    def _name(dev, kind) -> str:
        try:
            return sd.query_devices(dev, kind)["name"]
        except Exception:
            return str(dev)

    # ---- playback feed (called from asyncio) ------------------------------
    def play_frame(self, frame: rtc.AudioFrame) -> None:
        pcm = np.frombuffer(frame.data, dtype=np.int16)
        if frame.num_channels > 1:
            pcm = pcm.reshape(-1, frame.num_channels)[:, 0]
        if frame.sample_rate != RATE:
            # AudioStream is asked for 48k; this is only a safety net.
            idx = np.linspace(0, len(pcm) - 1, int(len(pcm) * RATE / frame.sample_rate)).astype(np.int64)
            pcm = pcm[idx]
        dropped = 0
        with self._play_lock:
            self._play.append(pcm.copy())
            self._play_samples += len(pcm)
            while self._play_samples > MAX_PLAY_SAMPLES:     # speaker stalled: drop the oldest
                self._play_samples -= len(self._play.popleft())
                dropped += 1
        if dropped:
            self._play_dropped += dropped
            self._drop_warning()

    def clear_playback(self) -> None:
        with self._play_lock:
            self._play.clear()
            self._play_samples = 0
            self._carry = np.zeros(0, dtype=np.int16)

    def queued_ms(self) -> float:
        with self._play_lock:
            n = self._play_samples + len(self._carry)
        return n * 1000.0 / RATE

    # ---- sounddevice callbacks (audio threads) ----------------------------
    def _on_input(self, indata, frames, time_info, status) -> None:
        if status:
            log.debug("input status: %s", status)
        pcm = np.ascontiguousarray(indata[:, 0], dtype=np.int16)
        if self.inject is not None:
            end = self._inject_pos + frames
            chunk = self.inject[self._inject_pos:end]
            pcm = np.zeros(frames, dtype=np.int16)
            pcm[:len(chunk)] = chunk
            self._inject_pos = end
            if self._inject_pos >= len(self.inject):
                self.inject = None
        frame = rtc.AudioFrame(data=pcm.tobytes(), sample_rate=RATE, num_channels=CHANNELS, samples_per_channel=len(pcm))
        try:
            self.apm.process_stream(frame)
        except Exception as e:  # never let the audio thread die
            log.debug("apm process_stream: %s", e)
        playing = self.gate_while_playing and self.guarding(time.monotonic())
        self.gated = playing and not self.muted
        if self.muted or playing:
            frame = rtc.AudioFrame(data=bytes(len(pcm) * 2), sample_rate=RATE, num_channels=CHANNELS, samples_per_channel=len(pcm))
            self.mic_level = 0.0
        else:
            self.mic_level = _rms(np.frombuffer(frame.data, dtype=np.int16))
        self._captured += 1
        with self._mic_lock:
            full = self._mic_inflight >= MAX_MIC_INFLIGHT
            if not full:
                self._mic_inflight += 1
        if full:                                            # loop/publish stalled: drop, don't queue
            self._mic_dropped += 1
            self._drop_warning()
            return
        fut = asyncio.run_coroutine_threadsafe(self.source.capture_frame(frame), self.loop)
        fut.add_done_callback(self._mic_done)

    def guarding(self, now: float) -> bool:
        """The echo guard's verdict (ignoring gate_while_playing): the bot's turn isn't over yet."""
        if self.agent_speaking or self._play_samples > 0 or len(self._carry):
            self._last_play_ts = max(self._last_play_ts, now)
            return True
        return (now - self._last_play_ts) < self.gate_tail_s

    def _mic_done(self, fut) -> None:
        with self._mic_lock:
            self._mic_inflight -= 1
        if not fut.cancelled() and fut.exception() is not None:
            log.debug("capture_frame: %s", fut.exception())

    def _on_output(self, outdata, frames, time_info, status) -> None:
        need = frames
        out = np.zeros(need, dtype=np.int16)
        pos = 0
        with self._play_lock:
            if len(self._carry):
                take = min(need, len(self._carry))
                out[:take] = self._carry[:take]
                self._carry = self._carry[take:]
                pos = take
            while pos < need and self._play:
                chunk = self._play.popleft()
                self._play_samples -= len(chunk)
                take = min(need - pos, len(chunk))
                out[pos:pos + take] = chunk[:take]
                if take < len(chunk):
                    self._carry = chunk[take:]
                pos += take
        if pos < need and pos > 0:
            self._underruns += 1
        outdata[:, 0] = out
        self.speaker_level = _rms(out)
        self.speaker_peak = max(self.speaker_peak, self.speaker_level)
        # The agent's track streams silence continuously, so "frames arrived" is not
        # "the bot is talking". Only real energy counts as playback for the echo guard.
        if pos > 0 and self.speaker_level > 0.004:
            self._last_play_ts = time.monotonic()
        # Tell the echo canceller what the speakers just played.
        try:
            rev = rtc.AudioFrame(data=out.tobytes(), sample_rate=RATE, num_channels=CHANNELS, samples_per_channel=need)
            self.apm.process_reverse_stream(rev)
        except Exception as e:
            log.debug("apm reverse: %s", e)


def list_devices() -> list[dict]:
    """Devices with their host API name, for the tray picker."""
    apis = sd.query_hostapis()
    out = []
    for i, d in enumerate(sd.query_devices()):
        out.append({
            "index": i,
            "name": d["name"],
            "hostapi": apis[d["hostapi"]]["name"],
            "in": d["max_input_channels"],
            "out": d["max_output_channels"],
        })
    return out
