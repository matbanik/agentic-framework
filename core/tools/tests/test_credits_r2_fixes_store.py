"""Execution review round 2: one cap per chain, and the accept clock after the lock wait.

Plan: docs/execution/plans/2026-10-15-scheduled-credits-runs (Components B, D and G;
review round 2 findings R2-F1 and R2-F2).

R2-F1 (AC-G.2, report sections 4.3 and 5.4.4): the runs of one chain share one cap.
  ``register`` refuses a manifest whose ``chain`` block differs from the block that a
  run of the same ``chain_id`` already holds (``chain_conflict``) and writes nothing.
  An equal block registers. Admission and ``chain_candidates`` use the smallest cap
  that the store holds for the chain, so a store that holds two caps for one chain
  never reserves more than the smaller cap.
R2-F2 (AC-D.3, MX-31): ``accept`` reads the production clock again after it takes the
  writer lock. A request that crossed the ``REQUEST_ACCEPT_TIMEOUT_S`` deadline while
  ``accept`` waited for the lock is ``stale_at_launcher``, not ``accepted``. The
  ``--now-utc`` test clock still fixes the clock.

Each store is a temp file. The R2-F2 tests hold the real writer lock for a few seconds.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from test_credits_state import (
    ROOT,
    TOOL,
    Store,
    accept_args,
    child_env,
    make_registered,
    parse_out,
    request_args,
    write_manifest,
)

EXIT_REFUSED = 3
UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
ACCEPT_MAX_AGE_S = 120
CHAIN_ID = "chain-r2"
QUOTE = "Run r2-a, then r2-b, with a total cap of ten dollars."
GIVEN_AT = "2026-10-17T01:00:00Z"
SESSION = "cccccccc-0000-4000-8000-000000000003"


@pytest.fixture
def st(tmp_path: Path) -> Store:
    store = Store(tmp_path)
    store.init()
    return store


# --- R2-F1 helpers ---------------------------------------------------------------------


def chain_block(**changes: Any) -> dict[str, Any]:
    block: dict[str, Any] = {
        "chain_id": CHAIN_ID,
        "quote": QUOTE,
        "given_at": GIVEN_AT,
        "chain_cap_usd": 10.0,
    }
    block.update(changes)
    return block


def chain_manifest(st: Store, run_id: str, block: dict[str, Any]) -> Path:
    """A fixture manifest (own lane) with ``block`` as its ``chain``."""
    path = write_manifest(st, run_id, lane=f"tree:X:/fixture-tree/{run_id}")
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["chain"] = block
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return path


def register_chain(st: Store, run_id: str, block: dict[str, Any]) -> Any:
    return st.cli(
        "register",
        "--run-id",
        run_id,
        "--manifest",
        str(chain_manifest(st, run_id, block)),
        "--cli-version",
        "9.9.9",
        "--kit-revision",
        "kitrev-fixture",
    )


def registered(st: Store, run_id: str, block: dict[str, Any]) -> None:
    out = register_chain(st, run_id, block)
    assert out.code == 0 and out.result == "changed", out.show()
    st.ok("registered", "--run-id", run_id, "--task-hash", f"taskhash-{run_id}")


def admit(st: Store, run_id: str) -> dict[str, Any]:
    st.ok("request", *request_args(run_id, 1), now=10)
    st.ok("accept", *accept_args(run_id, 1, SESSION), now=11)
    return st.ok(
        "admit",
        "--attempt-id",
        f"att-{run_id}-1",
        "--segment-id",
        f"seg-{run_id}-1",
        now=12,
    )


def open_reservations(st: Store) -> float:
    total = st.one(
        "SELECT COALESCE(SUM(reservation_usd), 0) FROM segments"
        " WHERE finalized_utc IS NULL AND reservation_released_utc IS NULL"
    )
    return float(total)


def run_count(st: Store, run_id: str) -> int:
    return int(st.one("SELECT COUNT(*) FROM runs WHERE run_id = ?", (run_id,)))


# --- R2-F1: registration ----------------------------------------------------------------


def test_r2_f1_other_cap_for_the_chain_is_refused(st: Store) -> None:
    registered(st, "r2-a", chain_block(chain_cap_usd=10.0))
    out = register_chain(st, "r2-b", chain_block(chain_cap_usd=20.0))
    assert out.code == EXIT_REFUSED, out.show()
    assert out.error == "chain_conflict", out.show()
    assert run_count(st, "r2-b") == 0
    assert st.one("SELECT state FROM runs WHERE run_id = 'r2-a'") == "registered"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("chain_cap_usd", 5.0),
        ("quote", "Run r2-a, then r2-b, with a total cap of twenty dollars."),
        ("given_at", "2026-10-17T02:00:00Z"),
    ],
)
def test_r2_f1_any_other_chain_field_is_refused(
    st: Store, field: str, value: Any
) -> None:
    registered(st, "r2-a", chain_block())
    out = register_chain(st, "r2-b", chain_block(**{field: value}))
    assert out.code == EXIT_REFUSED, out.show()
    assert out.error == "chain_conflict", out.show()
    assert run_count(st, "r2-b") == 0


def test_r2_f1_a_cancelled_run_of_the_chain_still_holds_the_cap(st: Store) -> None:
    registered(st, "r2-a", chain_block(chain_cap_usd=10.0))
    st.ok("cancel", "--run-id", "r2-a", "--reason", "fixture")
    out = register_chain(st, "r2-b", chain_block(chain_cap_usd=20.0))
    assert out.code == EXIT_REFUSED, out.show()
    assert out.error == "chain_conflict", out.show()
    assert run_count(st, "r2-b") == 0


def test_r2_f1_control_an_equal_chain_block_registers(st: Store) -> None:
    registered(st, "r2-a", chain_block())
    out = register_chain(st, "r2-b", chain_block())
    assert out.code == 0 and out.result == "changed", out.show()


def test_r2_f1_control_another_chain_id_registers_with_its_own_cap(st: Store) -> None:
    registered(st, "r2-a", chain_block(chain_cap_usd=10.0))
    out = register_chain(
        st, "r2-b", chain_block(chain_id="chain-r2-other", chain_cap_usd=20.0)
    )
    assert out.code == 0 and out.result == "changed", out.show()


def test_r2_f1_control_a_repeat_of_the_same_run_is_no_change(st: Store) -> None:
    block = chain_block()
    out = register_chain(st, "r2-a", block)
    assert out.code == 0 and out.result == "changed", out.show()
    again = register_chain(st, "r2-a", block)
    assert again.code == 0 and again.result == "no_change", again.show()


def test_r2_f1_control_one_cap_admits_the_chain_once(st: Store) -> None:
    registered(st, "r2-a", chain_block(chain_cap_usd=10.0))
    registered(st, "r2-b", chain_block(chain_cap_usd=10.0))
    first = admit(st, "r2-a")
    second = admit(st, "r2-b")
    assert first["outcome"] == "admitted" and first["reservation_usd"] == 10.0
    assert second["outcome"] == "rejected" and second["reason"] == "budget_floor"
    assert open_reservations(st) <= 10.0


# --- R2-F1: a store that already holds two caps for one chain -----------------------------


def seed_second_cap(st: Store, run_id: str, cap: float) -> None:
    """Rewrite the stored chain cap of ``run_id`` (a store written before the check)."""
    text = str(st.one("SELECT manifest_json FROM runs WHERE run_id = ?", (run_id,)))
    doc = json.loads(text)
    doc["chain"]["chain_cap_usd"] = cap
    st.write(
        "UPDATE runs SET manifest_json = ? WHERE run_id = ?", (json.dumps(doc), run_id)
    )


def test_r2_f1_admission_uses_the_smallest_stored_cap(st: Store) -> None:
    registered(st, "r2-a", chain_block(chain_cap_usd=10.0))
    registered(st, "r2-b", chain_block(chain_cap_usd=10.0))
    seed_second_cap(st, "r2-b", 20.0)
    first = admit(st, "r2-a")
    second = admit(st, "r2-b")
    assert first["outcome"] == "admitted" and first["reservation_usd"] == 10.0
    assert second["outcome"] == "rejected", second
    assert second["reason"] == "budget_floor", second
    assert open_reservations(st) <= 10.0


def test_r2_f1_chain_candidates_use_the_smallest_stored_cap(st: Store) -> None:
    registered(st, "r2-a", chain_block(chain_cap_usd=10.0))
    registered(st, "r2-b", chain_block(chain_cap_usd=10.0))
    seed_second_cap(st, "r2-b", 20.0)
    payload = st.ok("chain_candidates", expect=("ok",))
    rooms = {c["run_id"]: c["chain_room_usd"] for c in payload["candidates"]}
    assert rooms == {"r2-a": 10.0, "r2-b": 10.0}, payload


# --- R2-F2: the accept clock after the lock wait ------------------------------------------


def real_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def seed_request(st: Store, run_id: str, age_s: int) -> datetime:
    """A registered run with one pending request whose ``created_utc`` is ``age_s`` old."""
    make_registered(st, run_id)
    st.ok("request", *request_args(run_id, 1))
    created = real_now() - timedelta(seconds=age_s)
    st.write(
        "UPDATE requests SET created_utc = ? WHERE run_id = ?",
        (created.strftime(UTC_FORMAT), run_id),
    )
    return created


def start_accept(st: Store, run_id: str, now_utc: str | None) -> subprocess.Popen[str]:
    argv = [sys.executable, "-B", "-X", "utf8", str(TOOL), "--db", str(st.db)]
    if now_utc is not None:
        argv += ["--now-utc", now_utc]
    argv += ["--profile", "launcher", "accept", *accept_args(run_id, 1, SESSION)]
    env = child_env(st.env({"CREDITS_TEST_BUSY_TIMEOUT_MS": "20000"}))
    return subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=ROOT,
    )


@contextlib.contextmanager
def writer_lock(db: Path) -> Any:
    con = sqlite3.connect(db, isolation_level=None)
    try:
        con.execute("BEGIN IMMEDIATE")
        yield
    finally:
        with contextlib.suppress(sqlite3.Error):
            con.execute("ROLLBACK")
        con.close()


def hold_until(moment: datetime) -> None:
    while datetime.now(UTC) < moment:
        time.sleep(0.05)


def finish(proc: subprocess.Popen[str]) -> Any:
    stdout, stderr = proc.communicate(timeout=60)
    return parse_out(proc.returncode, stdout, stderr)


def test_r2_f2_a_request_that_ages_out_during_the_lock_wait_is_stale(st: Store) -> None:
    created = seed_request(st, "r2-stale", 117)
    deadline = created + timedelta(seconds=ACCEPT_MAX_AGE_S)
    with writer_lock(st.db):
        proc = start_accept(st, "r2-stale", None)
        hold_until(deadline + timedelta(seconds=1))
        waited = proc.poll() is None
    out = finish(proc)
    assert waited, "accept did not wait for the writer lock"
    assert out.code == 0, out.show()
    assert out.payload is not None and out.payload["outcome"] == "stale_at_launcher", (
        out.show()
    )
    assert out.payload["age_s"] >= ACCEPT_MAX_AGE_S, out.show()
    assert (
        st.one("SELECT state FROM requests WHERE run_id = 'r2-stale'") == "not_started"
    )
    assert st.rows("SELECT * FROM attempts WHERE run_id = 'r2-stale'") == []
    moved = str(
        st.one(
            "SELECT at_utc FROM transitions WHERE entity = 'request'"
            " AND to_state = 'not_started'"
        )
    )
    assert moved >= deadline.strftime(UTC_FORMAT), moved


def test_r2_f2_control_a_short_lock_wait_inside_the_window_accepts(st: Store) -> None:
    seed_request(st, "r2-fresh", 60)
    with writer_lock(st.db):
        proc = start_accept(st, "r2-fresh", None)
        hold_until(datetime.now(UTC) + timedelta(seconds=1))
        waited = proc.poll() is None
    out = finish(proc)
    assert waited, "accept did not wait for the writer lock"
    assert out.code == 0 and out.payload is not None, out.show()
    assert out.payload["outcome"] == "accepted", out.show()


def test_r2_f2_control_the_test_clock_does_not_move_during_the_lock_wait(
    st: Store,
) -> None:
    make_registered(st, "r2-seam")
    st.ok("request", *request_args("r2-seam", 1), now=0)
    store_clock = st.one("SELECT created_utc FROM requests WHERE run_id = 'r2-seam'")
    at_119 = (
        datetime.strptime(str(store_clock), UTC_FORMAT).replace(tzinfo=UTC)
        + timedelta(seconds=ACCEPT_MAX_AGE_S - 1)
    ).strftime(UTC_FORMAT)
    with writer_lock(st.db):
        proc = start_accept(st, "r2-seam", at_119)
        hold_until(datetime.now(UTC) + timedelta(seconds=2))
        waited = proc.poll() is None
    out = finish(proc)
    assert waited, "accept did not wait for the writer lock"
    assert out.code == 0 and out.payload is not None, out.show()
    assert out.payload["outcome"] == "accepted", out.show()
