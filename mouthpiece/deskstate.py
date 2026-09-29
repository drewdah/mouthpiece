"""Optional: publish the voice state for desk displays (config "desk_state": true).

Writes to HKCU\\Software\\HWiNFO64\\VSB in HWiNFO's "gadget" layout, because
InfoPanel's built-in "HWiNFO Registry" plugin already reads that key and turns
each entry into a sensor -- no custom InfoPanel plugin needed. Entries use high
indices so they never collide with HWiNFO's own export (Sensor0..N).

In InfoPanel the sensors are /hwinfo-registry-plugin/<index>; the plugin reads
the key once at startup (so Mouthpiece seeds it on launch) and polls it ~1 s.
"""
from __future__ import annotations

import logging
import sys

log = logging.getLogger("mouthpiece.deskstate")

KEY = r"Software\HWiNFO64\VSB"
GROUP = "Mouthpiece"

IDX_STATE, IDX_BOT, IDX_MUTED = 900, 901, 902

# Stable numeric codes: display profiles threshold on these, so never renumber.
STATE_CODES = {"off": 0, "in room": 1, "listening": 2, "thinking": 3, "speaking": 4, "error": 5, "joining": 6}


class DeskState:
    def __init__(self, bots: list) -> None:
        self._bot_codes = {b.id: i + 1 for i, b in enumerate(bots)}   # config order: 1, 2, 3...
        self._last: tuple = ()
        self.enabled = sys.platform == "win32"
        self.update("off", None, False)

    def update(self, state: str, bot_id: str | None, muted: bool) -> None:
        if not self.enabled:
            return
        values = (STATE_CODES.get(state, 0), self._bot_codes.get(bot_id or "", 0), int(bool(muted)))
        if values == self._last:
            return
        try:
            import winreg
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, KEY) as k:
                for idx, label, val in ((IDX_STATE, "Voice State", values[0]),
                                        (IDX_BOT, "Voice Bot", values[1]),
                                        (IDX_MUTED, "Voice Muted", values[2])):
                    for name, data in ((f"Sensor{idx}", GROUP), (f"Label{idx}", label),
                                       (f"Value{idx}", str(val)), (f"ValueRaw{idx}", str(val))):
                        winreg.SetValueEx(k, name, 0, winreg.REG_SZ, data)
            self._last = values
        except OSError:
            log.warning("desk state: registry write failed; disabling", exc_info=True)
            self.enabled = False
