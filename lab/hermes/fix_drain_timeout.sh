set -e
R=/usr/local/lib/hermes-agent; F=$R/gateway/run_turn.py
cp -a $F $F.bak-drain-$(date +%Y%m%d-%H%M%S)
sed -i 's/await _stts.wait_complete(timeout=10\.0)/await _stts.wait_complete(timeout=120.0)  # house patch: Pocket-TTS clause synthesis needs longer than 10s for long replies/' $F
grep -n "wait_complete(timeout=120.0)" $F | cut -c1-80
$R/venv/bin/python3 -m py_compile $F && echo "run_turn.py compiles"
# make it survive `hermes update` via the existing ExecStartPre reapply script
RP=/root/projects/livekit-spike/scripts/reapply-patches.sh
if ! grep -q "wait_complete(timeout=120.0)" $RP; then
  sed -i 's#^date -Iseconds > "$SPIKE/.patches-applied"#sed -i '"'"'s/await _stts.wait_complete(timeout=10\.0)/await _stts.wait_complete(timeout=120.0)  \# house patch: Pocket-TTS clause synthesis needs longer than 10s for long replies/'"'"' "$ROOT/gateway/run_turn.py" \&\& log "OK stts drain timeout 120s"\ndate -Iseconds > "$SPIKE/.patches-applied"#' $RP
  bash -n $RP && echo "reapply-patches.sh updated" && grep -n "drain timeout" $RP | cut -c1-90
fi
# quieter voice rooms for the bodies: no tool-progress / busy-ack notices
for p in baymax-voice wheatley-voice; do
  C=/root/.hermes/profiles/$p/config.yaml
  $R/venv/bin/python3 - "$C" <<'PYX'
import sys, re
p=sys.argv[1]; s=open(p).read()
i=s.index("display:\n"); j=s.index("\ndashboard:", i)
blk=s[i:j]
blk=re.sub(r"^  tool_progress: .*$", "  tool_progress: off", blk, flags=re.M)
blk=re.sub(r"^  busy_ack_detail: .*$", "  busy_ack_detail: false", blk, flags=re.M)
s=s[:i]+blk+s[j:]; open(p,"w").write(s)
print(p.split("/")[-2], "display:", re.findall(r"^  (tool_progress|busy_ack_detail): .*$", blk, flags=re.M))
PYX
done
systemctl restart hermes-baymax-voice hermes-wheatley-voice; sleep 10
for u in hermes-baymax-voice hermes-wheatley-voice; do echo "$u: $(systemctl is-active $u)"; done
