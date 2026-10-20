"""Shared plumbing for the {{PROJECT_NAME_TITLE}} Claude Code hooks.

The PreToolUse hooks (``pipe_filter_guard.py``, ``commit_gate.py``) and the PostToolUse
``delegation_streak.py`` follow the vendor contract: exit 0 always, output only as a
JSON object on stdout, and silence for anything they do not understand. This module is
deliberately stdlib-only so the hooks run under whichever interpreter
``uv run --no-sync --project`` resolves without a dependency sync.

Payload contract (Boundary Input Contract): stdin must be a JSON object. A list, null,
scalar, or unparsable stdin is not a decision surface and yields no output. Only the
fields a hook reads are looked at; every other key is ignored (Claude Code adds fields
across releases, and the hooks must fail open).
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass

# Segment separators for a shell command line. A pipeline inside one segment is the
# unit both hooks reason about; ``;``, ``&&``, ``||`` and newlines start a new segment.
_SEGMENT_SPLIT = ("&&", "||", ";", "\n")

# Logical line continuations joined BEFORE splitting on newlines, so a pipeline that
# wraps across lines stays one segment: a POSIX ``\\<newline>``, a PowerShell
# backtick-newline, a line that ends with ``|`` and a line that starts with ``|``.
_CONTINUATION_RE = re.compile(r"(?:\\|`)\r?\n[ \t]*")
_TRAILING_PIPE_RE = re.compile(r"(?<!\|)\|[ \t]*\r?\n[ \t]*")
_LEADING_PIPE_RE = re.compile(r"[ \t]*\r?\n[ \t]*\|(?!\|)")


@dataclass(frozen=True)
class HookInput:
    """The subset of a tool-event payload the hooks act on.

    ``command`` is the Bash command line, or ``""`` for a non-Bash tool that carries
    none. ``agent_id`` is set only when a subagent made the call.
    """

    session_id: str
    permission_mode: str | None
    command: str
    tool_name: str
    agent_id: str | None


def read_hook_input(
    raw: str,
    events: tuple[str, ...] = ("PreToolUse",),
    tools: tuple[str, ...] = ("Bash",),
) -> HookInput | None:
    """Parse a tool-event payload whose event is in ``events`` and tool in ``tools``.

    The defaults are the PreToolUse ``Bash`` contract the two PreToolUse hooks rely on.
    Returns None (the hook stays silent) when the payload is not a JSON object, its
    ``hook_event_name`` or ``tool_name`` is outside the accepted sets, or a ``Bash``
    call carries no string ``tool_input.command``. For any other tool the command is
    optional and defaults to ``""``.
    """
    try:
        payload = json.loads(raw) if raw.strip() else None
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("hook_event_name") not in events:
        return None
    tool_name = payload.get("tool_name")
    if not isinstance(tool_name, str) or tool_name not in tools:
        return None
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if tool_name == "Bash":
        if not isinstance(command, str):
            return None
    elif not isinstance(command, str):
        command = ""
    mode = payload.get("permission_mode")
    session = payload.get("session_id")
    agent = payload.get("agent_id")
    return HookInput(
        session_id=session if isinstance(session, str) else "",
        permission_mode=mode if isinstance(mode, str) else None,
        command=command,
        tool_name=tool_name,
        agent_id=agent if isinstance(agent, str) and agent else None,
    )


def join_continuations(command: str) -> str:
    """Fold logical line continuations into single lines.

    ``\\<newline>`` and PowerShell backtick-newline become a space; a newline right
    after or right before a pipe ``|`` (``||`` excluded) is folded into that pipe, so
    ``pytest tests |<newline>tail`` is one pipeline, not two segments. CRLF is
    normalised first; every other newline still separates segments.
    """
    text = command.replace("\r\n", "\n")
    text = _CONTINUATION_RE.sub(" ", text)
    text = _TRAILING_PIPE_RE.sub("| ", text)
    return _LEADING_PIPE_RE.sub(" |", text)


def split_segments(command: str) -> list[str]:
    """Split a command line into its ``;`` / ``&&`` / ``||`` / newline segments.

    Logical continuations (``join_continuations``) are folded first so a multiline
    pipeline is judged as the single segment it executes as.
    """
    segments = [join_continuations(command)]
    for separator in _SEGMENT_SPLIT:
        segments = [part for seg in segments for part in seg.split(separator)]
    return [seg.strip() for seg in segments if seg.strip()]


# --- bash tokenizer (commit_gate.py; run-parameters R§4.7 "Recognized dialect") ---------
#
# The Bash tool runs Git Bash, so a command string is a bash script. ``scan_bash`` splits
# it into simple commands on ``;``, ``&&``, ``||``, ``|``, ``|&``, ``&``, newline and the
# group delimiters, with bash quoting and redirections, and marks every construct outside
# the recognized dialect as unsupported. ``split_segments`` above is deliberately left
# as it is: ``pipe_filter_guard.py`` needs a whole pipeline in one segment.

_RESERVED_WORDS = frozenset(
    {
        "if",
        "then",
        "else",
        "elif",
        "fi",
        "for",
        "while",
        "until",
        "do",
        "done",
        "case",
        "esac",
        "select",
        "function",
        "time",
        "coproc",
        "!",
        "[[",
        "]]",
    }
)
_ASSIGNMENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
_BRACE_EXPANSION_RE = re.compile(r"\{[^{}\s]*(?:,|\.\.)[^{}\s]*\}")
_GLOB_CHARS = frozenset("*?[")
_DQ_ESCAPABLE = frozenset('$`"\\\n')


@dataclass(frozen=True)
class ShellWord:
    """One shell word: ``text`` after quote removal, ``raw`` as typed.

    ``quoted`` is set when any part was quoted or escaped; ``unsupported`` when the word
    holds an expansion the tokenizer does not evaluate (``$``, a backtick, a process
    substitution, brace expansion); ``globbed`` when an unquoted glob character occurs;
    ``assignment`` when the word starts with an unquoted ``NAME=``.
    """

    text: str
    raw: str
    quoted: bool
    unsupported: bool
    globbed: bool
    assignment: bool


@dataclass(frozen=True)
class ShellCommand:
    """One simple command; ``extra`` holds the words of its command substitutions."""

    words: tuple[ShellWord, ...]
    extra: tuple[ShellWord, ...]
    unsupported: bool


@dataclass(frozen=True)
class BashScan:
    """The simple commands of a command string.

    ``opaque`` is set when a construct hides the command boundaries (a function
    definition, a reserved word, a heredoc, an unterminated quote or substitution); the
    caller then treats every word of the string as one unsupported command.
    """

    commands: tuple[ShellCommand, ...]
    opaque: bool

    def words(self) -> tuple[ShellWord, ...]:
        """Every word of every command, substitutions included, in command order."""
        return tuple(w for c in self.commands for w in (*c.words, *c.extra))


class _BashScanner:
    """A single-pass bash tokenizer; see ``scan_bash``."""

    def __init__(self, text: str) -> None:
        self.s = text.replace("\r\n", "\n")
        self.n = len(self.s)
        self.commands: list[ShellCommand] = []
        self.opaque = False
        self._new_command()
        self._new_word()

    # -- state ---------------------------------------------------------------------------

    def _new_word(self) -> None:
        self.w_text: list[str] = []
        self.w_raw: list[str] = []
        self.w_unquoted: list[str] = []
        self.w_started = False
        self.w_quoted = False
        self.w_unsupported = False

    def _new_command(self) -> None:
        self.c_words: list[ShellWord] = []
        self.c_extra: list[ShellWord] = []
        self.c_unsupported = False
        self.redirect_pending = False

    def _append(self, text: str, raw: str, *, quoted: bool) -> None:
        self.w_started = True
        self.w_text.append(text)
        self.w_raw.append(raw)
        if quoted:
            self.w_quoted = True
        else:
            self.w_unquoted.append(text)

    def _unsupported_word(self) -> None:
        self.w_started = True
        self.w_unsupported = True
        self.c_unsupported = True

    def _end_word(self) -> None:
        if not self.w_started:
            return
        raw = "".join(self.w_raw)
        unquoted = "".join(self.w_unquoted)
        unsupported = self.w_unsupported or bool(_BRACE_EXPANSION_RE.search(unquoted))
        word = ShellWord(
            text="".join(self.w_text),
            raw=raw,
            quoted=self.w_quoted,
            unsupported=unsupported,
            globbed=any(ch in _GLOB_CHARS for ch in unquoted),
            assignment=bool(_ASSIGNMENT_RE.match(raw)),
        )
        self._new_word()
        if unsupported:
            self.c_unsupported = True
        if self.redirect_pending:
            # A redirection target is one plain word and is not part of the argv.
            self.redirect_pending = False
            return
        if not word.quoted and word.text in ("{", "}"):
            self._end_command()
            return
        self.c_words.append(word)

    def _end_command(self) -> None:
        self._end_word()
        if self.redirect_pending:
            self.c_unsupported = True  # a redirection without a target
            self.redirect_pending = False
        if self.c_words or self.c_extra:
            first = next((w for w in self.c_words if not w.assignment), None)
            if first is not None and not first.quoted and first.text in _RESERVED_WORDS:
                self.opaque = True
            self.commands.append(
                ShellCommand(
                    tuple(self.c_words), tuple(self.c_extra), self.c_unsupported
                )
            )
        self._new_command()

    # -- nested text -----------------------------------------------------------------------

    def _balanced(self, start: int) -> tuple[str, int]:
        """Return the text inside the ``(`` at ``start`` and the index after its ``)``."""
        depth, j = 0, start
        while j < self.n:
            ch = self.s[j]
            if ch == "\\":
                j += 2
                continue
            if ch == "'":
                close = self.s.find("'", j + 1)
                j = self.n if close < 0 else close + 1
                continue
            if ch == '"':
                j += 1
                while j < self.n and self.s[j] != '"':
                    j += 2 if self.s[j] == "\\" else 1
                j += 1
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return self.s[start + 1 : j], j + 1
            j += 1
        self.opaque = True
        return self.s[start + 1 :], self.n

    def _nested(self, inner: str) -> None:
        """Add the words of a command or process substitution to the current command."""
        scan = _BashScanner(inner).run()
        self.c_extra.extend(scan.words())
        if scan.opaque:
            self.opaque = True
        self._unsupported_word()

    def _backtick(self, i: int) -> int:
        j = i + 1
        while j < self.n and self.s[j] != "`":
            j += 2 if self.s[j] == "\\" else 1
        if j >= self.n:
            self.opaque = True
            j = self.n
        inner = self.s[i + 1 : j].replace("\\`", "`")
        self._nested(inner)
        self.w_raw.append(self.s[i : j + 1])
        return j + 1

    def _dollar(self, i: int) -> int:
        """Consume an unquoted ``$`` expansion; every form is unsupported."""
        s = self.s
        if s.startswith("$(", i):
            inner, end = self._balanced(i + 1)
            self._nested(inner)
            self.w_raw.append(s[i:end])
            return end
        self._unsupported_word()
        if s.startswith("$'", i):
            j = i + 2
            while j < self.n and s[j] != "'":
                j += 2 if s[j] == "\\" else 1
            if j >= self.n:
                self.opaque = True
            self._append(s[i + 2 : j], s[i : j + 1], quoted=True)
            return j + 1
        if s.startswith('$"', i):
            return self._double(i + 1)
        if s.startswith("${", i):
            close = s.find("}", i + 2)
            end = self.n if close < 0 else close + 1
            if close < 0:
                self.opaque = True
            self._append(s[i:end], s[i:end], quoted=True)
            return end
        self._append("$", "$", quoted=True)
        return i + 1

    def _double(self, i: int) -> int:
        """Consume a ``"…"`` string starting at ``i``; return the index after it."""
        s, j, text = self.s, i + 1, []
        while j < self.n and s[j] != '"':
            ch = s[j]
            if ch == "\\" and j + 1 < self.n and s[j + 1] in _DQ_ESCAPABLE:
                if s[j + 1] != "\n":
                    text.append(s[j + 1])
                j += 2
                continue
            if ch == "$" and s.startswith("$(", j):
                inner, end = self._balanced(j + 1)
                self._nested(inner)
                text.append(s[j:end])
                j = end
                continue
            if ch == "`":
                close = j + 1
                while close < self.n and s[close] != "`":
                    close += 2 if s[close] == "\\" else 1
                self._nested(s[j + 1 : close].replace("\\`", "`"))
                text.append(s[j : close + 1])
                j = close + 1
                continue
            if ch == "$":
                self._unsupported_word()
            text.append(ch)
            j += 1
        if j >= self.n:
            self.opaque = True
        self._append("".join(text), s[i : j + 1], quoted=True)
        return j + 1

    def _redirect(self, i: int) -> int:
        """Consume a redirection operator at ``i``; its target is the next word."""
        s = self.s
        if self.w_started:
            current = "".join(self.w_raw)
            if current == "*" and not self.w_quoted:
                self.c_unsupported = True  # PowerShell ``*>`` is a parse error in bash
                self._new_word()
            elif current.isdigit() and not self.w_quoted:
                self._new_word()  # ``[n]>``: the descriptor is not a word
            else:
                self._end_word()
        if s.startswith("<<<", i):
            self.c_unsupported = True
            self.redirect_pending = True
            return i + 3
        if s.startswith("<<", i):
            self.opaque = True  # a heredoc body follows on the next lines
            self.redirect_pending = True
            return i + (3 if s.startswith("<<-", i) else 2)
        if s.startswith("<(", i) or s.startswith(">(", i):
            inner, end = self._balanced(i + 1)
            self._nested(inner)
            self._new_word()
            return end
        width = 2 if s[i : i + 2] in (">>", ">|", ">&", "<&", "<>") else 1
        self.redirect_pending = True
        return i + width

    # -- main loop -------------------------------------------------------------------------

    def run(self) -> BashScan:
        s = self.s
        i = 0
        while i < self.n:
            ch = s[i]
            if ch == "\\":
                if i + 1 < self.n and s[i + 1] == "\n":
                    i += 2
                    continue
                nxt = s[i + 1] if i + 1 < self.n else ""
                self._append(nxt, s[i : i + 2], quoted=True)
                i += 2
            elif ch in " \t":
                self._end_word()
                i += 1
            elif ch == "\n":
                self._end_command()
                i += 1
            elif ch == "#" and not self.w_started:
                newline = s.find("\n", i)
                i = self.n if newline < 0 else newline
            elif ch == "'":
                close = s.find("'", i + 1)
                if close < 0:
                    self.opaque = True
                    close = self.n
                self._append(s[i + 1 : close], s[i : close + 1], quoted=True)
                i = close + 1
            elif ch == '"':
                i = self._double(i)
            elif ch == "`":
                i = self._backtick(i)
            elif ch == "$":
                i = self._dollar(i)
            elif ch in "<>":
                i = self._redirect(i)
            elif ch == "&":
                if s.startswith("&>", i):
                    self._end_word()
                    self.redirect_pending = True
                    i += 3 if s.startswith("&>>", i) else 2
                else:
                    self._end_command()
                    i += 2 if s.startswith("&&", i) else 1
            elif ch == "|":
                self._end_command()
                i += 2 if s[i : i + 2] in ("||", "|&") else 1
            elif ch == ";":
                self._end_command()
                i += 1
            elif ch == "(":
                j = i + 1
                while j < self.n and s[j] in " \t":
                    j += 1
                words = len(self.c_words) + (1 if self.w_started else 0)
                if j < self.n and s[j] == ")" and words == 1:
                    self.opaque = True  # ``name()``: a function definition
                    self._end_word()
                    i = j + 1
                else:
                    self._end_command()
                    i += 1
            elif ch == ")":
                self._end_command()
                i += 1
            else:
                self._append(ch, ch, quoted=False)
                i += 1
        self._end_command()
        return BashScan(tuple(self.commands), self.opaque)


def scan_bash(command: str) -> BashScan:
    """Tokenize a Bash-tool command string into simple commands (R§4.7 dialect).

    Never raises: an internal error yields one opaque command of the whitespace-split
    words, which the caller treats as unsupported.
    """
    try:
        return _BashScanner(command).run()
    except Exception:  # noqa: BLE001 - a hook must fail closed to "unsupported", not crash
        words = tuple(
            ShellWord(part, part, False, True, False, False) for part in command.split()
        )
        return BashScan((ShellCommand(words, (), True),), True)


def emit_decision(decision: str, reason: str) -> None:
    """Write the PreToolUse verdict JSON to stdout (the only stdout the hook produces)."""
    verdict = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }
    sys.stdout.write(json.dumps(verdict))
    sys.stdout.flush()


def append_log(hook: str, data: HookInput, decision: str) -> None:
    """Append one JSON line to ``{{PROJECT_NAME_UPPER}}_HOOK_LOG`` when set; never raises.

    A write failure is swallowed (fail-open): the audit log is evidence for the
    smoke receipt, and logging must never be able to block a tool call.
    """
    target = os.environ.get("{{PROJECT_NAME_UPPER}}_HOOK_LOG")
    if not target:
        return
    line = json.dumps(
        {
            "hook": hook,
            "session_id": data.session_id,
            "permission_mode": data.permission_mode,
            "command": data.command,
            "decision": decision,
        }
    )
    try:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass
