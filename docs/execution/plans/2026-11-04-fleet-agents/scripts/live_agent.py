#!/usr/bin/env python3
"""Run row 12's live Claude job from the hub through the fleet's own verbs, and save check_live.py's evidence.

kit      publish this repo's manifest and install the kit on the member
noquote  a start with no quote, which must be refused
start    start the job with the human's words
query    send one query and wait for its reply in the outbox
watch    run fleet watch until the job stops, and print the question
resume   resume with the human's answer as the quote and as the brief
final    wait for the end and record it

Every step's fleet output goes to fa-live-agent.log. The evidence is fa-live-agent.json.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
FLEET = ROOT / ".agent" / "fleet" / "fleet.py"
RECEIPTS = Path(os.environ.get("RECEIPTS_DIR") or "C:/Temp/agentic-framework/receipts")
REPO = RECEIPTS.parent / "fa-live-repo"
EVIDENCE = RECEIPTS / "fa-live-agent.json"
LOG = RECEIPTS / "fa-live-agent.log"
MEMBER = os.environ.get("FLEET_MEMBER") or sys.exit("set FLEET_MEMBER to the member's fleet name")
# fa-row12 was refused by the engine's $5 floor (FLOOR_USD) with a $3 cap, and a failed run can't start again.
RUN = "fa-row12b"
# The human's words, as typed, that start this job.
QUOTE = "Start the row 12 and row 15 test jobs."
CAPS = ("--segment-cap-usd", "6", "--run-cap-usd", "12", "--timeout-sec", "1200")
QUERY = "What does wait_step.py do? Answer in one sentence."
QUERY_WAIT_S = 420
KIT_TIMEOUT_S = 900
BRIEF = """This is a test job on a throwaway repository. Do these steps in order, and nothing else.

1. Use the Bash tool to run `python wait_step.py`. It waits 60 seconds.
2. If no message has reached you yet, run it again, at most five times in all. Answer the message as the header says.
3. Write the file `draft.txt` holding the one line `draft ok`.
4. You need a decision from the human, so stop as the header says. Your question is: which word should `answer.txt` hold, north or south?
"""
RESUME_BRIEF = """The human answered your question in the words quoted above. Write `answer.txt` holding the word they chose, on one line, then finish as the header says.
"""


def fleet(*args: str) -> subprocess.CompletedProcess:
    r = subprocess.run([sys.executable, str(FLEET), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"args": list(args), "exit": r.returncode, "stdout": r.stdout[-6000:], "stderr": r.stderr[-2000:]}) + "\n")
    return r


def last_json(r: subprocess.CompletedProcess) -> dict:
    lines = r.stdout.strip().splitlines()
    return json.loads(lines[-1]) if lines else {}


def evidence() -> dict:
    return json.loads(EVIDENCE.read_text(encoding="utf-8")) if EVIDENCE.exists() else {}


def save(**fields) -> None:
    EVIDENCE.write_text(json.dumps({**evidence(), **fields}, indent=1), encoding="utf-8")


def build_repo() -> Path:
    if not (REPO / ".git").exists():
        REPO.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q"], cwd=REPO, check=True)
        (REPO / "wait_step.py").write_text("import time\ntime.sleep(60)\nprint('waited')\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=REPO, check=True)
        subprocess.run(["git", "commit", "-q", "--no-gpg-sign", "-m", "base"], cwd=REPO, check=True)
    return REPO


def write_brief(name: str, text: str) -> str:
    path = RECEIPTS / name
    path.write_text(text, encoding="utf-8", newline="\n")
    return str(path)


def status() -> dict:
    return last_json(fleet("agent", "status", MEMBER, RUN))


def kit() -> int:
    r = fleet("publish", "--repo", str(ROOT))
    if r.returncode:
        print("publish exit", r.returncode, r.stderr[-500:])
        return r.returncode
    r = fleet("run", MEMBER, "--repo", str(ROOT), "kit-install", "--timeout", str(KIT_TIMEOUT_S))
    if r.returncode:
        print("run exit", r.returncode, r.stderr[-500:])
        return r.returncode
    log = RECEIPTS / "fa-row12-kit.log"
    r = fleet("wait", last_json(r)["task"], "--timeout", str(KIT_TIMEOUT_S), "--log", str(log))
    result = last_json(r)
    print({k: result.get(k) for k in ("state", "reason", "exit_code", "duration_s")})
    print(log.read_text(encoding="utf-8", errors="replace")[-800:] if log.exists() else "no log")
    return r.returncode


def noquote() -> int:
    r = fleet("agent", "start", MEMBER, "fa-row12-noquote", "--repo", str(build_repo()), "--brief", write_brief("fa-row12-brief.md", BRIEF), *CAPS)
    named = "quote_required" if "quote_required" in r.stderr else r.stderr[-200:]
    save(no_quote_refusal=named)
    print(r.returncode, named)
    return 0 if named == "quote_required" else 1


def start() -> int:
    r = fleet(
        "agent", "start", MEMBER, RUN, "--repo", str(build_repo()), "--brief", write_brief("fa-row12-brief.md", BRIEF),
        "--quote", QUOTE, "--allowed-tool", "Bash(python wait_step.py)", *CAPS,
    )
    doc = last_json(r)
    print(r.returncode, json.dumps(doc), r.stderr[-400:])
    if r.returncode:
        return r.returncode
    save(start={"quote": QUOTE, "session_id": None, "slot": doc.get("slot")}, start_task=doc)
    return 0


def query() -> int:
    r = fleet("agent", "message", MEMBER, RUN, "--kind", "query", "--text", QUERY)
    print(r.returncode, r.stdout[-300:], r.stderr[-300:])
    if r.returncode:
        return r.returncode
    end = time.monotonic() + QUERY_WAIT_S
    while time.monotonic() < end:
        doc = status()
        replies = [e["text"] for e in doc.get("outbox") or [] if e.get("text")]
        print(doc.get("run_state"), [e.get("kind") for e in doc.get("outbox") or []], flush=True)
        if replies:
            # The reply arrived while the run's state was this one, which is what the row asks to see.
            save(query_reply=replies[0], query_reply_run_state=doc.get("run_state"), query_session_id=doc.get("session_id"))
            print("reply:", replies[0])
            return 0
        if doc.get("run_state") != "running":
            print("the run left running with no reply:", json.dumps(doc)[:1500])
            return 1
        time.sleep(10)
    print("no reply in time")
    return 1


def watch() -> int:
    r = fleet("watch", MEMBER, RUN, "--poll", "15")
    doc = last_json(r)
    print("watch exit", r.returncode)
    print(json.dumps({k: doc.get(k) for k in ("run_state", "stop_class", "final_status", "session_id", "reason")}))
    print(doc.get("final_text"))
    first = evidence().get("start") or {}
    first["session_id"] = doc.get("session_id")
    save(stopped={"stop_class": doc.get("stop_class"), "watch_exit": r.returncode, "final_text": doc.get("final_text")}, start=first)
    return 0


def resume(answer: str) -> int:
    r = fleet("agent", "resume", MEMBER, RUN, "--brief", write_brief("fa-row12-resume.md", RESUME_BRIEF), "--quote", answer)
    doc = last_json(r)
    print(r.returncode, json.dumps(doc), r.stderr[-400:])
    if r.returncode:
        return r.returncode
    save(resume={"quote": answer, "session_id": None, "slot": doc.get("slot")}, resume_task=doc)
    return 0


def final() -> int:
    r = fleet("watch", MEMBER, RUN, "--poll", "15")
    doc = last_json(r)
    print("watch exit", r.returncode)
    print(json.dumps({k: doc.get(k) for k in ("run_state", "stop_class", "final_status", "verified", "session_id", "reason")}))
    print(doc.get("final_text"))
    second = evidence().get("resume") or {}
    second["session_id"] = doc.get("session_id")
    save(final={"run_state": doc.get("run_state"), "final_status": doc.get("final_status"), "watch_exit": r.returncode, "final_text": doc.get("final_text")}, resume=second)
    return 0


def main() -> int:
    action = sys.argv[1]
    if action == "resume":
        return resume(sys.argv[2])
    return {"kit": kit, "noquote": noquote, "start": start, "query": query, "watch": watch, "final": final}[action]()


if __name__ == "__main__":
    raise SystemExit(main())
