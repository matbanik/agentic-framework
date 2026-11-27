"""Claude subscription usage guard: the reader, the pause, the email and the task.

The guard makes one minimal ``claude -p`` request when a reading is due and reads
the usage event from its output. It keeps the last good value, sends one email
near each limit and shows the state. At 99 % it starts an ``auto`` pause: the
hook ``usage_guard_hook.py`` then holds each tool call until the pause ends.
``LAUNCHER`` and ``hook_entry`` give the hook entry of the settings. A reading
below 95 % ends an ``auto`` pause, and each pause ends at its end time.

Usage::

    python -I usage_guard.py read [--if-due] [--no-mail] --home <folder>
    python -I usage_guard.py status [--json] --home <folder>
    python -I usage_guard.py pause [--hours H] --home <folder>
    python -I usage_guard.py resume --home <folder>
    python -I usage_guard.py install [--part task|hook] --python <path>
        [--settings <path>] --home <folder>
    python -I usage_guard.py uninstall [--part task|hook] [--python <path>]
        [--settings <path>] --home <folder>

Each command needs ``--home``: the guard has no default folder. ``install`` needs
``--python``. ``uninstall`` without ``--python`` uses the interpreter that the
manifest of the install names.

``install`` without ``--part`` installs the task and then the hook. ``uninstall``
without ``--part`` removes the hook and then the task. The hook part adds one
``PreToolUse`` group to the user settings (``--settings``, default
``~/.claude/settings.json``). It keeps each other byte of the file, makes a backup
in ``<home>/backup`` first and refuses a file that is not a JSON object.

Exit codes: 0 for success, ``busy`` and "not due"; 1 for a failed operation; 2 for
a bad command line, which writes nothing. ``pause`` and ``resume`` wait for the
lock of a running reading; ``busy`` from them is exit 1.

Rules that the code keeps:

- A failed reading changes no value and no pause file. Null is never zero.
- Only an ``auto`` pause ends by a reading. A ``user`` pause ends at its end time
  or by ``resume``. ``resume`` suppresses each window at the limit until its reset.
- A value is a lower bound until its reset time plus 60 s. After that the window
  has no value.
- No file, log, email or output holds an account id, an address, a value of the
  environment or text of a model. Only a hash of the account id is stored.

The thresholds are module constants on purpose: no environment variable and no
settings file changes them. The tests inject a clock and paths through ``main``.
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any
from xml.sax.saxutils import escape

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

# ── Constants ───────────────────────────────────────────────────────────

# The guard has no default folder and no default interpreter: the command line
# names them. The notifier home follows the lookup of the notifier.
NOTIFY_HOME_ENV = "AGENT_NOTIFY_HOME"
REGISTRY_HOME_ENV = "AGENT_MODEL_REGISTRY_HOME"

WINDOWS = ("five_hour", "seven_day")
ACCOUNT_WINDOW = "account"
OTHER = "other"
STATUSES = ("allowed", "allowed_warning", "rejected", OTHER)

PAUSE_AT = 0.99
WARN_AT = 0.95
NEAR_AT = 0.90
UTILIZATION_MAX = 2.0

POLL_S = 600
POLL_NEAR_S = 300
ACTIVITY_S = 900
UNREADABLE_S = 1800
RESET_MARGIN_S = 60
RESET_PAST_S = 3600
PAUSE_MAX_S = 691_200
SAME_WINDOW_S = 600
READ_LIMIT_S = 90
MAIL_LIMIT_S = 60
QUERY_LIMIT_S = 30
REPLACE_RETRY_S = 2.0
REPLACE_STEP_S = 0.05
PAUSE_TRIES = 3
PAUSE_FALLBACK_S = 18_000
PAUSE_HOURS_DEFAULT = 5.0
PAUSE_HOURS_MIN = 0.02
PAUSE_HOURS_MAX = 192.0
LOCK_STEP_S = 0.5
HOOK_TIMEOUT_S = PAUSE_MAX_S

STDOUT_MAX = 4 * 1024 * 1024
LINE_MAX = 1024 * 1024
STATE_MAX = 256 * 1024
PAUSE_FILE_MAX = 4096
MANIFEST_MAX = 64 * 1024
ACCOUNT_FILE_MAX = 64 * 1024 * 1024
NOTIFY_LOG_MAX = 1024 * 1024
GUARD_LOG_MAX = 256 * 1024
MARKS_MAX = 64
# The pauses of ``state.json`` about the end email: the ended pauses whose email
# is not sent yet, and the last pauses whose email went out. A pause document
# is at most ``PAUSE_FILE_MAX``, so the two lists stay far below ``STATE_MAX``.
END_NOTICE_MAX = 8
MAILS_PER_READING = 2

STATE_SCHEMA = "usage-guard-state/1"
PAUSE_SCHEMA = "usage-guard-pause/1"
MANIFEST_SCHEMA = "usage-guard-manifest/1"
STATUS_SCHEMA = "usage-guard-status/1"

STATE_NAME = "state.json"
PAUSE_NAME = "pause.json"
MANIFEST_NAME = "manifest.json"
LOCK_NAME = "guard.lock"
LOG_NAME = "guard.log"
RUN_NAME = "run"

GUARD_NAME = "usage_guard.py"
NOTIFIER_NAME = "agent_notify.py"
HOOK_NAME = "usage_guard_hook.py"
PART_FILES: dict[str, tuple[str, ...]] = {
    "task": (GUARD_NAME, NOTIFIER_NAME),
    "hook": (GUARD_NAME, NOTIFIER_NAME, HOOK_NAME),
}
INSTALL_PARTS = ("task", "hook")

SETTINGS_MAX = 4 * 1024 * 1024
SETTINGS_DEPTH = 200
HOOK_RECORD_NAME = "hook-settings.json"
HOOK_RECORD_SCHEMA = "usage-guard-hook/1"
BACKUP_DIR = "backup"
HOOK_EVENT = "PreToolUse"
HOOK_MATCHER = "*"
HOOK_STATES = ("installed", "absent", "drift", "disabled", "unknown")
# The containers that the install can make (``made``) and the empty containers
# that it can fill (``padded``). The record of the install names them, so that
# the uninstall gives back the exact bytes.
MADE_CONTAINERS = ("hooks", HOOK_EVENT)
PADDED_CONTAINERS = ("root", "hooks", HOOK_EVENT)
TASK_NAME = "ClaudeUsageGuard"
TASK_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
# The English text of the Windows error 2, that ``schtasks /Query`` shows for
# a name without a task.
TASK_NOT_FOUND_TEXT = "The system cannot find the file specified."

READ_ARGS = (
    "-p",
    "Reply with: ok",
    "--output-format",
    "stream-json",
    "--verbose",
    "--model",
    "haiku",  # <!-- model-slug-ok: fixed model of the usage probe -->
    "--max-turns",
    "1",
    "--tools",
    "",
    "--strict-mcp-config",
    "--setting-sources",
    "",
    "--system-prompt",
    "Reply with one word.",
    "--no-session-persistence",
)
DROPPED_ENV = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_CODE_USE_FOUNDRY",
    }
)
NO_HOLD_TEXT = "No hold is installed, so each session continues."
NO_PAUSE_TEXT = "No pause is on, so each session continues."
END_TEXT = (
    "Claude usage: the pause of the usage guard has ended. The held sessions continue."
)
END_NEW_PAUSE_TEXT = (
    "Claude usage: the pause of the usage guard has ended. A new pause has started."
)
MAIL_KINDS = ("warn", "high", "unreadable", "end")
ORIGINS = ("auto", "user")

# The hook entry of the settings starts this text with ``python -I -S -c``. Each
# fault of the hook script (a missing file, a syntax error, an exception, an exit
# code) ends the process with exit code 0, so a broken hook never stops a session.
LAUNCHER = """\
import sys
try:
    p = sys.argv[sys.argv.index('--home') + 1] + '/usage_guard_hook.py'
    exec(compile(open(p, 'rb').read(), p, 'exec'), {'__name__': '__main__', '__file__': p})
except BaseException:
    pass
import os
os._exit(0)
"""

_HEX64 = re.compile(r"[0-9a-f]{64}")
_CODE = re.compile(r"[a-z_]{1,40}")


# ── Errors ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Trip:
    """A limit that stopped an operation. It holds numbers and fixed names only."""

    limit_name: str
    configured_value: float | str
    observed_value: float | str | None
    window: str | None = None


class ReadingError(Exception):
    """A reading failed. ``code`` is a fixed name that is safe to store and show."""

    def __init__(self, code: str, trip: Trip | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.trip = trip


class ProcessFailure(Exception):
    """A child process did not give a result: ``timeout``, ``start_failed`` or ``stdout_limit``."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class InstallError(Exception):
    """An install or an uninstall is refused or failed, with a fixed code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# ── Values ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Window:
    """One account window: the used part (1.0 is full) and the reset time."""

    utilization: float
    resets_at: int

    def current(self, now: float) -> bool:
        """True until the reset time plus the margin. After that there is no value."""
        return now < self.resets_at + RESET_MARGIN_S


@dataclass(frozen=True)
class Reading:
    """One good reading. A window that a ``rejected`` status names counts as full."""

    at: float
    windows: dict[str, Window]
    status: str
    limit_type: str
    overage: bool

    def current_windows(self, now: float) -> dict[str, Window]:
        """The windows that still have a value at ``now``."""
        return {k: w for k, w in self.windows.items() if w.current(now)}


@dataclass(frozen=True)
class WindowKey:
    """A window occurrence: its name and its reset time."""

    name: str
    reset: int

    def same(self, name: str, reset: int) -> bool:
        """The SAME_WINDOW rule: the same name, and resets that are near."""
        return self.name == name and abs(self.reset - reset) <= SAME_WINDOW_S


@dataclass(frozen=True)
class MailMark:
    """A sent email that must not repeat: ``warn``, ``high``, ``unreadable``, ``end``."""

    kind: str
    key: WindowKey
    at: float


@dataclass(frozen=True)
class LastEmail:
    """The last attempt to send an email."""

    kind: str
    at: float
    outcome: str


@dataclass
class State:
    """The content of ``state.json``."""

    account: str | None = None
    last_good: Reading | None = None
    last_attempt: float | None = None
    last_error: str | None = None
    failing_since: float | None = None
    mails: list[MailMark] = field(default_factory=list)
    last_email: LastEmail | None = None
    suppressed: list[WindowKey] = field(default_factory=list)
    # The ended pauses whose end email is not sent yet, the oldest first.
    pause_ended: list[Pause] = field(default_factory=list)
    # The last pauses whose end email was sent or was not needed. A pause file
    # that still holds one of them gets no second email.
    end_sent: list[Pause] = field(default_factory=list)

    def drop_account(self) -> None:
        """Forget each value of the old account. The next reading is due at once.

        The pause file belongs to the home, not to the account, so the record
        of its end email stays.
        """
        self.last_good = None
        self.last_attempt = None
        self.last_error = None
        self.failing_since = None
        self.mails = []
        self.suppressed = []


@dataclass(frozen=True)
class Pause:
    """The content of ``pause.json``."""

    origin: str
    started_at: float
    end_at: float
    windows: tuple[WindowKey, ...]


@dataclass(frozen=True)
class PauseView:
    """The pause file at one time: ``none``, ``bad``, ``ended`` or ``on``."""

    kind: str
    pause: Pause | None = None


@dataclass(frozen=True)
class Decision:
    """What a good reading does to the pause: ``none``, ``start`` or ``end``.

    For ``start`` the pause is the new pause; for ``end`` it is the pause that
    ends, or None when the ended file is gone.
    """

    action: str
    pause: Pause | None = None


@dataclass(frozen=True)
class Mail:
    """One email that is due."""

    kind: str
    cls: str
    key: WindowKey
    text: str


@dataclass(frozen=True)
class Manifest:
    """The content of ``manifest.json``: what an install put into the home."""

    parts: tuple[str, ...]
    files: dict[str, str]
    installed_at: float
    python: str
    exe: str | None


@dataclass(frozen=True)
class Deps:
    """The outside world. The defaults are the real paths; the tests inject stubs.

    ``settings`` is the user settings file of the hook part. None means that no
    file is known: ``main`` gives ``~/.claude/settings.json`` when it makes the
    default ``Deps``.

    ``notify_home`` is the home of the notifier. None means the lookup of the
    notifier (``notify_home_of``).
    """

    claude: tuple[str, ...] | None = None
    account_file: Path = field(default_factory=lambda: Path.home() / ".claude.json")
    projects: Path = field(default_factory=lambda: Path.home() / ".claude" / "projects")
    notify_home: Path | None = None
    notifier: tuple[str, ...] | None = None
    schtasks: tuple[str, ...] = ("schtasks.exe",)
    source: Path = field(default_factory=lambda: Path(__file__).resolve().parent)
    mail_dry_run: bool = False
    mail_limit_s: float = MAIL_LIMIT_S
    which: Callable[[str], str | None] = shutil.which
    env: Mapping[str, str] | None = None
    settings: Path | None = None


def notify_home_of(deps: Deps) -> Path:
    """The home of the notifier for these ``Deps``.

    The order is the order of the notifier: the ``Deps`` value, then
    ``AGENT_NOTIFY_HOME``, then ``notify`` in ``AGENT_MODEL_REGISTRY_HOME``, then
    ``~/.agent/notify``. An empty variable counts as not set. ``Deps.env`` replaces
    the environment of the process when it is given.
    """
    if deps.notify_home is not None:
        return deps.notify_home
    environ = os.environ if deps.env is None else deps.env
    named = environ.get(NOTIFY_HOME_ENV, "")
    if named:
        return Path(named)
    registry = environ.get(REGISTRY_HOME_ENV, "")
    if registry:
        return Path(registry) / "notify"
    return Path.home() / ".agent" / "notify"


# ── Strict JSON helpers ─────────────────────────────────────────────────


def _loads(raw: bytes) -> Any:
    """Parse UTF-8 JSON. Each kind of bad input becomes ``ValueError``."""
    try:
        return json.loads(raw.decode("utf-8"))
    except RecursionError as exc:
        raise ValueError("nesting") from exc


def _fields(doc: object, names: Iterable[str]) -> dict[str, Any]:
    """The object when it has exactly these fields, else ``ValueError``."""
    if not isinstance(doc, dict) or set(doc) != set(names):
        raise ValueError("fields")
    return doc


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


def _integer(value: object) -> int:
    """A JSON integer in the range of an epoch time, else ``ValueError``."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("integer")
    if not 0 <= value <= 10**12:
        raise ValueError("integer")
    return value


def _choice(value: object, allowed: Iterable[str]) -> str:
    """A text of a fixed set, else ``ValueError``."""
    if not isinstance(value, str) or value not in allowed:
        raise ValueError("choice")
    return value


def _opt_number(value: object) -> float | None:
    """A number or null, else ``ValueError``."""
    return None if value is None else _number(value)


def _list(value: object, limit: int) -> list[Any]:
    """A list of bounded length, else ``ValueError``."""
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError("list")
    return value


def _read_bounded(path: Path, limit: int) -> bytes:
    """The bytes of a file. A longer file raises ``ValueError``."""
    with open(path, "rb") as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("size")
    return raw


def _dumps(doc: object) -> bytes:
    """The one JSON form of each file of the guard."""
    return (json.dumps(doc, indent=1, sort_keys=True) + "\n").encode("utf-8")


def write_atomic(
    path: Path,
    data: bytes,
    *,
    retry_s: float = REPLACE_RETRY_S,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Write a file through a temporary file in the same folder.

    The replace is tried again for a short time, because a reader that has the
    file open makes it fail on Windows. The last failure raises ``OSError``.
    """
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tries = max(1, round(retry_s / REPLACE_STEP_S))
    try:
        with open(temp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        for left in range(tries - 1, -1, -1):
            try:
                os.replace(temp, path)
                return
            except PermissionError:
                if left == 0:
                    raise
                sleep(REPLACE_STEP_S)
    finally:
        with contextlib.suppress(OSError):
            temp.unlink(missing_ok=True)


# ── State ───────────────────────────────────────────────────────────────


def _key_doc(key: WindowKey) -> dict[str, Any]:
    return {"name": key.name, "reset": key.reset}


def _key_from(doc: object, names: Iterable[str]) -> WindowKey:
    data = _fields(doc, ("name", "reset"))
    return WindowKey(_choice(data["name"], names), _integer(data["reset"]))


def _state_doc(state: State) -> dict[str, Any]:
    good = state.last_good
    mail = state.last_email
    return {
        "schema": STATE_SCHEMA,
        "account": state.account,
        "last_good": None
        if good is None
        else {
            "at": good.at,
            "windows": {
                name: {"utilization": w.utilization, "resets_at": w.resets_at}
                for name, w in good.windows.items()
            },
            "status": good.status,
            "limit_type": good.limit_type,
            "overage": good.overage,
        },
        "last_attempt": state.last_attempt,
        "last_error": state.last_error,
        "failing_since": state.failing_since,
        "mails": [
            {"kind": m.kind, "at": m.at, **_key_doc(m.key)}
            for m in state.mails[-MARKS_MAX:]
        ],
        "last_email": None
        if mail is None
        else {"kind": mail.kind, "at": mail.at, "outcome": mail.outcome},
        "suppressed": [_key_doc(key) for key in state.suppressed[-MARKS_MAX:]],
        "pause_ended": [_notice_doc(p) for p in state.pause_ended[-END_NOTICE_MAX:]],
        "end_sent": [_notice_doc(p) for p in state.end_sent[-END_NOTICE_MAX:]],
    }


def _good_from(doc: object) -> Reading | None:
    if doc is None:
        return None
    data = _fields(doc, ("at", "windows", "status", "limit_type", "overage"))
    if not isinstance(data["windows"], dict) or not data["windows"]:
        raise ValueError("windows")
    windows: dict[str, Window] = {}
    for name, item in data["windows"].items():
        entry = _fields(item, ("utilization", "resets_at"))
        value = _number(entry["utilization"])
        if not 0 <= value <= UTILIZATION_MAX:
            raise ValueError("utilization")
        windows[_choice(name, WINDOWS)] = Window(value, _integer(entry["resets_at"]))
    if not isinstance(data["overage"], bool):
        raise ValueError("overage")
    return Reading(
        at=_number(data["at"]),
        windows=windows,
        status=_choice(data["status"], STATUSES),
        limit_type=_choice(data["limit_type"], (*WINDOWS, OTHER)),
        overage=data["overage"],
    )


def _mark_from(doc: object) -> MailMark:
    data = _fields(doc, ("kind", "at", "name", "reset"))
    key = _key_from(
        {"name": data["name"], "reset": data["reset"]}, (*WINDOWS, ACCOUNT_WINDOW)
    )
    kind = _choice(data["kind"], MAIL_KINDS)
    return MailMark(kind, key, _number(data["at"]))


def _last_email_from(doc: object) -> LastEmail | None:
    if doc is None:
        return None
    data = _fields(doc, ("kind", "at", "outcome"))
    return LastEmail(
        _choice(data["kind"], MAIL_KINDS),
        _number(data["at"]),
        _choice(data["outcome"], ("sent", "failed")),
    )


def _state_from(doc: object) -> State:
    if isinstance(doc, dict):
        # A state of the reader part (MEU-977) has no record of end emails yet.
        doc = {"pause_ended": [], "end_sent": [], **doc}
    data = _fields(doc, _state_doc(State()))
    _choice(data["schema"], (STATE_SCHEMA,))
    account, error = data["account"], data["last_error"]
    if account is not None and not (
        isinstance(account, str) and _HEX64.fullmatch(account)
    ):
        raise ValueError("account")
    if error is not None and not (isinstance(error, str) and _CODE.fullmatch(error)):
        raise ValueError("last_error")
    return State(
        account=account,
        last_good=_good_from(data["last_good"]),
        last_attempt=_opt_number(data["last_attempt"]),
        last_error=error,
        failing_since=_opt_number(data["failing_since"]),
        mails=[_mark_from(item) for item in _list(data["mails"], MARKS_MAX)],
        last_email=_last_email_from(data["last_email"]),
        suppressed=[
            _key_from(item, (*WINDOWS, ACCOUNT_WINDOW))
            for item in _list(data["suppressed"], MARKS_MAX)
        ],
        pause_ended=[
            _notice_from(item) for item in _list(data["pause_ended"], END_NOTICE_MAX)
        ],
        end_sent=[
            _notice_from(item) for item in _list(data["end_sent"], END_NOTICE_MAX)
        ],
    )


def load_state(home: Path) -> State:
    """The stored state. An absent, unreadable or refused file is an empty state."""
    try:
        return _state_from(_loads(_read_bounded(home / STATE_NAME, STATE_MAX)))
    except (OSError, ValueError):
        return State()


def save_state(
    home: Path, state: State, *, sleep: Callable[[float], None] = time.sleep
) -> None:
    """Store the state atomically. Raises ``OSError`` when the write fails."""
    write_atomic(home / STATE_NAME, _dumps(_state_doc(state)), sleep=sleep)


# ── Pause file ──────────────────────────────────────────────────────────


_NOTICE_FIELDS = ("origin", "started_at", "end_at", "windows")


def _notice_doc(pause: Pause) -> dict[str, Any]:
    """The fields of a pause, without the schema: the same as in ``pause.json``."""
    return {
        "origin": pause.origin,
        "started_at": pause.started_at,
        "end_at": pause.end_at,
        "windows": [_key_doc(key) for key in pause.windows[:MARKS_MAX]],
    }


def _notice_from(doc: object) -> Pause:
    """The pause of a document of ``_notice_doc``. Raises ``ValueError``."""
    data = _fields(doc, _NOTICE_FIELDS)
    return Pause(
        origin=_choice(data["origin"], ORIGINS),
        started_at=_number(data["started_at"]),
        end_at=_number(data["end_at"]),
        windows=tuple(
            _key_from(item, (*WINDOWS, ACCOUNT_WINDOW))
            for item in _list(data["windows"], MARKS_MAX)
        ),
    )


def _pause_from(doc: object) -> Pause:
    data = _fields(doc, ("schema", *_NOTICE_FIELDS))
    _choice(data["schema"], (PAUSE_SCHEMA,))
    return _notice_from({name: data[name] for name in _NOTICE_FIELDS})


def load_pause(
    home: Path, *, now: float, sleep: Callable[[float], None] = time.sleep
) -> PauseView:
    """The pause at ``now``. A pause that ends too far in the future is ``bad``."""
    path = home / PAUSE_NAME
    for left in range(PAUSE_TRIES - 1, -1, -1):
        try:
            pause = _pause_from(_loads(_read_bounded(path, PAUSE_FILE_MAX)))
        except FileNotFoundError:
            return PauseView("none")
        except ValueError:
            return PauseView("bad")
        except OSError:
            if left == 0:
                return PauseView("bad")
            sleep(REPLACE_STEP_S)
            continue
        if pause.end_at <= now:
            return PauseView("ended", pause)
        if pause.end_at > now + PAUSE_MAX_S:
            return PauseView("bad")
        return PauseView("on", pause)
    return PauseView("bad")


def _pause_doc(pause: Pause) -> dict[str, Any]:
    return {"schema": PAUSE_SCHEMA, **_notice_doc(pause)}


def write_pause(
    home: Path,
    pause: Pause,
    *,
    retry_s: float = REPLACE_RETRY_S,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Write ``pause.json`` atomically, so that a hook reads the old or the new file.

    A bad pause raises ``ValueError`` and writes nothing. A failed write raises
    ``OSError``.
    """
    _choice(pause.origin, ORIGINS)
    _number(pause.started_at)
    _number(pause.end_at)
    data = _dumps(_pause_doc(pause))
    if len(data) > PAUSE_FILE_MAX:
        raise ValueError("size")
    write_atomic(home / PAUSE_NAME, data, retry_s=retry_s, sleep=sleep)


def clear_pause(
    home: Path,
    *,
    retry_s: float = REPLACE_RETRY_S,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Remove ``pause.json``. An absent file is no error.

    The remove is tried again for a short time, because a hook that has the file
    open makes it fail on Windows. An empty folder of that name is removed too.
    The last failure raises ``OSError``.
    """
    path = home / PAUSE_NAME
    tries = max(1, round(retry_s / REPLACE_STEP_S))
    for left in range(tries - 1, -1, -1):
        try:
            path.unlink()
            return
        except FileNotFoundError:
            return
        except OSError:
            if path.is_dir() and not path.is_symlink():
                path.rmdir()
                return
            if left == 0:
                raise
            sleep(REPLACE_STEP_S)


# ── Account and activity ────────────────────────────────────────────────


def account_hash(path: Path) -> str | None:
    """The hash of the account id, or None when the id is not readable."""
    try:
        doc = _loads(_read_bounded(path, ACCOUNT_FILE_MAX))
    except (OSError, ValueError):
        return None
    account = doc.get("oauthAccount") if isinstance(doc, dict) else None
    value = account.get("accountUuid") if isinstance(account, dict) else None
    if not isinstance(value, str) or not 8 <= len(value) <= 128:
        return None
    try:
        return hashlib.sha256(f"usage-guard/1:{value}".encode()).hexdigest()
    except UnicodeEncodeError:
        return None


def session_active(projects: Path, *, now: float) -> bool:
    """True when a transcript below ``projects`` was written in the last 900 s."""
    folders = [projects]
    while folders:
        try:
            with os.scandir(folders.pop()) as entries:
                for entry in entries:
                    if _is_recent(entry, now):
                        return True
                    if entry.is_dir(follow_symlinks=False):
                        folders.append(Path(entry.path))
        except OSError:
            continue
    return False


def _is_recent(entry: os.DirEntry[str], now: float) -> bool:
    """True for a transcript file with a recent write time."""
    if not entry.name.endswith(".jsonl"):
        return False
    try:
        # A fresh stat: the folder entry of an open file is stale on Windows.
        info = os.stat(entry.path, follow_symlinks=False)
        return entry.is_file(follow_symlinks=False) and (
            now - info.st_mtime <= ACTIVITY_S
        )
    except OSError:
        return False


def due(state: State, *, now: float, active: bool, paused: bool) -> bool:
    """True when a reading is due. Without a working session and a pause: never."""
    if not (active or paused):
        return False
    last = state.last_attempt
    if last is None or last > now:
        return True
    interval = POLL_S
    if state.last_good is not None:
        for window in state.last_good.windows.values():
            if last < window.resets_at + RESET_MARGIN_S <= now:
                return True
        current = state.last_good.current_windows(now).values()
        if not paused and any(w.utilization >= NEAR_AT for w in current):
            interval = POLL_NEAR_S
    return now - last >= interval


# ── The usage event ─────────────────────────────────────────────────────


def _event_of(line: bytes) -> dict[str, Any] | None:
    """The usage event of a line, or None for each other line."""
    try:
        doc = _loads(line)
    except ValueError:
        return None
    if isinstance(doc, dict) and doc.get("type") == "rate_limit_event":
        return doc
    return None


def _observed(value: object) -> float | str | None:
    """A value for the log: a number, or the name of a type. Never a text."""
    if value is None:
        return None
    try:
        return _number(value)
    except ValueError:
        return f"type_{type(value).__name__}"


def _window_from(name: str, item: object, now: float) -> Window:
    """One valid window, or a failed reading."""
    if not isinstance(item, dict):
        raise ReadingError(
            "bad_window", Trip("valid_bound", "object", _observed(item), name)
        )
    raw, reset = item.get("utilization"), item.get("resetsAt")
    try:
        value = _number(raw)
        if not 0 <= value <= UTILIZATION_MAX:
            raise ValueError("range")
    except ValueError as exc:
        trip = Trip("valid_bound", UTILIZATION_MAX, _observed(raw), name)
        raise ReadingError("bad_utilization", trip) from exc
    if (
        isinstance(reset, bool)
        or not isinstance(reset, int)
        or not now - RESET_PAST_S <= reset <= now + PAUSE_MAX_S
    ):
        trip = Trip("valid_bound", now + PAUSE_MAX_S, _observed(reset), name)
        raise ReadingError("bad_reset", trip)
    return Window(value, reset)


def _reading_from(info: object, now: float) -> Reading:
    """The reading of an event. A bad value of an account window fails all of it."""
    if not isinstance(info, dict) or not isinstance(info.get("status"), str):
        raise ReadingError("bad_event")
    if "unifiedWindows" not in info:
        raise ReadingError("no_window")
    items = info["unifiedWindows"]
    if not isinstance(items, dict):
        raise ReadingError("bad_event")
    windows = {n: _window_from(n, items[n], now) for n in WINDOWS if n in items}
    if not windows:
        raise ReadingError("no_window")
    status = info["status"] if info["status"] in STATUSES else OTHER
    named = info.get("rateLimitType")
    limit_type = named if isinstance(named, str) and named in WINDOWS else OTHER
    if status == "rejected" and limit_type in windows:
        window = windows[limit_type]
        windows[limit_type] = Window(max(1.0, window.utilization), window.resets_at)
    return Reading(
        at=now,
        windows=windows,
        status=status,
        limit_type=limit_type,
        overage=info.get("isUsingOverage") is True,
    )


def parse_stream(data: bytes, *, now: float) -> Reading:
    """The reading of the last usage event in the output, else ``ReadingError``."""
    if len(data) > STDOUT_MAX:
        raise ReadingError("stdout_limit", Trip("stdout_bytes", STDOUT_MAX, len(data)))
    event: dict[str, Any] | None = None
    for line in data.split(b"\n"):
        if len(line) > LINE_MAX:
            raise ReadingError("line_limit", Trip("line_bytes", LINE_MAX, len(line)))
        event = _event_of(line) or event
    if event is None:
        raise ReadingError("no_event")
    return _reading_from(event.get("rate_limit_info"), now)


def is_high(reading: Reading) -> bool:
    """True at the pause threshold, for a refused request and for overage."""
    return (
        reading.status == "rejected"
        or reading.overage
        or any(w.utilization >= PAUSE_AT for w in reading.windows.values())
    )


def is_low(reading: Reading) -> bool:
    """True when each window is below the warn threshold and nothing is refused."""
    return (
        reading.status != "rejected"
        and not reading.overage
        and all(w.utilization < WARN_AT for w in reading.windows.values())
    )


# ── The pause decision ──────────────────────────────────────────────────


def _epoch_key(name: str, value: float) -> WindowKey:
    """A window key whose reset is a time in the range of the state file."""
    return WindowKey(name, min(max(int(value), 0), 10**12))


def high_windows(reading: Reading, now: float) -> list[tuple[WindowKey, float]]:
    """The windows at the limit, each with the end of its pause.

    These are the current windows at 99 % or more. A refused request or overage
    without such a window holds the account until the latest current reset, or
    for 5 hours when no window is current. Each end is the reset plus 60 s.
    """
    current = reading.current_windows(now)
    found = [
        (WindowKey(name, w.resets_at), float(w.resets_at + RESET_MARGIN_S))
        for name, w in current.items()
        if w.utilization >= PAUSE_AT
    ]
    if found or not (reading.status == "rejected" or reading.overage):
        return found
    if current:
        latest = max(w.resets_at for w in current.values())
        return [(WindowKey(ACCOUNT_WINDOW, latest), float(latest + RESET_MARGIN_S))]
    end = now + PAUSE_FALLBACK_S
    return [(_epoch_key(ACCOUNT_WINDOW, end), end)]


def _is_suppressed(state: State, key: WindowKey) -> bool:
    """True when ``resume`` suppressed this window occurrence."""
    return any(item.same(key.name, key.reset) for item in state.suppressed)


def auto_pause(state: State, reading: Reading, *, now: float) -> Pause | None:
    """The ``auto`` pause of a reading, or None when no window that is not
    suppressed is at the limit. The end is at most 8 days after ``now``."""
    found = [
        (k, end)
        for k, end in high_windows(reading, now)
        if not _is_suppressed(state, k)
    ]
    if not found:
        return None
    end_at = min(max(end for _, end in found), now + PAUSE_MAX_S)
    if end_at <= now:
        return None
    return Pause("auto", now, end_at, tuple(k for k, _ in found))


def decide(state: State, reading: Reading, view: PauseView, *, now: float) -> Decision:
    """What one good reading does to the pause.

    A pause that is on stays, except an ``auto`` pause and a low reading: that
    pause ends. Without a pause that is on, a high window that is not suppressed
    starts an ``auto`` pause; a bad file is replaced. Else an ended pause ends.
    """
    if view.kind == "on":
        pause = view.pause
        if pause is not None and pause.origin == "auto" and is_low(reading):
            return Decision("end", pause)
        return Decision("none")
    new = auto_pause(state, reading, now=now)
    if new is not None:
        return Decision("start", new)
    if view.kind == "ended":
        return Decision("end", view.pause)
    return Decision("none")


def end_keys(pause: Pause | None) -> list[WindowKey]:
    """The window keys of the email about the end of a pause.

    A pause without windows (a ``user`` pause) has one account key at its end.
    """
    if pause is None:
        return []
    if pause.windows:
        return list(pause.windows)
    return [_epoch_key(ACCOUNT_WINDOW, pause.end_at)]


def hook_entry(home: str | Path, python: str | Path) -> dict[str, Any]:
    """The hook entry of the settings for one home: ``python -I -S -c LAUNCHER``.

    The timeout is the longest pause, so that the program never ends a held call.
    """
    folder = home.as_posix() if isinstance(home, Path) else home
    program = python.as_posix() if isinstance(python, Path) else python
    return {
        "type": "command",
        "command": program,
        "args": ["-I", "-S", "-c", LAUNCHER, "--home", folder],
        "timeout": HOOK_TIMEOUT_S,
    }


# ── Child processes ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProcessResult:
    """The exit code and the output of a child process.

    ``stderr`` is empty unless the caller asked for the error output.
    """

    code: int
    stdout: bytes
    stderr: bytes = b""


if sys.platform == "win32":
    from ctypes import wintypes

    _CREATE_SUSPENDED = 0x00000004
    _JOB_LIMIT_CLASS = 9
    _JOB_KILL_ON_CLOSE = 0x00002000

    class _BasicLimit(ctypes.Structure):
        _fields_ = (
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        )

    class _ExtendedLimit(ctypes.Structure):
        _fields_ = (
            ("BasicLimitInformation", _BasicLimit),
            ("IoInfo", ctypes.c_uint64 * 6),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        )

    class _Tree:
        """A Windows job that ends each process of the tree when it closes.

        The child starts suspended, joins the job and then runs, so that it
        cannot start a process outside of the job.
        """

        flags = subprocess.CREATE_NO_WINDOW | _CREATE_SUSPENDED
        new_session = False

        def __init__(self) -> None:
            self._api = ctypes.WinDLL("kernel32", use_last_error=True)
            self._api.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
            self._api.CreateJobObjectW.restype = wintypes.HANDLE
            self._api.SetInformationJobObject.argtypes = (
                wintypes.HANDLE,
                ctypes.c_int,
                wintypes.LPVOID,
                wintypes.DWORD,
            )
            self._api.AssignProcessToJobObject.argtypes = (
                wintypes.HANDLE,
                wintypes.HANDLE,
            )
            self._api.OpenProcess.argtypes = (
                wintypes.DWORD,
                wintypes.BOOL,
                wintypes.DWORD,
            )
            self._api.OpenProcess.restype = wintypes.HANDLE
            self._api.CloseHandle.argtypes = (wintypes.HANDLE,)
            self._resume = ctypes.WinDLL("ntdll").NtResumeProcess
            self._resume.argtypes = (wintypes.HANDLE,)
            self._job: int | None = self._api.CreateJobObjectW(None, None)
            if not self._job:
                raise OSError("job")
            info = _ExtendedLimit()
            info.BasicLimitInformation.LimitFlags = _JOB_KILL_ON_CLOSE
            if not self._api.SetInformationJobObject(
                self._job, _JOB_LIMIT_CLASS, ctypes.byref(info), ctypes.sizeof(info)
            ):
                self.close()
                raise OSError("job")

        def adopt(self, pid: int) -> None:
            """Put the suspended child into the job and let it run."""
            access = 0x0001 | 0x0100 | 0x0800  # terminate, set quota, suspend/resume
            handle = self._api.OpenProcess(access, False, pid)
            if not handle:
                raise OSError("process")
            try:
                if not self._api.AssignProcessToJobObject(self._job, handle):
                    raise OSError("assign")
                if self._resume(handle) != 0:
                    raise OSError("resume")
            finally:
                self._api.CloseHandle(handle)

        def close(self) -> None:
            """End the tree."""
            if self._job:
                self._api.CloseHandle(self._job)
                self._job = None

else:

    class _Tree:
        """A POSIX session that ends as one process group."""

        flags = 0
        new_session = True

        def __init__(self) -> None:
            self._group: int | None = None

        def adopt(self, pid: int) -> None:
            """Remember the group of the child."""
            self._group = pid

        def close(self) -> None:
            """End the tree."""
            if self._group is not None:
                with contextlib.suppress(OSError):
                    os.killpg(self._group, signal.SIGKILL)
                self._group = None


class _Output:
    """Reads the output of a child in a thread, up to the size limit."""

    def __init__(self, stream: IO[bytes]) -> None:
        self.data = bytearray()
        self.overflow = False
        self._stream = stream
        self._done = threading.Event()
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _read(self) -> None:
        try:
            while chunk := self._stream.read(65536):
                self.data += chunk
                if len(self.data) > STDOUT_MAX:
                    self.overflow = True
                    break
        except (OSError, ValueError):
            # The stream closed with the process tree. The caller decides.
            return
        finally:
            self._done.set()

    def wait(self, limit_s: float) -> bool:
        """True when the stream ended or the limit of the size was reached."""
        return self._done.wait(limit_s)

    def close(self) -> None:
        """End the thread and close the stream."""
        self._thread.join(10)
        with contextlib.suppress(OSError):
            self._stream.close()


def run_process(
    cmd: Sequence[str],
    *,
    cwd: Path | None,
    limit_s: float,
    env: Mapping[str, str] | None = None,
    capture_stderr: bool = False,
) -> ProcessResult:
    """Run a program without a shell, an input and a window, with a time limit.

    The program and each process that it started end with this call. The error
    output is kept only with ``capture_stderr``; it has the size limit of the
    output.

    Raises:
        ProcessFailure: ``start_failed``, ``timeout`` or ``stdout_limit``.
    """
    end = time.monotonic() + limit_s
    try:
        tree = _Tree()
    except OSError as exc:
        raise ProcessFailure("start_failed") from exc
    try:
        proc = subprocess.Popen(
            list(cmd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE if capture_stderr else subprocess.DEVNULL,
            bufsize=0,
            cwd=cwd,
            env=None if env is None else dict(env),
            creationflags=tree.flags,
            start_new_session=tree.new_session,
        )
    except (OSError, ValueError) as exc:
        tree.close()
        raise ProcessFailure("start_failed") from exc
    if proc.stdout is None or (capture_stderr and proc.stderr is None):
        proc.kill()
        tree.close()
        raise ProcessFailure("start_failed")
    output = _Output(proc.stdout)
    errors = None if proc.stderr is None else _Output(proc.stderr)
    try:
        tree.adopt(proc.pid)
        if not output.wait(limit_s):
            raise ProcessFailure("timeout")
        if errors is not None and not errors.wait(max(0.0, end - time.monotonic())):
            raise ProcessFailure("timeout")
        if output.overflow or (errors is not None and errors.overflow):
            raise ProcessFailure("stdout_limit")
        code = proc.wait(max(0.0, end - time.monotonic()))
    except subprocess.TimeoutExpired as exc:
        raise ProcessFailure("timeout") from exc
    except OSError as exc:
        raise ProcessFailure("start_failed") from exc
    finally:
        tree.close()
        with contextlib.suppress(OSError):
            proc.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(10)
        output.close()
        if errors is not None:
            errors.close()
    return ProcessResult(
        code, bytes(output.data), b"" if errors is None else bytes(errors.data)
    )


# ── The reading ─────────────────────────────────────────────────────────


def resolve_exe(*, which: Callable[[str], str | None] = shutil.which) -> str | None:
    """The Claude program behind the npm shim, or None.

    The shim is a command file. The guard starts the program itself, so that no
    shell takes part and the arguments stay as they are.
    """
    shim = which("claude")
    if not shim:
        return None
    program = (
        Path(shim).parent
        / "node_modules"
        / "@anthropic-ai"
        / "claude-code"
        / "bin"
        / "claude.exe"
    )
    return str(program) if program.is_file() else None


def read_env(env: Mapping[str, str]) -> dict[str, str]:
    """The environment of the reading: without another account and provider."""
    return {k: v for k, v in env.items() if k.upper() not in DROPPED_ENV}


def _claude_prefix(home: Path, deps: Deps) -> tuple[str, ...]:
    """The program of the reading: injected, resolved now, or recorded at install."""
    if deps.claude is not None:
        return deps.claude
    exe = resolve_exe(which=deps.which)
    if exe is None:
        try:
            manifest = load_manifest(home)
        except ValueError:
            manifest = None
        recorded = None if manifest is None else manifest.exe
        exe = recorded if recorded and Path(recorded).is_file() else None
    if exe is None:
        raise ReadingError("no_claude")
    return (exe,)


def run_reading(
    home: Path, deps: Deps, *, now: Callable[[], float], limit_s: float = READ_LIMIT_S
) -> Reading:
    """Make one request and return its reading, else raise ``ReadingError``.

    The exit code of the program does not count: a refused request has an event.
    """
    prefix = _claude_prefix(home, deps)
    folder = home / RUN_NAME
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ReadingError("start_failed") from exc
    environ = os.environ if deps.env is None else deps.env
    started = time.monotonic()
    try:
        result = run_process(
            [*prefix, *READ_ARGS], cwd=folder, limit_s=limit_s, env=read_env(environ)
        )
    except ProcessFailure as exc:
        trip = None
        if exc.code == "timeout":
            elapsed = round(time.monotonic() - started, 1)
            trip = Trip("read_limit_s", limit_s, elapsed)
        elif exc.code == "stdout_limit":
            trip = Trip("stdout_bytes", STDOUT_MAX, None)
        raise ReadingError(exc.code, trip) from exc
    return parse_stream(result.stdout, now=now())


# ── Email ───────────────────────────────────────────────────────────────


def _local(epoch: float) -> str:
    """A local time for a person, or a fixed text for a time out of range."""
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(epoch))
    except (OSError, OverflowError, ValueError):
        return "unknown"


def _percent(utilization: float) -> str:
    """A percent without a fraction, rounded down."""
    return str(math.floor(utilization * 100 + 1e-9))


def _marked(state: State, kinds: Iterable[str], key: WindowKey) -> bool:
    """True when an email of one of the kinds was sent for this window occurrence."""
    return any(m.kind in kinds and m.key.same(key.name, key.reset) for m in state.mails)


def hold_text(home: Path, view: PauseView) -> str:
    """The last sentence of the 99 % email: what happens to the sessions.

    Without the hook script in the home no hold is installed. With it, the
    sessions are held while a pause is on.
    """
    try:
        installed = (home / HOOK_NAME).is_file()
    except OSError:
        installed = False
    if not installed:
        return NO_HOLD_TEXT
    if view.kind == "on" and view.pause is not None:
        return (
            f"Sessions are held until the pause ends at {_local(view.pause.end_at)} "
            "(local time). To continue at once, run resume."
        )
    return NO_PAUSE_TEXT


def _high_mail(key: WindowKey, utilization: float, hold: str) -> Mail:
    if key.name == ACCOUNT_WINDOW:
        what = (
            "Claude usage: the account is at its limit (a refused request or overage)."
        )
    else:
        share = _percent(utilization)
        what = f"Claude usage: the {key.name} window is at {share} % of its limit."
    text = f"{what} Reset: {_local(key.reset)} (local time). {hold}"
    return Mail("high", "blocked", key, text)


def _warn_mail(key: WindowKey, utilization: float) -> Mail:
    text = (
        f"Claude usage: the {key.name} window is at {_percent(utilization)} % of its "
        f"limit. Reset: {_local(key.reset)} (local time)."
    )
    return Mail("warn", "blocked", key, text)


def _usage_mails(state: State, now: float, hold: str) -> tuple[list[Mail], list[Mail]]:
    """The emails of the last value: those at the limit and those near it."""
    high: list[Mail] = []
    warn: list[Mail] = []
    good = state.last_good
    current = {} if good is None else good.current_windows(now)
    if good is None or not current:
        return high, warn
    full = False
    for name, window in current.items():
        key = WindowKey(name, window.resets_at)
        if window.utilization >= PAUSE_AT:
            full = True
            if not _marked(state, ("high",), key):
                high.append(_high_mail(key, window.utilization, hold))
        elif window.utilization >= WARN_AT:
            if not _marked(state, ("warn", "high"), key):
                warn.append(_warn_mail(key, window.utilization))
    if not full and (good.status == "rejected" or good.overage):
        latest = max(w.resets_at for w in current.values())
        key = WindowKey(ACCOUNT_WINDOW, latest)
        if not _marked(state, ("high",), key):
            high.append(_high_mail(key, 1.0, hold))
    return high, warn


def _end_mails(state: State, *, paused: bool) -> list[Mail]:
    """The one email about the end of the pauses that wait for it.

    One email covers each waiting pause. ``paused`` is True when a new pause is
    on: then the email also says that.
    """
    if not state.pause_ended:
        return []
    keys = end_keys(state.pause_ended[0])
    text = END_NEW_PAUSE_TEXT if paused else END_TEXT
    return [Mail("end", "done", keys[0], text)]


def _unreadable_mails(state: State, now: float, active: bool) -> list[Mail]:
    """The email about readings that fail for a long time while a session works."""
    since = state.failing_since
    if since is None or not active or now - since < UNREADABLE_S:
        return []
    if any(m.kind == "unreadable" for m in state.mails):
        return []
    text = (
        f"Claude usage is not readable since {_local(since)} (local time). "
        f"Error code: {state.last_error or 'unknown'}."
    )
    return [Mail("unreadable", "error", WindowKey(ACCOUNT_WINDOW, 0), text)]


def mail_due(
    state: State,
    *,
    now: float,
    active: bool,
    hold: str = NO_HOLD_TEXT,
    paused: bool = False,
) -> list[Mail]:
    """The emails that are due, the important ones first, bounded per reading.

    ``hold`` is the last sentence of a 99 % email (see ``hold_text``). The end
    email of an older pause goes first, so that it comes before the 99 % email
    of a new pause; ``paused`` is True when a pause is on.
    """
    high, warn = _usage_mails(state, now, hold)
    due_now = [
        *_end_mails(state, paused=paused),
        *high,
        *_unreadable_mails(state, now, active),
        *warn,
    ]
    return due_now[:MAILS_PER_READING]


def _console_python() -> str:
    """The interpreter for a child: ``python.exe``, also when ``pythonw.exe`` runs."""
    path = Path(sys.executable)
    if path.name.lower() == "pythonw.exe":
        console = path.with_name("python.exe")
        if console.is_file():
            return str(console)
    return str(path)


def _log_size(path: Path) -> int:
    """The size of the notifier log. An absent log has the size 0."""
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _sent_since(path: Path, offset: int, cls: str) -> bool:
    """True when the new log lines say that each manual email of the class was sent."""
    if _log_size(path) < offset:
        offset = 0  # the notifier started a new log
    try:
        with open(path, "rb") as handle:
            handle.seek(offset)
            raw = handle.read(NOTIFY_LOG_MAX)
    except OSError:
        return False
    outcomes: list[object] = []
    for line in raw.split(b"\n"):
        try:
            doc = _loads(line)
        except ValueError:
            continue
        if not isinstance(doc, dict):
            continue
        if doc.get("harness") != "manual" or doc.get("class") != cls:
            continue
        if doc.get("outcome") != "state_lock_timeout":
            outcomes.append(doc.get("outcome"))
    return bool(outcomes) and all(item == "sent" for item in outcomes)


def send_mail(mail: Mail, *, home: Path, deps: Deps) -> bool:
    """Send one email with the notifier. True only when its log proves the send.

    The notifier exits 0 in each case, so its exit code proves nothing.
    """
    prefix = deps.notifier
    if prefix is None:
        script = home / NOTIFIER_NAME
        if not script.is_file():
            return False
        prefix = (_console_python(), "-I", str(script))
    notify = notify_home_of(deps)
    log = notify / "state" / "notify.log.jsonl"
    offset = _log_size(log)
    cmd = [*prefix, "send", "--class", mail.cls, "--text", mail.text]
    cmd += ["--home", str(notify)]
    if deps.mail_dry_run:
        cmd.append("--dry-run")
    try:
        run_process(cmd, cwd=home, limit_s=deps.mail_limit_s)
    except ProcessFailure as exc:
        if exc.code == "start_failed":
            return False
    return _sent_since(log, offset, mail.cls)


# ── Lock and log ────────────────────────────────────────────────────────


@contextlib.contextmanager
def lock(home: Path) -> Iterator[bool]:
    """Hold the one lock of the home. Yields False when another process holds it.

    The system releases the lock when the process ends.
    """
    with open(home / LOCK_NAME, "a+b") as handle:
        handle.seek(0)
        try:
            if sys.platform == "win32":
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            if sys.platform == "win32":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def log_trip(home: Path, trip: Trip, *, now: float) -> None:
    """Add a line about a limit to the guard log. A failed write stops nothing."""
    path = home / LOG_NAME
    line = {
        "at": now,
        "event": "limit_trip",
        "limit_name": trip.limit_name,
        "configured_value": trip.configured_value,
        "observed_value": trip.observed_value,
        "window": trip.window,
    }
    with contextlib.suppress(OSError):
        if _log_size(path) > GUARD_LOG_MAX:
            os.replace(path, path.with_name(LOG_NAME + ".1"))
        with open(path, "ab") as handle:
            handle.write((json.dumps(line, sort_keys=True) + "\n").encode("utf-8"))


# ── read ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Run:
    """One call of the guard: its home, its stubs or real paths and its clock."""

    home: Path
    deps: Deps
    now: Callable[[], float]
    sleep: Callable[[float], None]
    limit_s: float


def _refresh_account(state: State, deps: Deps) -> bool:
    """Take the account into the state. True when it changed.

    An id that is not readable changes nothing.
    """
    digest = account_hash(deps.account_file)
    if digest is None or digest == state.account:
        return False
    changed = state.account is not None
    if changed:
        state.drop_account()
    state.account = digest
    return changed


def _prune_marks(state: State, now: float) -> None:
    """Forget the emails about windows that ended. Keep the mark about failures."""
    state.mails = [
        m
        for m in state.mails
        if m.kind == "unreadable" or m.key.reset + RESET_PAST_S >= now
    ]


def _prune_suppressed(state: State, now: float) -> None:
    """Forget each suppressed window after its reset: a new window can pause."""
    state.suppressed = [k for k in state.suppressed if k.reset + RESET_MARGIN_S > now]


def _take_reading(run: Run, state: State) -> None:
    """Make the request and put its result into the state."""
    try:
        reading = run_reading(run.home, run.deps, now=run.now, limit_s=run.limit_s)
    except ReadingError as exc:
        at = run.now()
        state.last_error = exc.code
        if state.failing_since is None:
            state.failing_since = at
        if exc.trip is not None:
            log_trip(run.home, exc.trip, now=at)
        return
    state.last_good = reading
    state.last_error = None
    state.failing_since = None
    state.mails = [m for m in state.mails if m.kind != "unreadable"]


def _deliver(run: Run, state: State, mails: Iterable[Mail], at: float) -> None:
    """Send each email and store the result of each one at once."""
    for mail in mails:
        sent = send_mail(mail, home=run.home, deps=run.deps)
        state.last_email = LastEmail(mail.kind, at, "sent" if sent else "failed")
        if sent and mail.kind == "end":
            # One email covers each window of each pause that waited for it.
            for pause in state.pause_ended:
                for key in end_keys(pause):
                    if not _marked(state, ("end",), key):
                        state.mails.append(MailMark("end", key, at))
            state.end_sent = [*state.end_sent, *state.pause_ended][-END_NOTICE_MAX:]
            state.pause_ended = []
        elif sent:
            state.mails.append(MailMark(mail.kind, mail.key, at))
        save_state(run.home, state, sleep=run.sleep)


def _send_due(run: Run, state: State, active: bool) -> None:
    """Send the due emails and store the result of each one at once."""
    at = run.now()
    _prune_marks(state, at)
    view = load_pause(run.home, now=at, sleep=run.sleep)
    hold = hold_text(run.home, view)
    paused = view.kind == "on"
    due_now = mail_due(state, now=at, active=active, hold=hold, paused=paused)
    _deliver(run, state, due_now, at)


def _send_end(run: Run, state: State, view: PauseView) -> None:
    """Send only the email about the end of a pause, when it is due.

    This is for a call that makes no reading: the other emails come from a
    reading. ``view`` is the pause file of this call.
    """
    at = run.now()
    _prune_marks(state, at)
    _deliver(run, state, _end_mails(state, paused=view.kind == "on"), at)


def _queue_end(home: Path, state: State, pause: Pause | None, now: float) -> bool:
    """Make the end email of a pause that ended wait for the next send.

    The record is tied to the pause itself, not to the age of its windows, so a
    long gap loses no email. A pause that waits, or whose email went out, is not
    added again. A pause whose windows all have an end email already (the same
    window) needs none. Above ``END_NOTICE_MAX`` waiting pauses, the oldest are
    dropped with a ``end_notice_max`` trip; no email is lost, because the one
    email covers each waiting pause. True when the state changed.
    """
    if pause is None or pause in state.pause_ended or pause in state.end_sent:
        return False
    if all(_marked(state, ("end",), key) for key in end_keys(pause)):
        state.end_sent = [*state.end_sent, pause][-END_NOTICE_MAX:]
        return True
    state.pause_ended.append(pause)
    count = len(state.pause_ended)
    if count > END_NOTICE_MAX:
        log_trip(home, Trip("end_notice_max", END_NOTICE_MAX, count), now=now)
        state.pause_ended = state.pause_ended[-END_NOTICE_MAX:]
    return True


def _track_end(home: Path, state: State, view: PauseView, now: float) -> bool:
    """Make the end email of a pause file that ended wait for the next send.

    This needs no reading, and a failed reading does not stop it. The pause
    file stays: only a good reading ends a pause or starts a new one. True when
    the state changed.
    """
    if view.kind != "ended":
        return False
    return _queue_end(home, state, view.pause, now)


def _pause_trips(reading: Reading, pause: Pause) -> list[Trip]:
    """The ``pause_at`` record of each window that starts an ``auto`` pause.

    A named window has its used part. The account window (a refused request or
    overage without a full window) has the name of its cause.
    """
    trips: list[Trip] = []
    for key in pause.windows:
        window = reading.windows.get(key.name)
        observed: float | str
        if window is not None:
            observed = window.utilization
        else:
            observed = "rejected" if reading.status == "rejected" else "overage"
        trips.append(Trip("pause_at", PAUSE_AT, observed, key.name))
    return trips


def _apply_pause(run: Run, state: State) -> None:
    """Start or end the pause after a good reading. A failed write raises.

    A new ``auto`` pause writes one ``pause_at`` record for each of its windows
    to the guard log. A pause that ended keeps its end email, also when a new
    pause replaces it.
    """
    good = state.last_good
    if good is None:
        return
    at = run.now()
    _prune_suppressed(state, at)
    # The file is read again here: a pause or resume of the user can come
    # during the request.
    view = load_pause(run.home, now=at, sleep=run.sleep)
    choice = decide(state, good, view, now=at)
    if choice.action == "start" and choice.pause is not None:
        if view.kind == "ended":
            _queue_end(run.home, state, view.pause, at)
        write_pause(run.home, choice.pause, sleep=run.sleep)
        for trip in _pause_trips(good, choice.pause):
            log_trip(run.home, trip, now=at)
    elif choice.action == "end":
        clear_pause(run.home, sleep=run.sleep)
        _queue_end(run.home, state, choice.pause, at)


def cmd_read(run: Run, *, if_due: bool, no_mail: bool) -> int:
    """Read the usage, when it is due or at once. Exit 1 for a failed reading."""
    run.home.mkdir(parents=True, exist_ok=True)
    with lock(run.home) as held:
        if not held:
            print("busy")
            return 0
        return _read_locked(run, if_due=if_due, no_mail=no_mail)


def _read_locked(run: Run, *, if_due: bool, no_mail: bool) -> int:
    """The reading of the process that holds the lock.

    A pause that ended gets its end email also when no reading is due and
    after a failed reading. That makes no request.
    """
    at = run.now()
    state = load_state(run.home)
    changed = _refresh_account(state, run.deps)
    active = session_active(run.deps.projects, now=at)
    view = load_pause(run.home, now=at, sleep=run.sleep)
    changed = _track_end(run.home, state, view, at) or changed
    paused = view.kind == "on"
    try:
        if if_due and not due(state, now=at, active=active, paused=paused):
            if changed:
                save_state(run.home, state, sleep=run.sleep)
            if not no_mail:
                _send_end(run, state, view)
            print("not due")
            return 0
        # The attempt is stored first: a process that dies in the request must
        # not make a request at each start.
        state.last_attempt = at
        save_state(run.home, state, sleep=run.sleep)
        _take_reading(run, state)
        save_state(run.home, state, sleep=run.sleep)
        if state.last_error is None:
            # Only a good reading starts or ends a pause.
            _apply_pause(run, state)
            save_state(run.home, state, sleep=run.sleep)
        if not no_mail:
            _send_due(run, state, active)
    except OSError:
        print("state_write")
        return 1
    if state.last_error is not None:
        print(f"reading failed: {state.last_error}")
        return 1
    print("reading ok")
    return 0


# ── pause and resume ────────────────────────────────────────────────────


def _with_lock(run: Run, body: Callable[[], int]) -> int:
    """Run ``body`` under the lock. A running reading is waited for.

    The wait ends after ``run.limit_s``: then the result is ``busy``, exit 1.
    """
    tries = max(1, math.ceil(run.limit_s / LOCK_STEP_S))
    for left in range(tries - 1, -1, -1):
        with lock(run.home) as held:
            if held:
                return body()
        if left:
            run.sleep(LOCK_STEP_S)
    print("busy")
    return 1


def cmd_pause(run: Run, *, hours: float) -> int:
    """Start a ``user`` pause of ``hours``. It replaces each pause that is there.

    The file is written at once, so the hold starts also while a reading runs,
    and again under the lock, so that the reading cannot undo it. A pause that
    had ended keeps its end email for the next read.
    """
    run.home.mkdir(parents=True, exist_ok=True)
    at = run.now()
    pause = Pause("user", at, at + hours * 3600, ())
    first = load_pause(run.home, now=at, sleep=run.sleep)
    write_pause(run.home, pause, sleep=run.sleep)

    def body() -> int:
        write_pause(run.home, pause, sleep=run.sleep)
        state = load_state(run.home)
        if first.kind == "ended":
            _queue_end(run.home, state, first.pause, at)
        save_state(run.home, state, sleep=run.sleep)
        print(f"paused until {_local(pause.end_at)} (local time)")
        return 0

    return _with_lock(run, body)


def cmd_resume(run: Run) -> int:
    """End each pause at once and suppress each window at the limit until its reset.

    The file is removed at once and again under the lock. The suppressed windows
    are the windows of the pause and the high windows of the last good reading.
    It reads no usage and sends no email. A pause that was on gets no end
    email; a pause that had ended keeps its end email for the next read.
    """
    run.home.mkdir(parents=True, exist_ok=True)
    at = run.now()
    first = load_pause(run.home, now=at, sleep=run.sleep)
    clear_pause(run.home, sleep=run.sleep)

    def body() -> int:
        view = load_pause(run.home, now=at, sleep=run.sleep)
        clear_pause(run.home, sleep=run.sleep)
        state = load_state(run.home)
        keys: list[WindowKey] = []
        for item in (first, view):
            if item.pause is not None:
                keys.extend(item.pause.windows)
        if state.last_good is not None:
            keys.extend(k for k, _ in high_windows(state.last_good, at))
        for key in keys:
            if key not in state.suppressed:
                state.suppressed.append(key)
        _prune_suppressed(state, at)
        for item in (first, view):
            if item.kind == "ended":
                _queue_end(run.home, state, item.pause, at)
        save_state(run.home, state, sleep=run.sleep)
        print("resumed")
        return 0

    return _with_lock(run, body)


# ── The scheduled task ──────────────────────────────────────────────────


def pythonw_of(python: Path) -> Path:
    """The windowless interpreter beside ``python``."""
    return python.with_name("pythonw.exe")


def _task_action(home: Path, python: Path) -> tuple[str, str]:
    """The command and the arguments of the task."""
    args = ["-I", str(home / GUARD_NAME), "read", "--if-due", "--home", str(home)]
    return str(pythonw_of(python)), subprocess.list2cmdline(args)


def _plain(text: str | None) -> str:
    """A form of a command line that compares: no quotes, one slash, one case."""
    return (text or "").replace("\\", "/").replace('"', "").strip().casefold()


def _user_id() -> str | None:
    """The account name of the current user for the task, or None."""
    if sys.platform != "win32":
        return None
    size = ctypes.c_ulong(512)
    buffer = ctypes.create_unicode_buffer(size.value)
    try:
        got = ctypes.WinDLL("secur32").GetUserNameExW(2, buffer, ctypes.byref(size))
    except (OSError, AttributeError):
        return None
    return buffer.value if got and buffer.value else None


def task_xml(home: Path, python: Path) -> str:
    """The definition of the scheduled task."""
    command, arguments = _task_action(home, python)
    user = _user_id()
    user_xml = "" if user is None else f"      <UserId>{escape(user)}</UserId>\n"
    return (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        f'<Task version="1.2" xmlns="{TASK_NS}">\n'
        "  <RegistrationInfo>\n"
        "    <Description>Reads the Claude usage and sends an email near a limit."
        "</Description>\n"
        "  </RegistrationInfo>\n"
        "  <Triggers>\n"
        "    <TimeTrigger>\n"
        "      <Repetition>\n"
        "        <Interval>PT5M</Interval>\n"
        "        <StopAtDurationEnd>false</StopAtDurationEnd>\n"
        "      </Repetition>\n"
        "      <StartBoundary>2026-01-01T00:00:00</StartBoundary>\n"
        "      <Enabled>true</Enabled>\n"
        "    </TimeTrigger>\n"
        "  </Triggers>\n"
        "  <Principals>\n"
        '    <Principal id="Author">\n'
        f"{user_xml}"
        "      <LogonType>InteractiveToken</LogonType>\n"
        "      <RunLevel>LeastPrivilege</RunLevel>\n"
        "    </Principal>\n"
        "  </Principals>\n"
        "  <Settings>\n"
        "    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n"
        "    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n"
        "    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n"
        "    <StartWhenAvailable>true</StartWhenAvailable>\n"
        "    <Enabled>true</Enabled>\n"
        "    <ExecutionTimeLimit>PT4M</ExecutionTimeLimit>\n"
        "  </Settings>\n"
        '  <Actions Context="Author">\n'
        "    <Exec>\n"
        f"      <Command>{escape(command)}</Command>\n"
        f"      <Arguments>{escape(arguments)}</Arguments>\n"
        "    </Exec>\n"
        "  </Actions>\n"
        "</Task>\n"
    )


@dataclass(frozen=True)
class TaskView:
    """The scheduled task: ``absent``, ``ready``, ``disabled``, ``changed``,
    ``foreign`` or ``unknown``.

    ``changed`` is our action with other settings. ``unknown`` is a failed query
    that did not confirm the absence. ``raw`` is the found definition.
    """

    kind: str
    raw: str = ""

    @property
    def ours(self) -> bool:
        """True when the task has the action of this install."""
        return self.kind in ("ready", "disabled", "changed")


def _decode_xml(raw: bytes) -> str:
    """The text of a task definition in each encoding that ``schtasks`` writes."""
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", "replace")
    if b"\x00" in raw[:64]:
        return raw.decode("utf-16-le", "replace")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("oem" if sys.platform == "win32" else "latin-1", "replace")


def _task_root(text: str) -> ET.Element | None:
    """The root of a task definition, or None."""
    body = re.sub(r"^\s*<\?xml[^>]*\?>", "", text)
    if "<!" in body:
        return None  # no document type and no entity is expected
    try:
        return ET.fromstring(body)
    except (ET.ParseError, ValueError):
        return None


def _task_text(root: ET.Element, path: str, default: str) -> str:
    """The text at a path of the definition. Windows leaves default values out."""
    node = root.find("/".join(f"{{{TASK_NS}}}{name}" for name in path.split("/")))
    return default if node is None else (node.text or "").strip()


def _task_kind(text: str, actions: Iterable[tuple[str, str]]) -> str:
    """Compare a found definition with the possible actions of this install."""
    root = _task_root(text)
    node = None if root is None else root.find(f"{{{TASK_NS}}}Actions")
    if root is None or node is None or len(node) != 1:
        return "foreign"
    found = (
        _plain(_task_text(root, "Actions/Exec/Command", "")),
        _plain(_task_text(root, "Actions/Exec/Arguments", "")),
    )
    wanted = list(actions)
    if found not in [(_plain(c), _plain(a)) for c, a in wanted]:
        return "foreign"
    if _task_text(root, "Settings/Enabled", "true").lower() == "false":
        return "disabled"
    principal = "Principals/Principal/"
    same = (
        found == (_plain(wanted[0][0]), _plain(wanted[0][1]))
        and _task_text(root, "Triggers/TimeTrigger/Repetition/Interval", "") == "PT5M"
        and _task_text(root, "Triggers/TimeTrigger/Enabled", "true") == "true"
        and _task_text(root, "Settings/MultipleInstancesPolicy", "IgnoreNew")
        == "IgnoreNew"
        and _task_text(root, "Settings/ExecutionTimeLimit", "PT72H") == "PT4M"
        and _task_text(root, "Settings/DisallowStartIfOnBatteries", "true") == "false"
        and _task_text(root, "Settings/StopIfGoingOnBatteries", "true") == "false"
        and _task_text(root, principal + "LogonType", "InteractiveToken")
        == "InteractiveToken"
        and _task_text(root, principal + "RunLevel", "LeastPrivilege")
        == "LeastPrivilege"
    )
    return "ready" if same else "changed"


def _schtasks(
    deps: Deps, args: Sequence[str], *, capture_stderr: bool = False
) -> ProcessResult:
    """Run ``schtasks`` with a time limit. Raises ``ProcessFailure``."""
    return run_process(
        [*deps.schtasks, *args],
        cwd=None,
        limit_s=QUERY_LIMIT_S,
        capture_stderr=capture_stderr,
    )


def _plain_message(text: str) -> str:
    """A message for a comparison: one space between words, no case, no end dot."""
    return " ".join(text.split()).casefold().rstrip(".")


def _not_found_messages() -> list[str]:
    """The texts of the Windows error 2, in English and in the language of the system."""
    found = [_plain_message(TASK_NOT_FOUND_TEXT)]
    if sys.platform == "win32":
        with contextlib.suppress(OSError, ValueError):
            local = _plain_message(ctypes.FormatError(2))
            if local and local not in found:
                found.append(local)
    return found


def _error_texts(raw: bytes) -> list[str]:
    """The error output of a child, decoded in each encoding that it can have."""
    names = ("oem", "mbcs", "utf-8") if sys.platform == "win32" else ("utf-8",)
    texts: list[str] = []
    for name in names:
        with contextlib.suppress(LookupError):
            text = _plain_message(raw.decode(name, "replace"))
            if text not in texts:
                texts.append(text)
    return texts


def _task_not_found(result: ProcessResult) -> bool:
    """True only when ``schtasks`` confirmed that no task has the name.

    That is exit code 1, no output, and no error output or the text of the
    Windows error 2 ("the file is not found"). Each other failure (for example a
    refused access, a crash or another code) leaves the state of the task unknown.
    """
    if result.code != 1 or result.stdout.strip():
        return False
    if not result.stderr.strip():
        return True
    wanted = _not_found_messages()
    return any(m in text for text in _error_texts(result.stderr) for m in wanted)


def query_task(home: Path, deps: Deps, pythons: Sequence[Path]) -> TaskView:
    """The state of the task. The first interpreter is the wanted one.

    A failed query that is not a confirmed absence gives ``unknown``.

    Raises:
        ProcessFailure: The query gave no result, so the state is not known.
    """
    result = _schtasks(deps, ["/Query", "/TN", TASK_NAME, "/XML"], capture_stderr=True)
    if result.code != 0:
        return TaskView("absent" if _task_not_found(result) else "unknown")
    text = _decode_xml(result.stdout)
    return TaskView(_task_kind(text, [_task_action(home, p) for p in pythons]), text)


def _create_task(deps: Deps, xml: str, *, replace: bool) -> bool:
    """Create the task from a temporary definition file. True on success."""
    handle, name = tempfile.mkstemp(prefix="usage-guard-", suffix=".xml")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(xml.encode("utf-16"))
        args = ["/Create", "/TN", TASK_NAME, "/XML", name]
        return _schtasks(deps, [*args, *(["/F"] if replace else [])]).code == 0
    except ProcessFailure:
        return False
    finally:
        with contextlib.suppress(OSError):
            os.unlink(name)


def _delete_task(deps: Deps) -> bool:
    """Delete the task. True on success."""
    try:
        return _schtasks(deps, ["/Delete", "/TN", TASK_NAME, "/F"]).code == 0
    except ProcessFailure:
        return False


# ── Manifest, install and uninstall ─────────────────────────────────────


def _names_of(parts: Iterable[str]) -> set[str]:
    """The files that these parts need."""
    return {name for part in parts for name in PART_FILES[part]}


def _ordered(parts: Iterable[str]) -> tuple[str, ...]:
    """The parts in their fixed order."""
    chosen = set(parts)
    return tuple(part for part in PART_FILES if part in chosen)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest_from(doc: object) -> Manifest:
    names = ("schema", "parts", "files", "installed_at", "python", "exe")
    data = _fields(doc, names)
    _choice(data["schema"], (MANIFEST_SCHEMA,))
    parts = [_choice(p, PART_FILES) for p in _list(data["parts"], len(PART_FILES))]
    if not parts or len(set(parts)) != len(parts):
        raise ValueError("parts")
    files = _fields(data["files"], _names_of(parts))
    for digest in files.values():
        if not isinstance(digest, str) or not _HEX64.fullmatch(digest):
            raise ValueError("files")
    python, exe = data["python"], data["exe"]
    if not isinstance(python, str) or not (exe is None or isinstance(exe, str)):
        raise ValueError("program")
    return Manifest(
        _ordered(parts), dict(files), _number(data["installed_at"]), python, exe
    )


def load_manifest(home: Path) -> Manifest | None:
    """The manifest, or None without one.

    Raises:
        ValueError: The manifest is not readable or is refused.
    """
    try:
        return _manifest_from(_loads(_read_bounded(home / MANIFEST_NAME, MANIFEST_MAX)))
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ValueError("manifest") from exc


def _save_manifest(run: Run, manifest: Manifest) -> None:
    doc = {
        "schema": MANIFEST_SCHEMA,
        "parts": list(manifest.parts),
        "files": manifest.files,
        "installed_at": manifest.installed_at,
        "python": manifest.python,
        "exe": manifest.exe,
    }
    write_atomic(run.home / MANIFEST_NAME, _dumps(doc), sleep=run.sleep)


def install_state(home: Path) -> str:
    """``absent``, ``ok`` or ``drift`` (a bad manifest, or a file that differs)."""
    try:
        manifest = load_manifest(home)
        if manifest is None:
            return "absent"
        for name, digest in manifest.files.items():
            if _sha((home / name).read_bytes()) != digest:
                return "drift"
    except (OSError, ValueError):
        return "drift"
    return "ok"


def _file_bytes(path: Path) -> bytes | None:
    """The bytes of a file, or None without one."""
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _pythons(manifest: Manifest | None, wanted: Path | None) -> list[Path]:
    """The interpreters that a task of this install can use, the wanted one first.

    Without a wanted interpreter and without a manifest the list is empty: each
    task is then foreign.
    """
    found: list[Path] = [] if wanted is None else [wanted]
    if manifest is not None:
        found.append(Path(manifest.python))
    return found


def _manifest_or_drift(home: Path) -> Manifest | None:
    """The manifest, with a refused one as ``InstallError``."""
    try:
        return load_manifest(home)
    except ValueError as exc:
        raise InstallError("drift") from exc


def _task_or_unknown(run: Run, pythons: Sequence[Path]) -> TaskView:
    """The task, with a failed or an unknown query as ``InstallError``."""
    try:
        task = query_task(run.home, run.deps, pythons)
    except ProcessFailure as exc:
        raise InstallError("task_query") from exc
    if task.kind == "unknown":
        raise InstallError("task_query")
    return task


def _plan_files(run: Run, manifest: Manifest | None, part: str) -> dict[str, bytes]:
    """The new bytes of each file of the part. A foreign file is refused."""
    owned = set() if manifest is None else set(manifest.files)
    planned: dict[str, bytes] = {}
    for name in PART_FILES[part]:
        try:
            planned[name] = (run.deps.source / name).read_bytes()
        except OSError as exc:
            raise InstallError("no_source") from exc
        present = _file_bytes(run.home / name)
        if present not in (None, planned[name]) and name not in owned:
            raise InstallError("file_foreign")
    return planned


def _new_manifest(
    run: Run, old: Manifest | None, part: str, files: dict[str, bytes], python: Path
) -> Manifest:
    """The manifest after the install. It is equal to the old one without a change."""
    hashes = {} if old is None else dict(old.files)
    hashes.update({name: _sha(data) for name, data in files.items()})
    exe = resolve_exe(which=run.deps.which) or (None if old is None else old.exe)
    parts = _ordered((part,) if old is None else (*old.parts, part))
    new = Manifest(parts, hashes, run.now(), str(python), exe)
    if old is not None and new == Manifest(
        old.parts, old.files, new.installed_at, old.python, old.exe
    ):
        return old
    return new


def _restore(run: Run, saved: Mapping[str, bytes | None]) -> None:
    """Put the files of a failed install back."""
    for name, data in saved.items():
        with contextlib.suppress(OSError):
            if data is None:
                (run.home / name).unlink(missing_ok=True)
            else:
                write_atomic(run.home / name, data, sleep=run.sleep)


def _restore_task(run: Run, before: TaskView) -> None:
    """Put the task of a failed install back."""
    if before.kind == "absent":
        _delete_task(run.deps)
    else:
        _create_task(run.deps, _utf16_text(before.raw), replace=True)


def _utf16_text(text: str) -> str:
    """A found definition with the declaration of the encoding that is written."""
    body = re.sub(r"^\s*<\?xml[^>]*\?>\s*", "", text)
    return '<?xml version="1.0" encoding="UTF-16"?>\n' + body


def _install_task(run: Run, part: str, python: Path) -> None:
    """The install of the task part. Each check is before the first write."""
    if not python.is_file() or not pythonw_of(python).is_file():
        raise InstallError("no_pythonw")
    old = _manifest_or_drift(run.home)
    files = _plan_files(run, old, part)
    task = _task_or_unknown(run, _pythons(old, python))
    if task.kind == "foreign":
        raise InstallError("task_foreign")
    manifest = _new_manifest(run, old, part, files, python)

    created = not run.home.exists()
    saved: dict[str, bytes | None] = {}
    task_done = False
    try:
        run.home.mkdir(parents=True, exist_ok=True)
        for name, data in files.items():
            present = _file_bytes(run.home / name)
            if present != data:
                saved[name] = present
                write_atomic(run.home / name, data, sleep=run.sleep)
        if task.kind != "ready":
            xml = task_xml(run.home, python)
            task_done = _create_task(run.deps, xml, replace=task.ours)
            if not task_done:
                raise InstallError("task_create")
        if manifest != old:
            saved[MANIFEST_NAME] = _file_bytes(run.home / MANIFEST_NAME)
            _save_manifest(run, manifest)
    except (OSError, InstallError) as exc:
        if task_done:
            _restore_task(run, task)
        _restore(run, saved)
        if created:
            with contextlib.suppress(OSError):
                run.home.rmdir()
        if isinstance(exc, InstallError):
            raise
        raise InstallError("install_write") from exc


def _install_hook(run: Run, python: Path, settings: Path) -> None:
    """The install of the hook part. Each check is before the first write.

    The order of the writes: the files, the record, the manifest, the backup of
    the settings and last the settings. A failure puts the files, the record and
    the manifest back; the backup stays.
    """
    if not python.is_file():
        raise InstallError("no_python")
    old = _manifest_or_drift(run.home)
    files = _plan_files(run, old, "hook")
    current = _read_settings(settings)
    edit = _plan_hook_install(current, run.home, python)
    program = python if old is None else Path(old.python)
    manifest = _new_manifest(run, old, "hook", files, program)

    created = not run.home.exists()
    saved: dict[str, bytes | None] = {}
    try:
        run.home.mkdir(parents=True, exist_ok=True)
        for name, data in files.items():
            present = _file_bytes(run.home / name)
            if present != data:
                saved[name] = present
                write_atomic(run.home / name, data, sleep=run.sleep)
        if edit is not None:
            record = _dumps(
                {
                    "schema": HOOK_RECORD_SCHEMA,
                    "made": list(edit.made),
                    "padded": list(edit.padded),
                }
            )
            present = _file_bytes(run.home / HOOK_RECORD_NAME)
            if present != record:
                saved[HOOK_RECORD_NAME] = present
                write_atomic(run.home / HOOK_RECORD_NAME, record, sleep=run.sleep)
        if manifest != old:
            saved[MANIFEST_NAME] = _file_bytes(run.home / MANIFEST_NAME)
            _save_manifest(run, manifest)
        if edit is not None:
            _write_settings(run, settings, current.raw, edit.text)
    except (OSError, InstallError) as exc:
        _restore(run, saved)
        if created:
            with contextlib.suppress(OSError):
                run.home.rmdir()
        if isinstance(exc, InstallError):
            raise
        raise InstallError("install_write") from exc


def _settings_path(run: Run, settings: Path | None) -> Path:
    """The settings file of the hook part: the option, else the default of ``Deps``."""
    path = settings if settings is not None else run.deps.settings
    if path is None:
        raise InstallError("no_settings")
    return path


def cmd_install(
    run: Run, *, part: str | None, python: Path, settings: Path | None = None
) -> int:
    """Install a part, or each part without one. A second run changes nothing.

    The task part copies the files and makes the task. The hook part copies the
    files and adds the hook entry to the settings.
    """
    for one in INSTALL_PARTS if part is None else (part,):
        try:
            if one == "hook":
                _install_hook(run, python, _settings_path(run, settings))
            else:
                _install_task(run, one, python)
        except InstallError as exc:
            print(exc.code)
            return 1
        print(f"installed: {one}")
    return 0


def cmd_uninstall(
    run: Run, *, part: str | None, python: Path | None, settings: Path | None = None
) -> int:
    """Remove a part, or each part without one: first the hook, then the task.

    A foreign task, a foreign hook entry, a file that the manifest does not name
    and the files of the other parts stay. Without ``python`` the task check uses
    the interpreter that the manifest names.
    """
    for one in tuple(reversed(INSTALL_PARTS)) if part is None else (part,):
        try:
            if one == "hook":
                _uninstall_hook(run, _settings_path(run, settings))
            else:
                _uninstall_task(run, one, python)
        except InstallError as exc:
            print(exc.code)
            return 1
        print(f"uninstalled: {one}")
    return 0


def _load_or_refused(home: Path) -> tuple[Manifest | None, bool]:
    """The manifest, and True when the manifest is refused."""
    try:
        return load_manifest(home), False
    except ValueError:
        return None, True


def _drop_part(run: Run, manifest: Manifest | None, part: str) -> None:
    """Remove the files that only this part needs, then save or remove the manifest.

    The bytecode cache of a removed file (``__pycache__/<name>.*.pyc``) goes too,
    and the cache folder goes when it is empty.
    """
    if manifest is None or part not in manifest.parts:
        return
    rest = _ordered(p for p in manifest.parts if p != part)
    needed = _names_of(rest)
    cache = run.home / "__pycache__"
    try:
        for name in sorted(set(manifest.files) - needed):
            (run.home / name).unlink(missing_ok=True)
            for compiled in cache.glob(f"{Path(name).stem}.*.pyc"):
                compiled.unlink(missing_ok=True)
        if cache.is_dir() and not cache.is_symlink() and not any(cache.iterdir()):
            cache.rmdir()
        if not rest:
            (run.home / MANIFEST_NAME).unlink(missing_ok=True)
            return
        files = {n: h for n, h in manifest.files.items() if n in needed}
        _save_manifest(
            run,
            Manifest(rest, files, manifest.installed_at, manifest.python, manifest.exe),
        )
    except OSError as exc:
        raise InstallError("uninstall_write") from exc


def _uninstall_task(run: Run, part: str, python: Path | None) -> None:
    """The uninstall of the task part: first the task, then the files."""
    manifest, refused = _load_or_refused(run.home)
    task = _task_or_unknown(run, _pythons(manifest, python))
    if task.ours and not _delete_task(run.deps):
        raise InstallError("task_delete")
    if task.kind == "foreign":
        print("task_foreign: kept")
    if refused:
        raise InstallError("drift")
    _drop_part(run, manifest, part)


def _uninstall_hook(run: Run, settings: Path) -> None:
    """The uninstall of the hook part: first the entry, then the pause, then the files.

    A missing settings file holds no entry. The uninstall ends a pause, so that no
    session stays held without the hook files.
    """
    manifest, refused = _load_or_refused(run.home)
    made, padded = _load_record(run.home)
    try:
        current: _Settings | None = _read_settings(settings)
    except InstallError as exc:
        if exc.code != "settings_missing":
            raise
        current = None
    if current is not None:
        text = _plan_hook_uninstall(current, run.home, made, padded)
        if text is not None:
            try:
                _write_settings(run, settings, current.raw, text)
            except OSError as exc:
                raise InstallError("uninstall_write") from exc
    try:
        clear_pause(run.home, sleep=run.sleep)
    except OSError as exc:
        raise InstallError("uninstall_write") from exc
    if refused:
        raise InstallError("drift")
    try:
        (run.home / HOOK_RECORD_NAME).unlink(missing_ok=True)
    except OSError as exc:
        raise InstallError("uninstall_write") from exc
    _drop_part(run, manifest, "hook")


# ── Settings edit ───────────────────────────────────────────────────────
#
# The hook part edits the text of the user settings, never a new dump of the
# parsed data. The parser keeps the span of each value, so that the install adds
# one piece of text and the uninstall removes that same piece. Each other byte of
# the file stays: the order of the keys, the spaces, the line ends and the escapes.

_WS = " \t\n\r"


def _reject_constant(name: str) -> object:
    """``NaN``, ``Infinity`` and ``-Infinity`` are not JSON."""
    raise ValueError(f"constant {name}")


_SCALARS = json.JSONDecoder(parse_constant=_reject_constant)


@dataclass(frozen=True)
class _Node:
    """One JSON value of a settings text and its span ``[start, end)``.

    An object has its keys, the start of each key and the value nodes. An array
    has its item nodes. A scalar has neither.
    """

    kind: str
    start: int
    end: int
    items: tuple[_Node, ...] = ()
    keys: tuple[str, ...] = ()
    key_starts: tuple[int, ...] = ()

    def member(self, key: str) -> _Node | None:
        """The value node of a key of an object, or None."""
        if self.kind != "object" or key not in self.keys:
            return None
        return self.items[self.keys.index(key)]

    def item_start(self, k: int) -> int:
        """The start of item ``k``: the key of a member, else the value."""
        return self.key_starts[k] if self.kind == "object" else self.items[k].start


@dataclass(frozen=True)
class _Settings:
    """A settings file that the guard accepts: its bytes, its text and its data."""

    raw: bytes
    text: str
    root: _Node
    doc: dict[str, Any]


@dataclass(frozen=True)
class _HookEdit:
    """The new settings text of an install and the containers that it made or filled."""

    text: str
    made: tuple[str, ...]
    padded: tuple[str, ...]


def _skip(text: str, i: int) -> int:
    """The first position from ``i`` that is not white space."""
    n = len(text)
    while i < n and text[i] in _WS:
        i += 1
    return i


def _parse_value(text: str, i: int, depth: int) -> _Node:
    """The value at ``i``. Bad JSON, a duplicate key or deep nesting is ``ValueError``."""
    if depth > SETTINGS_DEPTH:
        raise ValueError("nesting")
    if i >= len(text):
        raise ValueError("end")
    if text[i] == "{":
        return _parse_object(text, i, depth)
    if text[i] == "[":
        return _parse_array(text, i, depth)
    value, end = _SCALARS.raw_decode(text, i)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("number")
    return _Node("scalar", i, end)


def _parse_object(text: str, start: int, depth: int) -> _Node:
    """The object at ``start``."""
    n = len(text)
    i = _skip(text, start + 1)
    if i < n and text[i] == "}":
        return _Node("object", start, i + 1)
    keys: list[str] = []
    key_starts: list[int] = []
    items: list[_Node] = []
    while True:
        if i >= n or text[i] != '"':
            raise ValueError("key")
        key, after = _SCALARS.raw_decode(text, i)
        if not isinstance(key, str):
            raise ValueError("key")
        if key in keys:
            raise ValueError("duplicate")
        colon = _skip(text, after)
        if colon >= n or text[colon] != ":":
            raise ValueError("colon")
        node = _parse_value(text, _skip(text, colon + 1), depth + 1)
        keys.append(key)
        key_starts.append(i)
        items.append(node)
        i = _skip(text, node.end)
        if i < n and text[i] == ",":
            i = _skip(text, i + 1)
            continue
        if i < n and text[i] == "}":
            return _Node(
                "object", start, i + 1, tuple(items), tuple(keys), tuple(key_starts)
            )
        raise ValueError("object")


def _parse_array(text: str, start: int, depth: int) -> _Node:
    """The array at ``start``."""
    n = len(text)
    i = _skip(text, start + 1)
    if i < n and text[i] == "]":
        return _Node("array", start, i + 1)
    items: list[_Node] = []
    while True:
        node = _parse_value(text, i, depth + 1)
        items.append(node)
        i = _skip(text, node.end)
        if i < n and text[i] == ",":
            i = _skip(text, i + 1)
            continue
        if i < n and text[i] == "]":
            return _Node("array", start, i + 1, tuple(items))
        raise ValueError("array")


def _check_shape(doc: object) -> dict[str, Any]:
    """The settings data when the hook part can edit it, else ``ValueError``.

    The root is an object, ``hooks`` is an object, ``hooks.PreToolUse`` is a list
    of objects and the ``hooks`` of each group is a list. Each one can be absent.
    """
    if not isinstance(doc, dict):
        raise ValueError("root")
    hooks = doc.get("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("hooks")
    groups = hooks.get(HOOK_EVENT, [])
    if not isinstance(groups, list):
        raise ValueError("groups")
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("hooks", []), list):
            raise ValueError("group")
    return doc


def _settings_from(raw: bytes) -> _Settings:
    """The accepted settings of these bytes, else ``ValueError``.

    A byte order mark, bad UTF-8, bad JSON, a duplicate key at any depth, a
    constant such as ``NaN`` and text after the root are each refused.
    """
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError("bom")
    text = raw.decode("utf-8")
    root = _parse_value(text, _skip(text, 0), 0)
    if _skip(text, root.end) != len(text):
        raise ValueError("trailing")
    doc = _check_shape(json.loads(text))
    return _Settings(raw, text, root, doc)


def _read_settings(path: Path) -> _Settings:
    """The settings file, else ``InstallError``.

    Codes: ``settings_link`` for a link, ``settings_missing`` for no file and
    ``settings_invalid`` for a file that the guard does not edit.
    """
    if path.is_symlink():
        raise InstallError("settings_link")
    try:
        raw = _read_bounded(path, SETTINGS_MAX)
    except FileNotFoundError as exc:
        raise InstallError("settings_missing") from exc
    except ValueError as exc:
        raise InstallError("settings_invalid") from exc
    try:
        return _settings_from(raw)
    except (ValueError, RecursionError) as exc:
        raise InstallError("settings_invalid") from exc


def _reparse(text: str) -> _Settings:
    """The settings of an edited text. A failure is a fault of the edit."""
    try:
        return _settings_from(text.encode("utf-8"))
    except (ValueError, RecursionError) as exc:
        raise InstallError("settings_edit") from exc


def _home_key(text: str) -> str:
    """A home path for a comparison: forward slashes, no last slash, case on Windows."""
    key = text.replace("\\", "/").rstrip("/")
    return key.casefold() if sys.platform == "win32" else key


def _is_ours(item: object, home: Path) -> bool:
    """True for a hook entry of this home: ``--home <home>`` last and the hook file."""
    if not isinstance(item, dict):
        return False
    args = item.get("args")
    if not isinstance(args, list) or len(args) < 2:
        return False
    words = [a for a in args if isinstance(a, str)]
    if len(words) != len(args) or words[-2] != "--home":
        return False
    if _home_key(words[-1]) != _home_key(home.as_posix()):
        return False
    return any("/" + HOOK_NAME in word for word in words)


def _our_entries(
    doc: Mapping[str, Any], home: Path
) -> list[tuple[int, int, dict[str, Any]]]:
    """Each hook entry of this home: the group index, the entry index and the entry."""
    found: list[tuple[int, int, dict[str, Any]]] = []
    hooks = doc.get("hooks", {})
    for gi, group in enumerate(hooks.get(HOOK_EVENT, [])):
        for ei, item in enumerate(group.get("hooks", [])):
            if _is_ours(item, home):
                found.append((gi, ei, item))
    return found


def _newline(text: str) -> str:
    """The line end of the file: CRLF when the file has one, else LF."""
    return "\r\n" if "\r\n" in text else "\n"


def _indent_unit(text: str) -> str:
    """The indent of the first indented line, else two spaces."""
    for line in text.splitlines():
        body = line.lstrip(" \t")
        if body and len(body) < len(line):
            return line[: len(line) - len(body)]
    return "  "


def _line_indent(text: str, pos: int) -> str:
    """The white space at the start of the line that holds ``pos``."""
    first = max(text.rfind("\n", 0, pos), text.rfind("\r", 0, pos)) + 1
    last = first
    while last < pos and text[last] in " \t":
        last += 1
    return text[first:last]


def _insert(
    text: str, node: _Node, key: str | None, value: object, unit: str, nl: str
) -> tuple[str, bool]:
    """Add a member (with ``key``) or an item at the end of a container.

    Returns the new text and True when the container was ``{}`` or ``[]`` with
    nothing inside: the uninstall then removes the new line ends too.
    """

    def piece(indent: str) -> str:
        body = json.dumps(value, indent=unit, ensure_ascii=False)
        body = body.replace("\n", nl + indent)
        if key is None:
            return body
        return json.dumps(key, ensure_ascii=False) + ": " + body

    if node.items:
        last = len(node.items) - 1
        start = node.item_start(last)
        gap = start
        while gap > node.start + 1 and text[gap - 1] in _WS:
            gap -= 1
        at = node.items[last].end
        added = "," + text[gap:start] + piece(_line_indent(text, start))
        return text[:at] + added + text[at:], False
    outer = _line_indent(text, node.start)
    inner = outer + unit
    at = node.start + 1
    if node.end - node.start == 2:
        return text[:at] + nl + inner + piece(inner) + nl + outer + text[at:], True
    return text[:at] + nl + inner + piece(inner) + text[at:], False


def _remove(text: str, node: _Node, k: int) -> str:
    """Remove item ``k`` of a container and its separator."""
    end = node.items[k].end
    if k > 0:
        return text[: node.items[k - 1].end] + text[end:]
    if len(node.items) > 1:
        return text[: node.item_start(0)] + text[node.item_start(1) :]
    return text[: node.start + 1] + text[end:]


def _container(view: _Settings, name: str) -> _Node | None:
    """The root, the ``hooks`` object or the ``PreToolUse`` list, or None."""
    if name == "root":
        return view.root
    hooks = view.root.member("hooks")
    if name == "hooks" or hooks is None:
        return hooks
    return hooks.member(HOOK_EVENT)


def _need(node: _Node | None) -> _Node:
    """A node that the edit needs. None is a fault of the edit."""
    if node is None:
        raise InstallError("settings_edit")
    return node


def _plan_hook_install(
    current: _Settings, home: Path, python: Path
) -> _HookEdit | None:
    """The settings edit of the install, or None when the entry is already there.

    An entry of this home that differs, or two entries, is ``hook_differs``.
    """
    want = hook_entry(home, python)
    found = _our_entries(current.doc, home)
    if found:
        if len(found) == 1 and found[0][2] == want:
            return None
        raise InstallError("hook_differs")
    group = {"matcher": HOOK_MATCHER, "hooks": [want]}
    text = current.text
    unit, nl = _indent_unit(text), _newline(text)
    hooks = current.root.member("hooks")
    groups = None if hooks is None else hooks.member(HOOK_EVENT)
    if hooks is None:
        value: object = {HOOK_EVENT: [group]}
        new, filled = _insert(text, current.root, "hooks", value, unit, nl)
        made, where = MADE_CONTAINERS, "root"
    elif groups is None:
        new, filled = _insert(text, hooks, HOOK_EVENT, [group], unit, nl)
        made, where = (HOOK_EVENT,), "hooks"
    else:
        new, filled = _insert(text, groups, None, group, unit, nl)
        made, where = (), HOOK_EVENT
    edit = _HookEdit(new, made, (where,) if filled else ())
    _check_install_edit(current, edit, home, group)
    return edit


def _check_install_edit(
    current: _Settings, edit: _HookEdit, home: Path, group: Mapping[str, Any]
) -> None:
    """The new text holds the old data and one new group, in the same order."""
    after = _reparse(edit.text)
    if len(_our_entries(after.doc, home)) != 1:
        raise InstallError("settings_edit")
    doc = after.doc
    hooks = doc["hooks"]
    groups = hooks[HOOK_EVENT]
    if not groups or groups[-1] != group:
        raise InstallError("settings_edit")
    groups.pop()
    if HOOK_EVENT in edit.made:
        if groups:
            raise InstallError("settings_edit")
        del hooks[HOOK_EVENT]
    if "hooks" in edit.made:
        if hooks:
            raise InstallError("settings_edit")
        del doc["hooks"]
    if json.dumps(doc) != json.dumps(current.doc):
        raise InstallError("settings_edit")


def _plan_hook_uninstall(
    current: _Settings,
    home: Path,
    made: Sequence[str],
    padded: Sequence[str],
) -> str | None:
    """The settings text without the entries of this home, or None without one.

    A group that holds only the entry, with no key other than ``matcher`` and
    ``hooks``, goes too. Then an empty container that the install made goes, and
    an empty container that the install filled gets back its old form.
    """
    view = current
    text = current.text
    changed = False
    while found := _our_entries(view.doc, home):
        gi, ei, _entry = found[0]
        groups = _need(_container(view, HOOK_EVENT))
        entries = _need(groups.items[gi].member("hooks"))
        group = view.doc["hooks"][HOOK_EVENT][gi]
        if len(entries.items) == 1 and set(group) <= {"matcher", "hooks"}:
            text = _remove(text, groups, gi)
        else:
            text = _remove(text, entries, ei)
        view = _reparse(text)
        changed = True
    if not changed:
        return None
    for name, parent in ((HOOK_EVENT, "hooks"), ("hooks", "root")):
        holder = _container(view, parent)
        child = None if holder is None else holder.member(name)
        if name in made and holder is not None and child is not None:
            if not child.items:
                text = _remove(text, holder, holder.keys.index(name))
                view = _reparse(text)
    for name in padded:
        node = _container(view, name)
        if node is not None and not node.items and node.end - node.start > 2:
            text = text[: node.start + 1] + text[node.end - 1 :]
            view = _reparse(text)
    return text


def _load_record(home: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The containers that the install made and filled. A bad record names none."""
    try:
        doc = _fields(
            _loads(_read_bounded(home / HOOK_RECORD_NAME, MANIFEST_MAX)),
            ("schema", "made", "padded"),
        )
        _choice(doc["schema"], (HOOK_RECORD_SCHEMA,))
        made = [_choice(m, MADE_CONTAINERS) for m in _list(doc["made"], 2)]
        padded = [_choice(p, PADDED_CONTAINERS) for p in _list(doc["padded"], 3)]
    except (OSError, ValueError):
        return (), ()
    return tuple(made), tuple(padded)


def _write_settings(run: Run, path: Path, raw: bytes, text: str) -> None:
    """Back up the old settings, check that they did not change, then write the new.

    The backup is ``<home>/backup/settings-<UTC time>-<sha8>.json``. A file that
    changed after the read is ``settings_changed``, and nothing is written to it.
    """
    folder = run.home / BACKUP_DIR
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(run.now()))
    backup = folder / f"settings-{stamp}-{_sha(raw)[:8]}.json"
    write_atomic(backup, raw, sleep=run.sleep)
    if path.is_symlink():
        raise InstallError("settings_link")
    try:
        again = _read_bounded(path, SETTINGS_MAX)
    except (FileNotFoundError, ValueError) as exc:
        raise InstallError("settings_changed") from exc
    if again != raw:
        raise InstallError("settings_changed")
    write_atomic(path, text.encode("utf-8"), sleep=run.sleep)


def hook_state(home: Path, settings: Path | None) -> str:
    """The hook for the status: one of ``HOOK_STATES``. It starts no process.

    ``unknown``: no settings path, or a settings file that is not readable.
    ``absent``: no entry and no hook part. ``drift``: the entry and the manifest
    do not agree, or an installed file differs. ``disabled``: installed, but the
    settings set ``disableAllHooks``.
    """
    if settings is None:
        return "unknown"
    try:
        doc: Mapping[str, Any] = _read_settings(settings).doc
    except InstallError as exc:
        if exc.code != "settings_missing":
            return "unknown"
        doc = {}
    except OSError:
        return "unknown"
    found = _our_entries(doc, home)
    manifest, _refused = _load_or_refused(home)
    part = manifest is not None and "hook" in manifest.parts
    if not found and not part:
        return "absent"
    if not found or not part or len(found) != 1:
        return "drift"
    entry = found[0][2]
    command = entry.get("command")
    if not isinstance(command, str) or entry != hook_entry(home, command):
        return "drift"
    if install_state(home) != "ok":
        return "drift"
    if doc.get("disableAllHooks") is True:
        return "disabled"
    return "installed"


# ── status ──────────────────────────────────────────────────────────────


def _task_status(run: Run) -> str:
    """The task for the status: never a failure of the command."""
    try:
        manifest = load_manifest(run.home)
    except ValueError:
        manifest = None
    pythons = [] if manifest is None else [Path(manifest.python)]
    try:
        return query_task(run.home, run.deps, pythons).kind
    except ProcessFailure:
        return "unknown"


def status_doc(run: Run) -> dict[str, Any]:
    """The status as data. A window without a value has no percent, never 0."""
    at = run.now()
    state = load_state(run.home)
    good = state.last_good
    windows: dict[str, Any] = {}
    for name, window in {} if good is None else good.windows.items():
        value = window.utilization if window.current(at) else None
        windows[name] = {
            "utilization": value,
            "percent": None if value is None else round(value * 100, 1),
            "resets_at": window.resets_at,
        }
    view = load_pause(run.home, now=at, sleep=run.sleep)
    pause = {"bad": "pause_bad"}.get(view.kind, view.kind)
    if view.kind == "on" and view.pause is not None:
        pause = view.pause.origin
    mail = state.last_email
    return {
        "schema": STATUS_SCHEMA,
        "reading": good is not None,
        "read_at": None if good is None else good.at,
        "age_s": None if good is None else max(0, round(at - good.at)),
        "status": None if good is None else good.status,
        "overage": None if good is None else good.overage,
        "windows": windows,
        "last_attempt": state.last_attempt,
        "last_error": state.last_error,
        "failing_since": state.failing_since,
        "last_email": None
        if mail is None
        else {"kind": mail.kind, "at": mail.at, "outcome": mail.outcome},
        "task": _task_status(run),
        "pause": pause,
        "pause_end_at": None if view.pause is None else view.pause.end_at,
        "install": install_state(run.home),
        "hook": hook_state(run.home, run.deps.settings),
    }


def _window_line(name: str, item: Mapping[str, Any]) -> str:
    """One window for a person."""
    reset = _local(item["resets_at"])
    if item["percent"] is None:
        return f"{name}: no value (the reset was {reset})"
    return f"{name}: at least {item['percent']:g} % (reset {reset})"


def status_lines(doc: Mapping[str, Any]) -> list[str]:
    """The status for a person."""
    if doc["reading"]:
        lines = [_window_line(n, item) for n, item in doc["windows"].items()]
        lines.append(f"read: {_local(doc['read_at'])}, {doc['age_s']} s ago")
        if doc["status"] == "rejected" or doc["overage"]:
            lines.append(f"limit: status {doc['status']}, overage {doc['overage']}")
    else:
        lines = ["no reading"]
    if doc["last_error"] is not None:
        since = doc["failing_since"]
        note = "" if since is None else f" (since {_local(since)})"
        lines.append(f"last error: {doc['last_error']}{note}")
    else:
        lines.append("last error: none")
    mail = doc["last_email"]
    if mail is None:
        lines.append("last email: none")
    else:
        when = _local(mail["at"])
        lines.append(f"last email: {mail['kind']}, {mail['outcome']}, {when}")
    lines.append(f"task: {doc['task']}")
    end = doc["pause_end_at"]
    until = "" if end is None else f" (end {_local(end)})"
    lines.append(f"pause: {doc['pause']}{until}")
    lines.append(f"install: {doc['install']}")
    lines.append(f"hook: {doc['hook']}")
    return lines


def cmd_status(run: Run, *, as_json: bool) -> int:
    """Show the status. It writes nothing and starts only the task query."""
    doc = status_doc(run)
    if as_json:
        print(json.dumps(doc, indent=1, sort_keys=True))
    else:
        print("\n".join(status_lines(doc)))
    return 0


# ── Command line ────────────────────────────────────────────────────────


def _absolute(text: str) -> Path:
    """An absolute path, else a command line error."""
    path = Path(text)
    if not path.is_absolute() or "\x00" in text:
        raise argparse.ArgumentTypeError("the path must be absolute")
    return path


def _hours(text: str) -> float:
    """A finite number of hours from 0.02 to 192, else a command line error."""
    try:
        value = float(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("the hours must be a number") from exc
    if not math.isfinite(value) or not PAUSE_HOURS_MIN <= value <= PAUSE_HOURS_MAX:
        raise argparse.ArgumentTypeError(
            f"the hours must be from {PAUSE_HOURS_MIN:g} to {PAUSE_HOURS_MAX:g}"
        )
    return value


def build_parser() -> argparse.ArgumentParser:
    """The command line. An unknown or shortened option is an error."""
    parser = argparse.ArgumentParser(
        prog="usage_guard", description="Claude usage guard", allow_abbrev=False
    )
    commands = parser.add_subparsers(dest="command", required=True)

    def add(name: str, text: str) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=text, allow_abbrev=False)
        sub.add_argument(
            "--home",
            type=_absolute,
            required=True,
            help="the folder of the guard (required, no default)",
        )
        return sub

    read = add("read", "read the usage")
    read.add_argument("--if-due", action="store_true", help="only when it is due")
    read.add_argument("--no-mail", action="store_true", help="send no email")
    status = add("status", "show the last value and the task")
    status.add_argument("--json", action="store_true", help="show JSON")
    pause = add("pause", "hold the sessions for some hours")
    pause.add_argument(
        "--hours",
        type=_hours,
        default=PAUSE_HOURS_DEFAULT,
        help="the length of the pause, from 0.02 to 192 hours (default 5)",
    )
    add("resume", "end the pause and continue the sessions")
    for name, text in (("install", "install a part"), ("uninstall", "remove a part")):
        sub = add(name, text)
        sub.add_argument(
            "--part",
            choices=INSTALL_PARTS,
            default=None,
            help="one part (default: each part)",
        )
        sub.add_argument(
            "--python",
            type=_absolute,
            required=name == "install",
            default=None,
            help=(
                "the interpreter of the task and of the hook"
                if name == "install"
                else "the interpreter of the task (default: the one of the manifest)"
            ),
        )
        sub.add_argument(
            "--settings",
            type=_absolute,
            default=None,
            help="the user settings of the hook (default ~/.claude/settings.json)",
        )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    deps: Deps | None = None,
    now: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
    limit_s: float = READ_LIMIT_S,
) -> int:
    """Run one command and return its exit code. The keywords are for the tests."""
    args = build_parser().parse_args(argv)
    if deps is None:
        deps = Deps(settings=Path.home() / ".claude" / "settings.json")
    run = Run(args.home, deps, now, sleep, limit_s)
    try:
        if args.command == "read":
            return cmd_read(run, if_due=args.if_due, no_mail=args.no_mail)
        if args.command == "status":
            return cmd_status(run, as_json=args.json)
        if args.command == "pause":
            return cmd_pause(run, hours=args.hours)
        if args.command == "resume":
            return cmd_resume(run)
        if args.command == "install":
            return cmd_install(
                run, part=args.part, python=args.python, settings=args.settings
            )
        return cmd_uninstall(
            run, part=args.part, python=args.python, settings=args.settings
        )
    except OSError as exc:
        print(f"io_error: {type(exc).__name__}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
