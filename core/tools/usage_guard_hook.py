"""Claude usage guard: the hold hook of each tool call (``PreToolUse``).

The settings start this script through ``LAUNCHER`` of ``usage_guard.py``::

    python.exe -I -S -c <LAUNCHER> --home <folder>

Without a pause the hook ends at once and does not read its input. While a pause
is on, it holds the tool call until the pause ends, the pause file goes away or
the file becomes bad. Some calls pass at once: a command of the guard itself, the
skill of the guard and each run that uses an API key. A headless run (``claude
-p``) cannot wait, so it gets a deny answer that stops the run.

The hook fails open. Each error ends it with exit code 0 and no output, so a
fault of the hook never stops a session. It uses only the standard library and
starts in a few milliseconds.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import time
from collections.abc import Callable, Mapping, Sequence

# These values must equal the values in usage_guard.py; a test compares them.
POLL_S = 5.0
PAUSE_MAX_S = 691_200
PAUSE_FILE_MAX = 4096
PAUSE_TRIES = 3
RETRY_S = 0.05
MARKS_MAX = 64
STDIN_MAX = 64 * 1024 * 1024

PAUSE_NAME = "pause.json"
PAUSE_SCHEMA = "usage-guard-pause/1"
PAUSE_FIELDS = frozenset({"schema", "origin", "started_at", "end_at", "windows"})
WINDOW_FIELDS = frozenset({"name", "reset"})
WINDOW_NAMES = frozenset({"five_hour", "seven_day", "account"})
ORIGINS = frozenset({"auto", "user"})
RESET_MAX = 10**12

GUARD_NAME = "usage_guard.py"
GUARD_VERBS = ("status", "pause", "resume", "read")
SKILL_NAME = "usage-guard"
SKILL_FILE = ".agent/skills/usage-guard/SKILL.md"
SHELL_TOOLS = frozenset({"Bash", "PowerShell"})

API_KEYS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
)
ENTRYPOINT_KEY = "CLAUDE_CODE_ENTRYPOINT"
HEADLESS_SIGN = "sdk-cli"

# A command of the guard: an optional ``rtk proxy``, the interpreter, an optional
# ``-I``, the guard script, one verb, plain words and one optional redirect. No
# character can start a second command, a subshell or an expansion of a word.
_WORD = r"[A-Za-z0-9.\-_=:/]+"
_TARGET = r"[A-Za-z0-9.\-_=:/$]+"
_COMMAND = re.compile(
    r"(?:rtk proxy )?(?P<python>\S+)(?: -I)? (?P<script>\S+)"
    rf" (?:{'|'.join(GUARD_VERBS)})(?: {_WORD})*"
    rf"(?: > {_TARGET} 2>&1| \*> {_TARGET})?"
)

DENY_REASON = (
    "Claude usage is paused by the usage guard. A headless run cannot wait, so it "
    "stops here. Run it again after the pause ends."
)


def _plain(path: str) -> str:
    """A path with forward slashes, case-folded on Windows."""
    text = path.replace("\\", "/")
    return text.casefold() if sys.platform == "win32" else text


def _pythons() -> frozenset[str]:
    """The interpreters that may run the guard: this one and its base interpreter.

    The settings start the hook with the interpreter of the install, so the hook
    needs no fixed default path. A virtual environment adds its base interpreter.
    """
    names: set[str] = set()
    for path in (sys.executable, getattr(sys, "_base_executable", "")):
        if isinstance(path, str) and path:
            names.add(_plain(path))
    return frozenset(names)


# ── The pause file ──────────────────────────────────────────────────────


def _number(value: object) -> float:
    """A finite JSON number that is not a boolean, else ``ValueError``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError("number") from exc
    if not math.isfinite(result):
        raise ValueError("number")
    return result


def _fields(doc: object, names: frozenset[str]) -> dict[str, object]:
    """The object when it has exactly these fields, else ``ValueError``."""
    if not isinstance(doc, dict) or set(doc) != names:
        raise ValueError("fields")
    return {str(key): value for key, value in doc.items()}


def _check_window(doc: object) -> None:
    """A window of the pause: a known name and an integer reset time."""
    data = _fields(doc, WINDOW_FIELDS)
    name, reset = data["name"], data["reset"]
    if not isinstance(name, str) or name not in WINDOW_NAMES:
        raise ValueError("name")
    if isinstance(reset, bool) or not isinstance(reset, int):
        raise ValueError("reset")
    if not 0 <= reset <= RESET_MAX:
        raise ValueError("reset")


def _end_of(raw: bytes) -> float:
    """The end time of a valid pause file, else ``ValueError``.

    The rules are the rules of ``usage_guard.py``; a test proves that both agree.
    """
    try:
        doc = json.loads(raw.decode("utf-8"))
    except RecursionError as exc:
        raise ValueError("nesting") from exc
    data = _fields(doc, PAUSE_FIELDS)
    if data["schema"] != PAUSE_SCHEMA:
        raise ValueError("schema")
    origin = data["origin"]
    if not isinstance(origin, str) or origin not in ORIGINS:
        raise ValueError("origin")
    _number(data["started_at"])
    end_at = _number(data["end_at"])
    windows = data["windows"]
    if not isinstance(windows, list) or len(windows) > MARKS_MAX:
        raise ValueError("windows")
    for item in windows:
        _check_window(item)
    return end_at


def _read_bounded(path: str) -> bytes:
    """The bytes of the pause file. A longer file raises ``ValueError``."""
    with open(path, "rb") as handle:
        raw = handle.read(PAUSE_FILE_MAX + 1)
    if len(raw) > PAUSE_FILE_MAX:
        raise ValueError("size")
    return raw


def load_pause(
    home: str, *, now: float, sleep: Callable[[float], None] = time.sleep
) -> tuple[str, float]:
    """The pause at ``now`` as ``(kind, end_at)``.

    The kind is ``none``, ``bad``, ``ended`` or ``on``, as in ``usage_guard.py``.
    A file that is not readable is tried again two times, because a replace on
    Windows can block a reader for a moment.
    """
    path = f"{home}/{PAUSE_NAME}"
    for left in range(PAUSE_TRIES - 1, -1, -1):
        try:
            end_at = _end_of(_read_bounded(path))
        except FileNotFoundError:
            return "none", 0.0
        except ValueError:
            return "bad", 0.0
        except OSError:
            if left == 0:
                return "bad", 0.0
            sleep(RETRY_S)
            continue
        if end_at <= now:
            return "ended", end_at
        if end_at > now + PAUSE_MAX_S:
            return "bad", 0.0
        return "on", end_at
    return "bad", 0.0


# ── The calls that pass ─────────────────────────────────────────────────


def _guard_command(command: str, home: str) -> bool:
    """True for one plain command of the guard of this home."""
    match = _COMMAND.fullmatch(command.replace("\\", "/"))
    if match is None:
        return False
    base = home.replace("\\", "/").rstrip("/")
    script = _plain(f"{base}/{GUARD_NAME}")
    return _plain(match["python"]) in _pythons() and _plain(match["script"]) == script


def _skill_file(path: str) -> bool:
    """True for the skill file of the guard in any project folder."""
    text = _plain(path)
    name = _plain(SKILL_FILE)
    return text == name or text.endswith(f"/{name}")


def passes(call: Mapping[str, object], home: str) -> bool:
    """True for a call that runs while a pause is on.

    These are a command of the guard (``status``, ``pause``, ``resume`` and
    ``read``), a read of the skill file of the guard and the skill call itself.
    """
    tool = call.get("tool_name")
    args = call.get("tool_input")
    if not isinstance(tool, str) or not isinstance(args, dict):
        return False
    if tool in SHELL_TOOLS:
        command = args.get("command")
        return isinstance(command, str) and _guard_command(command, home)
    if tool == "Read":
        path = args.get("file_path")
        return isinstance(path, str) and _skill_file(path)
    if tool == "Skill":
        return args.get("skill") == SKILL_NAME
    return False


def api_run(env: Mapping[str, str]) -> bool:
    """True when the session uses an API key or a cloud provider, not the plan."""
    return any(env.get(key) for key in API_KEYS)


def headless(env: Mapping[str, str]) -> bool:
    """True for a headless run (``claude -p``), which cannot wait."""
    return env.get(ENTRYPOINT_KEY) == HEADLESS_SIGN


# ── The hook ────────────────────────────────────────────────────────────


def _home_of(argv: Sequence[str]) -> str | None:
    """The value of ``--home``, else ``None``."""
    try:
        home = argv[list(argv).index("--home") + 1]
    except (ValueError, IndexError):
        return None
    return home or None


def _read_call() -> Mapping[str, object] | None:
    """The tool call on stdin, else ``None`` for input that is too long or bad."""
    raw = sys.stdin.buffer.read(STDIN_MAX + 1)
    if len(raw) > STDIN_MAX:
        return None
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):
        return None
    return doc if isinstance(doc, dict) else None


def _deny() -> None:
    """Write the answer that stops a headless run."""
    answer = {
        "continue": False,
        "stopReason": DENY_REASON,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": DENY_REASON,
        },
    }
    sys.stdout.write(json.dumps(answer) + "\n")
    sys.stdout.flush()


def _hold(
    argv: Sequence[str],
    poll: float,
    now: Callable[[], float],
    sleep: Callable[[float], None],
) -> int:
    """The body of ``main``. Each exit is code 0."""
    home = _home_of(argv)
    if home is None:
        return 0
    if load_pause(home, now=now(), sleep=sleep)[0] != "on":
        return 0
    call = _read_call()
    if call is None or passes(call, home) or api_run(os.environ):
        return 0
    if headless(os.environ):
        _deny()
        return 0
    while True:
        kind, end_at = load_pause(home, now=now(), sleep=sleep)
        if kind != "on":
            return 0
        sleep(min(poll, max(0.0, end_at - now())))


def main(
    argv: Sequence[str],
    *,
    poll: float = POLL_S,
    now: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Hold one tool call while a pause is on. Always returns 0 (fail open)."""
    try:
        return _hold(argv, poll, now, sleep)
    except Exception:
        # Fail open: a fault of the hook must never stop or hold a session.
        return 0


if __name__ == "__main__":
    main(sys.argv)
