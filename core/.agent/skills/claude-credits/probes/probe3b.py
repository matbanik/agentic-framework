"""Probe 3b: T6b. T6 rerun with a stdout drain thread (the first T6 deadlocked on a full pipe).

T6b  additionalContext with --output-format stream-json --verbose.
     passed: GUAVA-6 in the final result event and claude exit 0
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


def run_t6b(cfg: Config) -> dict:
    inbox = fresh_inbox(cfg, "t6b")
    settings = kit.render_settings(cfg, "settings-t6.json", ("inbox_hook.py",), ())
    env = dict(os.environ, PROBE_INBOX=str(inbox))
    cmd = base_cmd(cfg, settings) + ["--output-format", "stream-json", "--verbose", PROMPT]
    t0 = time.time()
    proc = subprocess.Popen(cmd, cwd=cfg.project, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8")
    lines: list[str] = []
    th = threading.Thread(target=lambda: lines.extend(proc.stdout), daemon=True)
    th.start()
    posted = None
    while proc.poll() is None and time.time() - t0 < 300:
        fires = [e for e in hook_events(inbox) if e.get("event") == "PostToolUse"]
        if posted is None and len(fires) >= 2:
            post(inbox, "m1", "ORCHESTRATOR-MESSAGE id=m1: stop running sleep now and put the "
                 "codeword GUAVA-6 in your final answer.")
            posted = round(time.time() - t0, 1)
        time.sleep(0.5)
    if proc.poll() is None:
        proc.kill()
    proc.wait(timeout=60)
    th.join(timeout=10)
    final, cost, attach = "", None, []
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "result":
            final, cost = ev.get("result") or "", ev.get("total_cost_usd")
        if "GUAVA-6" in line and ev.get("type") != "result":
            attach.append({"type": ev.get("type"), "subtype": ev.get("subtype"),
                           "snippet": line[:300]})
    seen = "GUAVA-6" in final
    return {"test": "T6b additionalContext, stream-json output", "posted_at_s": posted,
            "elapsed_s": round(time.time() - t0, 1), "exit": proc.returncode,
            "result_text": final, "cost": cost, "codeword_seen": seen,
            "passed": seen and proc.returncode == 0,
            "stream_events_mentioning_codeword": attach, "hook_log": hook_events(inbox)}


CASES = {"T6b": run_t6b}


def main() -> int:
    return kit.probe_main(__doc__.splitlines()[0], CASES, "results3b.json")


if __name__ == "__main__":
    sys.exit(main())
