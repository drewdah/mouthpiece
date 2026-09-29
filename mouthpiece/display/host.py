"""The desk panels: one host per physical Turing screen, each showing the active
bot's face in that screen's orientation, swapped when the bot changes.

Config (turing section):
  {"brightness": 50, "registry": "<cast folder>",
   "panels": [{"port": "1-10.2", "orientation": "portrait"},
              {"port": "1-10.1.4", "orientation": "landscape", "brightness": 40}]}
A panel's "port" is a USB location (stable: which socket it's in), a COM name,
or "AUTO". Without "panels", the section itself is one portrait panel (the
original single-screen config).
"""
from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

from .faces import face_class
from .panel import PanelFace, Source
from .turing import TuringRevA

log = logging.getLogger("mouthpiece.panels")

SHARED = ("brightness", "registry")


def panel_configs(cfg: dict) -> list[dict]:
    panels = cfg.get("panels")
    if not panels:
        panels = [{"port": cfg.get("port", "AUTO"), "orientation": cfg.get("orientation", "portrait")}]
    return [{**{k: cfg[k] for k in SHARED if k in cfg}, **p} for p in panels]


class PanelHost:
    """One screen. The port stays open across bot swaps, so a swap costs only
    the new face's background (~2 s at the link's speed), not a panel reset."""

    def __init__(self, cfg: dict, source: Source) -> None:
        self.cfg = cfg
        self.source = source
        self.orientation = cfg.get("orientation", "portrait")
        self.screen = TuringRevA(cfg.get("port", "AUTO"), self.orientation)
        self.face: Optional[PanelFace] = None
        self.bot: Optional[str] = None

    def show(self, bot_id: str) -> None:
        if bot_id == self.bot:
            return
        old, self.bot = self.face, bot_id
        if old is not None:
            old.stop(close=False)
        self.face = face_class(bot_id)(self.cfg, self.source, orientation=self.orientation)
        self.face.start(self.screen)
        log.info("panel %s (%s): %s face", self.cfg.get("port"), self.orientation, self.face.name)

    def stop(self, blank: bool = False) -> None:
        if self.face is not None:
            self.face.stop(blank=blank)
        self.screen.close()


class DeskPanels:
    """All configured panels, following the active bot."""

    POLL = 0.5

    def __init__(self, cfg: dict, source: Source, bot: Callable[[], str]) -> None:
        self.hosts = [PanelHost(c, source) for c in panel_configs(cfg)]
        self._bot = bot
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="desk-panels", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            bot = self._bot()
            for host in self.hosts:
                try:
                    host.show(bot)
                except Exception:
                    log.exception("panel %s: showing %s failed", host.cfg.get("port"), bot)
            self._stop.wait(self.POLL)

    def stop(self, blank: bool = False) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        threads = [threading.Thread(target=h.stop, kwargs={"blank": blank}, daemon=True) for h in self.hosts]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=12)
