"""A voice session: mint -> connect -> publish mic -> play agent -> events -> leave.

Agent-side protocol (hermes_livekit 0.4.0 adapter, observed on CT116):
  data topic "conference.extensions": {"type": "agent:<event>", "payload": {...}}
     agent:listening-start/stop {identity}, agent:thinking-start,
     agent:user-transcript {transcript, final, identity, source},
     agent:agent-transcript {transcript, final}, agent:speaking-start/stop,
     hermes.input_audio.state_updated {muted}
  data topic "conference.events": OpenAI-realtime-style events (only if the client
     opts into that protocol; we do not).
Client -> agent on "conference.extensions": {"type": "hermes.input_audio.state", "muted": bool}
Client -> agent on "conference.extensions": {"type": "conference.message", "text": "..."} injects a typed turn.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

from livekit import rtc

from .audio import RATE, CHANNELS, AudioIO
from .config import Bot, Config
from .mint import MintError, mint

log = logging.getLogger("mouthpiece.session")

TOPIC_EVENTS = "conference.events"
TOPIC_EXT = "conference.extensions"


class State(str, Enum):
    OFF = "off"
    JOINING = "joining"
    IN_ROOM = "in room"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ERROR = "error"


@dataclass
class Transcript:
    who: str        # "you" | bot display
    text: str
    final: bool
    ts: float = field(default_factory=time.time)


Listener = Callable[[str, dict], None]


class VoiceSession:
    def __init__(self, cfg: Config, bot: Bot, loop: asyncio.AbstractEventLoop) -> None:
        self.cfg = cfg
        self.bot = bot
        self.loop = loop
        self.state = State.OFF
        self.error: str = ""
        self.room: Optional[rtc.Room] = None
        self.audio: Optional[AudioIO] = None
        self.agent_identity: Optional[str] = None
        self.transcripts: list[Transcript] = []
        self._listeners: list[Listener] = []
        self._agent_stream_task: Optional[asyncio.Task] = None
        self._mic_track: Optional[rtc.LocalAudioTrack] = None
        self.speaking_since: float = 0.0
        self._leaving = False
        self.agent_ready = asyncio.Event()

    # ---- observers -------------------------------------------------------
    def on(self, fn: Listener) -> None:
        self._listeners.append(fn)

    def _emit(self, kind: str, data: Optional[dict] = None) -> None:
        for fn in list(self._listeners):
            try:
                fn(kind, data or {})
            except Exception:
                log.exception("listener failed")

    def _set_state(self, s: State, error: str = "") -> None:
        if s == self.state and error == self.error:
            return
        self.state, self.error = s, error
        log.info("state -> %s%s", s.value, f" ({error})" if error else "")
        self._emit("state", {"state": s.value, "error": error})

    # ---- join / leave ----------------------------------------------------
    async def join(self) -> None:
        if self.state not in (State.OFF, State.ERROR):
            return
        self._set_state(State.JOINING)
        try:
            m = await asyncio.to_thread(
                mint, self.cfg.mint_url, self.cfg.mint_token,
                identity=self.cfg.identity, name=self.cfg.name, room=self.bot.room,
            )
        except MintError as e:
            self._set_state(State.ERROR, str(e))
            return

        room = rtc.Room(loop=self.loop)
        room.on("track_subscribed", self._on_track_subscribed)
        room.on("track_unsubscribed", self._on_track_unsubscribed)
        room.on("data_received", self._on_data)
        room.on("participant_connected", self._on_participant_connected)
        room.on("participant_disconnected", self._on_participant_disconnected)
        room.on("disconnected", self._on_disconnected)

        urls = [u for u in ((m.lan_url if self.cfg.prefer_lan_url else None), m.wss_url, m.lan_url) if u]
        last_err = None
        for url in dict.fromkeys(urls):
            try:
                await asyncio.wait_for(room.connect(url, m.token, options=rtc.RoomOptions(auto_subscribe=True)), timeout=10)
                log.info("connected to %s room=%s as %s", url, m.room, m.identity)
                last_err = None
                break
            except Exception as e:
                last_err = e
                log.warning("connect via %s failed: %s", url, e)
        if last_err is not None:
            self._set_state(State.ERROR, f"connect failed: {last_err}")
            return
        self.room = room

        self.audio = AudioIO(self.loop, input_device=self.cfg.input_device, output_device=self.cfg.output_device,
                             echo_cancellation=self.cfg.echo_cancellation,
                             noise_suppression=self.cfg.noise_suppression,
                             auto_gain_control=self.cfg.auto_gain_control)
        try:
            self.audio.start()
        except Exception as e:
            await self._teardown()
            self._set_state(State.ERROR, f"audio: {e}")
            return

        self._mic_track = rtc.LocalAudioTrack.create_audio_track("mic", self.audio.source)
        opts = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        await room.local_participant.publish_track(self._mic_track, opts)
        log.info("mic published; remote participants: %s", [p.identity for p in room.remote_participants.values()])
        self._set_state(State.IN_ROOM)
        self._emit("joined", {"room": m.room, "participants": [p.identity for p in room.remote_participants.values()]})
        for p in room.remote_participants.values():
            self._on_participant_connected(p)

    # The agent joins the room a few seconds after we do (it waits for a human).
    # Anything sent before it arrives is dropped, so control state is (re)sent on arrival.
    def _on_participant_connected(self, p: rtc.RemoteParticipant) -> None:
        self._emit("participant", {"identity": p.identity, "joined": True})
        if p.identity.startswith("hermes-") and not self.agent_ready.is_set():
            self.agent_identity = p.identity
            self.agent_ready.set()
            log.info("agent %s (%s) is in the room", p.identity, p.name)
            self._emit("agent_ready", {"identity": p.identity, "name": p.name})
            if self.audio and self.audio.muted:
                self.loop.create_task(self._send(TOPIC_EXT, {"type": "hermes.input_audio.state", "muted": True}))

    def _on_participant_disconnected(self, p: rtc.RemoteParticipant) -> None:
        self._emit("participant", {"identity": p.identity, "joined": False})
        if p.identity == self.agent_identity:
            self.agent_ready.clear()
            self._emit("agent_ready", {"identity": None})

    async def leave(self) -> None:
        if self.state == State.OFF:
            return
        self._leaving = True
        try:
            await self._teardown()
        finally:
            self._leaving = False
        self._set_state(State.OFF)
        self._emit("left", {})

    async def _teardown(self) -> None:
        if self._agent_stream_task:
            self._agent_stream_task.cancel()
            self._agent_stream_task = None
        if self.audio:
            self.audio.stop()
            self.audio = None
        if self.room:
            try:
                await asyncio.wait_for(self.room.disconnect(), timeout=5)
            except Exception as e:
                log.debug("disconnect: %s", e)
            self.room = None
        self.agent_identity = None
        self.agent_ready.clear()

    def _on_disconnected(self, *args) -> None:
        if self._leaving or self.state == State.OFF:
            return
        log.warning("room disconnected: %s", args)
        asyncio.ensure_future(self._teardown(), loop=self.loop)
        self._set_state(State.ERROR, "disconnected")

    # ---- mute ------------------------------------------------------------
    async def set_muted(self, muted: bool) -> None:
        if self.audio:
            self.audio.muted = muted
        if self.room:
            await self._send(TOPIC_EXT, {"type": "hermes.input_audio.state", "muted": muted})
        self._emit("muted", {"muted": muted})

    @property
    def muted(self) -> bool:
        return bool(self.audio and self.audio.muted)

    async def send_text(self, text: str, wait_for_agent: float = 10.0) -> bool:
        """Type a turn to the bot instead of speaking it. Waits for the agent to be present."""
        try:
            await asyncio.wait_for(self.agent_ready.wait(), timeout=wait_for_agent)
        except asyncio.TimeoutError:
            log.warning("send_text: agent not in room after %.0fs", wait_for_agent)
            return False
        await self._send(TOPIC_EXT, {"type": "conference.message", "text": text})
        return True

    async def _send(self, topic: str, msg: dict) -> None:
        if not self.room:
            return
        await self.room.local_participant.publish_data(json.dumps(msg).encode("utf-8"), reliable=True, topic=topic)

    # ---- tracks ----------------------------------------------------------
    def _on_track_subscribed(self, track: rtc.Track, pub: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant) -> None:
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        log.info("audio track from %s (%s)", participant.identity, participant.name)
        self.agent_identity = participant.identity
        if self._agent_stream_task:
            self._agent_stream_task.cancel()
        self._agent_stream_task = self.loop.create_task(self._pump_agent_audio(track))

    def _on_track_unsubscribed(self, track, pub, participant) -> None:
        if participant.identity == self.agent_identity and self._agent_stream_task:
            self._agent_stream_task.cancel()
            self._agent_stream_task = None

    async def _pump_agent_audio(self, track: rtc.Track) -> None:
        stream = rtc.AudioStream(track, sample_rate=RATE, num_channels=CHANNELS)
        try:
            async for ev in stream:
                if self.audio:
                    self.audio.play_frame(ev.frame)
        except asyncio.CancelledError:
            pass
        finally:
            await stream.aclose()

    # ---- data channel ----------------------------------------------------
    def _on_data(self, packet: rtc.DataPacket) -> None:
        try:
            msg = json.loads(bytes(packet.data).decode("utf-8"))
        except Exception:
            return
        topic = packet.topic or ""
        kind = msg.get("type", "")
        payload = msg.get("payload") or {}
        log.debug("data[%s] %s %s", topic, kind, payload if kind != "agent:agent-transcript" else "(transcript)")
        if kind == "agent:listening-start":
            self._set_state(State.LISTENING)
        elif kind == "agent:listening-stop":
            if self.state == State.LISTENING:
                self._set_state(State.IN_ROOM)
        elif kind == "agent:thinking-start":
            self._set_state(State.THINKING)
        elif kind == "agent:speaking-start":
            self.speaking_since = time.monotonic()
            self._set_state(State.SPEAKING)
        elif kind == "agent:speaking-stop":
            self._set_state(State.IN_ROOM)
        elif kind == "agent:user-transcript":
            t = Transcript("you", payload.get("transcript", ""), bool(payload.get("final", True)))
            self.transcripts.append(t)
            self._emit("transcript", t.__dict__)
        elif kind == "agent:agent-transcript":
            t = Transcript(self.bot.display, payload.get("transcript", ""), bool(payload.get("final", True)))
            self.transcripts.append(t)
            self._emit("transcript", t.__dict__)
        elif kind == "hermes.input_audio.state_updated":
            self._emit("muted", {"muted": bool(msg.get("muted"))})
        elif kind == "error":
            err = msg.get("error") or {}
            self._emit("agent_error", err)
        self._emit("event", {"topic": topic, "type": kind, "payload": payload})
