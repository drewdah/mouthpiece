"""Local HTTP trigger for the Stream Deck (and anything else on this PC).

Binds 127.0.0.1 only. Every action works over GET as well as POST so the Stream Deck's
built-in "System: Website" action (with "access in background") can drive it without a plugin.

  GET  /status                -> {"state","bot","muted","bots":[...]}
  GET  /join/<bot>            -> join that bot's room (switches if in another)
  GET  /switch/<bot>          -> join that bot, or leave if already in that bot's room (one button per bot)
  GET  /leave                 -> leave
  GET  /toggle                -> join current bot / leave
  GET  /mute  /unmute  /toggle-mute
  GET  /stop                  -> stop the bot talking
"""
from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional
from urllib.parse import urlparse

log = logging.getLogger("mouthpiece.trigger")


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

            def _dispatch(self) -> None:
                path = urlparse(self.path).path.rstrip("/") or "/"
                parts = [p for p in path.split("/") if p]
                try:
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
        except OSError as e:
            log.warning("trigger server not started on %s:%s: %s", self.host, self.port, e)
            return False
        self._thread = threading.Thread(target=self._srv.serve_forever, name="mouthpiece-trigger", daemon=True)
        self._thread.start()
        log.info("trigger server on http://%s:%s (Stream Deck: System > Website, background)", self.host, self.port)
        return True

    def stop(self) -> None:
        if self._srv:
            try:
                self._srv.shutdown()
            except Exception:
                pass
            self._srv = None
