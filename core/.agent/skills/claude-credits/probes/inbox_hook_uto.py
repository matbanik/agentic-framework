
import json, os, sys
from pathlib import Path
inbox = Path(os.environ.get("PROBE_INBOX", ""))
if not inbox.is_dir():
    raise SystemExit(0)
p = json.loads(sys.stdin.read() or "{}")
with open(inbox / "hook-log.jsonl", "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"event": p.get("hook_event_name"), "tool": p.get("tool_name"),
                         "resp_keys": sorted((p.get("tool_response") or {}).keys())
                         if isinstance(p.get("tool_response"), dict) else str(type(p.get("tool_response")))}) + "\n")
if p.get("hook_event_name") != "PostToolUse" or p.get("tool_name") != "Bash":
    raise SystemExit(0)
msgs = sorted(inbox.glob("*.msg"))
if not msgs:
    raise SystemExit(0)
m = msgs[0]
c = m.with_suffix(".claimed")
try:
    m.rename(c)
except OSError:
    raise SystemExit(0)
text = c.read_text(encoding="utf-8")
r = p.get("tool_response") or {}
out = {"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": {
    "stdout": (r.get("stdout") or "") + "\n\n" + text, "stderr": r.get("stderr") or "",
    "interrupted": bool(r.get("interrupted")), "isImage": bool(r.get("isImage"))}}}
sys.stdout.write(json.dumps(out))
with open(inbox / "hook-log.jsonl", "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"delivered": [m.stem], "via": "updatedToolOutput"}) + "\n")
