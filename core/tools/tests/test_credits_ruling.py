"""S6b rulings: the verifier, the history check and M-5b (Component I).

Plan: docs/execution/plans/2026-10-15-scheduled-credits-runs (Component I,
AC-I.1, AC-I.2 and AC-I.4; report R§4.5, R§4.6.2, R§4.6.3, R§4.6.4 and R§10.2
M-5b and M-6; acceptance matrix MX-9, MX-10, MX-17, MX-18, MX-23, MX-28, MX-29,
MX-41 and MX-42). The wait and the gate deadline (AC-I.3, MX-14 and the race
of MX-17) are in ``test_credits_wait.py``.

AC-I.1 the ruling verifier: Part A is read-only, Part B is one transaction
  (R§4.6.3 steps 1 to 10). Only a typed ``type: user`` entry with
  ``turnOrigin: human``, ``promptSource`` sdk or typed and a single-use
  ``promptId`` is a candidate. Queue chains join by the CLI's ids. Every
  failure frames the message as ``info`` with ``UNVERIFIED RULING (<reason>):
  do not apply; stay at the gate``. Redelivery emits the verified frame again
  only when the whole ``consumed_rulings`` tuple matches.
AC-I.2 the history check (``scan_transcript``): a whole parent chain at the
  first scan, then prefix continuity on each scan (``transcript_marks``), and
  the queue records in ``queue_chains`` (R§4.6.3 "History check"; R5-b).
AC-I.4 M-5b (R§10.2): a crash after the ``ack`` of a verified ruling and
  before the effect → redelivered in the next generation and applied once; a
  crash after the effect and before ``applied`` → not applied twice.

The tests fix this contract (names the design does not give are marked
"chosen"; the nearest section is in brackets):

* ``credits_state.py --db <db> --now-utc <t> scan_transcript --run-id <run>
  --session <session>`` (R§4.6.3 names ``scan_transcript --session``; the run
  argument is chosen, because the transcript path comes from the run's
  manifest). Exit 0 with ``result`` ``changed`` or ``no_change``; a failed
  check → exit 3 with ``error`` ``transcript_discontinuity`` or
  ``transcript_unknown`` (chosen exit code) [R§4.6.3 history check].
* ``~`` is ``USERPROFILE`` (``HOME`` too), and the project slug is the
  manifest ``project_root`` with each character outside ``[A-Za-z0-9]``
  replaced by ``-`` (chosen; the CLI's own rule) [R§4.6.3 step 2].
* ``credits_state.py send --kind ruling`` takes ``--human-quote``,
  ``--decision-id``, ``--gate-id``, ``--orchestrator-session`` and
  ``--user-message-uuid`` (the flags exist today; S6b enables the kind).
* The gate that a verified ruling closes names the message in
  ``resolved_by_msg`` (R§4.6.3 step 10) or in the ``msg_id`` column that the
  store already has (chosen: either is accepted).
* The hook's verified frame carries ``kind=ruling``, the marker
  ``ruling (verified: <session>/<uuid>)``, the quote and the sentence "If you
  already handled this msg_id, ignore it." (R§4.6.2, R§4.6.4 step 5).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from test_credits_inbox import (
    FRAME_RE,
    HOOK,
    MSG_TOOL,
    Fire,
    stamp,
)
from test_credits_state import (
    REAL_DB_STATE_AT_IMPORT,
    ROOT,
    SESSION_A,
    SESSION_B,
    T0,
    TOOL,
    Out,
    Seg,
    Store,
    at,
    child_env,
    finish,
    parse_out,
    real_db_state,
    start_segment,
    stop,
)

# The orchestrator session of the recorded M-6 fixture (R§10.2 M-6).
ORCH = "0596bd59-5711-4906-abbf-24bcfe7a7cc5"
ORCH_2 = "cccccccc-0000-4000-8000-000000000003"
ORCH_X = "dddddddd-0000-4000-8000-000000000004"
FIXTURE = (
    ROOT
    / ".agent"
    / "skills"
    / "claude-credits"
    / "probes"
    / "fixtures"
    / "m6-c47a9e.jsonl"
)
FIXTURE_RUN = "c47a9e"
FRAME_TAG = "[ORCHESTRATOR-MESSAGE "
HANDLED = "If you already handled this msg_id, ignore it."
UNVERIFIED_RE = re.compile(
    r"UNVERIFIED RULING \(([a-z_]+)\): do not apply; stay at the gate"
)
CALL_TIMEOUT = 30.0


# --- runners -----------------------------------------------------------------------


def secs(timestamp: str) -> float:
    """Seconds from T0 to a transcript timestamp."""
    moment = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return (moment - T0).total_seconds()


def slug(project_root: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", project_root)


def base_env(home: Path, st: Store) -> dict[str, str]:
    """No inherited ``CREDITS_*``; ``~`` is the temp home; the test effect log."""
    env = child_env(
        {
            "USERPROFILE": str(home),
            "HOME": str(home),
            "CREDITS_TEST_EFFECT_LOG": str(st.effect_log),
        }
    )
    env.pop("CLAUDE_CONFIG_DIR", None)
    return env


def run_proc(
    argv: list[str], env: dict[str, str], stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=CALL_TIMEOUT,
        cwd=ROOT,
        check=False,
    )


@dataclass
class Transcript:
    """An orchestrator transcript (JSON lines) built record by record."""

    path: Path
    session: str
    records: list[str] = field(default_factory=list)
    last_uuid: str | None = None

    def flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = "".join(line + "\n" for line in self.records)
        self.path.write_bytes(data.encode("utf-8"))

    def put(self, record: dict[str, Any], *, chained: bool) -> None:
        if chained:
            self.last_uuid = str(record["uuid"])
        self.records.append(json.dumps(record))
        self.flush()

    def raw(self, line: str) -> None:
        self.records.append(line)
        self.flush()

    def lines(self) -> list[str]:
        return list(self.records)

    def rewrite(self, lines: list[str]) -> None:
        self.records = list(lines)
        self.flush()

    def user(
        self,
        text: str,
        seconds: float,
        *,
        uid: str | None = None,
        prompt_id: str | None = None,
        drop: tuple[str, ...] = (),
        extra: dict[str, Any] | None = None,
        content: list[dict[str, Any]] | None = None,
    ) -> str:
        """A typed entry with every field of R§4.6.3 step 4 (the M-6 shape)."""
        uid = uid or str(uuid.uuid4())
        record: dict[str, Any] = {
            "parentUuid": self.last_uuid,
            "isSidechain": False,
            "promptId": prompt_id or str(uuid.uuid4()),
            "type": "user",
            "message": {
                "role": "user",
                "content": content
                if content is not None
                else [{"type": "text", "text": text}],
            },
            "uuid": uid,
            "timestamp": stamp(seconds),
            "permissionMode": "bypassPermissions",
            "origin": {"kind": "human"},
            "promptSource": "sdk",
            "turnOrigin": "human",
            "turnPosition": {"promptIndex": 1, "turnIndex": 1},
            "userType": "external",
            "entrypoint": "sdk-cli",
            "cwd": "X:/s6b-fixture",
            "sessionId": self.session,
            "version": "2.1.296",
            "gitBranch": "main",
        }
        for key in drop:
            record.pop(key, None)
        record.update(extra or {})
        self.put(record, chained=True)
        return uid

    def assistant(self, text: str, seconds: float) -> str:
        uid = str(uuid.uuid4())
        self.put(
            {
                "parentUuid": self.last_uuid,
                "isSidechain": False,
                "message": {
                    "model": "fixture-model",
                    "id": f"msg_{uid[:8]}",
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "text", "text": text}],
                },
                "type": "assistant",
                "uuid": uid,
                "timestamp": stamp(seconds),
                "sessionId": self.session,
                "version": "2.1.296",
            },
            chained=True,
        )
        return uid

    def queue_op(self, operation: str, seconds: float, **fields: Any) -> None:
        record: dict[str, Any] = {
            "type": "queue-operation",
            "operation": operation,
            "timestamp": stamp(seconds),
            "sessionId": self.session,
        }
        record.update(fields)
        self.put(record, chained=False)

    def enqueue(self, seconds: float, text: str | None = None) -> None:
        if text is None:
            self.queue_op("enqueue", seconds)
        else:
            self.queue_op("enqueue", seconds, content=text)

    def dequeue(self, seconds: float) -> None:
        self.queue_op("dequeue", seconds)

    def queued_command(self, text: str, seconds: float, delivery_id: str | None) -> str:
        uid = str(uuid.uuid4())
        attachment: dict[str, Any] = {
            "type": "queued_command",
            "prompt": [{"type": "text", "text": text}],
            "source_uuid": str(uuid.uuid4()),
            "commandMode": "prompt",
            "origin": {"kind": "human"},
            "timestamp": stamp(seconds),
            "humanTurn": True,
        }
        if delivery_id is not None:
            attachment["delivery_id"] = delivery_id
        self.put(
            {
                "parentUuid": self.last_uuid,
                "isSidechain": False,
                "attachment": attachment,
                "type": "attachment",
                "uuid": uid,
                "timestamp": stamp(seconds),
                "sessionId": self.session,
                "version": "2.1.296",
            },
            chained=True,
        )
        return uid

    def remove(
        self,
        text: str,
        seconds: float,
        delivery_id: str | None,
        command_uuid: str,
        reason: str = "absorbed_mid_turn",
    ) -> None:
        fields: dict[str, Any] = {
            "content": text,
            "reason": reason,
            "commandUuid": command_uuid,
        }
        if delivery_id is not None:
            fields["deliveryId"] = delivery_id
        self.queue_op("remove", seconds, **fields)


@dataclass
class Rr:
    """One job run with a live segment, its config, its home and its transcripts."""

    st: Store
    run_id: str
    seg: Seg
    home: Path
    project: str
    config: Path
    base: int

    def env(self) -> dict[str, str]:
        return base_env(self.home, self.st)

    def transcript(self, session: str = ORCH) -> Transcript:
        path = (
            self.home / ".claude" / "projects" / slug(self.project) / f"{session}.jsonl"
        )
        return Transcript(path, session)

    def store(self, verb: str, *args: str, seconds: int) -> Out:
        argv = [
            sys.executable,
            "-X",
            "utf8",
            str(TOOL),
            "--db",
            str(self.st.db),
            "--now-utc",
            at(seconds),
            verb,
            *args,
        ]
        proc = run_proc(argv, self.env())
        return parse_out(proc.returncode, proc.stdout, proc.stderr)

    def scan(self, seconds: int, session: str = ORCH) -> Out:
        return self.store(
            "scan_transcript",
            "--run-id",
            self.run_id,
            "--session",
            session,
            seconds=seconds,
        )

    def scanned(self, seconds: int, session: str = ORCH) -> Out:
        out = self.scan(seconds, session)
        assert out.code == 0, out.show()
        assert out.result in ("changed", "no_change"), out.show()
        return out

    def run_env(
        self,
        seconds: int,
        segment: str | None = None,
        extra: dict[str, str] | None = None,
    ) -> dict[str, str]:
        env = self.env()
        env.update(
            {
                "CREDITS_RUN_ID": self.run_id,
                "CREDITS_STATE_DB": str(self.st.db),
                "CREDITS_SEGMENT": segment or self.seg.segment_id,
                "CREDITS_CONFIG": str(self.config),
                "CREDITS_TEST_NOW_UTC": at(seconds),
                **(extra or {}),
            }
        )
        return env

    def msg(
        self,
        verb: str,
        *args: str,
        seconds: int,
        segment: str | None = None,
        extra: dict[str, str] | None = None,
    ) -> Out:
        argv = [
            sys.executable,
            "-X",
            "utf8",
            str(MSG_TOOL),
            "--now-utc",
            at(seconds),
            verb,
            *args,
        ]
        proc = run_proc(argv, self.run_env(seconds, segment, extra))
        return parse_out(proc.returncode, proc.stdout, proc.stderr)

    def decision(self, seconds: int, decision_id: str = "D-1") -> str:
        out = self.msg("decision", decision_id, "Pick A or B", seconds=seconds)
        assert out.code == 0 and out.payload is not None, out.show()
        gate_id = out.payload.get("gate_id")
        assert isinstance(gate_id, str) and gate_id, out.show()
        return gate_id

    def send_ruling(
        self,
        seconds: int,
        *,
        gate_id: str,
        quote: str,
        uid: str,
        decision_id: str = "D-1",
        session: str = ORCH,
    ) -> Out:
        return self.store(
            "send",
            "--run-id",
            self.run_id,
            "--kind",
            "ruling",
            "--body",
            "relayed ruling",
            "--human-quote",
            quote,
            "--decision-id",
            decision_id,
            "--gate-id",
            gate_id,
            "--orchestrator-session",
            session,
            "--user-message-uuid",
            uid,
            seconds=seconds,
        )

    def relay(self, seconds: int, **kw: Any) -> str:
        """Send a ``ruling`` (R§4.6.2); it must be accepted, verified or not."""
        out = self.send_ruling(seconds, **kw)
        assert out.code == 0 and out.payload is not None, out.show()
        msg_id = out.payload.get("msg_id")
        assert isinstance(msg_id, str) and msg_id, out.show()
        return msg_id

    def fire(
        self,
        seconds: int,
        *,
        segment: str | None = None,
        session: str | None = None,
        crash: str | None = None,
    ) -> Fire:
        payload = {
            "session_id": session or self.seg.session,
            "transcript_path": str(self.st.root / "segment-transcript.jsonl"),
            "cwd": str(ROOT),
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "echo fixture"},
            "tool_response": {
                "stdout": "fixture tool output",
                "stderr": "fixture tool warning",
                "interrupted": False,
                "isImage": False,
            },
        }
        extra = {"CREDITS_TEST_CRASH_AT": f"inbox:{crash}"} if crash else None
        argv = [sys.executable, "-X", "utf8", str(HOOK)]
        proc = run_proc(
            argv, self.run_env(seconds, segment, extra), json.dumps(payload)
        )
        return Fire(proc.returncode, proc.stdout, proc.stderr)

    def rows(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with contextlib.closing(sqlite3.connect(self.st.db)) as con:
            con.row_factory = sqlite3.Row
            return [dict(row) for row in con.execute(sql, params)]

    def gate(self, gate_id: str) -> dict[str, Any]:
        found = self.rows("SELECT * FROM gates WHERE gate_id = ?", (gate_id,))
        assert len(found) == 1, found
        return found[0]

    def consumed(self, msg_id: str | None = None) -> list[dict[str, Any]]:
        rows = self.rows("SELECT * FROM consumed_rulings")
        return [r for r in rows if msg_id is None or r.get("msg_id") == msg_id]

    def events(self, key: str) -> int:
        return len(
            self.rows("SELECT 1 FROM outbox_events WHERE semantic_key = ?", (key,))
        )


def make_run(
    tmp_path: Path,
    *,
    st: Store | None = None,
    home: Path | None = None,
    project: str | None = None,
    run_id: str = "s6b-run",
    base: int = 0,
    wait: int = 30,
    timeout: int = 43200,
    sessions: tuple[str, ...] = (ORCH, ORCH_2),
    ruling: bool = True,
    session: str = SESSION_A,
) -> Rr:
    """Register a job run with the S6b switches and start its first segment."""
    if st is None:
        st = Store(tmp_path / "store")
        st.root.mkdir(parents=True)
        st.init()
    home = home or tmp_path / "h"
    home.mkdir(parents=True, exist_ok=True)
    project = project or f"X:/s6b-fixture-{uuid.uuid4().hex[:8]}"
    manifest = {
        "schema": "credits-run.v1",
        "run_id": run_id,
        "kind": "exec",
        "project_root": project,
        "plan_folder": "docs/execution/plans/2026-10-15-fixture/",
        "brief": "C:/Temp/fixture/brief.md",
        "launch": {
            "working_directory": project,
            "claude_exe": "C:/fixture/claude.cmd",
            "python_exe": "C:/fixture/python.exe",
            "permission_mode": "bypassPermissions",
            "model": "fixture-model",
            "effort": "high",
            "segment_cap_usd": 75.0,
            "timeout_sec": timeout,
        },
        "budget": {"run_cap_usd": 200.0},
        "messaging": {
            "orchestrator_sessions": list(sessions),
            "ruling_enabled": ruling,
            "gate_wait_max_min": wait,
        },
        "depends_on": [],
        "lane": f"tree:{project}/{run_id}",
    }
    manifest_path = st.root / f"manifest-{run_id}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    config = st.root / f"config-{run_id}.json"
    config.write_text(
        json.dumps(
            {
                "ruling_enabled": ruling,
                "gate_wait_max_min": wait,
                "cache_ttl": "5m",
                "credits_start_policy": "human-only",
            }
        ),
        encoding="utf-8",
    )
    st.ok(
        "register",
        "--run-id",
        run_id,
        "--manifest",
        str(manifest_path),
        "--cli-version",
        "9.9.9",
        "--kit-revision",
        "kitrev-fixture",
        now=base,
    )
    st.ok(
        "registered", "--run-id", run_id, "--task-hash", f"taskhash-{run_id}", now=base
    )
    seg = start_segment(st, run_id, 1, now=base + 1, session=session)
    return Rr(st, run_id, seg, home, project, config, base)


def frames(fire: Fire) -> dict[str, tuple[str, str]]:
    """The frames of one fire: msg_id → (kind, the frame's text)."""
    text = fire.reason if fire.blocked else fire.context
    found: dict[str, tuple[str, str]] = {}
    for chunk in text.split(FRAME_TAG)[1:]:
        whole = FRAME_TAG + chunk
        match = FRAME_RE.match(whole)
        if match:
            found[match.group(1)] = (match.group(3), whole)
    return found


def assert_verified(
    rr: Rr,
    fire: Fire,
    msg_id: str,
    *,
    gate_id: str,
    uid: str,
    quote: str,
    session: str = ORCH,
) -> None:
    """R§4.6.3 Part B committed, then the verified frame (R§4.6.2, R§4.6.4 step 5)."""
    found = frames(fire)
    assert msg_id in found, fire.show()
    kind, text = found[msg_id]
    assert kind == "ruling", text
    assert f"ruling (verified: {session}/{uid})" in text, text
    assert quote in text, text
    assert HANDLED in text, text
    assert "UNVERIFIED RULING" not in text, text
    gate = rr.gate(gate_id)
    assert gate["state"] in ("closed", "resolved"), gate
    assert msg_id in (gate.get("resolved_by_msg"), gate.get("msg_id")), gate
    assert len(rr.consumed(msg_id)) == 1, rr.consumed()


def assert_unverified(
    rr: Rr,
    fire: Fire,
    msg_id: str,
    *,
    gate_id: str | None,
    reason: str | None = None,
) -> str:
    """R§4.6.3: any failed step frames the message as ``info``; nothing is consumed."""
    found = frames(fire)
    assert msg_id in found, fire.show()
    kind, text = found[msg_id]
    assert kind == "info", text
    match = UNVERIFIED_RE.search(text)
    assert match is not None, text
    if reason is not None:
        assert match.group(1) == reason, text
    assert "(verified:" not in text, text
    if gate_id is not None:
        assert rr.gate(gate_id)["state"] == "open"
    assert rr.consumed(msg_id) == []
    return match.group(1)


def open_flow(tmp_path: Path, **kw: Any) -> tuple[Rr, Transcript, str]:
    """A run, its scanned prefix (the attach watermark) and the open gate D-1."""
    rr = make_run(tmp_path, **kw)
    tr = rr.transcript(ORCH)
    tr.user("Start the plan run for the fixture.", rr.base + 10)
    tr.assistant("Started.", rr.base + 11)
    rr.scanned(rr.base + 20)
    gate_id = rr.decision(rr.base + 50)
    return rr, tr, gate_id


def fixture_lines() -> list[str]:
    return FIXTURE.read_text(encoding="utf-8").splitlines()


def fixture_ts(line_no: int) -> float:
    return secs(json.loads(fixture_lines()[line_no - 1])["timestamp"])


def fixture_uuid(line_no: int) -> str:
    return str(json.loads(fixture_lines()[line_no - 1])["uuid"])


def fixture_flow(tmp_path: Path) -> tuple[Rr, Transcript]:
    """The M-6 fixture: lines 1-22 scanned at attach, then the rest appended."""
    base = int(fixture_ts(3)) - 600
    rr = make_run(tmp_path, run_id=FIXTURE_RUN, base=base)
    tr = rr.transcript(ORCH)
    lines = fixture_lines()
    tr.rewrite(lines[:22])
    rr.scanned(base + 100)
    tr.rewrite(lines)
    return rr, tr


# --- AC-I.1: the verified path -------------------------------------------------------


@pytest.mark.parametrize("shape", ["plain", "enqueue_dequeue"])
def test_ac_i1_idle_typed_entry_is_verified_and_consumed_once(
    tmp_path: Path, shape: str
) -> None:
    """AC-I.1: an idle typed entry passes Part A and Part B; the tuple is consumed once."""
    rr, tr, gate_id = open_flow(tmp_path)
    if shape == "enqueue_dequeue":
        tr.enqueue(59)
        tr.dequeue(59)
    prompt_id = str(uuid.uuid4())
    uid = tr.user("D-1: A", 60, prompt_id=prompt_id)
    msg_id = rr.relay(70, gate_id=gate_id, quote="D-1: A", uid=uid)
    fire = rr.fire(80)
    assert fire.code == 0, fire.show()
    assert_verified(rr, fire, msg_id, gate_id=gate_id, uid=uid, quote="D-1: A")
    row = rr.consumed(msg_id)[0]
    assert row["orchestrator_session"] == ORCH
    assert row["user_message_uuid"] == uid
    assert row["prompt_id"] == prompt_id
    assert row["run_id"] == rr.run_id
    assert row["gate_id"] == gate_id
    assert f"python tools/credits_msg.py applied {msg_id}" in frames(fire)[msg_id][1]
    # A later fire consumes nothing more.
    rr.fire(90)
    assert len(rr.consumed()) == 1


def test_ac_i1_quote_matches_after_normalization(tmp_path: Path) -> None:
    """AC-I.1 (R§4.6.3 step 6): NFC, CRLF → LF, trim and collapsed whitespace."""
    rr, tr, gate_id = open_flow(tmp_path)
    uid = tr.user("D-1: A, keep the\r\ncache", 60)
    quote = "  D-1:  A, keep the\ncache "
    msg_id = rr.relay(70, gate_id=gate_id, quote=quote, uid=uid)
    fire = rr.fire(80)
    assert_verified(rr, fire, msg_id, gate_id=gate_id, uid=uid, quote="D-1:")


def test_ac_i1_switch_off_frames_the_ruling_unverified(tmp_path: Path) -> None:
    """AC-I.1 (R§4.6.3 step 1): ruling_enabled false → UNVERIFIED RULING, gate open."""
    rr = make_run(tmp_path, ruling=False, wait=0)
    tr = rr.transcript(ORCH)
    tr.user("Start the plan run for the fixture.", 10)
    tr.assistant("Started.", 11)
    gate_id = rr.decision(50)
    uid = tr.user("D-1: A", 60)
    msg_id = rr.relay(70, gate_id=gate_id, quote="D-1: A", uid=uid)
    assert_unverified(rr, rr.fire(80), msg_id, gate_id=gate_id)


def test_ac_i1_session_not_in_the_list_fails(tmp_path: Path) -> None:
    """AC-I.1 (R§4.6.3 step 2): a session outside messaging.orchestrator_sessions."""
    rr, _, gate_id = open_flow(tmp_path)
    other = rr.transcript(ORCH_X)
    other.user("Start.", 10)
    uid = other.user("D-1: A", 60)
    msg_id = rr.relay(70, gate_id=gate_id, quote="D-1: A", uid=uid, session=ORCH_X)
    assert_unverified(rr, rr.fire(80), msg_id, gate_id=gate_id)


@pytest.mark.parametrize("case", ["uuid_of_another_session", "unknown_uuid"])
def test_ac_i1_wrong_or_foreign_uuid_fails(tmp_path: Path, case: str) -> None:
    """AC-I.1 (R§4.6.3 step 4): exactly one line of this session has the uuid."""
    rr, tr, gate_id = open_flow(tmp_path)
    tr.user("D-1: A", 60)
    if case == "uuid_of_another_session":
        second = rr.transcript(ORCH_2)
        second.user("Start.", 10)
        uid = second.user("D-1: A", 61)
    else:
        uid = str(uuid.uuid4())
    msg_id = rr.relay(70, gate_id=gate_id, quote="D-1: A", uid=uid)
    assert_unverified(rr, rr.fire(80), msg_id, gate_id=gate_id)


ENTRY_SHAPES: dict[str, dict[str, Any]] = {
    "tool_result": {
        "content": [
            {"type": "tool_result", "tool_use_id": "toolu_fixture", "content": "D-1: A"}
        ]
    },
    "image": {
        "content": [
            {"type": "text", "text": "D-1: A"},
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": "iVBO"},
            },
        ]
    },
    "meta": {"extra": {"isMeta": True}},
    "compact_summary": {"extra": {"isCompactSummary": True}},
    "tool_use_result": {"extra": {"toolUseResult": {"stdout": "D-1: A"}}},
    "origin_not_human": {"extra": {"origin": {"kind": "task-notification"}}},
    "user_type_not_external": {"extra": {"userType": "internal"}},
    "session_id_differs": {"extra": {"sessionId": ORCH_2}},
}


@pytest.mark.parametrize("shape", sorted(ENTRY_SHAPES))
def test_ac_i1_entry_that_is_not_a_typed_human_turn_fails(
    tmp_path: Path, shape: str
) -> None:
    """AC-I.1 (R§4.6.3 step 4): tool result, image, meta, compact summary and the rest."""
    rr, tr, gate_id = open_flow(tmp_path)
    uid = tr.user("D-1: A", 60, **ENTRY_SHAPES[shape])
    msg_id = rr.relay(70, gate_id=gate_id, quote="D-1: A", uid=uid)
    assert_unverified(rr, rr.fire(80), msg_id, gate_id=gate_id)


def test_ac_i1_entry_before_the_gate_opened_fails(tmp_path: Path) -> None:
    """AC-I.1 (R§4.6.3 step 4): the timestamp must be later than the gate's opened_utc."""
    rr, tr, gate_id = open_flow(tmp_path)
    uid = tr.user("D-1: A", 45)
    msg_id = rr.relay(70, gate_id=gate_id, quote="D-1: A", uid=uid)
    assert_unverified(rr, rr.fire(80), msg_id, gate_id=gate_id)


def test_ac_i1_entry_before_the_attach_watermark_fails(tmp_path: Path) -> None:
    """AC-I.1 (R§4.6.3 step 3): the entry lies before the offset of the first scan."""
    rr = make_run(tmp_path)
    tr = rr.transcript(ORCH)
    tr.user("Start the plan run for the fixture.", 10)
    tr.assistant("Started.", 11)
    uid = tr.user("D-1: A", 60)
    rr.scanned(20)
    gate_id = rr.decision(50)
    msg_id = rr.relay(70, gate_id=gate_id, quote="D-1: A", uid=uid)
    assert_unverified(rr, rr.fire(80), msg_id, gate_id=gate_id)


@pytest.mark.parametrize(
    ("text", "quote"),
    [
        ("D-1: A, keep the cache", "D-1: B, keep the cache"),  # edited
        ("D-1: A, keep the cache", "D-1: A"),  # partial
        ("D-1: A, keep the cache", "D-1: A, keep cache"),  # a word removed
        (
            "Option A for the first decision",
            "Option A for the first decision",
        ),  # no D-1
        ("D-10: A", "D-10: A"),  # D-1 is not a whole token
    ],
)
def test_ac_i1_quote_must_equal_the_entry_and_hold_the_decision_token(
    tmp_path: Path, text: str, quote: str
) -> None:
    """AC-I.1 (R§4.6.3 step 6): no substring pass; the decision id is a whole token."""
    rr, tr, gate_id = open_flow(tmp_path)
    uid = tr.user(text, 60)
    msg_id = rr.relay(70, gate_id=gate_id, quote=quote, uid=uid)
    assert_unverified(rr, rr.fire(80), msg_id, gate_id=gate_id)


def test_ac_i1_run_token_of_another_run_fails_wrong_run(tmp_path: Path) -> None:
    """AC-I.1 (R§4.6.3 step 6): a run id token must name this run."""
    rr, tr, gate_id = open_flow(tmp_path)
    make_run(
        tmp_path,
        st=rr.st,
        home=rr.home,
        project=rr.project,
        run_id="s6b-other",
        base=52,
        session=SESSION_B,
    )
    uid = tr.user("s6b-other D-1: A", 60)
    msg_id = rr.relay(70, gate_id=gate_id, quote="s6b-other D-1: A", uid=uid)
    assert_unverified(rr, rr.fire(80), msg_id, gate_id=gate_id, reason="wrong_run")


# --- MX-41: the typed-turn fields and the single-use promptId -----------------------------


@pytest.mark.parametrize("missing", ["turnOrigin", "promptSource", "promptId"])
def test_mx_41_entry_without_a_typed_turn_field_fails_not_typed_turn(
    tmp_path: Path, missing: str
) -> None:
    """AC-I.1 / MX-41: no turnOrigin, promptSource or promptId → not_typed_turn."""
    rr, tr, gate_id = open_flow(tmp_path)
    uid = tr.user("D-1: A", 60, drop=(missing,))
    msg_id = rr.relay(70, gate_id=gate_id, quote="D-1: A", uid=uid)
    assert_unverified(rr, rr.fire(80), msg_id, gate_id=gate_id, reason="not_typed_turn")


def test_mx_41_reused_prompt_id_fails_replay(tmp_path: Path) -> None:
    """AC-I.1 / MX-41: a promptId that an earlier line holds → replay."""
    rr = make_run(tmp_path)
    tr = rr.transcript(ORCH)
    reused = str(uuid.uuid4())
    tr.user("Start the plan run for the fixture.", 10, prompt_id=reused)
    tr.assistant("Started.", 11)
    rr.scanned(20)
    gate_id = rr.decision(50)
    uid = tr.user("D-1: A", 60, prompt_id=reused)
    msg_id = rr.relay(70, gate_id=gate_id, quote="D-1: A", uid=uid)
    assert_unverified(rr, rr.fire(80), msg_id, gate_id=gate_id, reason="replay")


# --- queue chains: provenance_unknown, MX-42, MX-29 ----------------------------------------


@pytest.mark.parametrize(
    "record", ["attachment_without_delivery_id", "remove_without_delivery_id"]
)
def test_ac_i1_unjoinable_queue_record_with_the_entry_text_fails_provenance_unknown(
    tmp_path: Path, record: str
) -> None:
    """AC-I.1 (R§4.6.3 step 5): a queue record the scan could not join."""
    rr, tr, gate_id = open_flow(tmp_path)
    if record == "attachment_without_delivery_id":
        tr.queued_command("D-1: A", 55, delivery_id=None)
    else:
        tr.remove("D-1: A", 55, delivery_id=None, command_uuid=str(uuid.uuid4()))
    tr.assistant("Working.", 56)
    uid = tr.user("D-1: A", 60)
    msg_id = rr.relay(70, gate_id=gate_id, quote="D-1: A", uid=uid)
    assert_unverified(
        rr, rr.fire(80), msg_id, gate_id=gate_id, reason="provenance_unknown"
    )


@pytest.mark.parametrize("enqueue", ["with_text", "contentless_then_dequeue"])
def test_mx_42_assistant_text_holds_the_queued_ruling_then_relabeled_entry_fails(
    tmp_path: Path, enqueue: str
) -> None:
    """AC-I.1 / MX-42: the assistant text takes no part; the entry is queued_origin."""
    rr, tr, gate_id = open_flow(tmp_path)
    if enqueue == "with_text":
        tr.enqueue(55, "D-1: A")
        tr.assistant("I see D-1: A in the queue.", 56)
    else:
        tr.enqueue(55)
        tr.assistant("I see D-1: A in the queue.", 56)
        tr.dequeue(59)
    uid = tr.user("D-1: A", 60)
    msg_id = rr.relay(70, gate_id=gate_id, quote="D-1: A", uid=uid)
    assert_unverified(rr, rr.fire(80), msg_id, gate_id=gate_id, reason="queued_origin")


def test_mx_42_fixture_text_streamed_relabel_fails_queued_origin(
    tmp_path: Path,
) -> None:
    """AC-I.1 / MX-42 (M-6 fixture): line 52, typed while text streamed → queued_origin."""
    rr, _ = fixture_flow(tmp_path)
    gate_id = rr.decision(int(fixture_ts(46)) + 1, "D-2")
    uid = fixture_uuid(52)
    quote = "M6 c47a9e D-2: B"
    seconds = int(fixture_ts(71)) + 10
    msg_id = rr.relay(seconds, gate_id=gate_id, quote=quote, uid=uid, decision_id="D-2")
    fire = rr.fire(seconds + 10)
    assert_unverified(rr, fire, msg_id, gate_id=gate_id, reason="queued_origin")


def test_mx_29_queued_ruling_then_exact_resend_fails_then_reworded_passes(
    tmp_path: Path,
) -> None:
    """AC-I.1 / MX-29: the chain's text never passes; other words pass (R6-a)."""
    rr, tr, gate_id = open_flow(tmp_path)
    delivery, command = str(uuid.uuid4()), str(uuid.uuid4())
    tr.assistant("Running a tool.", 51)
    tr.enqueue(52, "D-1: A")
    tr.queued_command("D-1: A", 52, delivery)
    tr.remove("D-1: A", 53, delivery, command)
    tr.assistant("Done with the tool.", 54)
    tr.enqueue(60)
    tr.dequeue(60)
    exact = tr.user("D-1: A", 61)
    first = rr.relay(65, gate_id=gate_id, quote="D-1: A", uid=exact)
    assert_unverified(rr, rr.fire(66), first, gate_id=gate_id, reason="queued_origin")
    tr.assistant("Please send it again with other words.", 67)
    tr.enqueue(70)
    tr.dequeue(70)
    reworded = tr.user("D-1: A (resend)", 71)
    second = rr.relay(75, gate_id=gate_id, quote="D-1: A (resend)", uid=reworded)
    fire = rr.fire(80)
    assert_verified(
        rr, fire, second, gate_id=gate_id, uid=reworded, quote="D-1: A (resend)"
    )


def test_mx_29_fixture_exact_idle_resend_fails_and_reworded_resend_passes(
    tmp_path: Path,
) -> None:
    """AC-I.1 / MX-29 (M-6 fixture): line 63 → queued_origin; line 69 passes; line 32 fails."""
    rr, _ = fixture_flow(tmp_path)
    gate_id = rr.decision(int(fixture_ts(58)) + 1, "D-1")
    later = int(fixture_ts(71)) + 10
    attachment = rr.relay(
        later, gate_id=gate_id, quote="M6 c47a9e D-1: A", uid=fixture_uuid(32)
    )
    assert_unverified(rr, rr.fire(later + 1), attachment, gate_id=gate_id)
    exact = rr.relay(
        later + 2, gate_id=gate_id, quote="M6 c47a9e D-1: A", uid=fixture_uuid(63)
    )
    assert_unverified(
        rr, rr.fire(later + 3), exact, gate_id=gate_id, reason="queued_origin"
    )
    quote = "M6 c47a9e D-1: A (resend)"
    reworded = rr.relay(later + 4, gate_id=gate_id, quote=quote, uid=fixture_uuid(69))
    fire = rr.fire(later + 5)
    assert_verified(
        rr, fire, reworded, gate_id=gate_id, uid=fixture_uuid(69), quote=quote
    )


# --- MX-10, MX-18: replay, redelivery and ambiguity -----------------------------------------


def two_runs(tmp_path: Path) -> tuple[Rr, Rr, Transcript]:
    """Two runs in one store; both list ORCH as an orchestrator session."""
    one = make_run(tmp_path)
    two = make_run(
        tmp_path,
        st=one.st,
        home=one.home,
        project=one.project,
        run_id="s6b-two",
        base=2,
        session=SESSION_B,
    )
    tr = one.transcript(ORCH)
    tr.user("Start the plan run for the fixture.", 10)
    tr.assistant("Started.", 11)
    one.scanned(20)
    return one, two, tr


def test_mx_10_same_uuid_for_a_second_decision_fails_replay(tmp_path: Path) -> None:
    """AC-I.1 / MX-10: one entry answers two D-n; its second use → replay."""
    one, two, tr = two_runs(tmp_path)
    gate_1 = one.decision(50, "D-1")
    gate_2 = two.decision(51, "D-2")
    quote = "D-1: A, D-2: B"
    uid = tr.user(quote, 60)
    first = one.relay(70, gate_id=gate_1, quote=quote, uid=uid)
    assert_verified(one, one.fire(80), first, gate_id=gate_1, uid=uid, quote=quote)
    second = two.relay(90, gate_id=gate_2, quote=quote, uid=uid, decision_id="D-2")
    fire = two.fire(100, session=SESSION_B)
    assert_unverified(two, fire, second, gate_id=gate_2, reason="replay")


@pytest.mark.parametrize("point", ["after_emit_count", "after_emit"])
def test_mx_18_crash_between_commit_and_emit_redelivers_the_verified_frame(
    tmp_path: Path, point: str
) -> None:
    """AC-I.1 / MX-18 (R§4.6.3 Redelivery): the whole tuple matches → verified again."""
    rr, tr, gate_id = open_flow(tmp_path)
    uid = tr.user("D-1: A", 60)
    msg_id = rr.relay(70, gate_id=gate_id, quote="D-1: A", uid=uid)
    crashed = rr.fire(80, crash=point)
    assert crashed.code == 9, crashed.show()
    assert frames(rr.fire(90)) == {}
    again = rr.fire(143)
    assert_verified(rr, again, msg_id, gate_id=gate_id, uid=uid, quote="D-1: A")
    assert len(rr.consumed()) == 1


def tamper(rr: Rr, msg_id: str, column: str) -> None:
    """Change one field of the consumed tuple (R§4.6.3 step 9 lists the fields).

    ``payload_hash`` is a column when the store has one; otherwise it is a key of
    ``ruling_json`` (chosen: the schema today keeps the payload there).
    """
    columns = {r["name"] for r in rr.rows("PRAGMA table_info(consumed_rulings)")}
    if column in columns:
        rr.st.write(
            f"UPDATE consumed_rulings SET {column} = ? WHERE msg_id = ?",
            ("tampered-0000", msg_id),
        )
        return
    row = rr.consumed(msg_id)[0]
    ruling = json.loads(row.get("ruling_json") or "{}")
    assert column in ruling, ruling
    ruling[column] = "tampered-0000"
    rr.st.write(
        "UPDATE consumed_rulings SET ruling_json = ? WHERE msg_id = ?",
        (json.dumps(ruling), msg_id),
    )


@pytest.mark.parametrize("column", ["run_id", "gate_id", "payload_hash"])
def test_mx_18_same_msg_id_with_a_changed_field_fails_replay(
    tmp_path: Path, column: str
) -> None:
    """AC-I.1 / MX-18: a consumed tuple that differs in run, gate or payload → replay."""
    rr, tr, gate_id = open_flow(tmp_path)
    uid = tr.user("D-1: A", 60)
    msg_id = rr.relay(70, gate_id=gate_id, quote="D-1: A", uid=uid)
    crashed = rr.fire(80, crash="after_emit")
    assert crashed.code == 9, crashed.show()
    assert len(rr.consumed(msg_id)) == 1
    tamper(rr, msg_id, column)
    assert frames(rr.fire(90)) == {}
    fire = rr.fire(143)
    found = frames(fire)
    assert msg_id in found, fire.show()
    kind, text = found[msg_id]
    assert kind == "info", text
    match = UNVERIFIED_RE.search(text)
    assert match is not None and match.group(1) == "replay", text


def test_mx_18_same_decision_open_in_two_runs_needs_a_run_token(tmp_path: Path) -> None:
    """AC-I.1 / MX-18 (R§4.6.3 step 8): two open D-1 → ambiguous; with the run id it passes."""
    one, two, tr = two_runs(tmp_path)
    gate_1 = one.decision(50, "D-1")
    two.decision(51, "D-1")
    bare = tr.user("D-1: A", 60)
    first = one.relay(70, gate_id=gate_1, quote="D-1: A", uid=bare)
    assert_unverified(one, one.fire(80), first, gate_id=gate_1, reason="ambiguous")
    quote = f"{one.run_id} D-1: A"
    named = tr.user(quote, 90)
    second = one.relay(95, gate_id=gate_1, quote=quote, uid=named)
    assert_verified(one, one.fire(100), second, gate_id=gate_1, uid=named, quote=quote)


# --- MX-9: a ruling after the gate expired ---------------------------------------------------


def test_mx_9_ruling_after_the_gate_expired_fails_gate_closed(tmp_path: Path) -> None:
    """AC-I.1 / MX-9 (R§4.6.3 step 7): the expired gate is not open → gate_closed."""
    rr, tr, gate_id = open_flow(tmp_path)
    uid = tr.user("D-1: A", 60)
    deadline = rr.gate(gate_id)["deadline_utc"]
    assert deadline == at(50 + 30 * 60)
    expired = rr.msg(
        "wait", "--max-wait-ms", "200", "--poll-ms", "20", seconds=50 + 1800
    )
    assert expired.code == 0, expired.show()
    assert rr.gate(gate_id)["state"] == "expired"
    msg_id = rr.relay(1860, gate_id=gate_id, quote="D-1: A", uid=uid)
    fire = rr.fire(1870)
    found = frames(fire)
    assert msg_id in found, fire.show()
    match = UNVERIFIED_RE.search(found[msg_id][1])
    assert match is not None and match.group(1) == "gate_closed"
    assert rr.consumed() == []


# --- MX-23, MX-28: the history check -------------------------------------------------------


@pytest.mark.parametrize("bad", ["unknown_record_type", "unparseable_line"])
def test_mx_23_unknown_record_or_bad_line_fails_transcript_unknown(
    tmp_path: Path, bad: str
) -> None:
    """AC-I.1 / MX-23 (R§4.6.3 step 3): a record type outside the known list."""
    rr, tr, gate_id = open_flow(tmp_path)
    if bad == "unknown_record_type":
        tr.raw(
            json.dumps(
                {"type": "mystery-record", "sessionId": ORCH, "timestamp": stamp(55)}
            )
        )
    else:
        tr.raw('{"type": "user", "message": ')
    uid = tr.user("D-1: A", 60)
    msg_id = rr.relay(70, gate_id=gate_id, quote="D-1: A", uid=uid)
    assert_unverified(
        rr, rr.fire(80), msg_id, gate_id=gate_id, reason="transcript_unknown"
    )


def prefix_flow(tmp_path: Path) -> tuple[Rr, Transcript, str]:
    """A scanned prefix with a queue record, a chained line and a second turn."""
    rr = make_run(tmp_path)
    tr = rr.transcript(ORCH)
    tr.enqueue(9)
    tr.dequeue(9)
    tr.user("Start the plan run for the fixture.", 10)
    tr.assistant("Started.", 11)
    tr.enqueue(12)
    tr.dequeue(12)
    tr.user("Continue with the next row.", 13)
    tr.assistant("Continuing.", 14)
    rr.scanned(20)
    gate_id = rr.decision(50)
    return rr, tr, gate_id


@pytest.mark.parametrize(
    "cut", ["prefix_lines", "chained_line", "queue_operation_line", "shorter_file"]
)
def test_mx_28_lines_removed_from_a_scanned_prefix_fail_transcript_discontinuity(
    tmp_path: Path, cut: str
) -> None:
    """AC-I.2 / MX-28: a changed prefix → transcript_discontinuity, history_state broken."""
    rr, tr, gate_id = prefix_flow(tmp_path)
    lines = tr.lines()
    if cut == "prefix_lines":
        kept = lines[4:]
    elif cut == "chained_line":
        kept = lines[:3] + lines[4:]
    elif cut == "queue_operation_line":
        kept = lines[:4] + lines[5:]
    else:
        kept = lines[:-1]
    tr.rewrite(kept)
    if cut == "shorter_file":
        tr.last_uuid = json.loads(kept[-1])["uuid"]
    uid = tr.user("D-1: A", 60)
    msg_id = rr.relay(70, gate_id=gate_id, quote="D-1: A", uid=uid)
    fire = rr.fire(80)
    assert_unverified(
        rr, fire, msg_id, gate_id=gate_id, reason="transcript_discontinuity"
    )
    state = rr.rows(
        "SELECT history_state FROM orchestrator_sessions WHERE run_id = ? AND session = ?",
        (rr.run_id, ORCH),
    )
    assert state == [{"history_state": "broken"}]
    # A later ruling from the session fails at step 3 until a new attach.
    later = tr.user("D-1: A (again)", 90)
    again = rr.relay(95, gate_id=gate_id, quote="D-1: A (again)", uid=later)
    reason = assert_unverified(rr, rr.fire(100), again, gate_id=gate_id)
    assert reason in ("transcript_discontinuity", "transcript_unknown")


@pytest.mark.parametrize("broken", ["dangling_parent", "removed_prefix"])
def test_mx_28_first_scan_needs_a_whole_parent_chain(
    tmp_path: Path, broken: str
) -> None:
    """AC-I.2 / MX-28: a link that does not resolve at the first scan → the scan fails."""
    rr = make_run(tmp_path)
    tr = rr.transcript(ORCH)
    if broken == "dangling_parent":
        tr.user("Start the plan run for the fixture.", 10)
        tr.last_uuid = str(uuid.uuid4())
        tr.assistant("Started.", 11)
    else:
        tr.last_uuid = str(uuid.uuid4())
        tr.assistant("Started.", 11)
        tr.user("Continue.", 12)
    out = rr.scan(20)
    assert out.code == 3, out.show()
    assert out.error in ("transcript_discontinuity", "transcript_unknown"), out.show()
    assert rr.rows("SELECT * FROM transcript_marks WHERE session = ?", (ORCH,)) == []


# --- AC-I.2: the marks and the queue chains -------------------------------------------------


def test_ac_i2_scan_marks_the_fixture_and_its_queue_chain(tmp_path: Path) -> None:
    """AC-I.2: the mark holds the byte length, the SHA-256 and the line count (73)."""
    base = int(fixture_ts(3)) - 600
    rr = make_run(tmp_path, run_id=FIXTURE_RUN, base=base)
    tr = rr.transcript(ORCH)
    tr.path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURE, tr.path)
    data = tr.path.read_bytes()
    out = rr.scan(base + 1000)
    assert out.code == 0 and out.result == "changed", out.show()
    marks = rr.rows("SELECT * FROM transcript_marks WHERE session = ?", (ORCH,))
    assert len(marks) == 1, marks
    assert marks[0]["byte_length"] == len(data)
    assert marks[0]["prefix_sha256"] == hashlib.sha256(data).hexdigest()
    assert marks[0]["line_count"] == 73
    chains = rr.rows("SELECT * FROM queue_chains WHERE session = ?", (ORCH,))
    tool = [
        c for c in chains if c["delivery_id"] == "4975038f-70b7-4a2b-b7d9-acd2a9f577eb"
    ]
    assert len(tool) == 1, chains
    assert tool[0]["state"] == "closed"
    assert tool[0]["remove_reason"] == "absorbed_mid_turn"
    assert tool[0]["command_uuid"] == "50fe6209-e67a-47b2-be92-c4e09d1481ef"
    # A second scan of the same bytes moves nothing.
    again = rr.scan(base + 1001)
    assert again.code == 0 and again.result == "no_change", again.show()


def test_ac_i2_partial_last_line_is_not_read_yet(tmp_path: Path) -> None:
    """AC-I.2 (history check step 2): a last line with no newline waits for the next scan."""
    rr = make_run(tmp_path)
    tr = rr.transcript(ORCH)
    tr.user("Start the plan run for the fixture.", 10)
    tr.assistant("Started.", 11)
    whole = tr.path.read_bytes()
    with tr.path.open("ab") as fh:
        fh.write(b'{"type": "assistant", "partial')
    rr.scanned(20)
    marks = rr.rows("SELECT * FROM transcript_marks WHERE session = ?", (ORCH,))
    assert len(marks) == 1, marks
    assert marks[0]["byte_length"] == len(whole)
    assert marks[0]["prefix_sha256"] == hashlib.sha256(whole).hexdigest()
    assert marks[0]["line_count"] == 2


def test_ac_i2_two_scans_at_the_same_instant_move_the_mark_once(tmp_path: Path) -> None:
    """AC-I.2 (history check step 3): a compare-and-set on the old mark; one scan moves it."""
    rr = make_run(tmp_path)
    tr = rr.transcript(ORCH)
    tr.user("Start the plan run for the fixture.", 10)
    tr.assistant("Started.", 11)
    argv = [
        sys.executable,
        "-X",
        "utf8",
        str(TOOL),
        "--db",
        str(rr.st.db),
        "--now-utc",
        at(20),
        "scan_transcript",
        "--run-id",
        rr.run_id,
        "--session",
        ORCH,
    ]
    procs = [
        subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=rr.env(),
            cwd=ROOT,
        )
        for _ in range(2)
    ]
    outs: list[Out] = []
    for proc in procs:
        stdout, stderr = proc.communicate(timeout=CALL_TIMEOUT)
        outs.append(parse_out(proc.returncode, stdout, stderr))
    results = [o.result for o in outs]
    assert results.count("changed") == 1, [o.show() for o in outs]
    assert all(o.code in (0, 75) for o in outs), [o.show() for o in outs]
    assert (
        len(rr.rows("SELECT * FROM transcript_marks WHERE session = ?", (ORCH,))) == 1
    )


def test_ac_i2_enqueue_removed_before_the_next_scan_passes_threat_model_limit(
    tmp_path: Path,
) -> None:
    """AC-I.2 (R§4.6.3 threat model): an enqueue removed before any scan read it passes."""
    rr, tr, gate_id = open_flow(tmp_path)
    tr.enqueue(55, "D-1: A")
    uid = tr.user("D-1: A", 60)
    tr.rewrite([line for line in tr.lines() if '"enqueue"' not in line])
    msg_id = rr.relay(70, gate_id=gate_id, quote="D-1: A", uid=uid)
    assert_verified(rr, rr.fire(80), msg_id, gate_id=gate_id, uid=uid, quote="D-1: A")


# --- AC-I.4: M-5b -----------------------------------------------------------------------


def verified_then_resumed(
    tmp_path: Path, *, ack_crash: bool
) -> tuple[Rr, str, str, Seg]:
    """A verified ruling, its ack, the segment's end and a resumed segment 2."""
    rr, tr, gate_id = open_flow(tmp_path)
    uid = tr.user("D-1: A", 60)
    msg_id = rr.relay(70, gate_id=gate_id, quote="D-1: A", uid=uid)
    assert_verified(rr, rr.fire(80), msg_id, gate_id=gate_id, uid=uid, quote="D-1: A")
    crash = {"CREDITS_TEST_CRASH_AT": "ack:after_commit"} if ack_crash else None
    acked = rr.msg("ack", msg_id, "applying D-1: A", seconds=90, extra=crash)
    assert acked.code == (9 if ack_crash else 0), acked.show()
    finish(rr.st, rr.seg, now=100, total=5.0)
    stop(rr.st, rr.run_id, now=101)
    seg2 = start_segment(rr.st, rr.run_id, 2, now=110, session=SESSION_A, resume=True)
    fire = rr.fire(120, segment=seg2.segment_id)
    found = frames(fire)
    assert msg_id in found, fire.show()
    kind, text = found[msg_id]
    assert kind == "ruling", text
    assert f"ruling (verified: {ORCH}/{uid})" in text, text
    assert HANDLED in text, text
    assert len(rr.consumed()) == 1
    return rr, msg_id, gate_id, seg2


def test_ac_i4_m5b_crash_after_ack_before_effect_is_redelivered_and_applied_once(
    tmp_path: Path,
) -> None:
    """AC-I.4 (R§10.2 M-5b): acked, no effect → pending in the next generation; applied once."""
    rr, msg_id, gate_id, seg2 = verified_then_resumed(tmp_path, ack_crash=True)
    applied = rr.msg("applied", msg_id, seconds=130, segment=seg2.segment_id)
    assert applied.code == 0 and applied.result == "changed", applied.show()
    again = rr.msg("applied", msg_id, seconds=131, segment=seg2.segment_id)
    assert again.code == 0 and again.result == "no_change", again.show()
    assert rr.events(f"applied:{msg_id}") == 1
    assert rr.events(f"decision_resolved:{gate_id}") == 1
    assert rr.gate(gate_id)["state"] in ("closed", "resolved")


def test_ac_i4_m5b_crash_after_effect_before_applied_is_not_applied_twice(
    tmp_path: Path,
) -> None:
    """AC-I.4 (R§10.2 M-5b): the effect is in the decision log; the redelivery adds none."""
    rr, msg_id, gate_id, seg2 = verified_then_resumed(tmp_path, ack_crash=False)
    # The run finds the msg_id in its decision log and runs applied only (R§4.6.2).
    applied = rr.msg("applied", msg_id, seconds=130, segment=seg2.segment_id)
    assert applied.code == 0 and applied.result == "changed", applied.show()
    # A later fire of the same generation delivers nothing more.
    assert msg_id not in frames(rr.fire(200, segment=seg2.segment_id))
    assert rr.events(f"applied:{msg_id}") == 1
    assert rr.events(f"decision_resolved:{gate_id}") == 1
    assert len(rr.consumed()) == 1


# --- the real store --------------------------------------------------------------------


def test_real_store_unchanged() -> None:
    """AC-B.10: no S6b test touches the live store."""
    assert real_db_state() == REAL_DB_STATE_AT_IMPORT
    assert os.environ.get("CREDITS_STATE_DB") is None or "credits/state.db" not in str(
        os.environ.get("CREDITS_STATE_DB")
    )
