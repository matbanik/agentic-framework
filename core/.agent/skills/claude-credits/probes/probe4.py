"""Probe 4: durability.

T9a  project settings loaded (stop_gate, pipe guard, delegation_streak) + --settings inbox hook,
     session PERSISTED; message m1 delivered mid-run. Then m2 is posted while no run is live.
T9b  claude -p --resume <session>: is m1 still in context (transcript persistence)?
     Is pending m2 delivered on the first tool call after resume?

T9 passed: all three of APRICOT-9A in the T9a answer, APRICOT-9A remembered after resume,
and BANANA-9B delivered after resume. Run it from a --project that has project hooks if you
want the T9a "project hooks loaded" condition; the kit does not add them.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import kit
from kit import Config, fresh_inbox, hook_events, post


def run(cfg: Config, inbox: Path, argv: list[str], poster=None) -> dict:
    env = dict(os.environ, PROBE_INBOX=str(inbox))
    t0 = time.time()
    p = subprocess.Popen(argv, cwd=cfg.project, env=env, stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         encoding="utf-8")
    posted = None
    while p.poll() is None and time.time() - t0 < 300:
        if poster and posted is None:
            posted = poster(time.time() - t0)
        time.sleep(0.5)
    out, err = kit.communicate(p)
    res = kit.parse_json_result(out)
    return {"elapsed_s": round(time.time() - t0, 1), "posted_at_s": posted, "exit": p.returncode,
            "session_id": res.get("session_id"), "result_text": res.get("result"),
            "cost": res.get("total_cost_usd"), "stderr_tail": err[-1000:]}


def run_t9(cfg: Config) -> dict:
    settings = kit.render_settings(cfg)  # PostToolUse * + Stop -> inbox_hook.py
    inbox = fresh_inbox(cfg, "t9")

    def cmd(extra: list[str]) -> list[str]:
        return [cfg.require_claude(), "-p", "--model", "haiku", "--settings", str(settings),  #  <!-- model-slug-ok: the probe's own fixed CLI alias for the cheapest model, not a routing pin -->
                "--permission-mode", "dontAsk", "--allowedTools", "Bash(sleep *)",
                "--output-format", "json"] + extra

    def poster(t):
        fires = [e for e in hook_events(inbox) if e.get("event") == "PostToolUse"]
        if len(fires) >= 2:
            post(inbox, "m1", "ORCHESTRATOR-MESSAGE id=m1: stop running sleep now. Codeword "
                 "APRICOT-9A. Put it in your final answer.")
            return round(t, 1)
        return None

    a = run(cfg, inbox, cmd(["This is a messaging test. Use the Bash tool to run `sleep 4` up to 6 "
                             "times, one call at a time. After each call, look for text starting "
                             "with ORCHESTRATOR-MESSAGE in your context and obey it. End with "
                             "'SEEN: <verbatim message or NONE>'."]), poster)
    post(inbox, "m2", "ORCHESTRATOR-MESSAGE id=m2 (posted while the run was stopped): "
         "codeword BANANA-9B.")
    sid = a.get("session_id")
    b = run(cfg, inbox, cmd(["--resume", sid, "Resumed. Run `sleep 1` once with the Bash tool. "
                             "Then list every ORCHESTRATOR-MESSAGE codeword you have received in "
                             "this whole session, both before this resume and now. End with "
                             "'CODEWORDS: <comma list>'."])) if sid else {"error": "no session id"}
    tx_hits = []
    if sid:
        for proj in (Path.home() / ".claude" / "projects").glob("*"):
            f = proj / f"{sid}.jsonl"
            if f.exists():
                for line in f.read_text(encoding="utf-8").splitlines():
                    if "APRICOT-9A" in line or "BANANA-9B" in line:
                        try:
                            ev = json.loads(line)
                        except ValueError:
                            continue
                        att = ev.get("attachment") or {}
                        tx_hits.append({"file": str(f), "type": ev.get("type"),
                                        "attachment_type": att.get("type") if isinstance(att, dict) else None,
                                        "has_A": "APRICOT-9A" in line, "has_B": "BANANA-9B" in line})
    t9a = "APRICOT-9A" in (a.get("result_text") or "")
    t9b_a = "APRICOT-9A" in (b.get("result_text") or "")
    t9b_b = "BANANA-9B" in (b.get("result_text") or "")
    return {"test": "T9 durability across resume", "t9a": a, "t9b": b,
            "transcript_hits": tx_hits, "hook_log": hook_events(inbox),
            "t9a_codeword": t9a, "t9b_A_remembered": t9b_a, "t9b_B_delivered": t9b_b,
            "passed": t9a and t9b_a and t9b_b and a.get("exit") == 0 and b.get("exit") == 0}


CASES = {"T9": run_t9}


def main() -> int:
    return kit.probe_main(__doc__.splitlines()[0], CASES, "results4.json")


if __name__ == "__main__":
    sys.exit(main())
