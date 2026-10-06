"""Local HTTP trigger for the Stream Deck (and anything else on this PC).

Binds 127.0.0.1 only. Every action works over GET as well as POST so the Stream Deck's
built-in "System: Website" action (with "access in background") can drive it without a plugin.

  GET  /status                -> {"state","bot","bot_display","muted","error","bots":[...],"events":1}
  GET  /join/<bot>            -> join that bot's room (switches if in another)
  GET  /switch/<bot>          -> join that bot, or leave if already in that bot's room (one button per bot)
  GET  /leave                 -> leave
  GET  /toggle                -> join current bot / leave
  GET  /mute  /unmute  /toggle-mute   (muting ends the turn first, so what you said is heard now)
  GET  /end-turn              -> end your turn now (no 1.2 s silence wait) without muting
  GET  /stop                  -> stop the bot talking
  GET  /events                -> Server-Sent Events stream (see events.py): status, transcript, level,
                                 interrupted, agent. First frame is status; ": ping" every 15 s.
"""
from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional
from urllib.parse import urlparse

log = logging.getLogger("mouthpiece.trigger")

KEEPALIVE_S = 15.0


class TriggerServer:
    def __init__(self, app, host: str = "127.0.0.1", port: int = 18760) -> None:
        self.app = app
        self.host, self.port = host, port
        self._srv: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> bool:
        app = self.app

        class H(BaseHTTPRequestHandler):
            server_version = "Mouthpiece/1"

            def _json(self, code: int, obj: dict) -> None:
                body = json.dumps(obj).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)

            def _events(self) -> None:
                """SSE: this handler thread blocks on its client queue until the client goes away."""
                hub = app.events
                client = hub.subscribe()
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "keep-alive")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.flush()
                    while not client.closed:
                        f = client.get(timeout=KEEPALIVE_S)
                        if f is None:
                            if client.closed:
                                break
                            f = b": ping\n\n"
                        self.wfile.write(f)
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionError, OSError):
                    pass          # client went away; the next write after it left raises
                finally:
                    hub.unsubscribe(client)
                    self.close_connection = True

            def _dispatch(self) -> None:
                path = urlparse(self.path).path.rstrip("/") or "/"
                parts = [p for p in path.split("/") if p]
                try:
                    if path == "/events" and self.command == "GET":
                        return self._events()
                    if path == "/status" or path == "/":
                        return self._json(200, app.status())
                    if not parts:
                        return self._json(404, {"error": "unknown"})
                    verb = parts[0]
                    arg = parts[1] if len(parts) > 1 else None
                    if verb == "join" and arg:
                        app.join(app.cfg.bot(arg))
                    elif verb == "switch" and arg:
                        app.switch(arg)
                    elif verb == "leave":
                        app.leave()
                    elif verb == "toggle":
                        app.toggle_join()
                    elif verb == "mute":
                        app.set_muted(True)
                    elif verb == "unmute":
                        app.set_muted(False)
                    elif verb == "toggle-mute":
                        app.toggle_mute()
                    elif verb == "end-turn":
                        app.end_turn()
                    elif verb == "stop":
                        app.cancel_reply()
                    else:
                        return self._json(404, {"error": f"unknown action {path}"})
                    return self._json(200, {"ok": True, **app.status()})
                except KeyError as e:
                    return self._json(404, {"error": str(e.args[0]) if e.args else "unknown bot"})
                except Exception as e:  # never let a trigger kill the server
                    log.exception("trigger %s failed", path)
                    return self._json(500, {"error": str(e)})

            def do_GET(self):  # noqa: N802
                self._dispatch()

            def do_POST(self):  # noqa: N802
                self._dispatch()

            def log_message(self, fmt, *args):  # route to our logger, not stderr
                log.debug("http %s", fmt % args)

        try:
            self._srv = ThreadingHTTPServer((self.host, self.port), H)
            self._srv.daemon_threads = True     # an /events handler blocks for as long as its client stays
        except OSError as e:
            log.warning("trigger server not started on %s:%s: %s", self.host, self.port, e)
            return False
        self._thread = threading.Thread(target=self._srv.serve_forever, name="mouthpiece-trigger", daemon=True)
        self._thread.start()
        log.info("trigger server on http://%s:%s (Stream Deck: System > Website, background)", self.host, self.port)
        return True

    def stop(self) -> None:
        if self._srv:
            events = getattr(self.app, "events", None)
            if events is not None:
                events.close_all()          # wakes the /events handlers so they return
            try:
                self._srv.shutdown()
                self._srv.server_close()
            except Exception:
                pass
            self._srv = None
