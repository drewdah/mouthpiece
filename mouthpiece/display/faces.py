"""Which face class draws which bot on the desk panel."""
from __future__ import annotations

import importlib

FACES = {
    "kitt": ("kitt", "KittFace"),
    "baymax": ("baymax", "BaymaxFace"),
    "wheatley": ("wheatley", "WheatleyFace"),
}
DEFAULT = "kitt"


def face_class(bot_id: str):
    mod, cls = FACES.get(bot_id, FACES[DEFAULT])
    return getattr(importlib.import_module(f".{mod}", __package__), cls)
