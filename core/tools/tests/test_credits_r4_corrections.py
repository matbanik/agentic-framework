"""Execution review round 4 of docs/execution/plans/2026-11-05-pe21-credits-authority (EA-15).

Each test is the failing regression of one review finding, written before its fix:

* R4-F1 (AC-895.8): the hook clock has whole seconds, so a later fire in the second of the
  confirm has the confirm's time. The fire that confirmed the message is not counted; each
  other fire is, in the same second or later (report.md:1250-1253). The messages, the
  deliveries and the fires come from the real inbox hook.
"""

from __future__ import annotations

from test_credits_inbox import Live, live, st, started
from test_credits_monitor_duties import _keys, _scan
from test_credits_state import at
from test_credits_r3_corrections import (
    CONFIRM,
    NO_ACK_AFTER,
    _alive,
    _confirmed,
    _open_unacked,
)

__all__ = ["live", "st"]

#: The first scan time at which ``no_ack`` is due: ten minutes from the confirm.
DUE = CONFIRM + NO_ACK_AFTER


def _fires(live: Live, msg_id: str) -> int:
    row = live.delivery(msg_id)
    assert row is not None, msg_id
    return int(row["fires_since_emit"])


def test_r4_f1_the_confirming_fire_is_not_counted(live: Live) -> None:
    """R4-F1 control: after the fire that confirms, the count is 0."""
    msg_id = _confirmed(live)
    assert _fires(live, msg_id) == 0


def test_r4_f1_a_later_fire_in_the_confirm_second_counts(live: Live) -> None:
    """R4-F1: a later fire with the confirm's time counts; 10, 20 and 30 s give no_ack."""
    msg_id = _confirmed(live)
    for seconds in (CONFIRM, 20, 30):
        assert live.fire(seconds).emitted() == []
    assert _fires(live, msg_id) == 3
    _open_unacked(live, msg_id)
    _scan(live.st, DUE, _alive(live, DUE))
    assert _keys(live.st, "no_ack") == [f"no_ack:{msg_id}"]


def test_r4_f1_three_later_fires_in_the_confirm_second(live: Live) -> None:
    """R4-F1: three later fires all in the confirm's second count three."""
    msg_id = _confirmed(live)
    for _ in range(3):
        assert live.fire(CONFIRM).emitted() == []
    assert _fires(live, msg_id) == 3
    _scan(live.st, DUE, _alive(live, DUE))
    assert _keys(live.st, "no_ack") == [f"no_ack:{msg_id}"]


def test_r4_f1_two_later_fires_in_the_confirm_second_are_not_enough(live: Live) -> None:
    """R4-F1 control: two later fires in the confirm's second file nothing."""
    msg_id = _confirmed(live)
    for _ in range(2):
        live.fire(CONFIRM)
    assert _fires(live, msg_id) == 2
    _scan(live.st, DUE, _alive(live, DUE))
    assert _keys(live.st, "no_ack") == []


def test_r4_f1_the_fire_after_a_crash_at_the_confirm_counts(live: Live) -> None:
    """R4-F1: the confirm commits and the hook ends before its claim; the next fire counts."""
    msg_id = _confirmed_after_crash(live)
    for seconds in (CONFIRM, CONFIRM, 30):
        live.fire(seconds)
    assert _fires(live, msg_id) == 3
    _scan(live.st, DUE, _alive(live, DUE))
    assert _keys(live.st, "no_ack") == [f"no_ack:{msg_id}"]


def _confirmed_after_crash(live: Live) -> str:
    """A message that the fire of 10 s confirmed, with a crash after the confirm."""
    started(live)
    msg_id = live.send("info", "fixture context", 0)
    assert live.fire(2).emitted() == [msg_id]
    live.note(msg_id, 3.5)
    crashed = live.fire(CONFIRM, crash="after_confirm")
    assert crashed.code == 9, crashed.show()
    row = live.delivery(msg_id)
    assert row is not None and row["confirmed_utc"] == at(CONFIRM), row
    assert row["fires_since_emit"] == 0, row
    return msg_id
