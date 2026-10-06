"""Global hotkeys via the `keyboard` package (low-level hook, no admin needed on Windows).

Config (config.json):
  "hotkeys": {"toggle_mute": "ctrl+alt+m", "toggle_join": "ctrl+alt+j", "stop": "ctrl+alt+s",
              "push_to_talk": null}
Set a value to null / "" to disable that binding.

push_to_talk is a single key, e.g. "f13", "scroll lock", "right ctrl" (combos are not supported).
Hold it to talk: it unmutes while held if you were muted, and on release ends your turn (the bot
hears you right away) and mutes again. If you were already unmuted, release only ends the turn.
The key is never swallowed, so games still see it.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

log = logging.getLogger("mouthpiece.hotkeys")

DEFAULTS = {"toggle_mute": "ctrl+alt+m", "toggle_join": "ctrl+alt+j", "stop": "ctrl+alt+s"}


class PushToTalk:
    """Hold-to-talk state machine for one key. Callbacks run on the keyboard hook thread."""

    def __init__(self, key: Optional[str], in_room: Callable[[], bool], is_muted: Callable[[], bool],
                 set_muted: Callable[[bool], None], end_turn: Callable[[], None]) -> None:
        self.key = (key or "").strip() or None
        self.in_room, self.is_muted = in_room, is_muted
        self.set_muted, self.end_turn = set_muted, end_turn
        self._held = False          # key is down (auto-repeat presses are ignored)
        self._active = False        # this hold started in a room
        self._unmuted_by_us = False
        self._warned_no_room = False
        self._hooks = []

    def press(self, _event=None) -> None:
        if self._held:
            return
        self._held = True
        self._active = bool(self.in_room())
        if not self._active:
            if not self._warned_no_room:
                log.info("push-to-talk: not in a room, ignored")
                self._warned_no_room = True
            return
        self._unmuted_by_us = bool(self.is_muted())
        if self._unmuted_by_us:
            self.set_muted(False)

    def release(self, _event=None) -> None:
        if not self._held:
            return
        self._held = False
        if not self._active:
            return
        self._active = False
        if self._unmuted_by_us:
            self._unmuted_by_us = False
            self.set_muted(True)        # ends the turn first, then mutes
        else:
            self.end_turn()

    def start(self, keyboard) -> bool:
        if not self.key:
            return False
        if "+" in self.key and self.key != "+":
            log.warning("push-to-talk %r: combos aren't supported, use a single key", self.key)
            return False
        try:
            self._hooks = [keyboard.on_press_key(self.key, self.press, suppress=False),
                           keyboard.on_release_key(self.key, self.release, suppress=False)]
        except Exception as e:
            log.warning("push-to-talk %r failed: %s", self.key, e)
            self.stop(keyboard)
            return False
        log.info("hotkey %s -> push_to_talk (hold)", self.key)
        return True

    def stop(self, keyboard) -> None:
        for h in self._hooks:
            try:
                keyboard.unhook(h)
            except Exception:
                pass
        self._hooks.clear()


class Hotkeys:
    def __init__(self, bindings: Optional[dict], actions: dict[str, Callable[[], None]],
                 push_to_talk: Optional[PushToTalk] = None) -> None:
        self.bindings = {**DEFAULTS, **(bindings or {})}
        self.actions = actions
        self.ptt = push_to_talk
        self._handles = []
        self._ptt_on = False

    def start(self) -> bool:
        try:
            import keyboard
        except Exception as e:
            log.warning("hotkeys unavailable (pip install keyboard): %s", e)
            return False
        for name, combo in self.bindings.items():
            fn = self.actions.get(name)
            if name == "push_to_talk" or not combo or fn is None:
                continue
            try:
                h = keyboard.add_hotkey(combo, fn, suppress=False, trigger_on_release=False)
                self._handles.append(h)
                log.info("hotkey %s -> %s", combo, name)
            except Exception as e:
                log.warning("hotkey %r for %s failed: %s", combo, name, e)
        if self.ptt is not None:
            self._ptt_on = self.ptt.start(keyboard)
        return bool(self._handles) or self._ptt_on

    def stop(self) -> None:
        try:
            import keyboard
            for h in self._handles:
                keyboard.remove_hotkey(h)
            if self.ptt is not None:
                self.ptt.stop(keyboard)
        except Exception:
            pass
        self._handles.clear()
        self._ptt_on = False
