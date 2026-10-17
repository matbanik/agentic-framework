"""S2a store: ``tools/credits_state.py`` (Component B).

Plan: docs/execution/plans/2026-10-15-scheduled-credits-runs (Component B,
AC-B.1, AC-B.2, AC-B.4, AC-B.5, AC-B.6 and AC-B.10; report R§4.1, R§4.2,
R§4.3, R§4.4, R§4.7 and R§7.2; acceptance matrix MX-1, MX-2, MX-3, MX-8,
MX-21, MX-30, MX-35 and MX-43, the S2a parts). The crash points of AC-B.3 and
the effect windows of MX-22 are in ``test_credits_state_crash.py``.

The tests drive the store only through its CLI, in a subprocess, with a temp
store per test (AC-B.10). They fix this CLI contract:

* ``credits_state.py --db <path> [--now-utc <ISO Z>] [--profile cli|launcher|monitor|hook]
  <verb> [flags]``.
* stdout is one JSON object. ``result`` is one of ``changed``, ``no_change``,
  ``ok``, ``conflict``, ``refused``, ``failed``, ``busy`` or ``usage_error``.
  ``error`` holds the code of a refusal.
* Exit 0: changed, no_change or ok. Exit 1: ``check`` found a failure. Exit 2:
  usage error (an unknown verb, flag or crash point), and the store is not
  opened for writing. Exit 3: refused or conflict. Exit 75: busy after 3 tries.
* ``--now-utc`` is the store clock (R§4.7 wait seams: accept at 119 s and
  120 s, orphan at 150 s and 151 s, effect retry at 300 s and 301 s). The
  tests never sleep.
* ``CREDITS_TEST_EFFECT_LOG=<file>``: the test effect executor appends one JSON
  line ``{"key": ...}`` per performed effect, in place of the real effect.
* ``CREDITS_TEST_BUSY_TIMEOUT_MS=<n>``: a test-only busy timeout.
* Ids are optional inputs (``--request-id``, ``--attempt-id``, ``--segment-id``
  and so on), so two runs of one verb on equal stores write equal rows.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "credits_state.py"
REAL_DB = Path("{{RECEIPTS_DIR}}/credits/state.db")
T0 = datetime(2026, 10, 15, 12, 0, 0, tzinfo=UTC)
LANE = "tree:X:/fixture-tree"
BOOT = "boot-fixture-1"
SESSION_A = "aaaaaaaa-0000-4000-8000-000000000001"
SESSION_B = "bbbbbbbb-0000-4000-8000-000000000002"

STORE_TABLES = frozenset(
    {
        "runs",
        "requests",
        "attempts",
        "segments",
        "lanes",
        "exposures",
        "gates",
        "messages",
        "deliveries",
        "outbox_events",
        "consumed_rulings",
        "attaches",
        "orchestrator_sessions",
        "transcript_marks",
        "queue_chains",
        "landings",
        "drift_accepts",
        "notices",
        "effects",
        "transitions",
        "monitor_lease",
        "cursors",
    }
)


def real_db_state() -> str:
    """Return ``absent`` or the SHA-256 of the real store file (read as bytes only)."""
    if not REAL_DB.exists():
        return "absent"
    return hashlib.sha256(REAL_DB.read_bytes()).hexdigest()


REAL_DB_STATE_AT_IMPORT = real_db_state()


def at(seconds: int) -> str:
    """Return the store clock value ``T0 + seconds`` as an ISO UTC string."""
    return (T0 + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Out:
    """One CLI call: exit code, parsed stdout JSON and the raw streams."""

    code: int
    payload: dict[str, Any] | None
    stdout: str
    stderr: str

    @property
    def result(self) -> str | None:
        return None if self.payload is None else self.payload.get("result")

    @property
    def error(self) -> str | None:
        return None if self.payload is None else self.payload.get("error")

    def show(self) -> str:
        return f"exit={self.code}\nstdout={self.stdout[-1500:]}\nstderr={self.stderr[-1500:]}"


def child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Return the parent environment without any ``CREDITS_*`` value, plus ``extra``."""
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("CREDITS_")}
    if extra:
        env.update(extra)
    return env


def cli_argv(
    db: Path | str,
    verb: str,
    *args: str,
    now: int | None = 0,
    profile: str | None = None,
) -> list[str]:
    """Return the argv of one ``credits_state.py`` call."""
    argv = [sys.executable, str(TOOL), "--db", str(db)]
    if now is not None:
        argv += ["--now-utc", at(now)]
    if profile is not None:
        argv += ["--profile", profile]
    return [*argv, verb, *args]


def parse_out(code: int, stdout: str, stderr: str) -> Out:
    """Parse the one JSON object on stdout; ``payload`` is None when there is none."""
    payload: dict[str, Any] | None = None
    text = stdout.strip()
    if text:
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError:
            loaded = None
        if isinstance(loaded, dict):
            payload = loaded
    return Out(code, payload, stdout, stderr)


def run_cli(
    db: Path | str,
    verb: str,
    *args: str,
    now: int | None = 0,
    profile: str | None = None,
    env: dict[str, str] | None = None,
    timeout: float = 60.0,
) -> Out:
    """Run one verb in a subprocess and return its result."""
    proc = subprocess.run(
        cli_argv(db, verb, *args, now=now, profile=profile),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=child_env(env),
        timeout=timeout,
        cwd=ROOT,
        check=False,
    )
    return parse_out(proc.returncode, proc.stdout, proc.stderr)


@dataclass(frozen=True)
class Store:
    """A temp store folder: ``state.db``, the test effect log and the manifests."""

    root: Path

    @property
    def db(self) -> Path:
        return self.root / "state.db"

    @property
    def effect_log(self) -> Path:
        return self.root / "effects.jsonl"

    def env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        return {"CREDITS_TEST_EFFECT_LOG": str(self.effect_log), **(extra or {})}

    def cli(
        self,
        verb: str,
        *args: str,
        now: int | None = 0,
        profile: str | None = None,
        env: dict[str, str] | None = None,
    ) -> Out:
        return run_cli(
            self.db, verb, *args, now=now, profile=profile, env=self.env(env)
        )

    def ok(
        self,
        verb: str,
        *args: str,
        now: int = 0,
        expect: tuple[str, ...] = ("changed",),
    ) -> dict[str, Any]:
        out = self.cli(verb, *args, now=now)
        assert out.code == 0 and out.result in expect, f"{verb} {args}: {out.show()}"
        assert out.payload is not None
        return out.payload

    def init(self) -> None:
        self.ok("init", expect=("changed", "no_change"))

    def rows(self, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        with contextlib.closing(sqlite3.connect(self.db)) as con:
            return con.execute(sql, params).fetchall()

    def one(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        found = self.rows(sql, params)
        assert len(found) == 1, f"{sql} {params}: {found}"
        return found[0][0]

    def write(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        with contextlib.closing(sqlite3.connect(self.db)) as con:
            con.execute(sql, params)
            con.commit()

    def logged_effects(self) -> list[str]:
        if not self.effect_log.exists():
            return []
        lines = self.effect_log.read_text(encoding="utf-8").splitlines()
        return [str(json.loads(line)["key"]) for line in lines if line.strip()]


def dump(db: Path) -> dict[str, list[tuple[Any, ...]]]:
    """Return every row of every table, sorted, plus ``user_version``."""
    with contextlib.closing(sqlite3.connect(db)) as con:
        names = [
            r[0]
            for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            )
        ]
        out: dict[str, list[tuple[Any, ...]]] = {}
        for name in names:
            rows = con.execute(f'SELECT * FROM "{name}"').fetchall()
            out[name] = sorted(rows, key=repr)
        out["__user_version__"] = [tuple(con.execute("PRAGMA user_version").fetchone())]
        return out


@pytest.fixture
def st(tmp_path: Path) -> Store:
    return Store(tmp_path)


# --- lifecycle helpers (shared with test_credits_state_crash.py) -------------


def write_manifest(
    st: Store,
    run_id: str,
    *,
    lane: str = LANE,
    run_cap: float = 200.0,
    segment_cap: float = 75.0,
) -> Path:
    """Write a ``credits-run.v1`` manifest (R§4.1) with fixture values only."""
    manifest = {
        "schema": "credits-run.v1",
        "run_id": run_id,
        "kind": "exec",
        "project_root": "X:/fixture-project",
        "plan_folder": "docs/execution/plans/2026-10-15-fixture/",
        "brief": "C:/Temp/fixture/brief.md",
        "launch": {
            "working_directory": "X:/fixture-project",
            "claude_exe": "C:/fixture/claude.cmd",
            "python_exe": "C:/fixture/python.exe",
            "permission_mode": "bypassPermissions",
            "model": "fixture-model",
            "effort": "high",
            "segment_cap_usd": segment_cap,
            "timeout_sec": 43200,
        },
        "budget": {"run_cap_usd": run_cap},
        "messaging": {
            "orchestrator_sessions": ["00000000-0000-4000-8000-0000000000aa"],
            "ruling_enabled": False,
            "gate_wait_max_min": 0,
        },
        "depends_on": [],
        "lane": lane,
    }
    # The file name never carries the raw id: a test may pass an id that is
    # not a valid path part (for example "../escape").
    name_key = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:16]
    path = st.root / f"manifest-{name_key}.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def register_args(st: Store, run_id: str, **manifest_kw: Any) -> tuple[str, ...]:
    manifest = write_manifest(st, run_id, **manifest_kw)
    return (
        "--run-id",
        run_id,
        "--manifest",
        str(manifest),
        "--cli-version",
        "9.9.9",
        "--kit-revision",
        "kitrev-fixture",
    )


def register(st: Store, run_id: str, *, now: int = 0, **manifest_kw: Any) -> None:
    st.ok("register", *register_args(st, run_id, **manifest_kw), now=now)


def make_registered(
    st: Store, run_id: str, *, now: int = 0, **manifest_kw: Any
) -> None:
    register(st, run_id, now=now, **manifest_kw)
    st.ok(
        "registered", "--run-id", run_id, "--task-hash", f"taskhash-{run_id}", now=now
    )


def request_args(run_id: str, n: int, *, resume: bool = False) -> tuple[str, ...]:
    args = (
        "--run-id",
        run_id,
        "--started-by",
        "human-command",
        "--request-id",
        f"req-{run_id}-{n}",
    )
    return (*args, "--resume") if resume else args


def accept_args(run_id: str, n: int, session: str) -> tuple[str, ...]:
    return (
        "--run-id",
        run_id,
        "--launcher-pid",
        "4242",
        "--launcher-created",
        at(-600),
        "--boot-id",
        BOOT,
        "--win-session",
        "1",
        "--attempt-id",
        f"att-{run_id}-{n}",
        "--dispatch-id",
        f"disp-{run_id}-{n}",
        "--expected-session-id",
        session,
    )


def launched_args(segment_id: str, now: int) -> tuple[str, ...]:
    return (
        "--segment-id",
        segment_id,
        "--pid",
        "5151",
        "--created",
        at(now),
        "--boot-id",
        BOOT,
    )


@dataclass(frozen=True)
class Seg:
    run_id: str
    request_id: str
    attempt_id: str
    segment_id: str
    session: str


def start_segment(
    st: Store,
    run_id: str,
    n: int,
    *,
    now: int,
    session: str = SESSION_A,
    resume: bool = False,
    launch: bool = True,
) -> Seg:
    """Request, accept, admit and (when ``launch``) launch segment ``n`` of a run."""
    st.ok("request", *request_args(run_id, n, resume=resume), now=now)
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
    return Seg(run_id, f"req-{run_id}-{n}", f"att-{run_id}-{n}", segment_id, session)


def first_start(
    st: Store,
    run_id: str,
    *,
    now: int = 0,
    launch: bool = True,
    session: str = SESSION_A,
    **manifest_kw: Any,
) -> Seg:
    make_registered(st, run_id, now=now, **manifest_kw)
    return start_segment(st, run_id, 1, now=now + 1, session=session, launch=launch)


def complete_args(
    segment_id: str,
    *,
    by: str = "launcher",
    cls: str = "exited",
    total: float | None = None,
) -> tuple[str, ...]:
    args = ("--segment-id", segment_id, "--finalized-by", by, "--class", cls)
    return (*args, "--session-total-usd", f"{total}") if total is not None else args


def finish(
    st: Store,
    seg: Seg,
    *,
    now: int,
    total: float | None = None,
    by: str = "launcher",
    cls: str = "exited",
) -> dict[str, Any]:
    return st.ok(
        "complete_segment",
        *complete_args(seg.segment_id, by=by, cls=cls, total=total),
        now=now,
    )


def stop(st: Store, run_id: str, *, now: int) -> None:
    st.ok(
        "classify",
        "--run-id",
        run_id,
        "--to",
        "stopped",
        "--class",
        "context_exhausted",
        now=now,
    )


def minimal_args(
    run_id: str, segment_id: str, *, omit: str | None = None
) -> tuple[str, ...]:
    """Return the ``register_minimal`` flags (R§7.2 step 2), less ``omit``."""
    pairs = [
        ("--run-id", run_id),
        ("--segment-id", segment_id),
        ("--wrapper-pid", "6161"),
        ("--wrapper-created", at(-30)),
        ("--boot-id", BOOT),
        ("--win-session", "1"),
        ("--job-name", "Local\\{{PROJECT_NAME_UPPER}}Credits-" + segment_id),
        ("--expected-session-id", SESSION_B),
    ]
    return tuple(
        part for flag, value in pairs if flag != omit for part in (flag, value)
    )


def run_state(st: Store, run_id: str) -> str:
    return str(st.one("SELECT state FROM runs WHERE run_id = ?", (run_id,)))


def check_ok(st: Store, now: int) -> None:
    out = st.cli("check", now=now)
    assert out.code == 0 and out.result == "ok", out.show()


def spend(st: Store, run_id: str, now: int) -> dict[str, Any]:
    return st.ok("spend", "--run-id", run_id, now=now, expect=("ok",))


def held_lanes(st: Store) -> int:
    return int(st.one("SELECT COUNT(*) FROM lanes WHERE segment_id IS NOT NULL"))


def transitions(st: Store, entity: str, entity_id: str) -> list[tuple[Any, ...]]:
    return st.rows(
        "SELECT from_state, to_state, verb FROM transitions WHERE entity = ? AND entity_id = ? ORDER BY rowid",
        (entity, entity_id),
    )


# --- AC-B.1: init, settings, schema, refusals --------------------------------


def test_init_creates_store_tables_and_connection_settings(st: Store) -> None:
    """AC-B.1: ``init`` creates the R§4.7 tables with WAL, synchronous=FULL and 30 s busy_timeout."""
    out = st.cli("init")
    assert out.code == 0 and out.result == "changed", out.show()
    assert out.payload is not None
    names = {
        r[0] for r in st.rows("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert STORE_TABLES <= names, sorted(STORE_TABLES - names)
    assert str(st.one("PRAGMA journal_mode")).lower() == "wal"
    assert int(st.one("PRAGMA user_version")) >= 1
    connection = out.payload["connection"]
    assert connection["journal_mode"] == "wal"
    assert connection["synchronous"] == 2  # FULL
    assert connection["foreign_keys"] == 1
    assert connection["busy_timeout_ms"] == 30000


@pytest.mark.parametrize(
    ("profile", "timeout_ms"),
    [("cli", 30000), ("launcher", 30000), ("monitor", 30000), ("hook", 5000)],
)
def test_busy_timeout_follows_the_caller_profile(
    st: Store, profile: str, timeout_ms: int
) -> None:
    """AC-B.1: busy_timeout is 30 s for the CLI, launcher and monitor, and 5 s for the hook (R§4.7 rule 5)."""
    st.init()
    out = st.cli("check", profile=profile)
    assert out.code == 0 and out.result == "ok", out.show()
    assert out.payload is not None
    assert out.payload["connection"]["busy_timeout_ms"] == timeout_ms


def test_second_init_changes_nothing(st: Store) -> None:
    """AC-B.1: a second ``init`` returns ``no_change`` and leaves every row and the version as they were."""
    st.init()
    before = dump(st.db)
    out = st.cli("init", now=99)
    assert out.code == 0 and out.result == "no_change", out.show()
    assert dump(st.db) == before


def test_check_passes_on_a_fresh_store(st: Store) -> None:
    """AC-B.1: ``check`` passes on a fresh store."""
    st.init()
    out = st.cli("check")
    assert out.code == 0 and out.result == "ok", out.show()


def _unique_column_sets(
    con: sqlite3.Connection, table: str
) -> tuple[set[tuple[str, ...]], list[str]]:
    sets: set[tuple[str, ...]] = set()
    partial_sql: list[str] = []
    pk = tuple(
        r[1]
        for r in sorted(
            con.execute(f'PRAGMA table_info("{table}")'), key=lambda r: r[5]
        )
        if r[5] > 0
    )
    if pk:
        sets.add(pk)
    for _seq, name, unique, _origin, partial in con.execute(
        f'PRAGMA index_list("{table}")'
    ):
        if not unique:
            continue
        cols = tuple(r[2] for r in con.execute(f'PRAGMA index_info("{name}")'))
        if partial:
            sql = con.execute(
                "SELECT sql FROM sqlite_master WHERE name = ?", (name,)
            ).fetchone()
            partial_sql.append(f"{cols}:{(sql or [''])[0]}")
        else:
            sets.add(cols)
    return sets, partial_sql


def test_store_keys_and_unique_constraints(st: Store) -> None:
    """AC-B.1: the R§4.7 keys and unique constraints, and one open gate per run (partial unique index)."""
    st.init()
    expected = {
        "runs": ("run_id",),
        "requests": ("request_id",),
        "attempts": ("request_id",),
        "segments": ("attempt_id",),
        "exposures": ("segment_id",),
        "messages": ("run_id", "seq"),
        "outbox_events": ("semantic_key",),
        "consumed_rulings": ("orchestrator_session", "prompt_id"),
        "attaches": ("orchestrator_session", "prompt_id"),
        "queue_chains": ("session", "delivery_id"),
        "notices": ("notice_key",),
        "effects": ("effect_key",),
    }
    with contextlib.closing(sqlite3.connect(st.db)) as con:
        for table, cols in expected.items():
            sets, _ = _unique_column_sets(con, table)
            assert any(set(s) == set(cols) for s in sets), f"{table}: {sorted(sets)}"
        _, partial = _unique_column_sets(con, "gates")
    assert any("run_id" in p and "open" in p and "state" in p for p in partial), partial


def test_unc_store_path_is_refused_store_not_local(tmp_path: Path) -> None:
    """AC-B.1: a UNC path → ``store_not_local``, refused before the store is opened."""
    out = run_cli(r"\\fixture-host\share\state.db", "init")
    assert (
        out.code == 3 and out.result == "refused" and out.error == "store_not_local"
    ), out.show()
    assert list(tmp_path.iterdir()) == []


def test_newer_schema_version_is_refused(st: Store) -> None:
    """AC-B.1: a store with a newer ``user_version`` than the tool knows is refused, unchanged."""
    st.init()
    version = int(st.one("PRAGMA user_version"))
    st.write(f"PRAGMA user_version = {version + 1}")
    for verb, args in (("check", ()), ("register", register_args(st, "run-new"))):
        out = st.cli(verb, *args)
        assert (
            out.code == 3 and out.result == "refused" and out.error == "schema_too_new"
        ), out.show()
    assert int(st.one("PRAGMA user_version")) == version + 1
    assert int(st.one("SELECT COUNT(*) FROM runs")) == 0


def test_corrupt_store_fails_check_and_admission(st: Store) -> None:
    """AC-B.1: a corrupt store file → ``check`` exits non-zero and admission refuses (R§12)."""
    st.db.write_bytes(b"this is not a sqlite database " * 200)
    out = st.cli("check")
    assert out.code != 0 and out.result == "failed" and out.error == "store_corrupt", (
        out.show()
    )
    out = st.cli("admit", "--attempt-id", "att-x-1", "--segment-id", "seg-x-1")
    assert out.code != 0 and out.error == "store_corrupt", out.show()


def test_failed_check_blocks_admission_until_cleared(st: Store) -> None:
    """AC-B.1: an invariant failure sets the store flag; ``admit`` refuses until ``clear_check``."""
    make_registered(st, "run-stale")
    st.ok("request", *request_args("run-stale", 1), now=0)
    make_registered(st, "run-a", now=600, lane="tree:X:/other-tree")
    st.ok("request", *request_args("run-a", 1), now=650)
    st.ok("accept", *accept_args("run-a", 1, SESSION_A), now=655)

    out = st.cli("check", now=700)
    assert out.code == 1 and out.result == "failed", out.show()
    assert out.payload is not None
    assert "request_stale_pending" in {f["invariant"] for f in out.payload["failures"]}

    out = st.cli(
        "admit", "--attempt-id", "att-run-a-1", "--segment-id", "seg-run-a-1", now=701
    )
    assert (
        out.code == 3 and out.result == "refused" and out.error == "store_check_failed"
    ), out.show()
    assert int(st.one("SELECT COUNT(*) FROM segments")) == 0
    assert run_state(st, "run-a") == "launching"

    st.ok("scan_requests", now=702)
    check_ok(st, 703)
    out = st.cli(
        "admit", "--attempt-id", "att-run-a-1", "--segment-id", "seg-run-a-1", now=704
    )
    assert out.error == "store_check_failed", out.show()

    st.ok(
        "clear_check",
        "--note",
        "fixture: stale request cleaned by scan_requests",
        now=705,
    )
    admitted = st.ok(
        "admit", "--attempt-id", "att-run-a-1", "--segment-id", "seg-run-a-1", now=706
    )
    assert admitted["outcome"] == "admitted"


def _break_requested_without_pending(st: Store) -> None:
    make_registered(st, "run-x")
    st.ok("request", *request_args("run-x", 1), now=1)
    st.write("UPDATE requests SET state = 'rejected' WHERE request_id = 'req-run-x-1'")


def _break_finalized_without_cost(st: Store) -> None:
    seg = first_start(st, "run-x")
    finish(st, seg, now=20)
    st.write("DELETE FROM exposures")


def _break_manual_identity(st: Store) -> None:
    st.init()
    st.ok("register_minimal", *minimal_args("run-m", "seg-m-1"), now=1)
    st.write("UPDATE segments SET job_name = NULL WHERE segment_id = 'seg-m-1'")


def _break_lane(st: Store) -> None:
    first_start(st, "run-x")
    st.ok("register_minimal", *minimal_args("run-m", "seg-m-1"), now=12)
    st.write("UPDATE segments SET lane = ? WHERE segment_id = 'seg-m-1'", (LANE,))


@pytest.mark.parametrize(
    ("invariant", "breaker"),
    [
        ("requested_without_pending", _break_requested_without_pending),
        ("finalized_without_cost", _break_finalized_without_cost),
        ("manual_identity_missing", _break_manual_identity),
        ("lane_multi_segment", _break_lane),
    ],
)
def test_check_names_each_broken_invariant(
    st: Store, invariant: str, breaker: Any
) -> None:
    """AC-B.1: ``check`` runs the R§4.7 rule-6 invariants and names the one that fails."""
    breaker(st)
    out = st.cli("check", now=30)
    assert out.code == 1 and out.result == "failed", out.show()
    assert out.payload is not None
    assert invariant in {f["invariant"] for f in out.payload["failures"]}, out.payload


# --- AC-B.2: transitions ------------------------------------------------------


def test_first_start_lifecycle_writes_one_transition_per_change(st: Store) -> None:
    """AC-B.2: each state change of the R§4.7 table appends one ``transitions`` row; ``check`` passes throughout."""
    make_registered(st, "run-a")
    assert run_state(st, "run-a") == "registered"
    seg = start_segment(st, "run-a", 1, now=10, launch=False)
    assert run_state(st, "run-a") == "launching"
    check_ok(st, 17)
    st.ok("launched", *launched_args(seg.segment_id, 17), now=17)
    assert run_state(st, "run-a") == "running"
    check_ok(st, 18)
    finish(st, seg, now=30, total=12.5)
    assert run_state(st, "run-a") == "finalizing"
    check_ok(st, 31)
    st.ok("classify", "--run-id", "run-a", "--to", "done", "--class", "done", now=32)
    assert run_state(st, "run-a") == "done"
    check_ok(st, 33)

    assert transitions(st, "run", "run-a") == [
        (None, "registering", "register"),
        ("registering", "registered", "registered"),
        ("registered", "requested", "request"),
        ("requested", "launching", "accept"),
        ("launching", "running", "launched"),
        ("running", "finalizing", "complete_segment"),
        ("finalizing", "done", "classify"),
    ]
    assert transitions(st, "request", seg.request_id) == [
        (None, "pending", "request"),
        ("pending", "accepted", "accept"),
        ("accepted", "admitted", "admit"),
        ("admitted", "launched", "launched"),
    ]
    assert transitions(st, "attempt", seg.attempt_id) == [
        (None, "accepted", "accept"),
        ("accepted", "admitted", "admit"),
        ("admitted", "launched", "launched"),
    ]
    assert transitions(st, "segment", seg.segment_id) == [
        (None, "launching", "admit"),
        ("launching", "running", "launched"),
        ("running", "finalized", "complete_segment"),
    ]
    assert (
        int(
            st.one("SELECT COUNT(*) FROM transitions WHERE owner IS NULL OR owner = ''")
        )
        == 0
    )


def _registered(st: Store) -> tuple[str, tuple[str, ...]]:
    make_registered(st, "run-a")
    return "registered", ()


def _requested(st: Store) -> tuple[str, tuple[str, ...]]:
    make_registered(st, "run-a")
    st.ok("request", *request_args("run-a", 1), now=1)
    return "requested", ()


def _done(st: Store) -> tuple[str, tuple[str, ...]]:
    seg = first_start(st, "run-a")
    finish(st, seg, now=20, total=1.0)
    st.ok("classify", "--run-id", "run-a", "--to", "done", "--class", "done", now=21)
    return "done", ()


@pytest.mark.parametrize(
    ("setup", "verb", "args"),
    [
        (
            _registered,
            "classify",
            ("--run-id", "run-a", "--to", "done", "--class", "done"),
        ),
        (
            _registered,
            "registration_failed",
            ("--run-id", "run-a", "--reason", "fixture"),
        ),
        (_requested, "request", request_args("run-a", 2)),
        (_done, "cancel", ("--run-id", "run-a")),
        (_done, "request", request_args("run-a", 2, resume=True)),
    ],
    ids=[
        "classify-registered",
        "regfail-registered",
        "request-requested",
        "cancel-done",
        "resume-done",
    ],
)
def test_transition_outside_the_table_is_refused(
    st: Store, setup: Any, verb: str, args: tuple[str, ...]
) -> None:
    """AC-B.2: a transition outside the R§4.7 table → ``invalid_transition``; state and transitions unchanged."""
    state, _ = setup(st)
    count = int(st.one("SELECT COUNT(*) FROM transitions"))
    out = st.cli(verb, *args, now=40)
    assert (
        out.code == 3 and out.result == "refused" and out.error == "invalid_transition"
    ), out.show()
    assert run_state(st, "run-a") == state
    assert int(st.one("SELECT COUNT(*) FROM transitions")) == count


def test_not_started_after_accept_is_a_conflict(st: Store) -> None:
    """AC-B.2: the compare-and-set of ``not_started`` sees ``accepted`` → ``conflict``; it never overwrites."""
    make_registered(st, "run-a")
    st.ok("request", *request_args("run-a", 1), now=0)
    st.ok("accept", *accept_args("run-a", 1, SESSION_A), now=60)
    count = int(st.one("SELECT COUNT(*) FROM transitions"))
    out = st.cli(
        "not_started",
        "--request-id",
        "req-run-a-1",
        "--reason",
        "caller_timeout",
        now=120,
    )
    assert out.code == 3 and out.result == "conflict", out.show()
    assert (
        st.one("SELECT state FROM requests WHERE request_id = 'req-run-a-1'")
        == "accepted"
    )
    assert run_state(st, "run-a") == "launching"
    assert int(st.one("SELECT COUNT(*) FROM transitions")) == count


def test_busy_store_exits_75_and_writes_nothing(st: Store) -> None:
    """AC-B.2: a verb takes the write lock with BEGIN IMMEDIATE; held elsewhere → 3 tries, then exit 75."""
    register(st, "run-a")
    count = int(st.one("SELECT COUNT(*) FROM transitions"))
    holder = sqlite3.connect(st.db, isolation_level=None)
    try:
        holder.execute("BEGIN IMMEDIATE")
        out = st.cli(
            "registered",
            "--run-id",
            "run-a",
            "--task-hash",
            "taskhash-run-a",
            env={"CREDITS_TEST_BUSY_TIMEOUT_MS": "50"},
        )
        holder.execute("ROLLBACK")
    finally:
        holder.close()
    assert out.code == 75 and out.result == "busy", out.show()
    assert run_state(st, "run-a") == "registering"
    assert int(st.one("SELECT COUNT(*) FROM transitions")) == count


@pytest.mark.parametrize(
    ("age", "outcome"), [(119, "accepted"), (120, "stale_at_launcher")]
)
def test_accept_age_boundary(st: Store, age: int, outcome: str) -> None:
    """AC-B.2: accept takes a pending request younger than 120 s; at 120 s it is ``stale_at_launcher``."""
    make_registered(st, "run-a")
    st.ok("request", *request_args("run-a", 1), now=0)
    out = st.ok("accept", *accept_args("run-a", 1, SESSION_A), now=age)
    assert out["outcome"] == outcome
    request = st.rows(
        "SELECT state, reason FROM requests WHERE request_id = 'req-run-a-1'"
    )
    if outcome == "accepted":
        assert request[0][0] == "accepted"
        assert run_state(st, "run-a") == "launching"
        assert int(st.one("SELECT COUNT(*) FROM attempts")) == 1
    else:
        assert request == [("not_started", "stale_at_launcher")]
        assert run_state(st, "run-a") == "registered"
        assert int(st.one("SELECT COUNT(*) FROM attempts")) == 0
        assert int(st.one("SELECT COUNT(*) FROM notices")) == 1
    check_ok(st, age + 1)


def test_orphan_request_age_boundary(st: Store) -> None:
    """AC-B.2: ``scan_requests`` leaves a 150 s request; at 151 s it is ``not_started`` (orphan), noticed once."""
    make_registered(st, "run-a")
    st.ok("request", *request_args("run-a", 1), now=0)
    st.ok("scan_requests", now=150, expect=("no_change",))
    assert st.one("SELECT state FROM requests") == "pending"
    st.ok("scan_requests", now=151)
    assert st.rows("SELECT state, reason FROM requests") == [("not_started", "orphan")]
    assert run_state(st, "run-a") == "registered"
    st.ok("scan_requests", now=152, expect=("no_change",))
    assert int(st.one("SELECT COUNT(*) FROM notices")) == 1
    check_ok(st, 153)


@pytest.mark.parametrize(
    "argv",
    [("frobnicate",), ("init", "--bogus"), ("check", "--run-id", "run-a")],
    ids=["unknown-verb", "unknown-flag-init", "unknown-flag-check"],
)
def test_unknown_verb_or_flag_is_a_usage_error_and_writes_nothing(
    tmp_path: Path, argv: tuple[str, ...]
) -> None:
    """AC-B.2 boundary: an unknown verb or flag → exit 2; the store is not created or opened for writing."""
    db = tmp_path / "state.db"
    out = run_cli(db, *argv)
    assert out.code == 2 and out.result == "usage_error", out.show()
    assert not db.exists()


@pytest.mark.parametrize(
    "omit",
    [
        "--run-id",
        "--segment-id",
        "--wrapper-pid",
        "--wrapper-created",
        "--boot-id",
        "--win-session",
        "--job-name",
        "--expected-session-id",
    ],
)
def test_register_minimal_requires_every_identity_field(st: Store, omit: str) -> None:
    """AC-B.2 boundary: ``register_minimal`` without one identity field → exit 2 and no row."""
    st.init()
    out = st.cli("register_minimal", *minimal_args("run-m", "seg-m-1", omit=omit))
    assert out.code == 2 and out.result == "usage_error", out.show()
    assert int(st.one("SELECT COUNT(*) FROM runs")) == 0
    assert int(st.one("SELECT COUNT(*) FROM segments")) == 0


def test_run_id_outside_the_key_format_is_a_usage_error(st: Store) -> None:
    """AC-B.2 boundary: a run id with path characters → exit 2 and no row."""
    st.init()
    out = st.cli("register", *register_args(st, "../escape"))
    assert out.code == 2 and out.result == "usage_error", out.show()
    assert int(st.one("SELECT COUNT(*) FROM runs")) == 0


# --- AC-B.4: concurrency (MX-8) ----------------------------------------------


def _race(
    st: Store, first: tuple[str, ...], second: tuple[str, ...], now: int
) -> list[Out]:
    procs = [
        subprocess.Popen(
            cli_argv(st.db, *argv, now=now),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=child_env(st.env()),
            cwd=ROOT,
        )
        for argv in (first, second)
    ]
    outs: list[Out] = []
    for proc in procs:
        stdout, stderr = proc.communicate(timeout=90)
        outs.append(parse_out(proc.returncode, stdout, stderr))
    return outs


@pytest.mark.parametrize("round_no", [1, 2, 3])
def test_mx_8_two_finalizers_race_and_one_wins(tmp_path: Path, round_no: int) -> None:
    """AC-B.4 / MX-8: launcher and monitor finalize at once; exactly one changes, the other gets ``no_change``."""
    st = Store(tmp_path)
    seg = first_start(st, f"run-r{round_no}")
    outs = _race(
        st,
        ("complete_segment", *complete_args(seg.segment_id, by="launcher")),
        ("complete_segment", *complete_args(seg.segment_id, by="monitor")),
        now=40,
    )
    assert all(o.code == 0 for o in outs), [o.show() for o in outs]
    assert sorted(str(o.result) for o in outs) == ["changed", "no_change"], [
        o.show() for o in outs
    ]
    winner = "launcher" if outs[0].result == "changed" else "monitor"
    assert (
        st.one(
            "SELECT finalized_by FROM segments WHERE segment_id = ?", (seg.segment_id,)
        )
        == winner
    )
    finals = [
        t for t in transitions(st, "segment", seg.segment_id) if t[1] == "finalized"
    ]
    assert len(finals) == 1
    assert int(st.one("SELECT COUNT(*) FROM exposures")) == 1
    assert held_lanes(st) == 0
    check_ok(st, 41)


def test_two_registered_writers_race_and_one_wins(st: Store) -> None:
    """AC-B.4: two ``registered`` writers on one run; exactly one changes, the other gets ``no_change``."""
    register(st, "run-a")
    args = ("registered", "--run-id", "run-a", "--task-hash", "taskhash-run-a")
    outs = _race(st, args, args, now=5)
    assert all(o.code == 0 for o in outs), [o.show() for o in outs]
    assert sorted(str(o.result) for o in outs) == ["changed", "no_change"], [
        o.show() for o in outs
    ]
    assert (
        transitions(st, "run", "run-a").count(
            ("registering", "registered", "registered")
        )
        == 1
    )


def test_mx_8_second_finalize_is_no_change(st: Store) -> None:
    """AC-B.4 / MX-8: a second ``complete_segment`` returns ``no_change`` and changes no row."""
    seg = first_start(st, "run-a")
    finish(st, seg, now=30)
    before = dump(st.db)
    out = st.cli(
        "complete_segment", *complete_args(seg.segment_id, by="monitor"), now=31
    )
    assert out.code == 0 and out.result == "no_change", out.show()
    assert dump(st.db) == before


# --- AC-B.5: cost and exposure (MX-1, MX-2, MX-21) ---------------------------


def test_mx_1_resume_total_keeps_crash_exposure_open(st: Store) -> None:
    """AC-B.5 / MX-1: a crash opens an exposure; a later total of the same session never releases it."""
    seg1 = first_start(st, "run-a")
    finish(st, seg1, now=20)
    assert st.rows(
        "SELECT state, amount_usd FROM exposures WHERE segment_id = ?",
        (seg1.segment_id,),
    ) == [("open", 75.0)]
    stop(st, "run-a", now=21)
    seg2 = start_segment(st, "run-a", 2, now=30, session=SESSION_A, resume=True)
    finish(st, seg2, now=50, total=30.0)
    assert st.rows(
        "SELECT state, amount_usd FROM exposures WHERE segment_id = ?",
        (seg1.segment_id,),
    ) == [("open", 75.0)]
    view = spend(st, "run-a", 51)
    assert view["known_spent_usd"] == pytest.approx(30.0)
    assert view["open_exposures_usd"] == pytest.approx(75.0)
    assert view["settled_usd"] == pytest.approx(0.0)
    assert view["open_reservations_usd"] == pytest.approx(0.0)
    check_ok(st, 52)


def test_mx_1_fresh_session_fallback_keeps_exposure_open(st: Store) -> None:
    """AC-B.5 / MX-1: a fresh-session fallback starts a new session entry; the old exposure stays open."""
    seg1 = first_start(st, "run-a", session=SESSION_A)
    finish(st, seg1, now=20)
    stop(st, "run-a", now=21)
    seg2 = start_segment(st, "run-a", 2, now=30, session=SESSION_B, resume=True)
    finish(st, seg2, now=50, total=10.0)
    view = spend(st, "run-a", 51)
    assert view["known_spent_usd"] == pytest.approx(10.0)
    assert view["open_exposures_usd"] == pytest.approx(75.0)


def test_mx_2_crashes_zero_and_regressing_totals_are_not_trusted(st: Store) -> None:
    """AC-B.5 / MX-2: two crashes in one session, a zero total and a regressing total each open an exposure."""
    seg1 = first_start(st, "run-a")
    finish(st, seg1, now=20)
    stop(st, "run-a", now=21)
    seg2 = start_segment(st, "run-a", 2, now=30, resume=True)
    finish(st, seg2, now=40, total=0.0)
    stop(st, "run-a", now=41)
    seg3 = start_segment(st, "run-a", 3, now=50, resume=True)
    assert (
        float(
            st.one(
                "SELECT reservation_usd FROM segments WHERE segment_id = ?",
                (seg3.segment_id,),
            )
        )
        == 50.0
    )
    finish(st, seg3, now=60, total=20.0)
    stop(st, "run-a", now=61)
    seg4 = start_segment(st, "run-a", 4, now=70, resume=True)
    assert (
        float(
            st.one(
                "SELECT reservation_usd FROM segments WHERE segment_id = ?",
                (seg4.segment_id,),
            )
        )
        == 30.0
    )
    finish(st, seg4, now=80, total=10.0)

    exposures = dict(
        st.rows("SELECT segment_id, amount_usd FROM exposures WHERE state = 'open'")
    )
    assert exposures == {
        seg1.segment_id: 75.0,
        seg2.segment_id: 75.0,
        seg4.segment_id: 30.0,
    }
    view = spend(st, "run-a", 81)
    assert view["known_spent_usd"] == pytest.approx(20.0)
    assert view["open_exposures_usd"] == pytest.approx(180.0)
    check_ok(st, 82)


def test_mx_21_missing_cost_opens_exposure_at_full_reservation(st: Store) -> None:
    """AC-B.5 / MX-21: subagent work or a missing output cost → exposure at the full reservation."""
    seg = first_start(st, "run-a")
    assert (
        float(
            st.one(
                "SELECT reservation_usd FROM segments WHERE segment_id = ?",
                (seg.segment_id,),
            )
        )
        == 75.0
    )
    finish(st, seg, now=20, cls="exited")
    assert st.rows("SELECT state, amount_usd FROM exposures") == [("open", 75.0)]
    out = st.cli(
        "settle",
        "--segment-id",
        seg.segment_id,
        "--source",
        "transcript",
        "--amount-usd",
        "3.10",
        now=21,
    )
    assert out.code != 0 and out.result in ("refused", "usage_error"), out.show()
    assert st.rows("SELECT state, amount_usd FROM exposures") == [("open", 75.0)]


@pytest.mark.parametrize(
    ("flags", "state", "amount"),
    [
        (("--source", "console", "--amount-usd", "41.5"), "settled_console", 41.5),
        (
            (
                "--source",
                "human",
                "--amount-usd",
                "50",
                "--note",
                "subagent spend unknown",
            ),
            "human_adjusted",
            50.0,
        ),
    ],
    ids=["console", "human"],
)
def test_settle_sources_record_their_state(
    st: Store, flags: tuple[str, ...], state: str, amount: float
) -> None:
    """AC-B.5: ``-Source console`` → ``settled_console``; ``-Source human -Note`` → ``human_adjusted``."""
    seg = first_start(st, "run-a")
    finish(st, seg, now=20)
    st.ok("settle", "--segment-id", seg.segment_id, *flags, now=21)
    assert st.rows("SELECT state, amount_usd FROM exposures") == [(state, amount)]
    view = spend(st, "run-a", 22)
    assert view["open_exposures_usd"] == pytest.approx(0.0)
    assert view["settled_usd"] == pytest.approx(amount)
    if state == "human_adjusted":
        assert st.one("SELECT note FROM exposures") == "subagent spend unknown"
    check_ok(st, 23)


@pytest.mark.parametrize(
    ("flags", "code"),
    [
        (("--source", "human", "--amount-usd", "50"), 3),
        (("--source", "transcript", "--amount-usd", "50"), None),
        (("--amount-usd", "50"), 2),
    ],
    ids=["human-without-note", "transcript", "no-source"],
)
def test_settle_refusals_leave_the_exposure_open(
    st: Store, flags: tuple[str, ...], code: int | None
) -> None:
    """AC-B.5: a human settle needs ``-Note``; a transcript sum or no source never releases an exposure."""
    seg = first_start(st, "run-a")
    finish(st, seg, now=20)
    out = st.cli("settle", "--segment-id", seg.segment_id, *flags, now=21)
    assert out.code != 0 and out.result in ("refused", "usage_error"), out.show()
    if code is not None:
        assert out.code == code, out.show()
    assert st.rows("SELECT state, amount_usd FROM exposures") == [("open", 75.0)]


def test_admission_counts_exposure_at_full_amount_and_floor(st: Store) -> None:
    """AC-B.5: the reservation subtracts open exposure at its full amount; $5 is admitted, below is refused."""
    seg1 = first_start(st, "run-a", run_cap=80.0)
    finish(st, seg1, now=20)
    stop(st, "run-a", now=21)
    seg2 = start_segment(st, "run-a", 2, now=30, resume=True)
    assert (
        float(
            st.one(
                "SELECT reservation_usd FROM segments WHERE segment_id = ?",
                (seg2.segment_id,),
            )
        )
        == 5.0
    )
    finish(st, seg2, now=40)
    stop(st, "run-a", now=41)
    st.ok("request", *request_args("run-a", 3, resume=True), now=50)
    st.ok("accept", *accept_args("run-a", 3, SESSION_A), now=55)
    out = st.ok(
        "admit", "--attempt-id", "att-run-a-3", "--segment-id", "seg-run-a-3", now=56
    )
    assert out["outcome"] == "rejected" and out["reason"] == "budget_floor"
    assert run_state(st, "run-a") == "stopped"
    assert (
        st.one("SELECT state FROM requests WHERE request_id = 'req-run-a-3'")
        == "rejected"
    )
    assert (
        int(st.one("SELECT COUNT(*) FROM segments WHERE segment_id = 'seg-run-a-3'"))
        == 0
    )
    check_ok(st, 57)


def test_first_start_below_floor_fails(st: Store) -> None:
    """AC-B.5: a first start below the $5 floor → request and attempt ``rejected``, run ``failed``."""
    make_registered(st, "run-a", run_cap=4.0)
    st.ok("request", *request_args("run-a", 1), now=1)
    st.ok("accept", *accept_args("run-a", 1, SESSION_A), now=2)
    out = st.ok(
        "admit", "--attempt-id", "att-run-a-1", "--segment-id", "seg-run-a-1", now=3
    )
    assert out["outcome"] == "rejected" and out["reason"] == "budget_floor"
    assert run_state(st, "run-a") == "failed"
    assert st.one("SELECT state FROM attempts") == "rejected"
    assert int(st.one("SELECT COUNT(*) FROM segments")) == 0
    assert held_lanes(st) == 0
    check_ok(st, 4)


def test_lane_busy_first_start_waits_then_admits(st: Store) -> None:
    """AC-B.2: a first start on a busy lane → ``waiting``; after the lane is free a new request is admitted."""
    seg_a = first_start(st, "run-a")
    make_registered(st, "run-b", now=10)
    st.ok("request", *request_args("run-b", 1), now=11)
    st.ok("accept", *accept_args("run-b", 1, SESSION_B), now=12)
    out = st.ok(
        "admit", "--attempt-id", "att-run-b-1", "--segment-id", "seg-run-b-1", now=13
    )
    assert out["outcome"] == "rejected" and out["reason"] == "lane_busy"
    assert run_state(st, "run-b") == "waiting"
    finish(st, seg_a, now=20, total=5.0)
    assert held_lanes(st) == 0
    seg_b = start_segment(st, "run-b", 2, now=30, session=SESSION_B)
    assert run_state(st, "run-b") == "running"
    assert (
        st.one("SELECT segment_id FROM lanes WHERE segment_id IS NOT NULL")
        == seg_b.segment_id
    )
    check_ok(st, 40)


# --- scan verbs with an injected job adapter (MX-3, MX-30) -------------------


def test_mx_3_launcher_dies_after_admitted_releases_once(st: Store) -> None:
    """AC-B.2 / MX-3: launcher dead after ``admitted``; job proof ``empty`` → ``launch_failed``, released once."""
    seg = first_start(st, "run-a", launch=False)
    proofs = json.dumps({seg.attempt_id: "empty"})
    st.ok("scan_attempts", "--proofs-json", proofs, now=100)
    assert st.one("SELECT state FROM requests") == "launch_failed"
    assert st.one("SELECT state FROM attempts") == "launch_failed"
    assert st.rows("SELECT state, finalized_by FROM segments") == [
        ("finalized", "monitor")
    ]
    assert run_state(st, "run-a") == "failed"
    assert held_lanes(st) == 0
    assert spend(st, "run-a", 101)["open_reservations_usd"] == pytest.approx(0.0)
    assert st.rows("SELECT state, amount_usd FROM exposures") == [("open", 75.0)]
    before = dump(st.db)
    st.ok("scan_attempts", "--proofs-json", proofs, now=102, expect=("no_change",))
    st.ok(
        "scan_segments",
        "--proofs-json",
        json.dumps({seg.segment_id: "empty"}),
        now=103,
        expect=("no_change",),
    )
    assert dump(st.db) == before
    check_ok(st, 104)


@pytest.mark.parametrize("proof", ["live", "unknown"])
def test_mx_30_live_or_unknown_job_proof_holds_the_segment(
    st: Store, proof: str
) -> None:
    """MX-30 (store part): ``live`` or ``unknown`` never finalizes; lane and reservation stay held."""
    seg = first_start(st, "run-a")
    for now in (100, 400):
        st.ok(
            "scan_segments",
            "--proofs-json",
            json.dumps({seg.segment_id: proof}),
            now=now,
            expect=("changed", "no_change"),
        )
    assert st.one("SELECT state FROM segments") == "running"
    assert held_lanes(st) == 1
    assert spend(st, "run-a", 401)["open_reservations_usd"] == pytest.approx(75.0)
    notices = int(st.one("SELECT COUNT(*) FROM notices"))
    assert notices == (1 if proof == "unknown" else 0)
    check_ok(st, 402)


# --- AC-B.6: effects ----------------------------------------------------------


@pytest.mark.parametrize(
    ("by", "keys"), [("launcher", ["evtlog", "rescan"]), ("monitor", ["rescan"])]
)
def test_complete_segment_inserts_and_performs_keyed_effects(
    st: Store, by: str, keys: list[str]
) -> None:
    """AC-B.6: ``complete_segment`` writes ``evtlog:<seg>`` (launcher only) and ``rescan:<seg>``; each runs once."""
    seg = first_start(st, "run-a")
    finish(st, seg, now=20, by=by)
    expected = sorted(f"{k}:{seg.segment_id}" for k in keys)
    assert sorted(r[0] for r in st.rows("SELECT effect_key FROM effects")) == expected
    assert sorted(st.logged_effects()) == expected
    assert int(st.one("SELECT COUNT(*) FROM effects WHERE state != 'done'")) == 0


# --- MX-35, MX-43: manual supervision (S2a parts) ----------------------------


def test_register_minimal_stores_wrapper_identity_and_holds_nothing(st: Store) -> None:
    """AC-B.2: ``register_minimal`` → ``identity_pending`` manual job segment, no lane, no reservation."""
    st.init()
    st.ok("register_minimal", *minimal_args("run-m", "seg-m-1"), now=1)
    row = st.rows(
        "SELECT state, supervision, wrapper_pid, wrapper_created, boot_id, win_session, job_name "
        "FROM segments WHERE segment_id = 'seg-m-1'"
    )
    assert row == [
        (
            "identity_pending",
            "manual",
            6161,
            at(-30),
            BOOT,
            1,
            "Local\\{{PROJECT_NAME_UPPER}}Credits-seg-m-1",
        )
    ]
    assert held_lanes(st) == 0
    check_ok(st, 2)


def test_mx_43_wrapper_dies_before_child_is_finalized_on_gone(st: Store) -> None:
    """MX-43: the wrapper dies after ``register_minimal``; admission is not blocked; ``gone`` finalizes."""
    st.init()
    st.ok("register_minimal", *minimal_args("run-m", "seg-m-1"), now=1)
    seg = first_start(st, "run-a", now=2)
    assert run_state(st, "run-a") == "running"
    st.ok("scan_segments", "--proofs-json", json.dumps({"seg-m-1": "gone"}), now=60)
    assert st.rows(
        "SELECT state, finalized_by FROM segments WHERE segment_id = 'seg-m-1'"
    ) == [("finalized", "monitor")]
    assert (
        st.one("SELECT state FROM segments WHERE segment_id = ?", (seg.segment_id,))
        == "running"
    )
    check_ok(st, 61)


def test_mx_35_wrapper_dies_after_identity_is_finalized_on_empty(st: Store) -> None:
    """MX-35: after ``manual_identity`` the wrapper dies; job proof ``empty`` finalizes the running segment."""
    st.init()
    st.ok("register_minimal", *minimal_args("run-m", "seg-m-1"), now=1)
    st.ok(
        "manual_identity",
        "--segment-id",
        "seg-m-1",
        "--pid",
        "7171",
        "--created",
        at(2),
        now=3,
    )
    assert st.rows("SELECT state, pid FROM segments") == [("running", 7171)]
    st.ok("scan_segments", "--proofs-json", json.dumps({"seg-m-1": "empty"}), now=60)
    assert st.one("SELECT state FROM segments") == "finalized"
    out = st.cli(
        "manual_identity",
        "--segment-id",
        "seg-m-1",
        "--pid",
        "7272",
        "--created",
        at(61),
        now=61,
    )
    assert out.code == 3 and out.error == "invalid_transition", out.show()
    check_ok(st, 62)


@pytest.mark.parametrize("proof", ["live", "unknown"])
def test_mx_35_identity_pending_is_never_finalized_on_live_or_unknown(
    st: Store, proof: str
) -> None:
    """MX-35: an ``identity_pending`` segment is finalized only on ``empty`` or ``gone``."""
    st.init()
    st.ok("register_minimal", *minimal_args("run-m", "seg-m-1"), now=1)
    st.ok(
        "scan_segments",
        "--proofs-json",
        json.dumps({"seg-m-1": proof}),
        now=60,
        expect=("changed", "no_change"),
    )
    assert st.one("SELECT state FROM segments") == "identity_pending"
    check_ok(st, 61)


# --- AC-B.10: the real store ----------------------------------------------------


def test_real_store_is_never_opened(st: Store) -> None:
    """AC-B.10: a full lifecycle on a temp store leaves the real ``state.db`` as it was at import."""
    seg = first_start(st, "run-a")
    finish(st, seg, now=20, total=2.0)
    assert run_state(st, "run-a") == "finalizing"
    assert real_db_state() == REAL_DB_STATE_AT_IMPORT
