"""EventHub fan-out and the /events SSE endpoint, with a fake App (no LiveKit, no audio)."""
from __future__ import annotations

import http.client
import json
import socket
import time

import pytest

from mouthpiece.events import EventHub, frame, transcript_event
from mouthpiece.trigger import TriggerServer


class FakeApp:
    def __init__(self) -> None:
        self.st = {"state": "off", "bot": "kitt", "bot_display": "KITT", "muted": False, "error": "",
                   "bots": ["kitt"], "events": 1}
        self.lv = None          # (mic, spk) while "in a room"
        self.cfg = None
        self.events = EventHub(lambda: dict(self.st), lambda: self.lv)

    def status(self) -> dict:
        return dict(self.st)


def parse(raw: bytes) -> tuple[str, dict]:
    lines = raw.decode("utf-8").strip().split("\n")
    assert lines[0].startswith("event: ") and lines[1].startswith("data: ")
    return lines[0][7:], json.loads(lines[1][6:])


# ---- hub -------------------------------------------------------------------
def test_fan_out_to_every_client_status_first():
    app = FakeApp()
    a, b = app.events.subscribe(), app.events.subscribe()
    app.events.publish("interrupted", {"bot": "kitt"})
    for c in (a, b):
        assert parse(c.get(0.1)) == ("status", app.st)
        assert parse(c.get(0.1)) == ("interrupted", {"bot": "kitt"})
        assert c.get(0.01) is None and not c.closed


def test_status_published_only_on_change():
    app = FakeApp()
    c = app.events.subscribe()
    c.get(0.1)
    app.events.check_status()           # first check records the baseline and publishes it
    app.events.check_status()
    assert parse(c.get(0.1))[0] == "status"
    assert c.get(0.01) is None
    app.st["muted"] = True
    app.events.on_session_event("kitt", "muted", {"muted": True})
    name, data = parse(c.get(0.1))
    assert name == "status" and data["muted"] is True
    app.st["bots"] = ["kitt", "other"]  # not a watched key
    app.events.check_status()
    assert c.get(0.01) is None


def test_full_queue_drops_oldest_level_first_then_the_client():
    app = FakeApp()
    app.events = EventHub(app.status, lambda: None, queue_max=3)
    c = app.events.subscribe()                       # [status]
    app.events.publish("level", {"n": 1})            # [status, level1]
    app.events.publish("level", {"n": 2})            # [status, level1, level2]
    app.events.publish("interrupted", {"bot": "kitt"})   # full: level1 goes
    assert not c.closed
    got = [parse(c.get(0.1)) for _ in range(3)]
    assert [g[0] for g in got] == ["status", "level", "interrupted"] and got[1][1] == {"n": 2}
    for i in range(3):
        app.events.publish("agent", {"i": i})        # fills with non-level frames
    app.events.publish("agent", {"i": 3})            # nothing to drop: the client goes
    assert c.closed and app.events.client_count == 0
    assert c.get(0.01) is None


def test_session_events_map_to_wire_shapes():
    app = FakeApp()
    c = app.events.subscribe()
    c.get(0.1)
    hub = app.events
    hub.on_session_event("kitt", "transcript", {"who": "you", "text": "hi", "final": False, "kind": "reply",
                                                "id": 4, "ts": 1700000000.5, "seq": 2})
    hub.on_session_event("kitt", "transcript", {"who": "KITT", "text": "Hello", "final": True, "kind": "reply",
                                                "id": 5, "ts": 1700000001.0, "seq": 2})
    hub.on_session_event("kitt", "agent_ready", {"identity": "hermes-kitt", "name": "KITT"})
    hub.on_session_event("kitt", "agent_ready", {"identity": None})          # agent left: no event
    hub.on_session_event("kitt", "interrupted", {"local": True})
    hub.on_session_event("kitt", "interrupted", {})                          # the agent's echo of /stop
    out = []
    while (f := c.get(0.05)) is not None:
        out.append(parse(f))
    assert out == [
        ("transcript", {"bot": "kitt", "who": "user", "id": 4, "text": "hi", "final": False, "seq": 2,
                        "kind": "reply", "ts": 1700000000500}),
        ("transcript", {"bot": "kitt", "who": "agent", "id": 5, "text": "Hello", "final": True, "seq": 2,
                        "kind": "reply", "ts": 1700000001000}),
        ("agent", {"bot": "kitt", "identity": "hermes-kitt", "ready": True}),
        ("interrupted", {"bot": "kitt"}),
    ]


def test_frame_is_one_line_of_json():
    f = frame("transcript", transcript_event("kitt", {"who": "KITT", "text": "a\nb", "id": 1, "ts": 1}))
    assert f.count(b"\n") == 3 and f.endswith(b"\n\n")


def test_level_sampler_uses_its_own_peak(monkeypatch):
    app = FakeApp()
    samples = iter([(0.1, 0.0), (0.0, 0.9)] + [(0.0, 0.1)] * 10_000)
    app.events = EventHub(app.status, lambda: next(samples))
    c = app.events.subscribe()
    c.get(0.1)
    app.events.start()
    try:
        deadline = time.monotonic() + 3
        level = None
        while time.monotonic() < deadline:
            f = c.get(0.2)
            if f and parse(f)[0] == "level":
                level = parse(f)[1]
                break
    finally:
        app.events.stop()
    assert level is not None and level["bot"] == "kitt"
    assert level["spk"] == 0.9 and level["mic"] == 0.1     # max since the last level event


def test_no_levels_without_a_room():
    app = FakeApp()
    c = app.events.subscribe()
    c.get(0.1)
    app.events.start()
    try:
        names = []
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            f = c.get(0.1)
            if f:
                names.append(parse(f)[0])
        assert "level" not in names
    finally:
        app.events.stop()


# ---- SSE end to end ------------------------------------------------------
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def served():
    app = FakeApp()
    srv = TriggerServer(app, port=_free_port())
    assert srv.start()
    app.events.start()
    yield app, srv
    app.events.stop()
    srv.stop()


def _read_frame(resp) -> bytes:
    buf = b""
    while not buf.endswith(b"\n\n"):
        ch = resp.read(1)
        if not ch:
            raise EOFError
        buf += ch
    return buf


def test_status_advertises_events(served):
    app, srv = served
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    conn.request("GET", "/status")
    assert json.loads(conn.getresponse().read())["events"] == 1
    conn.close()


def test_sse_stream_end_to_end(served):
    app, srv = served
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    conn.request("GET", "/events")
    resp = conn.getresponse()
    assert resp.status == 200
    assert resp.getheader("Content-Type") == "text/event-stream"
    assert resp.getheader("Cache-Control") == "no-cache"
    assert parse(_read_frame(resp)) == ("status", app.st)

    app.st["state"] = "in room"
    app.events.on_session_event("kitt", "state", {"state": "in room", "error": ""})
    name, data = parse(_read_frame(resp))
    assert name == "status" and data["state"] == "in room"

    app.events.on_session_event("kitt", "transcript", {"who": "KITT", "text": "Hi", "final": False, "id": 7,
                                                       "ts": 2.0, "seq": 1, "kind": "reply"})
    assert parse(_read_frame(resp))[1]["text"] == "Hi"

    app.lv = (0.2, 0.5)                    # now "in a room": levels flow at ~20 Hz
    name, data = parse(_read_frame(resp))
    assert name == "level" and data == {"bot": "kitt", "mic": 0.2, "spk": 0.5}
    resp.close()                           # the response holds the socket open, not the connection
    conn.close()

    deadline = time.monotonic() + 3        # the handler notices on its next write and unsubscribes
    while app.events.client_count and time.monotonic() < deadline:
        time.sleep(0.05)
    assert app.events.client_count == 0


def test_keepalive_ping(served, monkeypatch):
    import mouthpiece.trigger as trig
    monkeypatch.setattr(trig, "KEEPALIVE_S", 0.2)
    app, srv = served
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    conn.request("GET", "/events")
    resp = conn.getresponse()
    _read_frame(resp)
    assert _read_frame(resp) == b": ping\n\n"
    conn.close()


def test_stop_releases_open_streams(served):
    app, srv = served
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    conn.request("GET", "/events")
    resp = conn.getresponse()
    _read_frame(resp)
    app.events.close_all()
    with pytest.raises(EOFError):
        _read_frame(resp)               # the handler returned and closed the response
    conn.close()
