# Mouthpiece

Native LiveKit desk client for talking to Hermes bots (KITT first). Tray icon, real Join/Leave,
full duplex through the house LiveKit room, Pocket-TTS voice back. No browser. See `SPEC.md`.

## Run
```
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy config.example.json config.json    # then paste the LiveKit mint token
Mouthpiece.cmd                          # tray (pythonw, no console)
.venv\Scripts\python spike.py           # terminal debug: join, print events, Enter to leave
```
Tray: right-click → Join KITT / Leave / Mute / Bot / devices / Open log. Left-click = Join/Leave.

## Layout
- `mouthpiece/config.py` — config.json (gitignored: mint token, devices, bots)
- `mouthpiece/mint.py` — JWT from CT116 mint API (memory only)
- `mouthpiece/audio.py` — sounddevice ⇄ LiveKit frames, echo cancellation
- `mouthpiece/session.py` — room lifecycle, agent events, transcripts
- `mouthpiece/tray.py` — pystray UI
- `lab/` — patches proposed for the Hermes side
