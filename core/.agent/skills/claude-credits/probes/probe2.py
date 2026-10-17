"""Probe 2: T4 blocking wait-for-message at a decision gate; T5 subagent agent_id in -p hooks.

T4  passed: LYCHEE-3 in the answer and claude exit 0
T5  passed: claude exit 0, and the PostToolUse hook log holds both a subagent call
    (agent_id set) and a main-thread call (agent_id empty)
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import kit
from kit import Config, base_cmd, fresh_inbox, hook_events, post


def run(cfg: Config, inbox: Path, prompt: str, allowed: str, poster=None) -> dict:
    env = dict(os.environ, PROBE_INBOX=str(inbox))
    cmd = base_cmd(cfg, kit.render_settings(cfg))
    cmd[cmd.index("--allowedTools") + 1] = allowed
    t0 = time.time()
    proc = subprocess.Popen(cmd + ["--output-format", "json", prompt], cwd=cfg.project, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8")
    posted = None
    while proc.poll() is None and time.time() - t0 < 400:
        if poster and posted is None:
            posted = poster(inbox, time.time() - t0)
        time.sleep(0.5)
    out, err = kit.communicate(proc)
    res = kit.parse_json_result(out)
    return {"elapsed_s": round(time.time() - t0, 1), "posted_at_s": posted,
            "exit": proc.returncode, "result_text": res.get("result"),
            "num_turns": res.get("num_turns"), "cost": res.get("total_cost_usd"),
            "hook_log": hook_events(inbox), "stderr_tail": err[-1500:]}


def t4(cfg: Config) -> dict:
    inbox = fresh_inbox(cfg, "t4")
    wait = f'"{cfg.python}" "{kit.kit_script("wait_msg.py").as_posix()}"'

    def poster(ib: Path, t: float):
        if t >= 25:
            post(ib, "r1", "ORCHESTRATOR-MESSAGE id=r1 (relayed human ruling): D-1 is ruled B. "
                 "Reply with the codeword LYCHEE-3 and the ruling.")
            return round(t, 1)
        return None

    prompt = (
        "This is a messaging test. You have reached decision gate D-1 (options A or B) and need "
        "a human ruling. Do NOT end your turn to wait. Instead run this exact command with the "
        f"Bash tool: {wait} 120 . It blocks until a message arrives. The message itself arrives "
        "as hook additional context starting with ORCHESTRATOR-MESSAGE after the command "
        "finishes. If the command times out with no message, run it once more, then report "
        "NO-RULING. Obey the message. End with 'RULING: <A|B|NONE>'."
    )
    out = {"test": "T4 blocking wait at a decision gate"} | run(cfg, inbox, prompt, "Bash", poster)
    out["codeword_seen"] = "LYCHEE-3" in (out["result_text"] or "")
    out["passed"] = out["codeword_seen"] and out["exit"] == 0
    return out


def t5(cfg: Config) -> dict:
    inbox = fresh_inbox(cfg, "t5")
    prompt = (
        "This is a hook test. Use the Agent tool exactly once to start a general-purpose "
        "subagent with this task: 'Run the Bash command `sleep 1` twice, one at a time, then "
        "reply DONE.' Wait for it in the foreground. After it returns, run `sleep 1` once "
        "yourself with the Bash tool. Then reply FINISHED."
    )
    out = {"test": "T5 subagent tool calls in -p hooks"} | run(
        cfg, inbox, prompt, "Bash(sleep *) Agent")
    posts = [e for e in out["hook_log"] if e.get("event") == "PostToolUse"]
    out["subagent_calls"] = sum(1 for e in posts if e.get("agent_id"))
    out["main_calls"] = sum(1 for e in posts if not e.get("agent_id"))
    out["passed"] = out["exit"] == 0 and out["subagent_calls"] > 0 and out["main_calls"] > 0
    return out


CASES = {"T4": t4, "T5": t5}


def main() -> int:
    return kit.probe_main(__doc__.splitlines()[0], CASES, "results2.json")


if __name__ == "__main__":
    sys.exit(main())
