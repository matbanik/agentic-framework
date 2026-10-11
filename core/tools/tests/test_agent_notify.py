"""Tests for the stop notifier ``agent_notify`` (AC-A.1 … AC-A.12).

The file is portable: it finds the module from its own location, so the same
bytes run in any repository that ships ``tools/agent_notify.py`` or a sibling
``agent_notify.py`` (AC-A.13). Each test loads the module inside its body and
isolates it: a temporary notify home, no kill switch inherited from the test
session, a recording SMTP class, a socket layer that refuses to connect, and
injected spawn and credential functions. No test touches a real notify home,
a real credential store or the network.
"""

from __future__ import annotations

import email
import email.message
import email.policy
import getpass
import importlib.util
import io
import json
import os
import re
import smtplib
import socket
import ssl
import statistics
import sys
import threading
import time
import types
from pathlib import Path

import pytest


def _fake(*parts: str) -> str:
    """Join fragments so no credential-shaped literal sits in the source for secret scanners."""
    return "".join(parts)


PASSWORD = _fake("dummy-test-", "pw-QZJX-9w7v")
DOMAIN = "zq-sentinel.invalid"
TO_ADDR = "@".join(("rcpt-qzv", DOMAIN))
FROM_ADDR = "@".join(("from-qzv", DOMAIN))
USER_ADDR = "@".join(("user-qzv", DOMAIN))
SESSION = "sess-0001-aaaa-bbbb"
T0 = 1_800_000_000.0
SKIP_FIELDS = {
    "limit_name",
    "configured_value",
    "observed_value",
    "window",
    "session8",
    "class",
}
SUBJECT_RE = re.compile(r"^\[agent\] \S+ \| [A-Z]+ \| \S+ \| \d{2}:\d{2}$")
DETACHED_PROCESS = 0x00000008


# ── Harness ─────────────────────────────────────────────────────────────


def _module_path() -> Path:
    """Walk up from this file for ``tools/agent_notify.py`` or a sibling copy."""
    here = Path(__file__).resolve().parent
    for base in (here, *here.parents):
        for candidate in (base / "tools" / "agent_notify.py", base / "agent_notify.py"):
            if candidate.is_file():
                return candidate
    raise AssertionError(f"agent_notify.py not found above {here}")


def _load(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    path = _module_path()
    assert path.is_file(), path
    spec = importlib.util.spec_from_file_location("agent_notify", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "agent_notify", mod)
    spec.loader.exec_module(mod)
    return mod


class Recorder:
    """Shared state of the fake SMTP class, the spawn stub and the credential writer."""

    def __init__(self) -> None:
        self.instances: list = []
        self.connect_sleep = 0.0
        self.login_sleep = 0.0
        self.starttls_exc: BaseException | None = None
        self.login_exc: BaseException | None = None
        self.spawned: list[tuple[list[str], int]] = []
        self.stored: list[tuple[str, str, str]] = []

    def spawn(
        self, argv: list[str], creationflags: int, workdir: str | None = None
    ) -> None:
        self.spawned.append((list(argv), creationflags))

    def cred_write(self, target: str, user: str, password: str) -> bool:
        self.stored.append((target, user, password))
        return True

    def messages(self) -> list:
        return [m for inst in self.instances for m in inst.messages]


def _smtp_class(rec: Recorder) -> type:
    class FakeSMTP:
        def __init__(
            self,
            host: str = "",
            port: int = 0,
            *args: object,
            timeout: float | None = None,
            **kw: object,
        ) -> None:
            self.host, self.port, self.timeout = host, port, timeout
            self.calls: list[tuple] = []
            self.messages: list = []
            rec.instances.append(self)
            if rec.connect_sleep:
                time.sleep(rec.connect_sleep)

        def ehlo(self, *args: object, **kw: object) -> tuple[int, bytes]:
            self.calls.append(("ehlo",))
            return 250, b"ok"

        def starttls(
            self, *args: object, context: ssl.SSLContext | None = None, **kw: object
        ) -> tuple[int, bytes]:
            self.calls.append(("starttls", context))
            if rec.starttls_exc is not None:
                raise rec.starttls_exc
            return 220, b"ready"

        def login(
            self, user: str, password: str, *args: object, **kw: object
        ) -> tuple[int, bytes]:
            self.calls.append(("login", user, password))
            if rec.login_sleep:
                time.sleep(rec.login_sleep)
            if rec.login_exc is not None:
                raise rec.login_exc
            return 235, b"ok"

        def send_message(self, msg: object, *args: object, **kw: object) -> dict:
            self.calls.append(("send_message",))
            self.messages.append(msg)
            return {}

        def quit(self) -> tuple[int, bytes]:
            self.calls.append(("quit",))
            return 221, b"bye"

        def close(self) -> None:
            self.calls.append(("close",))

        def __enter__(self) -> FakeSMTP:
            return self

        def __exit__(self, *exc: object) -> bool:
            self.close()
            return False

    return FakeSMTP


def _refuse(*args: object, **kw: object) -> None:
    raise OSError("network disabled in tests")


def _write_json(path: Path, doc: dict) -> None:
    path.write_text(json.dumps(doc), encoding="utf-8")


def _local(**over: object) -> dict:
    doc: dict = {
        "enabled": True,
        "to": [TO_ADDR],
        "from": FROM_ADDR,
        "smtp": {"user": USER_ADDR},
    }
    doc.update(over)
    return doc


def _setup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    shared: dict | None = None,
    local: dict | None = None,
) -> tuple[types.ModuleType, Path, Recorder]:
    mod = _load(monkeypatch)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    _write_json(home / "notify.json", {"version": 1, **(shared or {})})
    _write_json(home / "notify.local.json", _local() if local is None else local)
    for name in ("AGENT_NOTIFY", "AGENT_NOTIFY_DRY_RUN", "AGENT_MODEL_REGISTRY_HOME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AGENT_NOTIFY_HOME", str(home))
    monkeypatch.setenv("AGENT_NOTIFY_SMTP_PASSWORD", PASSWORD)
    rec = Recorder()
    monkeypatch.setattr(smtplib, "SMTP", _smtp_class(rec))
    monkeypatch.setattr(socket, "create_connection", _refuse)
    monkeypatch.setattr(mod, "_spawn", rec.spawn)
    monkeypatch.setattr(mod, "_cred_read", lambda target: None)
    monkeypatch.setattr(mod, "_cred_write", rec.cred_write)
    monkeypatch.setitem(sys.modules, "keyring", None)
    monkeypatch.setattr(mod, "DELIVERY_MODE", "sync")
    return mod, home, rec


def _clock(
    monkeypatch: pytest.MonkeyPatch, mod: types.ModuleType, start: float = T0
) -> list[float]:
    now = [start]
    monkeypatch.setattr(mod, "_now", lambda: now[0])
    return now


def _project(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir(exist_ok=True)
    return proj


def _stop(
    mod: types.ModuleType,
    tmp_path: Path,
    text: str = "All rows are complete.",
    *,
    session: str = SESSION,
    kind: str = "rows_complete",
    decision: str = "allow",
    release_reason: str | None = None,
    reason: str = "every row is complete",
    open_rows: int = 0,
    task_file: str | None = None,
) -> None:
    payload = {
        "session_id": session,
        "hook_event_name": "Stop",
        "cwd": str(_project(tmp_path)),
        "last_assistant_message": text,
    }
    mod.on_stop(payload, decision, reason, kind, open_rows, task_file, release_reason)


def _hook(
    mod: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
    harness: str = "claude",
) -> int:
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    monkeypatch.setattr(sys, "stdin", io.StringIO(raw))
    return mod.main(["hook", "--harness", harness])


def _log(home: Path) -> list[dict]:
    path = home / "state" / "notify.log.jsonl"
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _outcomes(home: Path) -> list[str]:
    return [line["outcome"] for line in _log(home)]


def _emls(home: Path) -> list[Path]:
    return sorted((home / "state" / "outbox").glob("*.eml"))


def _parse_eml(path: Path) -> email.message.EmailMessage:
    return email.message_from_bytes(path.read_bytes(), policy=email.policy.default)


def _pending(home: Path) -> list[Path]:
    return sorted((home / "state" / "pending").glob("*.json"))


CONFIG_FILES = ("notify.json", "notify.local.json")


def _all_bytes(root: Path) -> bytes:
    """Every file under ``root`` except the config files, which hold the addresses on purpose."""
    return b"\n".join(
        p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.name not in CONFIG_FILES
    )


# ── AC-A.1 home lookup ──────────────────────────────────────────────────


def test_home_lookup_order(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """AC-A.1: ``--home``, then AGENT_NOTIFY_HOME, then the registry home, then ``~/.agent/notify``."""
    mod = _load(monkeypatch)
    user_home = tmp_path / "user"
    monkeypatch.setenv("HOME", str(user_home))
    monkeypatch.setenv("USERPROFILE", str(user_home))
    monkeypatch.setenv("AGENT_NOTIFY_HOME", str(tmp_path / "env-home"))
    monkeypatch.setenv("AGENT_MODEL_REGISTRY_HOME", str(tmp_path / "registry"))
    assert Path(mod.resolve_home(str(tmp_path / "arg"))) == tmp_path / "arg"
    assert Path(mod.resolve_home(None)) == tmp_path / "env-home"
    monkeypatch.delenv("AGENT_NOTIFY_HOME")
    assert Path(mod.resolve_home(None)) == tmp_path / "registry" / "notify"
    monkeypatch.delenv("AGENT_MODEL_REGISTRY_HOME")
    assert Path(mod.resolve_home(None)) == user_home / ".agent" / "notify"


def test_no_home_is_silent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-A.1 negative: a home with no notify.json → exit 0, no output, no file created."""
    mod = _load(monkeypatch)
    empty = tmp_path / "empty-home"
    empty.mkdir()
    monkeypatch.delenv("AGENT_NOTIFY", raising=False)
    monkeypatch.setenv("AGENT_NOTIFY_HOME", str(empty))
    monkeypatch.setattr(socket, "create_connection", _refuse)
    rc = _hook(
        mod,
        monkeypatch,
        {
            "hook_event_name": "Notification",
            "notification_type": "permission_prompt",
            "session_id": SESSION,
        },
    )
    out = capsys.readouterr()
    assert rc == 0
    assert out.out == "" and out.err == ""
    assert list(empty.iterdir()) == []


# ── AC-A.2 config ───────────────────────────────────────────────────────


def test_config_merge_order(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """AC-A.2: defaults, then notify.json, then notify.local.json; one level deep for nested blocks."""
    shared = {
        "subject_prefix": "[s]",
        "events": {"idle_prompt": True},
        "smtp": {"port": 2525},
    }
    local = _local(subject_prefix="[l]")
    mod, home, _rec = _setup(monkeypatch, tmp_path, shared=shared, local=local)
    cfg = mod.load_config(home)
    assert cfg["subject_prefix"] == "[l]"
    assert cfg["events"]["idle_prompt"] is True
    assert cfg["events"]["stop"] is True
    assert cfg["events"]["permission_prompt"] is True
    assert cfg["smtp"]["port"] == 2525
    assert cfg["smtp"]["host"] == "smtp.gmail.com"
    assert cfg["smtp"]["starttls"] is True
    assert cfg["smtp"]["user"] == USER_ADDR
    assert cfg["min_gap_s"] == 300
    assert cfg["dedupe_window_s"] == 120
    assert cfg["hourly_cap"] == 20
    assert cfg["daily_cap"] == 200
    assert cfg["auth_backoff_s"] == 1800
    assert cfg["excerpt_chars"] == 600
    assert cfg["smtp"]["timeout_s"] == 5


@pytest.mark.parametrize(
    ("shared", "local", "bad_file", "bad_key"),
    [
        (None, _local(too=[]), "notify.local.json", "too"),
        (None, _local(enabled="yes"), "notify.local.json", "enabled"),
        ({"min_gap_s": -1}, None, "notify.json", "min_gap_s"),
        ({"smtp": {"prot": 25}}, None, "notify.json", "smtp.prot"),
        (
            None,
            {"enabled": True, "from": FROM_ADDR, "smtp": {"user": USER_ADDR}},
            "notify.local.json",
            "to",
        ),
    ],
)
def test_config_invalid_sends_nothing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    shared: dict | None,
    local: dict | None,
    bad_file: str,
    bad_key: str,
) -> None:
    """AC-A.2: an unknown key, a wrong type, a negative number or a missing required key → config_invalid, no send."""
    mod, home, rec = _setup(monkeypatch, tmp_path, shared=shared, local=local)
    monkeypatch.setenv("AGENT_NOTIFY_DRY_RUN", "1")
    _stop(mod, tmp_path)
    lines = [line for line in _log(home) if line["outcome"] == "config_invalid"]
    assert len(lines) == 1, _log(home)
    assert lines[0]["file"] == bad_file
    assert lines[0]["key"] == bad_key
    assert _emls(home) == []
    assert rec.instances == []


# ── AC-A.3 classifier ───────────────────────────────────────────────────


def _gate(
    decision: str = "allow",
    kind: str = "no_active_plan",
    release_reason: str | None = None,
) -> dict:
    return {"decision": decision, "kind": kind, "release_reason": release_reason}


def _said(text: str) -> dict:
    return {"session_id": SESSION, "last_assistant_message": text}


@pytest.mark.parametrize(
    ("event", "payload", "gate", "expected", "rule"),
    [
        ("StopFailure", {"error": "rate_limit"}, None, "error", 1),
        (
            "Notification",
            {"notification_type": "permission_prompt"},
            None,
            "approval",
            2,
        ),
        ("Notification", {"notification_type": "idle_prompt"}, None, "waiting", 3),
        ("Stop", _said("Working."), _gate("release", "open_rows"), "blocked", 4),
        (
            "Stop",
            _said("Done."),
            _gate(kind="released", release_reason="round-cap"),
            "blocked",
            5,
        ),
        (
            "Stop",
            _said("Done."),
            _gate(kind="released", release_reason="reviewer-unavailable"),
            "blocked",
            5,
        ),
        (
            "Stop",
            _said("Done."),
            _gate(kind="released", release_reason="human-gate"),
            "decision",
            6,
        ),
        (
            "Stop",
            _said("Done."),
            _gate(kind="released", release_reason="handback"),
            "decision",
            6,
        ),
        ("Stop", _said("Done."), _gate(kind="rows_complete"), "done", 7),
        (
            "Stop",
            _said("Checkpoint saved for some-plan. Status: blocked. Key evidence: x."),
            _gate(),
            "blocked",
            8,
        ),
        (
            "Stop",
            _said(
                "Checkpoint saved for some-plan. Status: ready-for-review. Key evidence: x."
            ),
            _gate(),
            "done",
            8,
        ),
        (
            "Stop",
            _said(
                "Checkpoint saved for some-plan. Status: complete. Key evidence: x.\n🕐 Completed: 2026-10-10 18:00 (EDT)"
            ),
            _gate(),
            "done",
            8,
        ),
        (
            "Stop",
            _said("⛔ HARD STOP: the reviewer is unavailable."),
            _gate(),
            "blocked",
            9,
        ),
        (
            "Stop",
            _said("⛔ Plan review reached 3 rounds without approval."),
            _gate(),
            "blocked",
            9,
        ),
        (
            "Stop",
            _said(
                "Which option do you want?\n\n🕐 Completed: 2026-10-10 18:00 (EDT)\n"
            ),
            _gate(),
            "waiting",
            10,
        ),
        ("Stop", _said("The change is in place."), _gate(), "waiting", 11),
    ],
)
def test_classify_rules(
    monkeypatch: pytest.MonkeyPatch,
    event: str,
    payload: dict,
    gate: dict | None,
    expected: str,
    rule: int,
) -> None:
    """AC-A.3: one case per rule of the classifier table; the rule number is asserted, not only the class."""
    mod = _load(monkeypatch)
    assert mod.classify_explain(event, payload, gate) == (expected, rule)
    assert mod.classify(event, payload, gate) == expected


def test_classify_first_match_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-A.3: StopFailure beats a trailing question; a human-gate release beats ``Status: complete.``."""
    mod = _load(monkeypatch)
    assert mod.classify_explain("StopFailure", _said("Shall I retry?"), None) == (
        "error",
        1,
    )
    text = "Checkpoint saved for some-plan. Status: complete. Key evidence: x."
    assert mod.classify_explain(
        "Stop", _said(text), _gate(kind="released", release_reason="human-gate")
    ) == ("decision", 6)
    assert mod.STOP_CLASSES == (
        "done",
        "decision",
        "approval",
        "waiting",
        "blocked",
        "error",
    )


def test_classify_reads_transcript_when_field_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC-A.3: with no ``last_assistant_message``, rules 8–10 read the last assistant entry of the transcript."""
    mod = _load(monkeypatch)
    transcript = tmp_path / "t.jsonl"
    entries = [
        {"type": "user", "message": {"content": "go"}},
        {
            "type": "assistant",
            "message": {
                "content": [{"type": "text", "text": "Which file should I edit?"}]
            },
        },
        {
            "type": "user",
            "message": {"content": [{"type": "tool_result", "content": "x"}]},
        },
    ]
    transcript.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8"
    )
    payload = {"session_id": SESSION, "transcript_path": str(transcript)}
    assert mod.classify_explain("Stop", payload, _gate()) == ("waiting", 10)
    empty_field = {**payload, "last_assistant_message": ""}
    assert mod.classify_explain("Stop", empty_field, _gate()) == ("waiting", 10)


# ── AC-A.4 suppression ──────────────────────────────────────────────────


@pytest.mark.parametrize("switch", ["env", "file", "enabled"])
def test_off_switches_write_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, switch: str
) -> None:
    """AC-A.4 / AC-A.9 negative: each off switch sends nothing and creates no state, lock, log, ledger or pending file."""
    mod, home, rec = _setup(
        monkeypatch,
        tmp_path,
        local=_local(enabled=False) if switch == "enabled" else None,
    )
    if switch == "env":
        monkeypatch.setenv("AGENT_NOTIFY", "OFF")
    if switch == "file":
        (home / "notify.off").write_text("", encoding="utf-8")
    _stop(mod, tmp_path)
    monkeypatch.setattr(mod, "DELIVERY_MODE", "detached")
    _stop(mod, tmp_path, session="sess-0002-cccc")
    assert (
        _hook(
            mod,
            monkeypatch,
            {
                "hook_event_name": "Notification",
                "notification_type": "permission_prompt",
                "session_id": SESSION,
            },
        )
        == 0
    )
    assert not (home / "state").exists()
    assert rec.instances == []
    assert rec.spawned == []


def test_cap_check_and_reservation_are_one_critical_section(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC-A.4: two workers released together with ``hourly_cap`` 1 produce exactly one ``sent``."""
    mod, home, rec = _setup(monkeypatch, tmp_path, shared={"hourly_cap": 1})
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def worker(n: int) -> None:
        try:
            barrier.wait(timeout=10)
            _stop(mod, tmp_path, f"Finished part {n}.", session=f"sess-000{n}-dddd")
        except BaseException as exc:  # noqa: BLE001 - surfaced through the errors list
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in (1, 2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert errors == []
    outcomes = _outcomes(home)
    assert outcomes.count("sent") == 1, outcomes
    assert outcomes.count("hourly_cap") == 1, outcomes
    assert len(rec.messages()) == 1


def test_held_lock_sends_once_and_logs_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC-A.4: a lock held past the wait → one send and one ``state_lock_timeout`` line."""
    mod, home, rec = _setup(monkeypatch, tmp_path)
    assert mod.LOCK_WAIT_S == 2
    monkeypatch.setattr(mod, "LOCK_WAIT_S", 0.3)
    state = home / "state"
    state.mkdir()
    (state / mod.LOCK_NAME).write_text("held", encoding="utf-8")
    _stop(mod, tmp_path)
    outcomes = _outcomes(home)
    assert outcomes.count("state_lock_timeout") == 1, outcomes
    assert outcomes.count("sent") == 1, outcomes
    assert len(rec.messages()) == 1


def test_stale_lock_is_removed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """AC-A.4: a lock older than 30 s is stale; it is removed and the send proceeds without a timeout line."""
    mod, home, rec = _setup(monkeypatch, tmp_path)
    state = home / "state"
    state.mkdir()
    lock = state / mod.LOCK_NAME
    lock.write_text("old", encoding="utf-8")
    old = time.time() - 60
    os.utime(lock, (old, old))
    _stop(mod, tmp_path)
    outcomes = _outcomes(home)
    assert "state_lock_timeout" not in outcomes
    assert outcomes.count("sent") == 1
    assert not lock.exists()


def _skip_line(home: Path, outcome: str) -> dict:
    lines = [line for line in _log(home) if line["outcome"] == outcome]
    assert len(lines) == 1, _log(home)
    assert SKIP_FIELDS <= set(lines[0]), lines[0]
    return lines[0]


def test_event_and_class_switches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC-A.4: ``events.<event>`` false → event_disabled; ``classes.<class>`` false → class_disabled."""
    mod, home, rec = _setup(monkeypatch, tmp_path, shared={"events": {"stop": False}})
    _stop(mod, tmp_path)
    assert _skip_line(home, "event_disabled")["limit_name"] == "events.stop"
    mod2, home2, rec2 = _setup(
        monkeypatch, tmp_path / "b", shared={"classes": {"done": False}}
    )
    _stop(mod2, tmp_path / "b")
    assert _skip_line(home2, "class_disabled")["limit_name"] == "classes.done"
    assert rec.instances == [] and rec2.instances == []


def test_idle_prompt_is_off_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC-A.4: ``events.idle_prompt`` defaults to false, so an idle prompt is logged and not sent."""
    mod, home, rec = _setup(monkeypatch, tmp_path)
    _hook(
        mod,
        monkeypatch,
        {
            "hook_event_name": "Notification",
            "notification_type": "idle_prompt",
            "session_id": SESSION,
            "cwd": str(_project(tmp_path)),
        },
    )
    assert _skip_line(home, "event_disabled")["limit_name"] == "events.idle_prompt"
    assert rec.instances == []


def test_min_gap(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """AC-A.4: a ``waiting`` stop 299 s after the previous one is skipped; one 300 s after is sent."""
    mod, home, _rec = _setup(monkeypatch, tmp_path)
    now = _clock(monkeypatch, mod)
    _stop(mod, tmp_path, "Shall I go on?", kind="no_active_plan")
    now[0] = T0 + 299
    _stop(mod, tmp_path, "And the next one?", kind="no_active_plan")
    line = _skip_line(home, "min_gap")
    assert line["limit_name"] == "min_gap_s"
    assert line["configured_value"] == 300
    assert line["observed_value"] == 299
    now[0] = T0 + 300 + 299
    _stop(mod, tmp_path, "One more question?", kind="no_active_plan")
    assert _outcomes(home).count("sent") == 2


def test_min_gap_is_per_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC-A.4: the gap is counted per session; another session's stop 1 s later is sent."""
    mod, home, _rec = _setup(monkeypatch, tmp_path)
    now = _clock(monkeypatch, mod)
    _stop(mod, tmp_path, "Shall I go on?", kind="no_active_plan")
    now[0] = T0 + 1
    _stop(
        mod, tmp_path, "Shall I go on?", kind="no_active_plan", session="sess-0009-eeee"
    )
    assert _outcomes(home).count("sent") == 2


def _bypass_stop(
    mod: types.ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, cls: str
) -> None:
    if cls == "done":
        _stop(mod, tmp_path, "All done.", kind="rows_complete")
    elif cls == "decision":
        _stop(
            mod,
            tmp_path,
            "Please rule on D-1.",
            kind="released",
            release_reason="human-gate",
        )
    elif cls == "blocked":
        _stop(
            mod,
            tmp_path,
            "Still open.",
            kind="open_rows",
            decision="release",
            open_rows=3,
        )
    else:
        payload = {
            "hook_event_name": "StopFailure",
            "session_id": SESSION,
            "cwd": str(_project(tmp_path)),
            "error": "rate_limit",
        }
        assert _hook(mod, monkeypatch, payload) == 0


@pytest.mark.parametrize("cls", ["done", "decision", "blocked", "error"])
def test_gap_bypass_classes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, cls: str
) -> None:
    """AC-A.4: each class in GAP_BYPASS_CLASSES is sent 1 s after a ``waiting`` stop of the same session."""
    mod, home, _rec = _setup(monkeypatch, tmp_path)
    assert mod.GAP_BYPASS_CLASSES == ("done", "decision", "blocked", "error")
    now = _clock(monkeypatch, mod)
    _stop(mod, tmp_path, "Shall I go on?", kind="no_active_plan")
    now[0] = T0 + 1
    _bypass_stop(mod, monkeypatch, tmp_path, cls)
    sent = [line for line in _log(home) if line["outcome"] == "sent"]
    assert [line["class"] for line in sent] == ["waiting", cls]


def test_approval_is_not_a_gap_bypass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC-A.4: a permission prompt 1 s after a ``waiting`` stop of the same session is held by the gap."""
    mod, home, _rec = _setup(monkeypatch, tmp_path)
    now = _clock(monkeypatch, mod)
    _stop(mod, tmp_path, "Shall I go on?", kind="no_active_plan")
    now[0] = T0 + 1
    _hook(
        mod,
        monkeypatch,
        {
            "hook_event_name": "Notification",
            "notification_type": "permission_prompt",
            "session_id": SESSION,
            "cwd": str(_project(tmp_path)),
        },
    )
    assert _skip_line(home, "min_gap")["class"] == "approval"


def test_dedupe_window(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """AC-A.4 / EA-1 R2-02: the same excerpt inside the window is skipped; a distinct excerpt is sent."""
    mod, home, _rec = _setup(monkeypatch, tmp_path)
    now = _clock(monkeypatch, mod)
    _stop(mod, tmp_path, "Report X is ready.")
    now[0] = T0 + 10
    _stop(mod, tmp_path, "Report X is ready.")
    line = _skip_line(home, "dedupe")
    assert line["limit_name"] == "dedupe_window_s"
    assert line["configured_value"] == 120
    now[0] = T0 + 20
    _stop(mod, tmp_path, "Report Y is ready.")
    now[0] = T0 + 200
    _stop(mod, tmp_path, "Report X is ready.")
    assert _outcomes(home).count("sent") == 3


def test_dedupe_digest_survives_redaction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """EA-1 R2-02: the ledger digest is its own field and is not redacted; distinct excerpts give distinct digests."""
    mod, home, _rec = _setup(monkeypatch, tmp_path)
    now = _clock(monkeypatch, mod)
    _stop(mod, tmp_path, "Report X is ready.")
    now[0] = T0 + 5
    _stop(mod, tmp_path, "Report Y is ready.")
    ledger = [
        json.loads(x)
        for x in (home / "state" / "sent.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if x.strip()
    ]
    digests = {line["digest"] for line in ledger if line.get("digest")}
    assert len(digests) == 2
    assert all("[redacted]" not in d for d in digests)


def test_hourly_cap(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """AC-A.4: the 21st message in an hour is skipped (hourly_cap 20, over all sessions)."""
    mod, home, rec = _setup(monkeypatch, tmp_path)
    now = _clock(monkeypatch, mod)
    for n in range(21):
        now[0] = T0 + n
        _stop(mod, tmp_path, f"Batch {n} finished.", session=f"sess-{n:04d}-ffff")
    line = _skip_line(home, "hourly_cap")
    assert line["configured_value"] == 20
    assert line["observed_value"] == 20
    assert _outcomes(home).count("sent") == 20
    assert len(rec.messages()) == 20


def test_daily_cap(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """AC-A.4: the daily cap counts over 24 h, across hours."""
    mod, home, _rec = _setup(
        monkeypatch, tmp_path, shared={"daily_cap": 2, "hourly_cap": 100}
    )
    now = _clock(monkeypatch, mod)
    for n, offset in enumerate((0, 4000, 8000)):
        now[0] = T0 + offset
        _stop(mod, tmp_path, f"Batch {n} finished.")
    line = _skip_line(home, "daily_cap")
    assert line["configured_value"] == 2
    assert _outcomes(home).count("sent") == 2


def test_auth_backoff(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """AC-A.4 / AC-A.5 negative: an auth failure writes backoff.json; the next stop inside the window is skipped."""
    mod, home, rec = _setup(monkeypatch, tmp_path)
    now = _clock(monkeypatch, mod)
    rec.login_exc = smtplib.SMTPAuthenticationError(535, b"bad credentials")
    _stop(mod, tmp_path, "Batch 1 finished.")
    assert "auth_failed" in _outcomes(home)
    assert (home / "state" / "backoff.json").exists()
    rec.login_exc = None
    now[0] = T0 + 60
    _stop(mod, tmp_path, "Batch 2 finished.")
    line = _skip_line(home, "auth_backoff")
    assert line["limit_name"] == "auth_backoff_s"
    assert line["configured_value"] == 1800
    now[0] = T0 + 1801
    _stop(mod, tmp_path, "Batch 3 finished.")
    assert _outcomes(home).count("sent") == 1


def test_missing_credential(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """AC-A.4: no credential anywhere → one ``credential_missing`` line and no SMTP connection."""
    mod, home, rec = _setup(monkeypatch, tmp_path)
    monkeypatch.delenv("AGENT_NOTIFY_SMTP_PASSWORD")
    _stop(mod, tmp_path)
    _skip_line(home, "credential_missing")
    assert rec.instances == []


# ── AC-A.5 delivery ─────────────────────────────────────────────────────


def test_smtp_delivery_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC-A.5: verified STARTTLS before login, one message, subject format, body fields and size."""
    mod, home, rec = _setup(monkeypatch, tmp_path)
    task = "docs/plans/x/task.md"
    _stop(
        mod,
        tmp_path,
        "Shall I start row 4?",
        kind="open_rows",
        decision="release",
        reason="3 rows open",
        open_rows=3,
        task_file=task,
    )
    assert len(rec.instances) == 1
    conn = rec.instances[0]
    assert (conn.host, conn.port) == ("smtp.gmail.com", 587)
    names = [c[0] for c in conn.calls]
    assert names.index("starttls") < names.index("login") < names.index("send_message")
    context = next(c[1] for c in conn.calls if c[0] == "starttls")
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert ("login", USER_ADDR, PASSWORD) in conn.calls
    assert names.count("send_message") == 1
    msg = conn.messages[0]
    assert SUBJECT_RE.match(msg["Subject"]), msg["Subject"]
    assert "| BLOCKED |" in msg["Subject"]
    assert msg["Subject"].startswith("[agent] proj |")
    body = msg.get_content()
    assert len(body.encode("utf-8")) <= 2048
    for needle in (
        "Project: proj",
        f"Directory: {_project(tmp_path)}",
        "Branch: ",
        "Harness: claude",
        "Session: sess-000",
        "Class: blocked",
        "Reason: 3 rows open",
        f"Task: {task}",
        "Open rows: 3",
        "Time: ",
        f"Log: {home / 'state' / 'notify.log.jsonl'}",
        "Shall I start row 4?",
    ):
        assert needle in body, needle
    assert "transcript" not in body.lower()
    assert _outcomes(home).count("sent") == 1


def test_starttls_failure_never_logs_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC-A.5: a certificate failure in STARTTLS ends the attempt before ``login``; outcome ``tls_error``."""
    mod, home, rec = _setup(monkeypatch, tmp_path)
    rec.starttls_exc = ssl.SSLCertVerificationError("certificate verify failed")
    _stop(mod, tmp_path)
    assert [c[0] for c in rec.instances[0].calls].count("login") == 0
    assert "tls_error" in _outcomes(home)
    assert rec.messages() == []


def test_delivery_total_deadline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC-A.5 / EA-1 R2-03: a connect and a login that each take 5 s (ignoring timeout hints) end in ``timeout`` before 9 s."""
    mod, home, rec = _setup(monkeypatch, tmp_path)
    assert mod.DELIVERY_BUDGET_S == 8
    rec.connect_sleep = 5.0
    rec.login_sleep = 5.0
    started = time.monotonic()
    _stop(mod, tmp_path)
    elapsed = time.monotonic() - started
    assert elapsed < 9, elapsed
    assert "timeout" in _outcomes(home)
    assert "sent" not in _outcomes(home)


def test_auth_failure_exits_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC-A.5 negative: ``SMTPAuthenticationError`` → ``auth_failed``, backoff.json, exit 0."""
    mod, home, rec = _setup(monkeypatch, tmp_path)
    rec.login_exc = smtplib.SMTPAuthenticationError(535, b"bad credentials")
    assert mod.main(["send", "--class", "done", "--text", "Manual note."]) == 0
    assert "auth_failed" in _outcomes(home)
    assert (home / "state" / "backoff.json").exists()


def test_test_send_ignores_enabled_and_marks_subject(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Plan Component A item 8: ``test-send`` sends one ``done`` message with ``(test)`` even when disabled."""
    mod, home, rec = _setup(monkeypatch, tmp_path, local=_local(enabled=False))
    assert mod.main(["test-send"]) == 0
    msgs = rec.messages()
    assert len(msgs) == 1
    assert msgs[0]["Subject"].endswith(" (test)")
    assert "| DONE |" in msgs[0]["Subject"]


# ── AC-A.6 secrets and addresses ────────────────────────────────────────


def test_password_and_addresses_never_leak(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-A.6: the password and full addresses never reach stdout, stderr, log, ledger, pending, .eml or status."""
    mod, home, rec = _setup(monkeypatch, tmp_path)
    assert mod.mask_address(TO_ADDR) == "r***@z***"
    monkeypatch.setenv("AGENT_NOTIFY_DRY_RUN", "1")
    _stop(mod, tmp_path, "Dry run note.")
    monkeypatch.delenv("AGENT_NOTIFY_DRY_RUN")
    _stop(mod, tmp_path, "Real send note.", session="sess-0002-gggg")
    monkeypatch.setattr(mod, "DELIVERY_MODE", "detached")
    _stop(mod, tmp_path, "Pending note.", session="sess-0003-hhhh")
    assert mod.main(["status"]) == 0
    captured = capsys.readouterr()
    assert "credential: present" in captured.out
    assert len(_emls(home)) == 1
    assert len(_pending(home)) == 1
    assert len(rec.messages()) == 1
    blob = (
        _all_bytes(home) + captured.out.encode("utf-8") + captured.err.encode("utf-8")
    )
    for secret in (PASSWORD, TO_ADDR, FROM_ADDR, USER_ADDR):
        assert secret.encode("utf-8") not in blob, secret
    eml = _parse_eml(_emls(home)[0])
    assert eml["To"] == mod.mask_address(TO_ADDR)
    assert eml["From"] == mod.mask_address(FROM_ADDR)


# ── AC-A.7 redaction ────────────────────────────────────────────────────

_S_BEARER = _fake("QJZX7vkq", "WZJX4qvk")
_S_BASIC = _fake("ZXqJvK9w", "QzJx8VkW==")
_S_BEARER_MID = _fake("JqZxWv3k", "QjZx5WvK")
_S_JSON = _fake("Vq7Zx", "JkWq9Zx")
_S_PY_KEY = _fake("KzQx8", "JvWqZ3x")
_S_TOKEN = _fake("XjQz6", "WvKqZ2j")
_S_ENV_KEY = _fake("ZqWx4", "JvKjQz7")
_S_SPACED_APP = _fake("qjzx kvwq", " zjxq wvkj")
_S_BARE_APP = _fake("xqzj vkwq", " jzxv qwkz")
_S_HEX = _fake("9f0c3b7e1a5d", "9f0c3b7e1a5d", "9f0c3b7e1a5d", "9f0c")

REDACTION_CASES = [
    ("auth_bearer", f"Authorization: Bearer {_S_BEARER}", _S_BEARER, "Authorization"),
    ("auth_basic", f"Authorization: Basic {_S_BASIC}", _S_BASIC, "Authorization"),
    (
        "bearer_mid",
        f"then I used Bearer {_S_BEARER_MID} to call it",
        _S_BEARER_MID,
        "Bearer",
    ),
    ("json_password", f'{{"password": "{_S_JSON}"}}', _S_JSON, "password"),
    ("py_api_key", f"{{'api_key': '{_S_PY_KEY}'}}", _S_PY_KEY, "api_key"),
    ("token_colon", f"token: {_S_TOKEN}", _S_TOKEN, "token"),
    ("env_api_key", f"API_KEY={_S_ENV_KEY}", _S_ENV_KEY, "API_KEY"),
    ("spaced_password", f"password = {_S_SPACED_APP}", _S_SPACED_APP, "password"),
    ("bare_app_password", f"the new one is {_S_BARE_APP} now", _S_BARE_APP, None),
    ("hex_run", f"digest {_S_HEX}", _S_HEX, None),
]


def _fragments(secret: str) -> set[str]:
    parts = {secret}
    for token in secret.split():
        parts.add(token)
        parts.update(token[i : i + 4] for i in range(0, len(token) - 3, 4))
    return parts


@pytest.mark.parametrize(
    ("label", "text", "secret", "key"),
    REDACTION_CASES,
    ids=[c[0] for c in REDACTION_CASES],
)
def test_redaction_corpus(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    label: str,
    text: str,
    secret: str,
    key: str | None,
) -> None:
    """AC-A.7: no secret, token or 4-letter group reaches the excerpt, .eml, log, ledger or pending file."""
    mod, home, _rec = _setup(monkeypatch, tmp_path)
    message = f"Before the note.\n{text}\nAfter the note."
    redacted = mod.redact(message)
    for fragment in _fragments(secret):
        assert fragment not in redacted, (label, fragment)
    if key is not None:
        assert key in redacted
    monkeypatch.setenv("AGENT_NOTIFY_DRY_RUN", "1")
    _stop(mod, tmp_path, message)
    monkeypatch.setattr(mod, "DELIVERY_MODE", "detached")
    _stop(mod, tmp_path, message, session="sess-0002-iiii")
    assert len(_emls(home)) == 1 and len(_pending(home)) == 1
    blob = _all_bytes(home).decode("utf-8", errors="replace")
    body = _parse_eml(_emls(home)[0]).get_content()
    for fragment in _fragments(secret):
        assert fragment not in blob, (label, fragment)
        assert fragment not in body, (label, fragment)
    if key is not None:
        assert key in body


def test_redaction_keeps_plain_prose(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC-A.7 negative: 600 characters of prose with no key word is kept whole; the excerpt is capped."""
    mod, home, _rec = _setup(monkeypatch, tmp_path)
    unit = "The quarterly review compared seven strategies across different markets, "
    prose = (unit * 10)[:600]
    assert mod.redact(prose) == prose
    monkeypatch.setenv("AGENT_NOTIFY_DRY_RUN", "1")
    _stop(mod, tmp_path, prose)
    assert prose in _parse_eml(_emls(home)[0]).get_content()
    long_text = "Opening line that is dropped. " * 40 + "Final question for you?"
    assert len(mod.excerpt(long_text, 600)) <= 600


# ── AC-A.8 credentials ──────────────────────────────────────────────────


def test_credential_store_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """AC-A.8: the OS credential store is read first; keyring is not consulted when it has a value."""
    mod, _home, _rec = _setup(monkeypatch, tmp_path)
    targets: list[str] = []
    keyring_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        mod, "_cred_read", lambda target: targets.append(target) or "from-store"
    )
    fake_keyring = types.SimpleNamespace(
        get_password=lambda svc, user: (
            keyring_calls.append((svc, user)) or "from-keyring"
        )
    )
    monkeypatch.setitem(sys.modules, "keyring", fake_keyring)
    assert mod.load_password(USER_ADDR) == "from-store"
    assert targets == [f"agent-notify:smtp:{USER_ADDR}"]
    assert keyring_calls == []


def test_keyring_then_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """AC-A.8: with no store value keyring is next; with keyring unavailable the env variable is used."""
    mod, _home, _rec = _setup(monkeypatch, tmp_path)
    fake_keyring = types.SimpleNamespace(
        get_password=lambda svc, user: (
            "from-keyring" if svc == "agent-notify:smtp" else None
        )
    )
    monkeypatch.setitem(sys.modules, "keyring", fake_keyring)
    assert mod.load_password(USER_ADDR) == "from-keyring"
    monkeypatch.setitem(sys.modules, "keyring", None)
    assert mod.load_password(USER_ADDR) == PASSWORD
    monkeypatch.delenv("AGENT_NOTIFY_SMTP_PASSWORD")
    assert mod.load_password(USER_ADDR) is None


def test_setup_stores_and_rejects_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-A.8 negative: ``setup`` with an empty password exits 1 and stores nothing; a real one is stored once."""
    mod, _home, rec = _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "")
    assert mod.main(["setup", "--user", USER_ADDR]) == 1
    assert rec.stored == []
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": PASSWORD)
    assert mod.main(["setup", "--user", USER_ADDR]) == 0
    assert rec.stored == [(f"agent-notify:smtp:{USER_ADDR}", USER_ADDR, PASSWORD)]
    captured = capsys.readouterr()
    assert PASSWORD not in captured.out + captured.err


# ── AC-A.9 on_stop delivery modes ───────────────────────────────────────


def test_detached_mode_writes_pending_and_spawns(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC-A.9: detached mode writes one pending file, spawns ``deliver`` with DETACHED_PROCESS, returns in < 150 ms."""
    mod, home, rec = _setup(monkeypatch, tmp_path)
    assert mod.DETACHED_PROCESS == DETACHED_PROCESS
    monkeypatch.setattr(mod, "DELIVERY_MODE", "detached")
    _stop(mod, tmp_path)
    pending = _pending(home)
    assert len(pending) == 1
    assert len(rec.spawned) == 1
    argv, flags = rec.spawned[0]
    assert argv[0] == sys.executable
    assert Path(argv[1]).resolve() == _module_path().resolve()
    assert argv[2:] == ["deliver", str(pending[0])]
    assert flags == (DETACHED_PROCESS if os.name == "nt" else 0)
    assert rec.instances == []
    timings = []
    for n in range(5):
        started = time.perf_counter()
        _stop(mod, tmp_path, f"Run {n}.", session=f"sess-01{n:02d}-jjjj")
        timings.append(time.perf_counter() - started)
    assert statistics.median(timings) < 0.150, timings


def test_sync_mode_delivers_in_process_within_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC-A.9: sync mode spawns nothing, writes no pending file and returns within the budget + 1 s on a hung server."""
    mod, home, rec = _setup(monkeypatch, tmp_path)
    assert mod.DELIVERY_MODE == "sync"
    rec.connect_sleep = 30.0
    started = time.monotonic()
    _stop(mod, tmp_path)
    assert time.monotonic() - started < mod.DELIVERY_BUDGET_S + 1
    assert rec.spawned == []
    assert _pending(home) == []
    assert len(rec.instances) == 1
    assert "timeout" in _outcomes(home)


def test_on_stop_never_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """AC-A.9: an exception inside ``on_stop`` is caught and logged in both modes."""
    mod, home, _rec = _setup(monkeypatch, tmp_path)

    def boom(*args: object, **kw: object) -> None:
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(mod, "classify", boom)
    monkeypatch.setattr(mod, "classify_explain", boom)
    _stop(mod, tmp_path)
    monkeypatch.setattr(mod, "DELIVERY_MODE", "detached")
    monkeypatch.setattr(mod, "_spawn", boom)
    _stop(mod, tmp_path, session="sess-0002-kkkk")
    assert _outcomes(home).count("internal_error") == 2, _outcomes(home)


def test_delivery_mode_is_a_known_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-A.9: the module constant is one of the two Probe-1 branches."""
    mod = _load(monkeypatch)
    assert mod.DELIVERY_MODE in ("detached", "sync")


# ── AC-A.10 deliver worker ──────────────────────────────────────────────


def test_deliver_sends_and_deletes_pending(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-A.10: ``deliver`` sends once and deletes the pending file; it prints nothing."""
    mod, home, rec = _setup(monkeypatch, tmp_path)
    _clock(monkeypatch, mod)
    monkeypatch.setattr(mod, "DELIVERY_MODE", "detached")
    _stop(mod, tmp_path)
    pending = _pending(home)[0]
    assert mod.main(["deliver", str(pending)]) == 0
    assert not pending.exists()
    assert len(rec.messages()) == 1
    assert _outcomes(home).count("sent") == 1
    assert capsys.readouterr().out == ""


def test_deliver_drops_stale_pending(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC-A.10: a pending file older than 600 s is deleted with ``pending_stale`` and nothing is sent."""
    mod, home, rec = _setup(monkeypatch, tmp_path)
    now = _clock(monkeypatch, mod)
    monkeypatch.setattr(mod, "DELIVERY_MODE", "detached")
    _stop(mod, tmp_path)
    pending = _pending(home)[0]
    now[0] = T0 + 601
    assert mod.main(["deliver", str(pending)]) == 0
    assert not pending.exists()
    assert "pending_stale" in _outcomes(home)
    assert rec.instances == []


# ── AC-A.11 other harnesses ─────────────────────────────────────────────


def test_codex_notify_argv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-A.11: ``hook --harness codex`` reads the last argv JSON; only ``agent-turn-complete`` is handled."""
    mod, home, rec = _setup(monkeypatch, tmp_path)
    turn = {
        "type": "agent-turn-complete",
        "thread-id": "thr-0001-llll",
        "turn-id": "1",
        "cwd": str(_project(tmp_path)),
        "input-messages": ["go"],
        "last-assistant-message": "The change is in place.",
    }
    assert mod.main(["hook", "--harness", "codex", json.dumps(turn)]) == 0
    assert _outcomes(home).count("sent") == 1
    assert len(rec.messages()) == 1
    assert (
        mod.main(["hook", "--harness", "codex", json.dumps({"type": "something-else"})])
        == 0
    )
    assert "event_unsupported" in _outcomes(home)
    assert len(rec.messages()) == 1
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    ("status", "expected"),
    [("completed", "done"), ("aborted", "waiting"), ("error", "error")],
)
def test_cursor_stop_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, status: str, expected: str
) -> None:
    """AC-A.11: ``hook --harness cursor`` maps ``status`` to the class."""
    mod, home, _rec = _setup(monkeypatch, tmp_path)
    payload = {
        "hook_event_name": "stop",
        "status": status,
        "conversation_id": "conv-0001-mmmm",
        "workspace_roots": [str(_project(tmp_path))],
    }
    assert _hook(mod, monkeypatch, payload, harness="cursor") == 0
    sent = [line for line in _log(home) if line["outcome"] == "sent"]
    assert [line["class"] for line in sent] == [expected]


def test_invalid_payload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-A.11 negative: invalid JSON → ``payload_invalid``, exit 0, nothing on stdout."""
    mod, home, _rec = _setup(monkeypatch, tmp_path)
    assert _hook(mod, monkeypatch, "{not json") == 0
    assert "payload_invalid" in _outcomes(home)
    assert capsys.readouterr().out == ""


# ── AC-A.12 dry run ─────────────────────────────────────────────────────


def test_dry_run_matches_real_send(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC-A.12: dry run writes one .eml with the real subject and body, masked addresses, and opens no socket."""
    mod, home, rec = _setup(monkeypatch, tmp_path, shared={"dedupe_window_s": 0})
    _clock(monkeypatch, mod)
    monkeypatch.setenv("AGENT_NOTIFY_DRY_RUN", "1")
    _stop(mod, tmp_path, "All rows are complete.")
    assert rec.instances == []
    assert "dry_run" in _outcomes(home)
    emls = _emls(home)
    assert len(emls) == 1
    assert emls[0].name.endswith("-done.eml")
    monkeypatch.delenv("AGENT_NOTIFY_DRY_RUN")
    _stop(mod, tmp_path, "All rows are complete.")
    real = rec.messages()
    assert len(real) == 1
    dry = _parse_eml(emls[0])
    assert dry["Subject"] == real[0]["Subject"]
    assert dry.get_content() == real[0].get_content()
    assert dry["To"] == mod.mask_address(TO_ADDR)
    assert TO_ADDR in str(real[0]["To"])


# ── Review round 1 corrections (EA-12) ──────────────────────────────────

OTHER_ADDR = "@".join(("other-qzv", "zq-elsewhere.invalid"))


def test_addresses_in_stop_text_are_masked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-A.6 / R1-F1: addresses in the stop text, gate reason, session, directory and task file are masked on every surface."""
    mod, home, rec = _setup(monkeypatch, tmp_path)
    proj = tmp_path / f"proj-{OTHER_ADDR}"
    proj.mkdir()
    text = (
        f"Mail goes to {TO_ADDR} and {TO_ADDR.upper()}, from {FROM_ADDR},"
        f" signed in as {USER_ADDR}; cc {OTHER_ADDR}."
    )

    def stop(n: int) -> None:
        payload = {
            "session_id": f"{OTHER_ADDR}-{n}",
            "hook_event_name": "Stop",
            "cwd": str(proj),
            "last_assistant_message": f"{text} Stop {n}.",
        }
        mod.on_stop(
            payload,
            "allow",
            f"reply to {OTHER_ADDR}",
            "rows_complete",
            1,
            f"plans/{USER_ADDR}/task.md",
            None,
        )

    monkeypatch.setenv("AGENT_NOTIFY_DRY_RUN", "1")
    stop(1)
    monkeypatch.delenv("AGENT_NOTIFY_DRY_RUN")
    stop(2)
    monkeypatch.setattr(mod, "DELIVERY_MODE", "detached")
    stop(3)
    assert mod.main(["status"]) == 0
    captured = capsys.readouterr()
    assert len(_emls(home)) == 1
    assert len(_pending(home)) == 1
    assert len(rec.messages()) == 1
    sent_body = rec.messages()[0].get_content()
    blob = (
        _all_bytes(home).decode("utf-8", errors="replace")
        + captured.out
        + captured.err
        + sent_body
    ).lower()
    for address in (TO_ADDR, FROM_ADDR, USER_ADDR, OTHER_ADDR):
        assert address.lower() not in blob, address
    dry_body = _parse_eml(_emls(home)[0]).get_content()
    for address in (TO_ADDR, OTHER_ADDR, USER_ADDR):
        assert mod.mask_address(address) in dry_body, address
    assert mod.mask_address(OTHER_ADDR) in sent_body


R6_SHAPES = [
    ("alpha_base64", "QzJx+WvKq/ZjXwQkVzJqXwKvZqJxWkQvZjXqWkJv=="),
    ("numeric", "8317594831726895473195861749286374153928"),
    ("alpha_hex", "deadbeefcafebabefacadedecadeabbaceeddeafbad"),
]


def _slices(secret: str) -> set[str]:
    return {secret} | {secret[i : i + 8] for i in range(0, len(secret) - 7, 8)}


@pytest.mark.parametrize(
    ("label", "secret"), R6_SHAPES, ids=[shape[0] for shape in R6_SHAPES]
)
def test_r6_redacts_every_long_run_shape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, label: str, secret: str
) -> None:
    """AC-A.7 / R1-F2: r6 removes any run of 32+ base64 or hex characters, letters-only and digits-only included."""
    mod, home, _rec = _setup(monkeypatch, tmp_path)
    assert len(secret) >= 32
    message = f"Before the note.\nthe value was {secret}\nAfter the note."
    redacted = mod.redact(message)
    for fragment in _slices(secret):
        assert fragment not in redacted, (label, fragment)
    assert "Before the note." in redacted and "After the note." in redacted
    monkeypatch.setenv("AGENT_NOTIFY_DRY_RUN", "1")
    _stop(mod, tmp_path, message)
    monkeypatch.setattr(mod, "DELIVERY_MODE", "detached")
    _stop(mod, tmp_path, message, session="sess-0002-kkkk")
    assert len(_emls(home)) == 1 and len(_pending(home)) == 1
    blob = _all_bytes(home).decode("utf-8", errors="replace")
    body = _parse_eml(_emls(home)[0]).get_content()
    for fragment in _slices(secret):
        assert fragment not in blob, (label, fragment)
        assert fragment not in body, (label, fragment)


def _stall_credential(
    monkeypatch: pytest.MonkeyPatch, mod: types.ModuleType
) -> threading.Event:
    """A credential store that hangs until released, then returns the password."""
    release = threading.Event()

    def stalled(target: str) -> str | None:
        release.wait(10)
        return PASSWORD

    monkeypatch.setattr(mod, "_cred_read", stalled)
    return release


def test_credential_stall_is_bounded_by_the_deadline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC-A.5 / AC-A.9 / R1-F3: a hung credential store ends in ``timeout`` within the budget + 1 s; the lock is released and no send follows."""
    mod, home, rec = _setup(monkeypatch, tmp_path)
    assert mod.DELIVERY_BUDGET_S == 8
    monkeypatch.setattr(mod, "DELIVERY_BUDGET_S", 2)
    release = _stall_credential(monkeypatch, mod)
    started = time.monotonic()
    try:
        _stop(mod, tmp_path)
        elapsed = time.monotonic() - started
    finally:
        release.set()
    time.sleep(0.3)
    assert elapsed < mod.DELIVERY_BUDGET_S + 1, elapsed
    outcomes = _outcomes(home)
    assert "timeout" in outcomes, outcomes
    assert "sent" not in outcomes, outcomes
    assert rec.instances == []
    assert not (home / "state" / mod.LOCK_NAME).exists()


def test_credential_stall_after_lock_timeout_is_bounded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC-A.5 / AC-A.9 / R1-F3: on the lock-timeout branch a hung credential store also ends in ``timeout`` within the budget + 1 s."""
    mod, home, rec = _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(mod, "LOCK_WAIT_S", 0.3)
    monkeypatch.setattr(mod, "DELIVERY_BUDGET_S", 2)
    state = home / "state"
    state.mkdir()
    (state / mod.LOCK_NAME).write_text("held", encoding="utf-8")
    release = _stall_credential(monkeypatch, mod)
    started = time.monotonic()
    try:
        _stop(mod, tmp_path)
        elapsed = time.monotonic() - started
    finally:
        release.set()
    time.sleep(0.3)
    assert elapsed < mod.DELIVERY_BUDGET_S + 1, elapsed
    outcomes = _outcomes(home)
    assert outcomes.count("state_lock_timeout") == 1, outcomes
    assert "timeout" in outcomes, outcomes
    assert "sent" not in outcomes, outcomes
    assert rec.instances == []
    assert (state / mod.LOCK_NAME).read_text(encoding="utf-8") == "held"


# ── Review round 2 corrections (EA-13) ──────────────────────────────────

E13_BRANCH = "e13-branch"
WORKDIR_ENV = "AGENT_NOTIFY_WORKDIR"


def _git_env() -> dict[str, str]:
    """The process environment without GIT_* overrides, so git sees only ``-C``."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _clear_git_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(name)
    monkeypatch.delenv(WORKDIR_ENV, raising=False)


def _git_repo(path: Path, branch: str) -> Path:
    """A real repository on ``branch`` with one empty commit."""
    import subprocess

    path.mkdir(parents=True)
    author = "@".join(("e13", "zq-sentinel.invalid"))
    steps = (
        ["-c", f"init.defaultBranch={branch}", "init", "-q"],
        [
            "-c",
            "user.name=e13",
            "-c",
            f"user.email={author}",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--allow-empty",
            "--no-verify",
            "-q",
            "-m",
            "e13",
        ],
    )
    for args in steps:
        subprocess.run(
            ["git", "-C", str(path), *args],
            env=_git_env(),
            capture_output=True,
            timeout=30,
            check=True,
        )
    return path


def _e13_payload(repo: Path, n: int = 1) -> dict[str, object]:
    return {
        "session_id": f"sess-e13-{n}",
        "hook_event_name": "Stop",
        "cwd": str(repo),
        "last_assistant_message": f"All rows are complete. Run {n}.",
    }


def _e13_run(
    mod: types.ModuleType, monkeypatch: pytest.MonkeyPatch, repo: Path, path: str
) -> None:
    if path == "on_stop":
        mod.on_stop(
            _e13_payload(repo),
            "allow",
            "every row is complete",
            "rows_complete",
            0,
            None,
            None,
        )
    elif path == "hook_claude":
        assert _hook(mod, monkeypatch, _e13_payload(repo)) == 0
    elif path == "hook_codex":
        turn = {
            "type": "agent-turn-complete",
            "thread-id": "sess-e13-codex",
            "cwd": str(repo),
            "last-assistant-message": "All rows are complete.",
        }
        assert mod.main(["hook", "--harness", "codex", json.dumps(turn)]) == 0
    elif path == "hook_cursor":
        payload = {
            "hook_event_name": "stop",
            "status": "completed",
            "conversation_id": "conv-e13-cursor",
            "workspace_roots": [str(repo)],
        }
        assert _hook(mod, monkeypatch, payload, harness="cursor") == 0
    else:
        monkeypatch.chdir(repo)
        assert (
            mod.main(["send", "--class", "done", "--text", "All rows are complete."])
            == 0
        )


SYNC_PATHS = ("on_stop", "hook_claude", "hook_codex", "hook_cursor", "send")


@pytest.mark.parametrize("path", SYNC_PATHS)
def test_branch_comes_from_the_real_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, path: str
) -> None:
    """AC-A.5 / AC-A.6 / R2-F1: an address in the working directory is masked in every artifact, but the branch lookup uses the real directory."""
    mod, home, rec = _setup(monkeypatch, tmp_path)
    _clear_git_env(monkeypatch)
    repo = _git_repo(tmp_path / f"proj-{OTHER_ADDR}", E13_BRANCH)
    _e13_run(mod, monkeypatch, repo, path)
    assert _outcomes(home) == ["sent"], _outcomes(home)
    assert len(rec.messages()) == 1
    body = rec.messages()[0].get_content()
    assert f"Branch: {E13_BRANCH}" in body, body
    blob = (_all_bytes(home).decode("utf-8", errors="replace") + body).lower()
    assert OTHER_ADDR.lower() not in blob
    assert mod.mask_addresses(str(repo)) in body


def test_deliver_takes_the_real_directory_from_its_process_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC-A.5 / R2-F1: ``deliver`` reads the real directory from AGENT_NOTIFY_WORKDIR; the pending file holds only the masked one."""
    mod, home, rec = _setup(monkeypatch, tmp_path)
    _clear_git_env(monkeypatch)
    repo = _git_repo(tmp_path / f"proj-{OTHER_ADDR}", E13_BRANCH)
    monkeypatch.setattr(mod, "DELIVERY_MODE", "detached")
    _e13_run(mod, monkeypatch, repo, "on_stop")
    pending = _pending(home)
    assert len(pending) == 1
    assert OTHER_ADDR.lower() not in pending[0].read_text(encoding="utf-8").lower()
    monkeypatch.setenv(WORKDIR_ENV, str(repo))
    assert mod.main(["deliver", str(pending[0])]) == 0
    assert _pending(home) == []
    assert len(rec.messages()) == 1
    body = rec.messages()[0].get_content()
    assert f"Branch: {E13_BRANCH}" in body, body
    blob = (_all_bytes(home).decode("utf-8", errors="replace") + body).lower()
    assert OTHER_ADDR.lower() not in blob


def test_deliver_ignores_a_process_directory_that_is_not_the_notes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """R2-F1 guard: an AGENT_NOTIFY_WORKDIR that does not mask to the note's directory is ignored; the branch comes from the note."""
    mod, home, rec = _setup(monkeypatch, tmp_path)
    _clear_git_env(monkeypatch)
    repo = _git_repo(tmp_path / "proj-note", "e13-note")
    other = _git_repo(tmp_path / "proj-other", "e13-other")
    monkeypatch.setattr(mod, "DELIVERY_MODE", "detached")
    _e13_run(mod, monkeypatch, repo, "on_stop")
    pending = _pending(home)
    assert len(pending) == 1
    monkeypatch.setenv(WORKDIR_ENV, str(other))
    assert mod.main(["deliver", str(pending[0])]) == 0
    body = rec.messages()[0].get_content()
    assert "Branch: e13-note" in body, body
    assert "e13-other" not in body


_CHILD = (
    "import importlib.util, json, sys\n"
    "spec = importlib.util.spec_from_file_location('agent_notify', sys.argv[1])\n"
    "mod = importlib.util.module_from_spec(spec)\n"
    "sys.modules['agent_notify'] = mod\n"
    "spec.loader.exec_module(mod)\n"
    "mod.DELIVERY_MODE = 'detached'\n"
    "mod.on_stop(json.loads(sys.argv[2]), 'allow', 'every row is complete',"
    " 'rows_complete', 0, None, None)\n"
)


def test_detached_worker_reports_the_real_branch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC-A.5 / AC-A.6 / R2-F1: end to end through a real detached worker, the branch is right and no file holds the address."""
    import subprocess

    _mod, home, _rec = _setup(monkeypatch, tmp_path)
    repo = _git_repo(tmp_path / f"proj-{OTHER_ADDR}", E13_BRANCH)
    drop = ("AGENT_NOTIFY", WORKDIR_ENV, "AGENT_MODEL_REGISTRY_HOME")
    env = {k: v for k, v in _git_env().items() if k not in drop}
    env.update(AGENT_NOTIFY_HOME=str(home), AGENT_NOTIFY_DRY_RUN="1")
    done = subprocess.run(
        [
            sys.executable,
            "-c",
            _CHILD,
            str(_module_path()),
            json.dumps(_e13_payload(repo)),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and not (_emls(home) and not _pending(home)):
        time.sleep(0.1)
    assert len(_emls(home)) == 1, _outcomes(home)
    assert _pending(home) == []
    body = _parse_eml(_emls(home)[0]).get_content()
    assert f"Branch: {E13_BRANCH}" in body, body
    blob = (_all_bytes(home).decode("utf-8", errors="replace") + body).lower()
    assert OTHER_ADDR.lower() not in blob
