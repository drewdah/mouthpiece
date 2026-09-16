R=/usr/local/lib/hermes-agent
for p in baymax-voice wheatley-voice; do
  C=/root/.hermes/profiles/$p/config.yaml
  cd $R && ./venv/bin/python3 - "$C" <<'PYX' 2>&1 | grep -v -i "warning\|deprecat"
import sys, re, yaml
sys.path.insert(0, ".")
from tools.tool_search import _DEFAULT_DEFERRED_TOOLS
defer = sorted(set(_DEFAULT_DEFERRED_TOOLS) | {"text_to_speech"})
p = sys.argv[1]; s = open(p).read()
assert not re.search(r"^tools:", s, re.M), "top-level tools block exists; edit by hand"
block = "tools:\n  tool_search:\n    defer:\n" + "".join(f"      - {n}\n" for n in defer)
open(p, "w").write(s.rstrip("\n") + "\n" + block)
print(p.split("/")[-2], "-> tools.tool_search.defer =", len(defer), "names (defaults + text_to_speech)")
PYX
done
systemctl restart hermes-baymax-voice hermes-wheatley-voice; sleep 10
for u in hermes-baymax-voice hermes-wheatley-voice; do echo "$u: $(systemctl is-active $u)"; done
