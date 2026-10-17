"""Probe hook: deliver orchestrator messages from an inbox directory to a running claude -p.

Handles PostToolUse (additionalContext) and Stop (decision=block with reason).
Inbox protocol: the orchestrator writes <inbox>/<id>.tmp then renames it to <id>.msg
(atomic on one volume). The hook claims each .msg by renaming it to .claimed (only one
claimer wins), emits it, then moves it to <inbox>/delivered/ and appends an ack line.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path


def log(inbox: Path, record: dict) -> None:
    record["utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    with open(inbox / "hook-log.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def claim(inbox: Path, pattern: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for msg in sorted(inbox.glob(pattern)):
        claimed = msg.with_suffix(".claimed")
        try:
            msg.rename(claimed)
        except OSError:
            continue  # another hook call claimed it
        text = claimed.read_text(encoding="utf-8")
        delivered = inbox / "delivered"
        delivered.mkdir(exist_ok=True)
        claimed.rename(delivered / msg.name)
        out.append((msg.stem, text))
    return out


def main() -> int:
    inbox = Path(os.environ.get("PROBE_INBOX", ""))
    if not inbox.is_dir():
        return 0
    payload = json.loads(sys.stdin.read() or "{}")
    event = payload.get("hook_event_name")
    log(inbox, {"event": event, "tool": payload.get("tool_name"),
                "session": payload.get("session_id"), "agent_id": payload.get("agent_id"), "agent_type": payload.get("agent_type"),
                "stop_hook_active": payload.get("stop_hook_active")})
    if event == "PostToolUse":
        msgs = claim(inbox, "*.msg")
        if msgs:
            text = "\n".join(t for _, t in msgs)
            log(inbox, {"delivered": [i for i, _ in msgs], "via": "PostToolUse"})
            sys.stdout.write(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PostToolUse", "additionalContext": text}}))
    elif event == "Stop":
        msgs = claim(inbox, "*.stopmsg")
        if msgs:
            text = "\n".join(t for _, t in msgs)
            log(inbox, {"delivered": [i for i, _ in msgs], "via": "Stop"})
            sys.stdout.write(json.dumps({"decision": "block", "reason": text}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
