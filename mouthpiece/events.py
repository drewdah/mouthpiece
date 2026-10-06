"""Live event stream for local clients (GET /events on the trigger server, Server-Sent Events).

The hub lives on the App, not the session, so a client's stream survives bot switches
(App.session is replaced on every switch). Session listeners fire on the asyncio thread,
the level sampler on its own thread, and each SSE client is served by an HTTP handler
thread; everything meets in per-client queues guarded by one condition variable.

Events (data is one line of JSON):
  status       the full /status dict; first frame on connect, then on state/bot/muted/error change
  transcript   {bot, who: "user"|"agent", id, text, final, seq, kind, ts}; text is cumulative
               for the line, id is stable across its partials and final, ts is epoch ms
  level        {bot, mic, spk} 0..1 RMS, ~20 Hz while in a room; each is the max since the
               last level event so short syllables register
  interrupted  {bot}   the agent's reply was cut off (barge-in or /stop)
  agent        {bot, identity, ready: true}   the agent participant arrived

A slow client's queue is bounded: when full, its oldest level event goes first; if there
is none to drop, the client is closed (its handler ends the response).
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from typing import Callable, Optional

log = logging.getLogger("mouthpiece.events")

QUEUE_MAX = 256
LEVEL_HZ = 20
SAMPLE_HZ = 100            # speaker_level updates every 10 ms; sample at that rate, publish the max
STATUS_POLL_S = 0.25       # belt and braces for status changes that raise no session event
INTERRUPT_DEDUPE_S = 1.0   # /stop emits locally, then the agent's buffer.cleared follows
STATUS_KEYS = ("state", "bot", "muted", "error")
IDLE_STATES = ("off", "joining", "error")


def frame(name: str, data: dict) -> bytes:
    return f"event: {name}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode("utf-8")


class Client:
    """One SSE subscriber: a bounded queue of encoded frames."""

    def __init__(self, hub: "EventHub", maxlen: int) -> None:
        self._hub = hub
        self._q: deque[tuple[str, bytes]] = deque()
        self._max = maxlen
        self.closed = False

    def _put(self, name: str, data: bytes) -> None:   # hub lock held
        if self.closed:
            return
        if len(self._q) >= self._max:
            for i, (n, _) in enumerate(self._q):
                if n == "level":
                    del self._q[i]
                    break
            else:
                log.info("event client too slow; dropping it")
                self.closed = True
                self._q.clear()
                return
        self._q.append((name, data))

    def get(self, timeout: float) -> Optional[bytes]:
        """Next frame, or None after `timeout` with nothing queued (or once closed; check .closed)."""
        with self._hub._cond:
            if not self._q and not self.closed:
                self._hub._cond.wait_for(lambda: self._q or self.closed, timeout=timeout)
            if self._q and not self.closed:
                return self._q.popleft()[1]
            return None


class EventHub:
    def __init__(self, status: Callable[[], dict], levels: Callable[[], Optional[tuple[float, float]]],
                 queue_max: int = QUEUE_MAX) -> None:
        """status() -> the /status dict; levels() -> (mic, spk) while in a room, else None."""
        self._status = status
        self._levels = levels
        self._queue_max = queue_max
        self._cond = threading.Condition()
        self._clients: list[Client] = []
        self._last_status: tuple = ()
        self._last_interrupt: dict[str, float] = {}
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    # ---- clients ---------------------------------------------------------
    def subscribe(self) -> Client:
        c = Client(self, self._queue_max)
        st = self._status()
        with self._cond:
            c._put("status", frame("status", st))     # first frame, queued before any later event
            self._clients.append(c)
        return c

    def unsubscribe(self, c: Client) -> None:
        with self._cond:
            c.closed = True
            if c in self._clients:
                self._clients.remove(c)
            self._cond.notify_all()

    def close_all(self) -> None:
        with self._cond:
            for c in self._clients:
                c.closed = True
            self._clients.clear()
            self._cond.notify_all()

    @property
    def client_count(self) -> int:
        with self._cond:
            return len(self._clients)

    def publish(self, name: str, data: dict) -> None:
        f = frame(name, data)
        with self._cond:
            if not self._clients:
                return
            for c in self._clients:
                c._put(name, f)
            self._clients = [c for c in self._clients if not c.closed]
            self._cond.notify_all()

    # ---- sources ---------------------------------------------------------
    def check_status(self) -> None:
        """Publish status if state, bot, muted or error changed since the last one."""
        st = self._status()
        key = tuple(st.get(k) for k in STATUS_KEYS)
        with self._cond:
            if key == self._last_status:
                return
            self._last_status = key
        self.publish("status", st)

    def on_session_event(self, bot: str, kind: str, data: dict) -> None:
        """Session listener (asyncio thread). `bot` is the id of the session that emitted."""
        if kind == "transcript":
            self.publish("transcript", transcript_event(bot, data))
        elif kind == "interrupted":
            now = time.monotonic()
            if now - self._last_interrupt.get(bot, -1e9) >= INTERRUPT_DEDUPE_S:
                self._last_interrupt[bot] = now
                self.publish("interrupted", {"bot": bot})
        elif kind == "agent_ready" and data.get("identity"):
            self.publish("agent", {"bot": bot, "identity": data["identity"], "ready": True})
        elif kind in ("state", "muted", "joined", "left"):
            self.check_status()

    # ---- sampler ---------------------------------------------------------
    def start(self) -> None:
        if self._thread is None:
            self._stop.clear()
            self._thread = threading.Thread(target=self._sample, name="mouthpiece-events", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.close_all()
        self._thread = None

    def _sample(self) -> None:
        # Our own peak from speaker_level samples: the desk face reads and resets
        # AudioIO.speaker_peak, so sharing it would starve one reader or the other.
        mic = spk = 0.0
        next_status = next_level = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            try:
                if now >= next_status:
                    next_status = now + STATUS_POLL_S
                    self.check_status()
                lv = self._levels() if self.client_count else None
            except Exception:
                log.debug("event sampler", exc_info=True)
                lv = None
            if lv is None:
                mic = spk = 0.0
                next_level = 0.0
                self._stop.wait(STATUS_POLL_S)
                continue
            mic, spk = max(mic, float(lv[0])), max(spk, float(lv[1]))
            if now >= next_level:
                if next_level:      # skip the first tick: a full window of samples per event
                    self.publish("level", {"bot": self._status().get("bot"),
                                           "mic": round(min(1.0, mic), 4), "spk": round(min(1.0, spk), 4)})
                    mic = spk = 0.0
                next_level = now + 1.0 / LEVEL_HZ
            self._stop.wait(1.0 / SAMPLE_HZ)


def transcript_event(bot: str, data: dict) -> dict:
    """Session transcript dict -> the wire shape (who "you" -> "user", anything else -> "agent")."""
    ts = data.get("ts") or time.time()
    return {
        "bot": bot,
        "who": "user" if data.get("who") == "you" else "agent",
        "id": int(data.get("id") or 0),
        "text": data.get("text", ""),
        "final": bool(data.get("final")),
        "seq": int(data.get("seq") or 0),
        "kind": data.get("kind", "reply"),
        "ts": int(ts * 1000),
    }
