"""S6b Stop reminders for rulings and open gates (Component C, EA-74).

Plan: docs/execution/plans/2026-10-15-scheduled-credits-runs (Component C,
AC-C.2 "handle Stop"; report R§4.6.4 step 7 and R§4.6.5).

R§4.6.4 step 7: "If a confirmed message has no ``ack``, or an acked ``ruling``
or ``stop-after-row`` has no ``applied``, or a gate is open and not expired
(section 4.6.5), block once with a reminder and set the segment's
``stop_reminded_utc``. With ``stop_hook_active`` true, or after that one
reminder, allow the stop."

``test_credits_inbox.py`` covers ``info``/``query`` without ``ack`` and a
``stop-after-row`` without ``applied``. This module covers the rest of the step:
a delivered ``ruling`` without ``ack``, an acked ``ruling`` without ``applied``
and an open gate before its deadline, with negative controls.

A gate is open when ``gates.state = 'open'``; it is not expired while the store
clock is before ``gates.deadline_utc`` (R§4.6.5 ``decision`` and ``wait``). The
expiry compare-and-set of ``credits_msg.py wait`` moves it to ``expired``.

The reminder text for a gate is not fixed by the design (chosen): the reason
names the gate id or says that a gate is open.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest

from test_credits_inbox import HOOK, Fire, fetch, stamp
from test_credits_ruling import (
    Rr,
    assert_verified,
    open_flow,
    run_proc,
)
from test_credits_state import (
    REAL_DB_STATE_AT_IMPORT,
    ROOT,
    at,
    real_db_state,
)

# --- helpers ---------------------------------------------------------------------------


def transcript_path(rr: Rr) -> Path:
    """The segment transcript the hook reads (the same path as ``Rr.fire``)."""
    return rr.st.root / "segment-transcript.jsonl"


def stop_fire(rr: Rr, seconds: int, *, active: bool = False) -> Fire:
    """Run the hook once with a ``Stop`` payload of the run's live segment."""
    payload: dict[str, Any] = {
        "session_id": rr.seg.session,
        "transcript_path": str(transcript_path(rr)),
        "cwd": str(ROOT),
        "hook_event_name": "Stop",
        "stop_hook_active": active,
    }
    argv = [sys.executable, "-X", "utf8", str(HOOK)]
    proc = run_proc(argv, rr.run_env(seconds), json.dumps(payload))
    return Fire(proc.returncode, proc.stdout, proc.stderr)


def note(rr: Rr, msg_id: str, seconds: float) -> None:
    """Append a segment transcript line that holds the frame of ``msg_id`` (confirm)."""
    text = f"[ORCHESTRATOR-MESSAGE msg_id={msg_id} seq=1 kind=ruling — fixture copy]"
    line: dict[str, Any] = {
        "type": "attachment",
        "attachment": {
            "type": "hook_additional_context",
            "content": [text],
            "hookName": "PostToolUse:Bash",
            "toolUseID": "toolu_fixture",
            "hookEvent": "PostToolUse",
        },
        "timestamp": stamp(seconds),
        "sessionId": rr.seg.session,
        "uuid": str(uuid.uuid4()),
    }
    with transcript_path(rr).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line) + "\n")


def reminded(rr: Rr) -> str | None:
    """The segment's ``stop_reminded_utc``."""
    rows = fetch(
        rr.st,
        "SELECT stop_reminded_utc FROM segments WHERE segment_id = ?",
        (rr.seg.segment_id,),
    )
    assert len(rows) == 1, rows
    value = rows[0]["stop_reminded_utc"]
    return None if value is None else str(value)


def delivered_ruling(tmp_path: Path) -> tuple[Rr, str, str]:
    """A verified ruling for D-1, emitted at 80 and confirmed from the transcript."""
    rr, tr, gate_id = open_flow(tmp_path)
    uid = tr.user("D-1: A", 60)
    msg_id = rr.relay(70, gate_id=gate_id, quote="D-1: A", uid=uid)
    assert_verified(rr, rr.fire(80), msg_id, gate_id=gate_id, uid=uid, quote="D-1: A")
    note(rr, msg_id, 81)
    confirm = rr.fire(85)
    assert confirm.code == 0, confirm.show()
    assert confirm.emitted() == [], confirm.show()
    delivery = fetch(
        rr.st,
        "SELECT confirmed_utc FROM deliveries WHERE msg_id = ? AND segment_id = ?",
        (msg_id, rr.seg.segment_id),
    )
    assert delivery == [{"confirmed_utc": at(85)}], delivery
    # The verified ruling closed its gate: no open gate confounds the message cases.
    assert rr.gate(gate_id)["state"] in ("closed", "resolved")
    return rr, msg_id, gate_id


# --- a delivered ruling without ack ---------------------------------------------------


def test_stop_reminds_once_for_a_delivered_ruling_without_ack(tmp_path: Path) -> None:
    """AC-C.2 (R§4.6.4 step 7, EA-74): a confirmed ruling with no ack blocks Stop once."""
    rr, msg_id, _ = delivered_ruling(tmp_path)
    first = stop_fire(rr, 100)
    assert first.code == 0, first.show()
    assert first.blocked, first.show()
    assert msg_id in first.reason, first.show()
    assert reminded(rr) == at(100)
    second = stop_fire(rr, 101)
    assert second.code == 0 and not second.blocked, second.show()


# --- an acked ruling without applied --------------------------------------------------


def test_stop_reminds_once_for_an_acked_ruling_without_applied(tmp_path: Path) -> None:
    """AC-C.2 (R§4.6.4 step 7, EA-74): an acked ruling with no applied blocks Stop once."""
    rr, msg_id, _ = delivered_ruling(tmp_path)
    acked = rr.msg("ack", msg_id, "applying D-1: A", seconds=90)
    assert acked.code == 0, acked.show()
    first = stop_fire(rr, 100)
    assert first.code == 0, first.show()
    assert first.blocked, first.show()
    assert msg_id in first.reason, first.show()
    assert reminded(rr) == at(100)
    second = stop_fire(rr, 101)
    assert second.code == 0 and not second.blocked, second.show()


def test_stop_is_allowed_for_an_acked_and_applied_ruling(tmp_path: Path) -> None:
    """AC-C.2 (R§4.6.4 step 7, EA-74): an applied ruling and nothing open → Stop allowed."""
    rr, msg_id, _ = delivered_ruling(tmp_path)
    acked = rr.msg("ack", msg_id, "applying D-1: A", seconds=90)
    assert acked.code == 0, acked.show()
    applied = rr.msg("applied", msg_id, seconds=95)
    assert applied.code == 0, applied.show()
    fire = stop_fire(rr, 100)
    assert fire.code == 0 and not fire.blocked, fire.show()
    assert reminded(rr) is None


# --- an open gate --------------------------------------------------------------------


def test_stop_reminds_once_for_an_open_gate_before_its_deadline(tmp_path: Path) -> None:
    """AC-C.2 (R§4.6.4 step 7, EA-74): an open gate before its deadline blocks Stop once."""
    rr, _, gate_id = open_flow(tmp_path)
    gate = rr.gate(gate_id)
    assert gate["state"] == "open"
    assert gate["deadline_utc"] == at(50 + 30 * 60)
    assert fetch(rr.st, "SELECT msg_id FROM messages") == []
    first = stop_fire(rr, 100)
    assert first.code == 0, first.show()
    assert first.blocked, first.show()
    assert gate_id in first.reason or "gate" in first.reason.lower(), first.show()
    assert reminded(rr) == at(100)
    second = stop_fire(rr, 101)
    assert second.code == 0 and not second.blocked, second.show()


@pytest.mark.parametrize("shape", ["expired_by_wait", "open_past_deadline"])
def test_stop_is_allowed_for_an_expired_gate(tmp_path: Path, shape: str) -> None:
    """AC-C.2 (R§4.6.4 step 7, EA-74): a gate at or past its deadline → Stop allowed.

    ``expired_by_wait``: the wait's compare-and-set moved the gate to ``expired``.
    ``open_past_deadline``: the row still says ``open``, but the store clock is past
    ``deadline_utc``, so the gate is expired (R§4.6.5).
    """
    rr, _, gate_id = open_flow(tmp_path)
    deadline_s = 50 + 30 * 60
    assert rr.gate(gate_id)["deadline_utc"] == at(deadline_s)
    if shape == "expired_by_wait":
        expired = rr.msg(
            "wait", "--max-wait-ms", "200", "--poll-ms", "20", seconds=deadline_s
        )
        assert expired.code == 0, expired.show()
        assert rr.gate(gate_id)["state"] == "expired"
    else:
        assert rr.gate(gate_id)["state"] == "open"
    fire = stop_fire(rr, deadline_s + 60)
    assert fire.code == 0 and not fire.blocked, fire.show()
    assert reminded(rr) is None


def test_stop_hook_active_allows_the_stop_at_an_open_gate(tmp_path: Path) -> None:
    """AC-C.2 (R§4.6.4 step 7, EA-74): stop_hook_active true at an open gate → allowed."""
    rr, _, gate_id = open_flow(tmp_path)
    assert rr.gate(gate_id)["state"] == "open"
    fire = stop_fire(rr, 100, active=True)
    assert fire.code == 0 and not fire.blocked, fire.show()
    assert reminded(rr) is None


# --- the real store --------------------------------------------------------------------


def test_real_store_unchanged() -> None:
    """AC-B.10: no test of this module touches the live store."""
    assert real_db_state() == REAL_DB_STATE_AT_IMPORT
    assert os.environ.get("CREDITS_STATE_DB") is None or "credits/state.db" not in str(
        os.environ.get("CREDITS_STATE_DB")
    )
