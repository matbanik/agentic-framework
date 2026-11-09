"""MEU-895 credits-headless-brief-authority: the monitor duties of the store (AC-895.8, unit part).

Plan: docs/execution/plans/2026-11-05-pe21-credits-authority (MEU-895 Design 7; PE21-D13;
KI SCHED-CREDITS-MONITOR-SCOPE-GAP; report sections on the monitor duties).

* ``scan_monitor --alive-json <object>`` takes the facts of the watcher, keyed by segment id:
  ``{"<segment_id>": {"transcript_mtime_utc": "...Z", "pid_alive": true, "slept": false}}``.
  The global ``--now-utc`` is its clock.
* Each duty files one notice with the key ``kind:ref``, once, at its limit.
* ``outbox_scan`` closes the open decision notice (``notices.closed_utc``).
* ``slept --segment-id`` sets ``segments.slept_utc`` and writes a ``slept`` transition. It
  never changes a state.

Every store call is a real ``credits_state.py`` subprocess on a temp store. The WCR part of
AC-895.8 is in ``tools/tests/Watch-CreditsRuns.Duties.Tests.ps1``.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from test_credits_state import (
    Out,
    Seg,
    Store,
    at,
    finish,
    first_start,
    stop,
)

RUN = "run-duty"
HANG = 3600
TERMINATION = 300
DELIVERY = 1800
NO_ACK = 600
NOT_APPLIED = 1800


@pytest.fixture
def st(tmp_path: Path) -> Store:
    store = Store(tmp_path / "store")
    store.root.mkdir()
    store.init()
    return store


def _cs() -> ModuleType:
    """The store module, imported inside a test body (a Red import error is a failure)."""
    return importlib.import_module("tools.credits_state")


def _scan_out(st: Store, now: int, alive: dict[str, Any] | None = None) -> Out:
    return st.cli("scan_monitor", "--alive-json", json.dumps(alive or {}), now=now)


def _scan(st: Store, now: int, alive: dict[str, Any] | None = None) -> None:
    out = _scan_out(st, now, alive)
    assert out.code == 0, out.show()


def _keys(st: Store, kind: str) -> list[str]:
    found = st.rows(
        "SELECT notice_key FROM notices WHERE kind = ? ORDER BY notice_key", (kind,)
    )
    return [str(row[0]) for row in found]


def _alive(
    seg: Seg, mtime: int, *, pid_alive: bool = True, slept: bool = False
) -> dict[str, Any]:
    fact = {"transcript_mtime_utc": at(mtime), "pid_alive": pid_alive, "slept": slept}
    return {seg.segment_id: fact}


def _send(st: Store, now: int, run_id: str = RUN) -> str:
    """One real ``send`` of an ``info`` message; the result is its ``msg_id``."""
    payload = st.ok(
        "send", "--run-id", run_id, "--kind", "info", "--body", "fixture body", now=now
    )
    msg_id = payload.get("msg_id")
    assert isinstance(msg_id, str) and msg_id, payload
    return msg_id


def _delivery(st: Store, msg_id: str, seg: Seg, now: int, *, fires: int = 0) -> None:
    """A delivery row in the form of the inbox hook: claimed, emitted once and confirmed."""
    utc = at(now)
    st.write(
        "INSERT INTO deliveries (msg_id, segment_id, generation, state, delivered_utc,"
        " claimed_utc, emit_count, last_emit_utc, fires_since_emit, confirmed_utc)"
        " VALUES (?, ?, 1, 'confirmed', ?, ?, 1, ?, ?, ?)",
        (msg_id, seg.segment_id, utc, utc, utc, fires, utc),
    )


def _ruling(st: Store, seg: Seg, msg_id: str, seq: int, acked: int) -> None:
    """An acked ruling message with a confirmed delivery (``send`` needs a whole ruling)."""
    st.write(
        "INSERT INTO messages (msg_id, run_id, seq, kind, body_json, state, created_utc,"
        " payload_hash, acked_utc) VALUES (?, ?, ?, 'ruling', '{}', 'open', ?, 'hash', ?)",
        (msg_id, seg.run_id, seq, at(acked), at(acked)),
    )
    _delivery(st, msg_id, seg, acked)


def _event(st: Store, kind: str, key: str, payload: dict[str, Any], now: int) -> None:
    st.write(
        "INSERT INTO outbox_events (run_id, kind, semantic_key, payload_json, created_utc)"
        " VALUES (?, ?, ?, ?, ?)",
        (RUN, kind, key, json.dumps(payload), at(now)),
    )


def _gate_payload(key: str, kind: str, gate: str, now: int) -> dict[str, Any]:
    """The payload of the ``credits_msg.py`` events (``credits-outbox.v1``)."""
    return {
        "schema": "credits-outbox.v1",
        "semantic_key": key,
        "utc": at(now),
        "run_id": RUN,
        "segment": f"seg-{RUN}-1",
        "kind": kind,
        "msg_id": f"msg-{gate}",
        "decision_id": f"D-{gate}",
        "gate_id": gate,
        "text": "fixture decision",
    }


def _decision_notice(st: Store, gate: str) -> tuple[Any, ...]:
    """The decision notice of ``gate``: the body names its event's semantic key."""
    found = [
        (key, closed)
        for key, body, closed in st.rows(
            "SELECT notice_key, body_json, closed_utc FROM notices WHERE kind = 'decision'"
        )
        if json.loads(str(body)).get("semantic_key") == f"decision:{gate}"
    ]
    assert len(found) == 1, f"decision:{gate}: {found}"
    return found[0]


def test_ac_895_8_duty_limits_are_the_planned_constants() -> None:
    """AC-895.8: the limits of the plan's Constant Classification table."""
    cs = _cs()
    assert cs.HANG_AFTER_S == HANG
    assert cs.TERMINATION_PENDING_AFTER_S == TERMINATION
    assert cs.DELIVERY_SLOW_AFTER_S == DELIVERY
    assert cs.NO_ACK_FIRES == 3
    assert cs.NO_ACK_AFTER_S == NO_ACK
    assert cs.NOT_APPLIED_AFTER_S == NOT_APPLIED


def test_ac_895_8_notice_kinds_name_each_duty() -> None:
    """AC-895.8 (Design 7): MONITOR_NOTICE_KINDS holds the new kinds and keeps the old one."""
    kinds = set(_cs().MONITOR_NOTICE_KINDS)
    assert kinds >= {
        "manual_child_alive",
        "possible_hang",
        "termination_pending",
        "delivery_slow",
        "no_ack",
        "not_applied",
        "transcript_discontinuity",
    }


def test_ac_895_8_possible_hang_files_once_at_the_limit(st: Store) -> None:
    """AC-895.8: a live segment with a still transcript; one second under files nothing."""
    seg = first_start(st, RUN)
    mtime = 1000
    alive = _alive(seg, mtime)
    _scan(st, mtime + HANG - 1, alive)
    assert _keys(st, "possible_hang") == []
    _scan(st, mtime + HANG, alive)
    assert _keys(st, "possible_hang") == [f"possible_hang:{seg.segment_id}"]
    _scan(st, mtime + HANG + 60, alive)
    assert _keys(st, "possible_hang") == [f"possible_hang:{seg.segment_id}"]


def test_ac_895_8_possible_hang_never_stops_the_segment(st: Store) -> None:
    """AC-895.8: the notice is a notice; the segment and the run stay running (never kill)."""
    seg = first_start(st, RUN)
    _scan(st, 1000 + HANG, _alive(seg, 1000))
    assert (
        st.one("SELECT state FROM segments WHERE segment_id = ?", (seg.segment_id,))
        == "running"
    )
    assert st.one("SELECT state FROM runs WHERE run_id = ?", (RUN,)) == "running"


def test_ac_895_8_possible_hang_needs_a_live_pid(st: Store) -> None:
    """AC-895.8: a dead pid is the crash path of the watcher, not a hang."""
    seg = first_start(st, RUN)
    _scan(st, 1000 + HANG * 2, _alive(seg, 1000, pid_alive=False))
    assert _keys(st, "possible_hang") == []


def test_ac_895_8_termination_pending_counts_from_its_transition(st: Store) -> None:
    """AC-895.8: the entry time is the time of the ``transitions`` row."""
    seg = first_start(st, RUN)
    entered = 100
    st.ok("termination_pending", "--segment-id", seg.segment_id, now=entered)
    alive = _alive(seg, entered, pid_alive=False)
    _scan(st, entered + TERMINATION - 1, alive)
    assert _keys(st, "termination_pending") == []
    _scan(st, entered + TERMINATION, alive)
    assert _keys(st, "termination_pending") == [f"termination_pending:{seg.segment_id}"]
    _scan(st, entered + TERMINATION + 60, alive)
    assert _keys(st, "termination_pending") == [f"termination_pending:{seg.segment_id}"]


def test_ac_895_8_delivery_slow_while_the_run_is_alive(st: Store) -> None:
    """AC-895.8: a posted message with no claim; one second under files nothing."""
    seg = first_start(st, RUN)
    posted = 100
    msg_id = _send(st, posted)
    alive = _alive(seg, posted + DELIVERY)
    _scan(st, posted + DELIVERY - 1, alive)
    assert _keys(st, "delivery_slow") == []
    _scan(st, posted + DELIVERY, alive)
    assert _keys(st, "delivery_slow") == [f"delivery_slow:{msg_id}"]
    _scan(st, posted + DELIVERY + 60, alive)
    assert _keys(st, "delivery_slow") == [f"delivery_slow:{msg_id}"]


def test_ac_895_8_a_claimed_message_is_not_slow(st: Store) -> None:
    """AC-895.8: the delivery limit ends at the claim."""
    seg = first_start(st, RUN)
    msg_id = _send(st, 100)
    _delivery(st, msg_id, seg, 110)
    _scan(st, 100 + DELIVERY * 2, _alive(seg, 100 + DELIVERY * 2))
    assert _keys(st, "delivery_slow") == []


def test_ac_895_8_no_ack_after_the_fires_and_the_limit(st: Store) -> None:
    """AC-895.8: a confirmed message with no ack after three fires and the limit."""
    seg = first_start(st, RUN)
    msg_id = _send(st, 100)
    confirmed = 200
    _delivery(st, msg_id, seg, confirmed, fires=3)
    alive = _alive(seg, confirmed + NO_ACK)
    _scan(st, confirmed + NO_ACK - 1, alive)
    assert _keys(st, "no_ack") == []
    _scan(st, confirmed + NO_ACK, alive)
    assert _keys(st, "no_ack") == [f"no_ack:{msg_id}"]
    _scan(st, confirmed + NO_ACK + 60, alive)
    assert _keys(st, "no_ack") == [f"no_ack:{msg_id}"]


def test_ac_895_8_an_acked_message_files_no_no_ack(st: Store) -> None:
    """AC-895.8: the ack ends the duty."""
    seg = first_start(st, RUN)
    msg_id = _send(st, 100)
    _delivery(st, msg_id, seg, 200, fires=3)
    st.write("UPDATE messages SET acked_utc = ? WHERE msg_id = ?", (at(210), msg_id))
    _scan(st, 200 + NO_ACK * 2, _alive(seg, 200 + NO_ACK * 2))
    assert _keys(st, "no_ack") == []


def test_ac_895_8_not_applied_counts_from_the_ack_of_a_ruling(st: Store) -> None:
    """AC-895.8: an acked ruling with no ``applied``; one second under files nothing."""
    seg = first_start(st, RUN)
    acked = 200
    _ruling(st, seg, "msg-ruling-1", 1, acked)
    alive = _alive(seg, acked + NOT_APPLIED)
    _scan(st, acked + NOT_APPLIED - 1, alive)
    assert _keys(st, "not_applied") == []
    _scan(st, acked + NOT_APPLIED, alive)
    assert _keys(st, "not_applied") == ["not_applied:msg-ruling-1"]
    _scan(st, acked + NOT_APPLIED + 60, alive)
    assert _keys(st, "not_applied") == ["not_applied:msg-ruling-1"]


def test_ac_895_8_not_applied_is_for_an_unapplied_ruling_only(st: Store) -> None:
    """AC-895.8: an acked ``info`` message and an applied ruling file nothing."""
    seg = first_start(st, RUN)
    info = _send(st, 100)
    _delivery(st, info, seg, 110)
    st.write("UPDATE messages SET acked_utc = ? WHERE msg_id = ?", (at(120), info))
    _ruling(st, seg, "msg-ruling-2", 2, 120)
    st.write(
        "UPDATE messages SET applied_utc = ? WHERE msg_id = ?",
        (at(130), "msg-ruling-2"),
    )
    _scan(st, 120 + NOT_APPLIED * 2, _alive(seg, 120 + NOT_APPLIED * 2))
    assert _keys(st, "not_applied") == []


def test_ac_895_8_a_stopped_run_files_the_message_duties_at_once(st: Store) -> None:
    """AC-895.8 (Design 7, "stopped: at once"): no limit once no session can read them."""
    seg = first_start(st, RUN)
    unclaimed = _send(st, 100)
    unacked = _send(st, 101)
    _delivery(st, unacked, seg, 102, fires=3)
    _ruling(st, seg, "msg-ruling-3", 3, 103)
    finish(st, seg, now=110, total=1.0)
    stop(st, RUN, now=111)
    _scan(st, 112)
    assert _keys(st, "delivery_slow") == [f"delivery_slow:{unclaimed}"]
    assert _keys(st, "no_ack") == [f"no_ack:{unacked}"]
    assert _keys(st, "not_applied") == ["not_applied:msg-ruling-3"]
    _scan(st, 113)
    assert len(_keys(st, "delivery_slow")) == 1
    assert len(_keys(st, "no_ack")) == 1
    assert len(_keys(st, "not_applied")) == 1


def test_ac_895_8_transcript_discontinuity_files_once_per_session(st: Store) -> None:
    """AC-895.8: a broken orchestrator session files its notice; an ``ok`` session none."""
    seg = first_start(st, RUN)
    broken = "cccccccc-0000-4000-8000-000000000003"
    healthy = "dddddddd-0000-4000-8000-000000000004"
    st.write(
        "UPDATE runs SET manifest_json = json_set(manifest_json,"
        " '$.messaging.ruling_enabled', json('true')) WHERE run_id = ?",
        (RUN,),
    )
    for session, state in ((broken, "broken"), (healthy, "ok")):
        st.write(
            "INSERT INTO orchestrator_sessions (run_id, session, history_state, attached_utc)"
            " VALUES (?, ?, ?, ?)",
            (RUN, session, state, at(50)),
        )
    alive = _alive(seg, 100)
    _scan(st, 100, alive)
    assert _keys(st, "transcript_discontinuity") == [
        f"transcript_discontinuity:{broken}"
    ]
    _scan(st, 200, alive)
    assert _keys(st, "transcript_discontinuity") == [
        f"transcript_discontinuity:{broken}"
    ]


def test_ac_895_8_a_second_scan_changes_no_notice_row(st: Store) -> None:
    """AC-895.8: a duty notice keeps its first row: no second file of any key."""
    seg = first_start(st, RUN)
    _send(st, 100)
    alive = _alive(seg, 100)
    _scan(st, 100 + HANG, alive)
    query = "SELECT notice_key, created_utc FROM notices ORDER BY notice_key"
    first = st.rows(query)
    assert first
    _scan(st, 100 + HANG + 3600, alive)
    assert st.rows(query) == first


def test_ac_895_8_a_bad_fact_files_nothing(st: Store) -> None:
    """AC-895.8 (Boundary Inventory): a time that is not ISO UTC is refused."""
    seg = first_start(st, RUN)
    bad = {seg.segment_id: {"transcript_mtime_utc": "soon", "pid_alive": True}}
    out = _scan_out(st, 1000 + HANG, bad)
    assert out.code == 3, out.show()
    assert _keys(st, "possible_hang") == []


def test_ac_895_8_outbox_scan_closes_the_open_decision_notice(st: Store) -> None:
    """AC-895.8: ``decision_resolved`` and ``gate_expired`` close the notice of their gate."""
    first_start(st, RUN)
    for gate in ("gate-A", "gate-B", "gate-C"):
        key = f"decision:{gate}"
        _event(st, "decision", key, _gate_payload(key, "decision", gate, 20), 20)
    st.ok("outbox_scan", now=21)
    for gate in ("gate-A", "gate-B", "gate-C"):
        assert _decision_notice(st, gate)[1] is None

    resolved = "decision_resolved:gate-A"
    _event(
        st,
        "decision_resolved",
        resolved,
        _gate_payload(resolved, "decision_resolved", "gate-A", 30),
        30,
    )
    # The payload of the ``finalize_segment`` event names no gate; its key does.
    _event(
        st,
        "gate_expired",
        "gate_expired:gate-B",
        {"segment_id": f"seg-{RUN}-1"},
        30,
    )
    st.ok("outbox_scan", now=31)
    assert _decision_notice(st, "gate-A")[1] == at(31)
    assert _decision_notice(st, "gate-B")[1] == at(31)
    assert _decision_notice(st, "gate-C")[1] is None
    assert len(_keys(st, "decision_resolved")) == 1
    assert len(_keys(st, "gate_expired")) == 1


def test_ac_895_8_slept_writes_the_note_and_no_stop(st: Store) -> None:
    """AC-895.8: ``slept_utc`` plus a ``slept`` transition; every state stays as it was."""
    seg = first_start(st, RUN)
    st.ok("slept", "--segment-id", seg.segment_id, now=100)
    assert st.one(
        "SELECT slept_utc FROM segments WHERE segment_id = ?", (seg.segment_id,)
    ) == at(100)
    found = st.rows(
        "SELECT from_state, to_state, at_utc FROM transitions"
        " WHERE entity = 'segment' AND entity_id = ? AND verb = 'slept'",
        (seg.segment_id,),
    )
    assert found == [("running", "running", at(100))]
    row = st.rows(
        "SELECT state, stop_class FROM segments WHERE segment_id = ?",
        (seg.segment_id,),
    )
    assert row == [("running", None)]
    assert st.one("SELECT state FROM runs WHERE run_id = ?", (RUN,)) == "running"


def test_ac_895_8_slept_keeps_the_time_of_the_last_sleep(st: Store) -> None:
    """AC-895.8 (Design 7): ``segments.slept_utc`` is the time of the last sleep."""
    seg = first_start(st, RUN)
    st.ok("slept", "--segment-id", seg.segment_id, now=100)
    st.ok("slept", "--segment-id", seg.segment_id, now=200)
    assert st.one(
        "SELECT slept_utc FROM segments WHERE segment_id = ?", (seg.segment_id,)
    ) == at(200)


def test_ac_895_8_slept_of_an_unknown_segment_is_refused(st: Store) -> None:
    """AC-895.8 (Boundary Inventory): a refusal is exit 3."""
    first_start(st, RUN)
    out = st.cli("slept", "--segment-id", "seg-none", now=100)
    assert out.code == 3, out.show()
