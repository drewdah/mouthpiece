"""End-of-turn (conference.control), /end-turn, and the push-to-talk state machine.

No LiveKit, no audio, no real keyboard hook: the room, AudioIO and `keyboard` module are fakes.
"""
from __future__ import annotations

import asyncio
import http.client
import json
import socket
from types import SimpleNamespace

import pytest

from mouthpiece.config import Bot
from mouthpiece.hotkeys import Hotkeys, PushToTalk
from mouthpiece.session import TOPIC_EXT, VoiceSession
from mouthpiece.trigger import TriggerServer

END_TURN = {"type": "conference.control", "action": "end-of-turn"}


def mute_msg(muted: bool) -> dict:
    return {"type": "hermes.input_audio.state", "muted": muted}


class FakeParticipant:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict, bool]] = []

    async def publish_data(self, data: bytes, reliable: bool = False, topic: str = "") -> None:
        self.sent.append((topic, json.loads(data.decode("utf-8")), reliable))


@pytest.fixture
def session():
    loop = asyncio.new_event_loop()
    s = VoiceSession(SimpleNamespace(), Bot("kitt", "KITT", "kitt-room"), loop)
    s.lp = FakeParticipant()
    yield s
    loop.close()


def in_room(s: VoiceSession, muted: bool = False) -> None:
    s.room = SimpleNamespace(local_participant=s.lp)
    s.audio = SimpleNamespace(muted=muted)


def run(s: VoiceSession, coro) -> None:
    s.loop.run_until_complete(coro)


# ---- session ---------------------------------------------------------------
def test_end_turn_message_shape_and_topic(session):
    in_room(session)
    run(session, session.end_turn())
    assert session.lp.sent == [(TOPIC_EXT, END_TURN, True)]
    assert TOPIC_EXT == "conference.extensions"
    assert "identity" not in session.lp.sent[0][1]


def test_end_turn_outside_a_room_sends_nothing(session):
    run(session, session.end_turn())
    assert session.lp.sent == []


def test_mute_ends_the_turn_first(session):
    in_room(session, muted=False)
    run(session, session.set_muted(True))
    assert [m for _, m, _ in session.lp.sent] == [END_TURN, mute_msg(True)]
    assert all(t == TOPIC_EXT and r for t, _, r in session.lp.sent)
    assert session.audio.muted is True


def test_mute_when_already_muted_does_not_end_the_turn(session):
    in_room(session, muted=True)
    run(session, session.set_muted(True))
    assert [m for _, m, _ in session.lp.sent] == [mute_msg(True)]


def test_unmute_is_unchanged(session):
    in_room(session, muted=True)
    run(session, session.set_muted(False))
    assert [m for _, m, _ in session.lp.sent] == [mute_msg(False)]


def test_mute_outside_a_room_sends_nothing(session):
    run(session, session.set_muted(True))
    assert session.lp.sent == []


# ---- /end-turn ---------------------------------------------------------------
class FakeApp:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.cfg = None
        self.events = None

    def end_turn(self) -> None:
        self.calls.append("end_turn")

    def set_muted(self, muted: bool) -> None:
        self.calls.append(f"set_muted({muted})")

    def status(self) -> dict:
        return {"state": "in room", "bot": "kitt", "muted": False}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_end_turn_route():
    app = FakeApp()
    srv = TriggerServer(app, port=_free_port())
    assert srv.start()
    try:
        for method in ("GET", "POST"):
            c = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
            c.request(method, "/end-turn")
            r = c.getresponse()
            body = json.loads(r.read())
            c.close()
            assert r.status == 200 and body["ok"] is True
        assert app.calls == ["end_turn", "end_turn"]       # never mutes
    finally:
        srv.stop()


# ---- push-to-talk ------------------------------------------------------------
class Mic:
    """Stands in for App: mute state plus a log of what push-to-talk asked for."""

    def __init__(self, muted: bool, room: bool = True) -> None:
        self.muted, self.room = muted, room
        self.calls: list = []

    def set_muted(self, m: bool) -> None:
        self.calls.append(("mute", m))
        self.muted = m

    def end_turn(self) -> None:
        self.calls.append("end_turn")

    def ptt(self, key="f13") -> PushToTalk:
        return PushToTalk(key, lambda: self.room, lambda: self.muted, self.set_muted, self.end_turn)


def test_ptt_from_muted_unmutes_then_remutes():
    mic = Mic(muted=True)
    p = mic.ptt()
    p.press()
    assert mic.calls == [("mute", False)] and mic.muted is False
    p.release()
    assert mic.calls == [("mute", False), ("mute", True)]   # set_muted(True) ends the turn first
    assert mic.muted is True


def test_ptt_from_unmuted_only_ends_the_turn():
    mic = Mic(muted=False)
    p = mic.ptt()
    p.press()
    assert mic.calls == []
    p.release()
    assert mic.calls == ["end_turn"] and mic.muted is False


def test_ptt_ignores_auto_repeat():
    mic = Mic(muted=True)
    p = mic.ptt()
    for _ in range(5):
        p.press()
    assert mic.calls == [("mute", False)]
    p.release()
    p.release()                         # stray release: nothing more
    assert mic.calls == [("mute", False), ("mute", True)]
    p.press()                           # a new hold works again
    assert mic.calls[-1] == ("mute", False)


def test_ptt_outside_a_room_does_nothing():
    mic = Mic(muted=True, room=False)
    p = mic.ptt()
    p.press()
    p.release()
    assert mic.calls == [] and mic.muted is True


class FakeKeyboard:
    def __init__(self) -> None:
        self.press, self.release, self.hotkeys, self.unhooked = {}, {}, [], []

    def on_press_key(self, key, cb, suppress=False):
        assert suppress is False
        self.press[key] = cb
        return ("press", key)

    def on_release_key(self, key, cb, suppress=False):
        assert suppress is False
        self.release[key] = cb
        return ("release", key)

    def add_hotkey(self, combo, fn, suppress=False, trigger_on_release=False):
        self.hotkeys.append(combo)
        return combo

    def remove_hotkey(self, h):
        pass

    def unhook(self, h):
        self.unhooked.append(h)


@pytest.fixture
def kb(monkeypatch):
    import sys
    fake = FakeKeyboard()
    monkeypatch.setitem(sys.modules, "keyboard", fake)
    return fake


def test_hotkeys_wire_ptt_to_press_and_release_hooks(kb):
    mic = Mic(muted=True)
    hk = Hotkeys({"push_to_talk": "scroll lock"}, {"toggle_mute": lambda: None}, push_to_talk=mic.ptt("scroll lock"))
    assert hk.start()
    assert "scroll lock" not in kb.hotkeys and "ctrl+alt+m" in kb.hotkeys
    kb.press["scroll lock"](None)
    kb.press["scroll lock"](None)       # auto-repeat from the OS
    kb.release["scroll lock"](None)
    assert mic.calls == [("mute", False), ("mute", True)]
    hk.stop()
    assert kb.unhooked == [("press", "scroll lock"), ("release", "scroll lock")]


def test_ptt_unset_installs_no_hook(kb):
    hk = Hotkeys({"push_to_talk": None}, {}, push_to_talk=Mic(True).ptt(None))
    hk.start()
    assert kb.press == {} and kb.release == {}


def test_ptt_combo_is_refused(kb):
    p = Mic(True).ptt("ctrl+space")
    assert p.start(kb) is False
    assert kb.press == {}


def test_the_agent_arriving_gets_the_current_mute_state_even_when_unmuted():
    # Regression (2026-10-06): only a mute was re-sent on arrival, so a voice body that still
    # remembered an earlier mute kept ignoring the mic after an unmute sent before it arrived.
    import asyncio
    from types import SimpleNamespace
    from mouthpiece.config import Bot
    from mouthpiece.session import VoiceSession

    loop = asyncio.new_event_loop()
    try:
        s = VoiceSession(SimpleNamespace(), Bot("kitt", "KITT", "kitt-room"), loop)
        sent = []

        async def fake_send(topic, msg):
            sent.append((topic, msg))

        s._send = fake_send
        for muted in (False, True):
            sent.clear()
            s.agent_ready.clear()
            s.audio = SimpleNamespace(muted=muted)
            s._on_participant_connected(SimpleNamespace(identity="hermes-kitt", name="KITT"))
            loop.run_until_complete(asyncio.sleep(0))
            assert ("conference.extensions", {"type": "hermes.input_audio.state", "muted": muted}) in sent
    finally:
        loop.close()
