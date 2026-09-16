"""Global hotkeys via the `keyboard` package (low-level hook, no admin needed on Windows).

Config (config.json):
  "hotkeys": {"toggle_mute": "ctrl+alt+m", "toggle_join": "ctrl+alt+j", "stop": "ctrl+alt+s"}
Set a value to null / "" to disable that binding.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

log = logging.getLogger("mouthpiece.hotkeys")

DEFAULTS = {"toggle_mute": "ctrl+alt+m", "toggle_join": "ctrl+alt+j", "stop": "ctrl+alt+s"}


class Hotkeys:
    def __init__(self, bindings: Optional[dict], actions: dict[str, Callable[[], None]]) -> None:
        self.bindings = {**DEFAULTS, **(bindings or {})}
        self.actions = actions
        self._handles = []

    def start(self) -> bool:
        try:
            import keyboard
        except Exception as e:
            log.warning("hotkeys unavailable (pip install keyboard): %s", e)
            return False
        for name, combo in self.bindings.items():
            fn = self.actions.get(name)
            if not combo or fn is None:
                continue
            try:
                h = keyboard.add_hotkey(combo, fn, suppress=False, trigger_on_release=False)
                self._handles.append(h)
                log.info("hotkey %s -> %s", combo, name)
            except Exception as e:
                log.warning("hotkey %r for %s failed: %s", combo, name, e)
        return bool(self._handles)

    def stop(self) -> None:
        try:
            import keyboard
            for h in self._handles:
                keyboard.remove_hotkey(h)
        except Exception:
            pass
        self._handles.clear()
