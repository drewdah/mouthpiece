"""Read bot blueprints from the cast registry (house-presence/cast/<id>/).

The registry is the single source of truth for each bot's identity and colours
(schema: cast/README.md). Mouthpiece only reads it; KITT owns the yaml files.
Everything here degrades to None when the NAS isn't reachable, so surfaces fall
back to their bundled defaults instead of failing.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

log = logging.getLogger("mouthpiece.registry")

def root(configured: Optional[str] = None) -> Optional[Path]:
    """Registry folder: $MOUTHPIECE_CAST_REGISTRY, else the config value
    (turing.registry). No default — without one, surfaces use bundled art."""
    value = os.environ.get("MOUTHPIECE_CAST_REGISTRY") or configured
    return Path(value) if value else None


def _load(bot_id: str, name: str, configured: Optional[str] = None) -> Optional[dict]:
    base = root(configured)
    if base is None:
        return None
    try:
        import yaml
        path = base / bot_id / name
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else None
    except Exception as e:
        log.info("cast registry: %s/%s unavailable (%s)", bot_id, name, e)
        return None


def load_style(bot_id: str, configured: Optional[str] = None) -> Optional[dict]:
    return _load(bot_id, "style.yaml", configured)


def load_bot(bot_id: str, configured: Optional[str] = None) -> Optional[dict]:
    return _load(bot_id, "bot.yaml", configured)
