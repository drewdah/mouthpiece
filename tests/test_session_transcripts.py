"""VoiceSession._on_data transcript mapping, without connecting anywhere."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from mouthpiece.config import Bot
from mouthpiece.session import State, VoiceSession


@pytest.fixture
def session():
    loop = asyncio.new_event_loop()
    s = VoiceSession(SimpleNamespace(), Bot("kitt", "KITT", "kitt-room"), loop)
    s.events = []
    s.on(lambda kind, data: s.events.append((kind, dict(data))))
    yield s
    loop.close()


def feed(s: VoiceSession, msg: dict, topic: str = "conference.extensions") -> None:
    s._on_data(SimpleNamespace(data=json.dumps(msg).encode("utf-8"), topic=topic))


def transcripts(s: VoiceSession) -> list[dict]:
    return [d for k, d in s.events if k == "transcript"]


def test_agent_transcript_partials_are_one_live_line(session):
    feed(session, {"type": "agent:thinking-start"})
    feed(session, {"type": "agent:agent-transcript", "payload": {"transcript": "Hello there.", "final": False}})
    feed(session, {"type": "agent:agent-transcript", "payload": {"transcript": "Hello there. How are", "final": False}})
    feed(session, {"type": "agent:agent-transcript", "payload": {"transcript": "Hello there. How are you?", "final": True}})
    ts = transcripts(session)
    assert [t["final"] for t in ts] == [False, False, True]
    assert [t["text"] for t in ts] == ["Hello there.", "Hello there. How are", "Hello there. How are you?"]
    assert len({t["id"] for t in ts}) == 1 and ts[0]["id"] > 0
    assert all(t["who"] == "KITT" for t in ts)
    assert len(session.transcripts) == 1 and session.transcripts[0].final


def test_agent_transcript_without_final_flag_is_final(session):
    feed(session, {"type": "agent:agent-transcript", "payload": {"transcript": "One shot."}})
    feed(session, {"type": "agent:agent-transcript", "payload": {"transcript": "Another."}})
    ts = transcripts(session)
    assert [t["final"] for t in ts] == [True, True]
    assert ts[0]["id"] != ts[1]["id"]


def test_realtime_deltas_share_the_final_id(session):
    feed(session, {"type": "response.created"}, topic="conference.events")
    for d in ("Hi", " there", "."):
        feed(session, {"type": "response.output_audio_transcript.delta", "delta": d}, topic="conference.events")
    feed(session, {"type": "response.output_audio_transcript.done", "transcript": "Hi there."}, topic="conference.events")
    ts = transcripts(session)
    assert [t["text"] for t in ts] == ["Hi", "Hi there", "Hi there.", "Hi there."]
    assert [t["final"] for t in ts] == [False, False, False, True]
    assert len({t["id"] for t in ts}) == 1
    assert ts[0]["seq"] == 1


def test_user_partials_then_completed_share_an_id(session):
    feed(session, {"type": "agent:user-transcript", "payload": {"transcript": "what is", "final": False}})
    feed(session, {"type": "conversation.item.input_audio_transcription.completed", "transcript": "what is the time"},
         topic="conference.events")
    ts = transcripts(session)
    assert [t["who"] for t in ts] == ["you", "you"]
    assert [t["final"] for t in ts] == [False, True]
    assert ts[0]["id"] == ts[1]["id"]


def test_new_response_abandons_an_unfinished_line(session):
    feed(session, {"type": "agent:agent-transcript", "payload": {"transcript": "Cut off", "final": False}})
    feed(session, {"type": "response.created"}, topic="conference.events")
    feed(session, {"type": "agent:agent-transcript", "payload": {"transcript": "Fresh reply", "final": True}})
    ts = transcripts(session)
    assert ts[0]["id"] != ts[1]["id"]


def test_gateway_notice_final_is_system(session):
    feed(session, {"type": "agent:agent-transcript", "payload": {"transcript": "⏳ Interrupting current task", "final": True}})
    assert transcripts(session)[0]["kind"] == "system"


def test_local_stop_emits_interrupted_while_speaking(session):
    session.state = State.SPEAKING
    session.loop.run_until_complete(session.cancel_reply())
    assert ("interrupted", {"local": True}) in session.events
