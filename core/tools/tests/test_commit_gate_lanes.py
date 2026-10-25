"""MEU-785 AC-785.6: the commit gate stays unchanged around the lane commit helper — red first (G19).

FIC: ``docs/execution/plans/2026-10-22-lane-branches-governed-land/implementation-plan.md``
AC-785.6 (design D:176, D:315). The helper ``python -m tools.lanes commit`` runs
``git commit`` in a subprocess, so the shell hook never sees that commit: no
commit-gate allow is added (``.claude/hooks/commit_gate.py`` names none of
``HELPER_NAMES``, a check that holds in any adopter's tree), and a direct
``git commit`` stays denied (rule 7).

The hook half of this AC is already true before the port; each test also needs the
helper's ``commit`` subcommand, so the file is Red until the helper exists. The
hook runs as a separate process with a JSON payload on stdin, as in
``test_claude_hooks.py`` (copied, not imported). Do not skip, only, or
early-return (G36).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
COMMIT_GATE = ROOT / ".claude" / "hooks" / "commit_gate.py"
COMMIT_GATE_REL = ".claude/hooks/commit_gate.py"
LANES = ROOT / "tools" / "lanes.py"
# The helper's names; the hook source holds none of them, so it has no allow for it.
HELPER_NAMES = ("tools.lanes", "tools/lanes", "lanes.py")
HELPER_COMMAND = "uv run python -m tools.lanes commit --worktree x --message-file y"
DIRECT_COMMITS = (
    "git commit -F msg.txt",
    "git -C {{PROJECT_ROOT}}-wt/lane-a commit -F msg.txt",
    "git commit --no-verify -F msg.txt",
)
PERMISSION_MODES = ("default", "acceptEdits", "bypassPermissions")
CLI_TIMEOUT_S = 120


def _payload(command: object, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "session_id": "sess-test",
        "transcript_path": "C:/tmp/transcript.jsonl",
        "cwd": str(ROOT),
        "permission_mode": "default",
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_use_id": "toolu_test",
    }
    payload.update(overrides)
    return payload


def _hook(command: str, permission_mode: str) -> subprocess.CompletedProcess[str]:
    env = {
        k: v for k, v in os.environ.items() if k != "{{PROJECT_NAME_UPPER}}_HOOK_LOG"
    }
    return subprocess.run(
        [sys.executable, str(COMMIT_GATE)],
        input=json.dumps(_payload(command, permission_mode=permission_mode)),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=ROOT,
        timeout=60,
        check=False,
    )


def _decision(proc: subprocess.CompletedProcess[str]) -> tuple[str | None, str]:
    """Return ``(permissionDecision, reason)``; ``(None, "")`` when the hook was silent."""
    assert proc.returncode == 0, f"hook exit {proc.returncode}; stderr: {proc.stderr}"
    if not proc.stdout.strip():
        return None, ""
    out = json.loads(proc.stdout)
    spec = out["hookSpecificOutput"]
    assert spec["hookEventName"] == "PreToolUse"
    return spec["permissionDecision"], spec.get("permissionDecisionReason", "")


def _helper_help() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(LANES), "commit", "--help"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=CLI_TIMEOUT_S,
        check=False,
    )


def test_commit_gate_is_unchanged_and_allows_the_lane_commit_helper() -> None:
    source = COMMIT_GATE.read_text(encoding="utf-8")
    for name in HELPER_NAMES:
        assert name not in source, (
            f"{COMMIT_GATE_REL} names {name!r}: no commit-gate allow is added (D:176)"
        )
    for mode in PERMISSION_MODES:
        decision, reason = _decision(_hook(HELPER_COMMAND, mode))
        assert decision in (None, "allow"), (mode, decision, reason)
    helper = _helper_help()
    assert helper.returncode == 0, (
        "lanes.py has no commit subcommand",
        helper.returncode,
        helper.stdout,
        helper.stderr,
    )
    assert "--worktree" in helper.stdout and "--message-file" in helper.stdout, (
        helper.stdout
    )


def test_a_direct_commit_stays_denied_beside_the_helper() -> None:
    for command in DIRECT_COMMITS:
        for mode in PERMISSION_MODES:
            decision, reason = _decision(_hook(command, mode))
            assert decision == "deny", (command, mode, decision, reason)
            assert reason.startswith("[commit_gate] deny:"), (command, mode, reason)
    helper = _helper_help()
    assert helper.returncode == 0, (
        "the denied direct commit has no helper route yet",
        helper.returncode,
        helper.stdout,
        helper.stderr,
    )
    assert "--message-file" in helper.stdout, helper.stdout
