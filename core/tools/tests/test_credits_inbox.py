"""S1b inbox hook: ``.claude/hooks/credits_inbox.py`` (Component C).

Plan: docs/execution/plans/2026-10-15-scheduled-credits-runs (Component C,
AC-C.1, AC-C.2 and AC-C.7; report R§4.6.2, R§4.6.4, R§4.7 and R§10.2 M-5a;
acceptance matrix MX-11, MX-12 and MX-19, the S1b parts).

The tests run the hook in a subprocess with a JSON payload on stdin, as Claude
Code does, against a temp store per test (AC-B.10). They fix this contract:

* The hook reads ``CREDITS_RUN_ID``, ``CREDITS_STATE_DB`` and
  ``CREDITS_SEGMENT``. With any of them unset it exits 0, prints nothing and
  opens no store.
* ``CREDITS_TEST_NOW_UTC=<YYYY-MM-DDTHH:MM:SSZ>`` is the hook's clock (test
  seam; the tests never sleep).
* ``CREDITS_TEST_CRASH_AT=inbox:<point>`` ends the hook with exit 9 at
  ``after_claim`` (inside the claim transaction, before its commit),
  ``after_emit_count`` (after that commit, before the output), ``after_emit``
  (after the output) or ``after_confirm`` (after the confirm commit).
* A skipped payload inserts one ``hook_skips`` row (``reason``, ``run_id``,
  ``segment_id``, ``session_id``, ``created_utc``) with the reason
  ``bind_mismatch`` or ``segment_not_live``.
* Messages enter through ``credits_state.py send --run-id <id> --kind <kind>
  --body <text>``. A resumed or fresh-session segment enters through
  ``credits_state.py register_minimal --resume``: it adds a new segment (a new
  delivery generation) to the manual run once every older segment is
  finalized, and closes each open ``stop-after-row`` as
  ``superseded_by_resume`` in the same transaction.
"""

from __future__ import annotations

import contextlib
import json
import re
import sqlite3
import statistics
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from test_credits_state import (
    BOOT,
    REAL_DB_STATE_AT_IMPORT,
    ROOT,
    SESSION_A,
    SESSION_B,
    T0,
    Out,
    Store,
    at,
    child_env,
    parse_out,
    real_db_state,
)

HOOK = ROOT / ".claude" / "hooks" / "credits_inbox.py"
MSG_TOOL = ROOT / "tools" / "credits_msg.py"

# Plan Constant Classification: the median of 5 no-op runs must stay below it.
HOOK_NOOP_MS_MAX = 300

ORIG_STDOUT = "fixture tool output"
ORIG_STDERR = "fixture tool warning"
FRAME_RE = re.compile(
    r"\[ORCHESTRATOR-MESSAGE msg_id=([A-Za-z0-9._-]+) seq=(\d+) kind=([a-z-]+)"
)
CONFIG_DEFAULTS: dict[str, Any] = {
    "ruling_enabled": False,
    "gate_wait_max_min": 0,
    "cache_ttl": "5m",
    "credits_start_policy": "human-only",
}


def stamp(seconds: float) -> str:
    """Return a transcript timestamp (milliseconds, ``Z``) at ``T0 + seconds``."""
    moment = T0 + timedelta(seconds=seconds)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def fetch(st: Store, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    """Return the rows of one query as dicts."""
    with contextlib.closing(sqlite3.connect(st.db)) as con:
        con.row_factory = sqlite3.Row
        return [dict(row) for row in con.execute(sql, params)]


@dataclass(frozen=True)
class Fire:
    """One hook run: exit code and both streams."""

    code: int
    stdout: str
    stderr: str

    @property
    def payload(self) -> dict[str, Any] | None:
        text = self.stdout.strip()
        if not text:
            return None
        loaded = json.loads(text)
        assert isinstance(loaded, dict), self.show()
        return loaded

    @property
    def context(self) -> str:
        """The ``additionalContext`` of a PostToolUse output, or ``""``."""
        payload = self.payload or {}
        specific = payload.get("hookSpecificOutput") or {}
        return str(specific.get("additionalContext") or "")

    @property
    def updated(self) -> dict[str, Any] | None:
        payload = self.payload or {}
        specific = payload.get("hookSpecificOutput") or {}
        found = specific.get("updatedToolOutput")
        return found if isinstance(found, dict) else None

    @property
    def blocked(self) -> bool:
        return (self.payload or {}).get("decision") == "block"

    @property
    def reason(self) -> str:
        return str((self.payload or {}).get("reason") or "")

    def emitted(self) -> list[str]:
        """The msg ids of the frames this fire carried, in output order."""
        text = self.reason if self.blocked else self.context
        return [m.group(1) for m in FRAME_RE.finditer(text)]

    def show(self) -> str:
        return f"exit={self.code}\nstdout={self.stdout[-1500:]}\nstderr={self.stderr[-1500:]}"


def run_hook(
    payload: dict[str, Any], env: dict[str, str], timeout: float = 60.0
) -> Fire:
    """Run the hook once with ``payload`` on stdin."""
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=child_env(env),
        timeout=timeout,
        cwd=ROOT,
        check=False,
    )
    return Fire(proc.returncode, proc.stdout, proc.stderr)


def write_config(path: Path, **values: Any) -> Path:
    """Write a temp ``config.json`` (never the live one)."""
    path.write_text(json.dumps({**CONFIG_DEFAULTS, **values}), encoding="utf-8")
    return path


@dataclass(frozen=True)
class Live:
    """One bound segment of a manual run, with its session and transcript."""

    st: Store
    run_id: str
    segment: str
    session: str
    transcript: Path
    config: Path

    def env(self, seconds: int, extra: dict[str, str] | None = None) -> dict[str, str]:
        return self.st.env(
            {
                "CREDITS_RUN_ID": self.run_id,
                "CREDITS_STATE_DB": str(self.st.db),
                "CREDITS_SEGMENT": self.segment,
                "CREDITS_CONFIG": str(self.config),
                "CREDITS_TEST_NOW_UTC": at(seconds),
                **(extra or {}),
            }
        )

    def fire(
        self,
        seconds: int,
        *,
        event: str = "PostToolUse",
        tool: str = "Bash",
        session: str | None = None,
        agent_id: str | None = None,
        stop_hook_active: bool = False,
        crash: str | None = None,
        omit_session: bool = False,
    ) -> Fire:
        payload: dict[str, Any] = {
            "session_id": session or self.session,
            "transcript_path": str(self.transcript),
            "cwd": str(ROOT),
            "hook_event_name": event,
        }
        if omit_session:
            del payload["session_id"]
        if agent_id is not None:
            payload["agent_id"] = agent_id
        if event == "PostToolUse":
            payload["tool_name"] = tool
            payload["tool_input"] = {"command": "echo fixture"}
            payload["tool_response"] = (
                {
                    "stdout": ORIG_STDOUT,
                    "stderr": ORIG_STDERR,
                    "interrupted": False,
                    "isImage": False,
                }
                if tool == "Bash"
                else {"type": "text", "file": {"filePath": "fixture.txt"}}
            )
        else:
            payload["stop_hook_active"] = stop_hook_active
        extra = {"CREDITS_TEST_CRASH_AT": f"inbox:{crash}"} if crash else None
        return run_hook(payload, self.env(seconds, extra))

    def send(self, kind: str, body: str, seconds: int = 0) -> str:
        out = self.st.cli(
            "send", "--run-id", self.run_id, "--kind", kind, "--body", body, now=seconds
        )
        assert out.code == 0 and out.payload is not None, out.show()
        msg_id = out.payload.get("msg_id")
        assert isinstance(msg_id, str) and msg_id, out.show()
        return msg_id

    def msg(
        self, verb: str, *args: str, seconds: int = 0, crash: str | None = None
    ) -> Out:
        """Run one ``credits_msg.py`` verb with this segment's ``CREDITS_*`` values."""
        extra = {"CREDITS_TEST_CRASH_AT": crash} if crash else None
        proc = subprocess.run(
            [
                sys.executable,
                "-X",
                "utf8",
                str(MSG_TOOL),
                "--now-utc",
                at(seconds),
                verb,
                *args,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=child_env(self.env(seconds, extra)),
            timeout=120,
            cwd=ROOT,
            check=False,
        )
        return parse_out(proc.returncode, proc.stdout, proc.stderr)

    def note(self, msg_id: str, seconds: float, shape: str = "attachment") -> None:
        """Append a transcript line that holds the frame of ``msg_id``."""
        text = f"[ORCHESTRATOR-MESSAGE msg_id={msg_id} seq=1 kind=info — fixture copy]"
        if shape == "attachment":
            line: dict[str, Any] = {
                "type": "attachment",
                "attachment": {
                    "type": "hook_additional_context",
                    "content": [text],
                    "hookName": "PostToolUse:Bash",
                    "toolUseID": "toolu_fixture",
                    "hookEvent": "PostToolUse",
                },
            }
        else:
            line = {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_fixture",
                            "content": f"{ORIG_STDOUT}\n\n{text}",
                            "is_error": False,
                        }
                    ],
                },
                "toolUseResult": {
                    "stdout": f"{ORIG_STDOUT}\n\n{text}",
                    "stderr": "",
                    "interrupted": False,
                    "isImage": False,
                },
            }
        line.update(
            timestamp=stamp(seconds), sessionId=self.session, uuid=str(uuid.uuid4())
        )
        with self.transcript.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line) + "\n")

    def delivery(
        self, msg_id: str, segment: str | None = None
    ) -> dict[str, Any] | None:
        found = fetch(
            self.st,
            "SELECT * FROM deliveries WHERE msg_id = ? AND segment_id = ?",
            (msg_id, segment or self.segment),
        )
        return found[0] if found else None

    def message(self, msg_id: str) -> dict[str, Any]:
        found = fetch(self.st, "SELECT * FROM messages WHERE msg_id = ?", (msg_id,))
        assert len(found) == 1, found
        return found[0]

    def skips(self) -> list[str]:
        return [
            str(r["reason"])
            for r in fetch(self.st, "SELECT reason FROM hook_skips ORDER BY rowid")
        ]

    def finalize(self, seconds: int) -> None:
        self.st.ok(
            "complete_segment",
            "--segment-id",
            self.segment,
            "--finalized-by",
            "wrapper",
            "--class",
            "stopped",
            "--exit-code",
            "0",
            now=seconds,
        )

    def resume(self, segment: str, session: str, seconds: int) -> Live:
        """A new delivery generation of this run: ``register_minimal --resume``."""
        bind(self.st, self.run_id, segment, session, seconds, resume=True)
        transcript = self.transcript.with_name(f"{segment}.jsonl")
        return replace(self, segment=segment, session=session, transcript=transcript)


def bind(
    st: Store,
    run_id: str,
    segment: str,
    session: str,
    seconds: int,
    *,
    resume: bool = False,
) -> None:
    """Register (or resume) a manual segment and move it to ``running``."""
    args = [
        "--run-id",
        run_id,
        "--segment-id",
        segment,
        "--wrapper-pid",
        "4242",
        "--wrapper-created",
        at(seconds),
        "--boot-id",
        BOOT,
        "--win-session",
        "1",
        "--job-name",
        "Local\\{{PROJECT_NAME_UPPER}}Credits-" + segment,
        "--expected-session-id",
        session,
    ]
    if resume:
        args.append("--resume")
    st.ok("register_minimal", *args, now=seconds)
    st.ok(
        "manual_identity",
        "--segment-id",
        segment,
        "--pid",
        "5151",
        "--created",
        at(seconds),
        now=seconds,
    )


@pytest.fixture
def st(tmp_path: Path) -> Store:
    store = Store(tmp_path / "store")
    store.root.mkdir()
    store.init()
    return store


@pytest.fixture
def live(st: Store, tmp_path: Path) -> Live:
    """A temp store and config; the run is registered inside each test."""
    return Live(
        st=st,
        run_id="c1-run",
        segment="seg-c1-run",
        session=SESSION_A,
        transcript=tmp_path / "seg-c1-run.jsonl",
        config=write_config(tmp_path / "config.json"),
    )


def started(live: Live) -> Live:
    bind(live.st, live.run_id, live.segment, live.session, 0)
    return live


# --- AC-C.1: a fast no-op outside a credits run ------------------------------------


@pytest.mark.parametrize("event", ["PostToolUse", "Stop"])
def test_noop_outside_a_credits_run_opens_no_store(tmp_path: Path, event: str) -> None:
    """AC-C.1: with CREDITS_RUN_ID unset the hook exits 0, prints nothing and opens no store."""
    absent = tmp_path / "absent" / "state.db"
    payload = {"session_id": SESSION_A, "hook_event_name": event, "tool_name": "Bash"}
    fire = run_hook(
        payload, {"CREDITS_STATE_DB": str(absent), "CREDITS_SEGMENT": "seg-x"}
    )
    assert fire.code == 0, fire.show()
    assert fire.stdout == "", fire.show()
    assert not absent.exists()
    assert not absent.parent.exists()


def test_noop_median_of_five_runs_is_under_hook_noop_ms_max() -> None:
    """AC-C.1: the median of 5 no-op runs is under HOOK_NOOP_MS_MAX (PD-9)."""
    payload = {
        "hook_event_name": "PostToolUse",
        "session_id": "00000000-0000-4000-8000-000000000000",
        "tool_name": "Bash",
    }
    times: list[float] = []
    for _ in range(5):
        began = time.perf_counter()
        fire = run_hook(payload, {})
        times.append((time.perf_counter() - began) * 1000.0)
        assert fire.code == 0 and fire.stdout == "", fire.show()
    assert statistics.median(times) < HOOK_NOOP_MS_MAX, times


def test_segment_not_live_skips_and_records_the_skip(live: Live) -> None:
    """AC-C.1 negative (MX-12 family): a finalized segment → skip, segment_not_live."""
    started(live)
    msg_id = live.send("info", "fixture context", 1)
    live.finalize(2)
    fire = live.fire(3)
    assert fire.code == 0, fire.show()
    assert fire.emitted() == [], fire.show()
    assert live.skips() == ["segment_not_live"]
    assert live.delivery(msg_id) is None


def test_unknown_segment_skips_as_segment_not_live(live: Live) -> None:
    """AC-C.1 negative: CREDITS_SEGMENT names no segment → skip, segment_not_live."""
    started(live)
    live.send("info", "fixture context", 1)
    fire = replace(live, segment="seg-missing").fire(3)
    assert fire.code == 0, fire.show()
    assert fire.emitted() == [], fire.show()
    assert live.skips() == ["segment_not_live"]


# --- AC-C.2: bind, emit, confirm, redeliver, Stop ----------------------------------


def test_mx_12_session_mismatch_skips_and_records_bind_mismatch(live: Live) -> None:
    """AC-C.2 / MX-12: a session id other than the segment's expected one → skip."""
    started(live)
    msg_id = live.send("info", "fixture context", 1)
    fire = live.fire(2, session=SESSION_B)
    assert fire.code == 0, fire.show()
    assert fire.stdout.strip() == "", fire.show()
    assert live.skips() == ["bind_mismatch"]
    rows = fetch(live.st, "SELECT run_id, segment_id, session_id FROM hook_skips")
    assert rows == [
        {"run_id": live.run_id, "segment_id": live.segment, "session_id": SESSION_B}
    ]
    assert live.delivery(msg_id) is None
    # The bound session still gets the message: nothing was learned from the stray fire.
    assert live.fire(3).emitted() == [msg_id]


def test_payload_with_agent_id_is_skipped(live: Live) -> None:
    """AC-C.2: a subagent payload (agent_id) gets nothing; only the coordinator thread does."""
    started(live)
    msg_id = live.send("info", "fixture context", 1)
    fire = live.fire(2, agent_id="agent-fixture")
    assert fire.code == 0, fire.show()
    assert fire.emitted() == [], fire.show()
    assert live.delivery(msg_id) is None
    assert live.fire(3).emitted() == [msg_id]


def test_payload_without_session_id_is_skipped(live: Live) -> None:
    """AC-C.2 boundary: a payload with no session_id is never trusted for delivery."""
    started(live)
    msg_id = live.send("info", "fixture context", 1)
    fire = live.fire(2, omit_session=True)
    assert fire.code == 0, fire.show()
    assert fire.emitted() == [], fire.show()
    assert live.delivery(msg_id) is None


def test_emit_frames_the_message_and_updates_bash_output(live: Live) -> None:
    """AC-C.2: the frame goes in additionalContext and, on Bash, in updatedToolOutput."""
    started(live)
    msg_id = live.send("info", "CI on main is red for an external reason", 1)
    fire = live.fire(2)
    assert fire.code == 0, fire.show()
    payload = fire.payload
    assert payload is not None, fire.show()
    assert payload["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    context = fire.context
    assert fire.emitted() == [msg_id]
    assert f"msg_id={msg_id} seq=1 kind=info" in context
    assert "not a human turn" in context
    assert "CI on main is red for an external reason" in context
    assert f"python tools/credits_msg.py ack {msg_id}" in context
    updated = fire.updated
    assert updated is not None, fire.show()
    assert str(updated["stdout"]).startswith(ORIG_STDOUT)
    assert f"msg_id={msg_id}" in str(updated["stdout"])
    assert updated["stderr"] == ORIG_STDERR
    assert updated["interrupted"] is False
    assert updated["isImage"] is False
    row = live.delivery(msg_id)
    assert row is not None
    assert row["claimed_utc"] == at(2)
    assert row["emit_count"] == 1
    assert row["last_emit_utc"] == at(2)
    assert row["confirmed_utc"] is None


def test_emit_on_a_non_bash_tool_has_no_updated_tool_output(live: Live) -> None:
    """AC-C.2: updatedToolOutput is set only when the tool is Bash."""
    started(live)
    msg_id = live.send("query", "report status", 1)
    fire = live.fire(2, tool="Read")
    assert fire.emitted() == [msg_id], fire.show()
    assert fire.updated is None


def test_stop_after_row_frame_names_the_applied_command(live: Live) -> None:
    """AC-C.2: a stop-after-row frame also tells the run to record the effect."""
    started(live)
    msg_id = live.send("stop-after-row", "finish the row, then end", 1)
    context = live.fire(2).context
    assert "kind=stop-after-row" in context
    assert f"python tools/credits_msg.py applied {msg_id}" in context


def test_pending_messages_emit_in_seq_order(live: Live) -> None:
    """AC-C.2: every pending message goes out in one fire, in seq order."""
    started(live)
    first = live.send("info", "first", 1)
    second = live.send("query", "second", 2)
    fire = live.fire(3)
    assert fire.emitted() == [first, second], fire.show()
    seqs = [int(m.group(2)) for m in FRAME_RE.finditer(fire.context)]
    assert seqs == [1, 2]


@pytest.mark.parametrize("shape", ["attachment", "tool_result"])
def test_confirm_from_the_transcript_stops_the_reemit(live: Live, shape: str) -> None:
    """AC-C.2: the frame in the transcript after last_emit_utc sets confirmed_utc."""
    started(live)
    msg_id = live.send("info", "fixture context", 1)
    assert live.fire(2).emitted() == [msg_id]
    live.note(msg_id, 3.5, shape)
    assert live.fire(10).emitted() == []
    row = live.delivery(msg_id)
    assert row is not None and row["confirmed_utc"] == at(10)
    for seconds in (100, 200, 300):
        assert live.fire(seconds).emitted() == []
    row = live.delivery(msg_id)
    assert row is not None and row["emit_count"] == 1 and row["failed_utc"] is None


def test_a_transcript_line_before_the_emit_does_not_confirm(live: Live) -> None:
    """AC-C.2: only a line after last_emit_utc confirms the emit."""
    started(live)
    msg_id = live.send("info", "fixture context", 1)
    live.note(msg_id, -30)
    assert live.fire(2).emitted() == [msg_id]
    assert live.fire(12).emitted() == []
    row = live.delivery(msg_id)
    assert row is not None and row["confirmed_utc"] is None
    assert live.fire(63).emitted() == [msg_id]


def test_reemit_needs_two_more_fires_and_sixty_seconds(live: Live) -> None:
    """AC-C.2: not confirmed after 2 more fires and 60 s → emit again."""
    started(live)
    msg_id = live.send("info", "fixture context", 0)
    assert live.fire(0).emitted() == [msg_id]
    # Two more fires, but under 60 s: no emit.
    assert live.fire(10).emitted() == []
    assert live.fire(59).emitted() == []
    # The third later fire at 60 s: emit again.
    assert live.fire(60).emitted() == [msg_id]
    row = live.delivery(msg_id)
    assert row is not None and row["emit_count"] == 2 and row["last_emit_utc"] == at(60)
    # 60 s passed, but only one more fire: no emit.
    assert live.fire(200).emitted() == []
    assert live.fire(201).emitted() == [msg_id]


def test_three_emits_without_a_confirm_set_failed(live: Live) -> None:
    """AC-C.2: after 3 emits with no confirm the delivery is failed and stops."""
    started(live)
    msg_id = live.send("info", "fixture context", 0)
    emits = 0
    for seconds in (0, 10, 70, 80, 140, 150, 210, 220, 280):
        emits += live.fire(seconds).emitted().count(msg_id)
    assert emits == 3
    row = live.delivery(msg_id)
    assert row is not None
    assert row["emit_count"] == 3
    assert row["failed_utc"] is not None
    assert row["confirmed_utc"] is None


def test_stop_emits_a_pending_message_as_a_block(live: Live) -> None:
    """AC-C.2: on Stop a pending message is claimed and emitted as decision block."""
    started(live)
    msg_id = live.send("stop-after-row", "finish the row, then end", 1)
    fire = live.fire(2, event="Stop")
    assert fire.code == 0, fire.show()
    assert fire.blocked, fire.show()
    assert fire.emitted() == [msg_id]
    row = live.delivery(msg_id)
    assert row is not None and row["emit_count"] == 1


def test_stop_reminds_once_for_a_confirmed_message_without_ack(live: Live) -> None:
    """AC-C.2: a confirmed message with no ack blocks Stop once, then the stop is allowed."""
    started(live)
    msg_id = live.send("info", "fixture context", 1)
    assert live.fire(2).emitted() == [msg_id]
    live.note(msg_id, 3)
    assert live.fire(5).emitted() == []
    first = live.fire(6, event="Stop")
    assert first.blocked, first.show()
    assert msg_id in first.reason
    reminded = fetch(
        live.st,
        "SELECT stop_reminded_utc FROM segments WHERE segment_id = ?",
        (live.segment,),
    )
    assert reminded == [{"stop_reminded_utc": at(6)}]
    second = live.fire(7, event="Stop")
    assert second.code == 0 and not second.blocked, second.show()


def test_stop_reminds_for_an_acked_stop_after_row_without_applied(live: Live) -> None:
    """AC-C.2: an acked stop-after-row with no applied blocks Stop once."""
    started(live)
    msg_id = live.send("stop-after-row", "finish the row, then end", 1)
    assert live.fire(2).emitted() == [msg_id]
    live.note(msg_id, 3)
    assert live.fire(5).emitted() == []
    ack = live.msg("ack", msg_id, "will stop after this row", seconds=6)
    assert ack.code == 0, ack.show()
    fire = live.fire(7, event="Stop")
    assert fire.blocked, fire.show()
    assert msg_id in fire.reason
    assert not live.fire(8, event="Stop").blocked


def test_stop_hook_active_allows_the_stop(live: Live) -> None:
    """AC-C.2: with stop_hook_active true the reminder case allows the stop."""
    started(live)
    msg_id = live.send("info", "fixture context", 1)
    assert live.fire(2).emitted() == [msg_id]
    live.note(msg_id, 3)
    assert live.fire(5).emitted() == []
    fire = live.fire(6, event="Stop", stop_hook_active=True)
    assert fire.code == 0 and not fire.blocked, fire.show()


def test_stop_with_nothing_open_is_allowed(live: Live) -> None:
    """AC-C.2: Stop with no message and no gate prints no block."""
    started(live)
    fire = live.fire(2, event="Stop")
    assert fire.code == 0 and not fire.blocked, fire.show()


# --- AC-C.7: M-5a crash points and delivery generations ----------------------------


def test_mx_11_crash_after_claim_rolls_back_and_the_next_fire_emits(live: Live) -> None:
    """AC-C.7 / MX-11: a crash inside the claim transaction leaves no claim."""
    started(live)
    msg_id = live.send("info", "fixture context", 1)
    crashed = live.fire(2, crash="after_claim")
    assert crashed.code == 9, crashed.show()
    assert crashed.emitted() == []
    row = live.delivery(msg_id)
    assert row is None or (row["emit_count"] or 0) == 0
    assert live.fire(3).emitted() == [msg_id]
    row = live.delivery(msg_id)
    assert row is not None and row["emit_count"] == 1


@pytest.mark.parametrize("point", ["after_emit_count", "after_emit"])
def test_mx_11_crash_around_the_emit_is_emitted_again(live: Live, point: str) -> None:
    """AC-C.7 / MX-11: a crash after the emit count or the emit → emitted again later."""
    started(live)
    msg_id = live.send("info", "fixture context", 1)
    crashed = live.fire(2, crash=point)
    assert crashed.code == 9, crashed.show()
    row = live.delivery(msg_id)
    assert row is not None and row["emit_count"] == 1
    assert live.fire(12).emitted() == []
    assert live.fire(63).emitted() == [msg_id]
    row = live.delivery(msg_id)
    assert row is not None and row["emit_count"] == 2


def test_mx_11_crash_after_confirm_keeps_the_confirm(live: Live) -> None:
    """AC-C.7 / MX-11: a crash after the confirm commit → no second emit."""
    started(live)
    msg_id = live.send("info", "fixture context", 1)
    assert live.fire(2).emitted() == [msg_id]
    live.note(msg_id, 3)
    crashed = live.fire(5, crash="after_confirm")
    assert crashed.code == 9, crashed.show()
    row = live.delivery(msg_id)
    assert row is not None and row["confirmed_utc"] == at(5)
    for seconds in (10, 70, 140):
        assert live.fire(seconds).emitted() == []


def test_crash_after_the_ack_of_an_info_is_never_redelivered(live: Live) -> None:
    """AC-C.7 negative (M-5a): a crash after ack of an info → closed, never redelivered."""
    started(live)
    msg_id = live.send("info", "fixture context", 1)
    assert live.fire(2).emitted() == [msg_id]
    acked = live.msg("ack", msg_id, "noted", seconds=3, crash="ack:after_commit")
    assert acked.code == 9, acked.show()
    message = live.message(msg_id)
    assert message["acked_utc"] == at(3)
    assert message["closed_reason"] == "done"
    live.finalize(4)
    nxt = live.resume("seg-c1-run-2", SESSION_A, 5)
    for seconds in (6, 70, 140):
        assert nxt.fire(seconds).emitted() == []
    assert nxt.delivery(msg_id) is None


def test_unacked_info_and_query_are_redelivered_in_the_next_generation(
    live: Live,
) -> None:
    """AC-C.7 (M-5a): emitted and confirmed but not acked → pending in the new generation."""
    started(live)
    info = live.send("info", "fixture context", 1)
    query = live.send("query", "report status", 2)
    assert live.fire(3).emitted() == [info, query]
    live.note(info, 4)
    live.note(query, 4)
    assert live.fire(5).emitted() == []
    live.finalize(6)
    nxt = live.resume("seg-c1-run-2", SESSION_A, 7)
    assert nxt.fire(8).emitted() == [info, query]
    # The old generation keeps its audit history.
    old = live.delivery(info)
    assert old is not None and old["confirmed_utc"] == at(5)
    new = nxt.delivery(info)
    assert new is not None and new["emit_count"] == 1 and new["confirmed_utc"] is None


def test_mx_19_resume_closes_an_open_stop_after_row_as_superseded(live: Live) -> None:
    """AC-C.7 / MX-19: a resume closes each open stop-after-row; it is never redelivered."""
    started(live)
    stop = live.send("stop-after-row", "finish the row, then end", 1)
    info = live.send("info", "fixture context", 2)
    assert live.fire(3).emitted() == [stop, info]
    ack = live.msg("ack", stop, "will stop after this row", seconds=4)
    assert ack.code == 0, ack.show()
    live.finalize(5)
    nxt = live.resume("seg-c1-run-2", SESSION_A, 6)
    message = live.message(stop)
    assert message["closed_reason"] == "superseded_by_resume"
    assert message["closed_utc"] == at(6)
    assert live.message(info)["closed_reason"] is None
    assert nxt.fire(7).emitted() == [info]


def test_fresh_session_fallback_makes_every_open_message_pending(live: Live) -> None:
    """AC-C.7 (M-5a): a fresh session is a new generation; every open message is pending."""
    started(live)
    closed = live.send("info", "already handled", 1)
    confirmed = live.send("query", "report status", 2)
    assert live.fire(3).emitted() == [closed, confirmed]
    ack = live.msg("ack", closed, "noted", seconds=4)
    assert ack.code == 0, ack.show()
    live.note(confirmed, 5)
    assert live.fire(6).emitted() == []
    unseen = live.send("info", "sent after the confirm", 7)
    live.finalize(8)
    fresh = live.resume("seg-c1-run-2", SESSION_B, 9)
    # The old session is no longer bound to the run.
    assert fresh.fire(10, session=SESSION_A).emitted() == []
    assert "bind_mismatch" in fresh.skips()
    assert fresh.fire(11).emitted() == [confirmed, unseen]


def test_resume_is_refused_while_a_segment_is_live(live: Live) -> None:
    """AC-C.7 boundary: a new generation needs every older segment finalized."""
    started(live)
    args = [
        "--run-id",
        live.run_id,
        "--segment-id",
        "seg-c1-run-2",
        "--wrapper-pid",
        "4243",
        "--wrapper-created",
        at(3),
        "--boot-id",
        BOOT,
        "--win-session",
        "1",
        "--job-name",
        "Local\\{{PROJECT_NAME_UPPER}}Credits-seg-c1-run-2",
        "--expected-session-id",
        SESSION_B,
        "--resume",
    ]
    out = live.st.cli("register_minimal", *args, now=3)
    assert out.code == 3, out.show()
    assert out.error == "segment_live", out.show()
    assert fetch(
        live.st, "SELECT segment_id FROM segments WHERE run_id = ?", (live.run_id,)
    ) == [{"segment_id": live.segment}]


def test_real_store_unchanged() -> None:
    """AC-B.10: no test of this file touched the real store."""
    assert real_db_state() == REAL_DB_STATE_AT_IMPORT
