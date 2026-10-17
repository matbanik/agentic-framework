"""EA-90 start authority: ``tools/credits_msg.py authority`` (D-14 B).

Plan: docs/execution/plans/2026-10-15-scheduled-credits-runs (EA-89 finding,
EA-90 fix; report R§4.2 start request, R§5.3 resume, D-1 B start source).

A headless run cannot see the human's chat. The human's start or resume words
reach it as the start request that ``Start-CreditsRunTask.ps1`` filed and the
launcher consumed. These tests fix the contract of the read-only verb that
shows that record to the run:

* ``python tools/credits_msg.py authority [--quote <words>]`` reads
  ``CREDITS_RUN_ID``, ``CREDITS_SEGMENT`` and ``CREDITS_STATE_DB`` (the
  launcher sets them; a missing one is a usage error, exit 2). It reads no
  config.
* It opens the store read-only (``mode=ro``) and writes nothing: every table
  and the database file bytes are the same after the call.
* It follows segment → attempt → request. On success (exit 0) stdout has
  ``result: ok``, ``authorized: true`` and the record: ``run_id``,
  ``segment_id``, ``segment_ordinal``, ``request_id``, ``request_state``,
  ``attempt_id``, ``dispatch_id``, ``started_by``, ``quote``,
  ``requested_by``, ``chain`` (``chain_id``, ``quote``, ``given_at`` of the
  manifest chain, for ``monitor-chain``; else null), ``resume``,
  ``resume_mode``, ``brief``, ``requested_utc`` and ``quote_checked``.
* ``--quote`` compares the given words with the recorded quote after the
  ruling verifier's normalization (NFC, CRLF to LF, trim, one space per
  whitespace run).
* Refusals exit 3 with ``error``: ``unknown_segment``,
  ``authority_no_request``, ``authority_link_mismatch``,
  ``authority_not_launched``, ``authority_segment_ended``,
  ``authority_no_quote``, ``authority_quote_mismatch``, plus the shared
  ``store_missing`` and ``schema_mismatch``.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from test_credits_state import (
    ROOT,
    SESSION_A,
    SESSION_B,
    Out,
    Seg,
    Store,
    accept_args,
    at,
    child_env,
    dump,
    finish,
    launched_args,
    make_registered,
    minimal_args,
    parse_out,
    stop,
    write_manifest,
)

MSG_TOOL = ROOT / "tools" / "credits_msg.py"


@pytest.fixture
def st(tmp_path: Path) -> Store:
    store = Store(tmp_path / "store")
    store.root.mkdir()
    store.init()
    return store


def start(
    st: Store,
    run_id: str,
    n: int,
    *,
    now: int,
    request: tuple[str, ...],
    session: str = SESSION_A,
    launch: bool = True,
) -> Seg:
    """File request ``n`` with the given flags, then accept, admit and launch it."""
    request_id = f"req-{run_id}-{n}"
    st.ok("request", "--run-id", run_id, "--request-id", request_id, *request, now=now)
    accepted = st.ok("accept", *accept_args(run_id, n, session), now=now + 5)
    assert accepted.get("outcome") == "accepted", accepted
    segment_id = f"seg-{run_id}-{n}"
    admitted = st.ok(
        "admit",
        "--attempt-id",
        f"att-{run_id}-{n}",
        "--segment-id",
        segment_id,
        now=now + 6,
    )
    assert admitted.get("outcome") == "admitted", admitted
    if launch:
        st.ok("launched", *launched_args(segment_id, now + 7), now=now + 7)
    return Seg(run_id, request_id, f"att-{run_id}-{n}", segment_id, session)


def authority(
    st: Store,
    run_id: str,
    segment_id: str,
    *args: str,
    extra: dict[str, str] | None = None,
    drop: str | None = None,
) -> Out:
    """Run ``credits_msg.py authority`` with the launcher's environment."""
    env = st.env(
        {
            "CREDITS_RUN_ID": run_id,
            "CREDITS_SEGMENT": segment_id,
            "CREDITS_STATE_DB": str(st.db),
            **(extra or {}),
        }
    )
    if drop is not None:
        del env[drop]
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(MSG_TOOL), "authority", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=child_env(env),
        timeout=120,
        cwd=ROOT,
        check=False,
    )
    return parse_out(proc.returncode, proc.stdout, proc.stderr)


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_only(st: Store, call: Any) -> Out:
    """Run ``call`` and prove that the store did not change (rows and file bytes)."""
    rows = dump(st.db)
    data = file_hash(st.db)
    out: Out = call()
    assert file_hash(st.db) == data, out.show()
    assert dump(st.db) == rows, out.show()
    return out


def agent(quote: str) -> tuple[str, ...]:
    return ("--started-by", "agent-on-user-chat", "--quote", quote)


HUMAN = ("--started-by", "human-command", "--requested-by", "fixture-user@fixture-host")


def test_human_command_start_is_authorized(st: Store) -> None:
    """EA-90 AC-1: a human-command start shows its full record; no config is read."""
    make_registered(st, "run-h")
    seg = start(st, "run-h", 1, now=0, request=HUMAN)
    out = read_only(
        st,
        lambda: authority(
            st,
            "run-h",
            seg.segment_id,
            extra={"CREDITS_CONFIG": str(st.root / "no-such-config.json")},
        ),
    )
    assert out.code == 0 and out.result == "ok", out.show()
    payload = out.payload or {}
    assert payload["verb"] == "authority"
    assert payload["authorized"] is True
    assert payload["run_id"] == "run-h"
    assert payload["segment_id"] == seg.segment_id
    assert payload["segment_ordinal"] == 1
    assert payload["request_id"] == seg.request_id
    assert payload["request_state"] == "launched"
    assert payload["attempt_id"] == seg.attempt_id
    assert payload["dispatch_id"] == "disp-run-h-1"
    assert payload["started_by"] == "human-command"
    assert payload["quote"] is None
    assert payload["requested_by"] == "fixture-user@fixture-host"
    assert payload["chain"] is None
    assert payload["resume"] is False
    assert payload["resume_mode"] is None
    assert payload["brief"] is None
    assert payload["requested_utc"] == at(0)
    assert payload["quote_checked"] is False


@pytest.mark.parametrize(
    ("recorded", "given"),
    [
        ("run S7 acceptance; D-11: A", "run S7 acceptance; D-11: A"),
        ("run S7 acceptance;  D-11: A", "  run S7 acceptance; D-11: A\n"),
        ("first line\r\nsecond line", "first line\nsecond line"),
    ],
)
def test_agent_start_shows_and_checks_the_quote(
    st: Store, recorded: str, given: str
) -> None:
    """EA-90 AC-2: the recorded quote is shown as filed; --quote matches it normalized."""
    make_registered(st, "run-q")
    seg = start(st, "run-q", 1, now=0, request=agent(recorded))
    out = read_only(
        st, lambda: authority(st, "run-q", seg.segment_id, "--quote", given)
    )
    assert out.code == 0 and out.result == "ok", out.show()
    payload = out.payload or {}
    assert payload["authorized"] is True
    assert payload["started_by"] == "agent-on-user-chat"
    assert payload["quote"] == recorded
    assert payload["requested_by"] is None
    assert payload["quote_checked"] is True


def test_quote_mismatch_is_refused(st: Store) -> None:
    """EA-90 AC-3: --quote that differs from the recorded quote → exit 3, no write."""
    make_registered(st, "run-q")
    seg = start(st, "run-q", 1, now=0, request=agent("A"))
    out = read_only(st, lambda: authority(st, "run-q", seg.segment_id, "--quote", "B"))
    assert out.code == 3 and out.error == "authority_quote_mismatch", out.show()
    assert (out.payload or {}).get("authorized") is not True


def test_quote_against_a_record_without_a_quote_is_refused(st: Store) -> None:
    """EA-90 AC-3: --quote on a human-command record (no quote) → exit 3."""
    make_registered(st, "run-h")
    seg = start(st, "run-h", 1, now=0, request=HUMAN)
    out = read_only(st, lambda: authority(st, "run-h", seg.segment_id, "--quote", "A"))
    assert out.code == 3 and out.error == "authority_quote_mismatch", out.show()


def test_resume_shows_its_mode_brief_and_ordinal(st: Store, tmp_path: Path) -> None:
    """EA-90 AC-4: a resume segment shows resume, the mode, the brief and its place."""
    make_registered(st, "run-r")
    first = start(st, "run-r", 1, now=0, request=HUMAN)
    finish(st, first, now=20, total=1.0)
    stop(st, "run-r", now=21)
    brief = tmp_path / "resume-brief.md"
    brief.write_text("# resume brief\n", encoding="utf-8")
    second = start(
        st,
        "run-r",
        2,
        now=30,
        session=SESSION_B,
        request=(
            *agent("resume run-r"),
            "--resume",
            "--resume-mode",
            "fresh",
            "--brief",
            str(brief),
        ),
    )
    out = read_only(
        st, lambda: authority(st, "run-r", second.segment_id, "--quote", "resume run-r")
    )
    assert out.code == 0 and out.result == "ok", out.show()
    payload = out.payload or {}
    assert payload["segment_ordinal"] == 2
    assert payload["request_id"] == second.request_id
    assert payload["resume"] is True
    assert payload["resume_mode"] == "fresh"
    assert payload["brief"] == str(brief)
    assert payload["requested_utc"] == at(30)


def chain_manifest(st: Store, run_id: str) -> Path:
    """A fixture manifest with a chain authorization (R§4.1 ``chain``)."""
    path = write_manifest(st, run_id)
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["chain"] = {
        "chain_id": "chain-1",
        "quote": "run the fixture chain",
        "given_at": at(-100),
        "chain_cap_usd": 50.0,
    }
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return path


def test_monitor_chain_start_shows_the_chain_authorization(st: Store) -> None:
    """EA-90 AC-5: a monitor-chain start shows the human's chain quote from the manifest."""
    manifest = chain_manifest(st, "run-c")
    st.ok(
        "register",
        "--run-id",
        "run-c",
        "--manifest",
        str(manifest),
        "--cli-version",
        "9.9.9",
        "--kit-revision",
        "kitrev-fixture",
    )
    st.ok("registered", "--run-id", "run-c", "--task-hash", "taskhash-run-c")
    seg = start(
        st,
        "run-c",
        1,
        now=0,
        request=("--started-by", "monitor-chain", "--chain-id", "chain-1"),
    )
    out = read_only(st, lambda: authority(st, "run-c", seg.segment_id))
    assert out.code == 0 and out.result == "ok", out.show()
    payload = out.payload or {}
    assert payload["started_by"] == "monitor-chain"
    assert payload["quote"] is None
    assert payload["chain"] == {
        "chain_id": "chain-1",
        "quote": "run the fixture chain",
        "given_at": at(-100),
    }


def test_admitted_segment_before_the_launch_record_is_authorized(st: Store) -> None:
    """EA-90 AC-6: the session can start before ``launched`` is recorded (admitted)."""
    make_registered(st, "run-h")
    seg = start(st, "run-h", 1, now=0, request=HUMAN, launch=False)
    out = read_only(st, lambda: authority(st, "run-h", seg.segment_id))
    assert out.code == 0 and out.result == "ok", out.show()
    assert (out.payload or {})["request_state"] == "admitted"


def test_segment_without_a_request_is_refused(st: Store) -> None:
    """EA-90 AC-7: a manual segment (register_minimal) has no start request → exit 3."""
    st.ok("register_minimal", *minimal_args("run-m", "seg-run-m"))
    out = read_only(st, lambda: authority(st, "run-m", "seg-run-m"))
    assert out.code == 3 and out.error == "authority_no_request", out.show()


def test_unknown_segment_is_refused(st: Store) -> None:
    """EA-90 AC-7: a segment id that the run does not have → exit 3."""
    make_registered(st, "run-h")
    start(st, "run-h", 1, now=0, request=HUMAN)
    out = read_only(st, lambda: authority(st, "run-h", "seg-no-such"))
    assert out.code == 3 and out.error == "unknown_segment", out.show()


def test_segment_of_another_run_is_refused(st: Store) -> None:
    """EA-90 AC-7: the segment must belong to CREDITS_RUN_ID."""
    make_registered(st, "run-a")
    make_registered(st, "run-b", lane="tree:X:/fixture-tree-b")
    seg_a = start(st, "run-a", 1, now=0, request=HUMAN)
    out = read_only(st, lambda: authority(st, "run-b", seg_a.segment_id))
    assert out.code == 3 and out.error == "unknown_segment", out.show()


def test_ended_segment_is_refused(st: Store) -> None:
    """EA-90 AC-8: a finalized segment no longer carries a start authority."""
    make_registered(st, "run-h")
    seg = start(st, "run-h", 1, now=0, request=HUMAN)
    finish(st, seg, now=20, total=1.0)
    out = read_only(st, lambda: authority(st, "run-h", seg.segment_id))
    assert out.code == 3 and out.error == "authority_segment_ended", out.show()


def test_request_in_another_state_is_refused(st: Store) -> None:
    """EA-90 AC-8: a request that is not admitted or launched → exit 3."""
    make_registered(st, "run-h")
    seg = start(st, "run-h", 1, now=0, request=HUMAN)
    st.write(
        "UPDATE requests SET state = 'not_started' WHERE request_id = ?",
        (seg.request_id,),
    )
    out = read_only(st, lambda: authority(st, "run-h", seg.segment_id))
    assert out.code == 3 and out.error == "authority_not_launched", out.show()


def test_segment_and_attempt_on_different_requests_are_refused(st: Store) -> None:
    """EA-90 AC-8: the segment's request must be the request of its attempt."""
    make_registered(st, "run-r")
    first = start(st, "run-r", 1, now=0, request=HUMAN)
    finish(st, first, now=20, total=1.0)
    stop(st, "run-r", now=21)
    second = start(
        st, "run-r", 2, now=30, session=SESSION_B, request=(*HUMAN, "--resume")
    )
    st.write(
        "UPDATE segments SET request_id = ? WHERE segment_id = ?",
        (first.request_id, second.segment_id),
    )
    out = read_only(st, lambda: authority(st, "run-r", second.segment_id))
    assert out.code == 3 and out.error == "authority_link_mismatch", out.show()


def test_agent_record_without_a_quote_is_refused(st: Store) -> None:
    """EA-90 AC-8: an agent-on-user-chat record must carry the user's words."""
    make_registered(st, "run-q")
    seg = start(st, "run-q", 1, now=0, request=agent("A"))
    st.write(
        "UPDATE requests SET start_quote = NULL WHERE request_id = ?",
        (seg.request_id,),
    )
    out = read_only(st, lambda: authority(st, "run-q", seg.segment_id))
    assert out.code == 3 and out.error == "authority_no_quote", out.show()


@pytest.mark.parametrize(
    "name", ["CREDITS_RUN_ID", "CREDITS_SEGMENT", "CREDITS_STATE_DB"]
)
def test_missing_environment_is_a_usage_error(st: Store, name: str) -> None:
    """EA-90 AC-9: each launcher value is needed (exit 2, no store opened)."""
    make_registered(st, "run-h")
    seg = start(st, "run-h", 1, now=0, request=HUMAN)
    out = read_only(st, lambda: authority(st, "run-h", seg.segment_id, drop=name))
    assert out.code == 2 and out.error == "usage", out.show()


def test_missing_store_is_refused(st: Store) -> None:
    """EA-90 AC-9: no store file → store_missing, and no file is created."""
    missing = st.root / "absent" / "state.db"
    out = authority(
        st, "run-h", "seg-run-h-1", extra={"CREDITS_STATE_DB": str(missing)}
    )
    assert out.code == 3 and out.error == "store_missing", out.show()
    assert not missing.exists()


def test_schema_mismatch_is_refused_without_a_write(st: Store) -> None:
    """EA-90 AC-9: a store of another schema → schema_mismatch; the read-only open migrates nothing."""
    make_registered(st, "run-h")
    seg = start(st, "run-h", 1, now=0, request=HUMAN)
    st.write("PRAGMA user_version = 5")
    out = read_only(st, lambda: authority(st, "run-h", seg.segment_id))
    assert out.code == 3 and out.error == "schema_mismatch", out.show()
