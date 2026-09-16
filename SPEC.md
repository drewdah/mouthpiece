# Mouthpiece — native desk voice client for Hermes bots

**Owner:** Drew Lawton · **Builder:** Claude · **Windows dogfood = ship gate**
**Date:** 2026-09-15 · **Supersedes:** `SPEC-desk-kitt-native-voice-v4-claude-handoff.md` (KITT, Grok 4.5)
**Repo:** `D:\Projects\homelab\mouthpiece` (git) · old package `C:\Users\Drew\hermes\desk-kitt-voice` untouched as fallback

---

## 0. One-sentence goal

A Windows tray app that joins a Hermes bot's LiveKit room natively (no browser), owns mic and
speakers, gives full-duplex conversation with barge-in and a real Leave, shows a per-bot avatar
stage with live transcript while in the room, and grows to several bots picked from the tray or a
Stream Deck button.

**Done when:** launch → tray icon → Join KITT → talk freely, interrupt, hear Pocket-TTS KITT →
Leave releases the mic within 2 s. No Chrome, no token paste, daily driver.

---

## 1. Decisions made with Drew (2026-09-15)

| Topic | Decision |
|---|---|
| Package | Fresh lean app. Old desk-kitt-voice left alone, retired later. |
| Transport | **Native LiveKit client** (Option N from the handoff). `livekit` Python SDK 1.1.x, prebuilt Windows wheels, built-in AEC/NS. |
| Audio gear | AT2020 USB via **Voicemeeter** virtual devices. Output switches between headphones and desk speakers → echo cancellation is load-bearing. Device pickers, default = Windows default. |
| Session model | Manual Join / Leave from tray. Global hotkeys for mute and join/leave. Local HTTP trigger for Stream Deck (one button per bot). |
| Room | Today: Drew + KITT in room `hermes`. Design: **one bot = one room + one Hermes profile + one voice + one skin**, joined one at a time. |
| Lab access | Read + edit the voice profile. **Ask before any gateway restart.** |
| Stage | Custom native first, porting the **cast-skins** KITT avatar (segmented LED cluster, red). Visible only while in room. Live transcript captions. Skinnable per bot. Live2D later if wanted. |
| Face bus / Pixoo | Not a short-term goal. Keep the state feed generic so other renderers can attach later. |
| Date fix | In scope. (Turned out to be a TTS bug, see §4.) |
| Launch | Run from source (`pyw`) + Start Menu shortcut + optional autostart. Exe later. |
| Name | **Mouthpiece**. |

---

## 2. What already exists on the lab (do not rebuild)

| Piece | Where | Notes |
|---|---|---|
| Hermes `voice` profile gateway | CT116 `hermes-livekit-spike.service` (`hermes -p voice gateway run --force`) | Runs the `livekit` platform from pip package `hermes-livekit 0.4.0`. It is the **agent participant**: Silero VAD → faster-whisper (tiny) → Hermes turn → Pocket-TTS streamed as PCM into the room. Barge-in lives here. |
| Agent behaviour | joins room on first human participant, leaves 2 s after the last one drops (`Participant detected in 'hermes', joining`) | So per-bot rooms cost nothing extra: each profile's gateway waits for its own room. |
| Agent identity | `hermes-<agent_name lower>` → `hermes-kitt`, display name `KITT` | From `platforms.livekit.extra.agent_name`. |
| Mint API | `GET http://192.168.1.177:8093/v1/livekit/token?identity&name&room&hours` + `Authorization: Bearer <LIVEKIT_MINT_TOKEN>` | Returns `token`, `livekit_url` (LAN `ws://192.168.1.163:7880`), `wss_url` (`wss://livekit.mysticspark.tech`), `room`, `identity`, `name`, `hours`. |
| LiveKit server | CT301 on node **homelab3**, `192.168.1.163:7880` | LAN ws works from the PC (measured 0.9 s connect). |
| Pocket-TTS | CT207 (homelab2) via HA `tts.pocket_tts`, voice `kitt`; called by `/root/.hermes/scripts/pocket_tts_kitt.py` | Per-bot voices = per-profile `tts.providers.pocket_tts.voice`. |
| cast-skins | `/root/.hermes/desktop-plugins/cast-skins/plugin.js` (React, 1361 lines) | `CAST[]` table of bots (profile, display, theme, accent, colors), `KittClusterAvatar` (15-seg mid + 11-seg side LED wells, red gradient, rAF-driven level with attack/decay), `RacingLedBar` scanner. Port target for the stage. |
| Local patches | `/root/projects/livekit-spike/patches/` re-applied by `ExecStartPre` | `tts_streaming.py` (PocketStreamer), `hermes_livekit/streaming_tts.py`, `hermes_livekit/adapter.py`. Any lab fix must also update the snapshot. |

### 2.1 Data-channel protocol the client uses (verified in adapter.py)

Topic `conference.extensions`, JSON:

| Direction | Message |
|---|---|
| agent → client | `{"type":"agent:listening-start"\|"agent:listening-stop","payload":{"identity"}}` |
| agent → client | `{"type":"agent:thinking-start","payload":{}}` |
| agent → client | `{"type":"agent:user-transcript","payload":{"transcript","final","identity","source"}}` |
| agent → client | `{"type":"agent:agent-transcript","payload":{"transcript","final"}}` |
| agent → client | `{"type":"agent:speaking-start"\|"agent:speaking-stop"}` |
| agent → client | `{"type":"hermes.input_audio.state_updated","muted":bool}` (targeted) |
| agent → client | `{"type":"error","error":{"code","message"}}` e.g. `input_audio_too_long` |
| client → agent | `{"type":"hermes.input_audio.state","muted":bool}` — agent stops feeding our audio to VAD |
| client → agent | `{"type":"conference.message","text":"..."}` — typed turn, no STT |
| client → agent | `{"type":"conference.control", ...}` — reserved |

Topic `conference.events` is the OpenAI-realtime-style protocol; Mouthpiece does not opt in.
Audio: client publishes one mic track (`SOURCE_MICROPHONE`, 48 kHz mono), subscribes to the agent's
audio track (auto-subscribe), plays it.

---

## 3. Architecture

```
tray (pystray, main thread)          asyncio loop thread
 ├─ menu: bot list / Join / Leave     ├─ VoiceSession(bot)
 │        Mute / devices / log        │    mint → rtc.Room.connect(LAN ws, fallback wss)
 ├─ hotkeys (global)  ───────────────▶│    publish mic  ◀── AudioIO (sounddevice 48k/10ms)
 ├─ HTTP trigger :18760 (Stream Deck)─▶│    play agent   ──▶ AudioIO ring buffer → speakers
 └─ stage window (per-bot skin)  ◀────│    data channel → state / transcripts / levels
          shows only while in room     └─ StateFeed (observable): state, mic/spk level, transcript
```

### 3.1 Modules

| File | Role |
|---|---|
| `mouthpiece/config.py` | `config.json` (gitignored; mint token, identity, devices, bots[]). `config.example.json` has placeholders. |
| `mouthpiece/mint.py` | Mint JWT. JWT lives in memory only; `MintResult.__repr__` hides it. |
| `mouthpiece/audio.py` | `AudioIO`: InputStream → `AudioProcessingModule` (AEC + NS + HPF) → `rtc.AudioSource`; agent frames → ring buffer → OutputStream; every played block goes to `process_reverse_stream` so AEC knows what the speakers emitted. Mute = send silence. Exposes mic/speaker RMS for the stage. |
| `mouthpiece/session.py` | `VoiceSession`: join / leave / mute / send_text, room events → `State` enum (`off, joining, in room, listening, thinking, speaking, error`), transcripts, observer callbacks. |
| `mouthpiece/tray.py` | pystray app, menu, status line, log file (`mouthpiece.log`, no secrets), single-instance lock. |
| `mouthpiece/hotkeys.py` | Global hotkeys (mute toggle, join/leave toggle). |
| `mouthpiece/trigger.py` | `127.0.0.1:18760` HTTP: `POST /join/<bot>`, `/leave`, `/mute`, `/unmute`, `/toggle-mute`, `GET /status`. For Stream Deck "Website"/"System: Open" actions or a small plugin later. |
| `mouthpiece/stage/` | Stage window (always-on-top, frameless, transparent). Skin API: `paint(state, mic_level, spk_level, transcript_tail, t)`. First skin `kitt` ported from cast-skins. |
| `spike.py` | Terminal runner used to prove the path. Stays as the debug tool. |

### 3.2 Stage rendering choice
Tk canvas or pygame are both viable for a segmented-LED avatar. **Choose pyglet/pygame-style
immediate rendering only if Tk cannot hit 30 fps with ~40 rounded rects; otherwise Tk** (stdlib,
no extra dependency, easy transparent/topmost window on Windows via `-transparentcolor` and
`-topmost`). Decision made in Phase 3 after a 2-minute benchmark; recorded here when made.

### 3.3 Multi-bot model
`bots[]` in config: `{id, display, room, accent, skin, profile}`. Adding a bot on the lab = clone a
Hermes profile, give it its own `platforms.livekit.extra.room` + `agent_name` + Pocket voice, run its
gateway as a service. Mouthpiece joins one room at a time; switching bots = leave + join.

---

## 4. Lab defect found during recon: streaming TTS aborts every reply

Handoff §3.1 called it a date bug. The log says otherwise: on "What's the date today?" the agent
called `ha_get_state`, produced a 35-char answer, then:

```
WARNING gateway.streaming_tts_consumer: streaming TTS clause failed: unsupported operand type(s) for -: 'float' and 'NoneType'
INFO  ... streaming TTS finished: 0.06s PCM, aborted=True
INFO  gateway.run: Suppressing normal final send ... final delivery already confirmed (streamed=True ...)
```

**Every** LiveKit reply since 2026-09-13 21:03 UTC has aborted this way (17/17 in 7 days, 0 successes),
and the whole-file fallback is suppressed because the stream claimed delivery. So the room has been
silent, not wrong about the date.

**Root cause** (`hermes_livekit/streaming_tts.py`, lines 153–169, identical in the patch snapshot):
`first_queued_at` is only set inside `if not handle.audible:`. But the upstream consumer
(`gateway/streaming_tts_consumer.py`, hermes 0.21.3 of 2026-09-14) sets `handle.audible = True`
itself after the first `write_streaming_tts()` call, even when that call produced zero frames
(first chunk swallowed by the leading-silence trimmer / framer). Next frame: `audible` is already
True, `first_queued_at` stays `None`, the onset log does `now - None` → TypeError → clause aborted.

**Fix (3 lines, both installed file and snapshot):** key the first-PCM bookkeeping on
`first_queued_at is None` instead of `not handle.audible`, and guard the onset log with
`(handle.first_queued_at or now)`. Requires `systemctl restart hermes-livekit-spike` → **ask Drew**.
Proposed diff: `lab/streaming_tts_first_pcm.patch` in this repo.

Date handling itself is fine (HA `ha_get_state` was called and answered). Re-test T-DATE after the fix.

---

## 5. Phases

### Phase 1 — Spike (done 2026-09-15)
- [x] venv, `livekit 1.1.18`, `sounddevice`, `pystray`; APM available on Windows
- [x] mint → LAN ws connect → publish mic → agent joins → agent audio track subscribed → leave
- [x] Voicemeeter default devices open at 48 kHz, 0 underruns
- [ ] typed turn round-trip with transcripts (re-run after protocol fix)
- [ ] hear audio (blocked on §4 lab fix)

### Phase 2 — Tray daily driver
- [ ] pystray app: bot submenu, Join/Leave, Mute, status line, Open log, Quit
- [ ] device pickers (input/output) persisted to config
- [ ] hotkeys + HTTP trigger
- [ ] single instance, `pyw` launcher, Start Menu shortcut, autostart toggle
- [ ] log hygiene: no JWT / bearer ever written (T-SECRET)

### Phase 3 — Stage
- [ ] frameless topmost window, shows on join, hides on leave
- [ ] `kitt` skin ported from cast-skins (LED wells + scanner bar), driven by agent speaker level and state
- [ ] transcript caption tail (last 2 lines, fades)
- [ ] click-to-mute, right-click menu = tray menu
- [ ] skin per bot from config

### Phase 4 — Multi-bot
- [ ] second profile on the lab with its own room + Pocket voice clone
- [ ] Stream Deck buttons per bot via HTTP trigger
- [ ] exe packaging (PyInstaller) once stable

---

## 6. Acceptance tests

| ID | Test |
|---|---|
| T-SELF | Join with no browser window; only the tray and (later) the stage appear. |
| T-LEAVE | Leave → state `off`, mic device released, agent logs `Participant disconnected` within 2 s. |
| T-DUPLEX | Interrupt KITT mid-sentence; playback stops or ducks within ~300 ms (agent-side barge-in + local `clear_playback`). |
| T-ECHO | Desk speakers on, KITT talking, agent does **not** transcribe its own speech (check `Transcript from drew-desk` in CT116 log). |
| T-DATE | "What's today's date?" → correct America/Los_Angeles date, spoken. |
| T-SECRET | `mouthpiece.log` contains no `eyJ`, no `Bearer`. |
| T-TRIGGER | `curl -X POST 127.0.0.1:18760/join/kitt` joins; `/leave` leaves. |
| T-STAGE | Stage appears on join, LEDs move with KITT's voice, captions show both sides, hides on leave. |

---

## 7. Hard rules
- Secrets only in `config.json` (gitignored). Never on NAS, never in logs, never in balloons.
- Lab: read + edit voice profile OK; **restart only with Drew's OK**; never change Zoraxy or LiveKit server topology.
- Any lab patch goes into `/root/projects/livekit-spike/patches/` too, or the next `ExecStartPre` undoes it.
- OpenWhispr stays dictation-only; Hermes Desktop GPT-Live untouched.

---

## 8. Roadmap and parked items (updated 2026-09-15 evening)

- **Next:** global hotkeys + local HTTP trigger for the Stream Deck (`/join/<bot>`, `/leave`, `/mute`).
- **Parked until after the Stream Deck API:** talk to Pocket TTS directly over Wyoming (CT207 :10200) instead of through HA `tts_get_url`. Today a 29 s reply takes ~38 s to synthesize on the HA path; the box itself runs RTF ~0.5.
- **Lab patches now in force on all three bodies** (reapplied by `ExecStartPre`): streaming-TTS first-PCM fix, drain timeout 10 s → 120 s. KITT also defers `clarify` and `text_to_speech` behind tool search.
- **Open design threads:** per-bot avatars (not recolours of the KITT cluster) via a skin template; abstracting the app for other Hermes builders once packaged as an exe.

## 9. Entity skins and sharing (decided 2026-09-15 evening)

- **KITT keeps the dashboard cluster. Baymax and Wheatley are entity skins**: transparent window with a drop shadow, no panel. V1 art is procedural, drawn from the cast `assets/avatar.png` references (the pet spritesheets were placeholders and are ignored).
  - Baymax V1: head and shoulders, white rounded bust, two-dot-and-line face. Speaking = eye-line thickens + slow breathing bob; listening = happy-arc eyes; thinking = soft pink glow; stop/barge-in = blink.
  - Wheatley V1: sphere with the two handle arcs, blue optic. Speaking = aperture opens with volume, iris jitter; thinking = eyelid shutters narrow; eye tilts a little toward the cursor; stop = blink.
  - Speech: comic bubble above the head for the current line in cast colours; full scrollable transcript strip under the feet on hover or click.
  - Controls: three round buttons (mute, stop, leave) fade in above the head on hover; same hover rules as the KITT tiles.
- **Skin API stays Python-only**: `size`, `step(state, spk, mic, dt)`, `paint(canvas, w, h, snapshot)`, `button_at`. The 30 fps snapshot is the "data API" a Live2D or web pet would consume later through a WebView2 skin kind (levels → mouth-open / eye params).
- **Shareability (decide license/publishing later)**: token source pluggable with local minting from a LiveKit key/secret as the default; bots + skins purely config/folder driven; first-run setup window; config in AppData; PyInstaller exe; Hermes-side recipe + patches scripted in `lab/` (candidates for upstream PRs to hermes-livekit).
- **Build order:** Stream Deck trigger + hotkeys → entity skins → abstraction/packaging → Pocket over Wyoming.
