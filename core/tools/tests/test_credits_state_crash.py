"""S2a store crash points and effect windows (Component B, AC-B.3 and AC-B.6).

Plan: docs/execution/plans/2026-10-15-scheduled-credits-runs (AC-B.3, AC-B.6,
AC-B.10; report R§4.7 rule 3 and the crash-point list; matrix MX-22).

``CREDITS_TEST_CRASH_AT=<verb>:<point>`` makes the store end the process with
exit 9 at that point. The declared points of every verb are ``before_begin``,
``before_commit`` and ``after_commit``. A verb with effects also has
``after_effect`` (after the first effect is performed and before it is marked
done). ``scan_effects`` has only ``after_effect``. Any other value is a usage
error (exit 2) before the store is opened for writing.

For each crash, the store must pass ``check`` and must equal the state before
the verb (the ``before_*`` points) or the state after it (the ``after_*``
points). The "after" state comes from a twin copy that ran the same verb with
no crash. Effect and notice rows are compared by key, because an effect that
is not yet performed is ``pending`` in the crashed copy and ``done`` in the
twin. The next ``scan_effects`` pass (after 300 s) performs every pending
effect, so each effect runs at least once, with its key.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import sqlite3
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from test_credits_state import (
    REAL_DB_STATE_AT_IMPORT,
    SESSION_A,
    Store,
    accept_args,
    check_ok,
    complete_args,
    dump,
    finish,
    first_start,
    launched_args,
    make_registered,
    minimal_args,
    real_db_state,
    register,
    register_args,
    request_args,
    run_state,
)

BASE_POINTS = ("before_begin", "before_commit", "after_commit")
EFFECT_POINTS = (*BASE_POINTS, "after_effect")
KEYED_TABLES = {"effects": "effect_key", "notices": "notice_key"}
RETRY_AFTER_S = 301

Dump = dict[str, list[tuple[Any, ...]]]


def reduced_dump(db: Path) -> Dump:
    """Return ``dump(db)`` with the effect and notice tables reduced to their sorted keys."""
    out = dump(db)
    with contextlib.closing(sqlite3.connect(db)) as con:
        for table, key in KEYED_TABLES.items():
            out[table] = sorted(
                con.execute(f'SELECT "{key}" FROM "{table}"').fetchall()
            )
    return out


def clone(src: Path, dst: Path) -> Store:
    """Copy a prepared store folder; the WAL is kept, the shared-memory file and the effect log are not."""
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("*-shm", "effects.jsonl"))
    return Store(dst)


@pytest.fixture
def st(tmp_path: Path) -> Store:
    return Store(tmp_path)


def pending_effects(st: Store) -> int:
    return int(st.one("SELECT COUNT(*) FROM effects WHERE state != 'done'"))


# --- scenarios: one verb each, from a known setup ------------------------------


def _init(st: Store) -> None:
    st.init()


def _registering(st: Store) -> None:
    register(st, "run-c")


def _registered(st: Store) -> None:
    make_registered(st, "run-c")


def _requested(st: Store) -> None:
    make_registered(st, "run-c")
    st.ok("request", *request_args("run-c", 1), now=10)


def _accepted(st: Store) -> None:
    _requested(st)
    st.ok("accept", *accept_args("run-c", 1, SESSION_A), now=15)


def _lane_busy(st: Store) -> None:
    first_start(st, "run-x")
    make_registered(st, "run-c", now=20)
    st.ok("request", *request_args("run-c", 1), now=21)
    st.ok("accept", *accept_args("run-c", 1, SESSION_A), now=22)


def _admitted(st: Store) -> None:
    first_start(st, "run-c", launch=False)


def _running(st: Store) -> None:
    first_start(st, "run-c")


def _finalizing(st: Store) -> None:
    seg = first_start(st, "run-c")
    finish(st, seg, now=30, total=12.5)


def _crashed(st: Store) -> None:
    seg = first_start(st, "run-c")
    finish(st, seg, now=20)


def _minimal(st: Store) -> None:
    st.init()
    st.ok("register_minimal", *minimal_args("run-m", "seg-m-1"), now=1)


def _manual_running(st: Store) -> None:
    _minimal(st)
    st.ok(
        "manual_identity",
        "--segment-id",
        "seg-m-1",
        "--pid",
        "7171",
        "--created",
        "2026-10-15T12:00:02Z",
        now=3,
    )


def _effects_pending(st: Store) -> None:
    first_start(st, "run-c")
    out = st.cli(
        "complete_segment",
        *complete_args("seg-run-c-1", total=12.5),
        now=30,
        env={"CREDITS_TEST_CRASH_AT": "complete_segment:after_commit"},
    )
    assert out.code == 9, out.show()


@dataclass(frozen=True)
class Scenario:
    name: str
    setup: Callable[[Store], None]
    verb: str
    args: Callable[[Store], tuple[str, ...]]
    now: int
    points: tuple[str, ...] = BASE_POINTS


def _fixed(*args: str) -> Callable[[Store], tuple[str, ...]]:
    return lambda _st: args


SCENARIOS: dict[str, Scenario] = {
    sc.name: sc
    for sc in (
        Scenario(
            "register", _init, "register", lambda st: register_args(st, "run-c"), 0
        ),
        Scenario(
            "registered",
            _registering,
            "registered",
            _fixed("--run-id", "run-c", "--task-hash", "taskhash-run-c"),
            1,
        ),
        Scenario(
            "registration_failed",
            _registering,
            "registration_failed",
            _fixed("--run-id", "run-c", "--reason", "fixture"),
            1,
        ),
        Scenario(
            "request", _registered, "request", _fixed(*request_args("run-c", 1)), 1
        ),
        Scenario(
            "not_started",
            _requested,
            "not_started",
            _fixed("--request-id", "req-run-c-1", "--reason", "caller_timeout"),
            130,
            EFFECT_POINTS,
        ),
        Scenario(
            "accept",
            _requested,
            "accept",
            _fixed(*accept_args("run-c", 1, SESSION_A)),
            15,
        ),
        Scenario(
            "accept_stale",
            _requested,
            "accept",
            _fixed(*accept_args("run-c", 1, SESSION_A)),
            135,
            EFFECT_POINTS,
        ),
        Scenario(
            "admit",
            _accepted,
            "admit",
            _fixed("--attempt-id", "att-run-c-1", "--segment-id", "seg-run-c-1"),
            16,
        ),
        Scenario(
            "admit_rejected",
            _lane_busy,
            "admit",
            _fixed("--attempt-id", "att-run-c-1", "--segment-id", "seg-run-c-1"),
            23,
        ),
        Scenario(
            "launched",
            _admitted,
            "launched",
            _fixed(*launched_args("seg-run-c-1", 20)),
            20,
        ),
        Scenario(
            "complete_segment",
            _running,
            "complete_segment",
            _fixed(*complete_args("seg-run-c-1", total=12.5)),
            30,
            EFFECT_POINTS,
        ),
        Scenario(
            "classify",
            _finalizing,
            "classify",
            _fixed("--run-id", "run-c", "--to", "done", "--class", "done"),
            31,
        ),
        Scenario("cancel", _registered, "cancel", _fixed("--run-id", "run-c"), 1),
        Scenario(
            "register_minimal",
            _init,
            "register_minimal",
            _fixed(*minimal_args("run-m", "seg-m-1")),
            1,
        ),
        Scenario(
            "manual_identity",
            _minimal,
            "manual_identity",
            _fixed(
                "--segment-id",
                "seg-m-1",
                "--pid",
                "7171",
                "--created",
                "2026-10-15T12:00:02Z",
            ),
            3,
        ),
        Scenario(
            "complete_manual",
            _manual_running,
            "complete_segment",
            _fixed(*complete_args("seg-m-1", by="wrapper", total=3.0)),
            30,
            EFFECT_POINTS,
        ),
        Scenario(
            "settle",
            _crashed,
            "settle",
            _fixed(
                "--segment-id",
                "seg-run-c-1",
                "--source",
                "console",
                "--amount-usd",
                "41.5",
            ),
            21,
        ),
        Scenario(
            "scan_requests", _requested, "scan_requests", _fixed(), 161, EFFECT_POINTS
        ),
        Scenario(
            "scan_attempts",
            _admitted,
            "scan_attempts",
            _fixed("--proofs-json", json.dumps({"att-run-c-1": "empty"})),
            100,
            EFFECT_POINTS,
        ),
        Scenario(
            "scan_segments",
            _running,
            "scan_segments",
            _fixed("--proofs-json", json.dumps({"seg-run-c-1": "gone"})),
            100,
            EFFECT_POINTS,
        ),
        Scenario(
            "scan_effects",
            _effects_pending,
            "scan_effects",
            _fixed(),
            331,
            ("after_effect",),
        ),
    )
}

CASES = [(name, point) for name, sc in SCENARIOS.items() for point in sc.points]


@dataclass(frozen=True)
class Prepared:
    base: Path
    args: tuple[str, ...]
    before: Dump
    after: Dump
    effect_keys: frozenset[str]


_PREPARED: dict[str, Prepared] = {}


def prepare(sc: Scenario, factory: pytest.TempPathFactory) -> Prepared:
    """Build the setup store and its no-crash twin once per scenario (cached for the module)."""
    cached = _PREPARED.get(sc.name)
    if cached is not None:
        return cached
    base = Store(factory.mktemp(f"crash-{sc.name}"))
    sc.setup(base)
    args = sc.args(base)
    before = dump(base.db)
    twin = clone(base.root, factory.mktemp(f"twin-{sc.name}") / "store")
    out = twin.cli(sc.verb, *args, now=sc.now)
    assert out.code == 0 and out.result == "changed", out.show()
    assert dump(twin.db) != before
    prepared = Prepared(
        base.root, args, before, reduced_dump(twin.db), frozenset(twin.logged_effects())
    )
    _PREPARED[sc.name] = prepared
    return prepared


# --- AC-B.3: every declared crash point ----------------------------------------


@pytest.mark.parametrize(("name", "point"), CASES, ids=[f"{n}:{p}" for n, p in CASES])
def test_crash_point_leaves_the_before_or_the_after_state(
    tmp_path: Path, tmp_path_factory: pytest.TempPathFactory, name: str, point: str
) -> None:
    """AC-B.3: a store killed at a declared point passes ``check`` and equals the before- or the after-state."""
    sc = SCENARIOS[name]
    prep = prepare(sc, tmp_path_factory)
    st = clone(prep.base, tmp_path / "store")
    out = st.cli(
        sc.verb,
        *prep.args,
        now=sc.now,
        env={"CREDITS_TEST_CRASH_AT": f"{sc.verb}:{point}"},
    )
    assert out.code == 9, out.show()

    if point.startswith("before_"):
        assert dump(st.db) == prep.before
    else:
        assert reduced_dump(st.db) == prep.after
    check_ok(st, sc.now)

    if point.startswith("after_"):
        st.ok(
            "scan_effects", now=sc.now + RETRY_AFTER_S, expect=("changed", "no_change")
        )
        assert set(st.logged_effects()) == prep.effect_keys
        assert pending_effects(st) == 0
        check_ok(st, sc.now + RETRY_AFTER_S)


@pytest.mark.parametrize(
    "crash_at",
    [
        "registered:after_effect",
        "bogus:before_commit",
        "register:sometime",
        "registered",
        "registered:",
    ],
)
def test_undeclared_crash_point_is_a_usage_error(st: Store, crash_at: str) -> None:
    """AC-B.3: an undeclared crash point → exit 2, and the store is unchanged."""
    register(st, "run-c")
    before = dump(st.db)
    out = st.cli(
        "registered",
        "--run-id",
        "run-c",
        "--task-hash",
        "taskhash-run-c",
        now=1,
        env={"CREDITS_TEST_CRASH_AT": crash_at},
    )
    assert out.code == 2 and out.result == "usage_error", out.show()
    assert dump(st.db) == before


def test_crash_point_of_another_verb_does_not_fire(st: Store) -> None:
    """AC-B.3: a declared point of another verb is inert; the verb runs to the end."""
    register(st, "run-c")
    out = st.cli(
        "registered",
        "--run-id",
        "run-c",
        "--task-hash",
        "taskhash-run-c",
        now=1,
        env={"CREDITS_TEST_CRASH_AT": "admit:before_commit"},
    )
    assert out.code == 0 and out.result == "changed", out.show()
    assert run_state(st, "run-c") == "registered"


# --- AC-B.6 / MX-22: effect windows --------------------------------------------


def test_mx_22_effect_after_commit_crash_runs_on_next_pass(st: Store) -> None:
    """AC-B.6 / MX-22: crash after the commit, before the effect → the effect runs on the next pass, once per key."""
    _effects_pending(st)
    assert st.logged_effects() == []
    keys = sorted(
        r[0] for r in st.rows("SELECT effect_key FROM effects WHERE state != 'done'")
    )
    assert keys == ["evtlog:seg-run-c-1", "rescan:seg-run-c-1"]

    st.ok("scan_effects", now=30 + 300, expect=("no_change",))
    assert st.logged_effects() == []
    st.ok("scan_effects", now=30 + RETRY_AFTER_S)
    assert sorted(st.logged_effects()) == keys
    assert pending_effects(st) == 0

    st.ok("scan_effects", now=30 + 900, expect=("no_change",))
    assert sorted(st.logged_effects()) == keys
    assert int(st.one("SELECT COUNT(*) FROM effects")) == len(keys)
    check_ok(st, 30 + 901)


def test_mx_22_effect_repeat_after_effect_crash_carries_same_key(st: Store) -> None:
    """AC-B.6 / MX-22: crash after an effect, before it is marked done → it runs again with the same key."""
    first_start(st, "run-c")
    out = st.cli(
        "complete_segment",
        *complete_args("seg-run-c-1", total=12.5),
        now=30,
        env={"CREDITS_TEST_CRASH_AT": "complete_segment:after_effect"},
    )
    assert out.code == 9, out.show()
    first = st.logged_effects()
    assert len(first) == 1, first

    st.ok("scan_effects", now=30 + RETRY_AFTER_S)
    counts = Counter(st.logged_effects())
    assert set(counts) == {"evtlog:seg-run-c-1", "rescan:seg-run-c-1"}
    assert counts[first[0]] == 2
    assert sorted(counts.values()) == [1, 2]
    assert int(st.one("SELECT COUNT(*) FROM effects")) == 2
    assert pending_effects(st) == 0
    check_ok(st, 30 + RETRY_AFTER_S)


# --- AC-B.10 --------------------------------------------------------------------


def test_crash_tests_never_open_the_real_store(st: Store) -> None:
    """AC-B.10: crash runs use temp stores only; the real ``state.db`` is as it was at import."""
    first_start(st, "run-c")
    out = st.cli(
        "complete_segment",
        *complete_args("seg-run-c-1"),
        now=30,
        env={"CREDITS_TEST_CRASH_AT": "complete_segment:before_commit"},
    )
    assert out.code == 9, out.show()
    assert real_db_state() == REAL_DB_STATE_AT_IMPORT
