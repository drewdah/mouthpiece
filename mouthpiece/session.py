"""A voice session: mint -> connect -> publish mic -> play agent -> events -> leave.

Agent-side protocol (hermes_livekit 0.4.0 adapter, verified on CT116 2026-09-15):

Topic "conference.events" (OpenAI-realtime style, flat JSON) — what we actually receive:
  session.created {session}                                   agent is in the room and ready
  input_audio_buffer.speech_started / speech_stopped          VAD heard us
  conversation.item.input_audio_transcription.completed {transcript}   what STT heard
  response.created {response}                                 agent is thinking
  response.output_audio_transcript.delta {delta} / .done {transcript}  what the agent says
  output_audio_buffer.started / stopped / cleared             speaking / done / interrupted
  response.done {response}
  error {error: {code, message}}
Client -> agent on "conference.events": {"type": "response.cancel"} stops the current reply.

Topic "conference.extensions" (Hermes controls, {"type", ...}):
  client -> agent  {"type": "hermes.input_audio.state", "muted": bool}   agent ignores our audio
  client -> agent  {"type": "conference.message", "text": "..."}         typed turn, no STT
  agent -> client  {"type": "hermes.input_audio.state_updated", "muted": bool}
  agent -> client  {"type": "error", "error": {...}}  e.g. input_audio_too_long
  (agent:* lifecycle events also arrive here in some builds; handled too)

The agent joins a few seconds AFTER the first human, and leaves 2 s after the last one drops.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
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
    kind: str = "reply"     # reply | system (gateway notice, never spoken) | silent (reply that produced no audio)
    id: int = 0
    ts: float = field(default_factory=time.time)
    seq: int = 0            # response the line belongs to


_NOTICE_RE = re.compile(
    "^\\s*[\u2300-\u23ff\u2600-\u27bf\U0001f300-\U0001faff\u2190-\u21ff\u25a0-\u25ff]"   # leading pictograph
    "|interrupting current task|respond to your message shortly|auto-lowered|context compress|memory trim",
    re.IGNORECASE,
)


def is_gateway_notice(text: str) -> bool:
    return bool(_NOTICE_RE.search(text or ""))


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
        self._partial = ""
        self._next_id = 1
        self._pending_reply: Optional[Transcript] = None   # reply awaiting its audio
        self._resp_had_audio = False
        self.response_seq = 0        # bumps when a new reply starts

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
        self.audio.gate_while_playing = not self.cfg.barge_in
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

    def set_barge_in(self, enabled: bool) -> None:
        if self.audio:
            self.audio.gate_while_playing = not enabled

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
        if not isinstance(msg, dict):
            return
        topic = packet.topic or ""
        kind = msg.get("type", "")
        payload = msg.get("payload") if isinstance(msg.get("payload"), dict) else msg
        log.debug("data[%s] %s", topic, kind)

        if kind in ("input_audio_buffer.speech_started", "agent:listening-start"):
            if self.state in (State.IN_ROOM, State.LISTENING, State.SPEAKING):
                self._set_state(State.LISTENING)
        elif kind in ("input_audio_buffer.speech_stopped", "agent:listening-stop"):
            if self.state == State.LISTENING:
                self._set_state(State.IN_ROOM)
        elif kind == "conversation.item.input_audio_transcription.completed":
            self._add_transcript("you", payload.get("transcript", ""), True)
        elif kind == "agent:user-transcript":
            self._add_transcript("you", payload.get("transcript", ""), bool(payload.get("final", True)))
        elif kind in ("response.created", "agent:thinking-start"):
            self._partial = ""
            self._resp_had_audio = False
            self.response_seq += 1
            self._set_state(State.THINKING)
        elif kind == "response.output_audio_transcript.delta":
            self._partial += payload.get("delta", "") or ""
            self._emit("transcript", {"who": self.bot.display, "text": self._partial, "final": False, "ts": time.time(),
                                      "seq": self.response_seq})
        elif kind in ("response.output_audio_transcript.done", "agent:agent-transcript"):
            self._partial = ""
            text = payload.get("transcript", "")
            if is_gateway_notice(text):
                self._add_transcript(self.bot.display, text, True, kind="system")
            else:
                t = self._add_transcript(self.bot.display, text, True, kind="reply")
                if t is not None and not self._resp_had_audio:
                    self._pending_reply = t
        elif kind in ("output_audio_buffer.started", "agent:speaking-start"):
            self.speaking_since = time.monotonic()
            self._resp_had_audio = True
            self._pending_reply = None
            self._set_state(State.SPEAKING)
        elif kind in ("output_audio_buffer.stopped", "agent:speaking-stop"):
            if self.state == State.SPEAKING:
                self._set_state(State.IN_ROOM)
        elif kind == "output_audio_buffer.cleared":
            # Barge-in: the agent dropped the rest of its reply; drop what we have buffered too.
            if self.audio:
                self.audio.clear_playback()
            self._emit("interrupted", {})
            if self.state == State.SPEAKING:
                self._set_state(State.IN_ROOM)
        elif kind == "response.done":
            if self._pending_reply is not None and not self._resp_had_audio:
                # The reply finished without a single audio frame: a silent TTS failure.
                self._pending_reply.kind = "silent"
                log.warning("reply produced no audio: %r", self._pending_reply.text[:80])
                self._emit("transcript", self._pending_reply.__dict__)
            self._pending_reply = None
            if self.state == State.THINKING:
                self._set_state(State.IN_ROOM)
        elif kind == "hermes.input_audio.state_updated":
            self._emit("muted", {"muted": bool(msg.get("muted"))})
        elif kind == "error":
            err = msg.get("error") or {}
            log.warning("agent error: %s", err)
            self._emit("agent_error", err)
        self._emit("event", {"topic": topic, "type": kind})

    def _add_transcript(self, who: str, text: str, final: bool, kind: str = "reply") -> Optional[Transcript]:
        text = (text or "").strip()
        if not text or not any(ch.isalnum() for ch in text):
            return None          # glyph-only status pings ("...", a lone emoji) are not captions
        t = Transcript(who, text, final, kind=kind, id=self._next_id, seq=self.response_seq)
        self._next_id += 1
        self.transcripts.append(t)
        del self.transcripts[:-200]
        self._emit("transcript", t.__dict__)
        return t

    async def cancel_reply(self) -> None:
        """Local barge-in button: stop the agent's current reply and flush our speaker buffer."""
        if self.audio:
            self.audio.clear_playback()
        await self._send(TOPIC_EVENTS, {"type": "response.cancel"})
