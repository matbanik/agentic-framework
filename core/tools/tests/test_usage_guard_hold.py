"""Tests for the hold of the usage guard (MEU-978, AC-978.1 to .10, .12 and .13).

The hook is ``tools/usage_guard_hook.py``. The guard ``tools/usage_guard.py`` makes
the hook entry (``LAUNCHER``), starts and ends the pause and sends the emails.
No test starts the real Claude program or sends a real email, and no test writes
the user settings. Each test uses a scratch home. The unit tests pass a fake
clock; a process test uses a pause end of 1 s or a fixed deadline of seconds.

AC-978.11 (the probe verdict) is a row check of the plan, not a test here.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import io
import json
import os
import statistics
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD = REPO_ROOT / "tools" / "usage_guard.py"
HOOK = REPO_ROOT / "tools" / "usage_guard_hook.py"

T0 = 1_800_000_000.0
FIVE_RESET = 1_800_007_200
SEVEN_RESET = 1_800_400_000
BASE_PY = Path(getattr(sys, "_base_executable", sys.executable)).as_posix()
# The hook trusts its own interpreter and the base interpreter of it. The
# framework has no fixed interpreter path, so the forms use the base one.
PY_DEFAULT = BASE_PY
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

FAIL_OPEN_S = 5.0
HELD_S = 3.0
SKILL_PATH = "/work/project/.agent/skills/usage-guard/SKILL.md"

API_KEYS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
)
HOOK_ENV_KEYS = (*API_KEYS, "CLAUDE_CODE_ENTRYPOINT")

# The exact text of LAUNCHER in the plan. The p2p tests run this text before the
# hook exists; an f2p test proves that the guard holds the same text.
LAUNCHER_TEXT = """\
import sys
try:
    p = sys.argv[sys.argv.index('--home') + 1] + '/usage_guard_hook.py'
    exec(compile(open(p, 'rb').read(), p, 'exec'), {'__name__': '__main__', '__file__': p})
except BaseException:
    pass
import os
os._exit(0)
"""

BROKEN_SCRIPTS = {
    "missing": None,
    "syntax": b"def (\n",
    "raises": b"raise RuntimeError('broken')\n",
    "exit_3": b"import sys\nsys.exit(3)\n",
    "keyboard": b"raise KeyboardInterrupt\n",
    "print_then_raise": b"print('allow')\nraise ValueError('broken')\n",
}

GOOD_CALL = json.dumps(
    {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "echo held"},
    }
).encode()

CLAUDE_STUB = '''
"""Stub of the Claude program: records the call, then prints a planned stream."""
import json, sys
from pathlib import Path

here = Path(__file__).resolve().parent
with open(here / "calls.jsonl", "a", encoding="utf-8") as out:
    out.write(json.dumps({"argv": sys.argv[1:]}) + "\\n")
stream = here / "stream.jsonl"
if stream.exists():
    sys.stdout.buffer.write(stream.read_bytes())
    sys.stdout.buffer.flush()
'''

NOTIFY_STUB = '''
"""Stub of the notifier: records the call, then appends planned log lines."""
import json, sys
from pathlib import Path

here = Path(__file__).resolve().parent
argv = sys.argv[1:]
with open(here / "mails.jsonl", "a", encoding="utf-8") as out:
    out.write(json.dumps(argv) + "\\n")
plan = json.loads((here / "notify-plan.json").read_text(encoding="utf-8"))
cls = argv[argv.index("--class") + 1]
home = Path(argv[argv.index("--home") + 1])
log = home / "state" / "notify.log.jsonl"
log.parent.mkdir(parents=True, exist_ok=True)
with open(log, "a", encoding="utf-8", newline="\\n") as out:
    for line in plan["lines"]:
        out.write(json.dumps({"ts": "t", "class": cls, "harness": "manual", **line}) + "\\n")
'''

SCHTASKS_STUB = '''
"""Stub of schtasks: no task exists."""
import sys

sys.exit(1)
'''

READER = '''
"""Reads the pause with the parser of the hook until a stop file exists."""
import importlib.util, json, sys, time
from pathlib import Path

hook_path, home, out, ready, stop = sys.argv[1:6]
spec = importlib.util.spec_from_file_location("usage_guard_hook", hook_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
seq, ends, reads = [], set(), 0
while True:
    kind, end = mod.load_pause(home, now=time.time(), sleep=time.sleep)
    reads += 1
    if not seq or seq[-1] != kind:
        seq.append(kind)
    if kind == "on":
        ends.add(end)
    if reads == 1:
        Path(ready).write_text("1")
    if Path(stop).exists():
        break
    time.sleep(0.005)
Path(out).write_text(json.dumps({"seq": seq, "ends": sorted(ends), "reads": reads}))
'''


# ── Harness ─────────────────────────────────────────────────────────────


def _load(name: str, path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    assert path.is_file(), path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod: Any = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, mod)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def ug(monkeypatch: pytest.MonkeyPatch) -> Any:
    """The guard module, loaded from its path."""
    return _load("usage_guard", GUARD, monkeypatch)


@pytest.fixture
def hook(monkeypatch: pytest.MonkeyPatch) -> Any:
    """The hook module, loaded from its path, with a clean hook environment."""
    for key in HOOK_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    return _load("usage_guard_hook", HOOK, monkeypatch)


@pytest.fixture
def box(tmp_path: Path, hook: Any) -> Path:
    """A scratch home that holds the hook script. The path has no space."""
    folder = tmp_path / "box"
    folder.mkdir()
    (folder / "usage_guard_hook.py").write_bytes(HOOK.read_bytes())
    return folder


@pytest.fixture
def procs() -> Iterator[list[subprocess.Popen[bytes]]]:
    """Processes of a test. Each one that still runs at the end is killed."""
    started: list[subprocess.Popen[bytes]] = []
    yield started
    for proc in started:
        if proc.poll() is None:
            proc.kill()
        proc.communicate(timeout=30)


def _pause_doc(
    end_at: float, *, origin: str = "auto", started_at: float | None = None
) -> dict[str, Any]:
    return {
        "schema": "usage-guard-pause/1",
        "origin": origin,
        "started_at": end_at - 100 if started_at is None else started_at,
        "end_at": end_at,
        "windows": [],
    }


def _write_pause(home: Path, end_at: float, *, origin: str = "auto") -> bytes:
    raw = json.dumps(_pause_doc(end_at, origin=origin)).encode()
    (home / "pause.json").write_bytes(raw)
    return raw


def _clean_env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k.upper() not in HOOK_ENV_KEYS}
    env.update(extra)
    return env


def _entry_args(ug: Any, home: Path) -> list[str]:
    entry = ug.hook_entry(home.as_posix(), BASE_PY)
    return [entry["command"], *entry["args"]]


def _launcher_args(home: Path) -> list[str]:
    return [BASE_PY, "-I", "-S", "-c", LAUNCHER_TEXT, "--home", home.as_posix()]


def _start(
    args: list[str],
    stdin: bytes | None,
    procs: list[subprocess.Popen[bytes]],
    env: dict[str, str] | None = None,
) -> subprocess.Popen[bytes]:
    """Start one hook process. ``None`` keeps stdin open and writes nothing."""
    proc = subprocess.Popen(
        args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_clean_env() if env is None else env,
        creationflags=NO_WINDOW,
    )
    procs.append(proc)
    if stdin is not None:
        assert proc.stdin is not None
        proc.stdin.write(stdin)
        proc.stdin.close()
    return proc


def _run(
    args: list[str], stdin: bytes, env: dict[str, str] | None = None
) -> tuple[subprocess.CompletedProcess[bytes], float]:
    """Run one hook process that must end within the fail-open deadline."""
    began = time.monotonic()
    done = subprocess.run(
        args,
        input=stdin,
        capture_output=True,
        env=_clean_env() if env is None else env,
        timeout=FAIL_OPEN_S + 10,
        creationflags=NO_WINDOW,
    )
    return done, time.monotonic() - began


def _ended(proc: subprocess.Popen[bytes], limit: float) -> tuple[bytes, bytes]:
    """Wait for the end of a process: exit 0 within the limit. Returns its output."""
    out, err = proc.communicate(timeout=limit)
    assert proc.returncode == 0
    return out, err


class Clock:
    """A fake clock. Each sleep moves it and can run a step of the test."""

    def __init__(self, start: float = T0) -> None:
        self.t = start
        self.sleeps: list[float] = []
        self.on_sleep: Callable[[int], None] | None = None

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds
        if self.on_sleep is not None:
            self.on_sleep(len(self.sleeps))
        assert len(self.sleeps) < 10_000, "endless hold"


class FakeStdin:
    """Stdin of a hook call. ``touched`` tells whether the hook read it."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.touched = False

    @property
    def buffer(self) -> io.BytesIO:
        self.touched = True
        return io.BytesIO(self.data)


def _call(
    hook: Any,
    home: Path,
    stdin: bytes,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clock: Clock,
    *,
    poll: float = 5.0,
) -> tuple[int, str, FakeStdin]:
    """Call ``main`` of the hook in this process. Returns code, stdout and stdin."""
    fake = FakeStdin(stdin)
    monkeypatch.setattr(sys, "stdin", fake)
    capsys.readouterr()
    code = hook.main(
        ["-c", "--home", home.as_posix()], poll=poll, now=clock.now, sleep=clock.sleep
    )
    captured = capsys.readouterr()
    return code, captured.out + captured.err, fake


def _tool(name: str, **tool_input: Any) -> bytes:
    return json.dumps(
        {"hook_event_name": "PreToolUse", "tool_name": name, "tool_input": tool_input}
    ).encode()


def _event(
    windows: dict[str, Any],
    *,
    status: str = "allowed",
    overage: bool = False,
    limit_type: str = "five_hour",
) -> bytes:
    info = {
        "status": status,
        "rateLimitType": limit_type,
        "resetsAt": FIVE_RESET,
        "isUsingOverage": overage,
        "unifiedWindows": windows,
    }
    return (
        json.dumps({"type": "rate_limit_event", "rate_limit_info": info}).encode()
        + b"\n"
    )


def _win(utilization: float, resets_at: int = FIVE_RESET) -> dict[str, Any]:
    return {"utilization": utilization, "resetsAt": resets_at}


STREAMS: dict[str, bytes] = {
    "allowed": _event({"five_hour": _win(0.07), "seven_day": _win(0.21, SEVEN_RESET)}),
    "at_95": _event({"five_hour": _win(0.95), "seven_day": _win(0.21, SEVEN_RESET)}),
    "at_99": _event({"five_hour": _win(0.99), "seven_day": _win(0.21, SEVEN_RESET)}),
    "rejected": _event(
        {"five_hour": _win(0.42), "seven_day": _win(0.21, SEVEN_RESET)},
        status="rejected",
    ),
    "overage": _event(
        {"five_hour": _win(0.3), "seven_day": _win(0.21, SEVEN_RESET)}, overage=True
    ),
    "no_event": b'{"type": "result", "subtype": "success"}\n',
}


def _jsonl(path: Path) -> list[Any]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class Rig:
    """A scratch home of the guard with stubs. The home holds the hook script."""

    def __init__(self, base: Path, ug: Any, capsys: pytest.CaptureFixture[str]) -> None:
        self.ug = ug
        self.capsys = capsys
        self.home = base / "guard home"
        self.home.mkdir()
        (self.home / "usage_guard_hook.py").write_bytes(HOOK.read_bytes())
        self.bin = base / "stub bin"
        self.bin.mkdir()
        self.projects = base / "projects"
        self.transcript = self.projects / "p--x" / "s.jsonl"
        self.transcript.parent.mkdir(parents=True)
        self.transcript.write_text("{}\n", encoding="utf-8")
        self.account_file = base / "claude.json"
        self.account_file.write_text(
            json.dumps({"oauthAccount": {"accountUuid": "account-aaaa-0001"}}),
            encoding="utf-8",
        )
        self.notify_home = base / "notify home"
        (self.notify_home / "state").mkdir(parents=True)
        for name, text in (
            ("claude_stub.py", CLAUDE_STUB),
            ("notify_stub.py", NOTIFY_STUB),
            ("schtasks_stub.py", SCHTASKS_STUB),
        ):
            (self.bin / name).write_text(text, encoding="utf-8")
        self.plan([{"outcome": "sent"}])
        self.stream("allowed")
        os.utime(self.transcript, (T0, T0))

    def stream(self, name: str) -> None:
        self.raw(STREAMS[name])

    def raw(self, data: bytes) -> None:
        (self.bin / "stream.jsonl").write_bytes(data)

    def plan(self, lines: list[dict[str, Any]]) -> None:
        text = json.dumps({"lines": lines})
        (self.bin / "notify-plan.json").write_text(text, encoding="utf-8")

    def pause(self, *, end_at: float, origin: str) -> bytes:
        return _write_pause(self.home, end_at, origin=origin)

    def deps(self) -> Any:
        return self.ug.Deps(
            claude=(sys.executable, str(self.bin / "claude_stub.py")),
            account_file=self.account_file,
            projects=self.projects,
            notify_home=self.notify_home,
            notifier=(sys.executable, str(self.bin / "notify_stub.py")),
            schtasks=(sys.executable, str(self.bin / "schtasks_stub.py")),
        )

    def run(self, *argv: str, at: float = T0) -> tuple[int, str]:
        self.capsys.readouterr()
        code = self.ug.main(
            [*argv, "--home", str(self.home)],
            deps=self.deps(),
            now=lambda: at,
            sleep=lambda _s: None,
        )
        captured = self.capsys.readouterr()
        return code, captured.out + captured.err

    def read(self, name: str | None = None, *, at: float = T0) -> int:
        if name is not None:
            self.stream(name)
        return self.run("read", at=at)[0]

    def pause_doc(self) -> dict[str, Any] | None:
        path = self.home / "pause.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def pause_bytes(self) -> bytes | None:
        path = self.home / "pause.json"
        return path.read_bytes() if path.exists() else None

    def state(self) -> dict[str, Any]:
        return json.loads((self.home / "state.json").read_text(encoding="utf-8"))

    def mails(self, cls: str | None = None) -> list[str]:
        out = []
        for argv in _jsonl(self.bin / "mails.jsonl"):
            if cls is None or argv[argv.index("--class") + 1] == cls:
                out.append(argv[argv.index("--text") + 1])
        return out


@pytest.fixture
def rig(
    tmp_path: Path,
    ug: Any,
    hook: Any,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> Rig:
    for key in [k for k in os.environ if k.upper().startswith("AGENT_NOTIFY")]:
        monkeypatch.delenv(key, raising=False)
    return Rig(tmp_path, ug, capsys)


# ── AC-978.1: no pause ──────────────────────────────────────────────────

NO_PAUSE: dict[str, Callable[[Path], object]] = {
    "absent": lambda home: None,
    "ended": lambda home: _write_pause(home, T0 - 1),
    "ends_now": lambda home: _write_pause(home, T0),
    "far": lambda home: _write_pause(home, T0 + 691_200 + 1),
    "corrupt": lambda home: (home / "pause.json").write_bytes(b'{"schema": "usa'),
    "folder": lambda home: (home / "pause.json").mkdir(),
}


@pytest.mark.parametrize("kind", sorted(NO_PAUSE))
def test_f2p_978_01_no_pause_exits_at_once_without_reading_stdin(
    hook: Any,
    box: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    kind: str,
) -> None:
    NO_PAUSE[kind](box)
    clock = Clock()
    code, out, stdin = _call(hook, box, GOOD_CALL, monkeypatch, capsys, clock)
    assert code == 0
    assert out == ""
    assert stdin.touched is False
    assert sum(clock.sleeps) <= 0.11
    if kind == "absent":
        assert clock.sleeps == []


@pytest.mark.parametrize("entrypoint", ["", "sdk-cli", "claude-vscode"])
def test_f2p_978_01_process_with_open_stdin_exits_at_once(
    ug: Any, box: Path, procs: list[subprocess.Popen[bytes]], entrypoint: str
) -> None:
    env = _clean_env(CLAUDE_CODE_ENTRYPOINT=entrypoint) if entrypoint else None
    proc = _start(_entry_args(ug, box), None, procs, env)
    out, err = _ended(proc, FAIL_OPEN_S)
    assert out == b"" and err == b""


# ── AC-978.2: the hold ──────────────────────────────────────────────────


def test_f2p_978_02_holds_until_end_at(
    hook: Any,
    box: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_pause(box, T0 + 12)
    clock = Clock()
    code, out, stdin = _call(hook, box, GOOD_CALL, monkeypatch, capsys, clock)
    assert code == 0
    assert out == ""
    assert stdin.touched is True
    assert clock.sleeps == pytest.approx([5.0, 5.0, 2.0])
    assert clock.t >= T0 + 12


def test_f2p_978_02_each_sleep_is_bounded_by_the_poll(
    hook: Any,
    box: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_pause(box, T0 + 1)
    clock = Clock()
    code, out, _ = _call(hook, box, GOOD_CALL, monkeypatch, capsys, clock, poll=0.05)
    assert (code, out) == (0, "")
    assert len(clock.sleeps) >= 19
    assert max(clock.sleeps) <= 0.05 + 1e-9
    assert clock.t == pytest.approx(T0 + 1)


@pytest.mark.parametrize("change", ["removed", "ended", "corrupt"])
def test_f2p_978_02_a_changed_file_ends_the_hold(
    hook: Any,
    box: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    change: str,
) -> None:
    _write_pause(box, T0 + 600)
    clock = Clock()

    def step(count: int) -> None:
        if count != 2:
            return
        if change == "removed":
            (box / "pause.json").unlink()
        elif change == "ended":
            _write_pause(box, T0 + 1)
        else:
            (box / "pause.json").write_bytes(b"{")

    clock.on_sleep = step
    code, out, _ = _call(hook, box, GOOD_CALL, monkeypatch, capsys, clock)
    assert (code, out) == (0, "")
    assert clock.sleeps[:2] == [5.0, 5.0]
    assert len(clock.sleeps) <= 4
    assert clock.t < T0 + 30


def test_f2p_978_02_constants(hook: Any, ug: Any) -> None:
    assert hook.POLL_S == 5.0
    assert inspect.signature(hook.main).parameters["poll"].default == 5.0
    assert hook.STDIN_MAX == 64 * 1024 * 1024
    assert hook.PAUSE_MAX_S == ug.PAUSE_MAX_S == 691_200
    assert hook.PAUSE_FILE_MAX == ug.PAUSE_FILE_MAX == 4096
    assert hook.PAUSE_TRIES == ug.PAUSE_TRIES == 3


def test_f2p_978_02_process_exits_at_end_at_with_no_output(
    ug: Any, box: Path, procs: list[subprocess.Popen[bytes]]
) -> None:
    end_at = time.time() + 1.0
    _write_pause(box, end_at)
    proc = _start(_entry_args(ug, box), GOOD_CALL, procs)
    out, err = _ended(proc, 10)
    assert time.time() >= end_at
    assert out == b"" and err == b""


def test_f2p_978_02_process_exits_when_the_file_goes_away(
    ug: Any, box: Path, procs: list[subprocess.Popen[bytes]]
) -> None:
    _write_pause(box, time.time() + 600)
    proc = _start(_entry_args(ug, box), GOOD_CALL, procs)
    time.sleep(1.0)
    assert proc.poll() is None
    for _ in range(100):
        try:
            (box / "pause.json").unlink()
            break
        except PermissionError:
            time.sleep(0.02)
    gone = time.monotonic()
    out, err = _ended(proc, 10)
    assert time.monotonic() - gone < 10
    assert out == b"" and err == b""


# ── AC-978.3: fail open ─────────────────────────────────────────────────


def test_p2p_978_03_plain_form_of_a_missing_script_exits_2(tmp_path: Path) -> None:
    done, _ = _run([BASE_PY, "-I", "-S", str(tmp_path / "usage_guard_hook.py")], b"")
    assert done.returncode == 2


@pytest.mark.parametrize("script", sorted(BROKEN_SCRIPTS))
def test_p2p_978_03_launcher_text_fails_open(tmp_path: Path, script: str) -> None:
    (tmp_path / "pause.json").write_bytes(b'{"schema": "usage-guard-pause/1", "e')
    data = BROKEN_SCRIPTS[script]
    if data is not None:
        (tmp_path / "usage_guard_hook.py").write_bytes(data)
    done, spent = _run(_launcher_args(tmp_path), GOOD_CALL)
    assert done.returncode == 0
    assert done.stdout == b""
    assert spent < FAIL_OPEN_S


def test_f2p_978_03_guard_launcher_and_hook_entry(ug: Any, hook: Any) -> None:
    assert ug.LAUNCHER == LAUNCHER_TEXT
    entry = ug.hook_entry("/opt/agent/usage-guard", PY_DEFAULT)
    assert entry == {
        "type": "command",
        "command": PY_DEFAULT,
        "args": ["-I", "-S", "-c", LAUNCHER_TEXT, "--home", "/opt/agent/usage-guard"],
        "timeout": 691_200,
    }
    tree = ast.parse(HOOK.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert names
    assert "argparse" not in names
    assert names <= set(sys.stdlib_module_names) | {"__future__"}


def _lock_file(path: Path) -> Callable[[], None]:
    """Make the file unreadable for another process. Returns the undo."""
    if sys.platform == "win32":
        import msvcrt

        handle = open(path, "r+b")  # noqa: SIM115 - held until the undo
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, path.stat().st_size)

        def undo() -> None:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, path.stat().st_size)
            handle.close()

        return undo
    path.chmod(0)
    return lambda: path.chmod(0o600)


BAD_FILES: dict[str, Callable[[Path, float], bytes | None]] = {
    "corrupt": lambda p, now: b'{"schema": "usage-guard-pause/1", "end_at": 9',
    "empty": lambda p, now: b"",
    "oversized": lambda p, now: (
        json.dumps(_pause_doc(now + 600)).encode() + b" " * 4096
    ),
    "far_end": lambda p, now: json.dumps(_pause_doc(now + 691_200 + 600)).encode(),
    "folder": lambda p, now: None,
    "locked": lambda p, now: json.dumps(_pause_doc(now + 600)).encode(),
}


@pytest.mark.parametrize("kind", sorted(BAD_FILES))
def test_f2p_978_03_bad_pause_file_fails_open(ug: Any, box: Path, kind: str) -> None:
    path = box / "pause.json"
    data = BAD_FILES[kind](path, time.time())
    if data is None:
        path.mkdir()
    else:
        path.write_bytes(data)
    undo = _lock_file(path) if kind == "locked" else None
    try:
        done, spent = _run(_entry_args(ug, box), GOOD_CALL)
    finally:
        if undo is not None:
            undo()
    assert done.returncode == 0
    assert done.stdout == b"" and done.stderr == b""
    assert spent < FAIL_OPEN_S


@pytest.mark.parametrize("script", sorted(BROKEN_SCRIPTS))
def test_f2p_978_03_broken_script_fails_open_with_a_pause_on(
    ug: Any, box: Path, script: str
) -> None:
    _write_pause(box, time.time() + 600)
    data = BROKEN_SCRIPTS[script]
    if data is None:
        (box / "usage_guard_hook.py").unlink()
    else:
        (box / "usage_guard_hook.py").write_bytes(data)
    done, spent = _run(_entry_args(ug, box), GOOD_CALL)
    assert done.returncode == 0
    assert done.stdout == b""
    assert spent < FAIL_OPEN_S


BAD_STDIN = {
    "not_json": b"not json",
    "list": b"[]",
    "number": b"1",
    "text": b'"call"',
    "empty": b"",
    "bad_utf8": b'{"tool_name": "\xff\xfe"}',
    "deep": b"[" * 100_000,
}


@pytest.mark.parametrize("kind", sorted(BAD_STDIN))
def test_f2p_978_03_bad_stdin_fails_open_with_a_pause_on(
    ug: Any, box: Path, kind: str
) -> None:
    _write_pause(box, time.time() + 600)
    done, spent = _run(_entry_args(ug, box), BAD_STDIN[kind])
    assert done.returncode == 0
    assert done.stdout == b"" and done.stderr == b""
    assert spent < FAIL_OPEN_S


def test_f2p_978_03_good_call_is_held_past_the_deadline(
    ug: Any, box: Path, procs: list[subprocess.Popen[bytes]]
) -> None:
    _write_pause(box, time.time() + 600)
    good = _start(_entry_args(ug, box), GOOD_CALL, procs)
    bad = _start(_entry_args(ug, box), b"not json", procs)
    _ended(bad, FAIL_OPEN_S)
    time.sleep(FAIL_OPEN_S)
    assert good.poll() is None


@pytest.mark.parametrize("kind", sorted(BAD_STDIN))
def test_f2p_978_03_bad_stdin_starts_no_wait(
    hook: Any,
    box: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    kind: str,
) -> None:
    _write_pause(box, T0 + 600)
    clock = Clock()
    code, out, _ = _call(hook, box, BAD_STDIN[kind], monkeypatch, capsys, clock)
    assert (code, out) == (0, "")
    assert clock.sleeps == []


def test_f2p_978_03_stdin_above_the_limit_starts_no_wait(
    hook: Any,
    box: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_pause(box, T0 + 600)
    monkeypatch.setattr(hook, "STDIN_MAX", len(GOOD_CALL) - 1)
    clock = Clock()
    code, out, _ = _call(hook, box, GOOD_CALL, monkeypatch, capsys, clock)
    assert (code, out) == (0, "")
    assert clock.sleeps == []
    monkeypatch.setattr(hook, "STDIN_MAX", len(GOOD_CALL))
    _write_pause(box, T0 + 1)
    code, out, _ = _call(hook, box, GOOD_CALL, monkeypatch, capsys, Clock())
    assert (code, out) == (0, "")


def test_f2p_978_03_main_never_raises(
    hook: Any,
    box: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_pause(box, T0 + 600)
    monkeypatch.setattr(sys, "stdin", FakeStdin(GOOD_CALL))
    for argv in ([], ["-c"], ["-c", "--home"]):
        assert hook.main(argv, now=Clock().now, sleep=Clock().sleep) == 0

    def broken() -> float:
        raise RuntimeError("clock")

    assert hook.main(["-c", "--home", box.as_posix()], now=broken) == 0
    calls: list[float] = []

    def failing_sleep(seconds: float) -> None:
        calls.append(seconds)
        raise OSError("sleep")

    assert (
        hook.main(["-c", "--home", box.as_posix()], now=lambda: T0, sleep=failing_sleep)
        == 0
    )
    assert calls == [5.0]
    assert capsys.readouterr().out == ""


def _agreement_cases() -> dict[str, bytes | None]:
    def doc(**over: Any) -> bytes:
        base = _pause_doc(T0 + 600, origin="user", started_at=T0 - 10)
        base["windows"] = [{"name": "five_hour", "reset": FIVE_RESET}]
        base.update(over)
        return json.dumps(base).encode()

    window = {"name": "five_hour", "reset": FIVE_RESET}
    return {
        "missing": None,
        "valid_user": doc(),
        "valid_auto": doc(origin="auto"),
        "account_window": doc(windows=[{"name": "account", "reset": FIVE_RESET}]),
        "ended": doc(end_at=T0 - 1),
        "ends_now": doc(end_at=T0),
        "at_the_far_bound": doc(end_at=T0 + 691_200),
        "beyond_the_far_bound": doc(end_at=T0 + 691_200.5),
        "integer_end": doc(end_at=int(T0) + 600),
        "extra_key": doc(extra=1),
        "missing_key": json.dumps({"schema": "usage-guard-pause/1"}).encode(),
        "other_schema": doc(schema="usage-guard-pause/2"),
        "other_origin": doc(origin="other"),
        "bool_end": doc(end_at=True),
        "text_end": doc(end_at="soon"),
        "nan_end": doc().replace(str(T0 + 600).encode(), b"NaN"),
        "infinity_end": doc().replace(str(T0 + 600).encode(), b"Infinity"),
        "huge_end": doc().replace(str(T0 + 600).encode(), b"1" + b"0" * 400),
        "huge_float": doc().replace(str(T0 + 600).encode(), b"1e400"),
        "bad_window_name": doc(windows=[{"name": "seven_day_opus", "reset": 1}]),
        "bool_reset": doc(windows=[{"name": "five_hour", "reset": True}]),
        "big_reset": doc(windows=[{"name": "five_hour", "reset": 10**12 + 1}]),
        "float_reset": doc(windows=[{"name": "five_hour", "reset": 1.5}]),
        "window_extra": doc(windows=[{**window, "x": 1}]),
        "many_windows": doc(windows=[window] * 65),
        "windows_not_list": doc(windows={}),
        "oversized": doc() + b" " * 4096,
        "at_the_size": doc() + b" " * (4096 - len(doc())),
        "bad_utf8": b"\xff" + doc(),
        "utf8_bom": b"\xef\xbb\xbf" + doc(),
        "list": b"[]",
        "brace": b"{",
        "empty": b"",
        "deep": b"[" * 3000 + b"]" * 3000,
    }


def test_f2p_978_03_hook_parser_agrees_with_the_guard(
    hook: Any, ug: Any, tmp_path: Path
) -> None:
    kinds: dict[str, str] = {}
    for name, data in _agreement_cases().items():
        home = tmp_path / name
        home.mkdir()
        if data is not None:
            (home / "pause.json").write_bytes(data)
        guard = ug.load_pause(home, now=T0, sleep=lambda _s: None).kind
        kind, end = hook.load_pause(home.as_posix(), now=T0, sleep=lambda _s: None)
        assert kind == guard, name
        kinds[name] = kind
        if kind == "on":
            assert end == pytest.approx(json.loads(data or b"")["end_at"])
    folder = tmp_path / "folder"
    (folder / "pause.json").mkdir(parents=True)
    assert hook.load_pause(folder.as_posix(), now=T0, sleep=lambda _s: None)[0] == (
        ug.load_pause(folder, now=T0, sleep=lambda _s: None).kind
    )
    assert kinds["valid_user"] == kinds["at_the_far_bound"] == "on"
    assert kinds["ended"] == kinds["ends_now"] == "ended"
    assert kinds["missing"] == "none"
    assert kinds["beyond_the_far_bound"] == kinds["extra_key"] == "bad"


# ── AC-978.4: the calls that pass ───────────────────────────────────────

PASS_FORMS = {
    "status": ("Bash", "{py} {home}/usage_guard.py status --home {home}"),
    "isolated": ("Bash", "{py} -I {home}/usage_guard.py status --json --home {home}"),
    "rtk": ("Bash", "rtk proxy {py} -I {home}/usage_guard.py read --home {home}"),
    "pause_hours": ("Bash", "{py} -I {home}/usage_guard.py pause --hours 2.5"),
    "resume_redirect": (
        "Bash",
        "{py} -I {home}/usage_guard.py resume --home {home} > C:/Temp/r.txt 2>&1",
    ),
    "powershell_redirect": (
        "PowerShell",
        "rtk proxy {py} -I {home}/usage_guard.py status *> C:/Temp/receipts/s.txt",
    ),
    "backslashes": ("Bash", "{pyb} -I {homeb}\\usage_guard.py resume"),
    "own_python": ("Bash", "{own} -I {home}/usage_guard.py status"),
}

HELD_FORMS = {
    "chained": "{py} -I {home}/usage_guard.py resume; other",
    "and": "{py} -I {home}/usage_guard.py resume && other",
    "background": "{py} -I {home}/usage_guard.py resume & other",
    "pipe": "{py} -I {home}/usage_guard.py status | other",
    "subshell": "{py} -I {home}/usage_guard.py status $(other)",
    "variable": "{py} -I {home}/usage_guard.py status --home $HOME",
    "backtick": "{py} -I {home}/usage_guard.py status `other`",
    "newline": "{py} -I {home}/usage_guard.py status\nother",
    "other_path": "{py} -I C:/other/usage_guard.py status",
    "other_script": "{py} -I {home}/usage_guard_hook.py status",
    "longer_name": "{py} -I {home}/usage_guard.py.bak status",
    "other_python": "C:/other/python.exe -I {home}/usage_guard.py status",
    "install": "{py} -I {home}/usage_guard.py install --part hook",
    "uninstall": "{py} -I {home}/usage_guard.py uninstall --part hook",
    "no_verb": "{py} -I {home}/usage_guard.py",
    "quoted": '{py} -I {home}/usage_guard.py status --home "{home}"',
    "redirect_subshell": "{py} -I {home}/usage_guard.py status > $(other).txt 2>&1",
    "two_redirects": "{py} {home}/usage_guard.py status > a.txt 2>&1 > b.txt 2>&1",
    "rtk_twice": "rtk proxy rtk proxy {py} {home}/usage_guard.py status",
    "other_first": "other {py} {home}/usage_guard.py status",
    "echo": "echo held",
}


def _form(text: str, home: Path) -> str:
    return text.format(
        py=PY_DEFAULT,
        pyb=PY_DEFAULT.replace("/", "\\"),
        own=Path(sys.executable).as_posix(),
        home=home.as_posix(),
        homeb=str(home).replace("/", "\\"),
    )


@pytest.mark.parametrize("name", sorted(PASS_FORMS))
def test_f2p_978_04_guard_command_passes(hook: Any, box: Path, name: str) -> None:
    tool, text = PASS_FORMS[name]
    call = json.loads(_tool(tool, command=_form(text, box)))
    assert hook.passes(call, box.as_posix()) is True


@pytest.mark.parametrize(
    "call",
    [
        {"tool_name": "Read", "tool_input": {"file_path": SKILL_PATH}},
        {
            "tool_name": "Read",
            "tool_input": {"file_path": SKILL_PATH.replace("/", "\\"), "limit": 50},
        },
        {"tool_name": "Skill", "tool_input": {"skill": "usage-guard"}},
    ],
)
def test_f2p_978_04_skill_calls_pass(
    hook: Any, box: Path, call: dict[str, Any]
) -> None:
    assert hook.passes(call, box.as_posix()) is True


@pytest.mark.parametrize("name", sorted(HELD_FORMS))
def test_f2p_978_04_other_commands_are_held(hook: Any, box: Path, name: str) -> None:
    command = _form(HELD_FORMS[name], box)
    for tool in ("Bash", "PowerShell"):
        call = json.loads(_tool(tool, command=command))
        assert hook.passes(call, box.as_posix()) is False


@pytest.mark.parametrize(
    "call",
    [
        {"tool_name": "Write", "tool_input": {"command": "{py} {home}/usage_guard.py"}},
        {"tool_name": "bash", "tool_input": {"command": "{status}"}},
        {"tool_name": "Bash", "tool_input": {"command": ["{status}"]}},
        {"tool_name": "Bash", "tool_input": "{status}"},
        {"tool_name": "Bash"},
        {"tool_input": {"command": "{status}"}},
        {"tool_name": "Read", "tool_input": {"file_path": SKILL_PATH + ".bak"}},
        {
            "tool_name": "Read",
            "tool_input": {"file_path": "/work/project/.agent/skills/other/SKILL.md"},
        },
        {"tool_name": "Read", "tool_input": {"file_path": 1}},
        {"tool_name": "Skill", "tool_input": {"skill": "usage-guard-x"}},
        {"tool_name": "Skill", "tool_input": {"skill": "other"}},
        {"tool_name": "Task", "tool_input": {"prompt": "usage-guard"}},
    ],
)
def test_f2p_978_04_other_calls_are_held(
    hook: Any, box: Path, call: dict[str, Any]
) -> None:
    status = _form("{py} {home}/usage_guard.py status", box)
    text = json.dumps(call).replace("{status}", status.replace("\\", "\\\\"))
    text = text.replace("{py}", PY_DEFAULT).replace("{home}", box.as_posix())
    assert hook.passes(json.loads(text), box.as_posix()) is False


def test_f2p_978_04_pass_call_ends_at_once_and_other_call_waits(
    hook: Any,
    box: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_pause(box, T0 + 12)
    status = _tool("Bash", command=_form(PASS_FORMS["status"][1], box))
    clock = Clock()
    assert _call(hook, box, status, monkeypatch, capsys, clock)[:2] == (0, "")
    assert clock.sleeps == []
    chained = _tool("Bash", command=_form(HELD_FORMS["chained"], box))
    clock = Clock()
    assert _call(hook, box, chained, monkeypatch, capsys, clock)[:2] == (0, "")
    assert sum(clock.sleeps) == pytest.approx(12)


def test_f2p_978_04_process_pass_and_hold(
    ug: Any, box: Path, procs: list[subprocess.Popen[bytes]]
) -> None:
    _write_pause(box, time.time() + 600)
    args = _entry_args(ug, box)
    held = {
        name: _start(args, _tool("Bash", command=_form(HELD_FORMS[name], box)), procs)
        for name in ("chained", "pipe", "subshell", "newline", "other_path")
    }
    for name in ("status", "powershell_redirect", "resume_redirect"):
        tool, text = PASS_FORMS[name]
        done, spent = _run(args, _tool(tool, command=_form(text, box)))
        assert (done.returncode, done.stdout, done.stderr) == (0, b"", b""), name
        assert spent < FAIL_OPEN_S, name
    for call in (
        _tool("Read", file_path=SKILL_PATH),
        _tool("Skill", skill="usage-guard"),
    ):
        done, spent = _run(args, call)
        assert (done.returncode, done.stdout) == (0, b"")
        assert spent < FAIL_OPEN_S
    time.sleep(HELD_S)
    for name, proc in held.items():
        assert proc.poll() is None, name


# ── AC-978.5: runs with an API key ──────────────────────────────────────


@pytest.mark.parametrize("key", API_KEYS)
def test_f2p_978_05_api_run_passes(
    hook: Any,
    box: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    key: str,
) -> None:
    _write_pause(box, T0 + 600)
    monkeypatch.setenv(key, "1")
    assert hook.api_run(os.environ) is True
    clock = Clock()
    code, out, _ = _call(hook, box, GOOD_CALL, monkeypatch, capsys, clock)
    assert (code, out) == (0, "")
    assert clock.sleeps == []


@pytest.mark.parametrize("key", API_KEYS)
def test_f2p_978_05_empty_value_is_held(
    hook: Any,
    box: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    key: str,
) -> None:
    _write_pause(box, T0 + 12)
    monkeypatch.setenv(key, "")
    assert hook.api_run(os.environ) is False
    assert hook.api_run({}) is False
    clock = Clock()
    code, out, _ = _call(hook, box, GOOD_CALL, monkeypatch, capsys, clock)
    assert (code, out) == (0, "")
    assert sum(clock.sleeps) == pytest.approx(12)


def test_f2p_978_05_process_api_run(
    ug: Any, box: Path, procs: list[subprocess.Popen[bytes]]
) -> None:
    _write_pause(box, time.time() + 600)
    args = _entry_args(ug, box)
    empty = _start(args, GOOD_CALL, procs, _clean_env(ANTHROPIC_API_KEY=""))
    done, spent = _run(args, GOOD_CALL, _clean_env(ANTHROPIC_API_KEY="planted"))
    assert (done.returncode, done.stdout, done.stderr) == (0, b"", b"")
    assert spent < FAIL_OPEN_S
    time.sleep(HELD_S)
    assert empty.poll() is None


# ── AC-978.6: a high reading starts an auto pause ───────────────────────

HIGH_CASES: dict[str, tuple[bytes, float, list[dict[str, Any]]]] = {
    "at_99": (
        STREAMS["at_99"],
        FIVE_RESET + 60,
        [{"name": "five_hour", "reset": FIVE_RESET}],
    ),
    "rejected": (
        STREAMS["rejected"],
        FIVE_RESET + 60,
        [{"name": "five_hour", "reset": FIVE_RESET}],
    ),
    "two_windows": (
        _event({"five_hour": _win(0.99), "seven_day": _win(1.0, SEVEN_RESET)}),
        SEVEN_RESET + 60,
        [
            {"name": "five_hour", "reset": FIVE_RESET},
            {"name": "seven_day", "reset": SEVEN_RESET},
        ],
    ),
    "seven_day_only": (
        _event({"five_hour": _win(0.5), "seven_day": _win(0.995, SEVEN_RESET)}),
        SEVEN_RESET + 60,
        [{"name": "seven_day", "reset": SEVEN_RESET}],
    ),
    "overage": (
        STREAMS["overage"],
        SEVEN_RESET + 60,
        [{"name": "account", "reset": SEVEN_RESET}],
    ),
    "eight_day_cap": (
        _event({"seven_day": _win(0.99, int(T0) + 691_200)}),
        T0 + 691_200,
        [{"name": "seven_day", "reset": int(T0) + 691_200}],
    ),
}


@pytest.mark.parametrize("case", sorted(HIGH_CASES))
def test_f2p_978_06_high_starts_an_auto_pause(rig: Rig, case: str) -> None:
    data, end_at, windows = HIGH_CASES[case]
    rig.raw(data)
    assert rig.read() == 0
    doc = rig.pause_doc()
    assert doc is not None
    assert doc["schema"] == "usage-guard-pause/1"
    assert doc["origin"] == "auto"
    assert doc["started_at"] == T0
    assert doc["end_at"] == pytest.approx(end_at)
    assert sorted(doc["windows"], key=lambda w: w["name"]) == windows
    assert len((rig.home / "pause.json").read_bytes()) <= 4096
    assert rig.ug.load_pause(rig.home, now=T0).kind == "on"


def test_f2p_978_06_overage_without_a_current_window_ends_after_5_hours(
    rig: Rig,
) -> None:
    rig.raw(_event({"five_hour": _win(0.3, int(T0) - 100)}, overage=True))
    assert rig.read() == 0
    doc = rig.pause_doc()
    assert doc is not None
    assert doc["origin"] == "auto"
    assert doc["end_at"] == pytest.approx(T0 + 18_000)


def test_f2p_978_06_starts_one_time(rig: Rig) -> None:
    assert rig.read("at_99") == 0
    first = rig.pause_bytes()
    assert first is not None
    assert rig.read("at_99", at=T0 + 600) == 0
    rig.raw(_event({"five_hour": _win(1.2), "seven_day": _win(0.99, SEVEN_RESET)}))
    assert rig.read(at=T0 + 1200) == 0
    assert rig.pause_bytes() == first


@pytest.mark.parametrize("value", [0.9899, 0.97, 0.95, 0.07])
def test_f2p_978_06_under_99_starts_none(rig: Rig, value: float) -> None:
    rig.raw(_event({"five_hour": _win(value), "seven_day": _win(0.9899, SEVEN_RESET)}))
    assert rig.read() == 0
    assert rig.pause_bytes() is None
    assert rig.read("at_99", at=T0 + 600) == 0
    assert rig.pause_bytes() is not None


@pytest.mark.parametrize("before", ["none", "ended"])
def test_f2p_978_06_failed_reading_starts_none(rig: Rig, before: str) -> None:
    assert rig.read("at_99") == 0
    (rig.home / "pause.json").unlink()
    if before == "ended":
        rig.pause(end_at=T0 + 100, origin="auto")
    old = rig.pause_bytes()
    assert rig.read("no_event", at=T0 + 600) != 0
    assert rig.pause_bytes() == old


def test_f2p_978_06_user_pause_is_kept_at_high(rig: Rig) -> None:
    raw = rig.pause(end_at=T0 + 900, origin="user")
    assert rig.read("at_99") == 0
    assert rig.pause_bytes() == raw


@pytest.mark.parametrize(
    "raw", [b"{", b"[]", json.dumps(_pause_doc(T0 + 691_200 + 900)).encode()]
)
def test_f2p_978_06_bad_file_is_replaced_at_high(rig: Rig, raw: bytes) -> None:
    (rig.home / "pause.json").write_bytes(raw)
    assert rig.read("at_99") == 0
    doc = rig.pause_doc()
    assert doc is not None
    assert (doc["origin"], doc["end_at"]) == ("auto", FIVE_RESET + 60)


def test_f2p_978_06_decide(ug: Any, hook: Any) -> None:
    high = ug.parse_stream(STREAMS["at_99"], now=T0)
    low = ug.parse_stream(STREAMS["allowed"], now=T0)
    start = ug.decide(ug.State(), high, ug.PauseView("none"), now=T0)
    assert start.action == "start"
    assert start.pause.origin == "auto"
    assert start.pause.end_at == FIVE_RESET + 60
    assert start.pause.windows == (ug.WindowKey("five_hour", FIVE_RESET),)
    assert ug.decide(ug.State(), low, ug.PauseView("none"), now=T0).action == "none"
    user = ug.Pause(origin="user", started_at=T0, end_at=T0 + 60, windows=())
    on = ug.PauseView("on", user)
    assert ug.decide(ug.State(), high, on, now=T0).action == "none"
    assert ug.decide(ug.State(), low, on, now=T0).action == "none"
    suppressed = ug.State(suppressed=[ug.WindowKey("five_hour", FIVE_RESET + 300)])
    assert ug.decide(suppressed, high, ug.PauseView("none"), now=T0).action == "none"


@pytest.mark.parametrize(
    ("value", "high", "low"),
    [(0.9899, False, False), (0.99, True, False), (0.95, False, False)],
)
def test_p2p_978_06_thresholds_of_the_guard(
    ug: Any, value: float, high: bool, low: bool
) -> None:
    reading = ug.parse_stream(_event({"five_hour": _win(value)}), now=T0)
    assert (ug.is_high(reading), ug.is_low(reading)) == (high, low)
    low_reading = ug.parse_stream(_event({"five_hour": _win(0.9499)}), now=T0)
    assert ug.is_low(low_reading) is True
    rejected = ug.parse_stream(STREAMS["rejected"], now=T0)
    assert (ug.is_high(rejected), ug.is_low(rejected)) == (True, False)


# ── AC-978.7: the end of a pause ────────────────────────────────────────


@pytest.mark.parametrize("value", [0.07, 0.9499])
def test_f2p_978_07_low_ends_an_auto_pause(rig: Rig, value: float) -> None:
    assert rig.read("at_99") == 0
    assert rig.pause_bytes() is not None
    rig.raw(_event({"five_hour": _win(value), "seven_day": _win(0.21, SEVEN_RESET)}))
    assert rig.read(at=T0 + 600) == 0
    assert rig.pause_bytes() is None
    assert rig.ug.load_pause(rig.home, now=T0 + 600).kind == "none"


@pytest.mark.parametrize("name", ["at_95", "at_97", "rejected", "overage"])
def test_f2p_978_07_not_low_keeps_an_auto_pause(rig: Rig, name: str) -> None:
    assert rig.read("at_99") == 0
    before = rig.pause_bytes()
    if name == "at_97":
        rig.raw(_event({"five_hour": _win(0.97)}))
    else:
        rig.stream(name)
    assert rig.read(at=T0 + 600) == 0
    assert rig.pause_bytes() == before


def test_f2p_978_07_failed_reading_keeps_an_auto_pause(rig: Rig) -> None:
    assert rig.read("at_99") == 0
    before = rig.pause_bytes()
    assert rig.read("no_event", at=T0 + 600) != 0
    assert rig.pause_bytes() == before


def test_f2p_978_07_user_pause_does_not_end_by_a_reading(rig: Rig) -> None:
    raw = rig.pause(end_at=T0 + 3600, origin="user")
    for step in range(3):
        assert rig.read("allowed", at=T0 + 600 * step) == 0
    assert rig.pause_bytes() == raw


@pytest.mark.parametrize("origin", ["auto", "user"])
def test_f2p_978_07_end_time_ends_each_pause(rig: Rig, origin: str) -> None:
    rig.pause(end_at=T0 + 100, origin=origin)
    rig.raw(_event({"five_hour": _win(0.97)}))
    assert rig.read(at=T0 + 200) == 0
    assert rig.pause_bytes() is None


def test_f2p_978_07_ended_pause_and_high_start_a_new_pause(rig: Rig) -> None:
    rig.pause(end_at=T0 + 100, origin="user")
    assert rig.read("at_99", at=T0 + 200) == 0
    doc = rig.pause_doc()
    assert doc is not None
    assert (doc["origin"], doc["started_at"]) == ("auto", T0 + 200)


@pytest.mark.parametrize(
    ("end_at", "kind"),
    [(T0, "ended"), (T0 + 691_200, "on"), (T0 + 691_200.5, "bad")],
)
def test_p2p_978_07_pause_kinds_of_the_guard(
    ug: Any, tmp_path: Path, end_at: float, kind: str
) -> None:
    _write_pause(tmp_path, end_at)
    assert ug.load_pause(tmp_path, now=T0, sleep=lambda _s: None).kind == kind


# ── AC-978.8: pause and resume ──────────────────────────────────────────


@pytest.mark.parametrize(
    ("hours", "seconds"),
    [(None, 18_000), ("2", 7200), ("0.02", 72), ("192", 691_200), ("1.5", 5400)],
)
def test_f2p_978_08_pause_by_the_user(
    rig: Rig, hours: str | None, seconds: float
) -> None:
    argv = ["pause"] if hours is None else ["pause", "--hours", hours]
    code, out = rig.run(*argv)
    assert code == 0, out
    doc = rig.pause_doc()
    assert doc is not None
    assert doc["origin"] == "user"
    assert doc["started_at"] == T0
    assert doc["end_at"] == pytest.approx(T0 + seconds)
    assert doc["windows"] == []
    assert rig.ug.load_pause(rig.home, now=T0).kind == "on"


@pytest.mark.parametrize(
    "hours", ["0.019", "192.01", "0", "-1", "nan", "inf", "x", "", "1e3"]
)
def test_f2p_978_08_pause_out_of_range_exits_2(rig: Rig, hours: str) -> None:
    with pytest.raises(SystemExit) as caught:
        rig.ug.main(
            ["pause", "--hours", hours, "--home", str(rig.home)],
            deps=rig.deps(),
            now=lambda: T0,
        )
    assert caught.value.code == 2
    assert rig.pause_bytes() is None
    assert not (rig.home / "state.json").exists()


def test_f2p_978_08_pause_replaces_an_auto_pause(rig: Rig) -> None:
    assert rig.read("at_99") == 0
    assert rig.run("pause", "--hours", "1", at=T0 + 10)[0] == 0
    doc = rig.pause_doc()
    assert doc is not None
    assert (doc["origin"], doc["end_at"]) == ("user", T0 + 10 + 3600)


def test_f2p_978_08_resume_suppresses_the_window_until_a_new_one(rig: Rig) -> None:
    assert rig.read("at_99") == 0
    assert rig.pause_bytes() is not None
    code, out = rig.run("resume", at=T0 + 10)
    assert code == 0, out
    assert rig.pause_bytes() is None
    assert {"name": "five_hour", "reset": FIVE_RESET} in rig.state()["suppressed"]
    assert rig.read("at_99", at=T0 + 600) == 0
    assert rig.pause_bytes() is None
    rig.raw(_event({"five_hour": _win(1.0, FIVE_RESET + 600)}))
    assert rig.read(at=T0 + 1200) == 0
    assert rig.pause_bytes() is None
    rig.raw(_event({"five_hour": _win(0.99, FIVE_RESET + 18_000)}))
    assert rig.read(at=T0 + 1800) == 0
    doc = rig.pause_doc()
    assert doc is not None
    assert doc["origin"] == "auto"
    assert doc["end_at"] == FIVE_RESET + 18_000 + 60


@pytest.mark.parametrize("name", ["rejected", "overage"])
def test_f2p_978_08_resume_suppresses_a_limit_without_a_full_window(
    rig: Rig, name: str
) -> None:
    assert rig.read(name) == 0
    assert rig.pause_bytes() is not None
    assert rig.run("resume", at=T0 + 10)[0] == 0
    assert rig.read(name, at=T0 + 600) == 0
    assert rig.pause_bytes() is None


def test_f2p_978_08_user_pause_after_resume(rig: Rig) -> None:
    assert rig.read("at_99") == 0
    assert rig.run("resume", at=T0 + 10)[0] == 0
    assert rig.run("pause", "--hours", "1", at=T0 + 20)[0] == 0
    doc = rig.pause_doc()
    assert doc is not None
    assert doc["origin"] == "user"
    assert rig.read("allowed", at=T0 + 600) == 0
    assert rig.pause_doc() == doc


@pytest.mark.parametrize("before", ["none", "user", "bad"])
def test_f2p_978_08_resume_clears_each_pause(rig: Rig, before: str) -> None:
    if before == "user":
        rig.pause(end_at=T0 + 600, origin="user")
    elif before == "bad":
        (rig.home / "pause.json").write_bytes(b"{")
    code, out = rig.run("resume")
    assert code == 0, out
    assert rig.pause_bytes() is None


def test_f2p_978_08_status_shows_the_user_pause(rig: Rig) -> None:
    assert rig.run("pause", "--hours", "2")[0] == 0
    code, out = rig.run("status", "--json", at=T0 + 5)
    assert code == 0
    data = json.loads(out)
    assert data["pause"] == "user"
    assert data["pause_end_at"] == pytest.approx(T0 + 7200)


def test_f2p_978_08_terminal_commands(rig: Rig) -> None:
    script = rig.home / "usage_guard.py"
    script.write_bytes(GUARD.read_bytes())
    base = [BASE_PY, "-I", str(script)]
    home = ["--home", str(rig.home)]
    pause = subprocess.run(
        [*base, "pause", "--hours", "1", *home],
        capture_output=True,
        timeout=60,
        creationflags=NO_WINDOW,
    )
    assert pause.returncode == 0, pause.stdout + pause.stderr
    doc = rig.pause_doc()
    assert doc is not None
    assert doc["origin"] == "user"
    assert doc["end_at"] - doc["started_at"] == pytest.approx(3600)
    bad = subprocess.run(
        [*base, "pause", "--hours", "200", *home],
        capture_output=True,
        timeout=60,
        creationflags=NO_WINDOW,
    )
    assert bad.returncode == 2
    resume = subprocess.run(
        [*base, "resume", *home],
        capture_output=True,
        timeout=60,
        creationflags=NO_WINDOW,
    )
    assert resume.returncode == 0, resume.stdout + resume.stderr
    assert rig.pause_bytes() is None


# ── AC-978.9: atomic writes while hooks read ────────────────────────────


def test_f2p_978_09_atomic_with_ten_readers(
    ug: Any, box: Path, procs: list[subprocess.Popen[bytes]]
) -> None:
    base = time.time() + 600

    def pause(end_at: float) -> Any:
        return ug.Pause(
            origin="auto",
            started_at=end_at - 600,
            end_at=end_at,
            windows=(ug.WindowKey("five_hour", int(end_at)),),
        )

    ug.write_pause(box, pause(base))
    written = {base}
    reader = box.parent / "reader.py"
    reader.write_text(READER, encoding="utf-8")
    stop = box.parent / "stop"
    outs = [box.parent / f"out-{n}.json" for n in range(10)]
    ready = [box.parent / f"ready-{n}" for n in range(10)]
    for out, flag in zip(outs, ready, strict=True):
        args = [
            BASE_PY,
            "-B",
            "-I",
            "-S",
            str(reader),
            str(box / "usage_guard_hook.py"),
        ]
        _start([*args, box.as_posix(), str(out), str(flag), str(stop)], b"", procs)
    calls = [_start(_entry_args(ug, box), GOOD_CALL, procs) for _ in range(10)]
    limit = time.monotonic() + 30
    while not all(flag.exists() for flag in ready):
        assert time.monotonic() < limit, "readers did not start"
        time.sleep(0.02)
    for step in range(200):
        end_at = base + step + 1
        ug.write_pause(box, pause(end_at))
        written.add(end_at)
    for proc in calls:
        assert proc.poll() is None, "a call leaked during the replaces"
    ug.clear_pause(box)
    assert not (box / "pause.json").exists()
    for proc in calls:
        out, _ = _ended(proc, 15)
        assert out == b""
    time.sleep(0.2)
    stop.write_text("1")
    for proc in procs[:10]:
        proc.communicate(timeout=30)
    for out in outs:
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["seq"] == ["on", "none"], data["seq"]
        assert data["reads"] >= 20
        assert set(data["ends"]) <= written
    assert [p.name for p in box.iterdir()] == ["usage_guard_hook.py"]


# ── AC-978.10: the emails of the hold ───────────────────────────────────


@pytest.mark.parametrize("name", ["at_99", "rejected", "overage"])
def test_f2p_978_10_99_email_says_sessions_are_held(rig: Rig, name: str) -> None:
    assert rig.read(name) == 0
    (text,) = rig.mails("blocked")
    lowered = text.lower()
    assert "sessions are held" in lowered
    assert "no hold" not in lowered
    assert rig.read(name, at=T0 + 600) == 0
    assert len(rig.mails("blocked")) == 1


def test_f2p_978_10_one_email_when_the_pause_ends(rig: Rig) -> None:
    assert rig.read("at_99") == 0
    assert rig.mails("done") == []
    assert rig.read("allowed", at=T0 + 600) == 0
    (text,) = rig.mails("done")
    assert "ended" in text.lower()
    assert rig.read("allowed", at=T0 + 1200) == 0
    assert len(rig.mails("done")) == 1


def test_f2p_978_10_no_second_end_email_in_the_same_window(rig: Rig) -> None:
    assert rig.read("at_99") == 0
    assert rig.read("allowed", at=T0 + 600) == 0
    assert rig.read("at_99", at=T0 + 1200) == 0
    assert rig.pause_bytes() is not None
    assert rig.read("allowed", at=T0 + 1800) == 0
    assert rig.pause_bytes() is None
    assert len(rig.mails("done")) == 1
    assert len(rig.mails("blocked")) == 1
    later = FIVE_RESET + 18_000
    rig.raw(_event({"five_hour": _win(0.99, later)}))
    assert rig.read(at=T0 + 2400) == 0
    rig.raw(_event({"five_hour": _win(0.1, later)}))
    assert rig.read(at=T0 + 3000) == 0
    assert len(rig.mails("done")) == 2
    assert len(rig.mails("blocked")) == 2


@pytest.mark.parametrize("origin", ["auto", "user"])
def test_f2p_978_10_end_by_time_has_its_email(rig: Rig, origin: str) -> None:
    rig.pause(end_at=T0 + 100, origin=origin)
    assert rig.read("at_95", at=T0 + 200) == 0
    assert len(rig.mails("done")) == 1
    assert rig.read("at_95", at=T0 + 800) == 0
    assert len(rig.mails("done")) == 1


def test_f2p_978_10_failed_end_email_is_tried_again(rig: Rig) -> None:
    assert rig.read("at_99") == 0
    rig.plan([{"outcome": "smtp_error"}])
    assert rig.read("allowed", at=T0 + 600) == 0
    assert len(rig.mails("done")) == 1
    rig.plan([{"outcome": "sent"}])
    assert rig.read("allowed", at=T0 + 1200) == 0
    assert len(rig.mails("done")) == 2
    assert rig.read("allowed", at=T0 + 1800) == 0
    assert len(rig.mails("done")) == 2


# ── AC-978.12: the start time ───────────────────────────────────────────


def test_f2p_978_12_median_start_without_a_pause_is_under_100_ms(
    ug: Any, box: Path
) -> None:
    args = _entry_args(ug, box)
    times: list[float] = []
    for _ in range(20):
        began = time.perf_counter()
        done = subprocess.run(
            args,
            input=b"{}",
            capture_output=True,
            env=_clean_env(),
            timeout=30,
            creationflags=NO_WINDOW,
        )
        times.append(time.perf_counter() - began)
        assert (done.returncode, done.stdout, done.stderr) == (0, b"", b"")
    assert statistics.median(times) < 0.100, times


# ── AC-978.13: headless runs ────────────────────────────────────────────


def _deny(out: str) -> dict[str, Any]:
    (line,) = out.splitlines()
    doc = json.loads(line)
    assert doc["continue"] is False
    assert isinstance(doc["stopReason"], str) and doc["stopReason"]
    specific = doc["hookSpecificOutput"]
    assert specific["hookEventName"] == "PreToolUse"
    assert specific["permissionDecision"] == "deny"
    reason = specific["permissionDecisionReason"]
    assert isinstance(reason, str) and reason
    return doc


def test_f2p_978_13_headless_run_stops_at_once(
    hook: Any,
    box: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_pause(box, T0 + 600)
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "sdk-cli")
    assert hook.headless(os.environ) is True
    clock = Clock()
    code, out, _ = _call(hook, box, GOOD_CALL, monkeypatch, capsys, clock)
    assert code == 0
    _deny(out)
    assert clock.sleeps == []


@pytest.mark.parametrize(
    "sign", ["claude-vscode", "cli", "", "sdk-ts", "SDK-CLI", " sdk-cli", "other"]
)
def test_f2p_978_13_other_signs_are_held_and_never_denied(
    hook: Any,
    box: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    sign: str,
) -> None:
    _write_pause(box, T0 + 12)
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", sign)
    assert hook.headless(os.environ) is False
    clock = Clock()
    code, out, _ = _call(hook, box, GOOD_CALL, monkeypatch, capsys, clock)
    assert (code, out) == (0, "")
    assert sum(clock.sleeps) == pytest.approx(12)


def test_f2p_978_13_no_sign_is_held(
    hook: Any,
    box: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_pause(box, T0 + 12)
    assert hook.headless({}) is False
    clock = Clock()
    code, out, _ = _call(hook, box, GOOD_CALL, monkeypatch, capsys, clock)
    assert (code, out) == (0, "")
    assert sum(clock.sleeps) == pytest.approx(12)


@pytest.mark.parametrize("call", ["skill", "api"])
def test_f2p_978_13_headless_pass_has_no_output(
    hook: Any,
    box: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    call: str,
) -> None:
    _write_pause(box, T0 + 600)
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "sdk-cli")
    stdin = GOOD_CALL
    if call == "skill":
        stdin = _tool("Skill", skill="usage-guard")
    else:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "1")
    clock = Clock()
    code, out, _ = _call(hook, box, stdin, monkeypatch, capsys, clock)
    assert (code, out) == (0, "")
    assert clock.sleeps == []


def test_f2p_978_13_process_headless_and_interactive(
    ug: Any, box: Path, procs: list[subprocess.Popen[bytes]]
) -> None:
    _write_pause(box, time.time() + 600)
    args = _entry_args(ug, box)
    vscode = _start(args, GOOD_CALL, procs, _clean_env(CLAUDE_CODE_ENTRYPOINT="cli"))
    plain = _start(args, GOOD_CALL, procs)
    done, spent = _run(args, GOOD_CALL, _clean_env(CLAUDE_CODE_ENTRYPOINT="sdk-cli"))
    assert done.returncode == 0
    assert spent < FAIL_OPEN_S
    _deny(done.stdout.decode("utf-8"))
    time.sleep(HELD_S)
    assert vscode.poll() is None
    assert plain.poll() is None
    vscode.kill()
    out, _ = vscode.communicate(timeout=30)
    assert out == b""




# ── R1 corrections: end email after expiry and the pause trip (EA-8) ────


def _r1_calls(rig: Rig) -> int:
    """The number of requests that the Claude stub recorded."""
    return len(_jsonl(rig.bin / "calls.jsonl"))


def _r1_trips(rig: Rig) -> list[dict[str, Any]]:
    """The ``pause_at`` trip records of the guard log."""
    return [
        line
        for line in _jsonl(rig.home / "guard.log")
        if line.get("event") == "limit_trip" and line.get("limit_name") == "pause_at"
    ]


def test_r1_f1_idle_expiry_sends_the_end_email_once(rig: Rig) -> None:
    assert rig.read("at_99") == 0
    doc = rig.pause_doc()
    assert doc is not None
    end_at = float(doc["end_at"])
    calls = _r1_calls(rig)
    assert rig.mails("done") == []
    code, out = rig.run("read", "--if-due", at=end_at + 10)
    assert (code, out.strip()) == (0, "not due")
    assert _r1_calls(rig) == calls
    (text,) = rig.mails("done")
    assert "ended" in text.lower()
    assert rig.state()["pause_ended"] == []
    code, out = rig.run("read", "--if-due", at=end_at + 610)
    assert (code, out.strip()) == (0, "not due")
    assert _r1_calls(rig) == calls
    assert len(rig.mails("done")) == 1


def test_r1_f1_expiry_during_failed_readings_sends_the_end_email(rig: Rig) -> None:
    assert rig.read("at_99") == 0
    doc = rig.pause_doc()
    assert doc is not None
    end_at = float(doc["end_at"])
    assert rig.read("no_event", at=T0 + 600) != 0
    assert rig.mails("done") == []
    before = rig.pause_bytes()
    assert before is not None
    assert rig.read("no_event", at=end_at + 10) != 0
    (text,) = rig.mails("done")
    assert "ended" in text.lower()
    assert rig.pause_bytes() == before
    assert rig.read("no_event", at=end_at + 610) != 0
    assert len(rig.mails("done")) == 1
    assert rig.pause_bytes() == before


R1_TRIP_CASES: dict[str, list[tuple[str, float | str]]] = {
    "at_99": [("five_hour", 0.99)],
    "rejected": [("five_hour", 1.0)],
    "two_windows": [("five_hour", 0.99), ("seven_day", 1.0)],
    "seven_day_only": [("seven_day", 0.995)],
    "overage": [("account", "overage")],
}


@pytest.mark.parametrize("case", sorted(R1_TRIP_CASES))
def test_r1_f5_auto_pause_start_writes_the_pause_at_trip(rig: Rig, case: str) -> None:
    data, _end_at, _windows = HIGH_CASES[case]
    rig.raw(data)
    assert rig.read() == 0
    assert rig.pause_doc() is not None
    trips = _r1_trips(rig)
    found = sorted((t["window"], t["observed_value"]) for t in trips)
    assert found == sorted(R1_TRIP_CASES[case])
    for trip in trips:
        assert trip["configured_value"] == pytest.approx(0.99)
        assert trip["at"] == T0
    assert rig.read(at=T0 + 600) == 0
    assert len(_r1_trips(rig)) == len(trips)


def test_r1_f5_no_pause_at_trip_without_a_new_pause(rig: Rig) -> None:
    assert rig.read("at_95") == 0
    assert rig.read("no_event", at=T0 + 600) != 0
    assert _r1_trips(rig) == []
    assert rig.read("at_99", at=T0 + 1200) == 0
    assert len(_r1_trips(rig)) == 1


# ── R2 corrections: the end email after a long gap (EA-9) ───────────────

R2_GAPS = [7200, 86_400, 4 * 86_400]
R2_LATER = [600, 2 * 86_400, 9 * 86_400]
R2_NEXT_RESET = FIVE_RESET + 18_000


def _r2_auto_pause(rig: Rig) -> float:
    """Start an ``auto`` pause at ``T0`` and give its end time."""
    assert rig.read("at_99") == 0
    doc = rig.pause_doc()
    assert doc is not None
    return float(doc["end_at"])


def _r2_idle(rig: Rig, at: float, *extra: str) -> None:
    """A scheduled poll that is not due. It must make no request."""
    calls = _r1_calls(rig)
    code, out = rig.run("read", "--if-due", *extra, at=at)
    assert (code, out.strip()) == (0, "not due")
    assert _r1_calls(rig) == calls


def _r2_classes(rig: Rig) -> list[str]:
    """The class of each email attempt, in the order of the attempts."""
    return [argv[argv.index("--class") + 1] for argv in _jsonl(rig.bin / "mails.jsonl")]


def _r2_low(rig: Rig, at: float) -> int:
    """A good low reading at ``at``. Its resets are after ``at``, so it is valid."""
    rig.raw(
        _event(
            {
                "five_hour": _win(0.07, int(at) + 3600),
                "seven_day": _win(0.21, int(at) + 86_400),
            }
        )
    )
    return rig.read(at=at)


@pytest.mark.parametrize("gap", R2_GAPS)
def test_r2_f1_late_idle_poll_sends_the_end_email_once(rig: Rig, gap: int) -> None:
    end_at = _r2_auto_pause(rig)
    before = rig.pause_bytes()
    _r2_idle(rig, end_at + gap)
    assert len(rig.mails("done")) == 1
    assert "ended" in rig.mails("done")[0].lower()
    assert rig.pause_bytes() == before
    for later in R2_LATER:
        _r2_idle(rig, end_at + gap + later)
    assert len(rig.mails("done")) == 1
    assert rig.pause_bytes() == before


@pytest.mark.parametrize("gap", R2_GAPS)
def test_r2_f1_late_failed_reading_sends_the_end_email_once(rig: Rig, gap: int) -> None:
    end_at = _r2_auto_pause(rig)
    before = rig.pause_bytes()
    assert rig.read("no_event", at=end_at + gap) != 0
    assert len(rig.mails("done")) == 1
    assert rig.pause_bytes() == before
    for later in R2_LATER:
        assert rig.read("no_event", at=end_at + gap + later) != 0
    assert len(rig.mails("done")) == 1
    assert rig.pause_bytes() == before


@pytest.mark.parametrize("gap", R2_GAPS)
def test_r2_f1_good_reading_after_a_gap_sends_the_queued_end_email_once(
    rig: Rig, gap: int
) -> None:
    end_at = _r2_auto_pause(rig)
    _r2_idle(rig, end_at + gap, "--no-mail")
    assert rig.mails("done") == []
    assert _r2_low(rig, end_at + gap + 600) == 0
    assert rig.pause_bytes() is None
    assert len(rig.mails("done")) == 1
    assert _r2_low(rig, end_at + gap + 1200) == 0
    assert len(rig.mails("done")) == 1


def test_r2_f1_failed_end_email_is_tried_again_after_a_long_gap(rig: Rig) -> None:
    end_at = _r2_auto_pause(rig)
    rig.plan([{"outcome": "smtp_error"}])
    _r2_idle(rig, end_at + 10)
    assert len(rig.mails("done")) == 1
    assert rig.state()["last_email"]["outcome"] == "failed"
    _r2_idle(rig, end_at + 2 * 86_400)
    assert len(rig.mails("done")) == 2
    rig.plan([{"outcome": "sent"}])
    _r2_idle(rig, end_at + 5 * 86_400)
    assert len(rig.mails("done")) == 3
    assert rig.state()["last_email"]["outcome"] == "sent"
    _r2_idle(rig, end_at + 6 * 86_400)
    assert len(rig.mails("done")) == 3


def test_r2_f1_failed_end_email_then_good_reading_after_a_gap(rig: Rig) -> None:
    end_at = _r2_auto_pause(rig)
    rig.plan([{"outcome": "smtp_error"}])
    before = rig.pause_bytes()
    assert rig.read("no_event", at=end_at + 7200) != 0
    assert len(rig.mails("done")) == 1
    assert rig.pause_bytes() == before
    rig.plan([{"outcome": "sent"}])
    assert _r2_low(rig, end_at + 86_400) == 0
    assert rig.pause_bytes() is None
    assert len(rig.mails("done")) == 2
    assert _r2_low(rig, end_at + 86_400 + 600) == 0
    assert len(rig.mails("done")) == 2


def test_r2_f1_end_email_is_not_sent_again_after_its_mark_is_forgotten(
    rig: Rig,
) -> None:
    end_at = _r2_auto_pause(rig)
    _r2_idle(rig, end_at + 10)
    assert len(rig.mails("done")) == 1
    before = rig.pause_bytes()
    for day in (1, 2, 5):
        assert rig.read("no_event", at=end_at + day * 86_400) != 0
    assert rig.pause_bytes() == before
    assert len(rig.mails("done")) == 1
    assert _r2_low(rig, end_at + 6 * 86_400) == 0
    assert rig.pause_bytes() is None
    assert len(rig.mails("done")) == 1


@pytest.mark.parametrize(("poll", "gap"), [(True, 600), (False, 600), (False, 7200)])
def test_r2_f1_ended_pause_replaced_by_a_new_pause_gets_its_end_email(
    rig: Rig, poll: bool, gap: int
) -> None:
    end_at = _r2_auto_pause(rig)
    if poll:
        rig.plan([{"outcome": "smtp_error"}])
        _r2_idle(rig, end_at + 10)
        rig.plan([{"outcome": "sent"}])
    rig.raw(_event({"five_hour": _win(0.99, R2_NEXT_RESET)}))
    assert rig.read(at=end_at + gap) == 0
    doc = rig.pause_doc()
    assert doc is not None
    assert (doc["origin"], doc["started_at"]) == ("auto", end_at + gap)
    done = rig.mails("done")
    assert len(done) == (2 if poll else 1)
    assert "ended" in done[-1].lower()
    assert "new pause" in done[-1].lower()
    first = ["blocked", "done"] if poll else ["blocked"]
    assert _r2_classes(rig) == [*first, "done", "blocked"]
    assert rig.read(at=end_at + gap + 600) == 0
    assert len(rig.mails("done")) == len(done)
    rig.raw(_event({"five_hour": _win(0.1, R2_NEXT_RESET)}))
    assert rig.read(at=end_at + gap + 1200) == 0
    assert rig.pause_bytes() is None
    assert len(rig.mails("done")) == len(done) + 1


def test_r2_f1_user_pause_over_an_ended_pause_keeps_its_end_email(rig: Rig) -> None:
    end_at = _r2_auto_pause(rig)
    assert rig.run("pause", "--hours", "1", at=end_at + 7200)[0] == 0
    assert _r2_low(rig, end_at + 7300) == 0
    done = rig.mails("done")
    assert len(done) == 1
    assert "new pause" in done[0].lower()
    doc = rig.pause_doc()
    assert doc is not None
    assert doc["origin"] == "user"
    assert _r2_low(rig, end_at + 7900) == 0
    assert len(rig.mails("done")) == 1
    assert _r2_low(rig, end_at + 7200 + 3600 + 100) == 0
    assert rig.pause_bytes() is None
    assert len(rig.mails("done")) == 2


@pytest.mark.parametrize("poll", [True, False])
def test_r2_f1_resume_after_an_ended_pause_keeps_its_end_email(
    rig: Rig, poll: bool
) -> None:
    end_at = _r2_auto_pause(rig)
    if poll:
        _r2_idle(rig, end_at + 7200, "--no-mail")
    assert rig.run("resume", at=end_at + 7300)[0] == 0
    assert rig.mails("done") == []
    assert rig.pause_bytes() is None
    _r2_idle(rig, end_at + 7400)
    assert len(rig.mails("done")) == 1
    _r2_idle(rig, end_at + 8000)
    assert len(rig.mails("done")) == 1


def test_r2_f1_resume_of_a_pause_that_is_on_sends_no_end_email(rig: Rig) -> None:
    _r2_auto_pause(rig)
    assert rig.run("resume", at=T0 + 10)[0] == 0
    assert rig.read("allowed", at=T0 + 600) == 0
    _r2_idle(rig, T0 + 86_400)
    assert rig.mails("done") == []


def test_r2_f1_end_email_record_stays_bounded(rig: Rig) -> None:
    rig.plan([{"outcome": "smtp_error"}])
    base = T0 + 1000
    for step in range(40):
        end = base + step * 1000
        rig.pause(end_at=end, origin="user")
        _r2_idle(rig, end + 10)
    limit = rig.ug.END_NOTICE_MAX
    state = rig.state()
    assert 1 <= len(state["pause_ended"]) <= limit
    assert len(state["end_sent"]) <= limit
    assert (rig.home / "state.json").stat().st_size <= rig.ug.STATE_MAX
    trips = [
        line
        for line in _jsonl(rig.home / "guard.log")
        if line.get("limit_name") == "end_notice_max"
    ]
    assert trips
    assert trips[0]["configured_value"] == limit
    attempts = len(rig.mails("done"))
    assert attempts == 40
    rig.plan([{"outcome": "sent"}])
    _r2_idle(rig, base + 10**6)
    assert len(rig.mails("done")) == attempts + 1
    assert rig.state()["pause_ended"] == []
    _r2_idle(rig, base + 10**6 + 600)
    assert len(rig.mails("done")) == attempts + 1
