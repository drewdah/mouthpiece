set -e
V=/root/.hermes/profiles/voice
wire() { # prof room name voice soulsrc
  P=/root/.hermes/profiles/$1; ROOM=$2; NAME=$3; VOICE=$4; SOUL=/root/.hermes/profiles/$5/SOUL.md
  echo "### $1"
  [ -f $V/auth.json ] && cp -a $V/auth.json $P/auth.json
  [ -d $V/plugins ] && [ ! -d $P/plugins ] && cp -a $V/plugins $P/plugins
  [ -d $V/bin ] && [ ! -d $P/bin ] && cp -a $V/bin $P/bin
  # .env: livekit creds from voice, own room/name/voice, realtime off
  sed -i -E '/^(LIVEKIT_URL|LIVEKIT_API_KEY|LIVEKIT_API_SECRET|LIVEKIT_ALLOW_ALL_USERS)=/d' $P/.env
  grep -E '^(LIVEKIT_URL|LIVEKIT_API_KEY|LIVEKIT_API_SECRET|LIVEKIT_ALLOW_ALL_USERS)=' $V/.env >> $P/.env
  sed -i -E "s/^HERMES_REALTIME_ENABLED=.*/HERMES_REALTIME_ENABLED=false/" $P/.env
  grep -q '^LIVEKIT_ROOM=' $P/.env && sed -i -E "s/^LIVEKIT_ROOM=.*/LIVEKIT_ROOM=$ROOM/" $P/.env || echo "LIVEKIT_ROOM=$ROOM" >> $P/.env
  grep -q '^LIVEKIT_AGENT_NAME=' $P/.env && sed -i -E "s/^LIVEKIT_AGENT_NAME=.*/LIVEKIT_AGENT_NAME=$NAME/" $P/.env || echo "LIVEKIT_AGENT_NAME=$NAME" >> $P/.env
  grep -q '^POCKET_TTS_VOICE=' $P/.env && sed -i -E "s/^POCKET_TTS_VOICE=.*/POCKET_TTS_VOICE=$VOICE/" $P/.env || echo "POCKET_TTS_VOICE=$VOICE" >> $P/.env
  # config.yaml: tts voice + platforms block
  ROOM=$ROOM NAME=$NAME VOICE=$VOICE P=$P /usr/local/lib/hermes-agent/venv/bin/python3 - <<'PYX'
import os, re
p=os.environ["P"]+"/config.yaml"; s=open(p).read()
s=re.sub(r"(pocket_tts:\n(?:      .*\n)*?      voice: )kitt", r"\g<1>"+os.environ["VOICE"], s, count=1)
assert not re.search(r"^platforms:", s, re.M), "top-level platforms block already present"
s=s.rstrip("\n")+f"""
platforms:
  realtime:
    enabled: false
  livekit:
    enabled: true
    extra:
      url: ${{LIVEKIT_URL}}
      api_key: ${{LIVEKIT_API_KEY}}
      api_secret: ${{LIVEKIT_API_SECRET}}
      room: {os.environ["ROOM"]}
      allow_all_users: true
      agent_name: {os.environ["NAME"]}
      silence_duration: 0.5
      tts_trim_leading_silence: true
  homeassistant:
    enabled: false
"""
open(p,"w").write(s)
print("config: voice ->", os.environ["VOICE"], "| room", os.environ["ROOM"], "| agent", os.environ["NAME"])
PYX
  # SOUL: character soul + the voice profile's spoken rules
  { cat $SOUL; echo; echo; echo "# Voice body ($NAME on LiveKit room '$ROOM')"; echo; echo "You are on a **voice call** with Drew. Everything below overrides formatting habits above."; echo; sed -n '/^## Spoken rules (hard)/,/^## /p' $V/SOUL.md | sed '$d'; } > $P/SOUL.md
  grep -q "Spoken rules" $P/SOUL.md && echo "SOUL: $(wc -c < $P/SOUL.md) bytes (character + spoken rules)"
  cat > $P/profile.yaml <<YML
description: LiveKit voice body for $NAME (room $ROOM, Pocket voice $VOICE)
description_auto: false
ui_meta:
  hermes-bots:
    title: $NAME Voice
    hidden: true
    shape: hexagon
    custom: true
YML
  # systemd unit modelled on hermes-livekit-spike.service
  U=/etc/systemd/system/hermes-$1.service
  sed -e "s#HERMES_HOME=/root/.hermes/profiles/voice#HERMES_HOME=$P#" -e "s#-p voice gateway#-p $1 gateway#" -e "s#^Description=.*#Description=Hermes voice body: $NAME (LiveKit room $ROOM)#" /etc/systemd/system/hermes-livekit-spike.service > $U
  grep -E "HERMES_HOME|ExecStart=" $U
}
wire baymax-voice baymax Baymax baymax baymax
wire wheatley-voice wheatley Wheatley wheatley-v2 wheatley
systemctl daemon-reload
systemctl enable --now hermes-baymax-voice.service hermes-wheatley-voice.service >/dev/null 2>&1
sleep 12
for u in hermes-baymax-voice hermes-wheatley-voice; do echo "### $u: $(systemctl is-active $u)"; journalctl -u $u --since "30 seconds ago" --no-pager | grep -i -E "livekit|error|traceback|platform|skipp|realtime" | cut -c26-200 | tail -6; done
free -m | sed -n 2p
