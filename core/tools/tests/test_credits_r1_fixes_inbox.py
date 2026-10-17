"""Execution review round 1: the attach, the deadline clock and the streamed queue.

Plan: docs/execution/plans/2026-10-15-scheduled-credits-runs (Component I; review
round 1 findings R1-F3, R1-F5 and R1-F6).

R1-F3 (AC-I.2, report section 4.5): ``attach`` adds an IDE session that the manifest
  does not list yet. The session passes the project path, the history check, the
  typed entry and the single-use checks, then the attach records it. Every refusal
  of those checks still refuses and writes nothing.
R1-F5 (AC-I.1, report section 4.6.3 step 7): the deadline check reads the production
  clock inside the consuming transaction. A hook that waits for the writer lock past
  the gate deadline refuses the ruling as ``gate_closed``. The test clock seam
  ``CREDITS_TEST_NOW_UTC`` still fixes the clock.
R1-F6 (AC-I.1, report section 4.6.3 step 5, R6-a): an entry typed while the model
  streamed (contentless ``enqueue``, assistant lines, ``dequeue``) is
  ``queued_origin``, and its text stays a queued text. An exact idle resend fails;
  a resend in other words passes.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from test_credits_inbox import HOOK, Fire
from test_credits_ruling import (
    CALL_TIMEOUT,
    ORCH,
    ORCH_2,
    Rr,
    Transcript,
    assert_unverified,
    assert_verified,
    fixture_flow,
    fixture_ts,
    fixture_uuid,
    make_run,
    open_flow,
    slug,
)
from test_credits_state import ROOT, Out, at

EXIT_REFUSED = 3
UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def attach(rr: Rr, session: str, uid: str, seconds: int) -> Out:
    """Run ``credits_state.py attach`` for one session and entry."""
    return rr.store(
        "attach",
        "--run-id",
        rr.run_id,
        "--session",
        session,
        "--uuid",
        uid,
        seconds=seconds,
    )


def session_rows(rr: Rr, session: str) -> list[dict[str, object]]:
    return rr.rows(
        "SELECT history_state FROM orchestrator_sessions WHERE run_id = ? AND session = ?",
        (rr.run_id, session),
    )


def attach_rows(rr: Rr, session: str) -> list[dict[str, object]]:
    return rr.rows(
        "SELECT * FROM attaches WHERE run_id = ? AND orchestrator_session = ?",
        (rr.run_id, session),
    )


def mark_rows(rr: Rr, session: str) -> list[dict[str, object]]:
    return rr.rows("SELECT * FROM transcript_marks WHERE session = ?", (session,))


def unlisted_run(tmp_path: Path, *, base: int = 0) -> Rr:
    """A run whose manifest lists ORCH_2 only; ORCH is a new IDE session."""
    rr = make_run(tmp_path, sessions=(ORCH_2,), base=base)
    assert session_rows(rr, ORCH) == []
    return rr


# --- R1-F3: attach a session that the manifest does not list ------------------------


def test_r1_f3_first_attach_of_an_unlisted_session_records_it(tmp_path: Path) -> None:
    """AC-I.2: a new IDE session attaches with no pre-listing; its ruling then passes."""
    rr = unlisted_run(tmp_path)
    tr = rr.transcript(ORCH)
    tr.user("Start the plan run for the fixture.", 10)
    tr.assistant("Started.", 11)
    uid = tr.user(f"attach {rr.run_id}", 20)
    out = attach(rr, ORCH, uid, 25)
    assert out.code == 0, out.show()
    assert out.result == "changed", out.show()
    assert session_rows(rr, ORCH) == [{"history_state": "ok"}]
    rows = attach_rows(rr, ORCH)
    assert len(rows) == 1, rows
    assert rows[0]["user_message_uuid"] == uid
    assert len(mark_rows(rr, ORCH)) == 1
    # The attach authorizes nothing by itself; a later ruling passes every step.
    tr.assistant("Attached.", 26)
    gate_id = rr.decision(50)
    ruling = tr.user("D-1: A", 60)
    msg_id = rr.relay(70, gate_id=gate_id, quote="D-1: A", uid=ruling)
    assert_verified(rr, rr.fire(80), msg_id, gate_id=gate_id, uid=ruling, quote="D-1: A")


def test_r1_f3_reattach_of_the_same_entry_refuses(tmp_path: Path) -> None:
    """AC-I.2 step 5: the attach entry is single use; the second attach writes nothing."""
    rr = unlisted_run(tmp_path)
    tr = rr.transcript(ORCH)
    tr.user("Start the plan run for the fixture.", 10)
    uid = tr.user(f"attach {rr.run_id}", 20)
    assert attach(rr, ORCH, uid, 25).code == 0
    again = attach(rr, ORCH, uid, 30)
    assert again.code == EXIT_REFUSED, again.show()
    # The entry is not later than the last attach: the floor check refuses it first.
    assert again.error == "entry_too_old", again.show()
    assert len(attach_rows(rr, ORCH)) == 1


REFUSALS = (
    "other_project",
    "queued_attachment",
    "not_typed_turn",
    "reused_prompt_id",
    "words_missing",
    "before_registration",
    "broken_chain",
)


@pytest.mark.parametrize("case", REFUSALS)
def test_r1_f3_unlisted_session_still_fails_each_attach_check(
    tmp_path: Path, case: str
) -> None:
    """AC-I.2 steps 1 to 5 refuse an unlisted session; nothing is recorded."""
    rr = unlisted_run(tmp_path, base=100 if case == "before_registration" else 0)
    expected: str
    tr = rr.transcript(ORCH)
    words = f"attach {rr.run_id}"
    if case == "other_project":
        # Step 1: the transcript lies under another project's slug.
        elsewhere = (
            rr.home / ".claude" / "projects" / slug("X:/s6b-elsewhere") / f"{ORCH}.jsonl"
        )
        tr = Transcript(elsewhere, ORCH)
        tr.user("Start the plan run for the fixture.", 10)
        uid = tr.user(words, 20)
        expected = "transcript_missing"
    elif case == "queued_attachment":
        # Step 3: an attach typed while busy reaches the file as an attachment.
        tr.user("Start the plan run for the fixture.", 10)
        uid = tr.queued_command(words, 20, str(uuid.uuid4()))
        expected = "not_human_entry"
    elif case == "not_typed_turn":
        tr.user("Start the plan run for the fixture.", 10)
        uid = tr.user(words, 20, drop=("turnOrigin",))
        expected = "not_typed_turn"
    elif case == "reused_prompt_id":
        reused = str(uuid.uuid4())
        tr.user("Start the plan run for the fixture.", 10, prompt_id=reused)
        uid = tr.user(words, 20, prompt_id=reused)
        expected = "replay"
    elif case == "words_missing":
        tr.user("Start the plan run for the fixture.", 10)
        uid = tr.user("attach the session please", 20)
        expected = "attach_words_missing"
    elif case == "before_registration":
        # The run registers at T0 + 100; the entry is older.
        tr.user("Start the plan run for the fixture.", 10)
        uid = tr.user(words, 50)
        expected = "entry_too_old"
    else:
        # Step 2: a parent link that no earlier line holds.
        tr.user("Start the plan run for the fixture.", 10)
        uid = tr.user(words, 20, extra={"parentUuid": str(uuid.uuid4())})
        expected = "transcript_discontinuity"
    out = attach(rr, ORCH, uid, 125)
    assert out.code == EXIT_REFUSED, out.show()
    assert out.error == expected, out.show()
    assert session_rows(rr, ORCH) == []
    assert attach_rows(rr, ORCH) == []
    assert mark_rows(rr, ORCH) == []


# --- R1-F5: the deadline check reads the clock after the writer lock -----------------


def set_deadline(rr: Rr, gate_id: str, deadline: datetime) -> None:
    rr.st.write(
        "UPDATE gates SET deadline_utc = ? WHERE gate_id = ?",
        (deadline.strftime(UTC_FORMAT), gate_id),
    )


def fire_under_lock(
    rr: Rr, tmp_path: Path, release_at: datetime, *, seam: int | None = None
) -> tuple[Fire, bool]:
    """Fire the hook while a second connection holds the writer lock until ``release_at``.

    With ``seam`` None the hook runs on the production clock. Return the fire and
    whether the hook was still waiting when the lock was released.
    """
    env = rr.run_env(seam if seam is not None else 0)
    if seam is None:
        env.pop("CREDITS_TEST_NOW_UTC", None)
    env["CREDITS_TEST_BUSY_TIMEOUT_MS"] = "30000"
    payload = {
        "session_id": rr.seg.session,
        "transcript_path": str(rr.st.root / "segment-transcript.jsonl"),
        "cwd": str(ROOT),
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "echo fixture"},
        "tool_response": {"stdout": "fixture tool output", "stderr": ""},
    }
    payload_file = tmp_path / f"payload-{uuid.uuid4().hex[:8]}.json"
    payload_file.write_text(json.dumps(payload), encoding="utf-8")
    locker = sqlite3.connect(rr.st.db, isolation_level=None, timeout=10)
    with contextlib.closing(locker), payload_file.open("rb") as stdin:
        locker.execute("BEGIN IMMEDIATE")
        try:
            proc = subprocess.Popen(
                [sys.executable, "-X", "utf8", str(HOOK)],
                stdin=stdin,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                cwd=ROOT,
            )
            while datetime.now(UTC) < release_at:
                time.sleep(0.05)
            waiting = proc.poll() is None
        finally:
            locker.execute("ROLLBACK")
        stdout, stderr = proc.communicate(timeout=CALL_TIMEOUT)
    return (
        Fire(
            proc.returncode,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        ),
        waiting,
    )


def test_r1_f5_lock_wait_past_the_deadline_refuses_the_ruling(tmp_path: Path) -> None:
    """AC-I.1 step 7: the hook got the lock after the deadline → gate_closed, nothing used."""
    rr, tr, gate_id = open_flow(tmp_path)
    uid = tr.user("D-1: A", 60)
    msg_id = rr.relay(70, gate_id=gate_id, quote="D-1: A", uid=uid)
    deadline = datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=5)
    set_deadline(rr, gate_id, deadline)
    fire, waiting = fire_under_lock(rr, tmp_path, deadline + timedelta(seconds=1))
    assert waiting, fire.show()
    assert fire.code == 0, fire.show()
    assert_unverified(rr, fire, msg_id, gate_id=gate_id, reason="gate_closed")
    assert rr.gate(gate_id)["resolved_by_msg"] is None


def test_r1_f5_lock_wait_before_the_deadline_passes_at_the_fresh_time(
    tmp_path: Path,
) -> None:
    """AC-I.1 step 10: a ruling that waited for the lock is consumed at the time it got it."""
    rr, tr, gate_id = open_flow(tmp_path)
    uid = tr.user("D-1: A", 60)
    msg_id = rr.relay(70, gate_id=gate_id, quote="D-1: A", uid=uid)
    start = datetime.now(UTC).replace(microsecond=0)
    set_deadline(rr, gate_id, start + timedelta(seconds=600))
    release_at = start + timedelta(seconds=2)
    fire, waiting = fire_under_lock(rr, tmp_path, release_at)
    assert waiting, fire.show()
    assert_verified(rr, fire, msg_id, gate_id=gate_id, uid=uid, quote="D-1: A")
    consumed = datetime.strptime(
        str(rr.consumed(msg_id)[0]["consumed_utc"]), UTC_FORMAT
    ).replace(tzinfo=UTC)
    closed = datetime.strptime(str(rr.gate(gate_id)["closed_utc"]), UTC_FORMAT).replace(
        tzinfo=UTC
    )
    assert consumed >= release_at, (consumed, release_at)
    assert closed >= release_at, (closed, release_at)


def test_r1_f5_test_clock_seam_still_fixes_the_clock(tmp_path: Path) -> None:
    """The seam stays the clock: real time is past the deadline, the seam time is not."""
    rr, tr, gate_id = open_flow(tmp_path)
    uid = tr.user("D-1: A", 60)
    msg_id = rr.relay(70, gate_id=gate_id, quote="D-1: A", uid=uid)
    assert rr.gate(gate_id)["deadline_utc"] == at(50 + 30 * 60)
    release_at = datetime.now(UTC) + timedelta(seconds=1)
    fire, _ = fire_under_lock(rr, tmp_path, release_at, seam=80)
    assert_verified(rr, fire, msg_id, gate_id=gate_id, uid=uid, quote="D-1: A")
    assert rr.consumed(msg_id)[0]["consumed_utc"] == at(80)


# --- R1-F6: the text of a streamed queued entry stays queued -------------------------


def test_r1_f6_streamed_entry_then_exact_resend_fails_and_reworded_passes(
    tmp_path: Path,
) -> None:
    """AC-I.1 step 5 / R6-a: the contentless streamed shape keeps its text queued."""
    rr, tr, gate_id = open_flow(tmp_path)
    tr.enqueue(55)
    tr.assistant("Still working.", 56)
    tr.dequeue(59)
    first = tr.user("D-1: A", 60)
    original = rr.relay(70, gate_id=gate_id, quote="D-1: A", uid=first)
    assert_unverified(rr, rr.fire(80), original, gate_id=gate_id, reason="queued_origin")
    tr.assistant("Please send it again with other words.", 81)
    tr.enqueue(85)
    tr.dequeue(86)
    exact = tr.user("D-1: A", 87)
    resend = rr.relay(90, gate_id=gate_id, quote="D-1: A", uid=exact)
    assert_unverified(rr, rr.fire(95), resend, gate_id=gate_id, reason="queued_origin")
    tr.enqueue(100)
    tr.dequeue(100)
    reworded = tr.user("D-1: A (resend)", 101)
    second = rr.relay(105, gate_id=gate_id, quote="D-1: A (resend)", uid=reworded)
    assert_verified(
        rr, rr.fire(110), second, gate_id=gate_id, uid=reworded, quote="D-1: A (resend)"
    )


def test_r1_f6_fixture_streamed_entry_then_exact_resend_fails_and_reworded_passes(
    tmp_path: Path,
) -> None:
    """AC-I.1 step 5 / R6-a (M-6 fixture line 52, the recorded streamed shape)."""
    rr, tr = fixture_flow(tmp_path)
    gate_id = rr.decision(int(fixture_ts(46)) + 1, "D-2")
    quote = "M6 c47a9e D-2: B"
    t = int(fixture_ts(71)) + 5
    original = rr.relay(
        t, gate_id=gate_id, quote=quote, uid=fixture_uuid(52), decision_id="D-2"
    )
    assert_unverified(rr, rr.fire(t + 1), original, gate_id=gate_id, reason="queued_origin")
    # The user types the same line again while the orchestrator is idle.
    tr.last_uuid = fixture_uuid(71)
    tr.enqueue(t + 2)
    tr.dequeue(t + 2)
    exact = tr.user(quote, t + 3)
    resend = rr.relay(t + 4, gate_id=gate_id, quote=quote, uid=exact, decision_id="D-2")
    assert_unverified(rr, rr.fire(t + 5), resend, gate_id=gate_id, reason="queued_origin")
    tr.enqueue(t + 6)
    tr.dequeue(t + 6)
    words = "M6 c47a9e D-2: B (resend)"
    reworded = tr.user(words, t + 7)
    second = rr.relay(
        t + 8, gate_id=gate_id, quote=words, uid=reworded, decision_id="D-2"
    )
    assert_verified(rr, rr.fire(t + 9), second, gate_id=gate_id, uid=reworded, quote=words)


def test_r1_f6_streamed_attach_then_exact_resend_fails_and_reworded_passes(
    tmp_path: Path,
) -> None:
    """Report section 4.5 / R6-a: a queued attach, the same line (fails), other words (pass)."""
    rr = make_run(tmp_path)
    tr = rr.transcript(ORCH)
    words = f"attach {rr.run_id}"
    tr.user("Start the plan run for the fixture.", 10)
    tr.enqueue(15)
    tr.assistant("Still working.", 16)
    tr.dequeue(18)
    streamed = tr.user(words, 19)
    out = attach(rr, ORCH, streamed, 20)
    assert out.code == EXIT_REFUSED and out.error == "queued_origin", out.show()
    tr.assistant("Type the attach line again with other words.", 21)
    tr.enqueue(25)
    tr.dequeue(25)
    exact = tr.user(words, 26)
    out = attach(rr, ORCH, exact, 27)
    assert out.code == EXIT_REFUSED and out.error == "queued_origin", out.show()
    assert attach_rows(rr, ORCH) == []
    tr.enqueue(30)
    tr.dequeue(30)
    reworded = tr.user(f"{words} again", 31)
    out = attach(rr, ORCH, reworded, 32)
    assert out.code == 0 and out.result == "changed", out.show()
    assert len(attach_rows(rr, ORCH)) == 1
