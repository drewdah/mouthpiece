"""Config loading and saving.

Where config.json lives (first match wins):
  1. $MOUTHPIECE_CONFIG                       explicit override
  2. <repo>/config.json                       developer checkout (gitignored)
  3. %APPDATA%\\Mouthpiece\\config.json         packaged / normal install (created by the setup window)

Two ways to get a LiveKit token:
  token_source = "livekit"  mint locally from livekit_url + livekit_api_key + livekit_api_secret
  token_source = "mint"     ask a mint service: mint_url + mint_token (the house API)
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

APP_NAME = "Mouthpiece"
FROZEN = bool(getattr(sys, "frozen", False))
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))   # resources (fonts, skins)
REPO_CONFIG = Path(__file__).resolve().parent.parent / "config.json"


def user_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    d = Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    env = os.environ.get("MOUTHPIECE_CONFIG")
    if env:
        return Path(env)
    if not FROZEN and REPO_CONFIG.exists():
        return REPO_CONFIG
    return user_dir() / "config.json"


CONFIG_PATH = config_path()


class ConfigMissing(Exception):
    pass


@dataclass
class Bot:
    id: str
    display: str
    room: str
    accent: str = "#FF1A1A"
    skin: str = "kitt"


@dataclass
class Config:
    token_source: str = "livekit"          # livekit | mint
    livekit_url: str = ""                  # ws://host:7880 or wss://...
    livekit_api_key: str = ""
    livekit_api_secret: str = field(default="", repr=False)   # never in repr/logs
    mint_url: str = ""
    mint_token: str = field(default="", repr=False)
    identity: str = "desk"
    name: str = "Me"
    prefer_lan_url: bool = True
    input_device: Optional[Any] = None
    output_device: Optional[Any] = None
    echo_cancellation: bool = True
    noise_suppression: bool = True
    auto_gain_control: bool = False
    barge_in: bool = False                 # False = echo guard on (mic silenced while the bot talks)
    trigger_port: int = 18760
    hotkeys: Optional[dict] = None
    log_file: str = "mouthpiece.log"
    bots: list[Bot] = field(default_factory=list)
    raw: dict = field(default_factory=dict, repr=False)
    path: Path = field(default_factory=lambda: CONFIG_PATH, repr=False)

    KNOWN = ("token_source", "livekit_url", "livekit_api_key", "livekit_api_secret", "mint_url", "mint_token",
             "identity", "name", "prefer_lan_url", "input_device", "output_device", "echo_cancellation",
             "noise_suppression", "auto_gain_control", "barge_in", "trigger_port", "hotkeys", "log_file")

    # ---- load / save ------------------------------------------------------
    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Config":
        path = path or CONFIG_PATH
        if not path.exists():
            raise ConfigMissing(str(path))
        data = json.loads(path.read_text(encoding="utf-8"))
        bots = [Bot(**{k: v for k, v in b.items() if k in Bot.__dataclass_fields__}) for b in data.get("bots", [])]
        kwargs = {k: v for k, v in data.items() if k in cls.KNOWN}
        if "token_source" not in kwargs:      # older configs: mint fields present -> mint mode
            kwargs["token_source"] = "mint" if data.get("mint_token") else "livekit"
        cfg = cls(bots=bots, raw=data, path=path, **kwargs)
        return cfg

    def validate(self) -> list[str]:
        """Human-readable problems; empty when the config is usable."""
        problems = []
        if self.token_source == "mint":
            if not self.mint_url or not self.mint_token or self.mint_token.startswith("PASTE_"):
                problems.append("mint_url and mint_token are required for token_source=mint")
        else:
            if not self.livekit_url or not self.livekit_api_key or not self.livekit_api_secret:
                problems.append("livekit_url, livekit_api_key and livekit_api_secret are required")
        if not self.bots:
            problems.append("at least one bot is required")
        return problems

    def save(self) -> None:
        data = dict(self.raw)
        for k in self.KNOWN:
            data[k] = getattr(self, k)
        data["bots"] = [{"id": b.id, "display": b.display, "room": b.room, "accent": b.accent, "skin": b.skin}
                        for b in self.bots]
        self.raw = data
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # ---- helpers --------------------------------------------------------------
    def bot(self, bot_id: Optional[str] = None) -> Bot:
        if not self.bots:
            raise ValueError("no bots configured")
        if bot_id is None:
            return self.bots[0]
        for b in self.bots:
            if b.id == bot_id:
                return b
        raise KeyError(f"unknown bot {bot_id!r}")

    def log_path(self) -> Path:
        p = Path(self.log_file)
        if p.is_absolute():
            return p
        base = user_dir() if (FROZEN or self.path.parent == user_dir()) else self.path.parent
        return base / p
