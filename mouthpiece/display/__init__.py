"""Desk display faces: each cast member's face pushed to small USB screens.

turing.py          minimal driver for the Turing Smart Screen 3.5" (rev A), portrait or landscape
tiles.py           sprite atlas + tile face with dirty tracking and a per-frame byte budget
panel.py           PanelFace base (thread, stats, clock, voice meter) + FrameDiff surface + Pen
kitt.py            KITT's dash (sprite sheet from make_kitt_sheet.py, both layouts)
baymax.py          Baymax: head and shoulders, projector screen on his belly
wheatley.py        Wheatley: the personality core's optic next to a test-chamber sign
faces.py           bot id -> face class
host.py            one host per configured panel, swapping faces with the active bot
"""
