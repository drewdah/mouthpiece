cd /opt/audio-tools
# ffmpeg eats the script from stdin when fed via bash -s: always -nostdin here.
prep() {
  peak=$(ffmpeg -nostdin -v error -i "$1" -af volumedetect -f null - 2>&1 | sed -n 's/.*max_volume: \(-\?[0-9.]*\) dB.*/\1/p' | head -1)
  gain=$(awk -v p="${peak:-0}" 'BEGIN{printf "%.2f", -3.0 - p}')
  ffmpeg -nostdin -v error -y -i "$1" -af "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.15,areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.15,areverse,volume=${gain}dB" -ac 1 -ar 24000 -sample_fmt s16 "$2" || return 1
  echo "$1: peak ${peak} dB -> gain ${gain} dB; out $(ffprobe -v error -show_entries format=duration -of csv=p=0 "$2")s"
}
prep raw/baymax_ref.mp3 out/baymax.wav && prep raw/wheatley_v2_ref.mp3 out/wheatley-v2.wav || { echo PREP FAILED; exit 1; }
cp -a out/baymax.wav /opt/pocket-tts/voices/baymax.wav
cp -a out/wheatley-v2.wav /opt/pocket-tts/voices/wheatley-v2.wav
/opt/audio-tools/venv/bin/python3 - <<'PYX'
import json
p="/opt/pocket-tts/options.json"; o=json.load(open(p))
for v in ("baymax","wheatley-v2"):
    if v not in o["preload_voices"]: o["preload_voices"].append(v)
json.dump(o, open(p,"w"), indent=2); print("preload_voices:", o["preload_voices"])
PYX
ls -la /opt/pocket-tts/voices/ | grep -E "baymax|wheatley"
docker restart pocket-tts >/dev/null </dev/null && echo "restarted"
START=$(docker inspect pocket-tts --format '{{.State.StartedAt}}')
for i in $(seq 1 36); do sleep 5; docker logs --since "$START" pocket-tts 2>&1 | grep -q -i -E "wyoming server (is )?ready|listening on|serving on" && break; done
docker logs --since "$START" pocket-tts 2>&1 | grep -i -E "custom voice|preload|fallback|weights from|error|ready|listening" | tail -10
