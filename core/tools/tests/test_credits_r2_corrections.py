"""Execution review round 2 of docs/execution/plans/2026-11-05-pe21-credits-authority (EA-14).

Each test is the failing regression of one review finding, written before its fix:

* R2-F1 (AC-895.8): a delivery of the current segment that the inbox claimed but that was
  never confirmed (still re-emitting, or failed after its last emit) is reconciled as
  ``delivery_slow`` after the limit, like a message that no delivery claimed
  (report.md:836-844). The messages and their deliveries come from the real inbox hook.
"""

from __future__ import annotations

from typing import Any

from test_credits_inbox import Live, live, st, started
from test_credits_monitor_duties import _keys, _scan
from test_credits_state import at

__all__ = ["live", "st"]

DELIVERY = 1800
#: The fires of ``test_three_emits_without_a_confirm_set_failed``: three emits, then failed.
FAIL_FIRES = (0, 10, 70, 80, 140, 150, 210, 220, 280)


def _alive(live: Live, now: int) -> dict[str, Any]:
    return {
        live.segment: {
            "pid_alive": True,
            "slept": False,
            "transcript_mtime_utc": at(now),
        }
    }


def _failed(live: Live) -> str:
    """A message that the hook emitted three times with no confirm; its delivery is failed."""
    started(live)
    msg_id = live.send("info", "fixture context", 0)
    for seconds in FAIL_FIRES:
        live.fire(seconds)
    row = live.delivery(msg_id)
    assert row is not None and row["failed_utc"] is not None, row
    assert row["confirmed_utc"] is None, row
    return msg_id


def test_r2_f1_failed_delivery_is_slow_at_the_limit(live: Live) -> None:
    """R2-F1: a failed delivery files ``delivery_slow`` at the limit, not one second before."""
    msg_id = _failed(live)
    _scan(live.st, DELIVERY - 1, _alive(live, DELIVERY - 1))
    assert _keys(live.st, "delivery_slow") == []
    _scan(live.st, DELIVERY, _alive(live, DELIVERY))
    assert _keys(live.st, "delivery_slow") == [f"delivery_slow:{msg_id}"]


def test_r2_f1_failed_delivery_is_filed_once(live: Live) -> None:
    """R2-F1: a second scan files no duplicate, and the failed delivery is no ``no_ack``."""
    msg_id = _failed(live)
    _scan(live.st, 2000, _alive(live, 2000))
    _scan(live.st, 2600, _alive(live, 2600))
    assert _keys(live.st, "delivery_slow") == [f"delivery_slow:{msg_id}"]
    assert _keys(live.st, "no_ack") == []


def test_r2_f1_unconfirmed_delivery_is_slow_at_the_limit(live: Live) -> None:
    """R2-F1: one emit with no confirm and no later fire is slow at the limit too."""
    started(live)
    msg_id = live.send("info", "fixture context", 0)
    assert live.fire(2).emitted() == [msg_id]
    row = live.delivery(msg_id)
    assert (
        row is not None and row["confirmed_utc"] is None and row["failed_utc"] is None
    )
    _scan(live.st, DELIVERY - 1, _alive(live, DELIVERY - 1))
    assert _keys(live.st, "delivery_slow") == []
    _scan(live.st, DELIVERY, _alive(live, DELIVERY))
    assert _keys(live.st, "delivery_slow") == [f"delivery_slow:{msg_id}"]


def test_r2_f1_confirmed_delivery_is_not_slow(live: Live) -> None:
    """R2-F1: a delivery that the transcript confirmed is never ``delivery_slow``."""
    started(live)
    msg_id = live.send("info", "fixture context", 0)
    assert live.fire(2).emitted() == [msg_id]
    live.note(msg_id, 3.5)
    assert live.fire(10).emitted() == []
    row = live.delivery(msg_id)
    assert row is not None and row["confirmed_utc"] == at(10)
    _scan(live.st, 2000, _alive(live, 2000))
    assert _keys(live.st, "delivery_slow") == []
