# Hermes side of Mouthpiece

Everything the client needs from the Hermes box (CT116 here) and the Pocket TTS box (CT207).
These are the scripts used to build the KITT / Baymax / Wheatley bodies on 2026-09-15; adapt paths.

## One voice body per bot
`wire_voice_body.sh` — clones a lean profile from `voice`, restores what `hermes profile create --clone-from`
strips (platform sections, LIVEKIT_* env, auth.json, plugins), sets the LiveKit room + agent name, the
Pocket voice, a SOUL (character SOUL + spoken rules), and a systemd unit modelled on the existing one.
Called as `wire <profile> <room> <DisplayName> <pocket_voice> <soul_source_profile>`.

Then in the profile's config.yaml:
- `agent.disabled_toolsets: [tts]` and `tools.tool_search.defer: [<defaults> + text_to_speech]` (`defer_tts_tool.sh`);
  the LiveKit platform ignores `platform_toolsets`, so this is the only way to keep the model off the
  `text_to_speech` tool (which otherwise makes it speak twice).
- `display.tool_progress: off`, `display.busy_ack_detail: false` — keeps tool names and busy pings out of the room.
- SOUL line: "Date or time questions: call ha_get_state on sensor.date_time_iso directly."
- Run the SOUL past `tools/threat_patterns.py`: phrases like "pretend to be" get the whole file silently blocked.

## Gateway patches (hermes-livekit 0.4.0 / hermes 0.21.x)
Applied by an `ExecStartPre` reapply script on every body unit so `hermes update` cannot undo them:
1. `streaming_tts_first_pcm.patch` (../) — first-PCM bookkeeping keyed on `first_queued_at is None`;
   without it every spoken reply aborts with `float - NoneType`.
2. `fix_drain_timeout.sh` — `gateway/run_turn.py` `wait_complete(timeout=10.0)` → 120 s; otherwise replies
   longer than ~8 s of audio are cut off and replayed from the start.
3. `apply_stts_clause_hook.py` — publishes each synthesized clause as a partial transcript so the client can
   caption as the audio starts.

## Pocket TTS voices
`install_pocket_voices.sh` — trim / mono / 24 kHz / gain, copy into the voices dir, add to `preload_voices`,
restart the container, verify `Found N custom voice(s)` and no `fallback`. Always `ffmpeg -nostdin` in scripts fed
over stdin.
