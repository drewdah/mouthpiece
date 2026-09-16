# Mouthpiece

Native LiveKit desk client for talking to Hermes bots (KITT first). Tray icon, real Join/Leave,
full duplex through the house LiveKit room, Pocket-TTS voice back. No browser. See `SPEC.md`.

## Install (packaged)
1. Unzip `Mouthpiece.zip` anywhere and run `Mouthpiece.exe`.
2. The first run opens a setup window. Pick how tokens are made:
   - **LiveKit API key + secret** (the usual case): paste your LiveKit server URL (`ws://host:7880` or `wss://…`)
     and the API key/secret from your LiveKit config. Tokens are signed locally; nothing else is contacted.
   - **Mint service**: a URL + bearer token if you run a token service instead.
3. Enter your identity/name and the first bot (its display name and the LiveKit **room** its Hermes gateway waits in).
4. A tray icon appears. Right-click → Join. Settings… reopens the window later.

Config and log live in `%APPDATA%\Mouthpiece\`. More bots go in the `bots` list of that config.json.

## Run from source (developers)
```
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy config.example.json config.json    # or let the setup window create %APPDATA%\Mouthpiece\config.json
Mouthpiece.cmd                          # tray (pythonw, no console)
.venv\Scripts\python spike.py           # terminal debug: join, print events, Enter to leave
```
A `config.json` next to the source wins over the AppData one, so a checkout keeps its own settings.

## Build the exe
```
.venv\Scripts\python -m pip install -r requirements-build.txt
.uild.ps1                              # dist\Mouthpiece\Mouthpiece.exe + dist\Mouthpiece.zip
```

## Hermes side
Each bot is a Hermes profile running the `livekit` platform (pip `hermes-livekit`) as its own gateway, waiting in
its own room, speaking through its own TTS voice. See `lab/` for the profile recipe and the two gateway patches
this client relies on (clause-by-clause transcripts, longer streaming-TTS drain).

## Layout
- `mouthpiece/config.py` — config.json (gitignored: mint token, devices, bots)
- `mouthpiece/mint.py` — JWT from CT116 mint API (memory only)
- `mouthpiece/audio.py` — sounddevice ⇄ LiveKit frames, echo cancellation
- `mouthpiece/session.py` — room lifecycle, agent events, transcripts
- `mouthpiece/tray.py` — pystray UI
- `lab/` — patches proposed for the Hermes side

## Adding a bot

Each bot is one entry in the `bots` list of `config.json` and one Hermes profile on the lab.

```json
{"id": "baymax", "display": "Baymax", "room": "baymax", "accent": "#FF1A1A", "skin": "kitt"}
```

| Field | Meaning |
|---|---|
| `id` | short handle; used by the Stream Deck trigger (`/join/<id>`) and the tray |
| `display` | name shown on the tray, the stage header, and the LCD tag |
| `room` | the LiveKit room this bot's gateway waits in. Must be unique per bot. |
| `accent` | LED colour for this bot's cluster |
| `skin` | stage skin. Only `kitt` exists today; new skins register in `mouthpiece/stage/kitt.py` `SKINS` |

The mint API hands out a token for any room name, so nothing changes there.

Lab side, per bot (on CT116):
1. Clone a profile: `hermes profile create <name> --clone` (see the `voice` profile as the template).
2. In that profile's `config.yaml`: `platforms.livekit.extra.room: <room>`, `agent_name: <Display>`
   (the agent joins as `hermes-<display lower>`), and its own `tts.providers.pocket_tts.voice`
   for the cloned Pocket voice. Disable the other platforms.
3. Run its gateway as a service like `hermes-livekit-spike.service`, with `ExecStartPre` reapply
   of the same streaming patches.

Mouthpiece joins one bot at a time: picking another bot in the tray leaves the current room and
joins the new one.


## Stream Deck / hotkeys
Local trigger on `http://127.0.0.1:18760` (GET or POST, loopback only). In the Stream Deck app use
**System → Website** with "Access in background" and a URL such as:

| URL | Does |
|---|---|
| `/switch/kitt` · `/switch/baymax` · `/switch/wheatley` | one button per bot: join, or leave if already in that room |
| `/join/<bot>` / `/leave` / `/toggle` | explicit join, leave, or join/leave the current bot |
| `/mute` / `/unmute` / `/toggle-mute` | mic |
| `/stop` | stop the bot talking |
| `/status` | JSON state |

Global hotkeys (config `hotkeys`): `ctrl+alt+m` mute, `ctrl+alt+j` join/leave, `ctrl+alt+s` stop.
