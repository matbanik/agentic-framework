"""MEU-894 credits-start-source-verify: each start source gets a check a script can repeat.

Plan: docs/execution/plans/2026-11-05-pe21-credits-authority (MEU-894, AC-894.1..8;
KI SCHED-CREDITS-START-SOURCE-UNVERIFIED; R1-F2, R1-F5, R1-F6, R2-F2; PE21-D5, D6, D8).

* ``agent-on-user-chat``: ``request --start-session <uuid> --start-message <uuid>``; the
  quote must equal the typed text of that message after normalization (NFC, one space per
  white-space run, strip). The row stores ``source_check = 'transcript_verified'``.
* (``run_id``, ``start_message``) is unique while the message is held; an unstarted
  ``launch_failed`` (``--cli-start absent``) gives the message back.
* ``monitor-chain``: the chain block names ``session`` and ``message_uuid``;
  ``authority`` reports ``chain_verified``.
* ``human-command``: ``attest_console`` (injectable reader and clock) in the prepare stage,
  before the write transaction; the ``CREDITS_ATTEST_FILE`` test seam off the production db.
* ``authority`` reports and re-checks ``source_check``.
* ``start_message_ok`` (E17) is containment after normalization on both sides.
* SCHEMA_V8 under the init crash points; a newer store is refused.
* The callers and the docs name ``-StartSession`` and ``-StartMessage``.

Every store call is a real ``credits_state.py`` subprocess on a temp store, except the
console tests of AC-894.4, which run ``main`` in process with an injected reader and clock.
"""

from __future__ import annotations

import contextlib
import importlib
import json
import re
import shutil
import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from test_credits_authority import agent, authority, chain_manifest, start
from test_credits_state import (
    ROOT,
    SESSION_B,
    Out,
    Seg,
    Store,
    accept_args,
    at,
    finish,
    launched_args,
    make_registered,
    register_args,
    request_args,
    run_cli,
    start_transcript_uuid,
    stop,
    write_manifest,
)

FX_ROOT = "X:/fixture-project"
SKILL_DIR = ROOT / ".agent" / "skills" / "claude-credits"
NEW_REQUEST_COLUMNS = (
    "start_session",
    "start_message",
    "source_check",
    "attested_utc",
    "attest_channel",
    "message_released_utc",
)
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
TYPED_CODE = "K7MPQ2"


@pytest.fixture
def st(tmp_path: Path) -> Store:
    store = Store(tmp_path / "store")
    store.root.mkdir()
    # The transcript config exists from the start, so CLAUDE_CONFIG_DIR never falls back
    # to the real ~/.claude of the host.
    store.start_transcript_config().mkdir(parents=True)
    store.init()
    return store


def _cs_tool() -> ModuleType:
    """``credits_state`` as ``credits_msg`` imports it (``tools/`` on ``sys.path``)."""
    tools = str(ROOT / "tools")
    if tools not in sys.path:
        sys.path.append(tools)
    return importlib.import_module("credits_state")


def _msg() -> ModuleType:
    """``credits_msg``; it imports its sibling as ``credits_state``."""
    _cs_tool()
    return importlib.import_module("credits_msg")


def _uuid(seed: str) -> str:
    return start_transcript_uuid(f"ac894|{seed}")


def _request_rows(st: Store, request_id: str) -> list[tuple[Any, ...]]:
    return st.rows("SELECT * FROM requests WHERE request_id = ?", (request_id,))


def _request(st: Store, request_id: str) -> dict[str, Any]:
    with contextlib.closing(sqlite3.connect(st.db)) as con:
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT * FROM requests WHERE request_id = ?", (request_id,)
        ).fetchone()
    assert row is not None, request_id
    return dict(row)


def _run_state(st: Store, run_id: str) -> str:
    return str(st.one("SELECT state FROM runs WHERE run_id = ?", (run_id,)))


def _agent_request(
    st: Store,
    run_id: str,
    request_id: str,
    quote: str,
    session: str,
    message: str,
    *extra: str,
    now: int = 0,
) -> Out:
    """An agent-on-user-chat request that names its start message (no fixture default)."""
    return st.cli(
        "request",
        "--run-id",
        run_id,
        "--request-id",
        request_id,
        "--started-by",
        "agent-on-user-chat",
        "--quote",
        quote,
        "--start-session",
        session,
        "--start-message",
        message,
        *extra,
        now=now,
    )


def _append_record(st: Store, session: str, record: dict[str, Any]) -> None:
    path = st.start_transcript_file(FX_ROOT, session)
    path.parent.mkdir(parents=True, exist_ok=True)
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(old + json.dumps(record) + "\n", encoding="utf-8", newline="\n")


def _typed_fields(session: str, message: str) -> dict[str, Any]:
    return {
        "type": "user",
        "sessionId": session,
        "uuid": message,
        "parentUuid": None,
        "isSidechain": False,
        "userType": "external",
        "origin": {"kind": "human"},
        "turnOrigin": "human",
        "promptSource": "typed",
        "promptId": f"prompt-{message}",
        "timestamp": "2026-10-16T09:00:00.000Z",
    }


def _refused(out: Out, error: str, st: Store, request_id: str) -> None:
    assert out.code == 3 and out.error == error, out.show()
    assert _request_rows(st, request_id) == [], out.show()


# --- AC-894.1 agent-on-user-chat ------------------------------------------------------


def test_ac_894_1_agent_quote_must_equal_the_typed_message(st: Store) -> None:
    """AC-894.1: equality after normalization writes transcript_verified; every other source is refused, no row."""
    run = "run-t1"
    make_registered(st, run)
    session = _uuid("t1-session")
    quote = "start the fixture run now"

    sub = _uuid("t1-substring")
    st.start_transcript_record(
        FX_ROOT, session, sub, "please start the fixture run now and report back"
    )
    _refused(
        _agent_request(st, run, "req-sub", quote, session, sub),
        "start_quote_mismatch",
        st,
        "req-sub",
    )

    tool = _uuid("t1-tool-result")
    tool_record = _typed_fields(session, tool)
    tool_record["toolUseResult"] = {"stdout": quote, "stderr": ""}
    tool_record["message"] = {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "toolu_fixture", "content": quote}
        ],
    }
    _append_record(st, session, tool_record)
    _refused(
        _agent_request(st, run, "req-tool", quote, session, tool),
        "start_message_not_found",
        st,
        "req-tool",
    )

    frame = _uuid("t1-injected-frame")
    frame_record = _typed_fields(session, frame)
    frame_record["isMeta"] = True
    frame_record["message"] = {"role": "user", "content": quote}
    _append_record(st, session, frame_record)
    _refused(
        _agent_request(st, run, "req-frame", quote, session, frame),
        "start_message_not_found",
        st,
        "req-frame",
    )

    unknown = _uuid("t1-unknown")
    _refused(
        _agent_request(st, run, "req-unknown", quote, session, unknown),
        "start_message_not_found",
        st,
        "req-unknown",
    )

    lost = _uuid("t1-no-transcript")
    _refused(
        _agent_request(st, run, "req-lost", quote, lost, _uuid("t1-lost-message")),
        "start_session_unlisted",
        st,
        "req-lost",
    )

    assert _run_state(st, run) == "registered"

    typed = _uuid("t1-typed")
    st.start_transcript_record(FX_ROOT, session, typed, "start  the\nfixture run now ")
    out = _agent_request(st, run, "req-ok", quote, session, typed)
    assert out.code == 0 and out.result == "changed", out.show()
    row = _request(st, "req-ok")
    assert row["source_check"] == "transcript_verified"
    assert row["start_session"] == session
    assert row["start_message"] == typed
    assert row["start_quote"] == quote
    assert _run_state(st, run) == "requested"


def test_ac_894_1_start_flags_follow_the_start_source(st: Store) -> None:
    """AC-894.1 boundary: the start flags are required for an agent, refused for the other sources; UUID and length rules."""
    run = "run-t1b"
    make_registered(st, run)
    session = _uuid("t1b-session")
    message = _uuid("t1b-message")
    st.start_transcript_record(FX_ROOT, session, message, "start run-t1b")

    missing = run_cli(
        st.db,
        "request",
        "--run-id",
        run,
        "--request-id",
        "req-missing",
        "--started-by",
        "agent-on-user-chat",
        "--quote",
        "start run-t1b",
        env=st.env(),
    )
    _refused(missing, "start_source_missing", st, "req-missing")

    refused = run_cli(
        st.db,
        "request",
        "--run-id",
        run,
        "--request-id",
        "req-human-flags",
        "--started-by",
        "human-command",
        "--start-session",
        session,
        "--start-message",
        message,
        env=st.env(),
    )
    _refused(refused, "start_source_refused", st, "req-human-flags")

    upper = _agent_request(
        st, run, "req-upper", "start run-t1b", session.upper(), message.upper()
    )
    assert upper.code in (2, 3), upper.show()
    assert _request_rows(st, "req-upper") == []

    cs = _cs_tool()
    assert getattr(cs, "QUOTE_MAX_CHARS", None) == 4000
    long_message = _uuid("t1b-long")
    long_quote = "x" * 4001
    st.start_transcript_record(FX_ROOT, session, long_message, long_quote)
    _refused(
        _agent_request(st, run, "req-long", long_quote, session, long_message),
        "quote_out_of_range",
        st,
        "req-long",
    )

    out = _agent_request(st, run, "req-ok", "start run-t1b", session, message)
    assert out.code == 0 and out.result == "changed", out.show()


# --- AC-894.2 one typed message, one segment --------------------------------------------


def _resume_flags(brief: Path) -> tuple[str, ...]:
    return ("--resume", "--resume-mode", "fresh", "--brief", str(brief))


def test_ac_894_2_a_start_message_starts_one_segment(st: Store, tmp_path: Path) -> None:
    """AC-894.2: the same message on a resume is refused start_message_reused; a new message is accepted."""
    run = "run-t2"
    make_registered(st, run)
    session = _uuid("t2-session")
    first = _uuid("t2-first")
    st.start_transcript_record(FX_ROOT, session, first, "start run-t2")
    out = _agent_request(st, run, f"req-{run}-1", "start run-t2", session, first)
    assert out.code == 0, out.show()
    seg = _launch(st, run, 1, f"req-{run}-1", now=0)
    finish(st, seg, now=20, total=1.0)
    stop(st, run, now=21)
    brief = tmp_path / "resume-brief.md"
    brief.write_text("# resume brief\n", encoding="utf-8")

    again = _agent_request(
        st,
        run,
        f"req-{run}-2",
        "start run-t2",
        session,
        first,
        *_resume_flags(brief),
        now=30,
    )
    _refused(again, "start_message_reused", st, f"req-{run}-2")
    assert _run_state(st, run) == "stopped"

    second = _uuid("t2-second")
    st.start_transcript_record(FX_ROOT, session, second, "resume run-t2")
    out = _agent_request(
        st,
        run,
        f"req-{run}-3",
        "resume run-t2",
        session,
        second,
        *_resume_flags(brief),
        now=31,
    )
    assert out.code == 0 and out.result == "changed", out.show()
    assert _request(st, f"req-{run}-3")["start_message"] == second


def _admitted(st: Store, run: str, n: int, request_id: str, *, now: int) -> str:
    """Accept and admit request ``n`` (no launched record: the segment is launching)."""
    st.ok("accept", *accept_args(run, n, SESSION_B), now=now + 5)
    st.ok(
        "admit",
        "--attempt-id",
        f"att-{run}-{n}",
        "--segment-id",
        f"seg-{run}-{n}",
        now=now + 6,
    )
    assert _request(st, request_id)["state"] == "admitted"
    return f"seg-{run}-{n}"


def _launch(st: Store, run: str, n: int, request_id: str, *, now: int) -> Seg:
    """Accept, admit and launch a request that the test filed itself."""
    segment = _admitted(st, run, n, request_id, now=now)
    st.ok("launched", *launched_args(segment, now + 7), now=now + 7)
    return Seg(run, request_id, f"att-{run}-{n}", segment, SESSION_B)


def test_ac_894_2_an_unstarted_launch_failure_gives_the_message_back(
    st: Store, tmp_path: Path
) -> None:
    """AC-894.2 (R1-F5, MEU-895 item 6): launch_failed --cli-start absent releases; present keeps the message."""
    run = "run-t2b"
    make_registered(st, run)
    session = _uuid("t2b-session")
    words = _uuid("t2b-words")
    st.start_transcript_record(FX_ROOT, session, words, "start run-t2b")
    out = _agent_request(st, run, "req-a", "start run-t2b", session, words)
    assert out.code == 0, out.show()
    segment = _admitted(st, run, 1, "req-a", now=0)
    st.ok(
        "complete_segment",
        "--segment-id",
        segment,
        "--finalized-by",
        "launcher",
        "--class",
        "launch_failed",
        "--cli-start",
        "absent",
        now=10,
    )
    released = _request(st, "req-a")
    assert released["message_released_utc"] is not None
    assert _run_state(st, run) == str(released["previous_state"])

    retry = _agent_request(st, run, "req-b", "start run-t2b", session, words, now=20)
    assert retry.code == 0 and retry.result == "changed", retry.show()
    assert _request(st, "req-b")["start_message"] == words

    # A resume whose CLI started keeps its message.
    run2 = "run-t2c"
    make_registered(st, run2)
    first = start(st, run2, 1, now=0, request=agent("start run-t2c"))
    finish(st, first, now=20, total=1.0)
    stop(st, run2, now=21)
    brief = tmp_path / "resume-brief.md"
    brief.write_text("# resume brief\n", encoding="utf-8")
    resume_words = _uuid("t2c-resume")
    st.start_transcript_record(FX_ROOT, session, resume_words, "resume run-t2c")
    out = _agent_request(
        st,
        run2,
        f"req-{run2}-2",
        "resume run-t2c",
        session,
        resume_words,
        *_resume_flags(brief),
        now=30,
    )
    assert out.code == 0, out.show()
    segment2 = _admitted(st, run2, 2, f"req-{run2}-2", now=30)
    st.ok(
        "complete_segment",
        "--segment-id",
        segment2,
        "--finalized-by",
        "launcher",
        "--class",
        "launch_failed",
        "--cli-start",
        "present",
        now=40,
    )
    assert _request(st, f"req-{run2}-2")["message_released_utc"] is None
    assert _run_state(st, run2) == "stopped"
    again = _agent_request(
        st,
        run2,
        f"req-{run2}-3",
        "resume run-t2c",
        session,
        resume_words,
        *_resume_flags(brief),
        now=50,
    )
    _refused(again, "start_message_reused", st, f"req-{run2}-3")


# --- AC-894.3 monitor-chain ---------------------------------------------------------------


def _register(st: Store, run_id: str, manifest: Path) -> Out:
    return st.cli(
        "register",
        "--run-id",
        run_id,
        "--manifest",
        str(manifest),
        "--cli-version",
        "9.9.9",
        "--kit-revision",
        "kitrev-fixture",
    )


def test_ac_894_3_chain_block_names_its_start_message(st: Store) -> None:
    """AC-894.3: the old chain block is refused; a full block registers; authority gives chain_verified."""
    schema = json.loads(
        (SKILL_DIR / "schemas" / "credits-run.v1.json").read_text(encoding="utf-8")
    )
    chain_schema = schema["properties"]["chain"]
    assert {"session", "message_uuid"} <= set(chain_schema["required"])
    assert chain_schema.get("additionalProperties") is False

    old = write_manifest(st, "run-old-chain")
    doc = json.loads(old.read_text(encoding="utf-8"))
    doc["chain"] = {
        "chain_id": "chain-1",
        "quote": "run the fixture chain",
        "given_at": at(-100),
        "chain_cap_usd": 50.0,
    }
    old.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    out = _register(st, "run-old-chain", old)
    assert out.code == 3 and out.error == "manifest_invalid", out.show()
    assert st.rows("SELECT run_id FROM runs WHERE run_id = 'run-old-chain'") == []

    cs = _cs_tool()
    assert {"session", "message_uuid"} <= set(cs.CHAIN_KEYS)

    manifest = chain_manifest(st, "run-c")
    out = _register(st, "run-c", manifest)
    assert out.code == 0 and out.result == "changed", out.show()
    st.ok("registered", "--run-id", "run-c", "--task-hash", "taskhash-run-c")
    seg = start(
        st,
        "run-c",
        1,
        now=0,
        request=("--started-by", "monitor-chain", "--chain-id", "chain-1"),
    )
    shown = authority(st, "run-c", seg.segment_id)
    assert shown.code == 0 and shown.result == "ok", shown.show()
    payload = shown.payload or {}
    assert payload["source_check"] == "chain_verified"
    assert payload["chain"] == {
        "chain_id": "chain-1",
        "quote": "run the fixture chain",
        "given_at": at(-100),
    }


# --- AC-894.4 human-command console attestation ---------------------------------------------


class FakeReader:
    """An injected console: ``available``, ``write_prompt``, ``kbhit`` and ``getwch``."""

    def __init__(
        self,
        keys: str | Callable[[list[str]], str] = "",
        *,
        available: bool = True,
        on_poll: Callable[[int], None] | None = None,
    ) -> None:
        self._keys = keys
        self._queue: list[str] | None = None
        self._available = available
        self._on_poll = on_poll
        self.prompts: list[str] = []
        self.polls = 0

    def available(self) -> bool:
        return self._available

    def write_prompt(self, text: str) -> None:
        self.prompts.append(text)

    def _pending(self) -> list[str]:
        if self._queue is None:
            keys = self._keys(self.prompts) if callable(self._keys) else self._keys
            self._queue = list(keys)
        return self._queue

    def kbhit(self) -> bool:
        self.polls += 1
        if self._on_poll is not None:
            self._on_poll(self.polls)
        return bool(self._pending())

    def getwch(self) -> str:
        queue = self._pending()
        assert queue, "getwch called with no key pending"
        return queue.pop(0)


class FakeClock:
    """Monotonic seconds that advance by ``step`` on each read."""

    def __init__(self, step: float = 1.0) -> None:
        self.step = step
        self.reads: list[float] = []
        self._now = 1000.0

    def __call__(self) -> float:
        value = self._now
        self.reads.append(value)
        self._now += self.step
        return value

    def span(self) -> float:
        return max(self.reads) - min(self.reads) if self.reads else 0.0


def _console(
    monkeypatch: pytest.MonkeyPatch,
    cs: ModuleType,
    reader: FakeReader,
    clock: FakeClock,
    code: str | None = TYPED_CODE,
) -> list[dict[str, Any]]:
    """Patch ``attest_console`` to run the real one with the injected reader, clock and code."""
    current = getattr(cs, "attest_console", None)
    assert current is not None, "credits_state.attest_console is missing"
    real = getattr(current, "_real", current)
    seen: list[dict[str, Any]] = []

    def injected(run_id: str, *, timeout_s: int, **_defaults: Any) -> Any:
        seen.append({"run_id": run_id, "timeout_s": timeout_s})
        return real(run_id, timeout_s=timeout_s, reader=reader, clock=clock, code=code)

    injected.__dict__["_real"] = real
    monkeypatch.setattr(cs, "attest_console", injected)
    return seen


def _no_credits_env(monkeypatch: pytest.MonkeyPatch, st: Store) -> None:
    import os

    for name in list(os.environ):
        if name.upper().startswith("CREDITS_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(st.start_transcript_config()))


def _main_request(
    cs: ModuleType,
    st: Store,
    run_id: str,
    request_id: str,
    *extra: str,
    now: int = 10,
) -> int:
    argv = [
        "--db",
        str(st.db),
        "--now-utc",
        at(now),
        "request",
        "--run-id",
        run_id,
        "--started-by",
        "human-command",
        "--request-id",
        request_id,
        *extra,
    ]
    return int(cs.main(argv))


def _last_json(text: str) -> dict[str, Any]:
    lines = [line for line in text.splitlines() if line.strip().startswith("{")]
    assert lines, text
    loaded = json.loads(lines[-1])
    assert isinstance(loaded, dict)
    return loaded


def test_ac_894_4_console_code_attests_a_human_command_start(
    st: Store, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-894.4: a typed code gives console_attested; no console, a wrong code are refused; the code never reaches stdout."""
    cs = _cs_tool()
    assert getattr(cs, "ATTEST_TIMEOUT_S", None) == 120
    assert getattr(cs, "ATTEST_CALLER_MARGIN_S", None) == 60
    assert getattr(cs, "ATTEST_CODE_LEN", None) == 6
    _no_credits_env(monkeypatch, st)
    run = "run-t4"
    make_registered(st, run)

    absent = FakeReader(available=False)
    _console(monkeypatch, cs, absent, FakeClock())
    code = _main_request(cs, st, run, "req-absent")
    payload = _last_json(capsys.readouterr().out)
    assert (code, payload.get("error")) == (3, "attest_no_console"), payload
    assert _request_rows(st, "req-absent") == []

    wrong = FakeReader("ZZZZZZ\r")
    _console(monkeypatch, cs, wrong, FakeClock())
    code = _main_request(cs, st, run, "req-wrong")
    payload = _last_json(capsys.readouterr().out)
    assert (code, payload.get("error")) == (3, "attest_mismatch"), payload
    assert _request_rows(st, "req-wrong") == []
    assert _run_state(st, run) == "registered"

    typed = FakeReader(TYPED_CODE + "\r")
    seen = _console(monkeypatch, cs, typed, FakeClock())
    code = _main_request(cs, st, run, "req-typed")
    captured = capsys.readouterr()
    payload = _last_json(captured.out)
    assert code == 0 and payload.get("result") == "changed", payload
    assert TYPED_CODE not in captured.out and TYPED_CODE not in captured.err
    assert [prompt.strip() for prompt in typed.prompts if TYPED_CODE in prompt] == [
        f"Type this code to start run {run}: {TYPED_CODE}"
    ]
    assert seen == [{"run_id": run, "timeout_s": 120}]
    row = _request(st, "req-typed")
    assert row["source_check"] == "console_attested"
    assert row["attest_channel"] == "console"
    assert isinstance(row["attested_utc"], str) and re.fullmatch(
        r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", row["attested_utc"]
    )
    assert row["start_session"] is None and row["start_message"] is None


def test_ac_894_4_generated_code_and_the_injected_timeout(
    st: Store, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-894.4 (R2-F2): the generated code uses the alphabet; --attest-timeout-s 600 waits 600 s of the injected clock."""
    cs = _cs_tool()
    _no_credits_env(monkeypatch, st)
    make_registered(st, "run-t4g")

    def echo(prompts: list[str]) -> str:
        found = (
            re.fullmatch(
                r"Type this code to start run run-t4g: (\S+)", prompts[-1].strip()
            )
            if prompts
            else None
        )
        return (found.group(1) if found else "") + "\r"

    echoing = FakeReader(echo)
    _console(monkeypatch, cs, echoing, FakeClock(), code=None)
    code = _main_request(cs, st, "run-t4g", "req-gen")
    captured = capsys.readouterr()
    assert code == 0, captured.out
    generated = re.fullmatch(
        r"Type this code to start run run-t4g: (\S+)", echoing.prompts[-1].strip()
    )
    assert generated is not None, echoing.prompts
    assert re.fullmatch(f"[{CODE_ALPHABET}]{{6}}", generated.group(1))
    assert generated.group(1) not in captured.out
    assert _request(st, "req-gen")["attest_channel"] == "console"

    make_registered(st, "run-t4t")
    slow = FakeClock(step=20.0)
    seen = _console(monkeypatch, cs, FakeReader(""), slow)
    code = _main_request(cs, st, "run-t4t", "req-600", "--attest-timeout-s", "600")
    payload = _last_json(capsys.readouterr().out)
    assert (code, payload.get("error")) == (3, "attest_timeout"), payload
    assert seen == [{"run_id": "run-t4t", "timeout_s": 600}]
    assert slow.span() >= 600, slow.reads
    assert _request_rows(st, "req-600") == []

    short = FakeClock(step=20.0)
    seen = _console(monkeypatch, cs, FakeReader(""), short)
    code = _main_request(cs, st, "run-t4t", "req-120")
    payload = _last_json(capsys.readouterr().out)
    assert (code, payload.get("error")) == (3, "attest_timeout"), payload
    assert seen == [{"run_id": "run-t4t", "timeout_s": 120}]
    assert 120 <= short.span() < 600, short.reads
    assert _request_rows(st, "req-120") == []


def test_ac_894_4_no_writer_lock_while_the_human_types(
    st: Store, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-894.4 (R1-F6): another verb writes during the wait; a run state changed meanwhile refuses in the transaction."""
    cs = _cs_tool()
    _no_credits_env(monkeypatch, st)
    run = "run-t4c"
    make_registered(st, run)
    side: list[Out] = []

    def write_meanwhile(poll: int) -> None:
        if poll == 1:
            side.append(
                run_cli(
                    st.db,
                    "register",
                    *register_args(st, "run-side"),
                    env=st.env({"CREDITS_TEST_BUSY_TIMEOUT_MS": "2000"}),
                )
            )
            side.append(
                run_cli(
                    st.db, "check", env=st.env({"CREDITS_TEST_BUSY_TIMEOUT_MS": "2000"})
                )
            )

    reader = FakeReader(TYPED_CODE + "\r", on_poll=write_meanwhile)
    _console(monkeypatch, cs, reader, FakeClock())
    code = _main_request(cs, st, run, "req-held")
    payload = _last_json(capsys.readouterr().out)
    assert code == 0, payload
    assert len(side) == 2
    assert side[0].code == 0 and side[0].result == "changed", side[0].show()
    assert side[1].code == 0 and side[1].result == "ok", side[1].show()

    run2 = "run-t4d"
    make_registered(st, run2)
    competing: list[Out] = []

    def compete(poll: int) -> None:
        if poll == 1:
            competing.append(
                run_cli(
                    st.db,
                    "request",
                    *request_args(run2, 9),
                    env=st.env({"CREDITS_TEST_BUSY_TIMEOUT_MS": "2000"}),
                )
            )

    racing = FakeReader(TYPED_CODE + "\r", on_poll=compete)
    _console(monkeypatch, cs, racing, FakeClock())
    code = _main_request(cs, st, run2, "req-ours")
    payload = _last_json(capsys.readouterr().out)
    assert len(competing) == 1 and competing[0].code == 0, (
        competing[0].show() if competing else "no competing call"
    )
    assert code == 3, payload
    assert _request_rows(st, "req-ours") == []
    assert [
        r[0]
        for r in st.rows("SELECT request_id FROM requests WHERE run_id = ?", (run2,))
    ] == [f"req-{run2}-9"]


def test_ac_894_4_attest_file_seam_and_timeout_range(
    st: Store,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-894.4: the file seam attests off the production db only; --attest-timeout-s outside [1, 600] is refused."""
    make_registered(st, "run-t4f")
    for value in ("0", "601"):
        out = st.cli(
            "request", *request_args("run-t4f", 1), "--attest-timeout-s", value
        )
        _refused(out, "attest_timeout_out_of_range", st, "req-run-t4f-1")

    bad = tmp_path / "bad-code.txt"
    bad.write_text("not a code\n", encoding="utf-8")
    out = st.cli(
        "request", *request_args("run-t4f", 2), env={"CREDITS_ATTEST_FILE": str(bad)}
    )
    _refused(out, "attest_mismatch", st, "req-run-t4f-2")

    gone = tmp_path / "no-such-code.txt"
    out = st.cli(
        "request", *request_args("run-t4f", 3), env={"CREDITS_ATTEST_FILE": str(gone)}
    )
    _refused(out, "attest_no_console", st, "req-run-t4f-3")

    out = st.cli("request", *request_args("run-t4f", 4), "--attest-timeout-s", "600")
    assert out.code == 0 and out.result == "changed", out.show()
    assert "ABCDEF" not in out.stdout
    row = _request(st, "req-run-t4f-4")
    assert (row["source_check"], row["attest_channel"]) == ("console_attested", "file")
    assert row["attested_utc"] is not None

    cs = _cs_tool()
    production = getattr(cs, "PRODUCTION_DB", None)
    assert production is not None
    assert (
        Path(production).resolve()
        == Path("{{RECEIPTS_DIR}}/credits/state.db").resolve()
    )
    _no_credits_env(monkeypatch, st)
    make_registered(st, "run-t4s")
    good = tmp_path / "good-code.txt"
    good.write_text("ABCDEF\n", encoding="utf-8")
    monkeypatch.setenv("CREDITS_ATTEST_FILE", str(good))
    monkeypatch.setattr(
        cs, "PRODUCTION_DB", str(st.db) if isinstance(production, str) else Path(st.db)
    )
    _console(monkeypatch, cs, FakeReader(available=False), FakeClock())
    code = _main_request(cs, st, "run-t4s", "req-seam")
    payload = _last_json(capsys.readouterr().out)
    assert (code, payload.get("error")) == (3, "attest_seam_refused"), payload
    assert _request_rows(st, "req-seam") == []


# --- AC-894.5 authority re-checks the source ----------------------------------------------


def test_ac_894_5_authority_reports_and_rechecks_the_source(st: Store) -> None:
    """AC-894.5: source_check shown and re-checked; pre-v8 row, untrusted file channel, edited quote refused."""
    make_registered(st, "run-a")
    seg = start(st, "run-a", 1, now=0, request=agent("start run-a"))
    out = authority(st, "run-a", seg.segment_id, "--quote", "start run-a")
    assert out.code == 0 and out.result == "ok", out.show()
    assert (out.payload or {})["source_check"] == "transcript_verified"

    make_registered(st, "run-h", lane="tree:X:/fixture-tree-b")
    human = start(st, "run-h", 1, now=0, request=("--started-by", "human-command"))
    out = authority(st, "run-h", human.segment_id)
    assert out.code == 0 and out.result == "ok", out.show()
    assert (out.payload or {})["source_check"] == "console_attested"

    out = authority(st, "run-h", human.segment_id, drop="CREDITS_ATTEST_FILE")
    assert out.code == 3 and out.error == "authority_attest_untrusted", out.show()
    assert (out.payload or {}).get("authorized") is not True

    st.write(
        "UPDATE requests SET source_check = NULL WHERE request_id = ?",
        (human.request_id,),
    )
    out = authority(st, "run-h", human.segment_id)
    assert out.code == 3 and out.error == "authority_source_unverified", out.show()

    st.write(
        "UPDATE requests SET start_quote = 'start a different run' WHERE request_id = ?",
        (seg.request_id,),
    )
    out = authority(st, "run-a", seg.segment_id, "--quote", "start a different run")
    assert out.code == 3, out.show()
    assert (out.payload or {}).get("authorized") is not True


# --- AC-894.6 E17 containment after normalization -----------------------------------------


def test_ac_894_6_start_message_ok_is_normalized_containment() -> None:
    """AC-894.6 (R1-F2): the quote with other white space inside the typed text is held; another text is not."""
    cm = _msg()
    session = _uuid("t6-session")
    message = _uuid("t6-message")
    quote = "start the fixture run now"
    texts = {
        "line break": "yes: start the fixture\nrun  now.",
        "ea21": f"yes: {quote}.",
        "other": "yes: start a different run.",
    }

    def fake_pr(text: str) -> SimpleNamespace:
        def typed_human_text(tree: Any, s: str, u: str) -> str | None:
            return text if (s, u) == (session, message) else None

        return SimpleNamespace(
            request={"start_quote": quote},
            doc={"messaging": {"orchestrator_sessions": [session]}},
            tree=ROOT,
            rp=SimpleNamespace(typed_human_text=typed_human_text),
        )

    payload = {"message_uuid": message}
    assert cm.start_message_ok(fake_pr(texts["line break"]), payload) is True
    assert cm.start_message_ok(fake_pr(texts["ea21"]), payload) is True
    assert cm.start_message_ok(fake_pr(texts["other"]), payload) is False


# --- AC-894.7 SCHEMA_V8 ----------------------------------------------------------------


def _v7_store(path: Path, cs: ModuleType) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.closing(sqlite3.connect(path)) as con:
        for version in range(1, 8):
            for statement in cs.SCHEMA_STEPS[version]:
                con.execute(statement)
        con.execute("PRAGMA user_version = 7")
        con.execute(
            "INSERT INTO runs (run_id, state, kind, supervision, created_utc, updated_utc)"
            " VALUES ('run-v7', 'requested', 'exec', 'job', ?, ?)",
            (at(0), at(0)),
        )
        con.execute(
            "INSERT INTO requests (request_id, run_id, state, previous_state, started_by,"
            " resume, created_utc, updated_utc)"
            " VALUES ('req-v7', 'run-v7', 'pending', 'registered', 'human-command', 0, ?, ?)",
            (at(0), at(0)),
        )
        con.commit()


def _shape(db: Path) -> tuple[int, set[str], list[dict[str, Any]]]:
    with contextlib.closing(sqlite3.connect(db)) as con:
        version = int(con.execute("PRAGMA user_version").fetchone()[0])
        columns = {str(r[1]) for r in con.execute("PRAGMA table_info(requests)")}
        indexes: list[dict[str, Any]] = []
        for row in con.execute("PRAGMA index_list(requests)"):
            name = str(row[1])
            cols = [str(c[2]) for c in con.execute(f'PRAGMA index_info("{name}")')]
            sql = con.execute(
                "SELECT sql FROM sqlite_master WHERE name = ?", (name,)
            ).fetchone()
            indexes.append(
                {
                    "name": name,
                    "unique": int(row[2]),
                    "partial": int(row[4]),
                    "cols": cols,
                    "sql": sql[0] if sql else None,
                }
            )
    return version, columns, indexes


def _start_index(indexes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        i
        for i in indexes
        if i["unique"] == 1
        and i["partial"] == 1
        and i["cols"] == ["run_id", "start_message"]
    ]


def test_ac_894_7_schema_v8_migrates_under_each_crash_point(tmp_path: Path) -> None:
    """AC-894.7: v7 → v8 with the columns and the partial unique index; a crash leaves v7 or v8; v9 is refused."""
    cs = importlib.import_module("tools.credits_state")
    assert cs.SCHEMA_VERSION == 8
    base = tmp_path / "v7" / "state.db"
    _v7_store(base, cs)
    for point in cs.CRASH_POINTS["init"]:
        db = tmp_path / point / "state.db"
        db.parent.mkdir()
        shutil.copyfile(base, db)
        out = run_cli(db, "init", env={"CREDITS_TEST_CRASH_AT": f"init:{point}"})
        assert out.code == 9, f"{point}: {out.show()}"
        version, columns, indexes = _shape(db)
        if version == 7:
            assert not set(NEW_REQUEST_COLUMNS) & columns, (point, columns)
            assert _start_index(indexes) == [], (point, indexes)
        else:
            assert version == 8, (point, version)
            assert set(NEW_REQUEST_COLUMNS) <= columns, (point, columns)
            assert len(_start_index(indexes)) == 1, (point, indexes)
        assert version == (8 if point == "after_commit" else 7), (point, version)

        out = run_cli(db, "init")
        assert out.code == 0, f"{point}: {out.show()}"
        version, columns, indexes = _shape(db)
        assert version == 8 and set(NEW_REQUEST_COLUMNS) <= columns
        found = _start_index(indexes)
        assert len(found) == 1, indexes
        where = re.sub(r"\s+", " ", str(found[0]["sql"])).lower()
        assert (
            "start_message is not null" in where
            and "message_released_utc is null" in where
        ), where
        with contextlib.closing(sqlite3.connect(db)) as con:
            kept = con.execute(
                "SELECT run_id, state, start_message, source_check FROM requests WHERE request_id = 'req-v7'"
            ).fetchall()
        assert kept == [("run-v7", "pending", None, None)], point

    db = tmp_path / "after_commit" / "state.db"
    with contextlib.closing(sqlite3.connect(db)) as con:
        con.execute("PRAGMA foreign_keys = ON")
        insert = (
            "INSERT INTO requests (request_id, run_id, state, previous_state, started_by, resume,"
            " created_utc, updated_utc, start_message, message_released_utc) VALUES (?, 'run-v7', 'launch_failed',"
            " 'registered', 'agent-on-user-chat', 0, ?, ?, 'm-1', ?)"
        )
        con.execute(insert, ("req-x1", at(1), at(1), None))
        with pytest.raises(sqlite3.IntegrityError):
            con.execute(insert, ("req-x2", at(2), at(2), None))
        con.execute(
            "UPDATE requests SET message_released_utc = ? WHERE request_id = 'req-x1'",
            (at(3),),
        )
        con.execute(insert, ("req-x3", at(4), at(4), None))
        con.rollback()

    newer = tmp_path / "newer" / "state.db"
    newer.parent.mkdir()
    assert run_cli(newer, "init").code == 0
    with contextlib.closing(sqlite3.connect(newer)) as con:
        con.execute(f"PRAGMA user_version = {cs.SCHEMA_VERSION + 1}")
        con.commit()
    out = run_cli(newer, "check")
    assert out.code == 3 and out.error == "schema_too_new", out.show()


# --- AC-894.8 callers and docs -------------------------------------------------------------


def test_ac_894_8_callers_and_docs_name_the_start_message() -> None:
    """AC-894.8: SKILL.md, the resume-brief template and the SRT help name -StartSession and -StartMessage."""
    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    template = (SKILL_DIR / "templates" / "resume-brief.md").read_text(encoding="utf-8")
    srt = (SKILL_DIR / "Start-CreditsRunTask.ps1").read_text(encoding="utf-8")
    help_block = srt[srt.index("<#") : srt.index("#>")]
    for name in ("-StartSession", "-StartMessage"):
        assert name in skill, name
        assert name in template, name
        assert name.lstrip("-") in help_block, name
