set -e
C=/root/.hermes/profiles/voice/config.yaml
python3 - <<'PY'
p="/root/.hermes/profiles/voice/config.yaml"
s=open(p).read()
i=s.index("platform_toolsets:\n")
# realtime block: put clarify back
r=s.index("  realtime:\n", i); r_end=s.index("  livekit:\n", r)
rb=s[r:r_end]
if "    - clarify\n" not in rb:
    rb=rb.replace("  realtime:\n","  realtime:\n    - clarify\n",1)
# livekit block: remove clarify
l=r_end; l_end=s.index("  api_server:\n", l)
lb=s[l:l_end].replace("    - clarify\n","")
s=s[:r]+rb+lb+s[l_end:]
open(p,"w").write(s)
PY
sed -n '/^platform_toolsets:/,/^  api_server:/p' $C
systemctl restart hermes-livekit-spike
sleep 7
systemctl is-active hermes-livekit-spike
journalctl -u hermes-livekit-spike --since "15 seconds ago" --no-pager | grep -E "^.*Started|Traceback" | cut -c26-140 | tail -3
