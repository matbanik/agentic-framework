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
``--exec-path``/``--namespace`` (each also consumes a separated value, AC-783.5)/
``--bare``/``--super-prefix``, an unknown option before the verb and an unknown verb all
make the command unsupported. ``git refs list|exists|verify`` and ``git lfs
version|env|ls-files|status`` are known verbs; other ``refs`` and ``lfs`` forms are
unknown (AC-783.8).

Segments and invocations. A simple command's segments are its own words and, apart,
each simple command of its command and process substitutions, so operands never span
``;``, ``&&``, ``|``, a newline or a closing ``)``. An invocation is a git token of a
segment with its global options (each value consumed by arity, so a value never starts
an invocation), the word in verb position and the words up to the next git token of
that segment; a read-only verb whose git token is the segment's executable (after only
command-introducing reserved words, assignments and ``rtk``/``rtk proxy``) takes the
words to the end of the segment. The arguments of an invocation whose verb is read-only
(``grep``, ``log``, ``show``, ``diff``, ``blame``, ``ls-files``, ``cat-file``,
``rev-parse``, ``status``) and the verb and arguments of a tag read (rule 10) are data
(AC-783.7). A remote-verb token is the word push, merge or tag outside data in a command
that holds a git token; it is *live*.

Before the rules: a command string whose text holds ``{{PROJECT_NAME_UPPER}}_REF_GUARD`` in any case
is denied, because only the human sets the main ref guard switch (AC-783.9).

Rules, first match per simple command. ``tools/tests/test_commit_gate.py`` holds at least
one test per rule; this list supersedes the run-parameters R§4.7 table (D-P6).

1. no git token → allow;
2. ``push`` or ``send-pack`` in verb position of an invocation → deny, the reason naming
   the human-directed push, unless the command is the canonical parsed ``git push`` of
   rule 11 (AC-783.2);
3. a git token, an unsupported construct and a live remote-verb token → deny;
4. ``commit`` with ``--no-verify``, ``-n`` or a hook-disabling ``-c`` (an option, not
   message text), also inside an unsupported construct → deny;
5. an invocation that sets ``core.hooksPath`` (``-c <key>=``, ``-c<key>=``,
   ``--config-env[=| ]<key>=``; the key compared without case) → deny (AC-783.3);
6. the driver ``[rtk proxy] uv run python tools/commit_batch.py …`` → allow (the driver
   verifies the grant or the human-directed message; run-parameters R§4.5);
7. a direct ``git commit`` → deny in every mode, naming ``tools/commit_batch.py``;
8. ref plumbing (S-0): ``commit-tree``, ``update-ref`` or a writing ``symbolic-ref`` →
   deny; inside an unsupported construct the verb of each invocation counts, and
   ``symbolic-ref`` writes there only with two non-option operands in that invocation or
   a delete option (AC-783.4);
9. a git token and an unsupported construct, no live remote-verb token: ``commit`` in
   verb position of an invocation → deny, naming ``tools/commit_batch.py``; an unknown
   verb (an alias or a ``git-<name>`` helper) → deny; otherwise → allow;
10. a parsed ``git tag`` with only list or verify options (``-l``, ``--list``, ``-n[<k>]``,
    ``-v``, ``--verify``, ``--contains``, ``--points-at``, ``--sort``, ``--format``), and
    names only with a list or verify option → allow in any spelling (AC-783.6);
11. push, merge or tag spelled exactly ``git <verb>`` or ``rtk proxy git <verb>`` (no
    assignment, no global option) → ask / deny;
12. push, merge or tag in any other spelling → deny;
13. any other git verb → allow.

Prompt hotfix 2026-10-21: rule 9 used to ask; it now allows or denies, and rule 8 denies,
so the only prompt left is rule 11, a push, merge or tag that a human directed. "ask /
deny" is ``ask`` in the asking modes (``default``, ``acceptEdits``, ``plan``, ``auto``,
``bypassPermissions``) and ``deny`` in ``dontAsk`` and in a missing or unknown mode,
where the hook cannot know that a prompt reaches anyone. The command string takes the
most restrictive outcome over its simple commands (deny > ask > allow).
``{{PROJECT_NAME_UPPER}}_COMMIT_APPROVED`` and ``{{PROJECT_NAME_UPPER}}_COMMIT_GRANT`` give a command no authority,
whether typed as an assignment or set in the hook's environment (D-19 A).

Stated limit (D§2.6): the hook does not read a quoted interpreter argument (``sh -c
"git commit …"``, ``perl -e'…'``) or a pager option (``git grep --op=…``); those allow.

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
    BashScan,
    ShellCommand,
    ShellWord,
    _BashScanner,
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
# Verbs that publish refs to a remote; only the canonical ``git push`` asks (rule 2).
PUSH_VERBS = frozenset({"push", "send-pack"})
# Verbs that write a commit object or move a ref without ``git commit`` (S-0).
REF_PLUMBING_VERBS = frozenset({"commit-tree", "update-ref", "symbolic-ref"})
# ``git symbolic-ref`` options of the read form; ``-m`` and ``-d``/``--delete`` write.
_SYMBOLIC_REF_READ_FLAGS = frozenset({"-q", "--quiet", "--short", "--no-recurse"})
DRIVER_ARGV = ("uv", "run", "python", "tools/commit_batch.py")
ALLOWED_CONFIG = frozenset({"core.autocrlf=false"})
HOOK_DISABLING_KEYS = frozenset({"core.hookspath"})
# The main ref guard switch (D§5.1 "Human escape"); compared without case (AC-783.9).
REF_GUARD_SWITCH = "{{PROJECT_NAME_UPPER}}_REF_GUARD".lower()

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
# The unsupported globals that take the next word as their value when given without
# ``=`` (AC-783.5); ``--bare`` and ``--super-prefix`` take none.
_SEPARATED_VALUE_GLOBALS = frozenset(
    {"--config-env", "--git-dir", "--work-tree", "--exec-path", "--namespace"}
)
# Built-in and shipped porcelain/plumbing verbs. An alias or an external ``git-<name>``
# helper is outside the list and therefore unsupported. Verbs that publish outside the
# repository by another route (send-email, imap-send, svn, p4, subtree, send-pack) are
# left out; ``refs`` and ``lfs`` are known only in their read forms (AC-783.8).
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
# Verbs known only with one of these subcommands (AC-783.8).
_READ_SUBCOMMANDS = {
    "refs": frozenset({"list", "exists", "verify"}),
    "lfs": frozenset({"version", "env", "ls-files", "status"}),
}
# Verbs whose arguments are data: they read the repository and run nothing (AC-783.7).
_READ_VERBS = frozenset(
    {
        "grep",
        "log",
        "show",
        "diff",
        "blame",
        "ls-files",
        "cat-file",
        "rev-parse",
        "status",
    }
)
# Reserved words that may come before the executable of a simple command (AC-783.7).
_LEADING_RESERVED = frozenset(
    {"do", "then", "else", "elif", "if", "while", "until", "!", "time"}
)
# ``git tag`` options of the list and verify forms (AC-783.6). The list options allow
# names (patterns, or tags to verify); the value options take ``=<v>`` or the next word.
_TAG_LIST_FLAGS = frozenset({"-l", "--list", "-n", "-v", "--verify"})
_TAG_LIST_VALUE = frozenset({"--contains", "--points-at"})
_TAG_FORMAT_VALUE = frozenset({"--sort", "--format"})
# ``git commit`` options that take the next word as their value when given without
# ``=``; a value is message text or a reference, never an option (rule 4).
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
# ``--d`` is the shortest abbreviation of symbolic-ref's ``--delete``.
_SYMBOLIC_REF_DELETE_MIN = len("--d")

_SEVERITY = {"allow": 0, "ask": 1, "deny": 2}

ASK_REASON = (
    f"[{HOOK_NAME}] Human approval gate (AGENTS.md §Hard Gates): "
    "push/merge/tag require a USER_EXPLICIT chat message."
)

Segment = tuple[ShellWord, ...]


@dataclass(frozen=True)
class Outcome:
    """One simple command's outcome; ``label`` names the verb, never the argv."""

    decision: str
    label: str
    commit: bool = False
    push: bool = False


@dataclass(frozen=True)
class _GitShape:
    """What the parser learned about a simple command that holds a git token."""

    unsupported: bool
    driver: bool
    verb: str | None
    canonical: bool
    args: tuple[str, ...] = ()
    known: bool = True


@dataclass(frozen=True)
class _Invocation:
    """One git token of a segment: its global options, verb word and argument words."""

    options: Segment
    verb: ShellWord | None
    args: Segment


class _SegmentScanner(_BashScanner):
    """``_BashScanner`` that also keeps the simple commands of each substitution apart.

    ``nested[i]`` holds the segments of the substitutions of ``commands[i]``, so an
    operand or a data word never spans a command boundary inside ``$(…)`` (AC-783.4).
    The scan result itself is the base scanner's, word for word.
    """

    def __init__(self, text: str) -> None:
        self.nested: list[tuple[Segment, ...]] = []
        super().__init__(text)

    def _new_command(self) -> None:
        super()._new_command()
        self.c_nested: list[Segment] = []

    def _end_command(self) -> None:
        nested = tuple(self.c_nested)
        super()._end_command()
        # ``_end_word`` may end a command first (a ``{`` or ``}`` word); that inner call
        # has already recorded its own entry, so only a missing entry is added here.
        while len(self.nested) < len(self.commands):
            self.nested.append(nested)

    def _nested(self, inner: str) -> None:
        sub = _SegmentScanner(inner)
        scan = sub.run()
        self.c_nested.extend(sub.segments())
        self.c_extra.extend(scan.words())
        if scan.opaque:
            self.opaque = True
        self._unsupported_word()

    def segments(self) -> tuple[Segment, ...]:
        """Each simple command's own words, then its substitutions' segments, in order."""
        out: list[Segment] = []
        for command, nested in zip(self.commands, self.nested, strict=True):
            out.append(command.words)
            out.extend(nested)
        return tuple(out)


def _scan(command: str) -> tuple[BashScan, tuple[tuple[Segment, ...], ...], bool]:
    """``scan_bash`` plus the segments of each simple command, aligned with its commands.

    The flag is True when the segments come from the full scan. An internal error falls
    back to ``scan_bash`` with one segment per simple command and the flag False, which
    keeps every git token and verb visible to the rules (fail closed).
    """
    try:
        scanner = _SegmentScanner(command)
        scan = scanner.run()
        groups = tuple(
            (simple.words, *nested)
            for simple, nested in zip(scan.commands, scanner.nested, strict=True)
        )
        return scan, groups, True
    except Exception:  # noqa: BLE001 - a hook must fail closed, not crash
        scan = scan_bash(command)
        return scan, tuple(((*c.words, *c.extra),) for c in scan.commands), False


def is_git_token(word: ShellWord) -> bool:
    """True when the word's last path component is ``git`` or ``git.exe``."""
    last = word.text.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return last in ("git", "git.exe")


def _texts(words: tuple[ShellWord, ...]) -> list[str]:
    return [w.text for w in words]


def _takes_value(option: str) -> bool:
    """True when a global option before the verb consumes the next word."""
    return option in ("-C", "-c") or option in _SEPARATED_VALUE_GLOBALS


def _verb_known(verb: str, args: tuple[str, ...]) -> bool:
    """True for a known verb, and for ``refs``/``lfs`` in a read form (AC-783.8)."""
    if verb in _KNOWN_VERBS:
        return True
    reads = _READ_SUBCOMMANDS.get(verb)
    return reads is not None and bool(args) and args[0] in reads


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
            k += 2 if text in _SEPARATED_VALUE_GLOBALS else 1
        elif text in _GLOBAL_FLAGS:
            k, global_options = k + 1, True
        elif text.startswith("-"):
            unsupported = True  # unknown option: its arity is unknown
            k += 1
        else:
            verb = text
            break
    args = tuple(_texts(body[k + 1 :])) if verb is not None else ()
    known = verb is None or _verb_known(verb, args)
    if not known:
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
    return _GitShape(unsupported, False, verb, canonical, args, known)


def _executable(segment: Segment, at: int) -> bool:
    """True when ``segment[at]`` is the executable of its simple command.

    Only command-introducing reserved words, then assignments, then ``rtk`` or ``rtk
    proxy`` may come before it. Any other word (``timeout``, ``xargs``, ``find -exec``)
    is a wrapper that may run more than one command.
    """
    n = 0
    while n < at and not segment[n].quoted and segment[n].text in _LEADING_RESERVED:
        n += 1
    while n < at and segment[n].assignment:
        n += 1
    if n < at and not segment[n].quoted and segment[n].text == "rtk":
        n += 1
        if n < at and not segment[n].quoted and segment[n].text == "proxy":
            n += 1
    return n == at


def _invocations(
    segments: tuple[Segment, ...], *, exact: bool = False
) -> list[_Invocation]:
    """Every git token of every segment, with its options, verb word and arguments.

    A global option's value is consumed by arity, so it never starts an invocation. The
    arguments of an invocation end at the next git token of its segment, and no
    invocation reads past its segment (AC-783.4). When ``exact`` holds (the segments
    come from a full scan), a read verb whose git token is in executable position reads
    to the end of its segment: a later ``git`` word is one of its arguments (AC-783.7).
    """
    found: list[_Invocation] = []
    for segment in segments:
        n = 0
        while n < len(segment):
            if not is_git_token(segment[n]):
                n += 1
                continue
            start, m = n, n + 1
            while m < len(segment) and segment[m].text.startswith("-"):
                m += 2 if _takes_value(segment[m].text) else 1
            m = min(m, len(segment))
            if m == len(segment) or is_git_token(segment[m]):
                found.append(_Invocation(segment[start + 1 : m], None, ()))
                n = m
                continue
            verb = segment[m]
            end = len(segment)
            if not (exact and verb.text in _READ_VERBS and _executable(segment, start)):
                end = next(
                    (k for k in range(m + 1, len(segment)) if is_git_token(segment[k])),
                    len(segment),
                )
            found.append(
                _Invocation(segment[start + 1 : m], verb, segment[m + 1 : end])
            )
            n = end
    return found


def _verb(invocation: _Invocation) -> str | None:
    return invocation.verb.text if invocation.verb is not None else None


def _tag_reads(args: tuple[str, ...] | list[str]) -> bool:
    """True when ``git tag`` arguments hold only list or verify options (AC-783.6).

    At least one option is needed, and a name or pattern only with a list or verify
    option; any other option (``-d``, ``-a``, ``-f`` …), ``--`` or an abbreviation is
    not a read.
    """
    options, lists, names, n = 0, False, False, 0
    while n < len(args):
        text = args[n]
        name = text.split("=", 1)[0]
        if text in _TAG_LIST_FLAGS or (text.startswith("-n") and text[2:].isdigit()):
            options, lists, n = options + 1, True, n + 1
        elif name in _TAG_LIST_VALUE:
            options, lists = options + 1, True
            has_value = "=" in text or n + 1 >= len(args) or args[n + 1].startswith("-")
            n += 1 if has_value else 2
        elif name in _TAG_FORMAT_VALUE:
            options += 1
            n += 1 if "=" in text else 2
        elif text.startswith("-"):
            return False
        else:
            names, n = True, n + 1
    return options > 0 and (lists or not names)


def _data_words(invocations: list[_Invocation]) -> set[int]:
    """The ids of the words that are data, never a gated word (AC-783.6, AC-783.7)."""
    data: set[int] = set()
    for invocation in invocations:
        verb = _verb(invocation)
        if verb in _READ_VERBS:
            data.update(id(w) for w in invocation.args)
        elif verb == "tag" and _tag_reads(_texts(invocation.args)):
            data.add(id(invocation.verb))
            data.update(id(w) for w in invocation.args)
    return data


def _sets_hooks_path(invocation: _Invocation) -> bool:
    """True when the invocation's global options set ``core.hooksPath`` (AC-783.3)."""
    texts = _texts(invocation.options)
    for n, text in enumerate(texts):
        if text in ("-c", "--config-env"):
            value = texts[n + 1] if n + 1 < len(texts) else ""
        elif text.startswith("--config-env="):
            value = text[len("--config-env=") :]
        elif text.startswith("-c") and not text.startswith("--"):
            value = text[2:]
        else:
            continue
        if value.split("=", 1)[0].lower() in HOOK_DISABLING_KEYS:
            return True
    return False


def _symbolic_ref_writes(args: tuple[str, ...]) -> bool:
    """True unless ``args`` is the read form ``[-q] [--short] [--no-recurse] <name>``."""
    names = [a for a in args if a not in _SYMBOLIC_REF_READ_FLAGS]
    return len(names) != 1 or names[0].startswith("-")


def _symbolic_ref_writes_bound(args: list[str]) -> bool:
    """The construct form of rule 8: a delete option or two non-option operands.

    ``args`` are one invocation's words, so operands never come from another command.
    """
    operands = 0
    for text in args:
        if text.startswith("--"):
            name = text.split("=", 1)[0]
            if len(name) >= _SYMBOLIC_REF_DELETE_MIN and "--delete".startswith(name):
                return True
        elif text.startswith("-") and len(text) > 1:
            if "d" in text[1:]:
                return True
        else:
            operands += 1
    return operands >= 2


def _ref_plumbing(shape: _GitShape, invocations: list[_Invocation]) -> bool:
    """True when the command runs a ref-plumbing verb (rule 8).

    A parsed command is judged by its verb and arguments. In an unsupported construct
    the verb of each invocation counts, and ``symbolic-ref`` by its bound operands.
    """
    if not shape.unsupported:
        if shape.verb == "symbolic-ref":
            return _symbolic_ref_writes(shape.args)
        return shape.verb in REF_PLUMBING_VERBS
    for invocation in invocations:
        verb = _verb(invocation)
        if verb == "symbolic-ref":
            if _symbolic_ref_writes_bound(_texts(invocation.args)):
                return True
        elif verb in REF_PLUMBING_VERBS:
            return True
    return False


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


def classify(
    command: ShellCommand,
    permission_mode: str | None,
    segments: tuple[Segment, ...] | None = None,
    *,
    exact: bool = False,
) -> Outcome:
    """Return the outcome of one simple command (rules 1-13 of the module docstring).

    ``segments`` are the command's own words and its substitutions' simple commands;
    without them the substitution words form one segment. ``exact`` marks segments
    from a full scan, whose simple-command boundaries are known (``_invocations``).
    """
    every = (*command.words, *command.extra)
    if not any(is_git_token(w) for w in every):
        return Outcome("allow", "no git")
    if segments is None:
        segments = (command.words, command.extra) if command.extra else (command.words,)
    invocations = _invocations(segments, exact=exact)
    data = _data_words(invocations)
    live = tuple(w for w in every if id(w) not in data)
    shape = _shape(command)
    canonical_push = not shape.unsupported and shape.verb == "push" and shape.canonical
    push = next(
        (v for i in invocations if (v := (_verb(i) or "").lower()) in PUSH_VERBS), None
    )
    if push is not None and not canonical_push:
        return Outcome("deny", f"{push} outside the canonical git push", push=True)
    remote = next(
        (w.text.lower() for w in live if w.text.lower() in REMOTE_VERBS), None
    )
    if shape.unsupported and remote is not None:
        return Outcome("deny", f"{remote} in an unsupported construct")
    # A parsed command commits only through its verb; inside an unsupported construct
    # the word ``commit`` after a git token is enough (rule 4 applies there too).
    commits, skips_hooks = (
        _commit_skips_hooks(live)
        if shape.unsupported or shape.verb == "commit"
        else (False, False)
    )
    if commits and skips_hooks:
        return Outcome("deny", "commit with a hook-disabling option", commit=True)
    if any(_sets_hooks_path(i) for i in invocations):
        return Outcome("deny", "core.hooksPath override")
    if shape.driver:
        return Outcome("allow", "commit_batch.py")
    if not shape.unsupported and shape.verb == "commit":
        return Outcome("deny", "commit", commit=True)
    if _ref_plumbing(shape, invocations):
        return Outcome("deny", "ref plumbing")
    if shape.unsupported:
        if any(_verb(i) == "commit" for i in invocations):
            return Outcome("deny", "commit in an unsupported construct", commit=True)
        if not shape.known:
            return Outcome("deny", "unknown git verb")
        return Outcome("allow", "unsupported git construct")
    if shape.verb == "tag" and _tag_reads(shape.args):
        return Outcome("allow", "tag read")
    if shape.verb in REMOTE_VERBS:
        if shape.canonical:
            return Outcome(_ask_or_deny(permission_mode), shape.verb)
        return Outcome("deny", f"{shape.verb} in a non-canonical spelling")
    return Outcome("allow", "git")


def classify_command(command: str, permission_mode: str | None) -> list[Outcome]:
    """Classify every simple command of a command string, in command order.

    An opaque string (a construct that hides the command boundaries) is one
    unsupported simple command made of all its words, with all its segments.
    """
    scan, groups, exact = _scan(command)
    if scan.opaque:
        every_segment = tuple(segment for group in groups for segment in group)
        merged = ShellCommand(scan.words(), (), True)
        return [classify(merged, permission_mode, every_segment, exact=exact)]
    return [
        classify(simple, permission_mode, group, exact=exact)
        for simple, group in zip(scan.commands, groups, strict=True)
    ]


def decide_command(command: str, permission_mode: str | None) -> tuple[str, str] | None:
    """Return ``(decision, reason)`` for a command string, or None when it is allowed."""
    ref_guard = REF_GUARD_SWITCH in command.lower()
    outcomes = classify_command(command, permission_mode)
    decision = max(
        (o.decision for o in outcomes), key=_SEVERITY.__getitem__, default="allow"
    )
    if ref_guard:
        decision = "deny"
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
    pushes = (
        " A push runs only as a human-directed push, spelled `git push …`, which asks."
        if any(o.push and o.decision == "deny" for o in outcomes)
        else ""
    )
    guard = (
        " The text names {{PROJECT_NAME_UPPER}}_REF_GUARD, the main ref guard switch; only the human "
        "sets it."
        if ref_guard
        else ""
    )
    listed = f" Non-allow segments: {segments}." if segments else ""
    reason = (
        f"[{HOOK_NAME}] deny: commit/push/merge/tag need a USER_EXPLICIT chat message "
        f"(AGENTS.md §Hard Gates).{driver}{pushes}{guard}{listed}"
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
