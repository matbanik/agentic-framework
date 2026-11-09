"""Execution review round 1 of docs/execution/plans/2026-11-05-pe21-credits-authority (EA-14).

Each test is the failing regression of one review finding, written before its fix:

* R1-F1 (AC-895.3): ``authority --quote`` compares a monitor-chain start with the chain quote.
* R1-F2 (AC-895.3): ``authority --quote-b64`` carries words that no shell quoting keeps whole.
* R1-F3 (AC-895.11): after a recorded removal, a run still bound to its removed executor tree
  continues in the main tree, and the binding moves to the main tree.
* R1-F4 (AC-895.8): message delivery is reconciled for the current segment only.
* R1-F5 (AC-895.8): a live segment with no transcript file counts its silence from its start.
* R1-F6 (AC-895.6): the estimate of a segment ends where the next segment of the run starts.
* R1-F7 (AC-895.8): a closed decision notice is never sent or retried.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest

from test_credits_authority import agent, authority, chain_manifest, start
from test_credits_launch_fixes import (
    PHASE_RUN,
    _iso_ms,
    _killed,
    _msg,
    _phase_fixture,
    _reconcile,
    _removal,
    _tree_run,
    _usage_record,
)
from test_credits_monitor_duties import (
    RUN,
    _delivery,
    _event,
    _gate_payload,
    _keys,
    _scan,
    _send,
)
from test_credits_state import (
    Store,
    at,
    finish,
    first_start,
    make_registered,
    start_segment,
    stop,
)

HANG = 3600
DELIVERY = 1800
CHAIN_QUOTE = "run the fixture chain"
#: Words with every character that a double-quoted bash or PowerShell argument changes.
SHELL_WORDS = 'Start the "quoted" fixture, don\'t stop: $HOME `date` \\ ! now.'


@pytest.fixture
def st(tmp_path: Path) -> Store:
    store = Store(tmp_path / "store")
    store.root.mkdir()
    store.init()
    return store


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _chain_start(st: Store, run_id: str) -> str:
    """A registered chain run with one launched monitor-chain segment; returns its id."""
    manifest = chain_manifest(st, run_id)
    st.ok(
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
    st.ok("registered", "--run-id", run_id, "--task-hash", f"taskhash-{run_id}")
    seg = start(
        st,
        run_id,
        1,
        now=0,
        request=("--started-by", "monitor-chain", "--chain-id", "chain-1"),
    )
    return seg.segment_id


# --- R1-F1 ------------------------------------------------------------------------------------


def test_r1_f1_chain_start_checks_the_chain_quote(st: Store) -> None:
    """R1-F1: the chain quote is the words of a chain start; --quote matches it."""
    segment_id = _chain_start(st, "run-c")
    out = authority(st, "run-c", segment_id, "--quote", CHAIN_QUOTE)
    assert out.code == 0 and out.result == "ok", out.show()
    payload = out.payload or {}
    assert payload["quote_checked"] is True
    assert payload["source_check"] == "chain_verified"


def test_r1_f1_chain_start_refuses_other_words(st: Store) -> None:
    """R1-F1 negative: words that are not the chain quote are refused."""
    segment_id = _chain_start(st, "run-c")
    out = authority(st, "run-c", segment_id, "--quote", "run some other chain")
    assert out.code == 3 and out.error == "authority_quote_mismatch", out.show()


# --- R1-F2 ------------------------------------------------------------------------------------


def test_r1_f2_quote_b64_matches_the_recorded_words(st: Store) -> None:
    """R1-F2: the base64 form gives the exact words, quotes and shell characters included."""
    make_registered(st, "run-q")
    seg = start(st, "run-q", 1, now=0, request=agent(SHELL_WORDS))
    out = authority(st, "run-q", seg.segment_id, "--quote-b64", _b64(SHELL_WORDS))
    assert out.code == 0 and out.result == "ok", out.show()
    payload = out.payload or {}
    assert payload["quote"] == SHELL_WORDS
    assert payload["quote_checked"] is True


def test_r1_f2_quote_b64_of_other_words_is_refused(st: Store) -> None:
    """R1-F2 negative: decoded words that differ are a mismatch, as with --quote."""
    make_registered(st, "run-q")
    seg = start(st, "run-q", 1, now=0, request=agent(SHELL_WORDS))
    out = authority(st, "run-q", seg.segment_id, "--quote-b64", _b64("other words"))
    assert out.code == 3 and out.error == "authority_quote_mismatch", out.show()


@pytest.mark.parametrize("raw", ["not base64!", _b64("AB")[:-1], "//4="])
def test_r1_f2_bad_quote_b64_is_a_usage_error(st: Store, raw: str) -> None:
    """R1-F2 negative: text that is not base64 of UTF-8 words is a usage error, exit 2."""
    make_registered(st, "run-q")
    seg = start(st, "run-q", 1, now=0, request=agent("A"))
    out = authority(st, "run-q", seg.segment_id, "--quote-b64", raw)
    assert out.code == 2 and out.error == "usage", out.show()


def test_r1_f2_quote_and_quote_b64_together_is_a_usage_error(st: Store) -> None:
    """R1-F2 negative: one form of the words at a time."""
    make_registered(st, "run-q")
    seg = start(st, "run-q", 1, now=0, request=agent("A"))
    out = authority(
        st, "run-q", seg.segment_id, "--quote", "A", "--quote-b64", _b64("A")
    )
    assert out.code == 2 and out.error == "usage", out.show()


# --- R1-F3 ------------------------------------------------------------------------------------


def test_r1_f3_removed_executor_binding_moves_to_the_main_tree(
    st: Store, tmp_path: Path
) -> None:
    """R1-F3: a run bound to its removed executor tree continues in the main tree."""
    fx = _phase_fixture(tmp_path)
    _removal(fx, PHASE_RUN)
    seg, config, head = _tree_run(st, fx)
    first = _msg(
        st,
        fx,
        PHASE_RUN,
        seg.segment_id,
        config,
        "tree",
        str(fx.repo),
        now=20,
        base=head,
    )
    assert first.code == 0, first.show()
    # The state of a run whose earlier segment worked in the executor tree, now removed.
    removed = str(tmp_path / "removed-executor")
    st.write("UPDATE runs SET active_tree = ? WHERE run_id = ?", (removed, PHASE_RUN))
    resumed = _msg(
        st,
        fx,
        PHASE_RUN,
        seg.segment_id,
        config,
        "tree",
        str(fx.repo),
        now=30,
        base=head,
    )
    assert resumed.code == 0, resumed.show()
    assert (resumed.payload or {}).get("tree_kind") == "main_after_removal"
    bound = st.one("SELECT active_tree FROM runs WHERE run_id = ?", (PHASE_RUN,))
    assert Path(str(bound)).resolve() == fx.repo.resolve()


def test_r1_f3_removal_needs_the_recorded_main_tree(st: Store, tmp_path: Path) -> None:
    """R1-F3 negative: the main tree must still be the run's recorded main tree."""
    fx = _phase_fixture(tmp_path)
    _removal(fx, PHASE_RUN)
    seg, config, head = _tree_run(st, fx)
    first = _msg(
        st,
        fx,
        PHASE_RUN,
        seg.segment_id,
        config,
        "tree",
        str(fx.repo),
        now=20,
        base=head,
    )
    assert first.code == 0, first.show()
    other = str(tmp_path / "other-main")
    st.write(
        "UPDATE runs SET active_tree = ?, main_tree = ? WHERE run_id = ?",
        (str(tmp_path / "removed-executor"), other, PHASE_RUN),
    )
    out = _msg(
        st,
        fx,
        PHASE_RUN,
        seg.segment_id,
        config,
        "tree",
        str(fx.repo),
        now=30,
        base=head,
    )
    assert out.code == 3 and out.error == "active_tree_mismatch", out.show()


# --- R1-F4 ------------------------------------------------------------------------------------


def _resumed(st: Store) -> tuple[str, Any]:
    """Segment 1 confirms one message and stops before its ack; segment 2 resumes at 200."""
    seg = first_start(st, RUN)
    message = _send(st, 100)
    _delivery(st, message, seg, 110, fires=0)
    finish(st, seg, now=120, total=1.0)
    stop(st, RUN, now=121)
    current = start_segment(st, RUN, 2, now=200, session=seg.session, resume=True)
    return message, current


def _live(segment_id: str, now: int) -> dict[str, Any]:
    return {
        segment_id: {"pid_alive": True, "slept": False, "transcript_mtime_utc": at(now)}
    }


def test_r1_f4_old_delivery_does_not_hide_an_unclaimed_resume_message(
    st: Store,
) -> None:
    """R1-F4: segment 2 never claimed the message, so it is slow after the limit."""
    message, current = _resumed(st)
    _scan(st, 2100, _live(current.segment_id, 2100))
    assert _keys(st, "delivery_slow") == [f"delivery_slow:{message}"]


def test_r1_f4_resume_message_is_slow_only_after_the_limit(st: Store) -> None:
    """R1-F4: the limit counts from the start of the current segment, one second under is quiet."""
    message, current = _resumed(st)
    started = int(
        st.one(
            "SELECT CAST(strftime('%s', created_utc) AS INTEGER) - CAST(strftime('%s', ?) AS INTEGER)"
            " FROM segments WHERE segment_id = ?",
            (at(0), current.segment_id),
        )
    )
    _scan(st, started + DELIVERY - 1, _live(current.segment_id, started + DELIVERY - 1))
    assert _keys(st, "delivery_slow") == []
    _scan(st, started + DELIVERY, _live(current.segment_id, started + DELIVERY))
    assert _keys(st, "delivery_slow") == [f"delivery_slow:{message}"]


def test_r1_f4_current_delivery_is_not_slow(st: Store) -> None:
    """R1-F4: a delivery that segment 2 claimed counts; the message is not slow."""
    message, current = _resumed(st)
    _delivery(st, message, current, 220, fires=0)
    _scan(st, 2100, _live(current.segment_id, 2100))
    assert _keys(st, "delivery_slow") == []
    assert _keys(st, "no_ack") == []


# --- R1-F5 ------------------------------------------------------------------------------------


def _started(st: Store, segment_id: str) -> int:
    """The seconds from ``at(0)`` to the launching -> running transition of the segment."""
    return int(
        st.one(
            "SELECT CAST(strftime('%s', at_utc) AS INTEGER) - CAST(strftime('%s', ?) AS INTEGER)"
            " FROM transitions WHERE entity = 'segment' AND entity_id = ?"
            " AND from_state = 'launching' AND to_state = 'running'",
            (at(0), segment_id),
        )
    )


def _no_transcript(segment_id: str) -> dict[str, Any]:
    return {
        segment_id: {"pid_alive": True, "slept": False, "transcript_mtime_utc": None}
    }


def test_r1_f5_no_transcript_is_a_hang_at_the_limit_from_the_start(st: Store) -> None:
    """R1-F5: with no transcript file, silence counts from the segment's start."""
    seg = first_start(st, RUN)
    began = _started(st, seg.segment_id)
    _scan(st, began + HANG - 1, _no_transcript(seg.segment_id))
    assert _keys(st, "possible_hang") == []
    _scan(st, began + HANG, _no_transcript(seg.segment_id))
    assert _keys(st, "possible_hang") == [f"possible_hang:{seg.segment_id}"]
    _scan(st, began + HANG + 60, _no_transcript(seg.segment_id))
    assert _keys(st, "possible_hang") == [f"possible_hang:{seg.segment_id}"]


def test_r1_f5_no_transcript_hang_never_stops_the_segment(st: Store) -> None:
    """R1-F5: the notice is a notice; the segment and the run stay running."""
    seg = first_start(st, RUN)
    _scan(st, 7200, _no_transcript(seg.segment_id))
    assert (
        st.one("SELECT state FROM segments WHERE segment_id = ?", (seg.segment_id,))
        == "running"
    )
    assert st.one("SELECT state FROM runs WHERE run_id = ?", (RUN,)) == "running"


def test_r1_f5_resume_counts_from_its_own_start(st: Store) -> None:
    """R1-F5 sibling: a resumed session's old transcript write is not silence of the new one."""
    seg = first_start(st, RUN)
    finish(st, seg, now=120, total=1.0)
    stop(st, RUN, now=121)
    current = start_segment(st, RUN, 2, now=5000, session=seg.session, resume=True)
    began = _started(st, current.segment_id)
    old_write = {
        current.segment_id: {
            "pid_alive": True,
            "slept": False,
            "transcript_mtime_utc": at(100),
        }
    }
    _scan(st, began + HANG - 1, old_write)
    assert _keys(st, "possible_hang") == []
    _scan(st, began + HANG, old_write)
    assert _keys(st, "possible_hang") == [f"possible_hang:{current.segment_id}"]


# --- R1-F6 ------------------------------------------------------------------------------------


def test_r1_f6_earlier_segment_excludes_later_resume_usage(
    st: Store, tmp_path: Path
) -> None:
    """R1-F6: usage after the next segment's start is not the earlier segment's."""
    seg, transcript, registry = _killed(st, tmp_path)
    before = _reconcile(st, seg, transcript, registry, now=45)
    assert before.code == 0, before.show()
    stop(st, seg.run_id, now=46)
    later = start_segment(st, seg.run_id, 2, now=50, session=seg.session, resume=True)
    finish(st, later, now=80, cls="exited")
    record = _usage_record(
        "msg-later", _iso_ms(65), {"input_tokens": 1000000}, seg.session
    )
    with transcript.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
    after = _reconcile(st, seg, transcript, registry, now=90)
    assert after.code == 0, after.show()
    assert after.payload is not None and before.payload is not None
    assert after.payload["cost_estimate_usd"] == before.payload["cost_estimate_usd"]
    assert after.payload["messages"] == before.payload["messages"]


def test_r1_f6_later_segment_counts_its_own_usage(st: Store, tmp_path: Path) -> None:
    """R1-F6: the later segment's estimate takes the usage from its own start on."""
    seg, transcript, registry = _killed(st, tmp_path)
    stop(st, seg.run_id, now=46)
    later = start_segment(st, seg.run_id, 2, now=50, session=seg.session, resume=True)
    finish(st, later, now=80, cls="exited")
    record = _usage_record(
        "msg-later", _iso_ms(65), {"input_tokens": 1000000}, seg.session
    )
    with transcript.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
    out = _reconcile(st, later, transcript, registry, now=90)
    assert out.code == 0, out.show()
    assert out.payload is not None and out.payload["messages"] == 1


# --- R1-F7 ------------------------------------------------------------------------------------


def _decision(st: Store, gate: str, now: int) -> str:
    key = f"decision:{gate}"
    _event(st, "decision", key, _gate_payload(key, "decision", gate, now), now)
    st.ok("outbox_scan", now=now + 1)
    return key


def _due(st: Store, now: int) -> list[str]:
    notices = st.ok("notices_due", now=now, expect=("no_change",))["notices"]
    return [str(n["kind"]) for n in notices]


def _decision_key(st: Store, gate: str) -> str:
    for key, body in st.rows(
        "SELECT notice_key, body_json FROM notices WHERE kind = 'decision'"
    ):
        if json.loads(str(body)).get("semantic_key") == f"decision:{gate}":
            return str(key)
    raise AssertionError(f"no decision notice for {gate}")


def test_r1_f7_resolved_before_the_first_send_is_not_due(st: Store) -> None:
    """R1-F7: a decision resolved before its first send is not sent; the result is."""
    first_start(st, RUN)
    _decision(st, "gate-A", 20)
    key = "decision_resolved:gate-A"
    _event(
        st,
        "decision_resolved",
        key,
        _gate_payload(key, "decision_resolved", "gate-A", 30),
        30,
    )
    st.ok("outbox_scan", now=31)
    assert _due(st, 32) == ["decision_resolved"]


def test_r1_f7_expired_before_the_first_send_is_not_due(st: Store) -> None:
    """R1-F7: a decision whose gate expired before its first send is not sent."""
    first_start(st, RUN)
    _decision(st, "gate-B", 20)
    _event(
        st, "gate_expired", "gate_expired:gate-B", {"segment_id": f"seg-{RUN}-1"}, 30
    )
    st.ok("outbox_scan", now=31)
    assert _due(st, 32) == ["gate_expired"]


def test_r1_f7_closed_after_a_failed_send_is_not_retried(st: Store) -> None:
    """R1-F7: a decision in retry after a failed send stops when it closes."""
    first_start(st, RUN)
    _decision(st, "gate-C", 20)
    decision = _decision_key(st, "gate-C")
    st.ok("notice_failed", "--key", decision, "--error", "smtp down", now=22)
    assert _due(st, 23) == ["decision"]
    key = "decision_resolved:gate-C"
    _event(
        st,
        "decision_resolved",
        key,
        _gate_payload(key, "decision_resolved", "gate-C", 30),
        30,
    )
    st.ok("outbox_scan", now=31)
    assert _due(st, 32) == ["decision_resolved"]
    # The closed notice keeps its row and its record of the failed send.
    state, attempts, closed = st.rows(
        "SELECT state, attempts, closed_utc FROM notices WHERE notice_key = ?",
        (decision,),
    )[0]
    assert (state, attempts, closed) == ("retry", 1, at(31))
