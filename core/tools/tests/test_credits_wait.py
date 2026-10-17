"""S6b the wait and the gate deadline (Component I, AC-I.3).

Plan: docs/execution/plans/2026-10-15-scheduled-credits-runs (Component I,
AC-I.3; the Constant Classification rows ``WAIT_RETURN_MAX_S`` and
``GATE_DEADLINE_MARGIN_MIN`` and the wait-seam table; report R§4.6.3 step 7
and "Expiry", R§4.6.5; acceptance matrix MX-14 and MX-17).

AC-I.3 ``wait`` returns within ``WAIT_RETURN_MAX_S`` (540 s). The gate deadline
  is min(``gate_wait_max_min``, segment deadline − ``GATE_DEADLINE_MARGIN_MIN``
  (15 min)). Expiry is a compare-and-set: a ruling and the expiry at the same
  instant → one wins, and the other gets ``gate_closed`` with one
  ``credits_limit_tripped`` WARN record.

The tests fix this contract (names the design does not give are marked
"chosen"; the nearest section is in brackets):

* ``credits_msg.py wait --max-wait-ms <ms> --poll-ms <ms>``: the seams of the
  wait-seam table. The code uses min(value, 540000), so a seam only lowers the
  cap (plan R2 C1).
* ``CREDITS_TEST_CLOCK_STEP_MS``: each poll moves the injected store clock on
  by this many ms, so the cap case passes 540 s of store time with no
  real-duration wait (chosen; the wait-seam table says "advances the injected
  clock past 540 s" and names no surface) [plan Constant Classification].
* The status is the ``status`` of the one JSON object on stdout, or the first
  word of the one status line (R§4.6.5 "prints one status line only").
* The WARN record is one JSON line on stderr with ``event``
  ``credits_limit_tripped``, ``level`` ``WARN`` and ``window``
  ``gate_deadline`` (chosen: the Python tools log JSON lines to stderr through
  ``credits_state.log``; the field names follow the PowerShell WARN records)
  [plan Constant Classification, ``GATE_DEADLINE_MARGIN_MIN``].
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from test_credits_ruling import (
    CALL_TIMEOUT,
    HOOK,
    MSG_TOOL,
    ROOT,
    UNVERIFIED_RE,
    Out,
    Rr,
    assert_verified,
    at,
    frames,
    make_run,
    open_flow,
    parse_out,
)
from test_credits_state import REAL_DB_STATE_AT_IMPORT, real_db_state
from test_credits_inbox import Fire

SEAMS = ("--max-wait-ms", "200", "--poll-ms", "20")
# A fast wait call may not take longer than this (no real-duration wait).
FAST_S = 10.0


def status(out: Out) -> str:
    """The wait status: the JSON ``status``, or the first word of the status line."""
    if out.payload is not None and isinstance(out.payload.get("status"), str):
        return str(out.payload["status"])
    words = out.stdout.strip().split()
    return words[0] if words else ""


def remaining(out: Out) -> int | None:
    """``remaining_s`` of the JSON form, or ``remaining=<n>s`` of the status line."""
    if out.payload is not None and "remaining_s" in out.payload:
        return int(out.payload["remaining_s"])
    for word in out.stdout.split():
        if word.startswith("remaining=") and word.endswith("s"):
            return int(word[len("remaining=") : -1])
    return None


def warns(*texts: str) -> list[dict[str, Any]]:
    """The ``credits_limit_tripped`` WARN records of the gate deadline in the streams."""
    found: list[dict[str, Any]] = []
    for text in texts:
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                isinstance(record, dict)
                and record.get("event") == "credits_limit_tripped"
                and str(record.get("level", "")).upper() == "WARN"
                and record.get("window") == "gate_deadline"
            ):
                found.append(record)
    return found


def timed_wait(
    rr: Rr, seconds: int, *flags: str, extra: dict[str, str] | None = None
) -> tuple[Out, float]:
    began = time.monotonic()
    out = rr.msg("wait", *flags, seconds=seconds, extra=extra)
    return out, time.monotonic() - began


# --- AC-I.3: the seams and the statuses ---------------------------------------------------


def test_ac_i3_wait_with_the_seams_returns_wait_timeout_at_once(tmp_path: Path) -> None:
    """AC-I.3: ``--max-wait-ms 200 --poll-ms 20`` → WAIT_TIMEOUT well inside a second."""
    rr, _, gate_id = open_flow(tmp_path)
    out, took = timed_wait(rr, 60, *SEAMS)
    assert out.code == 0, out.show()
    assert status(out) == "WAIT_TIMEOUT", out.show()
    assert remaining(out) in (1789, 1790), out.show()
    assert took < FAST_S, took
    assert rr.gate(gate_id)["state"] == "open"


def test_ac_i3_wait_returns_message_waiting_for_a_pending_message(
    tmp_path: Path,
) -> None:
    """AC-I.3 (R§4.6.5): a message for this segment ends the wait."""
    rr, _, _ = open_flow(tmp_path)
    sent = rr.store(
        "send", "--run-id", rr.run_id, "--kind", "info", "--body", "fyi", seconds=55
    )
    assert sent.code == 0, sent.show()
    out, took = timed_wait(rr, 60, *SEAMS)
    assert out.code == 0, out.show()
    assert status(out) == "MESSAGE_WAITING", out.show()
    assert took < FAST_S, took


def test_ac_i3_wait_without_an_open_gate_returns_gate_closed(tmp_path: Path) -> None:
    """AC-I.3 (R§4.6.5): no open gate → GATE_CLOSED."""
    rr = make_run(tmp_path)
    out, took = timed_wait(rr, 60, *SEAMS)
    assert out.code == 0, out.show()
    assert status(out) == "GATE_CLOSED", out.show()
    assert took < FAST_S, took


def test_ac_i3_wait_cap_holds_when_the_seam_asks_for_more(tmp_path: Path) -> None:
    """AC-I.3: ``--max-wait-ms 999999999`` → min(value, 540000); the clock passes 540 s."""
    rr = make_run(tmp_path, wait=120)
    gate_id = rr.decision(50)
    assert rr.gate(gate_id)["deadline_utc"] == at(50 + 120 * 60)
    out, took = timed_wait(
        rr,
        60,
        "--max-wait-ms",
        "999999999",
        "--poll-ms",
        "20",
        extra={"CREDITS_TEST_CLOCK_STEP_MS": "60000"},
    )
    assert out.code == 0, out.show()
    assert status(out) == "WAIT_TIMEOUT", out.show()
    left = remaining(out)
    assert left is not None, out.show()
    # The wait ended at the cap (540 s of store time), not at the gate deadline.
    assert 7190 - 600 <= left <= 7190 - 540, out.show()
    assert took < CALL_TIMEOUT, took
    assert rr.gate(gate_id)["state"] == "open"


@pytest.mark.parametrize(
    ("opened", "deadline"),
    [
        (100, 100 + 40 * 60),  # gate_wait_max_min is the earlier end
        (1000, 7 + 3600 - 15 * 60),  # segment deadline − 15 min is the earlier end
    ],
)
def test_ac_i3_gate_deadline_is_the_earlier_of_the_wait_and_the_segment_margin(
    tmp_path: Path, opened: int, deadline: int
) -> None:
    """AC-I.3: deadline = min(opened + gate_wait_max_min, segment deadline − 15 min)."""
    rr = make_run(tmp_path, wait=40, timeout=3600)
    gate_id = rr.decision(opened)
    assert rr.gate(gate_id)["deadline_utc"] == at(deadline)


# --- MX-14: the wait reaches its deadline ---------------------------------------------


def test_mx_14_wait_at_the_deadline_expires_the_gate(tmp_path: Path) -> None:
    """AC-I.3 / MX-14: deadline − 1 s → open; at the deadline → GATE_EXPIRED, one event."""
    rr, _, gate_id = open_flow(tmp_path)
    deadline = 50 + 30 * 60
    before, took = timed_wait(rr, deadline - 1, *SEAMS)
    assert before.code == 0, before.show()
    assert status(before) == "WAIT_TIMEOUT", before.show()
    assert took < FAST_S, took
    assert rr.gate(gate_id)["state"] == "open"
    expired, took = timed_wait(rr, deadline, *SEAMS)
    assert expired.code == 0, expired.show()
    assert status(expired) == "GATE_EXPIRED", expired.show()
    assert took < FAST_S, took
    assert rr.gate(gate_id)["state"] == "expired"
    assert rr.events(f"gate_expired:{gate_id}") == 1
    after, _ = timed_wait(rr, deadline + 1, *SEAMS)
    assert status(after) == "GATE_CLOSED", after.show()
    assert rr.events(f"gate_expired:{gate_id}") == 1


# --- MX-17: the race and the late ruling ------------------------------------------------


def popen(
    argv: list[str], env: dict[str, str], stdin: str | None
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        argv,
        stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=ROOT,
    )


def hook_payload(rr: Rr) -> str:
    return json.dumps(
        {
            "session_id": rr.seg.session,
            "transcript_path": str(rr.st.root / "segment-transcript.jsonl"),
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
    )


@pytest.mark.parametrize("round_no", [1, 2, 3])
def test_mx_17_ruling_and_expiry_race_and_one_wins(
    tmp_path: Path, round_no: int
) -> None:
    """AC-I.3 / MX-17: one wins; the other gets gate_closed and one WARN record."""
    rr, tr, gate_id = open_flow(tmp_path / f"round-{round_no}")
    deadline = 50 + 30 * 60
    uid = tr.user("D-1: A", 60)
    msg_id = rr.relay(70, gate_id=gate_id, quote="D-1: A", uid=uid)
    hook = popen(
        [sys.executable, "-X", "utf8", str(HOOK)],
        rr.run_env(deadline - 1),
        hook_payload(rr),
    )
    waiter = popen(
        [
            sys.executable,
            "-X",
            "utf8",
            str(MSG_TOOL),
            "--now-utc",
            at(deadline),
            "wait",
            *SEAMS,
        ],
        rr.run_env(deadline),
        None,
    )
    hook_out, hook_err = hook.communicate(hook_payload(rr), timeout=CALL_TIMEOUT)
    wait_out, wait_err = waiter.communicate(timeout=CALL_TIMEOUT)
    fire = Fire(hook.returncode, hook_out, hook_err)
    waited = parse_out(waiter.returncode, wait_out, wait_err)
    assert fire.code == 0, fire.show()
    assert waited.code == 0, waited.show()
    state = rr.gate(gate_id)["state"]
    if state == "expired":
        assert status(waited) == "GATE_EXPIRED", waited.show()
        found = frames(fire)
        assert msg_id in found, fire.show()
        kind, text = found[msg_id]
        assert kind == "info", text
        match = UNVERIFIED_RE.search(text)
        assert match is not None and match.group(1) == "gate_closed", text
        assert rr.consumed() == []
    else:
        assert state in ("closed", "resolved"), state
        assert status(waited) == "GATE_CLOSED", waited.show()
        assert_verified(rr, fire, msg_id, gate_id=gate_id, uid=uid, quote="D-1: A")
        assert rr.events(f"gate_expired:{gate_id}") == 0
    assert len(warns(hook_err, wait_err)) == 1, (hook_err, wait_err)


def test_mx_17_late_ruling_without_a_wait_fails_gate_closed_with_one_warn(
    tmp_path: Path,
) -> None:
    """AC-I.3 / MX-17 (R§4.6.3 "Expiry"): no wait expired the gate; step 7 still fails."""
    rr, tr, gate_id = open_flow(tmp_path)
    uid = tr.user("D-1: A", 60)
    deadline = 50 + 30 * 60
    msg_id = rr.relay(deadline + 10, gate_id=gate_id, quote="D-1: A", uid=uid)
    fire = rr.fire(deadline + 20)
    found = frames(fire)
    assert msg_id in found, fire.show()
    kind, text = found[msg_id]
    assert kind == "info", text
    match = UNVERIFIED_RE.search(text)
    assert match is not None and match.group(1) == "gate_closed", text
    assert rr.gate(gate_id)["state"] in ("open", "expired")
    assert rr.consumed() == []
    assert len(warns(fire.stderr)) == 1, fire.stderr


def test_real_store_unchanged() -> None:
    """AC-B.10: no S6b test touches the live store."""
    assert real_db_state() == REAL_DB_STATE_AT_IMPORT
