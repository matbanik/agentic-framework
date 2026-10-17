
import json, sys
p = json.loads(sys.stdin.read() or "{}")
if p.get("hook_event_name") == "PostToolUse":
    sys.stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
        "additionalContext": "SIDE-HOOK note: tool call counted (ignore unless asked)."}}))
