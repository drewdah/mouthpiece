"""Config loading. Secrets live in config.json next to the repo root (gitignored)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"


@dataclass
class Bot:
    id: str
    display: str
    room: str
    accent: str = "#FF1A1A"
    skin: str = "kitt"


@dataclass
class Config:
    mint_url: str
    mint_token: str
    identity: str = "drew-desk"
    name: str = "Drew"
    prefer_lan_url: bool = True
    input_device: Optional[Any] = None
    output_device: Optional[Any] = None
    echo_cancellation: bool = True
    noise_suppression: bool = True
    auto_gain_control: bool = False
    log_file: str = "mouthpiece.log"
    bots: list[Bot] = field(default_factory=list)
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "Config":
        data = json.loads(path.read_text(encoding="utf-8"))
        bots = [Bot(**b) for b in data.get("bots", [])]
        known = {k for k in cls.__dataclass_fields__ if k not in ("bots", "raw")}
        kwargs = {k: v for k, v in data.items() if k in known}
        cfg = cls(bots=bots, raw=data, **kwargs)
        if not cfg.mint_token or cfg.mint_token.startswith("PASTE_"):
            raise ValueError(f"mint_token missing in {path}")
        return cfg

    def bot(self, bot_id: Optional[str] = None) -> Bot:
        if not self.bots:
            raise ValueError("no bots configured")
        if bot_id is None:
            return self.bots[0]
        for b in self.bots:
            if b.id == bot_id:
                return b
        raise KeyError(f"unknown bot {bot_id!r}")
