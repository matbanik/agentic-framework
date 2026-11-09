"""Execution review round 3 of docs/execution/plans/2026-11-05-pe21-credits-authority (EA-15).

Each test is the failing regression of one review finding, written before its fix:

* R3-F1 (AC-895.8): a message that the transcript confirmed and that has no ack files
  ``no_ack`` after 3 more fires and 10 minutes (report.md:1250-1253). The inbox hook must
  count the fires after the confirm; the fire that confirmed the message is not one. The
  messages, the deliveries and the fires come from the real inbox hook.
"""

from __future__ import annotations

from typing import Any

from test_credits_inbox import Live, live, st, started
from test_credits_monitor_duties import _keys, _scan
from test_credits_state import at

__all__ = ["live", "st"]

#: The fire that confirms the message (its transcript sighting is at 3.5 s).
CONFIRM = 10
#: ``no_ack`` waits 10 minutes from the confirm.
NO_ACK_AFTER = 600


def _alive(live: Live, now: int) -> dict[str, Any]:
    return {
        live.segment: {
            "pid_alive": True,
            "slept": False,
            "transcript_mtime_utc": at(now),
        }
    }


def _confirmed(live: Live) -> str:
    """A message that the hook emitted at 2 s and confirmed at the fire of 10 s."""
    started(live)
    msg_id = live.send("info", "fixture context", 0)
    assert live.fire(2).emitted() == [msg_id]
    live.note(msg_id, 3.5)
    assert live.fire(CONFIRM).emitted() == []
    row = live.delivery(msg_id)
    assert row is not None and row["confirmed_utc"] == at(CONFIRM), row
    return msg_id


def _open_unacked(live: Live, msg_id: str) -> None:
    message = live.message(msg_id)
    assert message["state"] == "open" and message["acked_utc"] is None, message


def test_r3_f1_confirmed_message_files_no_ack(live: Live) -> None:
    """R3-F1: three fires after the confirm and ten minutes file ``no_ack`` for a live run."""
    msg_id = _confirmed(live)
    for seconds in (20, 30, 620):
        assert live.fire(seconds).emitted() == []
    _open_unacked(live, msg_id)
    _scan(live.st, 620, _alive(live, 620))
    assert _keys(live.st, "no_ack") == [f"no_ack:{msg_id}"]


def test_r3_f1_two_later_fires_are_not_enough(live: Live) -> None:
    """R3-F1: the confirming fire is not one of the three; two later fires file nothing."""
    msg_id = _confirmed(live)
    for seconds in (20, 620):
        live.fire(seconds)
    _open_unacked(live, msg_id)
    _scan(live.st, 620, _alive(live, 620))
    assert _keys(live.st, "no_ack") == []


def test_r3_f1_ten_minutes_from_the_confirm(live: Live) -> None:
    """R3-F1: with three later fires, ``no_ack`` waits ten minutes from the confirm."""
    msg_id = _confirmed(live)
    for seconds in (20, 30, 40):
        live.fire(seconds)
    _scan(live.st, CONFIRM + NO_ACK_AFTER - 1, _alive(live, CONFIRM + NO_ACK_AFTER - 1))
    assert _keys(live.st, "no_ack") == []
    _scan(live.st, CONFIRM + NO_ACK_AFTER, _alive(live, CONFIRM + NO_ACK_AFTER))
    assert _keys(live.st, "no_ack") == [f"no_ack:{msg_id}"]


def test_r3_f1_no_ack_is_filed_once(live: Live) -> None:
    """R3-F1: more fires and a second scan file no duplicate notice."""
    msg_id = _confirmed(live)
    for seconds in (20, 30, 620):
        live.fire(seconds)
    _scan(live.st, 620, _alive(live, 620))
    for seconds in (630, 640):
        live.fire(seconds)
    _scan(live.st, 700, _alive(live, 700))
    assert _keys(live.st, "no_ack") == [f"no_ack:{msg_id}"]


def test_r3_f1_an_ack_stops_no_ack(live: Live) -> None:
    """R3-F1: an ack after the confirm stops the notice, whatever the later fires."""
    msg_id = _confirmed(live)
    ack = live.msg("ack", msg_id, "noted", seconds=15)
    assert ack.code == 0, ack.show()
    for seconds in (20, 30, 620):
        live.fire(seconds)
    _scan(live.st, 620, _alive(live, 620))
    assert _keys(live.st, "no_ack") == []
