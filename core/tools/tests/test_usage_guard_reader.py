"""Tests for the usage reader of ``tools/usage_guard.py`` (MEU-977, AC-977.1 to .13).

No test starts the real Claude program, the real ``schtasks.exe`` or a real
email. Each test uses a scratch home, a stub program that records its call, a
recorded ``schtasks`` stub and a fake clock. The module is loaded by path in a
fixture, so that a missing module fails each test and not the collection.

The streams are embedded (``STREAMS``) and use fixed reset times. ``T0`` is the
clock that they fit.
"""

from __future__ import annotations

import ast
import email
import email.policy
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import textwrap
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD = REPO_ROOT / "tools" / "usage_guard.py"
NOTIFY = REPO_ROOT / "tools" / "agent_notify.py"

T0 = 1_800_000_000.0
FIVE_RESET = 1_800_007_200
SEVEN_RESET = 1_800_400_000
ACCOUNT_A = "account-aaaa-0001"
ACCOUNT_B = "account-bbbb-0002"
TASK_NS = "{http://schemas.microsoft.com/windows/2004/02/mit/task}"

DROPPED_KEYS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
)

READ_ARGS = [
    "-p",
    "Reply with: ok",
    "--output-format",
    "stream-json",
    "--verbose",
    "--model",
    "haiku",
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
]

BAD_VALUES = (
    "bad_null",
    "bad_text",
    "bad_boolean",
    "bad_negative",
    "bad_nan",
    "bad_infinity",
    "bad_percent",
    "bad_milliseconds",
    "bad_absent_reset",
)

CLAUDE_STUB = '''
"""Stub of the Claude program: records the call, then prints a planned stream."""
import json, os, subprocess, sys, time
from pathlib import Path

here = Path(__file__).resolve().parent
record = {
    "argv": sys.argv[1:],
    "env": dict(os.environ),
    "cwd": os.getcwd(),
    "stdin": sys.stdin.read() if sys.stdin is not None else "",
}
with open(here / "calls.jsonl", "a", encoding="utf-8") as out:
    out.write(json.dumps(record) + "\\n")
beat = here / "beat.py"
if beat.exists():
    subprocess.Popen([sys.executable, str(beat)])
gate = here / "gate"
while gate.exists():
    time.sleep(0.02)
sleep_s = here / "sleep.txt"
if sleep_s.exists():
    time.sleep(float(sleep_s.read_text()))
stream = here / "stream.jsonl"
if stream.exists():
    sys.stdout.buffer.write(stream.read_bytes())
    sys.stdout.buffer.flush()
note = here / "stderr.txt"
if note.exists():
    sys.stderr.write(note.read_text())
code = here / "exit.txt"
sys.exit(int(code.read_text()) if code.exists() else 0)
'''

NOTIFY_STUB = '''
"""Stub of the notifier: records the call, then appends planned log lines. It exits 0."""
import json, sys, time
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
if plan.get("truncate"):
    log.write_bytes(b"")
if plan.get("sleep"):
    time.sleep(plan["sleep"])
with open(log, "a", encoding="utf-8", newline="\\n") as out:
    for line in plan["lines"]:
        out.write(json.dumps({"ts": "t", "class": cls, "harness": "manual", **line}) + "\\n")
'''

SCHTASKS_STUB = '''
"""Recorded schtasks stub: one task, kept as XML in a folder."""
import json, sys
from pathlib import Path

here = Path(__file__).resolve().parent
argv = sys.argv[1:]
task = here / "task.xml"
with open(here / "sched.jsonl", "a", encoding="utf-8") as out:
    out.write(json.dumps(argv) + "\\n")
verb = argv[0].lower()
upper = [a.upper() for a in argv]
if argv[upper.index("/TN") + 1] != "ClaudeUsageGuard":
    sys.exit(1)
if verb == "/query":
    if not task.exists():
        sys.exit(1)
    sys.stdout.buffer.write(task.read_bytes().decode("utf-16").encode("ascii", "replace"))
    sys.exit(0)
if verb == "/create":
    if (here / "fail-create").exists() or (task.exists() and "/F" not in upper):
        sys.exit(1)
    task.write_bytes(Path(argv[upper.index("/XML") + 1]).read_bytes())
    sys.exit(0)
if verb == "/delete":
    if (here / "fail-delete").exists() or not task.exists() or "/F" not in upper:
        sys.exit(1)
    task.unlink()
    sys.exit(0)
sys.exit(1)
'''

DRIVER = '''
"""Process driver: loads the guard by path and calls main with the rig's stubs."""
import importlib.util, json, os, sys, time
from pathlib import Path

cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
spec = importlib.util.spec_from_file_location("usage_guard", cfg["guard"])
mod = importlib.util.module_from_spec(spec)
sys.modules["usage_guard"] = mod
spec.loader.exec_module(mod)
if len(sys.argv) > 2 and sys.argv[2] == "hang-replace":
    real = os.replace
    marker = Path(cfg["marker"])

    def hang(src, dst, **kw):
        if Path(dst).name == "state.json":
            part = marker.with_suffix(".part")
            part.write_text(str(src), encoding="utf-8")
            real(part, marker)
            time.sleep(60)
        return real(src, dst, **kw)

    os.replace = hang
deps = mod.Deps(
    claude=tuple(cfg["claude"]),
    account_file=Path(cfg["account_file"]),
    projects=Path(cfg["projects"]),
    notify_home=Path(cfg["notify_home"]),
    notifier=tuple(cfg["notifier"]),
    schtasks=tuple(cfg["schtasks"]),
)
sys.exit(mod.main(cfg["argv"], deps=deps, now=lambda: cfg["now"]))
'''


# ── Harness ─────────────────────────────────────────────────────────────


@pytest.fixture
def ug(monkeypatch: pytest.MonkeyPatch) -> Any:
    """The guard module, loaded from its path."""
    assert GUARD.is_file(), GUARD
    spec = importlib.util.spec_from_file_location("usage_guard", GUARD)
    assert spec is not None and spec.loader is not None
    mod: Any = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "usage_guard", mod)
    spec.loader.exec_module(mod)
    return mod


# The streams of the Claude program, embedded so that the package ships no
# fixture files. They use fixed reset times; ``T0`` is the clock that they fit.
STREAMS: dict[str, bytes] = {
    'absent_window': b'{"type":"system","subtype":"init","model":"haiku","tools":[]}\n{"type":"rate_limit_event","rate_limit_info":{"status":"allowed","resetsAt":1800007200,"rateLimitType":"five_hour","overageStatus":"rejected","isUsingOverage":false,"unifiedWindows":{"seven_day_opus":{"utilization":0.5,"resetsAt":1800400000}}}}\n{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"ok"}]}}\n{"type":"result","subtype":"success","is_error":false,"num_turns":1,"result":"ok"}\n',
    'allowed': b'{"type":"system","subtype":"init","model":"haiku","tools":[]}\n{"type":"rate_limit_event","rate_limit_info":{"status":"allowed","resetsAt":1800007200,"rateLimitType":"five_hour","overageStatus":"rejected","isUsingOverage":false,"unifiedWindows":{"five_hour":{"utilization":0.07,"resetsAt":1800007200},"seven_day":{"utilization":0.21,"resetsAt":1800400000}}}}\n{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"ok"}]}}\n{"type":"result","subtype":"success","is_error":false,"num_turns":1,"result":"ok"}\n',
    'at_95': b'{"type":"system","subtype":"init","model":"haiku","tools":[]}\n{"type":"rate_limit_event","rate_limit_info":{"status":"allowed","resetsAt":1800007200,"rateLimitType":"five_hour","overageStatus":"rejected","isUsingOverage":false,"unifiedWindows":{"five_hour":{"utilization":0.95,"resetsAt":1800007200},"seven_day":{"utilization":0.21,"resetsAt":1800400000}}}}\n{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"ok"}]}}\n{"type":"result","subtype":"success","is_error":false,"num_turns":1,"result":"ok"}\n',
    'at_99': b'{"type":"system","subtype":"init","model":"haiku","tools":[]}\n{"type":"rate_limit_event","rate_limit_info":{"status":"allowed","resetsAt":1800007200,"rateLimitType":"five_hour","overageStatus":"rejected","isUsingOverage":false,"unifiedWindows":{"five_hour":{"utilization":0.99,"resetsAt":1800007200},"seven_day":{"utilization":0.21,"resetsAt":1800400000}}}}\n{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"ok"}]}}\n{"type":"result","subtype":"success","is_error":false,"num_turns":1,"result":"ok"}\n',
    'bad_absent_reset': b'{"type":"system","subtype":"init","model":"haiku","tools":[]}\n{"type":"rate_limit_event","rate_limit_info":{"status":"allowed","resetsAt":1800007200,"rateLimitType":"five_hour","overageStatus":"rejected","isUsingOverage":false,"unifiedWindows":{"five_hour":{"utilization":0.07},"seven_day":{"utilization":0.21,"resetsAt":1800400000}}}}\n{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"ok"}]}}\n{"type":"result","subtype":"success","is_error":false,"num_turns":1,"result":"ok"}\n',
    'bad_boolean': b'{"type":"system","subtype":"init","model":"haiku","tools":[]}\n{"type":"rate_limit_event","rate_limit_info":{"status":"allowed","resetsAt":1800007200,"rateLimitType":"five_hour","overageStatus":"rejected","isUsingOverage":false,"unifiedWindows":{"five_hour":{"utilization":true,"resetsAt":1800007200},"seven_day":{"utilization":0.21,"resetsAt":1800400000}}}}\n{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"ok"}]}}\n{"type":"result","subtype":"success","is_error":false,"num_turns":1,"result":"ok"}\n',
    'bad_infinity': b'{"type":"system","subtype":"init","model":"haiku","tools":[]}\n{"type":"rate_limit_event","rate_limit_info":{"status":"allowed","resetsAt":1800007200,"rateLimitType":"five_hour","overageStatus":"rejected","isUsingOverage":false,"unifiedWindows":{"five_hour":{"utilization":Infinity,"resetsAt":1800007200},"seven_day":{"utilization":0.21,"resetsAt":1800400000}}}}\n{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"ok"}]}}\n{"type":"result","subtype":"success","is_error":false,"num_turns":1,"result":"ok"}\n',
    'bad_milliseconds': b'{"type":"system","subtype":"init","model":"haiku","tools":[]}\n{"type":"rate_limit_event","rate_limit_info":{"status":"allowed","resetsAt":1800007200,"rateLimitType":"five_hour","overageStatus":"rejected","isUsingOverage":false,"unifiedWindows":{"five_hour":{"utilization":0.07,"resetsAt":1800007200000},"seven_day":{"utilization":0.21,"resetsAt":1800400000}}}}\n{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"ok"}]}}\n{"type":"result","subtype":"success","is_error":false,"num_turns":1,"result":"ok"}\n',
    'bad_nan': b'{"type":"system","subtype":"init","model":"haiku","tools":[]}\n{"type":"rate_limit_event","rate_limit_info":{"status":"allowed","resetsAt":1800007200,"rateLimitType":"five_hour","overageStatus":"rejected","isUsingOverage":false,"unifiedWindows":{"five_hour":{"utilization":NaN,"resetsAt":1800007200},"seven_day":{"utilization":0.21,"resetsAt":1800400000}}}}\n{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"ok"}]}}\n{"type":"result","subtype":"success","is_error":false,"num_turns":1,"result":"ok"}\n',
    'bad_negative': b'{"type":"system","subtype":"init","model":"haiku","tools":[]}\n{"type":"rate_limit_event","rate_limit_info":{"status":"allowed","resetsAt":1800007200,"rateLimitType":"five_hour","overageStatus":"rejected","isUsingOverage":false,"unifiedWindows":{"five_hour":{"utilization":-0.01,"resetsAt":1800007200},"seven_day":{"utilization":0.21,"resetsAt":1800400000}}}}\n{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"ok"}]}}\n{"type":"result","subtype":"success","is_error":false,"num_turns":1,"result":"ok"}\n',
    'bad_null': b'{"type":"system","subtype":"init","model":"haiku","tools":[]}\n{"type":"rate_limit_event","rate_limit_info":{"status":"allowed","resetsAt":1800007200,"rateLimitType":"five_hour","overageStatus":"rejected","isUsingOverage":false,"unifiedWindows":{"five_hour":{"utilization":null,"resetsAt":1800007200},"seven_day":{"utilization":0.21,"resetsAt":1800400000}}}}\n{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"ok"}]}}\n{"type":"result","subtype":"success","is_error":false,"num_turns":1,"result":"ok"}\n',
    'bad_percent': b'{"type":"system","subtype":"init","model":"haiku","tools":[]}\n{"type":"rate_limit_event","rate_limit_info":{"status":"allowed","resetsAt":1800007200,"rateLimitType":"five_hour","overageStatus":"rejected","isUsingOverage":false,"unifiedWindows":{"five_hour":{"utilization":71,"resetsAt":1800007200},"seven_day":{"utilization":0.21,"resetsAt":1800400000}}}}\n{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"ok"}]}}\n{"type":"result","subtype":"success","is_error":false,"num_turns":1,"result":"ok"}\n',
    'bad_text': b'{"type":"system","subtype":"init","model":"haiku","tools":[]}\n{"type":"rate_limit_event","rate_limit_info":{"status":"allowed","resetsAt":1800007200,"rateLimitType":"five_hour","overageStatus":"rejected","isUsingOverage":false,"unifiedWindows":{"five_hour":{"utilization":"0.07","resetsAt":1800007200},"seven_day":{"utilization":0.21,"resetsAt":1800400000}}}}\n{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"ok"}]}}\n{"type":"result","subtype":"success","is_error":false,"num_turns":1,"result":"ok"}\n',
    'no_event': b'{"type":"system","subtype":"init","model":"haiku","tools":[]}\n{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"ok"}]}}\n{"type":"result","subtype":"success","is_error":false,"num_turns":1,"result":"ok"}\n',
    'overage': b'{"type":"system","subtype":"init","model":"haiku","tools":[]}\n{"type":"rate_limit_event","rate_limit_info":{"status":"allowed","resetsAt":1800007200,"rateLimitType":"five_hour","overageStatus":"rejected","isUsingOverage":true,"unifiedWindows":{"five_hour":{"utilization":0.3,"resetsAt":1800007200},"seven_day":{"utilization":0.21,"resetsAt":1800400000}}}}\n{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"ok"}]}}\n{"type":"result","subtype":"success","is_error":false,"num_turns":1,"result":"ok"}\n',
    'passed_reset': b'{"type":"system","subtype":"init","model":"haiku","tools":[]}\n{"type":"rate_limit_event","rate_limit_info":{"status":"allowed","resetsAt":1800007200,"rateLimitType":"five_hour","overageStatus":"rejected","isUsingOverage":false,"unifiedWindows":{"five_hour":{"utilization":0.97,"resetsAt":1799998200},"seven_day":{"utilization":0.21,"resetsAt":1800400000}}}}\n{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"ok"}]}}\n{"type":"result","subtype":"success","is_error":false,"num_turns":1,"result":"ok"}\n',
    'rejected': b'{"type":"system","subtype":"init","model":"haiku","tools":[]}\n{"type":"rate_limit_event","rate_limit_info":{"status":"rejected","resetsAt":1800007200,"rateLimitType":"five_hour","overageStatus":"rejected","isUsingOverage":false,"unifiedWindows":{"five_hour":{"utilization":0.42,"resetsAt":1800007200},"seven_day":{"utilization":0.21,"resetsAt":1800400000}}}}\n{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"ok"}]}}\n{"type":"result","subtype":"success","is_error":false,"num_turns":1,"result":"ok"}\n',
    'seven_day_only': b'{"type":"system","subtype":"init","model":"haiku","tools":[]}\n{"type":"rate_limit_event","rate_limit_info":{"status":"allowed","resetsAt":1800007200,"rateLimitType":"five_hour","overageStatus":"rejected","isUsingOverage":false,"unifiedWindows":{"seven_day":{"utilization":0.21,"resetsAt":1800400000},"seven_day_opus":{"utilization":0.5,"resetsAt":1800400000}}}}\n{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"ok"}]}}\n{"type":"result","subtype":"success","is_error":false,"num_turns":1,"result":"ok"}\n',
    'two_events': b'{"type":"system","subtype":"init","model":"haiku","tools":[]}\n{"type":"rate_limit_event","rate_limit_info":{"status":"allowed","resetsAt":1800007200,"rateLimitType":"five_hour","overageStatus":"rejected","isUsingOverage":false,"unifiedWindows":{"five_hour":{"utilization":0.07,"resetsAt":1800007200},"seven_day":{"utilization":0.21,"resetsAt":1800400000}}}}\n{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"ok"}]}}\n{"type":"rate_limit_event","rate_limit_info":{"status":"allowed","resetsAt":1800007200,"rateLimitType":"five_hour","overageStatus":"rejected","isUsingOverage":false,"unifiedWindows":{"five_hour":{"utilization":0.08,"resetsAt":1800007200},"seven_day":{"utilization":0.21,"resetsAt":1800400000}}}}\n{"type":"result","subtype":"success","is_error":false,"num_turns":1,"result":"ok"}\n',
}


def _stream(name: str) -> bytes:
    """The bytes of one embedded stream."""
    return STREAMS[name]


def _event(
    windows: dict[str, Any],
    *,
    status: str = "allowed",
    overage: Any = False,
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


def _win(utilization: Any, resets_at: Any = FIVE_RESET) -> dict[str, Any]:
    return {"utilization": utilization, "resetsAt": resets_at}


def _jsonl(path: Path) -> list[Any]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class Rig:
    """A scratch home with stubs. Folder names hold a space on purpose."""

    def __init__(self, base: Path, ug: Any, capsys: pytest.CaptureFixture[str]) -> None:
        self.ug = ug
        self.capsys = capsys
        self.home = base / "guard home"
        self.home.mkdir()
        self.bin = base / "stub bin"
        self.bin.mkdir()
        self.projects = base / "projects"
        self.transcript = self.projects / "p--x" / "s.jsonl"
        self.transcript.parent.mkdir(parents=True)
        self.transcript.write_text("{}\n", encoding="utf-8")
        self.account_file = base / "claude.json"
        self.notify_home = base / "notify home"
        (self.notify_home / "state").mkdir(parents=True)
        self.source = base / "source"
        self.source.mkdir()
        for path in (GUARD, NOTIFY):
            (self.source / path.name).write_bytes(path.read_bytes())
        self.python = base / "py dir" / "python.exe"
        self.python.parent.mkdir()
        self.python.write_bytes(b"")
        self.pythonw = self.python.with_name("pythonw.exe")
        self.pythonw.write_bytes(b"")
        for name, text in (
            ("claude_stub.py", CLAUDE_STUB),
            ("notify_stub.py", NOTIFY_STUB),
            ("schtasks_stub.py", SCHTASKS_STUB),
            ("driver.py", DRIVER),
        ):
            (self.bin / name).write_text(text, encoding="utf-8")
        self.account(ACCOUNT_A)
        self.plan([{"outcome": "sent"}])
        self.stream("allowed")
        self.active_at(T0)

    # Inputs

    def account(self, account_id: str) -> None:
        data = {
            "numStartups": 3,
            "oauthAccount": {
                "accountUuid": account_id,
                "emailAddress": "@".join(("who", "acct.invalid")),
            },
        }
        self.account_file.write_text(json.dumps(data), encoding="utf-8")

    def stream(self, name: str) -> None:
        self.raw(_stream(name))

    def raw(self, data: bytes) -> None:
        (self.bin / "stream.jsonl").write_bytes(data)

    def plan(self, lines: list[dict[str, Any]], **extra: Any) -> None:
        text = json.dumps({"lines": lines, **extra})
        (self.bin / "notify-plan.json").write_text(text, encoding="utf-8")

    def active_at(self, when: float) -> None:
        os.utime(self.transcript, (when, when))

    def pause(self, *, end_at: float = T0 + 18_000, origin: str = "user") -> bytes:
        data = {
            "schema": "usage-guard-pause/1",
            "origin": origin,
            "started_at": T0 - 10,
            "end_at": end_at,
            "windows": [],
        }
        raw = json.dumps(data).encode()
        (self.home / "pause.json").write_bytes(raw)
        return raw

    # Calls

    def deps(self, **over: Any) -> Any:
        values: dict[str, Any] = {
            "claude": (sys.executable, str(self.bin / "claude_stub.py")),
            "account_file": self.account_file,
            "projects": self.projects,
            "notify_home": self.notify_home,
            "notifier": (sys.executable, str(self.bin / "notify_stub.py")),
            "schtasks": (sys.executable, str(self.bin / "schtasks_stub.py")),
            "source": self.source,
        }
        values.update(over)
        return self.ug.Deps(**values)

    def run(
        self,
        *argv: str,
        at: float = T0,
        deps: Any = None,
        limit_s: float | None = None,
    ) -> tuple[int, str]:
        extra: dict[str, Any] = {} if limit_s is None else {"limit_s": limit_s}
        self.capsys.readouterr()
        code = self.ug.main(
            [*argv, "--home", str(self.home)],
            deps=deps if deps is not None else self.deps(),
            now=lambda: at,
            sleep=lambda _s: None,
            **extra,
        )
        captured = self.capsys.readouterr()
        return code, captured.out + captured.err

    def read(self, *flags: str, at: float = T0, **kw: Any) -> tuple[int, str]:
        """A plain read. A session works at that time unless the test says otherwise."""
        return self.run("read", *flags, at=at, **kw)

    def if_due(self, at: float, *, active: bool = True) -> bool:
        """Run ``read --if-due`` at a time. True when it made a request."""
        if active:
            self.active_at(at - 1)
        before = len(self.calls())
        code, out = self.run("read", "--if-due", at=at)
        made = len(self.calls()) - before
        assert made in (0, 1)
        assert code == 0, out
        return made == 1

    def status(self, at: float = T0) -> dict[str, Any]:
        code, out = self.run("status", "--json", at=at)
        assert code == 0, out
        return json.loads(out)

    def install(self, *flags: str, **kw: Any) -> tuple[int, str]:
        return self.run(
            "install", "--part", "task", "--python", str(self.python), *flags, **kw
        )

    def uninstall(self, **kw: Any) -> tuple[int, str]:
        return self.run("uninstall", "--part", "task", **kw)

    # Observations

    def calls(self) -> list[Any]:
        return _jsonl(self.bin / "calls.jsonl")

    def mails(self, cls: str | None = None) -> list[str]:
        """The texts of the sends, filtered by class."""
        out = []
        for argv in _jsonl(self.bin / "mails.jsonl"):
            if cls is None or argv[argv.index("--class") + 1] == cls:
                out.append(argv[argv.index("--text") + 1])
        return out

    def sched(self) -> list[list[str]]:
        return _jsonl(self.bin / "sched.jsonl")

    def state(self) -> dict[str, Any]:
        return json.loads((self.home / "state.json").read_text(encoding="utf-8"))

    def files(self) -> dict[str, bytes]:
        return {
            p.relative_to(self.home).as_posix(): p.read_bytes()
            for p in sorted(self.home.rglob("*"))
            if p.is_file()
        }

    def process(
        self, *argv: str, mode: str = "", at: float = T0
    ) -> subprocess.Popen[str]:
        """Start a driver process that calls ``main`` with the stubs of the rig."""
        deps = self.deps()
        cfg = {
            "guard": str(GUARD),
            "argv": [*argv, "--home", str(self.home)],
            "now": at,
            "marker": str(self.bin / "marker.txt"),
            "claude": list(deps.claude),
            "account_file": str(deps.account_file),
            "projects": str(deps.projects),
            "notify_home": str(deps.notify_home),
            "notifier": list(deps.notifier),
            "schtasks": list(deps.schtasks),
        }
        path = self.bin / "driver.json"
        path.write_text(json.dumps(cfg), encoding="utf-8")
        cmd = [sys.executable, str(self.bin / "driver.py"), str(path)]
        return subprocess.Popen(
            cmd + ([mode] if mode else []),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )


def _wait(check: Callable[[], bool], limit_s: float = 30.0) -> None:
    end = time.monotonic() + limit_s
    while not check():
        assert time.monotonic() < end, "the wait is too long"
        time.sleep(0.02)


@pytest.fixture
def rig(
    tmp_path: Path,
    ug: Any,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Rig]:
    for key in (
        "AGENT_NOTIFY",
        "AGENT_NOTIFY_HOME",
        "AGENT_NOTIFY_DRY_RUN",
        *DROPPED_KEYS,
    ):
        monkeypatch.delenv(key, raising=False)
    made = Rig(tmp_path, ug, capsys)
    yield made
    (made.bin / "gate").unlink(missing_ok=True)


# ── AC-977.1: the event ─────────────────────────────────────────────────


def test_f2p_977_01_two_windows(ug: Any) -> None:
    reading = ug.parse_stream(_stream("allowed"), now=T0)
    assert set(reading.windows) == {"five_hour", "seven_day"}
    assert reading.windows["five_hour"].utilization == 0.07
    assert reading.windows["five_hour"].resets_at == FIVE_RESET
    assert reading.windows["seven_day"].utilization == 0.21
    assert reading.windows["seven_day"].resets_at == SEVEN_RESET
    assert reading.status == "allowed"
    assert reading.limit_type == "five_hour"
    assert reading.overage is False


def test_f2p_977_01_seven_day_only_and_model_window_ignored(ug: Any) -> None:
    reading = ug.parse_stream(_stream("seven_day_only"), now=T0)
    assert set(reading.windows) == {"seven_day"}


def test_f2p_977_01_bad_model_window_is_ignored(ug: Any) -> None:
    data = _event({"five_hour": _win(0.07), "seven_day_opus": _win(None, "x")})
    assert set(ug.parse_stream(data, now=T0).windows) == {"five_hour"}


def test_f2p_977_01_last_event_counts(ug: Any) -> None:
    reading = ug.parse_stream(_stream("two_events"), now=T0)
    assert reading.windows["five_hour"].utilization == 0.08


def test_f2p_977_01_bad_last_event_fails_after_a_good_one(ug: Any) -> None:
    data = _stream("allowed") + _event({"five_hour": _win(None)})
    with pytest.raises(ug.ReadingError):
        ug.parse_stream(data, now=T0)


@pytest.mark.parametrize(
    ("name", "code"), [("no_event", "no_event"), ("absent_window", "no_window")]
)
def test_f2p_977_01_no_event_no_window(ug: Any, name: str, code: str) -> None:
    with pytest.raises(ug.ReadingError) as caught:
        ug.parse_stream(_stream(name), now=T0)
    assert caught.value.code == code


def test_f2p_977_01_foreign_lines_are_ignored(ug: Any) -> None:
    noise = b'not json\n\xff\xfe\n[1]\n"x"\n' + b"[" * 100_000 + b"\n\n"
    reading = ug.parse_stream(noise + _stream("allowed") + noise, now=T0)
    assert reading.windows["five_hour"].utilization == 0.07


@pytest.mark.parametrize(
    "data",
    [b"x" * (4 * 1024 * 1024 + 1), b"x" * (1024 * 1024 + 1) + b"\n"],
    ids=["stdout", "line"],
)
def test_f2p_977_01_size_limits(ug: Any, data: bytes) -> None:
    with pytest.raises(ug.ReadingError) as caught:
        ug.parse_stream(data, now=T0)
    assert caught.value.code not in ("no_event", "no_window")


@pytest.mark.parametrize("info", [None, [], "x", {"status": 5}, {"status": "allowed"}])
def test_f2p_977_01_wrong_event_shape_fails(ug: Any, info: Any) -> None:
    data = json.dumps({"type": "rate_limit_event", "rate_limit_info": info}).encode()
    with pytest.raises(ug.ReadingError):
        ug.parse_stream(data, now=T0)


# ── AC-977.2: the bounds ────────────────────────────────────────────────


@pytest.mark.parametrize("name", BAD_VALUES)
def test_f2p_977_02_bad_value_fails_the_full_reading(rig: Rig, name: str) -> None:
    with pytest.raises(rig.ug.ReadingError) as caught:
        rig.ug.parse_stream(_stream(name), now=T0)
    assert rig.read()[0] == 0
    good = rig.state()["last_good"]
    rig.stream(name)
    code, _out = rig.read(at=T0 + 60)
    assert code != 0
    state = rig.state()
    assert state["last_good"] == good
    assert state["last_error"] == caught.value.code
    assert re.fullmatch(r"[a-z_]{3,40}", state["last_error"])


@pytest.mark.parametrize(
    "window",
    [
        _win(2.01),
        _win([]),
        _win(0.1, True),
        _win(0.1, float(FIVE_RESET)),
        _win(0.1, str(FIVE_RESET)),
        _win(0.1, None),
        _win(0.1, int(T0) - 3601),
        _win(0.1, int(T0) + 691_201),
        _win(10**400),
        None,
        0.5,
    ],
)
def test_f2p_977_02_bound_edges_fail(ug: Any, window: Any) -> None:
    with pytest.raises(ug.ReadingError):
        ug.parse_stream(_event({"five_hour": _win(0.1), "seven_day": window}), now=T0)


@pytest.mark.parametrize(
    "window",
    [
        _win(0),
        _win(0.0),
        _win(2.0),
        _win(0.1, int(T0) - 3600),
        _win(0.1, int(T0) + 691_200),
    ],
)
def test_f2p_977_02_bound_edges_pass(ug: Any, window: dict[str, Any]) -> None:
    reading = ug.parse_stream(_event({"seven_day": window}), now=T0)
    assert reading.windows["seven_day"].utilization == window["utilization"]


def test_f2p_977_02_trip_of_a_bound_is_logged(rig: Rig) -> None:
    rig.stream("bad_percent")
    assert rig.read()[0] != 0
    text = b"\n".join(v for k, v in rig.files().items() if "log" in k).decode()
    for part in ("valid_bound", "configured_value", "observed_value", "five_hour"):
        assert part in text
    assert "71" in text


# ── AC-977.3: high and low ──────────────────────────────────────────────


def test_f2p_977_03_rejected_counts_as_full(ug: Any) -> None:
    reading = ug.parse_stream(_stream("rejected"), now=T0)
    assert reading.windows["five_hour"].utilization == 1.0
    assert reading.windows["seven_day"].utilization == 0.21
    assert ug.is_high(reading) is True
    assert ug.is_low(reading) is False


def test_f2p_977_03_rejected_never_lowers_a_value(ug: Any) -> None:
    data = _event({"five_hour": _win(1.4)}, status="rejected")
    assert ug.parse_stream(data, now=T0).windows["five_hour"].utilization == 1.4


def test_f2p_977_03_rejected_is_stored_as_full(rig: Rig) -> None:
    rig.stream("rejected")
    assert rig.read()[0] == 0
    assert rig.state()["last_good"]["windows"]["five_hour"]["utilization"] == 1.0
    assert rig.state()["last_error"] in (None, "")


def test_f2p_977_03_rejected_for_a_model_window_is_high(ug: Any) -> None:
    data = _event(
        {"five_hour": _win(0.2)}, status="rejected", limit_type="seven_day_opus"
    )
    reading = ug.parse_stream(data, now=T0)
    assert reading.windows["five_hour"].utilization == 0.2
    assert ug.is_high(reading) is True


def test_f2p_977_03_overage_is_high(ug: Any) -> None:
    reading = ug.parse_stream(_stream("overage"), now=T0)
    assert reading.overage is True
    assert ug.is_high(reading) is True
    assert ug.is_low(reading) is False


@pytest.mark.parametrize(
    ("value", "high", "low"),
    [
        (0.9499, False, True),
        (0.95, False, False),
        (0.98, False, False),
        (0.99, True, False),
    ],
)
def test_f2p_977_03_thresholds(ug: Any, value: float, high: bool, low: bool) -> None:
    for name in ("five_hour", "seven_day"):
        reading = ug.parse_stream(_event({name: _win(value)}), now=T0)
        assert (ug.is_high(reading), ug.is_low(reading)) == (high, low)


# ── AC-977.4: the reading command ───────────────────────────────────────


def test_f2p_977_04_command_environment_and_folder(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key in DROPPED_KEYS:
        monkeypatch.setenv(key, f"planted-{key}")
    monkeypatch.setenv("USAGE_GUARD_KEEP", "kept")
    code, out = rig.read()
    assert code == 0, out
    (call,) = rig.calls()
    assert call["argv"] == READ_ARGS
    assert call["stdin"] == ""
    assert Path(call["cwd"]).resolve() == (rig.home / "run").resolve()
    assert list((rig.home / "run").iterdir()) == []
    names = {key.upper() for key in call["env"]}
    assert not names & set(DROPPED_KEYS)
    assert call["env"]["USAGE_GUARD_KEEP"] == "kept"
    assert not any(str(v).startswith("planted-") for v in call["env"].values())


def test_f2p_977_04_nonzero_exit_with_an_event_is_a_reading(rig: Rig) -> None:
    (rig.bin / "exit.txt").write_text("1")
    rig.stream("rejected")
    assert rig.read()[0] == 0


def test_f2p_977_04_timeout_leaves_no_orphan(rig: Rig) -> None:
    beat = rig.bin / "beat.txt"
    (rig.bin / "beat.py").write_text(
        textwrap.dedent(
            f"""
            import time
            for n in range(600):
                open({str(beat)!r}, "w").write(str(n))
                time.sleep(0.05)
            """
        ),
        encoding="utf-8",
    )
    (rig.bin / "sleep.txt").write_text("60")
    started = time.monotonic()
    code, _out = rig.read(limit_s=4.0)
    assert time.monotonic() - started < 25
    assert code != 0
    assert rig.state()["last_error"] == "timeout"
    assert beat.exists(), "the stub did not start its child in the limit"
    time.sleep(0.3)
    first = beat.read_text()
    time.sleep(0.6)
    assert beat.read_text() == first, "the child of the reading is alive"


def test_f2p_977_04_large_output_is_stopped(rig: Rig) -> None:
    rig.raw((b"x" * 1000 + b"\n") * 5000 + _stream("allowed"))
    assert rig.read()[0] != 0
    assert rig.state()["last_error"] not in (None, "", "no_event")


def test_f2p_977_04_program_behind_the_npm_shim(ug: Any, tmp_path: Path) -> None:
    shim = tmp_path / "npm dir" / "claude.cmd"
    shim.parent.mkdir()
    shim.write_text("")
    program = (
        shim.parent
        / "node_modules"
        / "@anthropic-ai"
        / "claude-code"
        / "bin"
        / "claude.exe"
    )
    assert ug.resolve_exe(which=lambda _n: None) is None
    assert ug.resolve_exe(which=lambda _n: str(shim)) is None
    program.parent.mkdir(parents=True)
    program.write_bytes(b"")
    assert Path(ug.resolve_exe(which=lambda _n: str(shim))) == program


def test_f2p_977_04_no_program_is_no_claude(rig: Rig) -> None:
    deps = rig.deps(claude=None, which=lambda _n: None)
    assert rig.read(deps=deps)[0] != 0
    assert rig.state()["last_error"] == "no_claude"


def test_f2p_977_04_program_that_cannot_start_fails(rig: Rig) -> None:
    broken = rig.bin / "broken.exe"
    broken.write_bytes(b"not a program")
    assert rig.read(deps=rig.deps(claude=(str(broken),)))[0] != 0
    assert rig.state()["last_error"] not in (None, "")


# ── AC-977.5: a failed reading ──────────────────────────────────────────

FAILURES = ("no_event", "absent_window", *BAD_VALUES, "timeout", "no_claude")


@pytest.mark.parametrize("failure", FAILURES)
@pytest.mark.parametrize("pause", ["auto", "user", "bad", "none"])
def test_f2p_977_05_failed_reading_changes_no_pause(
    rig: Rig, failure: str, pause: str
) -> None:
    assert rig.read("--no-mail")[0] == 0
    good = rig.state()["last_good"]
    path = rig.home / "pause.json"
    path.unlink(missing_ok=True)
    if pause in ("auto", "user"):
        rig.pause(origin=pause)
    elif pause == "bad":
        path.write_bytes(b'{"schema": "usage-guard-pause/1", "end')
    before = path.read_bytes() if path.exists() else None
    deps, limit = rig.deps(), None
    if failure == "timeout":
        (rig.bin / "sleep.txt").write_text("30")
        limit = 0.5
    elif failure == "no_claude":
        deps = rig.deps(claude=None, which=lambda _n: None)
    else:
        rig.stream(failure)
    assert rig.read("--no-mail", at=T0 + 60, deps=deps, limit_s=limit)[0] != 0
    assert (path.read_bytes() if path.exists() else None) == before
    state = rig.state()
    assert state["last_good"] == good
    assert state["last_error"] not in (None, "")
    if failure in ("timeout", "no_claude", "no_event"):
        assert state["last_error"] == failure


def test_f2p_977_05_good_reading_clears_the_error(rig: Rig) -> None:
    rig.stream("no_event")
    assert rig.read()[0] != 0
    assert rig.state()["last_good"] is None
    rig.stream("allowed")
    assert rig.read(at=T0 + 60)[0] == 0
    assert rig.state()["last_error"] in (None, "")
    assert rig.state()["last_good"]["at"] == T0 + 60


# ── AC-977.6: the due rules ─────────────────────────────────────────────


def test_f2p_977_06_first_reading_is_due(rig: Rig) -> None:
    assert rig.if_due(T0) is True


def test_f2p_977_06_interval_600(rig: Rig) -> None:
    assert rig.if_due(T0)
    assert not rig.if_due(T0 + 599)
    assert rig.if_due(T0 + 600)


@pytest.mark.parametrize("name", ["five_hour", "seven_day"])
@pytest.mark.parametrize(("value", "interval"), [(0.8999, 600), (0.90, 300)])
def test_f2p_977_06_interval_300_from_90(
    rig: Rig, name: str, value: float, interval: int
) -> None:
    rig.raw(_event({name: _win(value)}))
    assert rig.if_due(T0)
    assert not rig.if_due(T0 + interval - 1)
    assert rig.if_due(T0 + interval)


def test_f2p_977_06_interval_counts_from_a_failed_attempt(rig: Rig) -> None:
    rig.stream("no_event")
    rig.active_at(T0)
    rig.run("read", "--if-due", at=T0)
    assert len(rig.calls()) == 1
    rig.run("read", "--if-due", at=T0 + 599)
    assert len(rig.calls()) == 1
    rig.run("read", "--if-due", at=T0 + 600)
    assert len(rig.calls()) == 2


def test_f2p_977_06_no_request_when_nothing_works(rig: Rig) -> None:
    rig.active_at(T0 - 901)
    assert not rig.if_due(T0, active=False)
    rig.active_at(T0 - 899)
    assert rig.if_due(T0, active=False)


def test_f2p_977_06_no_transcript_folder_is_no_activity(rig: Rig) -> None:
    rig.transcript.unlink()
    rig.transcript.parent.rmdir()
    rig.projects.rmdir()
    assert not rig.if_due(T0, active=False)


def test_f2p_977_06_subagent_transcript_is_activity(rig: Rig) -> None:
    rig.active_at(T0 - 5000)
    deep = rig.transcript.parent / "s" / "subagents" / "agent-1.jsonl"
    deep.parent.mkdir(parents=True)
    deep.write_text("{}\n")
    os.utime(deep, (T0 - 10, T0 - 10))
    assert rig.if_due(T0, active=False)


def test_f2p_977_06_other_files_are_no_activity(rig: Rig) -> None:
    rig.active_at(T0 - 5000)
    other = rig.transcript.parent / "notes.txt"
    other.write_text("x")
    os.utime(other, (T0, T0))
    assert not rig.if_due(T0, active=False)


def test_f2p_977_06_pause_reads_each_600_without_activity(rig: Rig) -> None:
    assert rig.if_due(T0)
    rig.active_at(T0 - 5000)
    rig.pause()
    assert not rig.if_due(T0 + 599, active=False)
    assert rig.if_due(T0 + 600, active=False)


def test_f2p_977_06_pause_interval_is_600_also_from_90(rig: Rig) -> None:
    rig.raw(_event({"seven_day": _win(0.93, SEVEN_RESET)}))
    assert rig.if_due(T0)
    rig.pause()
    assert not rig.if_due(T0 + 300)
    assert not rig.if_due(T0 + 599)
    assert rig.if_due(T0 + 600)


@pytest.mark.parametrize("end_at", [T0 + 100, T0 + 691_200 + 1000])
def test_f2p_977_06_past_or_far_pause_is_no_pause(rig: Rig, end_at: float) -> None:
    assert rig.if_due(T0)
    rig.active_at(T0 - 5000)
    rig.pause(end_at=end_at)
    assert not rig.if_due(T0 + 700, active=False)


def test_f2p_977_06_due_at_reset_plus_60(rig: Rig) -> None:
    assert rig.if_due(FIVE_RESET - 100)
    assert not rig.if_due(FIVE_RESET + 59)
    assert rig.if_due(FIVE_RESET + 60)
    assert not rig.if_due(FIVE_RESET + 61)


def test_f2p_977_06_plain_read_reads_at_once(rig: Rig) -> None:
    rig.active_at(T0 - 5000)
    assert rig.read()[0] == 0
    assert rig.read(at=T0 + 1)[0] == 0
    assert len(rig.calls()) == 2


def test_f2p_977_06_clock_that_moved_back_is_due(rig: Rig) -> None:
    assert rig.if_due(T0 + 5000)
    assert rig.if_due(T0)


def test_f2p_977_06_attempt_is_stored_before_the_request(rig: Rig) -> None:
    """A reader that dies in the request does not request again at the next start."""
    (rig.bin / "gate").write_text("")
    proc = rig.process("read")
    try:
        _wait(lambda: len(rig.calls()) == 1)
        proc.kill()
    finally:
        proc.kill()
        proc.communicate(timeout=30)
        (rig.bin / "gate").unlink()
    assert not rig.if_due(T0 + 300)


# ── AC-977.7: the lower bound ───────────────────────────────────────────


def test_f2p_977_07_value_until_reset_plus_60(rig: Rig) -> None:
    rig.raw(_event({"five_hour": _win(0.97), "seven_day": _win(0.21, SEVEN_RESET)}))
    assert rig.read()[0] == 0
    before = rig.status(FIVE_RESET + 59)["windows"]
    assert before["five_hour"]["percent"] == pytest.approx(97.0)
    after = rig.status(FIVE_RESET + 60)["windows"]
    assert after["five_hour"]["percent"] is None
    assert after["seven_day"]["percent"] == pytest.approx(21.0)
    code, out = rig.run("status", at=FIVE_RESET + 60)
    assert code == 0
    assert "97" not in out
    line = next(x for x in out.splitlines() if "five_hour" in x)
    assert "%" not in line


def test_f2p_977_07_failed_reading_keeps_the_lower_bound(rig: Rig) -> None:
    rig.raw(_event({"five_hour": _win(0.97)}))
    assert rig.read()[0] == 0
    rig.stream("no_event")
    assert rig.read(at=T0 + 3000)[0] != 0
    assert rig.status(T0 + 3000)["windows"]["five_hour"]["percent"] == pytest.approx(
        97.0
    )


def test_f2p_977_07_fresh_reading_with_a_passed_reset(rig: Rig) -> None:
    rig.stream("passed_reset")
    assert rig.read()[0] == 0
    assert rig.status()["windows"]["five_hour"]["percent"] is None
    assert rig.mails() == []


def test_f2p_977_07_expired_value_sets_no_short_interval(rig: Rig) -> None:
    rig.stream("passed_reset")
    assert rig.if_due(T0)
    assert not rig.if_due(T0 + 300)
    assert rig.if_due(T0 + 600)


# ── AC-977.8: the account ───────────────────────────────────────────────


def test_f2p_977_08_only_the_hash_is_stored(rig: Rig) -> None:
    assert rig.read()[0] == 0
    text = (rig.home / "state.json").read_text(encoding="utf-8")
    assert ACCOUNT_A not in text
    assert hashlib.sha256(f"usage-guard/1:{ACCOUNT_A}".encode()).hexdigest() in text


def test_f2p_977_08_changed_account_is_due_at_once(rig: Rig) -> None:
    assert rig.if_due(T0)
    assert not rig.if_due(T0 + 10)
    rig.account(ACCOUNT_B)
    assert rig.if_due(T0 + 11)
    assert not rig.if_due(T0 + 12)


def test_f2p_977_08_changed_account_drops_the_last_value(rig: Rig) -> None:
    assert rig.read()[0] == 0
    rig.account(ACCOUNT_B)
    rig.stream("no_event")
    assert rig.read(at=T0 + 10)[0] != 0
    assert rig.state()["last_good"] is None


def test_f2p_977_08_change_while_idle_drops_and_is_due_later(rig: Rig) -> None:
    assert rig.if_due(T0)
    rig.account(ACCOUNT_B)
    rig.active_at(T0 - 5000)
    assert not rig.if_due(T0 + 20, active=False)
    assert rig.status(T0 + 20)["windows"] == {} or all(
        w["percent"] is None for w in rig.status(T0 + 20)["windows"].values()
    )
    assert rig.if_due(T0 + 30)


def _big_account(rig: Rig) -> None:
    rig.account_file.write_text(
        json.dumps({"oauthAccount": {"accountUuid": "a" * 129}})
    )


BAD_ACCOUNTS: dict[str, Callable[[Rig], object]] = {
    "absent": lambda r: r.account_file.unlink(),
    "garbage": lambda r: r.account_file.write_text('{"oauthAccount": {"accountUu'),
    "list": lambda r: r.account_file.write_text("[]"),
    "no_key": lambda r: r.account_file.write_text('{"oauthAccount": {}}'),
    "null": lambda r: r.account_file.write_text('{"oauthAccount": null}'),
    "short": lambda r: r.account("a" * 7),
    "number": lambda r: r.account_file.write_text(
        '{"oauthAccount": {"accountUuid": 12345678}}'
    ),
    "long": _big_account,
    "deep": lambda r: r.account_file.write_text("[" * 100_000),
}


@pytest.mark.parametrize("kind", sorted(BAD_ACCOUNTS))
def test_f2p_977_08_unreadable_account_changes_nothing(rig: Rig, kind: str) -> None:
    assert rig.if_due(T0)
    digest = hashlib.sha256(f"usage-guard/1:{ACCOUNT_A}".encode()).hexdigest()
    good = rig.state()["last_good"]
    BAD_ACCOUNTS[kind](rig)
    assert not rig.if_due(T0 + 10)
    rig.stream("no_event")
    assert rig.read(at=T0 + 20)[0] != 0
    assert rig.state()["last_good"] == good
    assert digest in (rig.home / "state.json").read_text(encoding="utf-8")
    rig.account(ACCOUNT_A)
    assert not rig.if_due(T0 + 30)


# ── AC-977.9: state and lock ────────────────────────────────────────────


def _edit(change: Callable[[dict[str, Any]], object]) -> Callable[[bytes], bytes]:
    def apply(raw: bytes) -> bytes:
        data = json.loads(raw)
        change(data)
        return json.dumps(data).encode()

    return apply


BAD_STATES: dict[str, Callable[[bytes], bytes]] = {
    "empty": lambda _b: b"",
    "half": lambda b: b[: len(b) // 2],
    "not_utf8": lambda _b: b"\xff\xfe\xff",
    "list": lambda _b: b"[]",
    "deep": lambda _b: b"[" * 100_000,
    "too_large": lambda b: b + b" " * (256 * 1024),
    "schema": _edit(lambda d: d.update(schema="usage-guard-state/2")),
    "unknown_field": _edit(lambda d: d.update(extra=1)),
    "unknown_good_field": _edit(lambda d: d["last_good"].update(extra=1)),
    "unknown_window": _edit(
        lambda d: d["last_good"]["windows"].update(
            seven_day_opus={"utilization": 0.1, "resets_at": FIVE_RESET}
        )
    ),
    "bool_value": _edit(
        lambda d: d["last_good"]["windows"]["five_hour"].update(utilization=True)
    ),
    "large_value": _edit(
        lambda d: d["last_good"]["windows"]["five_hour"].update(utilization=71)
    ),
    "text_time": _edit(lambda d: d["last_good"].update(at="now")),
}


@pytest.mark.parametrize("kind", sorted(BAD_STATES))
def test_f2p_977_09_corrupt_state_is_no_last_value(rig: Rig, kind: str) -> None:
    assert rig.read()[0] == 0
    path = rig.home / "state.json"
    path.write_bytes(BAD_STATES[kind](path.read_bytes()))
    assert rig.ug.load_state(rig.home).last_good is None
    code, out = rig.run("status", at=T0 + 5)
    assert code == 0
    assert "no reading" in out
    assert "%" not in out
    assert rig.if_due(T0 + 10)
    assert rig.state()["schema"] == "usage-guard-state/1"
    assert rig.state()["last_good"]["at"] == T0 + 10


def test_f2p_977_09_good_state_round_trip(rig: Rig) -> None:
    assert rig.read()[0] == 0
    path = rig.home / "state.json"
    raw = path.read_bytes()
    state = rig.ug.load_state(rig.home)
    assert state.last_good is not None
    rig.ug.save_state(rig.home, state)
    assert path.read_bytes() == raw
    assert raw.endswith(b"\n") and b"\r" not in raw
    assert [p.name for p in rig.home.iterdir() if "state" in p.name] == ["state.json"]


def test_f2p_977_09_kill_before_the_replace_keeps_the_old_file(rig: Rig) -> None:
    assert rig.read()[0] == 0
    path = rig.home / "state.json"
    old = path.read_bytes()
    rig.stream("at_95")
    marker = rig.bin / "marker.txt"
    proc = rig.process("read", mode="hang-replace", at=T0 + 60)
    try:
        _wait(marker.exists)
    finally:
        proc.kill()
        proc.communicate(timeout=30)
    temp = Path(marker.read_text(encoding="utf-8"))
    assert temp.parent.resolve() == rig.home.resolve()
    assert temp.name != "state.json"
    assert (
        json.loads(temp.read_text(encoding="utf-8"))["schema"] == "usage-guard-state/1"
    )
    assert path.read_bytes() == old
    assert rig.read(at=T0 + 700)[0] == 0
    assert rig.state()["last_good"]["at"] == T0 + 700


def test_f2p_977_09_two_processes_make_one_request(rig: Rig) -> None:
    (rig.bin / "gate").write_text("")
    first = rig.process("read", "--no-mail")
    second: subprocess.Popen[str] | None = None
    try:
        _wait(lambda: len(rig.calls()) == 1)
        second = rig.process("read", "--no-mail")
        out, _err = second.communicate(timeout=60)
        assert second.returncode == 0, out
        assert out.split() == ["busy"]
        assert len(rig.calls()) == 1
        (rig.bin / "gate").unlink()
        out, _err = first.communicate(timeout=60)
        assert first.returncode == 0, out
    finally:
        for proc in (first, second):
            if proc is not None and proc.poll() is None:
                proc.kill()
                proc.communicate(timeout=30)
    assert len(rig.calls()) == 1
    assert rig.state()["last_good"]["at"] == T0


def test_f2p_977_09_lock_of_a_dead_process_is_free(rig: Rig) -> None:
    (rig.bin / "gate").write_text("")
    proc = rig.process("read")
    try:
        _wait(lambda: len(rig.calls()) == 1)
    finally:
        proc.kill()
        proc.communicate(timeout=30)
        (rig.bin / "gate").unlink()
    code, out = rig.read("--no-mail", at=T0 + 1)
    assert code == 0, out
    assert len(rig.calls()) == 2


def test_f2p_977_09_state_that_cannot_be_written_makes_no_request(rig: Rig) -> None:
    (rig.home / "state.json").mkdir()
    (rig.home / "state.json" / "x").write_text("")
    assert rig.read()[0] != 0
    assert rig.calls() == []


# ── AC-977.10: the email ────────────────────────────────────────────────


def _local(epoch: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(epoch))


def test_f2p_977_10_one_email_at_95(rig: Rig) -> None:
    rig.stream("at_95")
    assert rig.read()[0] == 0
    (text,) = rig.mails("blocked")
    assert "95" in text and _local(FIVE_RESET) in text
    assert rig.read(at=T0 + 600)[0] == 0
    assert len(rig.mails("blocked")) == 1


def test_f2p_977_10_one_email_at_99_says_no_hold(rig: Rig) -> None:
    rig.stream("at_99")
    assert rig.read()[0] == 0
    (text,) = rig.mails("blocked")
    assert "99" in text and _local(FIVE_RESET) in text
    assert "no hold is installed" in text.lower()
    assert rig.read(at=T0 + 600)[0] == 0
    assert len(rig.mails("blocked")) == 1


def test_f2p_977_10_no_95_email_after_the_99_email(rig: Rig) -> None:
    rig.stream("at_99")
    assert rig.read()[0] == 0
    rig.raw(_event({"five_hour": _win(0.97)}))
    assert rig.read(at=T0 + 600)[0] == 0
    assert len(rig.mails("blocked")) == 1


def test_f2p_977_10_95_then_99_gives_two(rig: Rig) -> None:
    for step, name in enumerate(("at_95", "at_99", "at_99")):
        rig.stream(name)
        assert rig.read(at=T0 + 600 * step)[0] == 0
    texts = rig.mails("blocked")
    assert len(texts) == 2
    assert "no hold" not in texts[0].lower()
    assert "no hold" in texts[1].lower()


def test_f2p_977_10_under_95_sends_nothing(rig: Rig) -> None:
    rig.raw(_event({"five_hour": _win(0.9499)}))
    assert rig.read()[0] == 0
    assert rig.mails() == []


@pytest.mark.parametrize("value", [0.95, 0.99])
@pytest.mark.parametrize(("shift", "mails"), [(600, 1), (-600, 1), (601, 2)])
def test_f2p_977_10_same_window_rule(
    rig: Rig, value: float, shift: int, mails: int
) -> None:
    rig.raw(_event({"five_hour": _win(value)}))
    assert rig.read()[0] == 0
    rig.raw(_event({"five_hour": _win(value, FIVE_RESET + shift)}))
    assert rig.read(at=T0 + 600)[0] == 0
    assert len(rig.mails("blocked")) == mails


def test_f2p_977_10_each_window_has_its_email(rig: Rig) -> None:
    rig.raw(_event({"five_hour": _win(0.96), "seven_day": _win(0.96, FIVE_RESET)}))
    assert rig.read()[0] == 0
    assert rig.read(at=T0 + 600)[0] == 0
    assert len(rig.mails("blocked")) == 2


@pytest.mark.parametrize("name", ["rejected", "overage"])
def test_f2p_977_10_rejected_and_overage_email(rig: Rig, name: str) -> None:
    rig.stream(name)
    assert rig.read()[0] == 0
    (text,) = rig.mails("blocked")
    assert "no hold is installed" in text.lower()
    assert rig.read(at=T0 + 600)[0] == 0
    assert len(rig.mails("blocked")) == 1


def test_f2p_977_10_other_account_has_its_own_email(rig: Rig) -> None:
    rig.stream("at_99")
    assert rig.read()[0] == 0
    rig.account(ACCOUNT_B)
    assert rig.read(at=T0 + 600)[0] == 0
    assert len(rig.mails("blocked")) == 2


def test_f2p_977_10_no_mail_flag(rig: Rig) -> None:
    rig.stream("at_99")
    assert rig.read("--no-mail")[0] == 0
    assert rig.mails() == []
    assert rig.read(at=T0 + 600)[0] == 0
    assert len(rig.mails("blocked")) == 1


NOT_SENT: dict[str, list[dict[str, Any]]] = {
    "no_line": [],
    "smtp_error": [{"outcome": "smtp_error"}],
    "dry_run": [{"outcome": "dry_run"}],
    "hourly_cap": [{"outcome": "hourly_cap"}],
    "other_session": [
        {"outcome": "smtp_error"},
        {"outcome": "sent", "harness": "claude"},
    ],
    "only_other_session": [{"outcome": "sent", "harness": "claude"}],
    "only_other_class": [{"outcome": "sent", "class": "done"}],
    "sent_and_error": [{"outcome": "sent"}, {"outcome": "smtp_error"}],
    "lock_timeout_only": [{"outcome": "state_lock_timeout"}],
    "no_outcome": [{}],
}


@pytest.mark.parametrize("kind", sorted(NOT_SENT))
def test_f2p_977_10_not_sent_is_tried_again(rig: Rig, kind: str) -> None:
    rig.plan(NOT_SENT[kind])
    rig.stream("at_99")
    assert rig.read()[0] == 0
    assert len(rig.mails("blocked")) == 1
    last = rig.status()["last_email"]
    assert last is None or last["outcome"] != "sent"
    rig.plan([{"outcome": "sent"}])
    assert rig.read(at=T0 + 300)[0] == 0
    assert len(rig.mails("blocked")) == 2
    assert rig.status()["last_email"]["outcome"] == "sent"
    assert rig.read(at=T0 + 600)[0] == 0
    assert len(rig.mails("blocked")) == 2


def test_f2p_977_10_failed_send_is_tried_again_by_a_failed_reading(rig: Rig) -> None:
    rig.plan([])
    rig.stream("at_99")
    assert rig.read()[0] == 0
    rig.plan([{"outcome": "sent"}])
    rig.stream("no_event")
    assert rig.read(at=T0 + 300)[0] != 0
    assert len(rig.mails("blocked")) == 2


@pytest.mark.parametrize(
    "lines",
    [
        [{"outcome": "state_lock_timeout"}, {"outcome": "sent"}],
        [{"outcome": "sent"}, {"outcome": "smtp_error", "harness": "claude"}],
        [{"outcome": "sent"}, {"outcome": "smtp_error", "class": "done"}],
    ],
)
def test_f2p_977_10_sent_with_foreign_lines(
    rig: Rig, lines: list[dict[str, Any]]
) -> None:
    rig.plan(lines)
    rig.stream("at_99")
    assert rig.read()[0] == 0
    assert rig.read(at=T0 + 600)[0] == 0
    assert len(rig.mails("blocked")) == 1


def _old_log(rig: Rig, count: int) -> None:
    line = json.dumps({"outcome": "sent", "class": "blocked", "harness": "manual"})
    path = rig.notify_home / "state" / "notify.log.jsonl"
    path.write_text((line + "\n") * count, encoding="utf-8", newline="\n")


def test_f2p_977_10_old_lines_do_not_count(rig: Rig) -> None:
    _old_log(rig, 5)
    rig.plan([])
    rig.stream("at_99")
    assert rig.read()[0] == 0
    assert rig.read(at=T0 + 600)[0] == 0
    assert len(rig.mails("blocked")) == 2


@pytest.mark.parametrize(("outcome", "mails"), [("sent", 1), ("smtp_error", 2)])
def test_f2p_977_10_rotated_log_counts_from_its_start(
    rig: Rig, outcome: str, mails: int
) -> None:
    _old_log(rig, 50)
    rig.plan([{"outcome": outcome}], truncate=True)
    rig.stream("at_99")
    assert rig.read()[0] == 0
    rig.plan([{"outcome": "sent"}])
    assert rig.read(at=T0 + 600)[0] == 0
    assert len(rig.mails("blocked")) == mails


def test_f2p_977_10_hanging_notifier_is_a_failed_send(rig: Rig) -> None:
    rig.plan([{"outcome": "sent"}], sleep=30)
    rig.stream("at_99")
    started = time.monotonic()
    assert rig.read(deps=rig.deps(mail_limit_s=0.5))[0] == 0
    assert time.monotonic() - started < 20
    rig.plan([{"outcome": "sent"}])
    assert rig.read(at=T0 + 600)[0] == 0
    assert rig.status(T0 + 600)["last_email"]["outcome"] == "sent"


def test_f2p_977_10_not_readable_after_1800(rig: Rig) -> None:
    rig.stream("no_event")
    for offset in (0, 600, 1200, 1799):
        rig.active_at(T0 + offset)
        assert rig.read(at=T0 + offset)[0] != 0
    assert rig.mails() == []
    for offset in (1800, 2400, 5000):
        rig.active_at(T0 + offset)
        assert rig.read(at=T0 + offset)[0] != 0
    assert len(rig.mails("error")) == 1
    assert len(rig.mails()) == 1


def test_f2p_977_10_good_reading_starts_the_1800_again(rig: Rig) -> None:
    steps = [(0, "no_event"), (1000, "allowed"), (1100, "no_event"), (2899, "no_event")]
    for offset, name in steps:
        rig.stream(name)
        rig.active_at(T0 + offset)
        rig.read(at=T0 + offset)
    assert rig.mails() == []
    rig.active_at(T0 + 2900)
    rig.read(at=T0 + 2900)
    assert len(rig.mails("error")) == 1


def test_f2p_977_10_not_readable_needs_a_working_session(rig: Rig) -> None:
    rig.stream("no_event")
    rig.read(at=T0)
    rig.active_at(T0)
    rig.read(at=T0 + 1900)
    assert rig.mails() == []
    rig.active_at(T0 + 1950)
    rig.read(at=T0 + 2000)
    assert len(rig.mails("error")) == 1


def test_f2p_977_10_new_failure_period_has_its_email(rig: Rig) -> None:
    for offset, name in ((0, "no_event"), (1800, "no_event"), (2000, "allowed")):
        rig.stream(name)
        rig.active_at(T0 + offset)
        rig.read(at=T0 + offset)
    assert len(rig.mails("error")) == 1
    rig.stream("no_event")
    for offset in (2100, 3900):
        rig.active_at(T0 + offset)
        rig.read(at=T0 + offset)
    assert len(rig.mails("error")) == 2


def test_f2p_977_10_not_readable_failed_send_is_tried_again(rig: Rig) -> None:
    rig.stream("no_event")
    rig.plan([{"outcome": "smtp_error"}])
    for offset in (0, 1800, 2400):
        rig.active_at(T0 + offset)
        rig.read(at=T0 + offset)
    assert len(rig.mails("error")) == 2


def _notify_config(rig: Rig) -> None:
    address = "@".join(("someone", "example.invalid"))
    config = {
        "version": 1,
        "enabled": True,
        "to": [address],
        "from": address,
        "smtp": {"user": address},
    }
    (rig.notify_home / "notify.json").write_text(json.dumps(config), encoding="utf-8")


def test_f2p_977_10_real_notifier_in_dry_run(rig: Rig) -> None:
    """The real notifier with a scratch home: a dry run is a log line, never a sent email."""
    _notify_config(rig)
    (rig.home / "agent_notify.py").write_bytes(NOTIFY.read_bytes())
    deps = rig.deps(notifier=None, mail_dry_run=True)
    rig.stream("at_99")
    code, out = rig.read(deps=deps)
    assert code == 0, out
    (line,) = _jsonl(rig.notify_home / "state" / "notify.log.jsonl")
    assert (line["outcome"], line["class"], line["harness"]) == (
        "dry_run",
        "blocked",
        "manual",
    )
    (mail,) = rig.notify_home.rglob("*.eml")
    message: Any = email.message_from_bytes(
        mail.read_bytes(), policy=email.policy.default
    )
    body = message.get_content()
    assert "99" in body and _local(FIVE_RESET) in body
    last = rig.status()["last_email"]
    assert last is None or last["outcome"] != "sent"


def test_f2p_977_10_no_notifier_copy_is_a_failed_send(rig: Rig) -> None:
    rig.stream("at_99")
    assert rig.read(deps=rig.deps(notifier=None))[0] == 0
    assert rig.read(at=T0 + 600)[0] == 0
    assert len(rig.mails("blocked")) == 1


def test_f2p_977_10_send_arguments(rig: Rig) -> None:
    rig.stream("at_99")
    assert rig.read()[0] == 0
    (argv,) = _jsonl(rig.bin / "mails.jsonl")
    assert argv[0] == "send"
    assert argv[argv.index("--class") + 1] == "blocked"
    assert Path(argv[argv.index("--home") + 1]) == rig.notify_home
    assert "--dry-run" not in argv


# ── AC-977.11: status ───────────────────────────────────────────────────


def test_f2p_977_11_no_state_is_no_reading(rig: Rig) -> None:
    code, out = rig.run("status")
    assert code == 0
    assert "no reading" in out
    assert "%" not in out
    data = rig.status()
    assert all(w["percent"] is None for w in data["windows"].values())
    assert "0%" not in out.replace(" ", "")


def test_f2p_977_11_text_and_json(rig: Rig) -> None:
    rig.stream("at_95")
    assert rig.read()[0] == 0
    rig.stream("no_event")
    assert rig.read(at=T0 + 120)[0] != 0
    data = rig.status(T0 + 180)
    five = data["windows"]["five_hour"]
    assert five["percent"] == pytest.approx(95.0)
    assert five["resets_at"] == FIVE_RESET
    assert data["age_s"] == 180
    assert data["last_error"] == "no_event"
    assert data["last_email"]["at"] == T0
    assert data["task"] == "absent"
    assert data["pause"] == "none"
    code, out = rig.run("status", at=T0 + 180)
    assert code == 0
    for part in (
        "five_hour",
        "95",
        "seven_day",
        "21",
        _local(FIVE_RESET),
        "no_event",
        "absent",
    ):
        assert part in out


def test_f2p_977_11_seven_day_only_shows_no_five_hour_percent(rig: Rig) -> None:
    rig.stream("seven_day_only")
    assert rig.read()[0] == 0
    windows = rig.status()["windows"]
    assert windows["seven_day"]["percent"] == pytest.approx(21.0)
    assert "five_hour" not in windows or windows["five_hour"]["percent"] is None


def test_f2p_977_11_pause_states(rig: Rig) -> None:
    rig.pause(origin="auto", end_at=T0 + 100)
    data = rig.status()
    assert data["pause"] == "auto"
    assert data["pause_end_at"] == T0 + 100
    for raw in (
        b"{",
        b"[]",
        b'{"schema": "usage-guard-pause/1"}',
        rig.pause() + b" " * 4096,
        rig.pause().replace(b'"windows"', b'"extra": 1, "windows"'),
        rig.pause().replace(b'"user"', b'"other"'),
        rig.pause(end_at=T0 + 691_201 + 10),
    ):
        (rig.home / "pause.json").write_bytes(raw)
        assert rig.status()["pause"] == "pause_bad", raw
        assert "pause_bad" in rig.run("status")[1]


def test_f2p_977_11_starts_only_a_task_query_and_writes_nothing(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig.stream("at_99")
    assert rig.read("--no-mail")[0] == 0
    before = rig.files()
    seen: list[list[str]] = []
    real: Any = subprocess.Popen

    class Recorder(real):
        def __init__(self, args: Any, *rest: Any, **kw: Any) -> None:
            seen.append([str(a) for a in args])
            super().__init__(args, *rest, **kw)

    monkeypatch.setattr(subprocess, "Popen", Recorder)
    assert rig.run("status")[0] == 0
    assert rig.run("status", "--json")[0] == 0
    assert len(seen) == 2
    for args in seen:
        assert args[:2] == list(rig.deps().schtasks)
        assert args[2] == "/Query"
    assert rig.files() == before
    assert len(rig.calls()) == 1
    assert rig.mails() == []


def test_f2p_977_11_task_states(rig: Rig) -> None:
    assert rig.status()["task"] == "absent"
    assert rig.install()[0] == 0
    assert rig.status()["task"] == "ready"
    assert rig.status()["install"] == "ok"
    (rig.home / "agent_notify.py").write_bytes(b"changed")
    assert rig.status()["install"] == "drift"


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.update(extra=1),
        lambda d: d.update(parts=["task", "other"]),
        lambda d: d.update(parts=[]),
        lambda d: d.update(parts=["task", "hook"]),
        lambda d: d["files"].update({"other.py": "0" * 64}),
        lambda d: d["files"].pop("agent_notify.py"),
        lambda d: d.update(schema="x"),
    ],
)
def test_f2p_977_11_refused_manifest_is_drift(
    rig: Rig, change: Callable[[dict[str, Any]], object]
) -> None:
    assert rig.install()[0] == 0
    path = rig.home / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8")
    assert rig.status()["install"] == "drift"


# ── AC-977.12: install and uninstall ────────────────────────────────────


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _task_xml(rig: Rig) -> ET.Element:
    text = (rig.bin / "task.xml").read_bytes().decode("utf-16")
    return ET.fromstring(re.sub(r"^\s*<\?xml[^>]*\?>", "", text))


def _verbs(rig: Rig) -> list[str]:
    return [argv[0] for argv in rig.sched()]


def _snapshot(rig: Rig) -> dict[str, tuple[bytes, int]]:
    return {k: (v, (rig.home / k).stat().st_mtime_ns) for k, v in rig.files().items()}


def test_f2p_977_12_install_copies_files_and_manifest(rig: Rig) -> None:
    code, out = rig.install()
    assert code == 0, out
    assert set(rig.files()) == {"usage_guard.py", "agent_notify.py", "manifest.json"}
    assert not (rig.home / "usage_guard_hook.py").exists()
    for name in ("usage_guard.py", "agent_notify.py"):
        assert (rig.home / name).read_bytes() == (rig.source / name).read_bytes()
    data = json.loads((rig.home / "manifest.json").read_text(encoding="utf-8"))
    assert data["schema"] == "usage-guard-manifest/1"
    assert data["parts"] == ["task"]
    assert data["files"] == {
        name: _sha(rig.source / name) for name in ("usage_guard.py", "agent_notify.py")
    }
    assert Path(data["python"]) == rig.python


def test_f2p_977_12_task_definition(rig: Rig) -> None:
    assert rig.install()[0] == 0
    (create,) = [a for a in rig.sched() if a[0] == "/Create"]
    assert "/F" not in [a.upper() for a in create]
    assert create[create.index("/TN") + 1] == "ClaudeUsageGuard"
    assert not Path(create[create.index("/XML") + 1]).exists(), (
        "the XML file stays behind"
    )
    root = _task_xml(rig)
    assert root.tag == TASK_NS + "Task"

    def one(tag: str) -> str:
        (node,) = root.iter(TASK_NS + tag)
        return (node.text or "").strip()

    home = rig.home.as_posix()
    assert Path(one("Command")) == rig.pythonw
    args = one("Arguments").replace("\\", "/").replace('"', "")
    assert args == f"-I {home}/usage_guard.py read --if-due --home {home}"
    assert f'"{home}/usage_guard.py"' in one("Arguments").replace("\\", "/")
    (interval,) = [n for n in root.iter(TASK_NS + "Interval")]
    assert interval.text == "PT5M"
    assert one("MultipleInstancesPolicy") == "IgnoreNew"
    assert one("ExecutionTimeLimit") == "PT4M"
    assert one("LogonType") == "InteractiveToken"
    assert one("RunLevel") == "LeastPrivilege"
    assert one("DisallowStartIfOnBatteries") == "false"
    assert one("StopIfGoingOnBatteries") == "false"
    assert not list(root.iter(TASK_NS + "Password"))


def test_f2p_977_12_xml_special_characters(rig: Rig, tmp_path: Path) -> None:
    rig.home = tmp_path / "a & b's home"
    rig.home.mkdir()
    assert rig.install()[0] == 0
    (node,) = _task_xml(rig).iter(TASK_NS + "Arguments")
    assert rig.home.as_posix() in (node.text or "").replace("\\", "/")
    assert rig.install()[0] == 0
    assert _verbs(rig).count("/Create") == 1


def test_f2p_977_12_second_install_changes_nothing(rig: Rig) -> None:
    assert rig.install()[0] == 0
    before, task = _snapshot(rig), (rig.bin / "task.xml").read_bytes()
    code, out = rig.install(at=T0 + 5000)
    assert code == 0, out
    assert _snapshot(rig) == before
    assert (rig.bin / "task.xml").read_bytes() == task
    assert _verbs(rig).count("/Create") == 1


def test_f2p_977_12_install_updates_its_own_files(rig: Rig) -> None:
    assert rig.install()[0] == 0
    (rig.source / "agent_notify.py").write_bytes(b"# newer\n")
    assert rig.install(at=T0 + 5000)[0] == 0
    assert (rig.home / "agent_notify.py").read_bytes() == b"# newer\n"
    assert rig.status()["install"] == "ok"


def test_f2p_977_12_lost_task_is_made_again(rig: Rig) -> None:
    assert rig.install()[0] == 0
    (rig.bin / "task.xml").unlink()
    assert rig.install()[0] == 0
    assert (rig.bin / "task.xml").exists()


def _foreign_task(rig: Rig) -> bytes:
    text = (
        '<?xml version="1.0" encoding="UTF-16"?>'
        '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
        '<Actions Context="Author"><Exec><Command>C:\\other\\run.exe</Command>'
        "<Arguments>go</Arguments></Exec></Actions></Task>"
    )
    raw = text.encode("utf-16")
    (rig.bin / "task.xml").write_bytes(raw)
    return raw


def test_f2p_977_12_foreign_task_is_refused(rig: Rig) -> None:
    raw = _foreign_task(rig)
    code, out = rig.install()
    assert code == 1
    assert "task_foreign" in out
    assert rig.files() == {}
    assert (rig.bin / "task.xml").read_bytes() == raw
    assert set(_verbs(rig)) == {"/Query"}
    assert rig.status()["task"] == "foreign"


def test_f2p_977_12_foreign_task_with_two_actions_is_refused(rig: Rig) -> None:
    assert rig.install()[0] == 0
    text = (rig.bin / "task.xml").read_bytes().decode("utf-16")
    extra = "<Exec><Command>C:\\other\\run.exe</Command></Exec></Actions>"
    raw = text.replace("</Actions>", extra).encode("utf-16")
    (rig.bin / "task.xml").write_bytes(raw)
    code, out = rig.install()
    assert code == 1
    assert "task_foreign" in out
    assert (rig.bin / "task.xml").read_bytes() == raw


def test_f2p_977_12_unreadable_task_is_foreign(rig: Rig) -> None:
    (rig.bin / "task.xml").write_bytes("no xml".encode("utf-16"))
    assert rig.install()[0] == 1
    assert set(_verbs(rig)) == {"/Query"}


def test_f2p_977_12_failed_create_leaves_no_half_install(rig: Rig) -> None:
    (rig.bin / "fail-create").write_text("")
    code, out = rig.install()
    assert code == 1, out
    assert rig.files() == {}
    assert rig.status()["install"] == "absent"


def test_f2p_977_12_failed_create_keeps_the_old_install(rig: Rig) -> None:
    assert rig.install()[0] == 0
    before = rig.files()
    (rig.bin / "task.xml").unlink()
    (rig.bin / "fail-create").write_text("")
    (rig.source / "agent_notify.py").write_bytes(b"# newer\n")
    assert rig.install(at=T0 + 10)[0] == 1
    assert rig.files() == before


def test_f2p_977_12_foreign_file_is_not_overwritten(rig: Rig) -> None:
    (rig.home / "agent_notify.py").write_bytes(b"mine")
    assert rig.install()[0] == 1
    assert rig.files() == {"agent_notify.py": b"mine"}
    assert "/Create" not in _verbs(rig)


def test_f2p_977_12_missing_source_or_python_is_refused(rig: Rig) -> None:
    rig.pythonw.unlink()
    assert rig.install()[0] == 1
    rig.pythonw.write_bytes(b"")
    (rig.source / "agent_notify.py").unlink()
    assert rig.install()[0] == 1
    assert rig.files() == {}
    assert "/Create" not in _verbs(rig)


def test_f2p_977_12_uninstall_removes_the_part(rig: Rig) -> None:
    assert rig.install()[0] == 0
    (rig.home / "backup").mkdir()
    (rig.home / "backup" / "settings-x.json").write_bytes(b"{}")
    (rig.home / "notes.txt").write_bytes(b"mine")
    code, out = rig.uninstall()
    assert code == 0, out
    assert rig.files() == {"backup/settings-x.json": b"{}", "notes.txt": b"mine"}
    assert not (rig.bin / "task.xml").exists()
    assert rig.uninstall()[0] == 0


def test_f2p_977_12_uninstall_keeps_a_foreign_task(rig: Rig) -> None:
    assert rig.install()[0] == 0
    raw = _foreign_task(rig)
    _code, out = rig.uninstall()
    assert "task_foreign" in out
    assert (rig.bin / "task.xml").read_bytes() == raw
    assert "/Delete" not in _verbs(rig)


def test_f2p_977_12_uninstall_without_manifest_keeps_files(rig: Rig) -> None:
    (rig.home / "agent_notify.py").write_bytes(b"mine")
    rig.uninstall()
    assert rig.files() == {"agent_notify.py": b"mine"}


def test_f2p_977_12_failed_delete_keeps_the_files(rig: Rig) -> None:
    assert rig.install()[0] == 0
    before = rig.files()
    (rig.bin / "fail-delete").write_text("")
    assert rig.uninstall()[0] == 1
    assert rig.files() == before


def test_f2p_977_12_uninstall_keeps_files_of_a_second_part(rig: Rig) -> None:
    assert rig.install()[0] == 0
    hook = rig.home / "usage_guard_hook.py"
    hook.write_bytes(b"# hook\n")
    path = rig.home / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["parts"] = ["task", "hook"]
    data["files"]["usage_guard_hook.py"] = _sha(hook)
    path.write_text(json.dumps(data), encoding="utf-8")
    assert rig.status()["install"] == "ok"
    assert rig.uninstall()[0] == 0
    assert set(rig.files()) == {
        "usage_guard.py",
        "agent_notify.py",
        "usage_guard_hook.py",
        "manifest.json",
    }
    after = json.loads(path.read_text(encoding="utf-8"))
    assert after["parts"] == ["hook"]
    assert after["files"] == data["files"]
    assert not (rig.bin / "task.xml").exists()
    assert rig.status()["install"] == "ok"


def test_f2p_977_12_task_install_keeps_a_second_part(rig: Rig) -> None:
    assert rig.install()[0] == 0
    hook = rig.home / "usage_guard_hook.py"
    hook.write_bytes(b"# hook\n")
    path = rig.home / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["parts"] = ["hook"]
    data["files"]["usage_guard_hook.py"] = _sha(hook)
    path.write_text(json.dumps(data), encoding="utf-8")
    assert rig.install()[0] == 0
    after = json.loads(path.read_text(encoding="utf-8"))
    assert sorted(after["parts"]) == ["hook", "task"]
    assert after["files"] == data["files"]
    assert hook.read_bytes() == b"# hook\n"


# ── AC-977.13: privacy ──────────────────────────────────────────────────


def test_f2p_977_13_markers_appear_nowhere(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    address = "@".join(("marker-addr", "zq.invalid"))
    markers = {
        "account": "marker-account-7731",
        "address": address,
        "env": "marker-env-7732",
        "key": "marker-key-7733",
        "text": "marker-text-7734",
        "stderr": "marker-stderr-7735",
        "status": "marker-status-7736",
        "value": "marker-value-7737",
    }
    monkeypatch.setenv("USAGE_GUARD_MARK", markers["env"])
    monkeypatch.setenv("ANTHROPIC_API_KEY", markers["key"])
    rig.account_file.write_text(
        json.dumps(
            {
                "oauthAccount": {
                    "accountUuid": markers["account"],
                    "emailAddress": address,
                }
            }
        ),
        encoding="utf-8",
    )
    (rig.bin / "stderr.txt").write_text(markers["stderr"])
    text = json.dumps({"type": "assistant", "text": markers["text"]}).encode() + b"\n"
    outputs: list[str] = []
    streams = (
        text + _stream("at_99"),
        text + _event({"five_hour": _win(0.2)}, status=markers["status"]),
        text
        + _event(
            {"five_hour": _win(1.0)}, status="rejected", limit_type=markers["status"]
        ),
        text + _event({"five_hour": _win(markers["value"])}),
        text + _event({"five_hour": _win(0.1, markers["value"])}),
        text + _event({markers["value"]: _win(0.1)}),
        text,
    )
    for step, data in enumerate(streams):
        when = T0 + 600 * step
        rig.active_at(when)
        rig.raw(data)
        outputs.append(rig.read(at=when)[1])
        outputs.append(rig.run("status", at=when)[1])
        outputs.append(rig.run("status", "--json", at=when)[1])
    outputs.append(rig.install()[1])
    outputs.append(rig.run("status")[1])
    outputs.append(rig.uninstall()[1])
    everything = [*outputs, *rig.mails()]
    for path in sorted((*rig.home.rglob("*"), *rig.notify_home.rglob("*"))):
        if path.is_file():
            everything.append(path.read_bytes().decode("utf-8", "replace"))
    assert rig.mails("blocked")
    joined = "\n".join(everything)
    for name, marker in markers.items():
        assert marker not in joined, name
    state = (rig.home / "state.json").read_text(encoding="utf-8")
    assert "@" not in state
    assert "sk-ant-" not in state and "accessToken" not in state
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}", state)


# ── Boundary: command line, constants and imports ───────────────────────


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["other"],
        ["read", "--home", "relative/path"],
        ["read", "--unknown"],
        ["read", "--if-d"],
        ["status", "--js"],
        ["install", "--part", "other"],
        ["uninstall", "--part", "other"],
    ],
)
def test_f2p_977_14_bad_arguments_exit_2(rig: Rig, argv: list[str]) -> None:
    full = argv if "--home" in argv or not argv else [*argv, "--home", str(rig.home)]
    with pytest.raises(SystemExit) as caught:
        rig.ug.main(full, deps=rig.deps(), now=lambda: T0)
    assert caught.value.code == 2
    assert rig.files() == {}
    assert rig.calls() == []


def test_f2p_977_14_constants(ug: Any) -> None:
    assert (ug.PAUSE_AT, ug.WARN_AT) == (0.99, 0.95)
    assert (ug.POLL_S, ug.POLL_NEAR_S, ug.NEAR_AT) == (600, 300, 0.90)
    assert (ug.ACTIVITY_S, ug.UNREADABLE_S, ug.RESET_MARGIN_S) == (900, 1800, 60)
    assert (ug.UTILIZATION_MAX, ug.PAUSE_MAX_S, ug.SAME_WINDOW_S) == (2.0, 691_200, 600)
    assert (ug.READ_LIMIT_S, ug.MAIL_LIMIT_S) == (90, 60)


def test_f2p_977_14_default_paths(ug: Any) -> None:
    """The guard has no default home, no default interpreter and no notifier home."""
    deps = ug.Deps()
    assert not hasattr(ug, "HOME_DIR") and not hasattr(ug, "DEFAULT_PYTHON")
    assert deps.notify_home is None
    assert deps.claude is None and deps.notifier is None
    assert deps.mail_dry_run is False


def test_f2p_977_14_notify_home_order(
    ug: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The notifier home: the ``Deps`` value, the notifier variable, the registry, the user."""
    user = tmp_path / "user"
    monkeypatch.setattr(Path, "home", lambda: user)
    explicit = tmp_path / "explicit"
    named = tmp_path / "named"
    registry = tmp_path / "registry"
    both = {"AGENT_NOTIFY_HOME": str(named), "AGENT_MODEL_REGISTRY_HOME": str(registry)}
    assert ug.notify_home_of(ug.Deps(notify_home=explicit, env=both)) == explicit
    assert ug.notify_home_of(ug.Deps(env=both)) == named
    empty = {"AGENT_NOTIFY_HOME": "", "AGENT_MODEL_REGISTRY_HOME": str(registry)}
    assert ug.notify_home_of(ug.Deps(env=empty)) == registry / "notify"
    assert ug.notify_home_of(ug.Deps(env={})) == user / ".agent" / "notify"
    monkeypatch.setenv("AGENT_NOTIFY_HOME", str(named))
    assert ug.notify_home_of(ug.Deps()) == named


def test_f2p_977_14_send_uses_the_notifier_lookup(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a notifier home in ``Deps``, the send names the home of the lookup."""
    monkeypatch.setenv("AGENT_NOTIFY_HOME", str(rig.notify_home))
    rig.stream("at_99")
    assert rig.read(deps=rig.deps(notify_home=None))[0] == 0
    (argv,) = _jsonl(rig.bin / "mails.jsonl")
    assert Path(argv[argv.index("--home") + 1]) == rig.notify_home
    assert rig.status()["last_email"]["outcome"] == "sent"


@pytest.mark.parametrize(
    "argv",
    [
        ["read"],
        ["status"],
        ["pause"],
        ["resume"],
        ["uninstall", "--part", "task"],
        ["install", "--part", "task", "--python", "{python}"],
        ["install", "--part", "task", "--home", "{home}"],
    ],
)
def test_f2p_977_14_home_and_python_are_required(rig: Rig, argv: list[str]) -> None:
    """Each command needs ``--home``; an install also needs ``--python``."""
    full = [word.format(python=rig.python, home=rig.home) for word in argv]
    with pytest.raises(SystemExit) as caught:
        rig.ug.main(full, deps=rig.deps(), now=lambda: T0)
    assert caught.value.code == 2
    assert rig.files() == {}
    assert rig.calls() == []


def test_f2p_977_14_standard_library_only() -> None:
    names: set[str] = set()
    for node in ast.walk(ast.parse(GUARD.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            names.add((node.module or "").split(".")[0])
    assert names and names <= set(sys.stdlib_module_names)


def test_f2p_977_14_runs_isolated_as_a_script(tmp_path: Path) -> None:
    home = tmp_path / "home"
    proc = subprocess.run(
        [sys.executable, "-I", str(GUARD), "read", "--if-due", "--home", "relative"],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 2
    assert "absolute" in proc.stderr
    assert not home.exists()


# ── The unchanged notifier contract that MAIL depends on ────────────────


def _send(home: Path, *flags: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("AGENT_NOTIFY")}
    cmd = [sys.executable, "-I", str(NOTIFY), "send", "--class", "blocked"]
    return subprocess.run(
        [*cmd, "--text", "usage text", "--home", str(home), *flags],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        env=env,
        cwd=home,
        timeout=60,
        check=False,
    )


def test_p2p_977_notifier_exit_0_without_config_has_no_line(tmp_path: Path) -> None:
    assert _send(tmp_path).returncode == 0
    assert not (tmp_path / "state" / "notify.log.jsonl").exists()


def test_p2p_977_notifier_manual_dry_run_line(tmp_path: Path) -> None:
    address = "@".join(("someone", "example.invalid"))
    config = {"version": 1, "enabled": True, "to": [address], "from": address}
    (tmp_path / "notify.json").write_text(
        json.dumps({**config, "smtp": {"user": address}}), encoding="utf-8"
    )
    assert _send(tmp_path, "--dry-run").returncode == 0
    (line,) = _jsonl(tmp_path / "state" / "notify.log.jsonl")
    assert (line["outcome"], line["class"], line["harness"]) == (
        "dry_run",
        "blocked",
        "manual",
    )
