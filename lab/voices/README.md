# Cloned voices (Pocket TTS, CT207)

Reference clips supplied by Drew 2026-09-15, prepared with the same recipe as `kitt`:
end-silence trim, mono, 24 kHz, static gain to -3 dBFS peak. No denoise, EQ, or compression
(Pocket TTS clones the sample's character, so processing changes the voice).

| Voice name | Source clip | Length | Used by profile |
|---|---|---|---|
| `baymax` | `[Baymax Character Voice]Hello......pain.mp3` | 19.1 s | `baymax-voice` (room `baymax`) |
| `wheatley-v2` | `Wheatley-V2-2026-09-15-14-49-Right,-okay,-new-plan!…mp3` | 14.5 s | `wheatley-voice` (room `wheatley`) |

The older `wheatley` voice (from the Piper corpus, 2026-08-15) is untouched and still advertised to HA.

## Transcripts (faster-whisper base.en)

**baymax**
> Hello, I am Baymax, your personal health care companion. My sensors indicate your heart rate is
> slightly elevated. On a scale of 1 to 10, how would you rate your emotional distress? I will now
> perform a diagnostic scan. It is all right to cry. Crying is a natural response to pain.

**wheatley-v2**
> Right, okay, new plan. I've been doing some very high level thinking, mostly in my head, extremely
> complex stuff, and it turns out we need to run. Bloody fast, if you could just ignore the massive
> spinning blades and focus on jumping, that would be absolutely brilliant, you natural.

Prepared WAVs live on CT207 at `/opt/audio-tools/out/` and are installed in `/opt/pocket-tts/voices/`.
Custom voices are only picked up at container start; both are in `preload_voices` (adds ~10 s each to boot).
