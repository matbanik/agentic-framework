"""Live probe: can an orchestrator pass messages into a running headless claude -p?

T1  PostToolUse hook inbox  -> additionalContext mid-run.   passed: PINEAPPLE-42 in the answer
T2  Stop hook inbox         -> decision=block reason.        passed: MANGO-7 in the answer
T3  stream-json stdin       -> second user message mid-turn. passed: KIWI-9 in the answer

Each case also needs claude to exit 0. The project dir (--project) is where claude runs, with
--setting-sources user so the project's own hooks do not load; the probe hooks come from the
settings file rendered into OUT. Model haiku, subscription auth.  <!-- model-slug-ok: the probe's own fixed CLI alias for the cheapest model, not a routing pin -->
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


def run_t1(cfg: Config) -> dict:
    inbox = fresh_inbox(cfg, "t1")
    settings = kit.render_settings(cfg)
    prompt = (
        "This is a messaging test. Use the Bash tool to run the command `sleep 4` up to 8 "
        "times, one call at a time, never in parallel. After each call, look for text that "
        "starts with ORCHESTRATOR-MESSAGE in your context (it arrives as hook additional "
        "context after a tool call). If one arrives, obey it. End your answer with two lines: "
        "'SEEN: <the verbatim message text, or NONE>' and 'SLEEPS: <number of sleep calls>'."
    )
    env = dict(os.environ, PROBE_INBOX=str(inbox))
    t0 = time.time()
    proc = subprocess.Popen(base_cmd(cfg, settings) + ["--output-format", "json", prompt],
                            cwd=cfg.project, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8")
    posted_at = None
    while proc.poll() is None and time.time() - t0 < 300:
        fires = [e for e in hook_events(inbox) if e.get("event") == "PostToolUse"]
        if posted_at is None and len(fires) >= 2:
            post(inbox, "m1", "ORCHESTRATOR-MESSAGE id=m1: stop running sleep now and put the "
                 "codeword PINEAPPLE-42 in your final answer.")
            posted_at = time.time() - t0
        time.sleep(0.5)
    out, err = kit.communicate(proc)
    result = kit.parse_json_result(out)
    seen = "PINEAPPLE-42" in (result.get("result") or "")
    return {"test": "T1 PostToolUse additionalContext", "posted_at_s": posted_at,
            "elapsed_s": round(time.time() - t0, 1), "exit": proc.returncode,
            "result_text": result.get("result"), "num_turns": result.get("num_turns"),
            "cost": result.get("total_cost_usd"),
            "codeword_seen": seen, "passed": seen and proc.returncode == 0,
            "hook_log": hook_events(inbox), "stderr_tail": err[-1500:]}


def run_t2(cfg: Config) -> dict:
    inbox = fresh_inbox(cfg, "t2")
    settings = kit.render_settings(cfg)
    post(inbox, "s1", "ORCHESTRATOR-MESSAGE id=s1: before you finish, also reply with the "
         "codeword MANGO-7 on its own line.", suffix=".stopmsg")
    prompt = "Reply with the single word READY. Do not use any tools."
    env = dict(os.environ, PROBE_INBOX=str(inbox))
    t0 = time.time()
    proc = subprocess.run(base_cmd(cfg, settings) + ["--output-format", "json", prompt],
                          cwd=cfg.project, env=env, capture_output=True, text=True,
                          encoding="utf-8", timeout=300)
    result = kit.parse_json_result(proc.stdout)
    seen = "MANGO-7" in (result.get("result") or "")
    return {"test": "T2 Stop hook block reason", "elapsed_s": round(time.time() - t0, 1),
            "exit": proc.returncode, "result_text": result.get("result"),
            "num_turns": result.get("num_turns"), "cost": result.get("total_cost_usd"),
            "codeword_seen": seen, "passed": seen and proc.returncode == 0,
            "hook_log": hook_events(inbox), "stderr_tail": proc.stderr[-1500:]}


def run_t3(cfg: Config) -> dict:
    settings = kit.render_empty_settings(cfg)
    cmd = base_cmd(cfg, settings) + ["--input-format", "stream-json", "--output-format",
                                     "stream-json", "--verbose"]
    t0 = time.time()
    proc = subprocess.Popen(cmd, cwd=cfg.project, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8")
    events: list[dict] = []
    lock = threading.Lock()

    def reader() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            ev["_t"] = round(time.time() - t0, 1)
            with lock:
                events.append(ev)

    th = threading.Thread(target=reader, daemon=True)
    th.start()

    def send(text: str) -> None:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps({"type": "user", "message": {"role": "user",
                                     "content": text}}) + "\n")
        proc.stdin.flush()

    send("This is a messaging test. Use the Bash tool to run `sleep 4` up to 8 times, one "
         "call at a time. After each call, check whether a new user message starting with "
         "ORCHESTRATOR-MESSAGE has arrived; if so, obey it. End with 'SEEN: <text or NONE>' "
         "and 'SLEEPS: <count>'.")
    injected_at = None
    while time.time() - t0 < 300:
        with lock:
            tool_uses = sum(1 for e in events if e.get("type") == "assistant" and any(
                c.get("type") == "tool_use" for c in e.get("message", {}).get("content", [])))
            results = sum(1 for e in events if e.get("type") == "result")
        if injected_at is None and tool_uses >= 2:
            send("ORCHESTRATOR-MESSAGE id=m3: stop running sleep now and put the codeword "
                 "KIWI-9 in your final answer.")
            injected_at = round(time.time() - t0, 1)
        if results >= 2 or (results >= 1 and injected_at is None and tool_uses == 0):
            break
        if proc.poll() is not None:
            break
        time.sleep(0.5)
    try:
        assert proc.stdin is not None
        proc.stdin.close()
    except OSError:
        pass
    try:
        proc.wait(timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
    th.join(timeout=5)
    timeline = []
    for e in events:
        kind = e.get("type")
        if kind == "assistant":
            for c in e.get("message", {}).get("content", []):
                if c.get("type") == "tool_use":
                    timeline.append((e["_t"], "tool_use", c.get("input", {}).get("command")))
                elif c.get("type") == "text":
                    timeline.append((e["_t"], "text", c.get("text", "")[:300]))
        elif kind == "user":
            content = e.get("message", {}).get("content")
            if isinstance(content, str):
                timeline.append((e["_t"], "user_echo", content[:200]))
        elif kind == "result":
            timeline.append((e["_t"], "result", (e.get("result") or "")[:400]))
    seen = any("KIWI-9" in str(x[2]) for x in timeline if x[1] != "user_echo")
    return {"test": "T3 stream-json stdin second message", "injected_at_s": injected_at,
            "exit": proc.returncode, "timeline": timeline,
            "codeword_seen": seen, "passed": seen and proc.returncode == 0,
            "stderr_tail": (proc.stderr.read() if proc.stderr else "")[-1500:]}


CASES = {"T1": run_t1, "T2": run_t2, "T3": run_t3}


def main() -> int:
    return kit.probe_main(__doc__.splitlines()[0], CASES, "results.json")


if __name__ == "__main__":
    sys.exit(main())
