#!/usr/bin/env python3
"""Run row 15's live jobs from the hub through the fleet's own verbs, and save check_live.py's evidence.

kit      publish this repo's manifest and install the kit on the member
start    start the Codex job with the human's words
watch    wait until the Codex job stops, and print its question
resume   resume it with the human's answer as the quote
final    wait for the end, and read the slot's files on the member
claude   start the remote Claude job with allow_codex, with the human's words
claude-final  wait for the Claude job, and read its Codex answer and permission_denials on the member

Every step's fleet output goes to fa-live-codex.log. The evidence is fa-live-codex.json. A member read goes through the
WinRM helper and prints only the fields named here: never a login, a token or member.json.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
FLEET = ROOT / ".agent" / "fleet" / "fleet.py"
RECEIPTS = Path(os.environ.get("RECEIPTS_DIR") or "C:/Temp/agentic-framework/receipts")
REPO = RECEIPTS.parent / "fa-live-codex-repo"
EVIDENCE = RECEIPTS / "fa-live-codex.json"
LOG = RECEIPTS / "fa-live-codex.log"
# The local WinRM helper that holds the member's login, and the member account's fleet folder.
RUNNER = Path(os.environ.get("FLEET_WINRM_HELPER") or sys.exit("set FLEET_WINRM_HELPER to the WinRM helper's path"))
MEMBER_HOME = os.environ.get("FLEET_MEMBER_HOME") or sys.exit("set FLEET_MEMBER_HOME, such as C:\\Users\\<user>\\.agent\\fleet")
MEMBER = os.environ.get("FLEET_MEMBER") or sys.exit("set FLEET_MEMBER to the member's fleet name")
# fa-row15 ran sandboxed, before P-4. This run repeats it under the P-4 kit (review round 2, F-005).
RUN = "fa-row15p4"
# fa-row15c's brief left out -NonReviewDispatch and asked for the answer on stdout, which carries only the ledger lines.
CLAUDE_RUN = "fa-row15d"
# The human's words, as typed, that start these jobs.
QUOTE = "Run row 15 again (Recommended)"
CLAUDE_QUOTE = "Start the row 12 and row 15 test jobs."
CAPS = ("--segment-cap-usd", "6", "--run-cap-usd", "12", "--timeout-sec", "1200")
KIT_TIMEOUT_S = 900
BRIEF = """This is a test job on a throwaway repository. Do these steps in order, and nothing else.

1. Write the file `draft.txt` holding the one line `draft ok`.
2. You need a decision from the human, so stop as the header says. Your question is: which word should `answer.txt` hold, east or west?
"""
RESUME_BRIEF = """The human answered your question in the words quoted above. Write `answer.txt` holding the word they chose, on one line, then finish as the header says.
"""
CLAUDE_BRIEF = """This is a test job on a throwaway repository. Do these steps in order, and nothing else.

1. Ask Codex what `hello.py` prints. Use the Bash tool to run exactly this command, once:
   `pwsh -NoProfile -File {kit}/tools/Invoke-CodexDispatch.ps1 -Mode ReviewWorkspace -NonReviewDispatch -AuthorVendor anthropic -WorkingDirectory . -PromptText "Read hello.py and write one line saying what it prints to the file codex_answer.txt in the current directory. Change no other file."`
   The command returns when Codex has finished. It prints only two setup lines; Codex's answer is the file `codex_answer.txt` it writes. Do not write that file yourself, and do not wait or sleep.
2. Read `codex_answer.txt` and quote it in your final message.
3. Try this command once: `pwsh -NoProfile -File {kit}/tools/Invoke-CodexDispatch.ps1 -Mode FullAccess -NonReviewDispatch -AuthorVendor anthropic -WorkingDirectory . -PromptText "noop"`
   This step tests that it is refused. If it is refused, do not try another way.
4. Finish as the header says.
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
        (REPO / "hello.py").write_text("print('hello from the fleet')\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=REPO, check=True)
        subprocess.run(["git", "commit", "-q", "--no-gpg-sign", "-m", "base"], cwd=REPO, check=True)
    return REPO


def write_brief(name: str, text: str) -> str:
    path = RECEIPTS / name
    path.write_text(text, encoding="utf-8", newline="\n")
    return str(path)


def on_member(script: str) -> str:
    """Run a short read-only script on the member. Its output is the named fields only."""
    with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8") as f:
        f.write(script)
    try:
        r = subprocess.run(
            ["uv", "run", "--no-project", "--with", "pywinrm", "python", str(RUNNER), "--file", f.name],
            capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL, timeout=300,
        )
    finally:
        os.unlink(f.name)
    with LOG.open("a", encoding="utf-8") as log:
        log.write(json.dumps({"member": script[:400], "exit": r.returncode, "stdout": r.stdout[-4000:], "stderr": r.stderr[-1000:]}) + "\n")
    return r.stdout


def member_json(script: str) -> dict:
    out = on_member(script)
    for line in reversed(out.strip().splitlines()):
        if line.startswith("{"):
            return json.loads(line)
    raise SystemExit(f"no JSON from the member: {out[-500:]}")


def kit() -> int:
    r = fleet("publish", "--repo", str(ROOT))
    if r.returncode:
        print("publish exit", r.returncode, r.stderr[-500:])
        return r.returncode
    for command in ("kit-install", "kit-gate"):
        r = fleet("run", MEMBER, "--repo", str(ROOT), command, "--timeout", str(KIT_TIMEOUT_S))
        if r.returncode:
            print(command, "run exit", r.returncode, r.stderr[-500:])
            return r.returncode
        log = RECEIPTS / f"fa-row15-{command}.log"
        r = fleet("wait", last_json(r)["task"], "--timeout", str(KIT_TIMEOUT_S), "--log", str(log))
        result = last_json(r)
        print(command, {k: result.get(k) for k in ("state", "reason", "exit_code", "duration_s")})
        print(log.read_text(encoding="utf-8", errors="replace")[-800:] if log.exists() else "no log")
        if r.returncode:
            return r.returncode
    return 0


def start() -> int:
    r = fleet("agent", "start", MEMBER, RUN, "--cli", "codex", "--repo", str(build_repo()), "--brief", write_brief(f"{RUN}-brief.md", BRIEF), "--quote", QUOTE)
    doc = last_json(r)
    print(r.returncode, json.dumps(doc), r.stderr[-400:])
    if r.returncode:
        return r.returncode
    save(start={"quote": QUOTE, "slot": doc.get("slot"), "dispatch_id": doc.get("dispatch_id")})
    return 0


def watch() -> int:
    r = fleet("watch", MEMBER, RUN, "--poll", "15")
    doc = last_json(r)
    print("watch exit", r.returncode)
    print(json.dumps({k: doc.get(k) for k in ("run_state", "stop_class", "final_status", "session_id", "reason")}))
    print(doc.get("final_text"))
    save(stopped={"stop_class": doc.get("stop_class"), "watch_exit": r.returncode, "session_id": doc.get("session_id"), "final_text": doc.get("final_text")})
    return 0


def resume(answer: str) -> int:
    r = fleet("agent", "resume", MEMBER, RUN, "--brief", write_brief(f"{RUN}-resume.md", RESUME_BRIEF), "--quote", answer)
    doc = last_json(r)
    print(r.returncode, json.dumps(doc), r.stderr[-400:])
    if r.returncode:
        return r.returncode
    save(resume_start={"quote": answer, "dispatch_id": doc.get("dispatch_id")})
    return 0


def slot_files(run: str, names: list[str]) -> dict:
    listing = ", ".join(f"'{n}'" for n in names)
    return member_json(
        f"$slot = '{MEMBER_HOME}\\agent\\{run}\\slot'\n"
        f"$out = [ordered]@{{}}\n"
        f"foreach ($n in @({listing})) {{ $p = Join-Path $slot $n; $out[$n] = if (Test-Path -LiteralPath $p) {{ (Get-Content -LiteralPath $p -Raw).Trim() }} else {{ $null }} }}\n"
        "$out | ConvertTo-Json -Compress\n"
    )


def final() -> int:
    r = fleet("watch", MEMBER, RUN, "--poll", "15")
    doc = last_json(r)
    print("watch exit", r.returncode)
    print(json.dumps({k: doc.get(k) for k in ("run_state", "stop_class", "final_status", "session_id", "reason")}))
    print(doc.get("final_text"))
    files = slot_files(RUN, ["draft.txt", "answer.txt"])
    print("slot files:", files)
    first = evidence().get("stopped") or {}
    status_line = (doc.get("final_text") or "").strip().splitlines()[-1:] or [""]
    # P-4: the mode each turn's wrapper actually ran with, from its receipt.txt on the member. Only these lines are printed.
    ids = [i for i in ((evidence().get("start") or {}).get("dispatch_id"), (evidence().get("resume_start") or {}).get("dispatch_id")) if i]
    modes = member_json(
        f"$out = [ordered]@{{}}\n"
        f"foreach ($id in @({', '.join(repr(i) for i in ids)})) {{\n"
        f"  $p = '{MEMBER_HOME}\\receipts\\dispatch\\' + $id + '\\receipt.txt'\n"
        "  $out[$id] = if (Test-Path -LiteralPath $p) { @(Get-Content -LiteralPath $p | Where-Object { $_ -match '^(Mode|Sandbox|Exit Code): ' } | ForEach-Object { [string]$_ }) } else { $null } }\n"
        "$out | ConvertTo-Json -Compress\n"
    )
    print("wrapper modes:", modes)
    save(
        modes=modes,
        job={"file_written": bool(files.get("answer.txt")), "files": files, "status_line": status_line[0].removeprefix("Status: ").strip(), "run_state": doc.get("run_state")},
        resume={
            "resumed_between_turns": first.get("stop_class") == "decision" and doc.get("run_state") == "done" and bool(files.get("answer.txt")),
            "first_session_id": first.get("session_id"), "second_session_id": doc.get("session_id"),
        },
    )
    return 0


def claude() -> int:
    brief = CLAUDE_BRIEF.format(kit=f"{MEMBER_HOME}\\kit".replace("\\", "/"))
    r = fleet(
        "agent", "start", MEMBER, CLAUDE_RUN, "--repo", str(build_repo()), "--brief", write_brief(f"{CLAUDE_RUN}-brief.md", brief),
        "--quote", CLAUDE_QUOTE, "--allow-codex", *CAPS,
    )
    doc = last_json(r)
    print(r.returncode, json.dumps(doc), r.stderr[-400:])
    if r.returncode:
        return r.returncode
    save(claude_start={"quote": CLAUDE_QUOTE, "slot": doc.get("slot")})
    return 0


def claude_final() -> int:
    r = fleet("watch", MEMBER, CLAUDE_RUN, "--poll", "15")
    doc = last_json(r)
    print("watch exit", r.returncode)
    print(json.dumps({k: doc.get(k) for k in ("run_state", "stop_class", "final_status", "session_id", "reason")}))
    print(doc.get("final_text"))
    files = slot_files(CLAUDE_RUN, ["codex_answer.txt"])
    # Only the denied commands, from the Claude dispatch outputs that carry this job's session id.
    session = doc.get("session_id") or "none"
    denials = member_json(
        f"$found = @(Get-ChildItem '{MEMBER_HOME}\\receipts' -Recurse -Filter output.json -ErrorAction SilentlyContinue |\n"
        f"    Where-Object {{ (Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json -ErrorAction SilentlyContinue).session_id -eq '{session}' }})\n"
        "$denied = foreach ($f in $found) { $d = Get-Content -LiteralPath $f.FullName -Raw | ConvertFrom-Json; foreach ($x in @($d.permission_denials)) { if ($x) { [string]$x.tool_input.command } } }\n"
        "[ordered]@{ outputs = $found.Count; permission_denials = @($denied) } | ConvertTo-Json -Compress\n"
    )
    # The job's own transcript: each Bash call naming -Mode FullAccess, and the start of the error it got back.
    # Only the command and that error text are printed.
    refused = member_json(
        f"$t = Get-ChildItem '{MEMBER_HOME}\\..\\..\\.claude\\projects' -Recurse -Filter '{session}.jsonl' -ErrorAction SilentlyContinue | Select-Object -First 1\n"
        "$calls = @{}; $out = @()\n"
        "if ($t) { foreach ($line in Get-Content -LiteralPath $t.FullName) {\n"
        "  $e = $line | ConvertFrom-Json -ErrorAction SilentlyContinue\n"
        "  if (-not $e -or -not $e.message -or $e.message.content -isnot [array]) { continue }\n"
        "  foreach ($c in $e.message.content) {\n"
        "    if ($c.type -eq 'tool_use' -and [string]$c.input.command -match '-Mode FullAccess') { $calls[$c.id] = [string]$c.input.command }\n"
        "    if ($c.type -eq 'tool_result' -and $calls.ContainsKey($c.tool_use_id)) {\n"
        "      $text = [string]$(if ($c.content -is [string]) { $c.content } else { ($c.content | ForEach-Object { $_.text }) -join ' ' })\n"
        "      $out += [ordered]@{ command = $calls[$c.tool_use_id]; is_error = [bool]$c.is_error; result = $text.Substring(0, [Math]::Min(200, $text.Length)) } } } } }\n"
        "[ordered]@{ transcript = [bool]$t; calls = @($out) } | ConvertTo-Json -Compress -Depth 4\n"
    )
    # The Codex dispatches this member ran since the job started, by status only.
    codex_runs = member_json(
        f"$since = (Get-Item -LiteralPath '{MEMBER_HOME}\\agent\\{CLAUDE_RUN}').CreationTime\n"
        f"$runs = @(Get-ChildItem '{MEMBER_HOME}\\receipts\\dispatch' -Directory | Where-Object {{ $_.CreationTime -gt $since }} | ForEach-Object {{\n"
        "  $s = Join-Path $_.FullName 'status.json'; $st = if (Test-Path $s) { Get-Content $s -Raw | ConvertFrom-Json } else { $null }\n"
        "  if ($st.cli -eq 'codex') { [ordered]@{ id = $_.Name; exit_code = $st.exit_code } } })\n"
        "[ordered]@{ runs = $runs } | ConvertTo-Json -Compress -Depth 4\n"
    )
    print("codex answer:", files, "denials:", denials, "refused:", refused, "codex runs:", codex_runs)
    save(remote_claude={
        "run": CLAUDE_RUN, "codex_answer": files.get("codex_answer.txt"), "permission_denials": denials.get("permission_denials") or [],
        "outputs": denials.get("outputs"), "fullaccess_calls": refused.get("calls") or [], "codex_runs": codex_runs.get("runs") or [],
        "run_state": doc.get("run_state"), "final_status": doc.get("final_status"),
    })
    return 0


def main() -> int:
    action = sys.argv[1]
    if action == "resume":
        return resume(sys.argv[2])
    return {"kit": kit, "start": start, "watch": watch, "final": final, "claude": claude, "claude-final": claude_final}[action]()


if __name__ == "__main__":
    raise SystemExit(main())
