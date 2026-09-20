#!/usr/bin/env python3
"""Disposable adopter replay for WP7. Writes wp7-adopter-replay.txt under RECEIPTS_DIR."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[2]
RECEIPTS = Path(os.environ["RECEIPTS_DIR"])
FIXTURE = Path("C:/Temp/agentic-framework/wp7-adopt-2026-09-19")
GIT_BASH = Path("C:/Program Files/Git/bin/bash.exe")
GIT_USR = Path("C:/Program Files/Git/usr/bin")
GIT_BIN = Path("C:/Program Files/Git/bin")


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def main() -> int:
    if FIXTURE.exists():
        shutil.rmtree(FIXTURE)
    FIXTURE.mkdir(parents=True)
    (FIXTURE / ".agent" / "templates").mkdir(parents=True)
    (FIXTURE / ".cursor" / "agents").mkdir(parents=True)
    (FIXTURE / ".claude" / "agents").mkdir(parents=True)

    copies = [
        (PKG / "core/AGENTS.md", FIXTURE / "AGENTS.md"),
        (PKG / "core/GUARDRAILS.md", FIXTURE / "GUARDRAILS.md"),
        (PKG / "core/CLAUDE.md", FIXTURE / "CLAUDE.md"),
        (PKG / ".agent/INSTANTIATE.md", FIXTURE / ".agent/INSTANTIATE.md"),
        (PKG / "PROJECT-PROFILE-TEMPLATE.md", FIXTURE / "PROJECT-PROFILE.md"),
    ]
    for src, dst in copies:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    shutil.copytree(PKG / "core/.agent", FIXTURE / ".agent", dirs_exist_ok=True)
    shutil.copy2(PKG / ".agent/INSTANTIATE.md", FIXTURE / ".agent/INSTANTIATE.md")
    shutil.copytree(PKG / "core/tools", FIXTURE / "tools")
    shutil.copytree(PKG / "core/templates", FIXTURE / ".agent/templates", dirs_exist_ok=True)
    shutil.copytree(PKG / "core/.cursor/agents", FIXTURE / ".cursor/agents", dirs_exist_ok=True)
    shutil.copytree(PKG / "core/.claude/agents", FIXTURE / ".claude/agents", dirs_exist_ok=True)

    profile = (FIXTURE / "PROJECT-PROFILE.md").read_text(encoding="utf-8")
    profile = profile.replace("<project name>", "wp7-adopt")
    extra = """

## WP7 fixture answers

| Slot | Value |
|---|---|
| A10 | deferred |
| D6 | `python -m pytest test_hello.py -q` cwd=fixture, blocking, expected pass, shell=posix-sh, receipt under RECEIPTS_DIR |
| D9 | no |
| C1 | yes — forbid external dispatch for this fixture |
| B4 | fixture-human |
| plan_to_exec_gate | human |
"""
    (FIXTURE / "PROJECT-PROFILE.md").write_text(profile + extra, encoding="utf-8")
    (FIXTURE / "test_hello.py").write_text(
        "def test_hello():\n    assert True\n", encoding="utf-8"
    )

    vars_path = RECEIPTS / "wp7-framework.vars"
    vars_path.write_text(
        "PROJECT_NAME=wp7adopt\n"
        f"PROJECT_ROOT={FIXTURE.as_posix()}\n"
        f"RECEIPTS_DIR={RECEIPTS.as_posix()}\n"
        "REPO_URL=example.invalid/wp7/adopt\n",
        encoding="utf-8",
    )
    inst = run(
        [
            sys.executable,
            str(PKG / "scripts/instantiate.py"),
            "--root",
            str(FIXTURE),
            "--config",
            str(vars_path),
        ]
    )
    if inst.returncode != 0:
        print(inst.stdout)
        print(inst.stderr)
        return inst.returncode

    profile_text = (FIXTURE / "PROJECT-PROFILE.md").read_text(encoding="utf-8")
    d9_no = False
    for line in profile_text.splitlines():
        if "| D9 |" in line and "no" in line.lower():
            d9_no = True
    c1_forbid = "forbid" in profile_text.lower() and "C1" in profile_text

    d6 = run([sys.executable, "-m", "pytest", "test_hello.py", "-q"], cwd=FIXTURE)

    plan_tmpl_path = FIXTURE / ".agent/templates/PLAN-TEMPLATE.md"
    task_tmpl_path = FIXTURE / ".agent/templates/TASK-TEMPLATE.md"
    plan_tmpl = plan_tmpl_path.read_text(encoding="utf-8")
    task_tmpl = task_tmpl_path.read_text(encoding="utf-8")
    if "template_version" not in plan_tmpl or "# Implementation Plan" not in plan_tmpl:
        print("installed PLAN-TEMPLATE.md missing expected markers", file=sys.stderr)
        return 1
    if "Status Legend" not in task_tmpl or "H1-1" not in task_tmpl:
        print("installed TASK-TEMPLATE.md missing expected markers", file=sys.stderr)
        return 1

    plan_dir = FIXTURE / "docs/execution/plans/2026-09-19-wp7-first"
    plan_dir.mkdir(parents=True)
    d9_sentence = (
        "D9_NO_BRANCH: PROFILE D9 is no; first-plan write omits meu_status.py."
        if d9_no
        else "D9 is yes; MEU tools would be required."
    )
    egress_sentence = (
        "EGRESS_PRECEDENCE: C1 forbids dispatch; stop for B4 named human; no provider web-prompt."
        if c1_forbid
        else "EGRESS_PRECEDENCE: dispatch remains required."
    )
    plan_text = plan_tmpl
    for old, new in (
        ("{YYYY-MM-DD}-{project-slug}", "2026-09-19-wp7-first"),
        ("{YYYY-MM-DD}", "2026-09-19"),
        ("{project-slug}", "wp7-first"),
        ("{Project Title}", "WP7 first"),
        ("{bp section reference(s)}", "none (docs/BUILD_PLAN.md absent)"),
        ("{section-reference}", "none"),
        (
            "{Brief description of the problem, background context, and what the change accomplishes.}",
            "Disposable adopter first-plan write after instantiate. "
            + d9_sentence
            + " "
            + egress_sentence,
        ),
    ):
        plan_text = plan_text.replace(old, new)
    if "#### Acceptance Criteria" not in plan_text or "## Verification Plan" not in plan_text:
        print("filled PLAN-TEMPLATE lost required sections", file=sys.stderr)
        return 1
    (plan_dir / "implementation-plan.md").write_text(plan_text, encoding="utf-8")
    task_head = task_tmpl.split("| # | Task |", 1)[0]
    task_head = task_head.replace("{YYYY-MM-DD}-{project-slug}", "2026-09-19-wp7-first")
    task_head = task_head.replace("{date}-{project-slug}", "2026-09-19-wp7-first")
    task_head = task_head.replace("{Project Title}", "WP7 first")
    task_head = task_head.replace("{Infrastructure/Docs | Domain | API | GUI | MCP}", "Docs")
    task_head = task_head.replace("{N files changed}", "fixture replay")
    task = (
        task_head
        + """| # | Task | Owner | Deliverable | Validation | Depends on | Context strategy | Durable outputs | builder_model | Status |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Write hello test | coder | test_hello.py | `python -m pytest test_hello.py -q *> $env:RECEIPTS_DIR/wp7-d6.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/wp7-d6.txt; exit $code` | — | shared | test_hello.py | `coordinator` | `[x]` |

### Status Legend

| Symbol | Meaning |
|--------|---------|
| `[ ]` | Not started |
| `[x]` | Complete |
"""
    )
    (plan_dir / "task.md").write_text(task, encoding="utf-8")
    lint = run(
        [
            sys.executable,
            str(FIXTURE / "tools/lint_task_contract.py"),
            "--task",
            str(plan_dir / "task.md"),
        ],
        env={**os.environ, "RECEIPTS_DIR": str(RECEIPTS)},
    )

    env = os.environ.copy()
    env["PATH"] = str(GIT_USR) + os.pathsep + str(GIT_BIN) + os.pathsep + env.get("PATH", "")
    env["RECEIPTS_DIR"] = str(RECEIPTS)
    env.pop("AGENT_MODEL_REGISTRY", None)
    env.pop("AGENT_MODEL_REGISTRY_HOME", None)
    run(["git", "init"], cwd=FIXTURE)
    pre = run(
        [str(GIT_BASH), str(FIXTURE / "tools/preflight.sh"), "--phase", "build"],
        cwd=FIXTURE,
        env=env,
    )
    first = (pre.stdout or pre.stderr or "").splitlines()[0] if (pre.stdout or pre.stderr) else ""
    if not first and pre.stdout is None:
        first = ""
    # merge streams already in stdout if we captured separately; take stdout first line
    out = pre.stdout or ""
    first = out.splitlines()[0] if out.strip() else ((pre.stderr or "").splitlines()[0] if pre.stderr else "")

    replay = RECEIPTS / "wp7-adopter-replay.txt"
    d9_flag = "yes" if d9_no else "no"
    egress_flag = "named-human-no-web-prompt" if c1_forbid else "dispatch-required"
    replay.write_text(
        "\n".join(
            [
                f"fixture={FIXTURE.as_posix()}",
                f"D6_EXIT={d6.returncode}",
                f"LINT_EXIT={lint.returncode}",
                f"PREFLIGHT_FIRST={first}",
                f"PREFLIGHT_EXIT={pre.returncode}",
                "PROVIDER_CALLS=0",
                f"D9_NO_BRANCH={d9_flag}",
                f"EGRESS_STOP={egress_flag}",
                f"INSTANTIATE_EXIT={inst.returncode}",
                "PLAN_FROM_TEMPLATE=yes",
                "TASK_FROM_TEMPLATE=yes",
                f"LINT_OUT={(lint.stdout or '')[:200]}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print(replay.read_text(encoding="utf-8"))
    return 0 if d6.returncode == 0 and lint.returncode == 0 and first.startswith("OK:") else 1


if __name__ == "__main__":
    raise SystemExit(main())
