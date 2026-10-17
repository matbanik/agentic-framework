"""Probe 3c: T6c. Hook additionalContext with stream-json INPUT and output (sdk-cli style, #102220).

T6c  passed: FIG-6C in the final result event and claude exit 0
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

import kit
from kit import Config, base_cmd, fresh_inbox, hook_events, post
from probe3 import PROMPT


def run_t6c(cfg: Config) -> dict:
    inbox = fresh_inbox(cfg, "t6c")
    settings = kit.render_settings(cfg, "settings-t6.json", ("inbox_hook.py",), ())
    env = dict(os.environ, PROBE_INBOX=str(inbox))
    cmd = base_cmd(cfg, settings) + ["--input-format", "stream-json", "--output-format",
                                     "stream-json", "--verbose"]
    t0 = time.time()
    proc = subprocess.Popen(cmd, cwd=cfg.project, env=env, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8")
    lines: list[str] = []
    th = threading.Thread(target=lambda: lines.extend(proc.stdout), daemon=True)
    th.start()
    proc.stdin.write(json.dumps({"type": "user", "message": {"role": "user",
                                 "content": PROMPT}}) + "\n")
    proc.stdin.flush()
    posted = None
    while proc.poll() is None and time.time() - t0 < 300:
        fires = [e for e in hook_events(inbox) if e.get("event") == "PostToolUse"]
        if posted is None and len(fires) >= 2:
            post(inbox, "m1", "ORCHESTRATOR-MESSAGE id=m1: stop running sleep now and put the "
                 "codeword FIG-6C in your final answer.")
            posted = round(time.time() - t0, 1)
        if any('"type":"result"' in line for line in list(lines)):
            break
        time.sleep(0.5)
    try:
        proc.stdin.close()
    except OSError:
        pass
    try:
        proc.wait(timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    th.join(timeout=10)
    final, cost = "", None
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "result":
            final, cost = ev.get("result") or "", ev.get("total_cost_usd")
    seen = "FIG-6C" in final
    return {"test": "T6c additionalContext, stream-json input and output", "posted_at_s": posted,
            "elapsed_s": round(time.time() - t0, 1), "exit": proc.returncode,
            "result_text": final, "cost": cost, "codeword_seen": seen,
            "passed": seen and proc.returncode == 0, "hook_log": hook_events(inbox)}


CASES = {"T6c": run_t6c}


def main() -> int:
    return kit.probe_main(__doc__.splitlines()[0], CASES, "results3c.json")


if __name__ == "__main__":
    sys.exit(main())
