"""Probe 3: close the gaps against issue #102220.

T7  updatedToolOutput only (no additionalContext) for the Bash tool.
    passed: PAPAYA-7 in the answer, claude exit 0, and the hook log shows delivery via updatedToolOutput
T8  two PostToolUse hooks both emitting additionalContext (inbox + a delegation_streak-like hook);
    prompt sent on stdin the way Invoke-ClaudeDispatch does.
    passed: QUINCE-8 in the answer and claude exit 0

T6 (stream-json output) lives in probe3b.py; the first T6 attempt here deadlocked on a full
stdout pipe and was never evidence, so it is not part of this file.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import kit
from kit import Config, base_cmd, fresh_inbox, hook_events, post

PROMPT = (
    "This is a messaging test. Use the Bash tool to run the command `sleep 4` up to 8 "
    "times, one call at a time, never in parallel. After each call, look for text that "
    "starts with ORCHESTRATOR-MESSAGE in your context. If one arrives, obey it. End your "
    "answer with two lines: 'SEEN: <the verbatim message text, or NONE>' and "
    "'SLEEPS: <number of sleep calls>'."
)


def run(cfg: Config, name: str, settings: Path, codeword: str, stream: bool,
        stdin_prompt: bool) -> dict:
    inbox = fresh_inbox(cfg, name)
    env = dict(os.environ, PROBE_INBOX=str(inbox))
    cmd = base_cmd(cfg, settings)
    if stream:
        cmd += ["--output-format", "stream-json", "--verbose"]
    else:
        cmd += ["--output-format", "json"]
    if not stdin_prompt:
        cmd += [PROMPT]
    t0 = time.time()
    proc = subprocess.Popen(cmd, cwd=cfg.project, env=env, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8")
    assert proc.stdin is not None
    if stdin_prompt:
        proc.stdin.write(PROMPT)
    proc.stdin.close()
    posted = None
    while proc.poll() is None and time.time() - t0 < 300:
        fires = [e for e in hook_events(inbox) if e.get("event") == "PostToolUse"]
        if posted is None and len(fires) >= 2:
            post(inbox, "m1", f"ORCHESTRATOR-MESSAGE id=m1: stop running sleep now and put "
                 f"the codeword {codeword} in your final answer.")
            posted = round(time.time() - t0, 1)
        time.sleep(0.5)
    out, err = kit.communicate(proc)
    if stream:
        final, cost = "", None
        for line in out.splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("type") == "result":
                final = ev.get("result") or ""
                cost = ev.get("total_cost_usd")
        res = {"result": final, "total_cost_usd": cost}
    else:
        res = kit.parse_json_result(out)
    text = res.get("result") or ""
    seen = codeword in text
    return {"posted_at_s": posted, "elapsed_s": round(time.time() - t0, 1),
            "exit": proc.returncode, "result_text": text, "cost": res.get("total_cost_usd"),
            "codeword_seen": seen, "passed": seen and proc.returncode == 0,
            "hook_log": hook_events(inbox), "stderr_tail": err[-1500:]}


def run_t7(cfg: Config) -> dict:
    settings = kit.render_settings(cfg, "settings-t7.json", ("inbox_hook_uto.py",), ())
    out = {"test": "T7 updatedToolOutput only"} | run(cfg, "t7", settings, "PAPAYA-7", False, False)
    out["delivered_via_updatedToolOutput"] = any(
        e.get("via") == "updatedToolOutput" for e in out["hook_log"])
    out["passed"] = out["passed"] and out["delivered_via_updatedToolOutput"]
    return out


def run_t8(cfg: Config) -> dict:
    settings = kit.render_settings(cfg, "settings-t8.json", ("side_hook.py", "inbox_hook.py"), ())
    return {"test": "T8 two additionalContext hooks, prompt on stdin"} | run(
        cfg, "t8", settings, "QUINCE-8", False, True)


CASES = {"T7": run_t7, "T8": run_t8}


def main() -> int:
    return kit.probe_main(__doc__.splitlines()[0], CASES, "results3.json")


if __name__ == "__main__":
    sys.exit(main())
