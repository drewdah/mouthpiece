"""First-run / Settings window (Tk). Collects how to reach LiveKit and the first bot.

Runs on the main thread before the tray starts (first run), or as a Toplevel of the stage
root later (tray → Settings…). Secrets are written only to config.json.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from .config import Bot, Config

BG = "#141418"
FG = "#E8E8EC"
ACCENT = "#FF1A1A"


def _style(root) -> None:
    st = ttk.Style(root)
    try:
        st.theme_use("clam")
    except tk.TclError:
        pass
    st.configure(".", background=BG, foreground=FG, fieldbackground="#1E1E24", bordercolor="#333", font=("Segoe UI", 9))
    st.configure("TEntry", fieldbackground="#1E1E24", foreground=FG, insertcolor=FG)
    st.configure("TButton", background="#2A2A32", foreground=FG, padding=6)
    st.map("TButton", background=[("active", "#3A3A44")])
    st.configure("Accent.TButton", background=ACCENT, foreground="#ffffff")
    st.map("Accent.TButton", background=[("active", "#ff4a4a")])
    st.configure("TRadiobutton", background=BG, foreground=FG)
    st.configure("Header.TLabel", font=("Segoe UI", 12, "bold"))
    st.configure("Hint.TLabel", foreground="#9A9AA4", font=("Segoe UI", 8))


class SetupWindow:
    def __init__(self, cfg: Optional[Config], *, parent: Optional[tk.Misc] = None,
                 on_saved: Optional[Callable[[Config], None]] = None) -> None:
        self.cfg = cfg or Config()
        self.on_saved = on_saved
        self.saved = False
        self.top = tk.Toplevel(parent) if parent is not None else tk.Tk()
        self.top.title("Mouthpiece setup")
        self.top.configure(bg=BG)
        self.top.resizable(False, False)
        self.top.attributes("-topmost", True)
        _style(self.top)
        self._build()
        self.top.protocol("WM_DELETE_WINDOW", self._cancel)

    # ---- widgets -------------------------------------------------------------
    def _build(self) -> None:
        c = self.cfg
        f = ttk.Frame(self.top, padding=16)
        f.grid(sticky="nsew")
        r = 0
        ttk.Label(f, text="Mouthpiece", style="Header.TLabel").grid(row=r, column=0, columnspan=3, sticky="w"); r += 1
        ttk.Label(f, text="Voice client for a Hermes bot over LiveKit. Nothing here leaves this PC except the LiveKit connection.",
                  style="Hint.TLabel", wraplength=420).grid(row=r, column=0, columnspan=3, sticky="w", pady=(0, 10)); r += 1

        self.mode = tk.StringVar(value=c.token_source or "livekit")
        ttk.Label(f, text="How to get a room token").grid(row=r, column=0, sticky="w"); r += 1
        ttk.Radiobutton(f, text="LiveKit API key + secret (mint locally)", variable=self.mode, value="livekit",
                        command=self._refresh_mode).grid(row=r, column=0, columnspan=3, sticky="w"); r += 1
        ttk.Radiobutton(f, text="A mint service URL + bearer token", variable=self.mode, value="mint",
                        command=self._refresh_mode).grid(row=r, column=0, columnspan=3, sticky="w", pady=(0, 8)); r += 1

        self.vars: dict[str, tk.StringVar] = {}

        def row(label, key, value, hint="", secret=False):
            nonlocal r
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", pady=2)
            v = tk.StringVar(value=value or "")
            e = ttk.Entry(f, textvariable=v, width=44, show="•" if secret else "")
            e.grid(row=r, column=1, sticky="we", pady=2)
            if hint:
                ttk.Label(f, text=hint, style="Hint.TLabel").grid(row=r, column=2, sticky="w", padx=(8, 0))
            self.vars[key] = v
            self._rows.setdefault(key, []).extend([e])
            r += 1

        self._rows: dict[str, list] = {}
        row("LiveKit URL", "livekit_url", c.livekit_url, "ws://host:7880 or wss://…")
        row("API key", "livekit_api_key", c.livekit_api_key)
        row("API secret", "livekit_api_secret", c.livekit_api_secret, secret=True)
        row("Mint URL", "mint_url", c.mint_url, "…/v1/livekit/token")
        row("Mint token", "mint_token", c.mint_token, secret=True)
        ttk.Separator(f).grid(row=r, column=0, columnspan=3, sticky="we", pady=8); r += 1
        row("Your identity", "identity", c.identity or "desk", "participant id")
        row("Your name", "name", c.name or "Me")
        ttk.Separator(f).grid(row=r, column=0, columnspan=3, sticky="we", pady=8); r += 1
        first = c.bots[0] if c.bots else Bot("kitt", "KITT", "hermes")
        row("First bot id", "bot_id", first.id, "short handle")
        row("Bot display name", "bot_display", first.display)
        row("Bot room", "bot_room", first.room, "must match the bot's gateway")
        ttk.Label(f, text="More bots: edit the bots list in config.json (id, display, room, accent, skin).",
                  style="Hint.TLabel").grid(row=r, column=0, columnspan=3, sticky="w", pady=(2, 10)); r += 1

        self.msg = ttk.Label(f, text="", style="Hint.TLabel", wraplength=420)
        self.msg.grid(row=r, column=0, columnspan=3, sticky="w"); r += 1
        b = ttk.Frame(f)
        b.grid(row=r, column=0, columnspan=3, sticky="e", pady=(8, 0))
        ttk.Button(b, text="Cancel", command=self._cancel).pack(side="right", padx=(8, 0))
        ttk.Button(b, text="Save", style="Accent.TButton", command=self._save).pack(side="right")
        ttk.Label(f, text=f"Config file: {c.path}", style="Hint.TLabel").grid(row=r + 1, column=0, columnspan=3, sticky="w", pady=(10, 0))
        self._refresh_mode()

    def _refresh_mode(self) -> None:
        lk = self.mode.get() == "livekit"
        for key in ("livekit_url", "livekit_api_key", "livekit_api_secret"):
            for w in self._rows.get(key, []):
                w.state(["!disabled"] if lk else ["disabled"])
        for key in ("mint_url", "mint_token"):
            for w in self._rows.get(key, []):
                w.state(["disabled"] if lk else ["!disabled"])

    # ---- actions -----------------------------------------------------------------
    def _save(self) -> None:
        c = self.cfg
        v = {k: s.get().strip() for k, s in self.vars.items()}
        c.token_source = self.mode.get()
        c.livekit_url, c.livekit_api_key, c.livekit_api_secret = v["livekit_url"], v["livekit_api_key"], v["livekit_api_secret"]
        c.mint_url, c.mint_token = v["mint_url"], v["mint_token"]
        c.identity, c.name = v["identity"] or "desk", v["name"] or "Me"
        bot = Bot(v["bot_id"] or "bot", v["bot_display"] or "Bot", v["bot_room"] or "hermes",
                  accent=(c.bots[0].accent if c.bots else "#FF1A1A"), skin=(c.bots[0].skin if c.bots else "kitt"))
        if c.bots:
            c.bots[0] = bot
        else:
            c.bots = [bot]
        problems = c.validate()
        if problems:
            self.msg.configure(text="; ".join(problems))
            return
        c.save()
        self.saved = True
        if self.on_saved:
            self.on_saved(c)
        self.top.destroy()

    def _cancel(self) -> None:
        self.top.destroy()

    def run(self) -> bool:
        """Blocking (first run): returns True if saved."""
        self.top.mainloop()
        return self.saved
