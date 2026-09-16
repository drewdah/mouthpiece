"""Mint a short-lived LiveKit room JWT from the house mint API (CT116 :8093).

The JWT is held in memory only and never logged.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

log = logging.getLogger("mouthpiece.mint")


class MintError(RuntimeError):
    pass


@dataclass
class MintResult:
    token: str
    wss_url: str
    lan_url: str
    room: str
    identity: str
    name: str
    hours: float

    def __repr__(self) -> str:  # never leak the JWT via repr/logging
        return f"MintResult(room={self.room!r}, identity={self.identity!r}, lan={self.lan_url!r}, wss={self.wss_url!r})"


def mint(mint_url: str, mint_token: str, *, identity: str, name: str, room: str, hours: int = 8,
         timeout: float = 5.0) -> MintResult:
    q = urllib.parse.urlencode({"identity": identity, "name": name, "room": room, "hours": hours})
    req = urllib.request.Request(f"{mint_url}?{q}", headers={"Authorization": f"Bearer {mint_token}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise MintError(f"mint HTTP {e.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise MintError(f"mint unreachable: {getattr(e, 'reason', e)}") from None
    token = body.get("token")
    if not token:
        raise MintError("mint response had no token")
    res = MintResult(
        token=token,
        wss_url=body.get("wss_url") or "",
        lan_url=body.get("livekit_url") or "",
        room=body.get("room") or room,
        identity=body.get("identity") or identity,
        name=body.get("name") or name,
        hours=float(body.get("hours") or hours),
    )
    log.info("minted %r", res)
    return res
