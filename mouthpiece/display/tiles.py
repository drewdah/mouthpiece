"""Sprite atlas + tile face with dirty tracking and a per-frame byte budget.

A face is a set of named slots at fixed screen positions; each slot shows one
frame from the atlas. Callers set what each slot *should* show; flush() sends
only slots whose frame differs from what is on the glass, in priority order,
until the frame's byte budget is spent. Anything left over stays dirty and goes
out on a later frame (NES-style: never redraw the screen, only changed tiles).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image


class Atlas:
    def __init__(self, index_path: Path) -> None:
        meta = json.loads(Path(index_path).read_text())
        base = Path(index_path).parent
        sheet = Image.open(base / meta["image"]).convert("RGB")
        self.frames = {k: sheet.crop((x, y, x + w, y + h)) for k, (x, y, w, h) in meta["frames"].items()}
        self.background = Image.open(base / meta["background"]).convert("RGB") if meta.get("background") else None
        self.size = tuple(meta.get("size", (0, 0)))

    def __getitem__(self, name: str) -> Image.Image:
        return self.frames[name]

    def compose(self, parts: list[str], width: int, height: int, gap: int = 2, align: str = "center") -> str:
        """Build (once) and name a tile from glyph frames trimmed to their ink,
        e.g. digits set as a tightly kerned number. Returns the frame name."""
        key = f"{'+'.join(parts)}@{width}x{height}{align}"
        if key not in self.frames:
            glyphs = []
            for p in parts:
                g = self.frames[p]
                box = g.getbbox()                     # non-black extent
                glyphs.append(g.crop((box[0], 0, box[2], g.height)) if box else Image.new("RGB", (g.width // 2, g.height)))
            total = sum(g.width for g in glyphs) + gap * max(0, len(glyphs) - 1)
            x = {"left": 0, "right": width - total}.get(align, (width - total) // 2)
            tile = Image.new("RGB", (width, height))
            for g in glyphs:
                tile.paste(g, (x, (height - g.height) // 2))
                x += g.width + gap
            self.frames[key] = tile
        return key


@dataclass
class Slot:
    x: int
    y: int
    priority: int = 5          # lower goes first when the budget is tight
    want: Optional[str] = None
    shown: Optional[str] = None


class TileFace:
    def __init__(self, atlas: Atlas) -> None:
        self.atlas = atlas
        self.slots: dict[str, Slot] = {}

    def slot(self, name: str, x: int, y: int, priority: int = 5, frame: Optional[str] = None) -> None:
        self.slots[name] = Slot(x, y, priority, want=frame)

    def set(self, name: str, frame: str) -> None:
        self.slots[name].want = frame

    def invalidate(self) -> None:
        """Forget what is on the glass (after drawing the background)."""
        for s in self.slots.values():
            s.shown = None

    def dirty(self) -> list[tuple[str, Slot]]:
        d = [(n, s) for n, s in self.slots.items() if s.want and s.want != s.shown]
        d.sort(key=lambda it: it[1].priority)
        return d

    def flush(self, screen, budget: Optional[int] = None) -> tuple[int, int]:
        """Send dirty slots until `budget` bytes are used. Returns (bytes, slots sent)."""
        sent = count = 0
        for name, s in self.dirty():
            img = self.atlas[s.want]
            cost = img.width * img.height * 2
            if budget is not None and count and sent + cost > budget:
                continue            # try smaller, lower-priority tiles that still fit
            screen.blit(img, s.x, s.y)
            s.shown = s.want
            sent += cost
            count += 1
        return sent, count

    def render(self) -> Image.Image:
        """What the glass should look like (for previews and other renderers)."""
        img = self.atlas.background.copy() if self.atlas.background else Image.new("RGB", self.atlas.size)
        for s in self.slots.values():
            if s.want:
                img.paste(self.atlas[s.want], (s.x, s.y))
        return img
