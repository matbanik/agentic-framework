"""PreToolUse hook: the human approval gate for commit / push / merge / tag.

AGENTS.md §Hard Gates: an irreversible git act needs a USER_EXPLICIT chat message. The
Bash tool runs Git Bash, so the command string is a bash script; ``_hook_common.scan_bash``
splits it into simple commands in the recognized dialect of run-parameters R§4.7 and
marks every other construct as unsupported.

Git detection. A git token is a word whose last path component (after ``/`` or ``\\``
and quote removal) is ``git`` or ``git.exe``, case-insensitively. A simple command is a
git command when its executable word, after the wrappers ``rtk`` and ``rtk proxy``, is a
git token. A git token anywhere else, a leading ``GIT_*`` assignment, a ``-c`` key other
than ``core.autocrlf=false``, ``--config-env``/``--git-dir``/``--work-tree``/
``--exec-path``/``--namespace``/``--bare``/``--super-prefix``, an unknown option before
the verb and an unknown verb all make the command unsupported. A remote-verb token is
the word push, merge or tag anywhere in a command that holds a git token.

Rules, first match per simple command:

1. no git token → allow;
2. a git token, an unsupported construct and a remote-verb token → deny;
3. ``commit`` with ``--no-verify``, ``-n`` or a hook-disabling ``-c`` (an option, not
   message text), also inside an unsupported construct → deny;
4. the driver ``[rtk proxy] uv run python tools/commit_batch.py …`` → allow (the driver
   verifies the grant or the human-directed message; run-parameters R§4.5);
5. a direct ``git commit`` → deny in every mode, naming ``tools/commit_batch.py``;
6. a git token and an unsupported construct, no remote-verb token → ask / deny;
7. push, merge or tag spelled exactly ``git <verb>`` or ``rtk proxy git <verb>`` (no
   assignment, no global option) → ask / deny;
8. push, merge or tag in any other spelling → deny;
9. any other git verb → allow.

"ask / deny" is ``ask`` in the asking modes (``default``, ``acceptEdits``, ``plan``,
``auto``, ``bypassPermissions``) and ``deny`` in ``dontAsk`` and in a missing or unknown
mode, where the hook cannot know that a prompt reaches anyone. The command string takes
the most restrictive outcome over its simple commands (deny > ask > allow).
``{{PROJECT_NAME_UPPER}}_COMMIT_APPROVED`` and ``{{PROJECT_NAME_UPPER}}_COMMIT_GRANT`` give a command no authority,
whether typed as an assignment or set in the hook's environment (D-19 A).

Reasons (D-35): an ask reason is ``ASK_REASON``; a deny reason starts with
``[commit_gate] deny:``, names ``tools/commit_batch.py`` when a commit is denied and
lists each non-allow simple command by index and verb, never by argv. An allow is silent.

Contract: exit 0 always; malformed stdin → no output. When ``{{PROJECT_NAME_UPPER}}_HOOK_LOG`` names a
file, one JSON line per ask or deny decision is appended.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _hook_common import (  # noqa: E402 - path insert above
    ShellCommand,
    ShellWord,
    append_log,
    emit_decision,
    read_hook_input,
    scan_bash,
)

HOOK_NAME = "commit_gate"
ASKING_MODES = frozenset(
    {"default", "acceptEdits", "plan", "auto", "bypassPermissions"}
)
REMOTE_VERBS = frozenset({"push", "merge", "tag"})
DRIVER_ARGV = ("uv", "run", "python", "tools/commit_batch.py")
ALLOWED_CONFIG = frozenset({"core.autocrlf=false"})
HOOK_DISABLING_KEYS = frozenset({"core.hookspath"})

# Global options git accepts before the verb, by arity (git.c handle_options).
_GLOBAL_FLAGS = frozenset(
    {
        "-p",
        "--paginate",
        "-P",
        "--no-pager",
        "--no-replace-objects",
        "--literal-pathspecs",
        "--glob-pathspecs",
        "--noglob-pathspecs",
        "--icase-pathspecs",
        "--no-optional-locks",
    }
)
_UNSUPPORTED_GLOBALS = frozenset(
    {
        "--config-env",
        "--git-dir",
        "--work-tree",
        "--exec-path",
        "--namespace",
        "--bare",
        "--super-prefix",
    }
)
# Built-in and shipped porcelain/plumbing verbs. An alias or an external ``git-<name>``
# helper is outside the list and therefore unsupported. Verbs that publish outside the
# repository by another route (send-email, imap-send, svn, p4, subtree, lfs) are left out.
_KNOWN_VERBS = frozenset(
    {
        "add",
        "am",
        "annotate",
        "apply",
        "archive",
        "bisect",
        "blame",
        "branch",
        "bundle",
        "cat-file",
        "check-attr",
        "check-ignore",
        "check-mailmap",
        "check-ref-format",
        "checkout",
        "checkout-index",
        "cherry",
        "cherry-pick",
        "clean",
        "clone",
        "commit",
        "commit-graph",
        "commit-tree",
        "config",
        "count-objects",
        "describe",
        "diff",
        "diff-files",
        "diff-index",
        "diff-tree",
        "difftool",
        "fetch",
        "for-each-ref",
        "format-patch",
        "fsck",
        "gc",
        "grep",
        "hash-object",
        "help",
        "init",
        "log",
        "ls-files",
        "ls-remote",
        "ls-tree",
        "maintenance",
        "merge",
        "merge-base",
        "merge-file",
        "merge-tree",
        "mergetool",
        "mktree",
        "mv",
        "name-rev",
        "notes",
        "pack-refs",
        "prune",
        "pull",
        "push",
        "range-diff",
        "read-tree",
        "rebase",
        "reflog",
        "remote",
        "repack",
        "replace",
        "request-pull",
        "rerere",
        "reset",
        "restore",
        "rev-list",
        "rev-parse",
        "revert",
        "rm",
        "shortlog",
        "show",
        "show-branch",
        "show-ref",
        "sparse-checkout",
        "stash",
        "status",
        "submodule",
        "switch",
        "symbolic-ref",
        "tag",
        "update-index",
        "update-ref",
        "var",
        "verify-commit",
        "verify-pack",
        "verify-tag",
        "version",
        "whatchanged",
        "worktree",
        "write-tree",
    }
)
# ``git commit`` options that take the next word as their value when given without
# ``=``; a value is message text or a reference, never an option (rule 3).
_COMMIT_VALUE_LONG = frozenset(
    {
        "--message",
        "--file",
        "--reuse-message",
        "--reedit-message",
        "--fixup",
        "--squash",
        "--author",
        "--date",
        "--template",
        "--cleanup",
        "--trailer",
        "--pathspec-from-file",
    }
)
_COMMIT_VALUE_SHORT = frozenset("mFCct")
_COMMIT_OPTIONAL_SHORT = frozenset("Su")
# Shortest unambiguous abbreviation git's parse-options accepts for --no-verify
# (``--no-ver`` also matches --no-verbose).
_NO_VERIFY_MIN = len("--no-veri")

_SEVERITY = {"allow": 0, "ask": 1, "deny": 2}

ASK_REASON = (
    f"[{HOOK_NAME}] Human approval gate (AGENTS.md §Hard Gates): "
    "commit/push/merge/tag require a USER_EXPLICIT chat message."
)


@dataclass(frozen=True)
class Outcome:
    """One simple command's outcome; ``label`` names the verb, never the argv."""

    decision: str
    label: str
    commit: bool = False


@dataclass(frozen=True)
class _GitShape:
    """What the parser learned about a simple command that holds a git token."""

    unsupported: bool
    driver: bool
    verb: str | None
    canonical: bool


def is_git_token(word: ShellWord) -> bool:
    """True when the word's last path component is ``git`` or ``git.exe``."""
    last = word.text.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return last in ("git", "git.exe")


def _texts(words: tuple[ShellWord, ...]) -> list[str]:
    return [w.text for w in words]


def _shape(command: ShellCommand) -> _GitShape:
    """Parse assignments, wrappers, global options and the verb of a simple command."""
    words = command.words
    unsupported = command.unsupported or bool(command.extra)
    i = 0
    while i < len(words) and words[i].assignment:
        if words[i].raw.split("=", 1)[0].upper().startswith("GIT_"):
            unsupported = True
        i += 1
    has_assignment = i > 0
    rest = words[i:]

    j, wrapper = 0, ""
    if rest and rest[0].text == "rtk":
        if len(rest) > 1 and rest[1].text == "proxy":
            j, wrapper = 2, "rtk proxy"
        else:
            j, wrapper = 1, "rtk"

    body = rest[j:]
    driver = (
        not unsupported
        and wrapper in ("", "rtk proxy")
        and tuple(_texts(body[: len(DRIVER_ARGV)])) == DRIVER_ARGV
        and not any(w.quoted for w in body[: len(DRIVER_ARGV)])
    )
    if driver or not body or not is_git_token(body[0]):
        # The git token is somewhere other than the executable position.
        return _GitShape(True, driver, None, False)
    exe = body[0]
    if exe.unsupported or exe.globbed:
        unsupported = True
    if any(is_git_token(w) for w in body[1:]):
        unsupported = True

    k, global_options, verb = 1, False, None
    while k < len(body):
        text = body[k].text
        if text == "-C":
            if k + 1 >= len(body):
                unsupported = True
            k, global_options = k + 2, True
        elif text == "-c":
            value = body[k + 1].text if k + 1 < len(body) else ""
            if value not in ALLOWED_CONFIG:
                unsupported = True
            k, global_options = k + 2, True
        elif text.split("=", 1)[0] in _UNSUPPORTED_GLOBALS:
            unsupported = True
            k += 1
        elif text in _GLOBAL_FLAGS:
            k, global_options = k + 1, True
        elif text.startswith("-"):
            unsupported = True  # unknown option: its arity is unknown
            k += 1
        else:
            verb = text
            break
    if verb is not None and verb not in _KNOWN_VERBS:
        unsupported = True
    canonical = (
        not has_assignment
        and wrapper in ("", "rtk proxy")
        and all(not w.quoted for w in rest[: j + 1])
        and exe.raw == "git"
        and not global_options
        and verb is not None
        and not body[k].quoted
    )
    return _GitShape(unsupported, False, verb, canonical)


def _commit_skips_hooks(words: tuple[ShellWord, ...]) -> tuple[bool, bool]:
    """Return ``(commits, skips_hooks)`` for the words of one simple command.

    ``commits`` is set when the word ``commit`` follows a git token. ``skips_hooks`` is
    set by ``-c core.hooksPath=…`` or ``--config-env`` naming it before that word, or by
    ``--no-verify`` (or an abbreviation) or ``-n`` among the commit options after it;
    the value of a value-taking option is skipped, so message text never counts.
    """
    texts = _texts(words)
    start = next((n for n, w in enumerate(words) if is_git_token(w)), None)
    if start is None:
        return False, False
    commit_at = next(
        (n for n in range(start + 1, len(texts)) if texts[n] == "commit"), None
    )
    if commit_at is None:
        return False, False
    skips = False
    for n in range(start + 1, commit_at):
        text = texts[n].lower()
        if text == "-c" and n + 1 < commit_at:
            key = texts[n + 1].split("=", 1)[0].lower()
            skips = skips or key in HOOK_DISABLING_KEYS
        elif text.startswith("--config-env"):
            value = (
                text
                if "=" in text
                else (texts[n + 1].lower() if n + 1 < commit_at else "")
            )
            skips = skips or any(key in value for key in HOOK_DISABLING_KEYS)
    n = commit_at + 1
    while n < len(texts):
        text = texts[n]
        if text == "--":
            break
        if text.startswith("--"):
            name = text.split("=", 1)[0]
            if len(name) >= _NO_VERIFY_MIN and "--no-verify".startswith(name):
                skips = True
            n += 2 if name in _COMMIT_VALUE_LONG and "=" not in text else 1
            continue
        if text.startswith("-") and len(text) > 1:
            consumed_next = False
            for pos, flag in enumerate(text[1:], start=1):
                if flag == "n":
                    skips = True
                elif flag in _COMMIT_VALUE_SHORT:
                    consumed_next = pos == len(text) - 1
                    break
                elif flag in _COMMIT_OPTIONAL_SHORT:
                    break
            n += 2 if consumed_next else 1
            continue
        n += 1
    return True, skips


def _ask_or_deny(permission_mode: str | None) -> str:
    return "ask" if permission_mode in ASKING_MODES else "deny"


def classify(command: ShellCommand, permission_mode: str | None) -> Outcome:
    """Return the outcome of one simple command (R§4.7 rules 1-9)."""
    every = (*command.words, *command.extra)
    if not any(is_git_token(w) for w in every):
        return Outcome("allow", "no git")
    remote = next(
        (w.text.lower() for w in every if w.text.lower() in REMOTE_VERBS), None
    )
    shape = _shape(command)
    if shape.unsupported and remote is not None:
        return Outcome("deny", f"{remote} in an unsupported construct")
    # A parsed command commits only through its verb; inside an unsupported construct
    # the word ``commit`` after a git token is enough (rule 3 applies there too).
    commits, skips_hooks = (
        _commit_skips_hooks(every)
        if shape.unsupported or shape.verb == "commit"
        else (False, False)
    )
    if commits and skips_hooks:
        return Outcome("deny", "commit with a hook-disabling option", commit=True)
    if shape.driver:
        return Outcome("allow", "commit_batch.py")
    if not shape.unsupported and shape.verb == "commit":
        return Outcome("deny", "commit", commit=True)
    if shape.unsupported:
        return Outcome(_ask_or_deny(permission_mode), "unsupported git construct")
    if shape.verb in REMOTE_VERBS:
        if shape.canonical:
            return Outcome(_ask_or_deny(permission_mode), shape.verb)
        return Outcome("deny", f"{shape.verb} in a non-canonical spelling")
    return Outcome("allow", "git")


def classify_command(command: str, permission_mode: str | None) -> list[Outcome]:
    """Classify every simple command of a command string, in command order.

    An opaque string (a construct that hides the command boundaries) is one
    unsupported simple command made of all its words.
    """
    scan = scan_bash(command)
    if scan.opaque:
        return [classify(ShellCommand(scan.words(), (), True), permission_mode)]
    return [classify(simple, permission_mode) for simple in scan.commands]


def decide_command(command: str, permission_mode: str | None) -> tuple[str, str] | None:
    """Return ``(decision, reason)`` for a command string, or None when it is allowed."""
    outcomes = classify_command(command, permission_mode)
    decision = max(
        (o.decision for o in outcomes), key=_SEVERITY.__getitem__, default="allow"
    )
    if decision == "allow":
        return None
    if decision == "ask":
        return "ask", ASK_REASON
    segments = ", ".join(
        f"#{index} {o.label} ({o.decision})"
        for index, o in enumerate(outcomes, start=1)
        if o.decision != "allow"
    )
    driver = (
        " Commits run through tools/commit_batch.py, which verifies the grant or the "
        "human-directed message."
        if any(o.commit and o.decision == "deny" for o in outcomes)
        else ""
    )
    reason = (
        f"[{HOOK_NAME}] deny: commit/push/merge/tag need a USER_EXPLICIT chat message "
        f"(AGENTS.md §Hard Gates).{driver} Non-allow segments: {segments}."
    )
    return "deny", reason


def main() -> int:
    data = read_hook_input(sys.stdin.read())
    if data is None:
        return 0
    verdict = decide_command(data.command, data.permission_mode)
    if verdict is None:
        return 0
    decision, reason = verdict
    append_log(HOOK_NAME, data, decision)
    emit_decision(decision, reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
