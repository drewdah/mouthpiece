"""Get a short-lived LiveKit room token.

Two sources:
  mint_local(...)   sign the JWT here from the LiveKit API key/secret (default for most installs)
  mint_remote(...)  ask a mint service over HTTP (the house API on CT116)

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


def mint_local(url: str, api_key: str, api_secret: str, *, identity: str, name: str, room: str,
               hours: float = 8) -> MintResult:
    try:
        from livekit import api
    except Exception as e:  # pragma: no cover
        raise MintError(f"livekit-api package missing: {e}") from None
    try:
        from datetime import timedelta
        token = (api.AccessToken(api_key=api_key, api_secret=api_secret)
                 .with_identity(identity)
                 .with_name(name)
                 .with_ttl(timedelta(hours=hours))
                 .with_grants(api.VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True,
                                              can_publish_data=True))
                 .to_jwt())
    except Exception as e:
        raise MintError(f"local mint failed: {e}") from None
    res = MintResult(token=token, wss_url=url, lan_url=url, room=room, identity=identity, name=name, hours=float(hours))
    log.info("minted locally %r", res)
    return res


def mint_remote(mint_url: str, mint_token: str, *, identity: str, name: str, room: str, hours: int = 8,
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


def mint_for(cfg, *, room: str) -> MintResult:
    """Pick the source from config."""
    if cfg.token_source == "mint":
        return mint_remote(cfg.mint_url, cfg.mint_token, identity=cfg.identity, name=cfg.name, room=room)
    return mint_local(cfg.livekit_url, cfg.livekit_api_key, cfg.livekit_api_secret,
                      identity=cfg.identity, name=cfg.name, room=room)


# backwards-compatible name used by the spike
mint = mint_remote
