#!/usr/bin/env python3
"""Run row 8's smoke steps from the hub through the fleet, and save their results as check_live.py's evidence.

prepare   register the run on the member (nothing spent)
start     start it, send one info message, wait for the end, and write fa-live-credits.json
report    add the human's meter report: report <plan_usage_moved true|false> <console_unchanged true|false>

The throwaway repo holds only credits_smoke.py and its own manifest, so the project's .agent/fleet.json is unchanged.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
FLEET = ROOT / ".agent" / "fleet" / "fleet.py"
RECEIPTS = Path(os.environ.get("RECEIPTS_DIR") or "C:/Temp/agentic-framework/receipts")
REPO = RECEIPTS.parent / "fa-smoke-repo"
# The additional run the human asked for keeps its own evidence and logs, and starts on the human's words for it.
ADDITIONAL = os.environ.get("SMOKE_MODEL")
RESEARCH = os.environ.get("SMOKE_BRIEF") == "research"
SUFFIX = "-research" if RESEARCH else "-additional" if ADDITIONAL else ""
EVIDENCE = RECEIPTS / f"fa-live-credits{SUFFIX}.json"
# The human's words, as typed, that approve row 8.
QUOTE = "run the research prompt" if RESEARCH else "create additional run and leave sonnet going" if ADDITIONAL else "proceed, commit the plan, rows 3, 8, 12, 15 and 17 are approved."
MANIFEST = {
    "v": 1, "project": "fa-smoke", "requires": ["python", "pwsh", "claude"],
    "commands": {"smoke-prepare": [["python", "credits_smoke.py", "prepare"]], "smoke-start": [["python", "credits_smoke.py", "start"]], "smoke-look": [["python", "credits_smoke.py", "look"]], "smoke-resolve": [["python", "credits_smoke.py", "resolve"]], "smoke-denials": [["python", "credits_smoke.py", "denials"]], "smoke-mcp": [["python", "credits_smoke.py", "mcp"]]},
}
RUN_TIMEOUT_S = 3000
MEMBER = os.environ.get("FLEET_MEMBER") or sys.exit("set FLEET_MEMBER to the member's fleet name")


def fleet(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(FLEET), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")


def hub_identity() -> list[str]:
    """The hub's global commit name and address. The member has none, so its smoke base commit carries these."""
    values = [subprocess.run(["git", "config", "--global", "--get", key], capture_output=True, text=True).stdout.strip()
              for key in ("user.name", "user.email")]
    if not all(values) or not values[1].endswith("@users.noreply.github.com"):
        raise SystemExit("The hub's global git identity is missing or not a noreply address")
    return values


def build_repo() -> None:
    if not (REPO / ".git").exists():
        REPO.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q"], cwd=REPO, check=True)
    (REPO / ".agent").mkdir(exist_ok=True)
    (REPO / ".agent" / "fleet.json").write_text(json.dumps(MANIFEST, indent=2), encoding="utf-8")
    smoke = {"quote": QUOTE, "model": ADDITIONAL, "research": RESEARCH, "identity": hub_identity()}
    (REPO / "smoke.json").write_text(json.dumps(smoke), encoding="utf-8")
    shutil.copyfile(HERE / "credits_smoke.py", REPO / "credits_smoke.py")
    subprocess.run(["git", "add", "-A"], cwd=REPO, check=True)
    if subprocess.run(["git", "rev-parse", "--verify", "-q", "HEAD"], cwd=REPO, capture_output=True).returncode:
        subprocess.run(["git", "commit", "-q", "--no-gpg-sign", "-m", "smoke"], cwd=REPO, check=True)


def run_step(command: str) -> dict:
    build_repo()
    r = fleet("publish", "--repo", str(REPO))
    if r.returncode:
        raise SystemExit(f"publish exit {r.returncode}: {r.stderr[:500]}")
    r = fleet("run", MEMBER, "--repo", str(REPO), command, "--timeout", str(RUN_TIMEOUT_S))
    if r.returncode:
        raise SystemExit(f"run exit {r.returncode}: {r.stderr[:500]}")
    task = json.loads(r.stdout.strip().splitlines()[-1])["task"]
    log = RECEIPTS / f"fa-{command}{SUFFIX}.log"
    r = fleet("wait", task, "--timeout", str(RUN_TIMEOUT_S), "--log", str(log))
    result = json.loads(r.stdout.strip().splitlines()[-1])
    print(json.dumps({k: result.get(k) for k in ("state", "reason", "exit_code", "duration_s")}))
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    lines = [line for line in text.splitlines() if line.startswith("SMOKE ")]
    if not lines:
        print(text[-3000:])
        raise SystemExit("no SMOKE line in the log")
    return json.loads(lines[-1][len("SMOKE "):])


def read_evidence() -> dict:
    return json.loads(EVIDENCE.read_text(encoding="utf-8")) if EVIDENCE.exists() else {}


def main() -> int:
    action = sys.argv[1]
    if action == "prepare":
        doc = run_step("smoke-prepare")
        print(json.dumps(doc, indent=1))
        return doc.get("register_exit", 1)
    if action == "start":
        doc = run_step("smoke-start")
        view = read_evidence()
        messages = doc.get("messages") or []
        view.update({
            "raw": doc, "final_status": doc.get("final_status"), "auth_mode": doc.get("auth_mode"),
            "logon_s4u": doc.get("task_logon") == "S4U",
            "message_acknowledged": any(
                isinstance(m, dict) and m.get("state") == "closed" and m.get("closed_reason") == "done"
                and any(d.get("state") == "confirmed" and d.get("confirmed_utc") for d in m.get("deliveries") or [])
                for m in messages
            ),
            "budget_in_argv": "--max-budget-usd" in (doc.get("sanitized_argv") or []),
            "gate_passed": doc.get("gate_qualifying") is True,
        })
        EVIDENCE.write_text(json.dumps(view, indent=1), encoding="utf-8")
        print(json.dumps({k: v for k, v in view.items() if k != "raw"}, indent=1))
        print(json.dumps({k: doc.get(k) for k in ("run", "state", "class", "model", "session_id", "exit_code", "cost", "file_written", "essays_written", "mcp_calls", "web_calls", "research_words", "timed_out", "start_exit", "send_exit", "messages")}, indent=1))
        return 0
    if action in ("look", "resolve", "denials", "mcp"):
        run_step(f"smoke-{action}")
        return 0
    if action == "report":
        view = read_evidence()
        view["mat_report"] = {"plan_usage_moved": sys.argv[2] == "true", "console_unchanged": sys.argv[3] == "true"}
        EVIDENCE.write_text(json.dumps(view, indent=1), encoding="utf-8")
        return 0
    raise SystemExit(f"unknown action {action}")


if __name__ == "__main__":
    raise SystemExit(main())
