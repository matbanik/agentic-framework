"""The commit gate of the run-parameters port (B-3; AC-C.8, AC-C.9; ported for B-9, AC-I.1).

The {{PROJECT_NAME_TITLE}} source tests its two PreToolUse hooks in one module. The framework ships the
commit hook alone (``.claude/hooks/commit_gate.py`` and ``_hook_common.py``), so this module
holds the commit-gate subset: ``TestCommitGate``, the classifier tests, ``TestCommitGateStage0``
(the stage-0 classifier cases and the prompt hotfix of 2026-10-21) and the settings wiring.

* ``commit_gate.py`` denies a direct ``git commit`` in every mode and names the driver
  (``tools/commit_batch.py``); the canonical ``git <verb>`` and ``rtk proxy git <verb>`` of
  push, merge and tag ask in an asking mode and are denied in ``dontAsk`` or a missing mode;
  a token on a commit grants nothing.
* The settings tests read ``.claude/settings.json`` in an adopter and the fragment
  ``.claude/settings.hooks.json`` in the raw framework, where no ``settings.json`` exists.

The hooks run as real subprocesses, so a missing script fails as an assertion rather than a
collection error. Env names in shell text use ``APPROVED`` and ``GRANT``: in the raw framework
the project placeholder is not a shell name, so a plain name stands in; the hook treats every
assignment alike, whatever its name.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS_DIR = REPO_ROOT / ".claude" / "hooks"
COMMIT_GATE = HOOKS_DIR / "commit_gate.py"
FRAGMENT = REPO_ROOT / ".claude" / "settings.hooks.json"
ADOPTER_SETTINGS = REPO_ROOT / ".claude" / "settings.json"
SETTINGS = ADOPTER_SETTINGS if ADOPTER_SETTINGS.is_file() else FRAGMENT

_UPPER = "{{PROJECT_NAME_UPPER}}"
# The raw framework still holds the placeholder, which is not a shell name.
UPPER = "ADOPTER" if _UPPER.startswith("{" * 2) else _UPPER
APPROVED = f"{UPPER}_COMMIT_APPROVED"
GRANT = f"{UPPER}_COMMIT_GRANT"
HOOK_LOG_ENV = "{{PROJECT_NAME_UPPER}}_HOOK_LOG"

COMMIT_GATE_COMMAND = 'python "${CLAUDE_PROJECT_DIR}/.claude/hooks/commit_gate.py"'
# D-19 A (M7 H-8, D-40 A): the canonical push, merge and tag spellings are harness ``ask``
# rules; the commit spellings and the non-canonical ``rtk git push`` stay absent.
CANONICAL_ASK_RULES = ["Bash(git push *)", "Bash(git merge *)", "Bash(git tag *)"]
ABSENT_ASK_RULES = [
    "Bash(git commit *)",
    "Bash(rtk git commit *)",
    "Bash(rtk git push *)",
]


def _payload(command: object, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "session_id": "sess-test",
        "transcript_path": "C:/tmp/transcript.jsonl",
        "cwd": str(REPO_ROOT),
        "permission_mode": "default",
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_use_id": "toolu_test",
    }
    payload.update(overrides)
    return payload


def _run(
    script: Path, stdin_text: str, env_extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    assert script.is_file(), f"hook script missing: {script}"
    env = {k: v for k, v in os.environ.items() if k != HOOK_LOG_ENV}
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(script)],
        input=stdin_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=REPO_ROOT,
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


def _read_log(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# --- D-4: commit_gate ------------------------------------------------------------------


class TestCommitGate:
    ASK_REASON = (
        "[commit_gate] Human approval gate (AGENTS.md §Hard Gates): "
        "push/merge/tag require a USER_EXPLICIT chat message."
    )

    # M-7 H-1 (run-parameters B-3; AC-C.8, AC-C.9): a direct ``git commit`` is denied in
    # every mode and names the driver; ``rtk git push`` is not a canonical spelling (D-19 A).
    @pytest.mark.parametrize(
        ("command", "mode", "expected"),
        [
            ("git commit -m x", "default", "deny"),
            ("rtk git push origin main", "acceptEdits", "deny"),
            ("rtk proxy git tag v1", "default", "ask"),
            ("git status && git push", "default", "ask"),
            ("git merge feature", "plan", "ask"),
            ("git commit -m x", "auto", "deny"),
        ],
        ids=[
            "git-commit-default",
            "rtk-git-push-acceptedits",
            "rtk-proxy-git-tag",
            "chained-segment-push",
            "git-merge-plan",
            "git-commit-auto",
        ],
    )
    def test_interactive_modes_ask(
        self, command: str, mode: str, expected: str
    ) -> None:
        payload = _payload(command, permission_mode=mode)
        decision, reason = _decision(_run(COMMIT_GATE, json.dumps(payload)))
        assert decision == expected
        if expected == "ask":
            assert reason == self.ASK_REASON
        else:
            assert reason.startswith("[commit_gate] deny:")
            if "commit" in command:
                assert "tools/commit_batch.py" in reason

    @pytest.mark.parametrize(
        "command",
        [
            "git status",
            "git log --oneline -5",
            "git symbolic-ref --short HEAD",
            "rtk git diff --stat",
            "echo 'git commit' > note.txt",
        ],
        ids=[
            "status",
            "log",
            "symbolic-ref-read",
            "rtk-diff",
            "quoted-in-echo",
        ],
    )
    def test_ungated_commands_are_silent(self, command: str) -> None:
        decision, _ = _decision(_run(COMMIT_GATE, json.dumps(_payload(command))))
        assert decision is None

    @pytest.mark.parametrize(
        "payload",
        [
            _payload("git commit -m x", permission_mode="bypassPermissions"),
            _payload("git commit -m x", permission_mode="dontAsk"),
            {
                "session_id": "s",
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "git commit -m x"},
            },
        ],
        ids=["bypassPermissions", "dontAsk", "no-permission-mode-key"],
    )
    def test_headless_modes_deny_and_name_override(
        self, payload: dict[str, Any]
    ) -> None:
        decision, reason = _decision(_run(COMMIT_GATE, json.dumps(payload)))
        assert decision == "deny"
        assert reason.startswith("[commit_gate] deny:")
        assert "USER_EXPLICIT" in reason
        assert "AGENTS.md §Hard Gates" in reason
        # M-7 H-5 (D-19 A): the reason names the driver, never the deleted token.
        assert "tools/commit_batch.py" in reason
        assert "_COMMIT_APPROVED" not in reason

    def test_override_prefix_silences_the_hook(self) -> None:
        # M-7 H-2 (AC-C.8, AC-C.9): a token on a commit gives no authority.
        payload = _payload(
            f"{APPROVED}=1 git commit -m x",
            permission_mode="bypassPermissions",
        )
        decision, reason = _decision(_run(COMMIT_GATE, json.dumps(payload)))
        assert decision == "deny"
        assert "tools/commit_batch.py" in reason
        assert "_COMMIT_APPROVED" not in reason

    def test_override_must_prefix_the_gated_segment(self) -> None:
        # M-7 H-7 (D-19 A; AC-C.9): the token has no effect; the canonical ``git push``
        # asks under ``bypassPermissions`` and ``git status`` is an ordinary git verb.
        payload = _payload(
            f"{APPROVED}=1 git status && git push",
            permission_mode="bypassPermissions",
        )
        decision, reason = _decision(_run(COMMIT_GATE, json.dumps(payload)))
        assert decision == "ask"
        assert reason == self.ASK_REASON

    # R1-F1 (execution review round 1): the override is segment-local. An approved
    # first gated segment must not exempt a later gated segment from the gate.
    @pytest.mark.parametrize(
        "command",
        [
            f"{APPROVED}=1 rtk proxy git commit -m approved && rtk proxy git push origin main",
            f"{APPROVED}=1 git commit -m approved; git push origin main",
            f"{APPROVED}=1 git commit -m approved\ngit push origin main",
            f"{APPROVED}=1 git commit -m approved || git push origin main",
            f"{APPROVED}=1 rtk git commit -m approved && git status && rtk git tag v1",
        ],
        ids=["and-rtk-proxy", "semicolon", "newline", "or", "and-rtk-tag-after-status"],
    )
    @pytest.mark.parametrize(
        "mode",
        ["bypassPermissions", "dontAsk", None],
        ids=["bypass", "dontAsk", "no-mode"],
    )
    def test_override_on_first_segment_does_not_cover_later_gated_segment_headless(
        self, command: str, mode: str | None
    ) -> None:
        payload = _payload(command)
        if mode is None:
            del payload["permission_mode"]
        else:
            payload["permission_mode"] = mode
        decision, reason = _decision(_run(COMMIT_GATE, json.dumps(payload)))
        assert decision == "deny"
        assert reason.startswith("[commit_gate] deny:")
        # M-7 H-6 (D-19 A; D-35): the commit segment names the driver, never the token.
        assert "tools/commit_batch.py" in reason
        assert "_COMMIT_APPROVED" not in reason
        # The re-run hint names the segment that still needs approval, not the approved one.
        assert "push" in reason or "tag" in reason
        assert "-m approved" not in reason

    @pytest.mark.parametrize("mode", ["default", "plan", "acceptEdits"])
    def test_override_on_first_segment_still_asks_for_later_segment_interactive(
        self, mode: str
    ) -> None:
        # M-7 H-3 (AC-C.8): the commit segment is denied; the most restrictive outcome wins.
        payload = _payload(
            f"{APPROVED}=1 git commit -m approved && git push origin main",
            permission_mode=mode,
        )
        decision, reason = _decision(_run(COMMIT_GATE, json.dumps(payload)))
        assert decision == "deny"
        assert reason.startswith("[commit_gate] deny:")

    def test_every_gated_segment_overridden_is_silent(self) -> None:
        # M-7 H-4 (AC-C.8, AC-C.9): tokens on every segment still give no authority.
        payload = _payload(
            f"{APPROVED}=1 git commit -m x && {APPROVED}=1 git push origin main",
            permission_mode="bypassPermissions",
        )
        decision, _ = _decision(_run(COMMIT_GATE, json.dumps(payload)))
        assert decision == "deny"

    def test_deny_wins_over_override_in_the_log(self, tmp_path: Path) -> None:
        log = tmp_path / "hooks.jsonl"
        env = {HOOK_LOG_ENV: str(log)}
        command = f"{APPROVED}=1 git commit -m x && git push origin main"
        payload = _payload(command, permission_mode="bypassPermissions")
        _decision(_run(COMMIT_GATE, json.dumps(payload), env))
        lines = _read_log(log)
        assert len(lines) == 1
        assert lines[0]["command"] == command
        assert lines[0]["decision"] == "deny"

    @pytest.mark.parametrize("raw", ["not json", "[]", "null", '"str"'])
    def test_malformed_payload_is_silent(self, raw: str) -> None:
        proc = _run(COMMIT_GATE, raw)
        assert proc.returncode == 0
        assert proc.stdout == ""

    def test_hook_log_records_gated_decisions(self, tmp_path: Path) -> None:
        log = tmp_path / "hooks.jsonl"
        env = {HOOK_LOG_ENV: str(log)}
        denied = _payload("git commit -m x", permission_mode="bypassPermissions")
        _decision(_run(COMMIT_GATE, json.dumps(denied), env))
        _decision(_run(COMMIT_GATE, json.dumps(_payload("git status")), env))
        lines = _read_log(log)
        assert len(lines) == 1
        assert lines[0] == {
            "hook": "commit_gate",
            "session_id": "sess-test",
            "permission_mode": "bypassPermissions",
            "command": "git commit -m x",
            "decision": "deny",
        }


# --- run-parameters B-3: the commit_gate classifier (R§4.7) ----------------------------

ASKING_MODES = ["default", "acceptEdits", "plan", "auto", "bypassPermissions"]
ALL_MODES: list[str | None] = [*ASKING_MODES, "dontAsk", None, "unknownMode"]
ALL_MODE_IDS = [*ASKING_MODES, "dontAsk", "no-mode", "unknown-mode"]
# An argv marker that no reason may quote (D-35: segments by index and verb, never argv).
MARK = "zq9"
# ast.get_source_segment of split_segments, read with newline="" (run-parameters 5-splithash).
SPLIT_SEGMENTS_SHA256 = (
    "cb9811670ed11f63a99856710a3a7824ae3b69080cec9da948355851aff764fb"
)


def _gate(
    command: str, mode: str | None, env_extra: dict[str, str] | None = None
) -> tuple[str | None, str]:
    payload = _payload(command)
    if mode is None:
        del payload["permission_mode"]
    else:
        payload["permission_mode"] = mode
    return _decision(_run(COMMIT_GATE, json.dumps(payload), env_extra))


def _ask_or_deny(mode: str | None) -> str:
    """The decision-table outcome of rules 6 and 7 (R§4.7 :1275-1285)."""
    return "ask" if mode in ASKING_MODES else "deny"


def _assert_outcome(
    command: str,
    mode: str | None,
    expected: str,
    *,
    commit: bool = False,
    env_extra: dict[str, str] | None = None,
) -> str:
    decision, reason = _gate(command, mode, env_extra)
    if expected == "allow":
        assert decision is None, (decision, reason)
        assert reason == ""
    elif expected == "ask":
        assert decision == "ask", (decision, reason)
        assert reason == TestCommitGate.ASK_REASON
    else:
        assert decision == "deny", (decision, reason)
        assert reason.startswith("[commit_gate] deny:")
        assert "USER_EXPLICIT" in reason
        assert "AGENTS.md §Hard Gates" in reason
        assert "_COMMIT_APPROVED" not in reason
        assert MARK not in reason
        if commit:
            assert "tools/commit_batch.py" in reason
    return reason


class TestCommitGateClassifier:
    """The bash-dialect classifier of ``commit_gate.py`` (run-parameters B-3; R§4.7 :1188-1318).

    AC-C.8: every recognized spelling; every unsupported construct wrapped around a commit;
    assignment placement; ``--no-verify``/``-n`` in any position and inside a message; a
    direct ``git commit`` denied in every mode, the driver's own argv included; the driver
    spelling allowed; a token on a commit without authority; each mode column of the
    decision table, ``auto`` and a missing mode included; most-restrictive aggregation.
    AC-C.9 (D-19 A): ``{{PROJECT_NAME_UPPER}}_COMMIT_APPROVED=1`` has no effect; the canonical spellings
    ``git <verb>`` and ``rtk proxy git <verb>`` of push, merge and tag ask outside
    ``dontAsk`` and a missing or unknown mode; every other spelling is denied; a remote verb
    inside an unsupported construct is denied (rule 2 before rule 6). AC-C.10: the pipe
    guard still denies a producer piped to a filter, and ``_hook_common.split_segments`` is
    byte-unchanged. Ask and deny reasons follow D-35; an allow is silent.
    """

    # V3-020: a git token is a word whose last path component, after quote removal, is
    # git or git.exe (case-insensitive); rtk and rtk proxy are the only stripped wrappers.
    @pytest.mark.parametrize(
        ("spelling", "canonical"),
        [
            ("git", True),
            ("rtk proxy git", True),
            ("rtk git", False),
            ("git.exe", False),
            ("GIT", False),
            ("Git.EXE", False),
            ("/usr/bin/git", False),
            ('"C:/Program Files/Git/cmd/git.exe"', False),
            ("'C:\\Program Files\\Git\\cmd\\git.exe'", False),
            ("'git'", False),
            ('"git"', False),
            ("rtk proxy /usr/bin/git", False),
        ],
        ids=[
            "git",
            "rtk-proxy-git",
            "rtk-git",
            "git-exe",
            "upper",
            "mixed-case-exe",
            "posix-path",
            "windows-path-quoted",
            "windows-backslash-path",
            "single-quoted",
            "double-quoted",
            "rtk-proxy-path",
        ],
    )
    @pytest.mark.parametrize("mode", ["default", "dontAsk"])
    def test_vec_v3_020_every_recognized_spelling_is_classified(
        self, spelling: str, canonical: bool, mode: str
    ) -> None:
        _assert_outcome(f"{spelling} commit -m {MARK}", mode, "deny", commit=True)
        _assert_outcome(f"{spelling} status", mode, "allow")
        push = _ask_or_deny(mode) if canonical else "deny"
        _assert_outcome(f"{spelling} push origin {MARK}", mode, push)

    @pytest.mark.parametrize(
        "command",
        [f"gitx commit -m {MARK}", f"legit push origin {MARK}", "echo git-commit"],
        ids=["gitx", "legit", "hyphenated-word"],
    )
    def test_vec_v3_020_a_word_that_is_not_a_git_token_passes(
        self, command: str
    ) -> None:
        _assert_outcome(command, "dontAsk", "allow")

    # V3-021 / V3-051 (rule 6, prompt hotfix 2026-10-21): a git token with an unsupported
    # construct, no remote-verb token and the word ``commit`` after the git token is denied
    # in every mode and names the driver; an unknown verb (an alias) is denied. Nothing
    # waits for a prompt.
    @pytest.mark.parametrize(
        "command",
        [
            f"timeout 5 git commit -m {MARK}",
            f"find . -exec git commit -m {MARK} \\;",
            f"f() {{ git commit -m {MARK}; }}; f",
            f"git commit -m $'{MARK}'",
            f"git commit -F - <<EOF\n{MARK}\nEOF",
            f"git commit -F - <<< {MARK}",
            f"pwsh -c git commit -m {MARK}",
            f"powershell -Command git commit -m {MARK}",
            f"python -c git commit -m {MARK}",
            f"bash -c git commit -m {MARK}",
            f"env GIT_CONFIG_PARAMETERS={MARK} git commit -m {MARK}",
            f"GIT_DIR=.git git commit -m {MARK}",
            f"git commit -m `{MARK}`",
            f"git commit -m ${{{MARK}}}",
            f"xargs git commit -m {MARK}",
            f"nohup git commit -m {MARK}",
            f"sudo git commit -m {MARK}",
            f"eval git commit -m {MARK}",
            f"if true; then git commit -m {MARK}; fi",
            f"git --git-dir=.git commit -m {MARK}",
            f"git -c user.name={MARK} commit -m {MARK}",
            f"git ci -m {MARK}",
            f"git commit -m {MARK} *> C:/Temp/x.txt",
        ],
        ids=[
            "timeout",
            "find-exec",
            "function",
            "ansi-c-quoting",
            "heredoc",
            "herestring",
            "pwsh-c",
            "powershell-command",
            "python-c",
            "bash-c",
            "env-exported-config",
            "git-dir-assignment",
            "backtick",
            "parameter-expansion",
            "xargs",
            "nohup",
            "sudo",
            "eval",
            "if",
            "git-dir-option",
            "c-key-outside-allow-list",
            "unknown-verb",
            "pwsh-redirect",
        ],
    )
    @pytest.mark.parametrize("mode", ALL_MODES, ids=ALL_MODE_IDS)
    def test_vec_v3_021_vec_v3_051_unsupported_construct_around_a_commit(
        self, command: str, mode: str | None
    ) -> None:
        _assert_outcome(command, mode, "deny", commit="commit" in command)

    # Prompt hotfix 2026-10-21 (rule 6): an unsupported construct that holds a git token
    # but no commit, remote verb, ref-plumbing verb or unknown verb is allowed in every
    # mode. These shapes caused most bypass-mode prompts (census 2026-10-20).
    @pytest.mark.parametrize(
        "command",
        [
            "timeout 5 git log",
            "echo $(git rev-parse HEAD)",
            "git diff $(git merge-base HEAD main)",
            "git -c user.name=x log -1",
            "GIT_DIR=.git git status",
            "find . -name '*.py' -exec git add {} \\;",
            "xargs git add",
            "cat <<EOF > C:/Temp/x.txt\ngit status shows the tree\nEOF",
            "cat <<EOF > C:/Temp/x.txt\nthe git token, then a commit word\nEOF",
            "git -C . hash-object -t blob --stdin <<< x",
            "if true; then git status; fi",
        ],
        ids=[
            "timeout-log",
            "substitution-rev-parse",
            "substitution-merge-base",
            "c-key-log",
            "git-dir-status",
            "find-exec-add",
            "xargs-add",
            "heredoc-prose",
            "heredoc-prose-commit-word",
            "herestring-hash-object",
            "if-status",
        ],
    )
    @pytest.mark.parametrize("mode", ALL_MODES, ids=ALL_MODE_IDS)
    def test_hotfix_unsupported_construct_without_a_gated_word_is_allowed(
        self, command: str, mode: str | None
    ) -> None:
        _assert_outcome(command, mode, "allow")

    # S-0 (ruled 2026-10-21; deny, not ask, so nothing waits): ref plumbing that writes a
    # commit or moves a ref outside commit_batch.py is denied in every mode, also inside
    # an unsupported construct. The read-only symbolic-ref forms stay silent.
    @pytest.mark.parametrize(
        "command",
        [
            f"git commit-tree HEAD^{{tree}} -m {MARK}",
            f"git update-ref refs/heads/main {MARK}",
            f"git update-ref -d refs/heads/{MARK}",
            "git update-ref --stdin",
            f"git symbolic-ref HEAD refs/heads/{MARK}",
            "git symbolic-ref -d HEAD",
            "git symbolic-ref --delete HEAD",
            f"rtk proxy git update-ref refs/heads/main {MARK}",
            f"timeout 5 git update-ref refs/heads/main {MARK}",
            f"echo $(git commit-tree HEAD^{{tree}} -m {MARK})",
        ],
        ids=[
            "commit-tree",
            "update-ref",
            "update-ref-delete",
            "update-ref-stdin",
            "symbolic-ref-write",
            "symbolic-ref-d",
            "symbolic-ref-delete",
            "rtk-proxy-update-ref",
            "timeout-update-ref",
            "substitution-commit-tree",
        ],
    )
    @pytest.mark.parametrize("mode", ALL_MODES, ids=ALL_MODE_IDS)
    def test_s0_ref_plumbing_is_denied(self, command: str, mode: str | None) -> None:
        reason = _assert_outcome(command, mode, "deny")
        assert "ref plumbing" in reason

    @pytest.mark.parametrize(
        "command",
        [
            "git symbolic-ref HEAD",
            "git symbolic-ref -q HEAD",
            "git symbolic-ref --short HEAD",
            "git symbolic-ref --no-recurse HEAD",
            "git symbolic-ref -q --short HEAD",
        ],
        ids=["plain", "quiet", "short", "no-recurse", "quiet-short"],
    )
    @pytest.mark.parametrize("mode", ALL_MODES, ids=ALL_MODE_IDS)
    def test_s0_symbolic_ref_read_is_silent(
        self, command: str, mode: str | None
    ) -> None:
        _assert_outcome(command, mode, "allow")

    # V3-022 / V3-047 (rule 2): a remote-verb token inside an unsupported construct is
    # denied in every mode; rule 2 comes before rule 6.
    @pytest.mark.parametrize(
        "command",
        [
            f"timeout 5 git push origin {MARK}",
            f"echo $(git push origin {MARK})",
            f"git push {MARK} $BRANCH",
            f"find . -exec git tag {MARK} \\;",
            f"xargs git merge {MARK}",
            f"GIT_DIR=.git git push origin {MARK}",
            f"f() {{ git push origin {MARK}; }}; f",
            f"git push origin {MARK} <<< y",
            f"git --git-dir=.git tag {MARK}",
            f"if true; then git merge {MARK}; fi",
            f"pwsh -c git push origin {MARK}",
        ],
        ids=[
            "timeout-push",
            "command-substitution-push",
            "parameter-push",
            "find-exec-tag",
            "xargs-merge",
            "git-dir-assignment-push",
            "function-push",
            "herestring-push",
            "git-dir-option-tag",
            "if-merge",
            "pwsh-c-push",
        ],
    )
    @pytest.mark.parametrize("mode", ALL_MODES, ids=ALL_MODE_IDS)
    def test_vec_v3_022_vec_v3_047_remote_verb_inside_unsupported_is_denied(
        self, command: str, mode: str | None
    ) -> None:
        _assert_outcome(command, mode, "deny")

    # V3-023: assignment placement. An assignment on one simple command never covers
    # another; a hook-disabling -c before the verb is rule 3.
    @pytest.mark.parametrize(
        ("command", "commit"),
        [
            (f"git -c core.hooksPath=/dev/null commit -m {MARK}", True),
            (f"{GRANT}=op-1 git commit -m {MARK}", True),
            (f"GIT_DIR=.git git push origin {MARK}", False),
            (
                f"{GRANT}=op-1 uv run python tools/commit_batch.py commit "
                f"--op op-1; git commit -m {MARK}",
                True,
            ),
            (f"{GRANT}=op-1 git status && git commit -m {MARK}", True),
        ],
        ids=[
            "hooks-path-config",
            "grant-assignment-on-commit",
            "git-dir-assignment-on-push",
            "driver-assignment-does-not-cover-next",
            "assignment-on-status-does-not-cover-commit",
        ],
    )
    @pytest.mark.parametrize("mode", ALL_MODES, ids=ALL_MODE_IDS)
    def test_vec_v3_023_assignment_placement(
        self, command: str, commit: bool, mode: str | None
    ) -> None:
        _assert_outcome(command, mode, "deny", commit=commit)

    # V3-024 / V3-048 (rule 3): --no-verify, -n or a hook-disabling -c in any position.
    # Inside a message it is message text, and the command is still a direct commit (rule 5).
    @pytest.mark.parametrize(
        "command",
        [
            f"git commit --no-verify -m {MARK}",
            f"git commit -m {MARK} --no-verify",
            f"git commit -n -m {MARK}",
            f"git commit -m {MARK} -n",
            'git commit -m "--no-verify"',
            "git commit -m -n",
            f"rtk proxy git commit --no-verify -m {MARK}",
            f"git -c core.hooksPath=/dev/null commit -m {MARK}",
            f"timeout 5 git commit --no-verify -m {MARK}",
        ],
        ids=[
            "no-verify-first",
            "no-verify-last",
            "n-first",
            "n-last",
            "no-verify-as-message",
            "n-as-message",
            "rtk-proxy-no-verify",
            "hooks-path-config",
            "no-verify-inside-unsupported",
        ],
    )
    @pytest.mark.parametrize("mode", ALL_MODES, ids=ALL_MODE_IDS)
    def test_vec_v3_024_vec_v3_048_hook_disabling_option_is_denied(
        self, command: str, mode: str | None
    ) -> None:
        _assert_outcome(command, mode, "deny", commit=True)

    # V3-025 / V3-050 (rule 5): a direct git commit is denied in every mode, including
    # the argv the driver itself runs in its candidate worktree.
    @pytest.mark.parametrize(
        "command",
        [
            f"git commit -m {MARK}",
            f"git commit -F C:/Temp/{MARK}.txt",
            f"rtk git commit -m {MARK}",
            f"rtk proxy git commit -m {MARK}",
            f"git -C C:/Temp/{MARK} commit -S --cleanup=verbatim -F C:/Temp/{MARK}/msg.txt",
            f"git -c core.autocrlf=false commit --allow-empty -m {MARK}",
            "git commit",
            "git commit --amend --no-edit",
        ],
        ids=[
            "message",
            "message-file",
            "rtk-git",
            "rtk-proxy-git",
            "driver-argv",
            "allowed-config",
            "bare",
            "amend",
        ],
    )
    @pytest.mark.parametrize("mode", ALL_MODES, ids=ALL_MODE_IDS)
    def test_vec_v3_025_vec_v3_050_direct_commit_is_denied(
        self, command: str, mode: str | None
    ) -> None:
        _assert_outcome(command, mode, "deny", commit=True)

    # V3-026 / V3-049 (rule 4): the driver spelling passes the hook in every mode.
    @pytest.mark.parametrize(
        "command",
        [
            "uv run python tools/commit_batch.py commit --op op-1",
            "rtk proxy uv run python tools/commit_batch.py reconcile --op op-1",
            f"{GRANT}=op-1 uv run python tools/commit_batch.py commit --op op-1",
            "uv run python tools/commit_batch.py commit --op op-1 && git status",
        ],
        ids=["driver", "rtk-proxy-driver", "driver-with-grant", "driver-then-status"],
    )
    @pytest.mark.parametrize("mode", ALL_MODES, ids=ALL_MODE_IDS)
    def test_vec_v3_026_vec_v3_049_driver_spelling_is_allowed(
        self, command: str, mode: str | None
    ) -> None:
        _assert_outcome(command, mode, "allow")

    # V3-027 (D-19 A): the deleted override token gives a commit no authority.
    @pytest.mark.parametrize(
        "command",
        [
            f"{APPROVED}=1 git commit -m {MARK}",
            f"{APPROVED}=1 rtk proxy git commit -m {MARK}",
            f"{APPROVED}=1 {GRANT}=op-1 git commit -m {MARK}",
        ],
        ids=["token", "token-rtk-proxy", "token-and-grant"],
    )
    @pytest.mark.parametrize("mode", ALL_MODES, ids=ALL_MODE_IDS)
    def test_vec_v3_027_a_token_on_a_commit_has_no_authority(
        self, command: str, mode: str | None
    ) -> None:
        _assert_outcome(command, mode, "deny", commit=True)

    @pytest.mark.parametrize("mode", ALL_MODES, ids=ALL_MODE_IDS)
    def test_vec_v3_027_the_old_token_in_the_environment_has_no_effect(
        self, mode: str | None
    ) -> None:
        env = {f"{APPROVED}": "1"}
        _assert_outcome(
            f"git commit -m {MARK}", mode, "deny", commit=True, env_extra=env
        )
        _assert_outcome(
            f"git push origin {MARK}", mode, _ask_or_deny(mode), env_extra=env
        )

    # V3-028 / V3-052 (rule 7): a grant never authorizes a push; the canonical spelling
    # still asks, and a grant assignment makes the spelling non-canonical (rule 8).
    @pytest.mark.parametrize("mode", ALL_MODES, ids=ALL_MODE_IDS)
    def test_vec_v3_028_vec_v3_052_a_grant_never_authorizes_a_push(
        self, mode: str | None
    ) -> None:
        env = {f"{GRANT}": "op-1"}
        _assert_outcome(
            f"git push origin {MARK}", mode, _ask_or_deny(mode), env_extra=env
        )
        _assert_outcome(
            f"{GRANT}=op-1 git push origin {MARK}", mode, "deny"
        )
        _assert_outcome(
            f"{GRANT}=op-1 rtk proxy git tag {MARK}", mode, "deny"
        )

    @pytest.mark.parametrize(
        "command",
        [
            f"git push origin {MARK}",
            "git push",
            f"rtk proxy git push origin {MARK}",
            f"git merge {MARK}",
            f"rtk proxy git merge {MARK}",
            f"git tag {MARK}",
            f"rtk proxy git tag {MARK}",
        ],
        ids=[
            "push",
            "bare-push",
            "rtk-proxy-push",
            "merge",
            "rtk-proxy-merge",
            "tag",
            "rtk-proxy-tag",
        ],
    )
    @pytest.mark.parametrize("mode", ALL_MODES, ids=ALL_MODE_IDS)
    def test_vec_v3_052_canonical_remote_verb(
        self, command: str, mode: str | None
    ) -> None:
        _assert_outcome(command, mode, _ask_or_deny(mode))

    def test_ac_c9_token_on_a_canonical_push_is_denied_in_default_mode(self) -> None:
        # AC-C.9 under D-19 A: the token makes the spelling non-canonical (rule 8).
        _assert_outcome(
            f"{APPROVED}=1 git push origin {MARK}", "default", "deny"
        )

    # V3-053 (rule 8): every other recognized spelling of push, merge and tag is denied.
    @pytest.mark.parametrize(
        "command",
        [
            f"rtk git push origin {MARK}",
            f"git -C . push origin {MARK}",
            f"git --no-pager push origin {MARK}",
            f"/usr/bin/git push origin {MARK}",
            f"'git' push origin {MARK}",
            f"git.exe merge {MARK}",
            f"rtk git tag {MARK}",
            f"{APPROVED}=1 git push origin {MARK}",
            f"{APPROVED}=1 rtk proxy git merge {MARK}",
        ],
        ids=[
            "rtk-git-push",
            "dash-c-push",
            "no-pager-push",
            "path-push",
            "quoted-push",
            "exe-merge",
            "rtk-git-tag",
            "token-push",
            "token-rtk-proxy-merge",
        ],
    )
    @pytest.mark.parametrize("mode", ALL_MODES, ids=ALL_MODE_IDS)
    def test_vec_v3_053_other_remote_verb_spelling_is_denied(
        self, command: str, mode: str | None
    ) -> None:
        _assert_outcome(command, mode, "deny")

    # V3-046 (rule 1) and V3-054 (rule 9): no git token, or another git verb, is silent.
    @pytest.mark.parametrize(
        "command",
        [
            "echo push merge tag",
            "uv run pytest tests/ -q",
            "ls -la",
            "echo 'git commit'",
        ],
        ids=["remote-words", "pytest", "ls", "quoted-phrase"],
    )
    @pytest.mark.parametrize("mode", ALL_MODES, ids=ALL_MODE_IDS)
    def test_vec_v3_046_no_git_token_is_silent(
        self, command: str, mode: str | None
    ) -> None:
        _assert_outcome(command, mode, "allow")

    @pytest.mark.parametrize(
        "command",
        [
            "git status",
            "git log --oneline -5",
            "rtk git diff --stat",
            "rtk proxy git fetch origin",
            "git -C . status",
            "git -c core.autocrlf=false status",
            "git --no-pager log -1",
        ],
        ids=[
            "status",
            "log",
            "rtk-diff",
            "rtk-proxy-fetch",
            "dash-c",
            "allowed-config",
            "no-pager",
        ],
    )
    @pytest.mark.parametrize("mode", ALL_MODES, ids=ALL_MODE_IDS)
    def test_vec_v3_054_other_git_verb_is_silent(
        self, command: str, mode: str | None
    ) -> None:
        _assert_outcome(command, mode, "allow")

    # V3-029: the command string takes the most restrictive outcome over its simple
    # commands (deny > ask > allow); groups and asynchronous lists are classified recursively.
    @pytest.mark.parametrize(
        ("command", "mode", "expected", "commit"),
        [
            (f"git log && git push origin {MARK}", "default", "ask", False),
            (f"git log && git push origin {MARK}", "dontAsk", "deny", False),
            (f"git status | git commit -m {MARK}", "default", "deny", True),
            (f"git push origin {MARK} | git log", "auto", "ask", False),
            (
                f"git push origin {MARK}; rtk git push origin {MARK}",
                "default",
                "deny",
                False,
            ),
            (f"(git status; git commit -m {MARK})", "default", "deny", True),
            (f"{{ git log; git merge {MARK}; }}", "acceptEdits", "ask", False),
            (f"git log & git commit -m {MARK}", "plan", "deny", True),
            (f"git status |& git tag {MARK}", "bypassPermissions", "ask", False),
            (f"echo {MARK} && git status", "default", "allow", False),
            ("timeout 5 git log && git status", "default", "allow", False),
            (f"timeout 5 git log && git commit -m {MARK}", "default", "deny", True),
            (
                "uv run python tools/commit_batch.py commit --op op-1 && "
                f"git push origin {MARK}",
                "default",
                "ask",
                False,
            ),
            (
                "uv run python tools/commit_batch.py commit --op op-1 && "
                f"git push origin {MARK}",
                None,
                "deny",
                False,
            ),
        ],
        ids=[
            "allow-and-ask",
            "allow-and-ask-dontask",
            "pipeline-commit",
            "pipeline-push",
            "ask-and-deny",
            "subshell-commit",
            "group-merge",
            "async-commit",
            "pipe-stderr-tag",
            "all-allow",
            "unsupported-and-allow",
            "unsupported-and-deny",
            "driver-and-push",
            "driver-and-push-no-mode",
        ],
    )
    def test_vec_v3_029_most_restrictive_outcome_wins(
        self, command: str, mode: str | None, expected: str, commit: bool
    ) -> None:
        _assert_outcome(command, mode, expected, commit=commit)

    def test_vec_v3_029_a_deny_reason_lists_segments_by_verb_never_argv(self) -> None:
        command = f"git log && git push origin {MARK} && git commit -m {MARK}"
        reason = _assert_outcome(command, "default", "deny", commit=True)
        assert "push" in reason
        assert "commit" in reason
        assert "origin" not in reason

    def test_vec_v3_030_split_segments_is_byte_unchanged(self) -> None:
        import ast
        import hashlib

        path = HOOKS_DIR / "_hook_common.py"
        with path.open(encoding="utf-8", newline="") as handle:
            source = handle.read()
        nodes = [
            node
            for node in ast.parse(source).body
            if isinstance(node, ast.FunctionDef) and node.name == "split_segments"
        ]
        assert len(nodes) == 1
        segment = ast.get_source_segment(source, nodes[0])
        assert segment is not None
        digest = hashlib.sha256(segment.encode("utf-8")).hexdigest()
        assert digest == SPLIT_SEGMENTS_SHA256


class TestCommitGateStage0:
    """The stage-0 classifier changes of 2026-10-20-multi-agent-lanes (MEU-783).

    AC-783.2: ``push`` or ``send-pack`` in verb position after a git token, in a construct,
    a loop or a wrapper, is denied and the reason names the human-directed push; the
    canonical ``git push`` still asks. AC-783.3: a git invocation that sets
    ``core.hooksPath`` is denied. AC-783.4: in a construct ``symbolic-ref`` is denied only in
    the write form, with operands bound to one invocation. AC-783.5: separated global
    option values are consumed. AC-783.6: tag list and verify forms are read-only.
    AC-783.7: after a read-only verb later plain words are data, nested commands are still
    scanned. AC-783.8: ``git refs`` and ``git lfs`` read forms. AC-783.9: the ref-guard
    switch is the human's. AC-783.11: the round-2 attack strings and the D§2.6 "Effect"
    list keep their stated outcome.
    """

    @pytest.mark.parametrize(
        "command",
        [
            f"timeout 5 git send-pack origin {MARK}",
            f"timeout 5 git push origin {MARK}",
            f"for r in a; do git send-pack $r {MARK}; done",
            f"git send-pack origin {MARK}",
            f"rtk git send-pack origin {MARK}",
            f"echo $(git send-pack origin {MARK})",
            f"git -C . push origin {MARK}",
            f"f() {{ git push origin {MARK}; }}; f",
            f"git -C . --no-pager send-pack origin {MARK}",
        ],
        ids=[
            "timeout-send-pack",
            "timeout-push",
            "loop-send-pack",
            "plain-send-pack",
            "rtk-send-pack",
            "substitution-send-pack",
            "dash-c-push",
            "function-push",
            "global-options-send-pack",
        ],
    )
    @pytest.mark.parametrize("mode", ALL_MODES, ids=ALL_MODE_IDS)
    def test_ac783_2_send_pack_or_push_in_verb_position_is_denied(
        self, command: str, mode: str | None
    ) -> None:
        reason = _assert_outcome(command, mode, "deny")
        assert "human-directed push" in reason

    @pytest.mark.parametrize(
        "command",
        [
            f"git push origin {MARK}",
            f"rtk proxy git push origin {MARK}",
            f"git push origin {MARK} && timeout 5 git log",
        ],
        ids=["push", "rtk-proxy-push", "push-then-wrapped-log"],
    )
    @pytest.mark.parametrize("mode", ALL_MODES, ids=ALL_MODE_IDS)
    def test_ac783_2_send_pack_rule_keeps_the_canonical_push_ask(
        self, command: str, mode: str | None
    ) -> None:
        _assert_outcome(command, mode, _ask_or_deny(mode))

    @pytest.mark.parametrize(
        "command",
        [
            "git -c core.hooksPath=/dev/null reset --hard",
            "git -c CORE.HOOKSPATH=/dev/null reset --hard HEAD",
            "git -ccore.hooksPath=/dev/null status",
            "git --config-env=core.hooksPath=HP status",
            "git --config-env core.hooksPath=HP status",
            "timeout 5 git -c core.hooksPath=/dev/null reset --hard",
            "for f in a; do git -c core.hookspath=x checkout main; done",
            "echo $(git -c core.hooksPath=/dev/null status)",
            "git -C . -c Core.HooksPath=/dev/null merge-base HEAD main",
        ],
        ids=[
            "dash-c",
            "dash-c-upper",
            "dash-c-joined",
            "config-env-joined",
            "config-env-separated",
            "timeout",
            "loop-lower",
            "substitution",
            "after-dash-capital-c",
        ],
    )
    @pytest.mark.parametrize("mode", ALL_MODES, ids=ALL_MODE_IDS)
    def test_ac783_3_hookspath_override_is_denied(
        self, command: str, mode: str | None
    ) -> None:
        reason = _assert_outcome(command, mode, "deny")
        assert "core.hooksPath" in reason

    @pytest.mark.parametrize(
        "command",
        ["git -c core.editor=vi status", "git -c core.hooksPathx=1 log -1"],
        ids=["other-key", "longer-key"],
    )
    @pytest.mark.parametrize("mode", ALL_MODES, ids=ALL_MODE_IDS)
    def test_ac783_3_hookspath_rule_ignores_other_keys(
        self, command: str, mode: str | None
    ) -> None:
        _assert_outcome(command, mode, "allow")

    @pytest.mark.parametrize(
        "command",
        [
            "git -c core.hooksPath=/tmp/git status",
            "git --config-env=core.hooksPath=/tmp/git status",
            "git --config-env core.hooksPath=/tmp/git status",
            "timeout 5 git -c core.hooksPath=/tmp/git reset --hard",
            "git -ccore.hooksPath=/tmp/git status",
        ],
        ids=[
            "dash-c",
            "config-env-joined",
            "config-env-separated",
            "timeout",
            "dash-c-joined",
        ],
    )
    @pytest.mark.parametrize("mode", ALL_MODES, ids=ALL_MODE_IDS)
    def test_ac783_3_hookspath_value_ending_in_git_is_denied(
        self, command: str, mode: str | None
    ) -> None:
        # A global option's value is never a git token, even when its last path
        # component is "git" (R1-F2).
        reason = _assert_outcome(command, mode, "deny")
        assert "core.hooksPath" in reason

    @pytest.mark.parametrize(
        "command",
        [
            f"x=$(git symbolic-ref HEAD refs/heads/{MARK})",
            f"timeout 5 git symbolic-ref HEAD refs/heads/{MARK}",
            "timeout 5 git symbolic-ref -d HEAD",
            "for r in a; do git symbolic-ref --delete HEAD; done",
            f'git -C "$r" symbolic-ref HEAD refs/heads/{MARK}',
            "timeout 5 git symbolic-ref -qd HEAD",
            "timeout 5 git symbolic-ref --del HEAD",
            f"timeout 5 git symbolic-ref -m why HEAD refs/heads/{MARK}",
        ],
        ids=[
            "substitution-write",
            "timeout-write",
            "timeout-d",
            "loop-delete",
            "dash-c-write",
            "short-cluster-d",
            "delete-abbreviation",
            "message-write",
        ],
    )
    @pytest.mark.parametrize("mode", ALL_MODES, ids=ALL_MODE_IDS)
    def test_ac783_4_symbolic_ref_write_in_a_construct_is_denied(
        self, command: str, mode: str | None
    ) -> None:
        reason = _assert_outcome(command, mode, "deny")
        assert "ref plumbing" in reason

    @pytest.mark.parametrize(
        "command",
        [
            "echo $(git symbolic-ref --short HEAD)",
            "timeout 5 git symbolic-ref --short HEAD",
            'git -C "$r" symbolic-ref -q HEAD',
            "for r in a; do git symbolic-ref -q HEAD; done",
            "b=$(git symbolic-ref --short HEAD); echo a b",
            "for r in a; do git symbolic-ref -q HEAD; echo a b; done",
            "timeout 5 git symbolic-ref -q HEAD && echo a b",
            "timeout 5 git symbolic-ref -q HEAD || echo a b",
            "for r in a; do git symbolic-ref -q HEAD | cat; done",
            "echo $(git symbolic-ref --short HEAD) b",
            "echo $(git symbolic-ref --short HEAD; echo a b)",
            "for r in a; do git symbolic-ref -q HEAD\necho a b; done",
            "git symbolic-ref --short HEAD; echo a b",
        ],
        ids=[
            "substitution-short",
            "timeout-short",
            "dash-c-quiet",
            "loop-quiet",
            "semicolon",
            "loop-semicolon",
            "and",
            "or",
            "pipe",
            "closing-paren",
            "semicolon-inside-substitution",
            "newline",
            "parsed-semicolon",
        ],
    )
    @pytest.mark.parametrize("mode", ALL_MODES, ids=ALL_MODE_IDS)
    def test_ac783_4_symbolic_ref_read_in_a_construct_is_allowed(
        self, command: str, mode: str | None
    ) -> None:
        _assert_outcome(command, mode, "allow")

    @pytest.mark.parametrize(
        "command",
        [
            "git --git-dir .git status",
            "git --work-tree . status",
            "git --namespace ns log -1",
            "git --git-dir .git --work-tree . diff --stat",
            "git --exec-path /usr/lib/git-core status",
        ],
        ids=["git-dir", "work-tree", "namespace", "git-dir-and-work-tree", "exec-path"],
    )
    @pytest.mark.parametrize("mode", ALL_MODES, ids=ALL_MODE_IDS)
    def test_ac783_5_global_option_value_is_consumed(
        self, command: str, mode: str | None
    ) -> None:
        _assert_outcome(command, mode, "allow")

    @pytest.mark.parametrize(
        "command",
        [
            f"git --git-dir .git commit -m {MARK}",
            f"git --work-tree . commit -m {MARK}",
            f"git --bare commit -m {MARK}",
            f"timeout 5 git --namespace ns commit -m {MARK}",
        ],
        ids=["git-dir", "work-tree", "bare-takes-no-value", "wrapped-namespace"],
    )
    @pytest.mark.parametrize("mode", ALL_MODES, ids=ALL_MODE_IDS)
    def test_ac783_5_global_option_value_never_hides_the_commit_verb(
        self, command: str, mode: str | None
    ) -> None:
        _assert_outcome(command, mode, "deny", commit=True)

    @pytest.mark.parametrize(
        "command",
        [
            "git tag -l",
            "git tag --list",
            "git tag -l 'v1*'",
            "git tag -n5",
            "git tag -n -l",
            "git tag -v v1.0",
            "git tag --verify v1.0",
            "git tag --contains HEAD",
            "git tag --points-at HEAD",
            "git tag --sort=-v:refname",
            "git tag --sort -creatordate -l",
            "git tag '--format=%(refname)' -l",
            "rtk git tag -l",
            "rtk proxy git tag --list",
            "git -C . tag -l",
        ],
        ids=[
            "l",
            "list",
            "l-pattern",
            "n-count",
            "n-and-l",
            "v",
            "verify",
            "contains",
            "points-at",
            "sort-joined",
            "sort-separated",
            "format",
            "rtk-git",
            "rtk-proxy-git",
            "dash-c",
        ],
    )
    @pytest.mark.parametrize("mode", ALL_MODES, ids=ALL_MODE_IDS)
    def test_ac783_6_tag_read_is_allowed(self, command: str, mode: str | None) -> None:
        _assert_outcome(command, mode, "allow")

    @pytest.mark.parametrize(
        "command",
        [
            "git tag -l -d v1",
            f"git tag -a v1 -m {MARK}",
            "git tag --list --delete v1",
            "git tag v1",
            "git tag -f v1",
            "git tag --sort=refname v2",
            "git tag",
        ],
        ids=["l-d", "annotate", "list-delete", "name", "force", "sort-name", "bare"],
    )
    @pytest.mark.parametrize("mode", ALL_MODES, ids=ALL_MODE_IDS)
    def test_ac783_6_tag_read_with_a_mutation_keeps_the_ask(
        self, command: str, mode: str | None
    ) -> None:
        _assert_outcome(command, mode, _ask_or_deny(mode))

    @pytest.mark.parametrize("mode", ALL_MODES, ids=ALL_MODE_IDS)
    def test_ac783_6_tag_read_rule_keeps_a_non_canonical_mutation_denied(
        self, mode: str | None
    ) -> None:
        _assert_outcome("rtk git tag -l -d v1", mode, "deny")
        _assert_outcome(f"git -C . tag -a v1 -m {MARK}", mode, "deny")

    @pytest.mark.parametrize(
        "command",
        [
            'git -C "$r" grep -n push -- docs',
            'git -C "$r" grep commit -n README.md',
            'git -C "$r" log --grep=merge --oneline',
            'git -C "$r" log --grep tag -1',
            "for f in a; do git grep -n push docs; done",
            'git -C "$r" show HEAD --stat -- merge',
            'git -C "$r" diff HEAD -- push commit',
            'git -C "$r" blame -L 1,2 tag.txt push',
            'git -C "$r" ls-files push',
            'git -C "$r" cat-file -p HEAD:push',
            'git -C "$r" rev-parse --verify tag',
            'git -C "$r" status --short push',
        ],
        ids=[
            "grep-push",
            "grep-commit-n",
            "log-grep-merge",
            "log-grep-tag",
            "loop-grep-push",
            "show",
            "diff",
            "blame",
            "ls-files",
            "cat-file",
            "rev-parse",
            "status",
        ],
    )
    @pytest.mark.parametrize("mode", ALL_MODES, ids=ALL_MODE_IDS)
    def test_ac783_7_read_verb_data_is_allowed(
        self, command: str, mode: str | None
    ) -> None:
        _assert_outcome(command, mode, "allow")

    @pytest.mark.parametrize(
        "command",
        [
            "git -C . grep -e git -e push -- docs",
            "git -C . grep -n git push -- docs",
            f"git log git commit -m {MARK}",
            f"for f in a; do git log git commit -m {MARK}; done",
            "rtk proxy git grep -n git push -- docs",
            "X=1 git grep git merge -- docs",
        ],
        ids=[
            "grep-e-git-e-push",
            "grep-git-push",
            "log-git-commit",
            "loop-log-git-commit",
            "rtk-proxy-grep",
            "assignment-grep",
        ],
    )
    @pytest.mark.parametrize("mode", ALL_MODES, ids=ALL_MODE_IDS)
    def test_ac783_7_a_git_word_in_read_verb_data_is_data(
        self, command: str, mode: str | None
    ) -> None:
        # A read verb in executable position reads to the end of its segment: a later
        # "git" word is one of its arguments, not a new invocation (R1-F2).
        _assert_outcome(command, mode, "allow")

    @pytest.mark.parametrize(
        ("command", "commit"),
        [
            (f'git grep "$(git push origin {MARK})"', False),
            (f'git -C "$r" log $(git commit -m {MARK})', True),
            (f"git -C \"$r\" grep `git push origin {MARK}`", False),
            (f"for f in a; do git grep x; git push origin {MARK}; done", False),
            (f'git -C "$r" grep push -- docs; timeout 5 git commit -m {MARK}', True),
            (f"find . -exec git log {{}} \\; -exec git push origin {MARK} \\;", False),
            (f"timeout 5 git log -1 git push origin {MARK}", False),
        ],
        ids=[
            "grep-substitution-push",
            "log-substitution-commit",
            "grep-backtick-push",
            "loop-next-command-push",
            "next-command-commit",
            "find-exec-read-then-push",
            "wrapped-read-then-push",
        ],
    )
    @pytest.mark.parametrize("mode", ALL_MODES, ids=ALL_MODE_IDS)
    def test_ac783_7_read_verb_never_hides_a_nested_command(
        self, command: str, commit: bool, mode: str | None
    ) -> None:
        _assert_outcome(command, mode, "deny", commit=commit)

    @pytest.mark.parametrize(
        "command",
        [
            "git refs list",
            "git refs exists refs/heads/main",
            "git refs verify",
            "git lfs version",
            "git lfs env",
            "git lfs ls-files",
            "git lfs status",
            "rtk git lfs ls-files",
        ],
        ids=[
            "refs-list",
            "refs-exists",
            "refs-verify",
            "lfs-version",
            "lfs-env",
            "lfs-ls-files",
            "lfs-status",
            "rtk-lfs-ls-files",
        ],
    )
    @pytest.mark.parametrize("mode", ALL_MODES, ids=ALL_MODE_IDS)
    def test_ac783_8_refs_lfs_read_is_allowed(
        self, command: str, mode: str | None
    ) -> None:
        _assert_outcome(command, mode, "allow")

    @pytest.mark.parametrize(
        "command",
        [
            "git refs migrate --ref-format=reftable",
            "git refs",
            "git lfs install",
            f"git lfs push origin {MARK}",
            "git lfs",
        ],
        ids=["refs-migrate", "refs-bare", "lfs-install", "lfs-push", "lfs-bare"],
    )
    @pytest.mark.parametrize("mode", ALL_MODES, ids=ALL_MODE_IDS)
    def test_ac783_8_refs_lfs_other_forms_are_denied(
        self, command: str, mode: str | None
    ) -> None:
        _assert_outcome(command, mode, "deny")

    # The hook holds the literal token form of the switch name, so these cases build it
    # from ``_UPPER`` directly: the raw framework keeps the placeholder, an adopter its name.
    @pytest.mark.parametrize(
        "command",
        [
            f"{_UPPER}_REF_GUARD=off git update-ref refs/heads/main {MARK}",
            f"export {_UPPER}_REF_GUARD=off".lower(),
            f"{_UPPER}_REF_GUARD=off git status",
            f"echo ${_UPPER}_REF_GUARD",
            f"env {f'{_UPPER}_REF_GUARD'.title()}=0 git log",
            f"unset {_UPPER}_REF_GUARD",
            f"echo ok; export {_UPPER}_REF_GUARD=off",
        ],
        ids=[
            "assignment-update-ref",
            "export-lower",
            "assignment-status",
            "read",
            "env-mixed-case",
            "unset",
            "second-command",
        ],
    )
    @pytest.mark.parametrize("mode", ALL_MODES, ids=ALL_MODE_IDS)
    def test_ac783_9_ref_guard_env_is_denied(
        self, command: str, mode: str | None
    ) -> None:
        reason = _assert_outcome(command, mode, "deny")
        assert "only the human sets it" in reason
        assert f"{_UPPER}_REF_GUARD" in reason

    # D§2.6 "Effect on the round-2 attack strings": the seven round-2 inputs hide the act in
    # a quoted interpreter argument or a pager option, which the hook does not read (the
    # stated limit); they allow in both modes Astra ran.
    @pytest.mark.parametrize(
        "command",
        [
            'for f in a; do git status; "sh" -c "git commit -am hidden"; done',
            'for f in a; do git status; "sh" -c "git push origin HEAD"; done',
            'for f in a; do git status; "eval" "git update-ref refs/heads/main HEAD~1"; done',
            "for f in a; do git grep --op=vim needle; done",
            "git grep --op=\"sh -c 'git commit -am hidden' --\" needle",
            "for f in a; do git status; perl -e'system(\"git commit -am hidden\")'; done",
            "for f in a; do git config --unset-a core.hooksPath; done",
        ],
        ids=[
            "quoted-sh-commit",
            "quoted-sh-push",
            "quoted-eval-update-ref",
            "grep-open-files-in-pager",
            "grep-pager-shell",
            "perl-attached-code",
            "config-unset-abbreviation",
        ],
    )
    @pytest.mark.parametrize("mode", ["default", "bypassPermissions"])
    def test_ac783_11_round2_attack_strings_keep_the_stated_limit(
        self, command: str, mode: str
    ) -> None:
        _assert_outcome(command, mode, "allow")

    @pytest.mark.parametrize(
        ("command", "expected", "commit"),
        [
            (f"timeout 5 git commit -m {MARK}", "deny", True),
            (f"GIT_DIR=.git git commit -m {MARK}", "deny", True),
            (f"echo $(git commit -m {MARK})", "deny", True),
            (f"git commit-tree HEAD^{{tree}} -m {MARK}", "deny", False),
            (f"git update-ref refs/heads/main {MARK}", "deny", False),
            (f"timeout 5 git commit-tree HEAD^{{tree}} -m {MARK}", "deny", False),
            (f"bash -c \"git commit -m {MARK}\"", "allow", False),
            ("timeout 5 git ci", "allow", False),
            ("git pull", "allow", False),
            ("git rebase main", "allow", False),
            ("git cherry-pick HEAD~1", "allow", False),
            ("git revert HEAD", "allow", False),
            (f"git am C:/Temp/{MARK}.patch", "allow", False),
            ("git reset --hard", "allow", False),
        ],
        ids=[
            "timeout-commit",
            "git-dir-commit",
            "substitution-commit",
            "commit-tree",
            "update-ref",
            "timeout-commit-tree",
            "bash-c-commit",
            "timeout-alias",
            "pull",
            "rebase",
            "cherry-pick",
            "revert",
            "am",
            "reset-hard",
        ],
    )
    @pytest.mark.parametrize("mode", ALL_MODES, ids=ALL_MODE_IDS)
    def test_ac783_11_round2_effect_list(
        self, command: str, expected: str, commit: bool, mode: str | None
    ) -> None:
        _assert_outcome(command, mode, expected, commit=commit)


# --- settings wiring (FS row 44) -------------------------------------------------------


def _load(path: Path) -> dict[str, Any]:
    assert path.is_file(), f"missing {path}"
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    assert isinstance(data, dict), f"{path} is not a JSON object"
    return data


def test_settings_wire_the_commit_gate() -> None:
    """The PreToolUse ``Bash`` matcher runs the commit hook (adopter or raw fragment)."""
    hooks = _load(SETTINGS).get("hooks")
    assert isinstance(hooks, dict), f"{SETTINGS.name} has no hooks block"
    pre = hooks.get("PreToolUse")
    assert isinstance(pre, list), f"{SETTINGS.name} has no PreToolUse list"
    commands = [
        hook.get("command")
        for group in pre
        if isinstance(group, dict) and group.get("matcher") == "Bash"
        for hook in group.get("hooks", [])
        if isinstance(hook, dict) and hook.get("type") == "command"
    ]
    assert commands.count(COMMIT_GATE_COMMAND) == 1, commands


def test_fragment_carries_the_canonical_ask_rules() -> None:
    """The fragment holds the D-19 A ``ask`` rules and no commit spelling."""
    ask = _load(FRAGMENT).get("permissions", {}).get("ask", [])
    assert isinstance(ask, list), "settings.hooks.json permissions.ask is not a list"
    missing = [rule for rule in CANONICAL_ASK_RULES if rule not in ask]
    assert missing == [], f"D-19 A ask rules missing: {missing}"
    present = [rule for rule in ABSENT_ASK_RULES if rule in ask]
    assert present == [], f"ask rules that duplicate commit_gate: {present}"
