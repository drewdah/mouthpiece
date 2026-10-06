"""The echo guard: the mic stays silenced toward the agent for the bot's whole turn plus a tail.

Regression (2026-10-05, Candypanel live check): with a 0.45 s tail after the last loud frame,
the bot's last words came back through Voicemeeter and the room after the guard opened, and
the bot answered itself (speaking -> in room -> listening 0.8 s later -> thinking).
No audio devices: AudioIO is built without __init__ (that would open LiveKit's APM).
"""
from __future__ import annotations

import asyncio
from collections import deque
from types import SimpleNamespace

import numpy as np
import pytest

from mouthpiece.audio import AudioIO
from mouthpiece.config import Bot, Config
from mouthpiece.session import State, VoiceSession


def guard(tail: float = 1.2) -> AudioIO:
    a = object.__new__(AudioIO)
    a.gate_while_playing = True
    a.gate_tail_s = tail
    a.agent_speaking = False
    a._last_play_ts = 0.0
    a._play = deque()
    a._play_samples = 0
    a._carry = np.zeros(0, dtype=np.int16)
    return a


def test_the_bots_last_words_do_not_reach_it_through_the_room():
    a = guard()
    a._last_play_ts = 100.0              # last loud frame
    assert a.guarding(100.8)             # where the echo arrived in the live log
    assert not a.guarding(101.3)         # the tail ends: the user can talk again


def test_the_guard_holds_through_pauses_while_the_agent_is_speaking():
    a = guard()
    a.agent_speaking = True
    a._last_play_ts = 100.0
    assert a.guarding(103.0)             # a 3 s pause between sentences
    a.agent_speaking = False             # speaking-stop: the tail runs from now
    assert a.guarding(104.0)
    assert not a.guarding(104.3)


def test_the_agents_continuous_silence_does_not_shut_the_guard():
    # Regression (2026-10-05): the agent's track streams silence, so the play queue is never
    # empty; counting queued audio as "the bot's turn" muted the mic for good.
    a = guard()
    a._play.append(np.zeros(480, dtype=np.int16))
    a._play_samples = 480
    a._carry = np.zeros(120, dtype=np.int16)
    a._last_play_ts = 500.0
    assert not a.guarding(502.0)


def test_the_tail_is_configurable():
    a = guard(tail=0.2)
    a._last_play_ts = 10.0
    assert not a.guarding(10.3)
    assert Config().echo_guard_tail_s == 1.2
    assert "echo_guard_tail_s" in Config.KNOWN


def test_the_session_tells_the_guard_when_the_agent_speaks():
    loop = asyncio.new_event_loop()
    try:
        s = VoiceSession(SimpleNamespace(), Bot("kitt", "KITT", "kitt-room"), loop)
        s.audio = SimpleNamespace(agent_speaking=False)
        s._set_state(State.THINKING)
        assert s.audio.agent_speaking is False
        s._set_state(State.SPEAKING)
        assert s.audio.agent_speaking is True
        s._set_state(State.IN_ROOM)
        assert s.audio.agent_speaking is False
    finally:
        loop.close()
