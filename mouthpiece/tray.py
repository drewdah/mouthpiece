"""Mouthpiece tray app.

pystray owns the main thread (Windows message loop). The LiveKit session runs on an
asyncio loop in a background thread; everything crosses over with
asyncio.run_coroutine_threadsafe. The icon colour is the room state.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import sys
import threading
from logging.handlers import RotatingFileHandler
from typing import Optional

import pystray
import sounddevice as sd
from PIL import Image, ImageDraw

from . import __version__
from .config import CONFIG_PATH, ROOT, Bot, Config
from .session import State, VoiceSession

log = logging.getLogger("mouthpiece.tray")

STATE_COLORS = {
    State.OFF: "#5a5a5a",
    State.JOINING: "#d9a400",
    State.IN_ROOM: "#2fa84f",
    State.LISTENING: "#22b8cf",
    State.THINKING: "#ff8c1a",
    State.SPEAKING: None,       # bot accent
    State.ERROR: "#d0219b",
}
SINGLE_INSTANCE_PORT = 18761


class _RedactSecrets(logging.Filter):
    """Belt and braces: never let a JWT or bearer token reach the log file."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if "eyJ" in msg or "Bearer " in msg:
            record.msg = "[redacted: message contained a token]"
            record.args = ()
        return True


def setup_logging(cfg: Config) -> str:
    path = str((ROOT / cfg.log_file).resolve())
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fh = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    fh.addFilter(_RedactSecrets())
    root.addHandler(fh)
    if sys.stderr is not None and sys.stderr.isatty():
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(sh)
    logging.getLogger("livekit").setLevel(logging.WARNING)
    return path


def make_icon(color: str, muted: bool = False, size: int = 64) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = 6
    d.ellipse((pad, pad, size - pad, size - pad), fill=color)
    # a small mouth bar so it reads as "voice" at 16px
    d.rounded_rectangle((size * 0.3, size * 0.56, size * 0.7, size * 0.64), radius=3, fill="#0b0b0b")
    if muted:
        d.line((pad + 4, size - pad - 4, size - pad - 4, pad + 4), fill="#ffffff", width=6)
    return img


class App:
    def __init__(self) -> None:
        self.cfg = Config.load()
        self.log_path = setup_logging(self.cfg)
        log.info("Mouthpiece %s starting (config %s)", __version__, CONFIG_PATH)
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, name="mouthpiece-loop", daemon=True)
        self.thread.start()
        self.session: Optional[VoiceSession] = None
        self.bot: Bot = self.cfg.bot()
        self.last_transcript: str = ""
        self.captions: list[tuple[str, str, bool]] = []
        self.stage = None  # set by main() when the stage runs on the main thread
        self.icon = pystray.Icon("mouthpiece", make_icon(STATE_COLORS[State.OFF]), "Mouthpiece", menu=self._build_menu())

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _call(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    # ---- state -----------------------------------------------------------
    @property
    def state(self) -> State:
        return self.session.state if self.session else State.OFF

    def _on_session_event(self, kind: str, data: dict) -> None:
        if kind == "state":
            self._refresh()
            if data.get("state") == State.ERROR.value and data.get("error"):
                self._notify(f"{self.bot.display}: {data['error']}")
        elif kind == "transcript":
            who, text, final = data["who"], data["text"], bool(data.get("final"))
            if self.captions and not self.captions[-1][2] and self.captions[-1][0] == who:
                self.captions[-1] = (who, text, final)      # live-update the partial line
            else:
                self.captions.append((who, text, final))
            del self.captions[:-60]
            if final:
                self.last_transcript = f"{who}: {text}"
                self._refresh()
        elif kind == "left" or (kind == "state" and data.get("state") == State.OFF.value):
            self.captions.clear()
        elif kind == "muted":
            self._refresh()
        elif kind == "agent_error":
            self._notify(f"{self.bot.display}: {data.get('message') or data.get('code') or 'agent error'}")

    def snapshot(self) -> dict:
        """What the stage paints this frame. Plain data only; called from the Tk thread."""
        st = self.state
        a = self.session.audio if self.session else None
        return {
            "visible": st not in (State.OFF, State.ERROR),
            "state": st.value,
            "muted": bool(self.session and self.session.muted),
            "spk_level": a.speaker_level if a else 0.0,
            "mic_level": a.mic_level if a else 0.0,
            "bot_display": self.bot.display,
            "accent": self.bot.accent,
            "skin": self.bot.skin,
            "captions": list(self.captions),
        }

    def _refresh(self) -> None:
        st = self.state
        color = STATE_COLORS.get(st) or self.bot.accent
        muted = bool(self.session and self.session.muted)
        try:
            self.icon.icon = make_icon(color, muted)
            self.icon.title = f"Mouthpiece — {self.bot.display}: {st.value}" + (" (muted)" if muted else "")
            self.icon.update_menu()
        except Exception:
            log.debug("icon refresh failed", exc_info=True)

    def _notify(self, text: str) -> None:
        try:
            self.icon.notify(text[:200], "Mouthpiece")
        except Exception:
            pass

    # ---- actions ---------------------------------------------------------
    def join(self, bot: Optional[Bot] = None) -> None:
        if bot is not None and bot.id != self.bot.id:
            if self.session and self.state != State.OFF:
                self._call(self._switch(bot))
                return
            self.bot = bot
        if self.session and self.state not in (State.OFF, State.ERROR):
            return
        self.session = VoiceSession(self.cfg, self.bot, self.loop)
        self.session.on(self._on_session_event)
        self._call(self.session.join())

    async def _switch(self, bot: Bot) -> None:
        if self.session:
            await self.session.leave()
        self.bot = bot
        self.session = VoiceSession(self.cfg, self.bot, self.loop)
        self.session.on(self._on_session_event)
        await self.session.join()

    def leave(self) -> None:
        if self.session:
            self._call(self.session.leave())

    def toggle_mute(self) -> None:
        if self.session and self.state not in (State.OFF, State.ERROR):
            self._call(self.session.set_muted(not self.session.muted))

    def toggle_join(self) -> None:
        if self.state in (State.OFF, State.ERROR):
            self.join()
        else:
            self.leave()

    def toggle_barge_in(self) -> None:
        self.cfg.barge_in = not self.cfg.barge_in
        self.cfg.raw["barge_in"] = self.cfg.barge_in
        CONFIG_PATH.write_text(json.dumps(self.cfg.raw, indent=2), encoding="utf-8")
        if self.session:
            self.session.set_barge_in(self.cfg.barge_in)
        log.info("barge-in %s (echo guard %s)", "on" if self.cfg.barge_in else "off", "off" if self.cfg.barge_in else "on")

    def cancel_reply(self) -> None:
        if self.session:
            self._call(self.session.cancel_reply())

    def open_log(self) -> None:
        try:
            os.startfile(self.log_path)  # type: ignore[attr-defined]
        except Exception as e:
            log.warning("open log: %s", e)

    def quit(self) -> None:
        def _stop():
            try:
                if self.session:
                    fut = self._call(self.session.leave())
                    fut.result(timeout=5)
            except Exception:
                pass
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.icon.stop()
            if self.stage is not None:
                self.stage.close()
        threading.Thread(target=_stop, daemon=True).start()

    # ---- devices ---------------------------------------------------------
    def _devices(self, kind: str) -> list[tuple[int, str]]:
        """Devices of the default host API only (Windows lists each device 4x otherwise)."""
        try:
            default_idx = sd.default.device[0 if kind == "input" else 1]
            hostapi = sd.query_devices(default_idx)["hostapi"] if default_idx is not None and default_idx >= 0 else sd.default.hostapi
        except Exception:
            hostapi = 0
        key = "max_input_channels" if kind == "input" else "max_output_channels"
        out = []
        for i, d in enumerate(sd.query_devices()):
            if d["hostapi"] == hostapi and d[key] > 0:
                out.append((i, d["name"]))
        return out

    def _set_device(self, kind: str, index: Optional[int]) -> None:
        field = "input_device" if kind == "input" else "output_device"
        setattr(self.cfg, field, index)
        self.cfg.raw[field] = index
        CONFIG_PATH.write_text(json.dumps(self.cfg.raw, indent=2), encoding="utf-8")
        log.info("%s device -> %s", kind, index if index is not None else "Windows default")
        if self.session and self.state not in (State.OFF, State.ERROR):
            self._notify("Device change applies on next Join")

    def _device_menu(self, kind: str) -> pystray.Menu:
        field = "input_device" if kind == "input" else "output_device"

        def make(index: Optional[int], name: str):
            def action(icon, item):
                self._set_device(kind, index)

            def checked(item):
                return getattr(self.cfg, field) == index

            return pystray.MenuItem(name, action, checked=checked, radio=True)

        def items():
            yield make(None, "Windows default")
            for idx, name in self._devices(kind):
                yield make(idx, name)

        return pystray.Menu(items)

    # ---- menu ------------------------------------------------------------
    def _build_menu(self) -> pystray.Menu:
        def bot_item(b: Bot):
            def action(icon, item):
                self.join(b)

            def checked(item):
                return self.bot.id == b.id

            return pystray.MenuItem(b.display, action, checked=checked, radio=True)

        def bot_items():
            for b in self.cfg.bots:
                yield bot_item(b)

        in_room = lambda item: self.state not in (State.OFF, State.ERROR, State.JOINING)  # noqa: E731
        return pystray.Menu(
            pystray.MenuItem(lambda item: f"{self.bot.display}: {self.state.value}"
                             + (f" — {self.session.error}" if self.session and self.session.error else ""),
                             None, enabled=False),
            pystray.MenuItem(lambda item: (self.last_transcript[:60] or "…") if in_room(item) else "",
                             None, enabled=False, visible=lambda item: in_room(item) and bool(self.last_transcript)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda item: f"Join {self.bot.display}", lambda: self.join(),
                             visible=lambda item: self.state in (State.OFF, State.ERROR), default=True),
            pystray.MenuItem(lambda item: f"Leave {self.bot.display}", lambda: self.leave(),
                             visible=lambda item: self.state not in (State.OFF, State.ERROR), default=True),
            pystray.MenuItem("Mute microphone", lambda: self.toggle_mute(),
                             checked=lambda item: bool(self.session and self.session.muted), visible=in_room),
            pystray.MenuItem("Stop talking", lambda: self.cancel_reply(),
                             visible=lambda item: self.state == State.SPEAKING),
            pystray.MenuItem("Allow interruptions (barge-in)", lambda: self.toggle_barge_in(),
                             checked=lambda item: self.cfg.barge_in),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Bot", pystray.Menu(bot_items)),
            pystray.MenuItem("Microphone device", self._device_menu("input")),
            pystray.MenuItem("Speaker device", self._device_menu("output")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open log", lambda: self.open_log()),
            pystray.MenuItem(f"Mouthpiece {__version__}", None, enabled=False),
            pystray.MenuItem("Quit", lambda: self.quit()),
        )

    def run(self) -> None:
        """Tray detached on its own thread; the stage owns the main thread (Tk needs it)."""
        from .stage.window import StageWindow
        self.stage = StageWindow(
            self.snapshot,
            actions={"mic": self.toggle_mute, "stop": self.cancel_reply, "link": self.leave},
            menu_items=[
                (lambda: "Unmute microphone" if (self.session and self.session.muted) else "Mute microphone", self.toggle_mute),
                ("Stop talking", self.cancel_reply),
                (None, None),
                (lambda: f"Leave {self.bot.display}", self.leave),
            ],
            config_path=CONFIG_PATH,
            config_raw=self.cfg.raw,
        )
        self.icon.run_detached()
        try:
            self.stage.mainloop()
        finally:
            try:
                self.icon.stop()
            except Exception:
                pass


def _single_instance() -> Optional[socket.socket]:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
        s.listen(1)
        return s
    except OSError:
        return None


def main() -> int:
    lock = _single_instance()
    if lock is None:
        print("Mouthpiece is already running.", file=sys.stderr)
        return 2
    app = App()
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
