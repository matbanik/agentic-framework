"""The quota governor: the quota replay, the store admit, the governor CLI and the monitor.

Each test uses a temp store and a set clock. The CLI of a probe is a stub that the test writes
into its own folder; no test starts the real CLI.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from test_credits_state import (
    ROOT,
    T0,
    Out,
    Store,
    accept_args,
    at,
    child_env,
    cli_argv,
    finish,
    launched_args,
    make_registered,
    parse_out,
    request_args,
    run_cli,
    run_state,
    write_manifest,
)
from tools import credits_state as cs

pytestmark = pytest.mark.timeout(600)

SKILL = ROOT / ".agent" / "skills" / "claude-credits"
MODULE = SKILL / "CreditsRun.psm1"
QUOTA = ROOT / "tools" / "orch_quota.py"
STATE_TOOL = ROOT / "tools" / "credits_state.py"
WATCH = SKILL / "Watch-CreditsRuns.ps1"
SESSION = "bbbbbbbb-0000-4000-8000-000000000002"
OWNED = ("usage_limit", "clean_end", "start_parked", "resume_started", "breaker_open")
BASE_POINTS = ("before_begin", "before_commit", "after_commit")
ADMIT_KEYS = {
    "verdict",
    "window",
    "running",
    "limited",
    "resets_at_utc",
    "retry_after_utc",
}


# --- the replay ---------------------------------------------------------------------------


class Log:
    """A quota event log in memory."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def add(
        self, kind: str, seconds: int, resets: int | None = None, run: str | None = None
    ) -> None:
        """Add one event at ``T0 + seconds``."""
        self.events.append(
            {
                "seq": len(self.events) + 1,
                "at_utc": at(seconds),
                "kind": kind,
                "run_id": run,
                "segment_id": None if run is None else f"seg-{run}",
                "resets_at_utc": None if resets is None else at(resets),
                "detail": None,
            }
        )

    def clean(self, count: int, start: int = 0) -> None:
        """Add ``count`` clean ends, one second apart."""
        for number in range(count):
            self.add("clean_end", start + number)

    def state(self, now: int, cap: int = 4) -> dict[str, Any]:
        """The state of the log at ``T0 + now``."""
        return cs.quota_state(self.events, T0 + timedelta(seconds=now), cap)

    def window(self, now: int, cap: int = 4) -> int:
        return int(self.state(now, cap)["window"])


def test_ac_928_1_the_named_values() -> None:
    assert cs.START_WINDOW == 3
    assert cs.DEFAULT_MAX_CLAUDE_WORKERS == 4
    assert cs.CLEAN_ENDS_PER_STEP == 10
    assert cs.RESUME_DELAY_S == 300
    assert cs.PROBE_EVERY_S == 1800
    assert cs.PROBE_TIMEOUT_S == 120
    assert cs.BURST_S == 300
    assert cs.BREAKER_RESTARTS == 3
    assert cs.BREAKER_WINDOW_S == 3600
    assert cs.CODEX_BACKOFF_BASE_S == 300
    assert cs.CODEX_BACKOFF_MAX_S == 3600


def test_ac_928_1_the_replay_grows_and_halves_the_window() -> None:
    log = Log()
    assert log.window(0) == 3
    log.clean(9)
    assert log.window(20) == 3
    log.clean(1, 9)
    assert log.window(20) == 4
    log.clean(10, 20)
    assert log.window(40) == 4
    log.add("usage_limit", 1000, 9000)
    assert log.window(1001) == 2
    for step in (10, 20, 30, 40):
        log.add("usage_limit", 1000 + step, 9000)
        assert log.window(1000 + step) == 2
    log.add("usage_limit", 1200)
    assert log.window(1201) == 2
    log.add("usage_limit", 1400, 9999)
    assert log.window(1401) == 1
    log.add("usage_limit", 3000, 12000)
    log.add("usage_limit", 5000, 14000)
    assert log.window(5001) == 1


def test_ac_928_1_the_cap_stops_the_growth() -> None:
    log = Log()
    log.clean(30)
    assert log.window(100, cap=3) == 3
    assert log.window(100, cap=4) == 4
    assert log.window(100, cap=2) == 2


@pytest.mark.parametrize(
    ("second", "resets", "window"),
    [
        (1300, 9100, 2),
        (1301, 9100, 1),
        (1300, None, 2),
        (1301, None, 1),
        (5000, 9000, 2),
        (5000, 9100, 1),
    ],
    ids=[
        "edge_new_reset",
        "past_edge_new_reset",
        "edge_no_reset",
        "past_edge_no_reset",
        "late_same_reset",
        "late_new_reset",
    ],
)
def test_ac_928_1_a_burst_is_one_decrease(
    second: int, resets: int | None, window: int
) -> None:
    """Same reset time, or within 300 s of the last decrease: no second decrease."""
    log = Log()
    log.clean(10)
    log.add("usage_limit", 1000, 9000)
    assert log.window(1001) == 2
    log.add("usage_limit", second, resets)
    assert log.window(second + 1) == window


def test_ac_928_1_two_limits_with_no_reset_time_have_no_common_reset() -> None:
    log = Log()
    log.clean(10)
    log.add("usage_limit", 1000)
    log.add("usage_limit", 1400)
    assert log.window(1401) == 1


def test_ac_928_1_the_burst_counts_from_the_decrease_not_from_its_last_member() -> None:
    log = Log()
    log.clean(10)
    log.add("usage_limit", 1000, 9000)
    log.add("usage_limit", 1250, 9000)
    log.add("usage_limit", 1400, 9500)
    assert log.window(1401) == 1


def test_ac_928_1_the_clean_ends_count_again_after_a_change() -> None:
    log = Log()
    log.clean(9)
    log.add("usage_limit", 1000, 2000)
    log.clean(9, 1100)
    assert log.window(1200) == 1
    log.clean(1, 1200)
    assert log.window(1300) == 2


def test_ac_928_1_the_replay_is_the_same_for_the_same_log() -> None:
    log = Log()
    log.clean(12)
    log.add("usage_limit", 1000, 9000, "r1")
    before = json.dumps(log.events)
    first = log.state(1100)
    assert log.state(1100) == first
    assert json.dumps(log.events) == before


# --- a store with subscription runs -------------------------------------------------------


@pytest.fixture
def st(tmp_path: Path) -> Store:
    store = Store(tmp_path / "store")
    store.root.mkdir()
    store.init()
    return store


def epoch(seconds: int) -> int:
    return int((T0 + timedelta(seconds=seconds)).timestamp())


def registered(
    st: Store,
    run: str,
    *,
    now: int = 0,
    exe: Path | None = None,
    auth: str = "subscription",
) -> None:
    """A registered run on its own lane; ``auth`` key writes a manifest with no route."""
    if auth == "key":
        make_registered(st, run, now=now, lane=f"tree:X:/lane-{run}")
        return
    path = write_manifest(st, run, lane=f"tree:X:/lane-{run}")
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["launch"].update(
        auth=auth, claude_version="2.1.327", allowed_tools=["Read", "Edit"]
    )
    if exe is not None:
        doc["launch"]["claude_exe"] = exe.as_posix()
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    facts = ("--cli-version", "9.9.9", "--kit-revision", "kitrev-fixture")
    st.ok("register", "--run-id", run, "--manifest", str(path), *facts, now=now)
    st.ok("registered", "--run-id", run, "--task-hash", f"taskhash-{run}", now=now)


def accepted(st: Store, run: str, n: int, *, now: int, resume: bool = False) -> None:
    """A request and its accept, some seconds before ``now``."""
    st.ok("request", *request_args(run, n, resume=resume), now=now - 6)
    st.ok("accept", *accept_args(run, n, SESSION), now=now - 1)


def admit_args(run: str, n: int) -> tuple[str, ...]:
    return ("--attempt-id", f"att-{run}-{n}", "--segment-id", f"seg-{run}-{n}")


def attempt(
    st: Store, run: str, n: int, *, now: int, resume: bool = False
) -> dict[str, Any]:
    """Request, accept and admit segment ``n`` of a run at ``now``; return the admit answer."""
    accepted(st, run, n, now=now, resume=resume)
    return st.ok("admit", *admit_args(run, n), now=now)


def opened(st: Store, run: str, n: int = 1, *, now: int, resume: bool = False) -> None:
    """Admit and launch segment ``n``; it stays open."""
    answer = attempt(st, run, n, now=now, resume=resume)
    assert answer["outcome"] == "admitted", answer
    st.ok("launched", *launched_args(f"seg-{run}-{n}", now + 1), now=now + 1)


class Part:
    """The segment fields that ``finish`` reads."""

    def __init__(self, run: str, n: int) -> None:
        self.segment_id = f"seg-{run}-{n}"


def ended(st: Store, run: str, n: int = 1, *, now: int) -> None:
    """End segment ``n``; the run is then finalizing."""
    finish(st, Part(run, n), now=now, total=1.0)  # type: ignore[arg-type]


def class_args(
    run: str, stop_class: str, to: str = "stopped", resets: int | None = None
) -> tuple[str, ...]:
    args = ("--run-id", run, "--to", to, "--class", stop_class)
    return args if resets is None else (*args, "--resets-at", str(epoch(resets)))


def stopped(
    st: Store,
    run: str,
    *,
    now: int,
    stop_class: str = "unknown",
    resets: int | None = None,
    auth: str = "subscription",
    exe: Path | None = None,
) -> None:
    """A run with one finished segment, stopped with ``stop_class`` at ``now``."""
    registered(st, run, now=now - 60, auth=auth, exe=exe)
    opened(st, run, now=now - 40)
    ended(st, run, now=now - 20)
    st.ok("classify", *class_args(run, stop_class, resets=resets), now=now)


def limited(
    st: Store,
    run: str,
    *,
    now: int,
    resets: int | None = None,
    exe: Path | None = None,
) -> None:
    """A subscription run that a usage limit stopped at ``now``."""
    stopped(st, run, now=now, stop_class="usage_limit", resets=resets, exe=exe)


def events(st: Store, kind: str | None = None) -> list[tuple[Any, ...]]:
    """The quota events: ``(kind, run_id, segment_id, resets_at_utc)`` in order."""
    rows = st.rows(
        "SELECT kind, run_id, segment_id, resets_at_utc FROM quota_events ORDER BY seq"
    )
    return [row for row in rows if kind is None or row[0] == kind]


def add_event(
    st: Store,
    kind: str,
    *,
    now: int,
    run: str | None = None,
    resets: int | None = None,
) -> None:
    """Fixture setup: one event row of a kind that only another verb writes."""
    st.write(
        "INSERT INTO quota_events (at_utc, kind, run_id, resets_at_utc) VALUES (?, ?, ?, ?)",
        (at(now), kind, run, None if resets is None else at(resets)),
    )


def dump(db: Path) -> dict[str, list[tuple[Any, ...]]]:
    """Each row of each table of the store."""
    with contextlib.closing(sqlite3.connect(db)) as con:
        names = [
            str(row[0])
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            )
        ]
        return {
            name: con.execute(f'SELECT * FROM "{name}"').fetchall() for name in names
        }


def quota(db: Path | None, *args: str, now: int | None = 0) -> Out:
    """One ``orch_quota.py`` call in its own process."""
    argv = [sys.executable, str(QUOTA)]
    if db is not None:
        argv += ["--db", str(db)]
    if now is not None:
        argv += ["--now-utc", at(now)]
    proc = subprocess.run(
        [*argv, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=child_env(),
        cwd=ROOT,
        timeout=120,
        check=False,
    )
    return parse_out(proc.returncode, proc.stdout, proc.stderr)


def asked(st: Store, *args: str, now: int) -> dict[str, Any]:
    """The answer of one governor call that must succeed."""
    out = quota(st.db, *args, now=now)
    assert out.code == 0 and out.payload is not None, out.show()
    return out.payload


def claude(st: Store, now: int, *args: str) -> dict[str, Any]:
    answer = asked(st, "admit", "--kind", "claude", *args, now=now)
    assert set(answer) >= ADMIT_KEYS, answer
    return answer


def codex(st: Store, now: int, running: int = 0) -> dict[str, Any]:
    answer = asked(st, "admit", "--kind", "codex", "--running", str(running), now=now)
    assert set(answer) >= ADMIT_KEYS, answer
    return answer


# --- AC-928.2: the store admit ------------------------------------------------------------


def test_ac_928_2_a_start_is_parked_until_the_reset_and_the_delay(st: Store) -> None:
    limited(st, "r1", now=100, resets=1000)
    assert events(st, "usage_limit") == [
        ("usage_limit", "r1", "seg-r1-1", at(1000)),
    ]
    registered(st, "r2", now=200)
    answer = attempt(st, "r2", 1, now=1299)
    assert (answer["outcome"], answer["reason"]) == ("rejected", "parked_quota")
    assert run_state(st, "r2") == "waiting"
    assert st.rows("SELECT * FROM segments WHERE run_id = 'r2'") == []
    assert [row[:2] for row in events(st, "start_parked")] == [("start_parked", "r2")]
    assert asked(st, "tick", now=1299)["parked_starts"] != []
    assert "r2" in json.dumps(asked(st, "tick", now=1299)["parked_starts"])
    again = attempt(st, "r2", 2, now=1300)
    assert again["outcome"] == "admitted", again
    assert len(events(st, "start_parked")) == 1
    assert "r2" not in json.dumps(asked(st, "tick", now=1301)["parked_starts"])


def test_ac_928_2_a_parked_resume_goes_back_to_stopped(st: Store) -> None:
    limited(st, "r1", now=100, resets=1000)
    answer = attempt(st, "r1", 2, now=1299, resume=True)
    assert (answer["outcome"], answer["reason"]) == ("rejected", "parked_quota")
    assert run_state(st, "r1") == "stopped"
    bodies = st.rows("SELECT body_json FROM notices WHERE kind = 'resume_refused'")
    assert len(bodies) == 1 and "parked_quota" in bodies[0][0]
    assert events(st, "start_parked") == []
    assert events(st, "resume_started") == []
    assert len(st.rows("SELECT * FROM segments")) == 1
    again = attempt(st, "r1", 3, now=1300, resume=True)
    assert again["outcome"] == "admitted", again
    assert [row[:3] for row in events(st, "resume_started")] == [
        ("resume_started", "r1", "seg-r1-3")
    ]


def test_ac_928_2_a_key_run_is_admitted_while_limited(st: Store) -> None:
    limited(st, "r1", now=100, resets=1000)
    registered(st, "k1", now=200, auth="key")
    assert attempt(st, "k1", 1, now=500)["outcome"] == "admitted"
    registered(st, "k2", now=200, auth="key")
    stopped(st, "k3", now=600, auth="key")
    assert attempt(st, "k3", 2, now=700, resume=True)["outcome"] == "admitted"
    before = dump(st.db)
    assert claude(st, 500, "--run-id", "k2")["verdict"] == "allow"
    assert dump(st.db) == before
    assert {row[0] for row in events(st)} == {"usage_limit"}


def test_ac_928_2_an_explicit_key_route_is_a_key_run(st: Store) -> None:
    limited(st, "r1", now=100, resets=1000)
    path = write_manifest(st, "k1", lane="tree:X:/lane-k1")
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["launch"]["auth"] = "key"
    path.write_text(json.dumps(doc), encoding="utf-8")
    facts = ("--cli-version", "9.9.9", "--kit-revision", "kitrev-fixture")
    st.ok("register", "--run-id", "k1", "--manifest", str(path), *facts)
    st.ok("registered", "--run-id", "k1", "--task-hash", "taskhash-k1")
    assert attempt(st, "k1", 1, now=500)["outcome"] == "admitted"


def test_ac_928_2_the_preview_says_the_store_verdict_and_adds_no_row(st: Store) -> None:
    limited(st, "r1", now=100, resets=1000)
    before = dump(st.db)
    parked = claude(st, 1299)
    assert parked["verdict"] == "parked_quota"
    assert parked["limited"] is True
    assert parked["window"] == 1
    assert parked["running"] == 0
    assert parked["resets_at_utc"] == at(1000)
    assert parked["retry_after_utc"] == at(1300)
    free = claude(st, 1300)
    assert (free["verdict"], free["limited"]) == ("allow", False)
    assert dump(st.db) == before


def test_ac_928_2_the_preview_refuses_an_unknown_run(st: Store) -> None:
    out = quota(st.db, "admit", "--kind", "claude", "--run-id", "nobody")
    assert out.code == 3, out.show()


def test_ac_928_2_the_window_counts_the_open_subscription_segments(st: Store) -> None:
    registered(st, "k1", auth="key")
    opened(st, "k1", now=10)
    for number in (1, 2, 3):
        registered(st, f"r{number}")
    opened(st, "r1", now=20)
    ended(st, "r1", now=25)
    opened(st, "r2", now=30)
    opened(st, "r3", now=40)
    registered(st, "r4")
    assert attempt(st, "r4", 1, now=50)["outcome"] == "admitted"
    assert st.one("SELECT state FROM segments WHERE run_id = 'r4'") == "launching"
    registered(st, "r5")
    answer = attempt(st, "r5", 1, now=60)
    assert (answer["outcome"], answer["reason"]) == ("rejected", "at_capacity")
    assert run_state(st, "r5") == "waiting"
    assert events(st, "start_parked") == []
    shown = claude(st, 60)
    assert (shown["verdict"], shown["running"], shown["window"]) == (
        "at_capacity",
        3,
        3,
    )
    ended(st, "r2", now=70)
    assert attempt(st, "r5", 2, now=80)["outcome"] == "admitted"


def test_ac_928_2_an_earlier_reason_stays_first(st: Store) -> None:
    limited(st, "r1", now=100, resets=1000)
    registered(st, "r2", now=200)
    st.write(
        "INSERT INTO lanes (lane, segment_id, claimed_utc)"
        " VALUES ('tree:X:/lane-r2', 'seg-r1-1', ?)",
        (at(0),),
    )
    assert attempt(st, "r2", 1, now=500)["reason"] == "lane_busy"
    assert events(st, "start_parked") == []


def test_ac_928_2_two_admits_at_one_time_do_not_both_take_the_last_slot(
    st: Store,
) -> None:
    for run in ("r1", "r2", "r3", "r4"):
        registered(st, run)
    opened(st, "r1", now=10)
    opened(st, "r2", now=20)
    accepted(st, "r3", 1, now=40)
    accepted(st, "r4", 1, now=40)
    lock = sqlite3.connect(st.db, isolation_level=None, timeout=30)
    procs: list[subprocess.Popen[str]] = []
    try:
        # Both processes wait for the write lock, so their two transactions follow at once.
        lock.execute("BEGIN IMMEDIATE")
        for run in ("r3", "r4"):
            procs.append(
                subprocess.Popen(
                    cli_argv(st.db, "admit", *admit_args(run, 1), now=40),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    env=child_env(st.env()),
                    cwd=ROOT,
                )
            )
        time.sleep(2)
        assert [proc.poll() for proc in procs] == [None, None]
        lock.execute("ROLLBACK")
    finally:
        lock.close()
    answers = []
    for proc in procs:
        out, err = proc.communicate(timeout=120)
        answers.append(parse_out(proc.returncode, out, err))
    assert [answer.code for answer in answers] == [0, 0], [a.show() for a in answers]
    said = sorted(
        str(a.payload.get("reason") or a.payload["outcome"])
        for a in answers
        if a.payload is not None
    )
    assert said == ["admitted", "at_capacity"]
    held = st.one("SELECT COUNT(*) FROM segments WHERE finalized_utc IS NULL")
    assert held == 3


def test_ac_928_2_a_crash_leaves_the_parked_start_and_its_event_or_neither(
    st: Store,
) -> None:
    limited(st, "r1", now=100, resets=1000)
    for number, point in enumerate(BASE_POINTS, start=2):
        run = f"r{number}"
        registered(st, run, now=200)
        accepted(st, run, 1, now=500)
        before = dump(st.db)
        env = {"CREDITS_TEST_CRASH_AT": f"admit:{point}"}
        out = st.cli("admit", *admit_args(run, 1), now=500, env=env)
        assert out.code == 9, out.show()
        parked = [row for row in events(st, "start_parked") if row[1] == run]
        if point == "after_commit":
            assert len(parked) == 1 and run_state(st, run) == "waiting"
        else:
            assert dump(st.db) == before


def test_ac_928_2_the_class_and_its_event_land_in_one_transaction(st: Store) -> None:
    args = {
        "usage_limit": class_args("r1", "usage_limit", resets=1000),
        "done": class_args("r2", "done", to="done"),
    }
    for run in ("r1", "r2"):
        registered(st, run)
        opened(st, run, now=10)
        ended(st, run, now=20)
    for verb_args, kind in ((args["usage_limit"], "usage_limit"), (args["done"], "")):
        wanted = kind or "clean_end"
        for point in BASE_POINTS:
            before = dump(st.db)
            env = {"CREDITS_TEST_CRASH_AT": f"classify:{point}"}
            out = st.cli("classify", *verb_args, now=100, env=env)
            assert out.code == 9, out.show()
            if point == "after_commit":
                assert len(events(st, wanted)) == 1
            else:
                assert dump(st.db) == before
        again = st.ok("classify", *verb_args, now=110, expect=("no_change",))
        assert again["state"] in ("stopped", "done")
        assert len(events(st, wanted)) == 1
    assert events(st) == [
        ("usage_limit", "r1", "seg-r1-1", at(1000)),
        ("clean_end", "r2", "seg-r2-1", None),
    ]


def test_ac_928_2_only_a_limit_or_a_clean_end_of_a_subscription_run_is_an_event(
    st: Store,
) -> None:
    stopped(st, "r1", now=100, stop_class="decision")
    registered(st, "r2", now=100)
    opened(st, "r2", now=110)
    ended(st, "r2", now=120)
    unverified = class_args("r2", "done_unverified", to="done_unverified")
    st.ok("classify", *unverified, now=130)
    stopped(st, "k1", now=200, stop_class="usage_limit", resets=1000, auth="key")
    registered(st, "k2", now=300, auth="key")
    opened(st, "k2", now=310)
    ended(st, "k2", now=320)
    st.ok("classify", *class_args("k2", "done", to="done"), now=330)
    assert events(st) == []
    limited(st, "r3", now=400)
    assert events(st) == [("usage_limit", "r3", "seg-r3-1", None)]


@pytest.mark.parametrize("kind", OWNED)
def test_ac_928_2_record_refuses_a_kind_that_the_store_owns(
    st: Store, kind: str
) -> None:
    out = quota(st.db, "record", "--event", kind)
    assert out.code == 3, out.show()
    assert out.error == "event_owned_by_store"
    assert events(st) == []


@pytest.mark.parametrize("kind", [*OWNED, "nonsense", ""])
def test_ac_928_2_quota_event_takes_only_the_governor_kinds(
    st: Store, kind: str
) -> None:
    out = st.cli("quota_event", "--kind", kind)
    assert out.code == 3, out.show()
    assert events(st) == []


def test_ac_928_2_quota_event_checks_its_fields(st: Store) -> None:
    limited(st, "r1", now=100, resets=1000)
    before = dump(st.db)
    for args in (
        ("--run-id", "nobody"),
        ("--segment-id", "seg-nobody"),
        ("--resets-at", str(epoch(1000))),
    ):
        out = st.cli("quota_event", "--kind", "codex_limit", *args, now=200)
        assert out.code == 3, out.show()
    assert dump(st.db) == before
    good = ("--run-id", "r1", "--segment-id", "seg-r1-1", "--detail", "a note")
    st.ok("quota_event", "--kind", "codex_limit", *good, now=200)
    row = st.rows("SELECT at_utc, detail FROM quota_events WHERE kind = 'codex_limit'")
    assert row == [(at(200), "a note")]
    assert events(st, "codex_limit") == [("codex_limit", "r1", "seg-r1-1", None)]


def test_ac_928_2_quota_event_writes_its_row_or_nothing(st: Store) -> None:
    assert cs.CRASH_POINTS["quota_event"] == BASE_POINTS
    assert cs.CRASH_POINTS["quota_view"] == ()
    for point in BASE_POINTS:
        env = {"CREDITS_TEST_CRASH_AT": f"quota_event:{point}"}
        out = st.cli("quota_event", "--kind", "codex_limit", env=env)
        assert out.code == 9, out.show()
        assert len(events(st)) == (1 if point == "after_commit" else 0)


def test_ac_928_2_quota_view_holds_the_events_and_the_state(st: Store) -> None:
    limited(st, "r1", now=100, resets=1000)
    registered(st, "r2", now=200)
    opened(st, "r2", now=1400)
    before = dump(st.db)
    view = st.ok("quota_view", now=1500, expect=("no_change",))
    assert [event["kind"] for event in view["events"]] == ["usage_limit"]
    assert [event["seq"] for event in view["events"]] == [1]
    assert view["state"]["window"] == 1
    assert view["open_segments"] == 1
    assert "seg-r1-1" in json.dumps(view["limit_segments"])
    assert dump(st.db) == before


def test_ac_928_2_record_adds_one_row(st: Store) -> None:
    for number, kind in enumerate(("codex_limit", "codex_ok", "probe_ok"), start=1):
        answer = asked(
            st, "record", "--event", kind, "--detail", f"n {number}", now=number
        )
        assert answer is not None
    assert [row[0] for row in events(st)] == ["codex_limit", "codex_ok", "probe_ok"]
    details = st.rows("SELECT at_utc, detail FROM quota_events ORDER BY seq")
    assert details == [(at(1), "n 1"), (at(2), "n 2"), (at(3), "n 3")]


@pytest.mark.parametrize("detail", ["x" * 501, "two\nlines", "two\rlines"])
def test_ac_928_2_record_refuses_a_long_or_split_detail(st: Store, detail: str) -> None:
    out = quota(st.db, "record", "--event", "codex_limit", "--detail", detail)
    assert out.code in (2, 3), out.show()
    assert events(st) == []
    out = quota(st.db, "record", "--event", "codex_limit", "--detail", "x" * 500)
    assert out.code == 0, out.show()


@pytest.mark.parametrize(
    "db",
    [
        None,
        cs.PRODUCTION_DB,
        pytest.param(
            cs.PRODUCTION_DB.replace("/credits/state.db", "/./credits/STATE.DB"),
            marks=pytest.mark.skipif(
                sys.platform != "win32", reason="the letter case counts here"
            ),
        ),
    ],
    ids=["default", "production", "other_spelling"],
)
def test_ac_928_2_the_clock_seam_is_refused_for_the_production_store(
    db: str | None,
) -> None:
    out = quota(None if db is None else Path(db), "state", now=0)
    assert out.code == 3, out.show()
    assert out.error == "clock_seam_refused"


@pytest.mark.parametrize(
    "args",
    [
        (),
        ("nonsense",),
        ("admit",),
        ("admit", "--kind", "gemini"),
        ("record",),
        ("state", "extra"),
    ],
)
def test_ac_928_2_a_bad_command_line_is_a_usage_error(
    st: Store, args: tuple[str, ...]
) -> None:
    assert QUOTA.is_file()
    out = quota(st.db, *args)
    assert out.code == 2, out.show()


# --- AC-928.2 and AC-928.4: the launcher --------------------------------------------------


# --- AC-928.3: the tick, the probe and the monitor ----------------------------------------


# --- a probe world: a store, a token file and the stub CLI ----------------------------------

BASE_PYTHON = getattr(sys, "_base_executable", sys.executable)
# Built from parts: the value is a fixture, and no scanner reads it as a login.
TOKEN = "-".join(("fixture", "subscription", "token", "7" * 24))
TOKEN_SHA = hashlib.sha256(TOKEN.encode("utf-8")).hexdigest()
DROP_NAMES = frozenset(
    {
        "CLAUDECODE",
        "CLAUDE_CODE_ENTRYPOINT",
        "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
    }
)
DROP_PREFIXES = ("CREDITS_", "MOCK_", "STUB_", "FAKE_", "CLAUDE_CREDITS_", "ANTHROPIC_")

# The stub answers one ``-p`` call. Each call adds one JSON line to ``STUB_CLAUDE_RECORD``; the
# line holds the SHA-256 of the token and never its value.
STUB_PY = textwrap.dedent(
    """\
    import hashlib, json, os, sys, time
    from pathlib import Path

    token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    line = {
        "argv": sys.argv[1:],
        "cwd": os.getcwd(),
        "env": {
            "ANTHROPIC_API_KEY": "ANTHROPIC_API_KEY" in os.environ,
            "ANTHROPIC_AUTH_TOKEN": "ANTHROPIC_AUTH_TOKEN" in os.environ,
            "CLAUDE_CODE_OAUTH_TOKEN_sha256": None
            if token is None
            else hashlib.sha256(token.encode("utf-8")).hexdigest(),
        },
    }
    with open(os.environ["STUB_CLAUDE_RECORD"], "a", encoding="utf-8", newline="\\n") as handle:
        handle.write(json.dumps(line) + "\\n")
    time.sleep(int(os.environ.get("STUB_CLAUDE_SLEEP_MS") or "0") / 1000.0)
    sys.stdin.buffer.read()
    sys.stdout.buffer.write(Path(os.environ["STUB_CLAUDE_STREAM"]).read_bytes())
    sys.stdout.buffer.flush()
    """
)
STUB_CMD = '@echo off\r\n"%STUB_CLAUDE_PYTHON%" -I -X utf8 "%~dp0stub_claude.py" %*\r\n'


@dataclass
class Child:
    """The exit code and the text of one child process."""

    code: int
    out: str
    err: str

    @property
    def text(self) -> str:
        return f"exit={self.code}\n--- out\n{self.out}\n--- err\n{self.err}"

    @property
    def doc(self) -> dict[str, Any]:
        """The last JSON object on stdout."""
        for line in reversed(self.out.splitlines()):
            if line.strip().startswith("{"):
                found = json.loads(line)
                assert isinstance(found, dict), self.text
                return found
        raise AssertionError(f"no JSON on stdout: {self.text}")


def run_child(argv: list[str], env: dict[str, str]) -> Child:
    """Run one child process to its end."""
    proc = subprocess.run(
        argv, input=b"", capture_output=True, env=env, timeout=240, check=False
    )
    return Child(
        proc.returncode,
        proc.stdout.decode("utf-8", "replace"),
        proc.stderr.decode("utf-8", "replace"),
    )


def follows(argv: list[str], first: str) -> str:
    """The word after the only ``first`` in ``argv``."""
    assert argv.count(first) == 1, argv
    return argv[argv.index(first) + 1]


def stream_text() -> str:
    """One stream-json fixture: an init line and a result line."""
    lines = [
        {"type": "system", "subtype": "init", "model": "stub"},
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": "STUB_RESULT_OK",
            "total_cost_usd": 0.0123,
            "stop_reason": "end_turn",
            "permission_denials": [],
        },
    ]
    return "".join(json.dumps(line) + "\n" for line in lines)


class World:
    """One temp store, token file and stub CLI."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.store = root / "store"
        self.db = self.store / "state.db"
        self.out = root / "dispatch"
        for folder in (self.store, self.out):
            folder.mkdir(parents=True)
        self.record = root / "stub-record.jsonl"
        self.token = self.file("token.txt", TOKEN + "\n")
        self.stream = self.file("stream-fixture.jsonl", stream_text())
        self.config = self.file(
            "config.json",
            json.dumps(
                {"ruling_enabled": False, "gate_wait_max_min": 0, "cache_ttl": "5m"}
            ),
        )
        self.file("stub_claude.py", STUB_PY)
        self.stub = self.file("stub_claude.cmd", STUB_CMD)

    def file(self, name: str, text: str) -> Path:
        """Write one fixture file with the exact bytes of ``text``."""
        path = self.root / name
        path.write_bytes(text.encode("utf-8"))
        return path

    def env(self, **changed: str) -> dict[str, str]:
        """The child environment without the credits, API, stub and nested-session names."""
        env = {
            name: value
            for name, value in os.environ.items()
            if name.upper() not in DROP_NAMES
            and not name.upper().startswith(DROP_PREFIXES)
        }
        env.update(
            {
                "CREDITS_TEST_EFFECT_LOG": str(self.root / "effects.jsonl"),
                "CREDITS_CONFIG": str(self.config),
                "CLAUDE_CONFIG_DIR": str(self.root / "claude-config"),
                "CLAUDE_CREDITS_TOKEN_FILE": str(self.token),
                "STUB_CLAUDE_PYTHON": BASE_PYTHON,
                "STUB_CLAUDE_RECORD": str(self.record),
                "STUB_CLAUDE_STREAM": str(self.stream),
                "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}",
            }
        )
        env.update(changed)
        return env

    def calls(self) -> list[dict[str, Any]]:
        """Each stub call, oldest first."""
        if not self.record.is_file():
            return []
        text = self.record.read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines() if line.strip()]


@pytest.fixture
def world(tmp_path: Path) -> World:
    """A private probe world; the credits monitor is a Windows script."""
    if sys.platform != "win32":
        pytest.skip("the credits monitor is a Windows script")
    return World(tmp_path / "world")


def resume_command(run: str) -> str:
    return (
        "pwsh -NoProfile -File .agent/skills/claude-credits/Start-CreditsRunTask.ps1"
        f" -RunId {run} -StartedBy human-command -Resume -ResumeMode session"
    )


def test_ac_928_3_the_resume_is_due_300_s_after_the_reset(st: Store) -> None:
    limited(st, "r1", now=100, resets=1000)
    early = asked(st, "tick", now=1299)
    assert set(early) >= {
        "window",
        "limited",
        "probe_due",
        "resumes_due",
        "parked_starts",
        "breaker",
    }
    assert (early["limited"], early["resumes_due"]) == (True, [])
    due = asked(st, "tick", now=1300)
    assert due["limited"] is False
    assert due["probe_due"] is False
    assert due["window"] == 1
    assert due["resumes_due"] == [
        {
            "run_id": "r1",
            "segment_id": "seg-r1-1",
            "resets_at_utc": at(1000),
            "due_utc": at(1300),
            "command": resume_command("r1"),
        }
    ]


def test_ac_928_3_a_resume_with_a_later_segment_is_not_listed(st: Store) -> None:
    limited(st, "r1", now=100, resets=1000)
    opened(st, "r1", 2, now=1300, resume=True)
    assert asked(st, "tick", now=1310)["resumes_due"] == []
    ended(st, "r1", 2, now=1320)
    st.ok("classify", *class_args("r1", "decision"), now=1330)
    assert asked(st, "tick", now=1340)["resumes_due"] == []


def test_ac_928_3_a_cancelled_run_is_not_listed(st: Store) -> None:
    limited(st, "r1", now=100, resets=1000)
    st.ok("cancel", "--run-id", "r1", now=200)
    assert asked(st, "tick", now=1300)["resumes_due"] == []


def test_ac_928_3_a_probe_is_due_after_1800_s_with_no_reset_time(st: Store) -> None:
    limited(st, "r1", now=100)
    early = asked(st, "tick", now=1899)
    assert (early["limited"], early["probe_due"]) == (True, False)
    assert asked(st, "tick", now=1900)["probe_due"] is True
    asked(st, "record", "--event", "probe_fail", now=1900)
    failed = asked(st, "tick", now=3699)
    assert (failed["limited"], failed["probe_due"], failed["resumes_due"]) == (
        True,
        False,
        [],
    )
    assert claude(st, 3699)["verdict"] == "parked_quota"
    assert asked(st, "tick", now=3700)["probe_due"] is True
    asked(st, "record", "--event", "probe_ok", now=3700)
    done = asked(st, "tick", now=3701)
    assert (done["limited"], done["probe_due"]) == (False, False)
    assert [(r["run_id"], r["command"]) for r in done["resumes_due"]] == [
        ("r1", resume_command("r1"))
    ]
    assert claude(st, 3701)["verdict"] == "allow"
    assert attempt(st, "r1", 2, now=3710, resume=True)["outcome"] == "admitted"


def test_ac_928_3_a_probe_is_not_due_when_the_reset_time_is_known(st: Store) -> None:
    limited(st, "r1", now=100, resets=90000)
    later = asked(st, "tick", now=9000)
    assert (later["limited"], later["probe_due"]) == (True, False)


def test_ac_928_3_a_probe_ok_before_the_limit_does_not_end_it(st: Store) -> None:
    asked(st, "record", "--event", "probe_ok", now=50)
    limited(st, "r1", now=100, resets=1000)
    assert asked(st, "tick", now=500)["limited"] is True
    asked(st, "record", "--event", "probe_ok", now=600)
    assert asked(st, "tick", now=601)["limited"] is False


def governor() -> ModuleType:
    """The governor module; imported in the test so that its absence is a failed test."""
    return importlib.import_module("tools.orch_quota")


@pytest.mark.parametrize(
    "words",
    [
        ("tick",),
        ("state",),
        ("admit", "--kind", "claude"),
        ("admit", "--kind", "codex", "--running", "0"),
        ("record", "--event", "codex_ok"),
        ("breaker-reset", "--by", "the fixture human"),
    ],
    ids=lambda words: "-".join(words[:3]),
)
def test_ac_928_3_the_governor_starts_only_the_store_call(
    st: Store,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    words: tuple[str, ...],
) -> None:
    limited(st, "r1", now=100, resets=1000)
    module = governor()
    started: list[list[str]] = []

    class SpyPopen(subprocess.Popen):  # type: ignore[type-arg]
        def __init__(self, args: Any, *rest: Any, **named: Any) -> None:
            started.append([str(word) for word in args])
            super().__init__(args, *rest, **named)

    monkeypatch.setattr(subprocess, "Popen", SpyPopen)
    code = module.main(["--db", str(st.db), "--now-utc", at(1300), *words])
    assert code == 0, capsys.readouterr()
    assert json.loads(capsys.readouterr().out)
    assert started
    for argv in started:
        assert argv[:2] == [sys.executable, "-I"], argv
        assert Path(argv[2]).resolve() == STATE_TOOL.resolve(), argv
        assert follows(argv, "--db") == str(st.db)
        assert {"quota_event", "quota_view"} & set(argv), argv


WATCH_DRIVER = textwrap.dedent(
    r"""
    param([string]$Watch, [string]$Db, [string]$Out, [string]$Now, [string]$Sent)
    Set-StrictMode -Version Latest
    $ErrorActionPreference = 'Stop'
    $clock = [datetime]::Parse($Now, [System.Globalization.CultureInfo]::InvariantCulture, [System.Globalization.DateTimeStyles]::AdjustToUniversal)
    $notifier = { param($notice) [System.IO.File]::AppendAllText($Sent, (($notice | ConvertTo-Json -Compress -Depth 8) + "`n")) }.GetNewClosure()
    & $Watch -StateDb $Db -OutputDir $Out -NowUtc $clock -Notifier $notifier -HostEvents @()
    exit $LASTEXITCODE
    """
)
PROBE_DRIVER = textwrap.dedent(
    r"""
    param([string]$Module, [string]$Db, [string]$Now)
    Set-StrictMode -Version Latest
    $ErrorActionPreference = 'Stop'
    Import-Module -Name $Module -Force -DisableNameChecking
    $clock = [datetime]::Parse($Now, [System.Globalization.CultureInfo]::InvariantCulture, [System.Globalization.DateTimeStyles]::AdjustToUniversal)
    try { $answer = Invoke-CreditsQuotaProbe -StateDb $Db -NowUtc $clock }
    catch { $answer = [ordered]@{ thrown = $_.Exception.Message } }
    [Console]::Out.WriteLine((ConvertTo-Json -InputObject $answer -Compress -Depth 6))
    """
)


def monitor(world: World, now: int, **changed: str) -> Child:
    """One monitor pass at ``T0 + now``."""
    driver = world.file("watch-driver.ps1", WATCH_DRIVER)
    words = ["-Watch", str(WATCH), "-Db", str(world.db), "-Out", str(world.out)]
    words += ["-Now", at(now), "-Sent", str(world.root / "sent.jsonl")]
    child = run_child(
        ["pwsh", "-NoProfile", "-File", str(driver), *words], world.env(**changed)
    )
    assert child.code == 0, child.text
    assert child.doc["outcome"] == "pass", child.text
    return child


def probe(world: World, now: int, **changed: str) -> Child:
    """One direct call of the probe function at ``T0 + now``."""
    driver = world.file("probe-driver.ps1", PROBE_DRIVER)
    words = ["-Module", str(MODULE), "-Db", str(world.db), "-Now", at(now)]
    return run_child(
        ["pwsh", "-NoProfile", "-File", str(driver), *words], world.env(**changed)
    )


def store_of(world: World) -> Store:
    """The store of a ``World`` with the helpers of this module."""
    store = Store(world.store)
    store.init()
    return store


def notice_keys(st: Store, kind: str) -> list[str]:
    rows = st.rows(
        "SELECT notice_key FROM notices WHERE kind = ? ORDER BY notice_key", (kind,)
    )
    return [str(row[0]) for row in rows]


def sent_count(world: World, kind: str) -> int:
    path = world.root / "sent.jsonl"
    text = path.read_text(encoding="utf-8-sig") if path.is_file() else ""
    return sum(f"{kind}:" in line for line in text.splitlines())


def test_ac_928_3_the_monitor_files_the_due_resume_once(world: World) -> None:
    st = store_of(world)
    limited(st, "r1", now=100, resets=1000, exe=world.stub)
    monitor(world, 1299)
    assert notice_keys(st, "quota_resume_due") == []
    monitor(world, 1300)
    monitor(world, 1360)
    assert notice_keys(st, "quota_resume_due") == ["quota_resume_due:r1:seg-r1-1"]
    row = st.rows(
        "SELECT run_id, ref, body_json FROM notices WHERE kind = 'quota_resume_due'"
    )[0]
    assert row[:2] == ("r1", "r1:seg-r1-1")
    assert json.loads(row[2])["command"] == resume_command("r1")
    assert sent_count(world, "quota_resume_due") == 1
    assert run_state(st, "r1") == "stopped"
    assert world.calls() == []


def test_ac_928_3_the_monitor_runs_the_due_probe(world: World) -> None:
    st = store_of(world)
    limited(st, "r1", now=100, exe=world.stub)
    monitor(world, 1899)
    assert world.calls() == []
    monitor(world, 1900)
    calls = world.calls()
    assert len(calls) == 1, calls
    argv = calls[0]["argv"]
    assert follows(argv, "-p") == "Reply with the word OK."
    assert follows(argv, "--output-format") == "stream-json"
    assert follows(argv, "--max-turns") == "1"
    assert follows(argv, "--permission-mode") == "dontAsk"
    assert "--verbose" in argv
    assert len(argv) == 9, argv
    folder = Path(calls[0]["cwd"])
    assert world.store.resolve() in folder.resolve().parents
    assert calls[0]["env"]["ANTHROPIC_API_KEY"] is False
    assert calls[0]["env"]["ANTHROPIC_AUTH_TOKEN"] is False
    assert calls[0]["env"]["CLAUDE_CODE_OAUTH_TOKEN_sha256"] == TOKEN_SHA
    assert [row[0] for row in events(st)] == ["usage_limit", "probe_ok"]
    monitor(world, 1960)
    assert len(world.calls()) == 1
    assert notice_keys(st, "quota_resume_due") == ["quota_resume_due:r1:seg-r1-1"]


REJECTED = {
    "type": "rate_limit_event",
    "rate_limit_info": {"status": "rejected", "resetsAt": 1792579800},
}
ERROR_RESULT = {"type": "result", "subtype": "success", "is_error": True, "result": "x"}


@pytest.mark.parametrize("case", ["rejected", "is_error", "no_result", "timeout"])
def test_ac_928_3_a_failed_probe_keeps_the_limit(world: World, case: str) -> None:
    st = store_of(world)
    limited(st, "r1", now=100, exe=world.stub)
    extra: dict[str, str] = {}
    if case == "rejected":
        world.file("stream-fixture.jsonl", json.dumps(REJECTED) + "\n" + stream_text())
    elif case == "is_error":
        world.file("stream-fixture.jsonl", json.dumps(ERROR_RESULT) + "\n")
    elif case == "no_result":
        world.file("stream-fixture.jsonl", "{}\n")
    else:
        extra = {
            "STUB_CLAUDE_SLEEP_MS": "5000",
            "CREDITS_TEST_PROBE_TIMEOUT_MS": "300",
        }
    child = probe(world, 1900, **extra)
    assert child.code == 0, child.text
    assert [row[0] for row in events(st)] == ["usage_limit", "probe_fail"], child.text
    after = asked(st, "tick", now=1901)
    assert (after["limited"], after["probe_due"]) == (True, False)


def test_ac_928_3_a_wrong_token_file_is_a_failed_probe(world: World) -> None:
    st = store_of(world)
    limited(st, "r1", now=100, exe=world.stub)
    world.token.write_text("", encoding="utf-8")
    child = probe(world, 1900)
    assert child.code == 0, child.text
    assert world.calls() == []
    assert [row[0] for row in events(st)] == ["usage_limit", "probe_fail"]
    detail = st.one("SELECT detail FROM quota_events WHERE kind = 'probe_fail'")
    assert "token_missing" in str(detail)


# --- AC-928.4: the breaker ----------------------------------------------------------------


def stop_four(st: Store) -> None:
    """Four stopped subscription runs, each ready for a resume."""
    for number in (1, 2, 3, 4):
        stopped(st, f"r{number}", now=number * 100)


def restart(st: Store, run: str, now: int) -> dict[str, Any]:
    """One admitted resume, then the end of its segment."""
    answer = attempt(st, run, 2, now=now, resume=True)
    if answer["outcome"] == "admitted":
        ended(st, run, 2, now=now + 1)
    return answer


def test_ac_928_4_three_restarts_in_an_hour_open_the_breaker(st: Store) -> None:
    stop_four(st)
    for run, now in (("r1", 2000), ("r2", 3000)):
        assert restart(st, run, now)["outcome"] == "admitted"
    assert events(st, "breaker_open") == []
    assert claude(st, 3000)["verdict"] == "allow"
    assert restart(st, "r3", 5600)["outcome"] == "admitted"
    assert [row[1:3] for row in events(st, "resume_started")] == [
        ("r1", "seg-r1-2"),
        ("r2", "seg-r2-2"),
        ("r3", "seg-r3-2"),
    ]
    cause = st.one("SELECT detail FROM quota_events WHERE kind = 'breaker_open'")
    assert all(run in str(cause) for run in ("r1", "r2", "r3")), cause

    refused = restart(st, "r4", 5700)
    assert (refused["outcome"], refused["reason"]) == ("rejected", "breaker_open")
    assert run_state(st, "r4") == "stopped"
    registered(st, "s1", now=5700)
    start = attempt(st, "s1", 1, now=90000)
    assert (start["outcome"], start["reason"]) == ("rejected", "breaker_open")
    assert run_state(st, "s1") == "waiting"
    assert events(st, "start_parked") == []
    assert claude(st, 90000)["verdict"] == "breaker_open"
    assert codex(st, 90000)["verdict"] == "breaker_open"
    shown = asked(st, "tick", now=90000)["breaker"]
    assert shown["open"] is True
    assert all(run in json.dumps(shown) for run in ("r1", "r2", "r3"))

    asked(st, "breaker-reset", "--by", "the fixture human", now=90100)
    assert len(events(st, "breaker_reset")) == 1
    detail = st.one("SELECT detail FROM quota_events WHERE kind = 'breaker_reset'")
    assert "the fixture human" in str(detail)
    assert claude(st, 90100)["verdict"] == "allow"
    assert codex(st, 90100)["verdict"] == "allow"
    assert asked(st, "tick", now=90100)["breaker"]["open"] is False
    assert attempt(st, "s1", 2, now=90200)["outcome"] == "admitted"


def test_ac_928_4_three_restarts_in_3601_s_leave_it_closed(st: Store) -> None:
    stop_four(st)
    for run, now in (("r1", 2000), ("r2", 3000), ("r3", 5601)):
        assert restart(st, run, now)["outcome"] == "admitted"
    assert events(st, "breaker_open") == []
    assert claude(st, 5602)["verdict"] == "allow"
    assert restart(st, "r4", 6600)["outcome"] == "admitted"
    assert len(events(st, "breaker_open")) == 1
    cause = str(st.one("SELECT detail FROM quota_events WHERE kind = 'breaker_open'"))
    assert "r1" not in cause and "r4" in cause


def test_ac_928_4_the_restarts_before_a_reset_do_not_count(st: Store) -> None:
    stop_four(st)
    for run, now in (("r1", 2000), ("r2", 2100), ("r3", 2200)):
        assert restart(st, run, now)["outcome"] == "admitted"
    asked(st, "breaker-reset", "--by", "the fixture human", now=2300)
    assert restart(st, "r4", 2400)["outcome"] == "admitted"
    assert len(events(st, "breaker_open")) == 1
    assert claude(st, 2500)["verdict"] == "allow"


def test_ac_928_4_a_start_is_not_a_restart(st: Store) -> None:
    for number in (1, 2, 3):
        registered(st, f"r{number}")
        opened(st, f"r{number}", now=10 * number)
        ended(st, f"r{number}", now=10 * number + 2)
    assert events(st) == []
    assert claude(st, 100)["verdict"] == "allow"


def test_ac_928_4_the_breaker_comes_before_the_limit(st: Store) -> None:
    for now in (100, 200, 300):
        add_event(st, "resume_started", now=now)
    add_event(st, "usage_limit", now=400, resets=1000)
    registered(st, "r1", now=400)
    assert attempt(st, "r1", 1, now=500)["reason"] == "breaker_open"
    assert claude(st, 500)["verdict"] == "breaker_open"


@pytest.mark.parametrize("args", [(), ("--by",), ("--by", ""), ("--by", "  ")])
def test_ac_928_4_a_reset_names_the_human(st: Store, args: tuple[str, ...]) -> None:
    assert QUOTA.is_file()
    out = quota(st.db, "breaker-reset", *args)
    assert out.code in (2, 3), out.show()
    assert events(st) == []


def test_ac_928_4_a_crash_leaves_the_segment_and_its_events_or_neither(
    st: Store,
) -> None:
    stop_four(st)
    restart(st, "r1", 2000)
    restart(st, "r2", 2100)
    accepted(st, "r3", 2, now=2200, resume=True)
    before = dump(st.db)
    for point in BASE_POINTS:
        env = {"CREDITS_TEST_CRASH_AT": f"admit:{point}"}
        out = st.cli("admit", *admit_args("r3", 2), now=2200, env=env)
        assert out.code == 9, out.show()
        if point != "after_commit":
            assert dump(st.db) == before
            assert len(events(st, "resume_started")) == 2
    assert len(events(st, "resume_started")) == 3
    assert len(events(st, "breaker_open")) == 1
    assert st.one("SELECT COUNT(*) FROM segments WHERE segment_id = 'seg-r3-2'") == 1
    st.ok("admit", *admit_args("r3", 2), now=2201, expect=("no_change",))
    assert len(events(st, "resume_started")) == 3


def test_ac_928_4_an_open_breaker_stops_the_probe(world: World) -> None:
    st = store_of(world)
    limited(st, "r1", now=100, exe=world.stub)
    assert asked(st, "tick", now=1900)["probe_due"] is True
    for now in (200, 300, 400):
        add_event(st, "resume_started", now=now, run="r1")
    assert asked(st, "tick", now=1900)["probe_due"] is False
    child = probe(world, 1900)
    assert "probe_refused breaker_open" in child.out, child.text
    monitor(world, 1900)
    monitor(world, 1960)
    assert not world.record.exists()
    assert [row[0] for row in events(st) if row[0].startswith("probe")] == []
    assert len(notice_keys(st, "quota_breaker_open")) == 1
    assert sent_count(world, "quota_breaker_open") == 1


# --- AC-928.5: the Codex wait -------------------------------------------------------------


@pytest.mark.parametrize(
    ("limits", "wait"), [(1, 300), (2, 600), (3, 1200), (4, 2400), (5, 3600), (9, 3600)]
)
def test_ac_928_5_the_wait_grows_with_each_limit(
    st: Store, limits: int, wait: int
) -> None:
    for number in range(limits):
        add_event(st, "codex_limit", now=number)
    last = limits - 1
    refused = codex(st, last + wait - 1)
    assert refused["verdict"] == "codex_backoff"
    assert refused["retry_after_utc"] == at(last + wait)
    free = codex(st, last + wait)
    assert (free["verdict"], free["retry_after_utc"]) == ("allow", None)


def test_ac_928_5_a_good_reply_starts_the_count_again(st: Store) -> None:
    for number in range(4):
        asked(st, "record", "--event", "codex_limit", now=number)
    assert codex(st, 10)["verdict"] == "codex_backoff"
    asked(st, "record", "--event", "codex_ok", now=20)
    assert codex(st, 20)["verdict"] == "allow"
    asked(st, "record", "--event", "codex_limit", now=30)
    assert codex(st, 30)["retry_after_utc"] == at(330)


def test_ac_928_5_a_claude_limit_does_not_change_the_codex_wait(st: Store) -> None:
    limited(st, "r1", now=100, resets=1000)
    add_event(st, "usage_limit", now=200)
    assert codex(st, 300)["verdict"] == "allow"
    asked(st, "record", "--event", "codex_limit", now=300)
    assert codex(st, 301)["retry_after_utc"] == at(600)


def test_ac_928_5_the_running_reviews_are_below_the_review_cap(st: Store) -> None:
    from tools import orch

    assert codex(st, 0, orch.REVIEW_CAP - 1)["verdict"] == "allow"
    full = codex(st, 0, orch.REVIEW_CAP)
    assert full["verdict"] == "at_capacity"
    assert full["running"] == orch.REVIEW_CAP
    assert codex(st, 0, 64)["verdict"] == "at_capacity"


def test_ac_928_5_the_review_cap_is_read_from_its_owner(
    st: Store,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from tools import orch

    monkeypatch.setattr(orch, "REVIEW_CAP", 7)
    module = governor()
    for running, verdict in ((6, "allow"), (7, "at_capacity")):
        words = ["admit", "--kind", "codex", "--running", str(running)]
        assert module.main(["--db", str(st.db), "--now-utc", at(0), *words]) == 0
        assert json.loads(capsys.readouterr().out)["verdict"] == verdict


def test_ac_928_5_the_wait_comes_before_the_capacity(st: Store) -> None:
    asked(st, "record", "--event", "codex_limit", now=0)
    assert codex(st, 10, 64)["verdict"] == "codex_backoff"


@pytest.mark.parametrize(
    "args",
    [
        ("--kind", "claude", "--running", "0"),
        ("--kind", "codex", "--running", "65"),
        ("--kind", "codex", "--running", "-1"),
        ("--kind", "codex", "--running", "two"),
    ],
)
def test_ac_928_5_a_wrong_running_count_is_refused(
    st: Store, args: tuple[str, ...]
) -> None:
    assert QUOTA.is_file()
    out = quota(st.db, "admit", *args)
    assert out.code in (2, 3), out.show()


# --- AC-928.7: the migration --------------------------------------------------------------


def old_store(db: Path, schema: int) -> None:
    """A store of ``schema`` with one run and one segment."""
    with contextlib.closing(sqlite3.connect(db)) as con:
        for step in range(1, schema + 1):
            for statement in cs.SCHEMA_STEPS[step]:
                con.execute(statement)
        con.execute(f"PRAGMA user_version = {schema}")
        when = "2026-10-16T09:00:00Z"
        con.execute(
            "INSERT INTO runs (run_id, state, kind, supervision, created_utc, updated_utc) "
            "VALUES ('old', 'stopped', 'exec', 'job', ?, ?)",
            (when, when),
        )
        con.execute(
            "INSERT INTO segments (segment_id, run_id, supervision, job, state, created_utc, "
            "updated_utc) VALUES ('old-seg', 'old', 'job', 1, 'finalized', ?, ?)",
            (when, when),
        )
        con.commit()


def columns(db: Path) -> set[str]:
    """The column names of the segments table."""
    with contextlib.closing(sqlite3.connect(db)) as con:
        return {str(row[1]) for row in con.execute("PRAGMA table_info(segments)")}


def version(db: Path) -> int:
    """The schema version of a store."""
    with contextlib.closing(sqlite3.connect(db)) as con:
        return int(con.execute("PRAGMA user_version").fetchone()[0])


def has_events(db: Path) -> bool:
    with contextlib.closing(sqlite3.connect(db)) as con:
        found = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'quota_events'"
        ).fetchone()
    return found is not None


def kept(db: Path) -> tuple[Any, ...]:
    with contextlib.closing(sqlite3.connect(db)) as con:
        return (
            con.execute("SELECT run_id, state, kind FROM runs").fetchall(),
            con.execute("SELECT segment_id, run_id, state FROM segments").fetchall(),
        )


OLD_ROWS = ([("old", "stopped", "exec")], [("old-seg", "old", "finalized")])


def test_ac_928_7_the_store_version_is_11() -> None:
    assert cs.SCHEMA_VERSION == 11
    assert set(cs.SCHEMA_STEPS) == set(range(1, 12))


def test_ac_928_7_a_v10_store_migrates_at_each_crash_point(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    old_store(source, 10)
    for point in cs.CRASH_POINTS["init"]:
        db = tmp_path / point / "state.db"
        db.parent.mkdir()
        shutil.copy2(source, db)
        crashed = run_cli(db, "init", env={"CREDITS_TEST_CRASH_AT": f"init:{point}"})
        assert crashed.code == 9, crashed.show()
        done = point == "after_commit"
        assert (version(db), has_events(db)) == ((11, True) if done else (10, False))
        assert kept(db) == OLD_ROWS
        again = run_cli(db, "init")
        assert again.code == 0, again.show()
        assert (version(db), has_events(db)) == (11, True)
        assert kept(db) == OLD_ROWS


def test_ac_928_7_a_v8_store_gets_the_columns_of_three_versions(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    old_store(db, 8)
    out = run_cli(db, "init")
    assert out.code == 0, out.show()
    assert version(db) == 11
    assert columns(db) >= {"auth_method", "cli_version", "resets_at_utc"}
    with contextlib.closing(sqlite3.connect(db)) as con:
        info = con.execute("PRAGMA table_info(quota_events)").fetchall()
    assert [(row[1], row[2], row[3], row[5]) for row in info] == [
        ("seq", "INTEGER", 0, 1),
        ("at_utc", "TEXT", 1, 0),
        ("kind", "TEXT", 1, 0),
        ("run_id", "TEXT", 0, 0),
        ("segment_id", "TEXT", 0, 0),
        ("resets_at_utc", "TEXT", 0, 0),
        ("detail", "TEXT", 0, 0),
    ]
    assert kept(db) == OLD_ROWS


def test_ac_928_7_a_newer_store_is_refused(st: Store) -> None:
    with contextlib.closing(sqlite3.connect(st.db)) as con:
        con.execute("PRAGMA user_version = 12")
    out = st.cli("quota_view")
    assert out.code == 3, out.show()
    assert out.error == "schema_too_new"
    assert quota(st.db, "state").code == 3
