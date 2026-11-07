#!/usr/bin/env python3
"""Plan-local verifier for the live ACs of the fleet agents plan: AC-5, AC-16, AC-28, AC-33 and AC-37.

Modes: setup, credits, agent, codex, result, --selftest.
Each mode reads the evidence its live row saved under RECEIPTS_DIR, then a pure function lists the problems,
which is what --selftest feeds. It writes nothing, and it never reads a credential or a member's member.json.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
FLEET_PY = ROOT / ".agent" / "fleet" / "fleet.py"
HUB_REGISTRY = Path("P:/.agent/model-registry.json")
REGISTRY_SHA_PREFIX = "7097dc5bb0f07978"
# The member's fleet name. The selftest samples use the default.
MEMBER = os.environ.get("FLEET_MEMBER", "member-1")
REPORT_FIELDS = {"changed", "versions", "sandbox", "elevated_tried", "write_tests", "isolated_worker_slug", "reason"}
SETUP_TOOLS = ("claude", "codex", "pwsh")
SANDBOXES = {"elevated", "unelevated"}


def receipts() -> Path:
    return Path(os.environ.get("RECEIPTS_DIR", "C:/Temp/agentic-framework/receipts"))


def read_json(name: str):
    path = receipts() / name
    if not path.exists():
        raise SystemExit(f"FAILED: no evidence at {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def fleet_status() -> dict:
    r = subprocess.run(
        [sys.executable, str(FLEET_PY), "status"], capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return json.loads(r.stdout.strip().splitlines()[-1])


def registry_sha(path: Path = HUB_REGISTRY) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reviewer_slug(path: Path = HUB_REGISTRY) -> str | None:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["classes"]["independent_reviewer"]["bindings"].get("codex-cli", {}).get("slug")


def report_problems(label: str, report: dict, slug: str | None) -> list[str]:
    out = [f"{label}: unknown field {k}" for k in sorted(set(report) - REPORT_FIELDS)]
    out += [f"{label}: missing field {k}" for k in sorted(REPORT_FIELDS - set(report))]
    tests = report.get("write_tests") or {}
    for cli in ("claude", "codex"):
        if tests.get(cli) != "pass":
            out.append(f"{label}: {cli} write test is {tests.get(cli)!r}")
    if report.get("sandbox") not in SANDBOXES:
        out.append(f"{label}: sandbox is {report.get('sandbox')!r}")
    if report.get("elevated_tried") is not True:
        out.append(f"{label}: the elevated outcome is not recorded")
    if not report.get("isolated_worker_slug"):
        out.append(f"{label}: no isolated_worker slug on codex-cli")
    elif report["isolated_worker_slug"] != slug:
        out.append(f"{label}: isolated_worker slug differs from the reviewer's")
    if report.get("reason"):
        out.append(f"{label}: reason {report['reason']}")
    return out


def setup_problems(first: dict, second: dict, slug: str | None, sha: str, status: dict) -> list[str]:
    out = report_problems("first", first, slug) + report_problems("second", second, slug)
    if second.get("changed"):
        out.append(f"second: changed is not empty: {second['changed']}")
    if not sha.startswith(REGISTRY_SHA_PREFIX):
        out.append("The hub's registry hash changed (stop condition 12)")
    rows = {m["name"]: m for m in status.get("members", [])}
    caps = (rows.get(MEMBER) or {}).get("capabilities") or {}
    for tool in SETUP_TOOLS:
        if not caps.get(tool):
            out.append(f"fleet status has no version of {tool} on {MEMBER}")
    return out


def credits_problems(view: dict) -> list[str]:
    out = []
    if view.get("final_status") != "DONE":
        out.append(f"final status is {view.get('final_status')!r}")
    if view.get("auth_mode") == "api_key_file":
        out.append("the run used auth_mode api_key_file (stop condition 3)")
    elif not view.get("auth_mode"):
        out.append("no auth_mode in the evidence")
    if not view.get("logon_s4u"):
        out.append("the task did not run under S4U")
    if not view.get("message_acknowledged"):
        out.append("no info message was acknowledged, so no hook fired under the scrub")
    if not view.get("budget_in_argv"):
        out.append("--max-budget-usd is not in the argv")
    if not view.get("gate_passed"):
        out.append("the gate did not pass on the token")
    # P-3: the human dropped the meter reading on the Ultra account. Their words and the token's own window stand in for it.
    if (view.get("mat_ruling") or {}).get("quote"):
        probe = view.get("subscription_probe") or {}
        if probe.get("api_key_source") != "none":
            out.append(f"the token's apiKeySource is {probe.get('api_key_source')!r}, not none")
        if not probe.get("seven_day_resets_at"):
            out.append("no subscription window in the token's stream output")
        return out
    meter = view.get("mat_report") or {}
    if meter.get("plan_usage_moved") is not True:
        out.append("The human has not reported plan usage moving")
    if meter.get("console_unchanged") is not True:
        out.append("The human has not reported the Console balance unchanged")
    return out


def agent_problems(t: dict) -> list[str]:
    out = []
    if t.get("no_quote_refusal") != "quote_required":
        out.append(f"a start with no quote gave {t.get('no_quote_refusal')!r}, not quote_required")
    if not (t.get("start") or {}).get("quote"):
        out.append("the start has no quote from the human")
    if not t.get("query_reply"):
        out.append("no query reply in outbox during the run")
    stopped = t.get("stopped") or {}
    if stopped.get("stop_class") != "decision":
        out.append(f"stop_class is {stopped.get('stop_class')!r}, not decision")
    if stopped.get("watch_exit") != 7:
        out.append(f"fleet watch exited {stopped.get('watch_exit')!r}, not 7")
    resume = t.get("resume") or {}
    if not resume.get("quote"):
        out.append("the resume has no quote from the human")
    if not resume.get("session_id") or resume.get("session_id") != (t.get("start") or {}).get("session_id"):
        out.append("the session id changed on resume")
    if not resume.get("slot") or resume.get("slot") != (t.get("start") or {}).get("slot"):
        out.append("the slot changed on resume")
    if (t.get("final") or {}).get("run_state") != "done":
        out.append(f"run_state is {(t.get('final') or {}).get('run_state')!r}, not done")
    return out


def codex_problems(t: dict) -> list[str]:
    out = []
    job = t.get("job") or {}
    if not job.get("file_written"):
        out.append("the Codex job wrote no file, whatever its exit code")
    if job.get("status_line") != "DONE":
        out.append(f"the Codex status line is {job.get('status_line')!r}")
    if not (t.get("resume") or {}).get("resumed_between_turns"):
        out.append("no stopped Codex run resumed between turns")
    remote = t.get("remote_claude") or {}
    if not remote.get("codex_answer"):
        out.append("the remote Claude run got no Codex answer")
    denials = remote.get("permission_denials") or []
    if not any("FullAccess" in str(d) for d in denials):
        out.append("the remote Claude run's -Mode FullAccess attempt is not in permission_denials")
    return out


def result_problems(t: dict) -> list[str]:
    out = []
    results = t.get("results") or []
    clis = {r.get("cli") for r in results}
    for cli in ("claude", "codex"):
        if cli not in clis:
            out.append(f"no {cli} result landed")
    want = t.get("identity") or {}
    if not want.get("name") or not want.get("email"):
        out.append("The hub's global git identity is not in the evidence")
    for r in results:
        label = f"{r.get('cli')} {r.get('run')}"
        if r.get("ref") != f"refs/fleet/result/{r.get('run')}":
            out.append(f"{label}: ref is {r.get('ref')!r}")
        if not r.get("tree") or r.get("tree") != r.get("tree_expected"):
            out.append(f"{label}: the commit's tree differs from what the member reported")
        for who in ("author", "committer"):
            if r.get(who) != {"name": want.get("name"), "email": want.get("email")}:
                out.append(f"{label}: {who} is not the hub's global git identity")
        if not r.get("diff_shown"):
            out.append(f"{label}: the diff was not shown to the human")
        if not r.get("dropped"):
            out.append(f"{label}: the slot was not dropped")
    if t.get("branches_before") != t.get("branches_after"):
        out.append("landing a result created or changed a branch")
    if t.get("landing_word") is None:
        out.append("The human's landing word is not in the evidence")
    return out


def report(problems: list[str]) -> int:
    for p in problems:
        print(f"PROBLEM {p}")
    print(f"{len(problems)} problem(s)")
    return 1 if problems else 0


def cmd_setup() -> int:
    return report(setup_problems(
        read_json("fa-setup-report-1.json"), read_json("fa-setup-report-2.json"),
        reviewer_slug(), registry_sha(), fleet_status(),
    ))


def cmd_credits() -> int:
    return report(credits_problems(read_json("fa-live-credits.json")))


def cmd_agent() -> int:
    return report(agent_problems(read_json("fa-live-agent.json")))


def cmd_codex() -> int:
    return report(codex_problems(read_json("fa-live-codex.json")))


def cmd_result() -> int:
    return report(result_problems(read_json("fa-live-result.json")))


GOOD_REPORT = {
    "changed": [], "versions": {"claude": "1", "codex": "1", "pwsh": "1", "uv": "1"}, "sandbox": "unelevated",
    "elevated_tried": True, "write_tests": {"claude": "pass", "codex": "pass"}, "isolated_worker_slug": "m", "reason": None,
}
GOOD_STATUS = {"members": [{"name": MEMBER, "capabilities": {"claude": "1", "codex": "1", "pwsh": "1"}}]}
GOOD_SHA = REGISTRY_SHA_PREFIX + "0" * 48
GOOD_CREDITS = {
    "final_status": "DONE", "auth_mode": "subscription", "logon_s4u": True, "message_acknowledged": True,
    "budget_in_argv": True, "gate_passed": True, "mat_report": {"plan_usage_moved": True, "console_unchanged": True},
}
GOOD_AGENT = {
    "no_quote_refusal": "quote_required", "start": {"quote": "q", "session_id": "s", "slot": "p"},
    "query_reply": "r", "stopped": {"stop_class": "decision", "watch_exit": 7},
    "resume": {"quote": "a", "session_id": "s", "slot": "p"}, "final": {"run_state": "done"},
}
GOOD_CODEX = {
    "job": {"file_written": True, "status_line": "DONE"}, "resume": {"resumed_between_turns": True},
    "remote_claude": {"codex_answer": "a", "permission_denials": ["Invoke-CodexDispatch.ps1 -Mode FullAccess"]},
}
IDENTITY = {"name": "n", "email": "e@users.noreply.github.com"}


def good_result() -> dict:
    return {
        "identity": dict(IDENTITY), "landing_word": "w", "branches_before": ["main"], "branches_after": ["main"],
        "results": [
            {"cli": cli, "run": cli, "ref": f"refs/fleet/result/{cli}", "tree": "t", "tree_expected": "t",
             "author": dict(IDENTITY), "committer": dict(IDENTITY), "diff_shown": True, "dropped": True}
            for cli in ("claude", "codex")
        ],
    }


def selftest() -> int:
    def setup(first=None, second=None, slug="m", sha=GOOD_SHA, status=GOOD_STATUS):
        return setup_problems(first or GOOD_REPORT, second or GOOD_REPORT, slug, sha, status)

    no_cap = {"members": [{"name": MEMBER, "capabilities": {"claude": "1", "codex": "1", "pwsh": None}}]}
    first_result = good_result()
    first_result["results"][0]["tree"] = "other"
    bad_author = good_result()
    bad_author["results"][1]["author"] = {"name": "fleet", "email": "fleet@fleet.invalid"}
    bad_committer = good_result()
    bad_committer["results"][1]["committer"] = {"name": "n", "email": "x@users.noreply.github.com"}
    denial_free = {**GOOD_CODEX, "remote_claude": {"codex_answer": "a", "permission_denials": []}}
    cases = [
        ("clean setup", setup(), 0),
        ("non-empty changed", setup(second={**GOOD_REPORT, "changed": ["uv"]}), 1),
        ("failed write test", setup(first={**GOOD_REPORT, "write_tests": {"claude": "pass", "codex": "fail"}}), 1),
        ("no isolated_worker slug", setup(first={**GOOD_REPORT, "isolated_worker_slug": None}), 1),
        ("slug differs from reviewer", setup(slug="other"), 2),
        ("changed registry hash", setup(sha="0" * 64), 1),
        ("unknown report field", setup(second={**GOOD_REPORT, "x": 1}), 1),
        ("status without pwsh", setup(status=no_cap), 1),
        ("clean credits", credits_problems(GOOD_CREDITS), 0),
        ("no acknowledged message", credits_problems({**GOOD_CREDITS, "message_acknowledged": False}), 1),
        ("api key auth", credits_problems({**GOOD_CREDITS, "auth_mode": "api_key_file"}), 1),
        ("no meter report", credits_problems({**GOOD_CREDITS, "mat_report": {}}), 2),
        ("P-3 ruling", credits_problems({**GOOD_CREDITS, "mat_report": {}, "mat_ruling": {"quote": "q"}, "subscription_probe": {"api_key_source": "none", "seven_day_resets_at": "t"}}), 0),
        ("P-3 ruling, no probe", credits_problems({**GOOD_CREDITS, "mat_report": {}, "mat_ruling": {"quote": "q"}}), 2),
        ("P-3 ruling, key source", credits_problems({**GOOD_CREDITS, "mat_ruling": {"quote": "q"}, "subscription_probe": {"api_key_source": "env", "seven_day_resets_at": "t"}}), 1),
        ("empty ruling", credits_problems({**GOOD_CREDITS, "mat_report": {}, "mat_ruling": {"quote": ""}}), 2),
        ("clean agent", agent_problems(GOOD_AGENT), 0),
        ("session changed", agent_problems({**GOOD_AGENT, "resume": {"quote": "a", "session_id": "x", "slot": "p"}}), 1),
        ("no query reply", agent_problems({**GOOD_AGENT, "query_reply": ""}), 1),
        ("no quote refusal", agent_problems({**GOOD_AGENT, "no_quote_refusal": None}), 1),
        ("clean codex", codex_problems(GOOD_CODEX), 0),
        ("exit 0 with no file", codex_problems({**GOOD_CODEX, "job": {"file_written": False, "status_line": "DONE"}}), 1),
        ("no denial", codex_problems(denial_free), 1),
        ("clean result", result_problems(good_result()), 0),
        ("new branch", result_problems({**good_result(), "branches_after": ["main", "x"]}), 1),
        ("tree differs", result_problems(first_result), 1),
        ("other author", result_problems(bad_author), 1),
        ("other committer", result_problems(bad_committer), 1),
    ]
    failed = 0
    for label, problems, want in cases:
        ok = len(problems) == want
        print(f"{'ok' if ok else 'FAILED'}: {label}: {len(problems)} problem(s), want {want}")
        failed += 0 if ok else 1
    print(f"selftest: {len(cases) - failed} of {len(cases)} ok")
    return 1 if failed else 0


MODES = {
    "setup": cmd_setup, "credits": cmd_credits, "agent": cmd_agent, "codex": cmd_codex,
    "result": cmd_result, "--selftest": selftest,
}


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in MODES:
        print(__doc__)
        return 2
    return MODES[mode]()


if __name__ == "__main__":
    raise SystemExit(main())
