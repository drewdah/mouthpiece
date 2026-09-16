"""House patch: publish each streaming-TTS clause as a partial transcript so clients can show
the bot's words as the audio starts instead of after it ends. Idempotent (needle-checked).

Targets:
  /usr/local/lib/hermes-agent/gateway/streaming_tts_consumer.py       (upstream; calls the hook)
  .../site-packages/hermes_livekit/adapter.py + the reapply snapshot (implements the hook)
Installed at /root/projects/livekit-spike/patches/apply_stts_clause_hook.py and run by
reapply-patches.sh on every gateway start.
"""
import sys

R = "/usr/local/lib/hermes-agent"
CONSUMER = f"{R}/gateway/streaming_tts_consumer.py"
ADAPTERS = [
    f"{R}/venv/lib/python3.11/site-packages/hermes_livekit/adapter.py",
    "/root/projects/livekit-spike/patches/hermes_livekit_adapter.py",
]
NEEDLE = "on_streaming_tts_clause"


def patch_consumer():
    s = open(CONSUMER).read()
    if NEEDLE in s:
        print("OK consumer clause hook already patched")
        return
    old = '''        if not (cleaned := self._strip_markdown(clause).strip()):
            return
'''
    new = '''        if not (cleaned := self._strip_markdown(clause).strip()):
            return
        # house patch: let the adapter publish the clause text as a partial transcript (LiveKit bubble)
        _hook = getattr(self._adapter, "on_streaming_tts_clause", None)
        if _hook is not None:
            try:
                await _hook(self._chat_id, cleaned)
            except Exception as _hook_exc:
                logger.debug("streaming TTS clause hook failed: %s", _hook_exc)
'''
    assert old in s, "consumer anchor not found"
    open(CONSUMER, "w").write(s.replace(old, new, 1))
    print("PATCHED consumer clause hook")


ADAPTER_METHOD = '''
    # ---- house patch: clause-level partial transcripts for the LiveKit bubble ----
    async def on_streaming_tts_clause(self, chat_id: str, text: str) -> None:
        """Called by the streaming-TTS consumer for every clause it synthesises. Accumulates the
        spoken text for this reply and publishes it as a partial agent transcript so the client
        can caption the audio as it starts. Cleared by send() when the final text goes out."""
        acc = getattr(self, "_stts_clause_text", None)
        if acc is None:
            acc = self._stts_clause_text = {}
        joined = (acc.get(chat_id, "") + " " + (text or "")).strip()
        acc[chat_id] = joined
        try:
            await self._publish_agent_event("agent:agent-transcript", {"transcript": joined, "final": False})
        except Exception as exc:
            logger.debug("[%s] clause transcript publish failed: %s", self.name, exc)

    async def send(
'''


def patch_adapter(path):
    s = open(path).read()
    if NEEDLE in s:
        print(f"OK adapter hook already patched: {path}")
        return
    anchor = "\n    async def send(\n"
    assert s.count(anchor) == 1, f"send() anchor not unique in {path}"
    s = s.replace(anchor, ADAPTER_METHOD, 1)
    # clear the accumulator once the final text has been published
    old = '''            await self._publish_agent_event(
                "agent:agent-transcript", {"transcript": content, "final": True}
            )
'''
    new = '''            await self._publish_agent_event(
                "agent:agent-transcript", {"transcript": content, "final": True}
            )
            getattr(self, "_stts_clause_text", {}).pop(chat_id, None)  # house patch
'''
    assert old in s, f"send() transcript anchor not found in {path}"
    s = s.replace(old, new, 1)
    open(path, "w").write(s)
    print(f"PATCHED adapter hook: {path}")


patch_consumer()
for p in ADAPTERS:
    patch_adapter(p)
import py_compile
py_compile.compile(CONSUMER, doraise=True)
py_compile.compile(ADAPTERS[0], doraise=True)
print("compiled ok")
