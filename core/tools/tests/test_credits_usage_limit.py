"""The usage_limit class: its signals, its reset time and the stream fixtures.

The classifier tests load the functions of ``Watch-CreditsRuns.ps1`` in a pwsh harness. No test
starts the CLI, a monitor pass or a real store.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import textwrap
import time
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from test_credits_state import (
    ROOT,
    T0,
    Seg,
    Store,
    at,
    finish,
    first_start,
    run_cli,
    run_state,
)
from tools import credits_state as cs

pytestmark = pytest.mark.timeout(600)

SKILL = ROOT / ".agent" / "skills" / "claude-credits"
WATCH = SKILL / "Watch-CreditsRuns.ps1"
MODULE = SKILL / "CreditsRun.psm1"
STREAM_TOOL = ROOT / "tools" / "credits_stream.py"
STREAMS = Path(__file__).resolve().parent / "fixtures" / "orch" / "streams"
BASE_PYTHON = getattr(sys, "_base_executable", sys.executable)
RESETS_AT = 1792579800
RESETS_UTC = "2026-10-21T10:50:00Z"
LIMIT_TEXT = f"Claude AI usage limit reached|{RESETS_AT}"
RESETS_MIN = 1577836800
RESETS_MAX = int((T0 + timedelta(seconds=200, days=8)).timestamp())

# The functions and the named values of the monitor script, without its main pass.
HARNESS = textwrap.dedent(
    r"""
    param([string]$Watch, [string]$Module, [string]$Doc)
    Set-StrictMode -Version Latest
    $ErrorActionPreference = 'Stop'
    Import-Module -Name $Module -Force -DisableNameChecking
    $d = [System.IO.File]::ReadAllText($Doc) | ConvertFrom-Json -DateKind String
    $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($Watch, [ref]$null, [ref]$errors)
    if ($errors.Count) { throw "parse errors in $Watch" }
    foreach ($fn in $ast.FindAll({ $args[0] -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $false)) {
        . ([scriptblock]::Create($fn.Extent.Text))
    }
    foreach ($statement in $ast.EndBlock.Statements) {
        if ($statement -is [System.Management.Automation.Language.AssignmentStatementAst] -and
            $statement.Left.Extent.Text -match '^\$script:(\w+Pattern|StoppedGates|\w+TimeoutMs)\z') {
            . ([scriptblock]::Create($statement.Extent.Text))
        }
    }
    $HostEvents = @()
    $script:HostEventsGiven = $true
    $script:OutDir = $d.out
    $script:LogPath = $d.log
    $script:PreflightTool = $d.preflight
    $script:Db = $d.db
    $script:Clock = [datetime]::Parse($d.now, [System.Globalization.CultureInfo]::InvariantCulture, [System.Globalization.DateTimeStyles]::AdjustToUniversal)
    $script:NowTime = $script:Clock
    $script:Boot = 'fixture-boot'
    if ($d.mode -eq 'set') {
        $answer = [ordered]@{ set = [bool](Set-RunClass $d.run) }
    } else {
        $v = Get-RunClass $d.run
        $reset = $v.PSObject.Properties['ResetsAt']
        $answer = [ordered]@{ class = $v.Class; missing = @($v.Missing); signals = $v.Signals; resets_at = $(if ($reset) { $reset.Value } else { $null }) }
    }
    [Console]::Out.WriteLine(($answer | ConvertTo-Json -Compress -Depth 8))
    exit 0
    """
)
PREFLIGHT = "import json\nprint(json.dumps({'ok': True, 'missing': []}))\n"


def rejected_event(**changed: Any) -> dict[str, Any]:
    """One rate limit event with the rejected status."""
    info: dict[str, Any] = {
        "status": "rejected",
        "resetsAt": RESETS_AT,
        "rateLimitType": "five_hour",
        "overageStatus": "rejected",
    }
    info.update(changed)
    return {"type": "rate_limit_event", "rate_limit_info": info}


def result_line(**changed: Any) -> dict[str, Any]:
    """One result object of the CLI."""
    line: dict[str, Any] = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "stop_reason": "end_turn",
        "result": "ok",
        "permission_denials": [],
        "total_cost_usd": 0.0,
    }
    line.update(changed)
    return line


ERROR_RESULT = result_line(is_error=True, result=LIMIT_TEXT)


class Bench:
    """One temp dispatch folder and the pwsh harness that classifies it."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.out = root / "dispatch"
        self.folder = self.out / "d1"
        self.folder.mkdir(parents=True)
        self.harness = root / "harness.ps1"
        self.harness.write_text(HARNESS, encoding="utf-8", newline="\n")
        self.preflight = root / "preflight.py"
        self.preflight.write_text(PREFLIGHT, encoding="utf-8", newline="\n")
        self.log = root / "monitor.jsonl"

    def put(
        self,
        *,
        stream: list[dict[str, Any]] | None = None,
        output: dict[str, Any] | None = None,
        exit_code: int | None = None,
        stderr: str | None = None,
        final: str | None = None,
    ) -> None:
        """Write the artifacts of the dispatch."""
        if stream is not None:
            body = "".join(json.dumps(line) + "\n" for line in stream)
            (self.folder / "stream.jsonl").write_bytes(body.encode("utf-8"))
        if output is not None:
            (self.folder / "output.json").write_text(
                json.dumps(output), encoding="utf-8"
            )
        if exit_code is not None:
            status = {"exit_code": exit_code, "timed_out": False}
            (self.folder / "status.json").write_text(
                json.dumps(status), encoding="utf-8"
            )
        if stderr is not None:
            (self.folder / "stderr.txt").write_text(stderr, encoding="utf-8")
        if final is not None:
            (self.folder / "final.md").write_text(final, encoding="utf-8")

    def run_object(
        self, *, python: str | None = None, project: Path | None = None
    ) -> dict[str, Any]:
        """A finalizing run in the form of the store view."""
        exe = python or sys.executable
        return {
            "run_id": "r1",
            "kind": "plan",
            "python_exe": exe,
            "manifest": {
                "kind": "plan",
                "project_root": str(project or ROOT),
                "plan_folder": "docs/execution/plans/fixture",
                "launch": {"python_exe": exe},
            },
            "segment": {
                "segment_id": "s1",
                "dispatch_id": "d1",
                "stop_class": "exited",
                "exit_code": None,
                "boot_id": "fixture-boot",
                "created_utc": at(0),
                "last_alive_utc": at(60),
                "finalized_utc": at(90),
            },
            "landings": [],
            "phases": [],
        }

    def call(
        self,
        run: dict[str, Any],
        *,
        mode: str = "class",
        db: Path | None = None,
        now: int = 200,
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Run the harness once and return its answer."""
        doc = self.root / f"doc-{uuid.uuid4().hex}.json"
        doc.write_text(
            json.dumps(
                {
                    "mode": mode,
                    "out": str(self.out),
                    "log": str(self.log),
                    "preflight": str(self.preflight),
                    "db": str(db or self.root / "none.db"),
                    "now": at(now),
                    "run": run,
                }
            ),
            encoding="utf-8",
        )
        child = {
            k: v for k, v in os.environ.items() if not k.upper().startswith("CREDITS_")
        }
        child.update(env or {})
        argv = ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(self.harness)]
        argv += ["-Watch", str(WATCH), "-Module", str(MODULE), "-Doc", str(doc)]
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=child,
            timeout=240,
            check=False,
        )
        shown = f"exit={proc.returncode}\n{proc.stdout}\n{proc.stderr}"
        assert proc.returncode == 0, shown
        answer = json.loads(proc.stdout.splitlines()[-1])
        assert isinstance(answer, dict), shown
        return answer

    def classify(self, **kw: Any) -> dict[str, Any]:
        """The class of the dispatch of this bench."""
        return self.call(self.run_object(), **kw)

    def log_records(self) -> list[dict[str, Any]]:
        """The records of the monitor log."""
        if not self.log.exists():
            return []
        lines = self.log.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]


@pytest.fixture
def bench(tmp_path: Path) -> Bench:
    """A dispatch bench; the monitor is a Windows script."""
    if sys.platform != "win32":
        pytest.skip("the credits monitor is a Windows script")
    return Bench(tmp_path / "bench")


@pytest.fixture
def st(tmp_path: Path) -> Store:
    """A new store."""
    store = Store(tmp_path / "store")
    store.root.mkdir()
    store.init()
    return store


# --- AC-927.1 the class


@pytest.mark.parametrize(
    ("output", "stream_result", "exit_code"),
    [
        pytest.param(ERROR_RESULT, True, 1, id="is_error"),
        pytest.param(
            result_line(subtype="error_during_execution", stop_reason=None),
            True,
            1,
            id="error_subtype",
        ),
        pytest.param(None, False, 3, id="no_result"),
        pytest.param(None, False, None, id="killed"),
    ],
)
def test_ac_927_1_a_rejected_event_with_no_clean_result_is_a_usage_limit(
    bench: Bench,
    output: dict[str, Any] | None,
    stream_result: bool,
    exit_code: int | None,
) -> None:
    tail = [output] if stream_result and output is not None else []
    bench.put(
        stream=[{"type": "system"}, rejected_event(), *tail],
        output=output,
        exit_code=exit_code,
    )
    found = bench.classify()
    assert found["class"] == "usage_limit", found
    assert found["resets_at"] == RESETS_AT, found
    assert found["signals"]["rejected"] is True, found


@pytest.mark.parametrize(
    "text",
    [
        LIMIT_TEXT,
        "5-hour limit reached",
        "You've hit your limit",
        "You have reached your usage limit",
        "Opus limit hit",
        "Weekly limit reached",
        "limit reached - resets 7pm",
        "You are out of extra usage",
    ],
)
def test_ac_927_1_the_message_text_is_enough_with_no_stream_file(
    bench: Bench, text: str
) -> None:
    bench.put(output=result_line(is_error=True, result=text), exit_code=1)
    found = bench.classify()
    assert found["class"] == "usage_limit", found
    assert found["signals"]["stream"] is None, found
    assert found["resets_at"] == (RESETS_AT if text == LIMIT_TEXT else None), found


def test_ac_927_1_the_message_text_on_stderr_is_enough(bench: Bench) -> None:
    bench.put(stderr="Error: weekly limit reached\n", exit_code=1)
    found = bench.classify()
    assert found["class"] == "usage_limit", found


def test_ac_927_1_usage_limit_is_a_stop_class() -> None:
    assert "usage_limit" in cs.STOP_CLASSES


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("credit balance is too low", "billing"),
        ('{"type":"error","error":{"type":"rate_limit_error"}}', "transient_api"),
    ],
)
def test_ac_927_1_the_billing_and_rate_limit_texts_keep_their_class(
    bench: Bench, text: str, expected: str
) -> None:
    result = result_line(is_error=True, result=text)
    bench.put(
        stream=[rejected_event(status="allowed"), result], output=result, exit_code=1
    )
    found = bench.classify()
    assert found["class"] == expected, found
    assert found["resets_at"] is None, found
    assert found["signals"]["rejected"] is False, found


@pytest.mark.parametrize("status", ["allowed", "rejected"])
def test_ac_927_1_a_clean_success_is_not_a_usage_limit(
    bench: Bench, status: str
) -> None:
    result = result_line(result="The usage limit reached page is fixed.")
    bench.put(
        stream=[rejected_event(status=status), result], output=result, exit_code=0
    )
    found = bench.classify()
    assert found["class"] == "unknown", found
    assert found["signals"]["rejected"] is (status == "rejected"), found
    assert found["resets_at"] is None, found


def test_ac_927_1_the_run_limits_come_first(bench: Bench) -> None:
    result = result_line(subtype="error_max_budget_usd", is_error=True)
    bench.put(stream=[rejected_event(), result], output=result, exit_code=1)
    found = bench.classify()
    assert found["class"] == "budget_cap", found
    assert found["signals"]["rejected"] is True, found


def test_ac_927_1_a_failed_stream_tool_leaves_the_old_path(
    bench: Bench, tmp_path: Path
) -> None:
    bench.put(stream=[rejected_event(), ERROR_RESULT], exit_code=0)
    run = bench.run_object(project=tmp_path)
    found = bench.call(run)
    assert found["class"] == "unknown", found
    assert found["signals"]["stream"] is None, found
    assert "stream_signals" not in found["missing"], found


def test_ac_927_1_a_slow_stream_tool_is_ended_and_named(
    bench: Bench, tmp_path: Path
) -> None:
    marker = tmp_path / "late.txt"
    code = (
        "import pathlib, time; time.sleep(5); "
        f"pathlib.Path(r'{marker}').write_text('1')"
    )
    stub = tmp_path / "slow.cmd"
    stub.write_bytes(f'@echo off\r\n"{BASE_PYTHON}" -I -c "{code}"\r\n'.encode("utf-8"))
    bench.put(stream=[rejected_event(), ERROR_RESULT], output=ERROR_RESULT, exit_code=1)
    found = bench.call(
        bench.run_object(python=str(stub)),
        env={"CREDITS_TEST_SIGNALS_TIMEOUT_MS": "200"},
    )
    assert found["class"] == "usage_limit", found
    assert found["missing"] == ["stream_signals"], found
    assert found["signals"]["stream"] is None, found
    time.sleep(6)
    assert not marker.exists(), "the stream tool was not ended"


def stream_tool(*args: str) -> subprocess.CompletedProcess[str]:
    """One call of the stream tool."""
    return subprocess.run(
        [sys.executable, "-I", str(STREAM_TOOL), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )


def test_ac_927_1_the_stream_tool_refuses_a_missing_and_a_large_stream(
    tmp_path: Path,
) -> None:
    stream = tmp_path / "stream.jsonl"
    gone = stream_tool("signals", "--stream", str(stream))
    assert gone.returncode == 3, gone.stderr
    assert "stream_missing" in gone.stderr
    line = (json.dumps(rejected_event()) + "\n").encode("utf-8")
    stream.write_bytes(line.ljust(1023) + b"\n")
    assert stream.stat().st_size == 1024
    good = stream_tool("signals", "--stream", str(stream), "--max-bytes", "1024")
    assert good.returncode == 0, good.stderr
    assert json.loads(good.stdout)["rejected"] is True
    stream.write_bytes(line.ljust(1024) + b"\n")
    large = stream_tool("signals", "--stream", str(stream), "--max-bytes", "1024")
    assert large.returncode == 3, large.stderr
    assert "stream_too_large" in large.stderr
    record = json.loads(large.stdout)
    assert record["limit_name"] == "stream_max_bytes"
    assert record["configured_value"] == 1024
    assert record["observed_value"] == 1025
    assert record["window"] == "one stream"


# --- AC-927.2 the denials and the signals


def done_run(bench: Bench, denials: Any) -> dict[str, Any]:
    """Classify a run that ended well with a DONE status and these denials."""
    result = result_line(permission_denials=denials)
    bench.put(
        stream=[result], output=result, exit_code=0, final="Closed.\n\nStatus: DONE\n"
    )
    return bench.classify()


DENIAL = {"tool_name": "Bash", "tool_use_id": "t1", "tool_input": {}}


@pytest.mark.parametrize(
    ("denials", "count"), [([DENIAL, DENIAL], 2), ("Bash was denied", 1), ({}, 1)]
)
def test_ac_927_2_a_done_run_with_denials_is_not_verified(
    bench: Bench, denials: Any, count: int
) -> None:
    found = done_run(bench, denials)
    assert found["class"] == "done_unverified", found
    assert found["missing"] == ["permission_denials"], found
    assert found["signals"]["permission_denials"] == count, found


@pytest.mark.parametrize("denials", [[], None])
def test_ac_927_2_a_done_run_with_no_denial_is_done(bench: Bench, denials: Any) -> None:
    found = done_run(bench, denials)
    assert found["class"] == "done", found
    assert found["missing"] == [], found
    assert found["signals"]["permission_denials"] == 0, found


def test_ac_927_2_the_exit_code_alone_is_never_done(bench: Bench) -> None:
    result = result_line()
    bench.put(stream=[result], output=result, exit_code=0, final="All rows closed.\n")
    found = bench.classify()
    assert found["class"] == "unknown", found


def test_ac_927_2_the_signals_hold_the_result_fields(bench: Bench) -> None:
    result = result_line(
        subtype="error_during_execution",
        is_error=True,
        stop_reason="refusal",
        result="weekly limit reached",
        permission_denials=[DENIAL],
    )
    bench.put(stream=[rejected_event(), result], output=result, exit_code=1)
    signals = bench.classify()["signals"]
    assert signals["subtype"] == "error_during_execution", signals
    assert signals["is_error"] is True, signals
    assert signals["stop_reason"] == "refusal", signals
    assert signals["permission_denials"] == 1, signals
    assert signals["rejected"] is True, signals
    assert signals["stream"]["resets_at"] == RESETS_AT, signals


# --- AC-927.3 the reset time


def finalizing(st: Store, run_id: str = "r1") -> Seg:
    """A run that ended and has no class yet."""
    seg = first_start(st, run_id, now=0)
    finish(st, seg, now=100)
    assert run_state(st, run_id) == "finalizing"
    return seg


def stored_run(st: Store, bench: Bench, run_id: str = "r1") -> dict[str, Any]:
    """The view row of a finalizing run, with the project and the dispatch of the bench."""
    view = st.ok("monitor_view", now=110, expect=("no_change",))
    run = next(row for row in view["runs"] if row["run_id"] == run_id)
    run["manifest"]["project_root"] = str(ROOT)
    run["python_exe"] = sys.executable
    run["segment"]["dispatch_id"] = "d1"
    assert isinstance(run, dict)
    return run


def reset_column(st: Store, seg: Seg) -> Any:
    """The stored reset time of one segment."""
    return st.one(
        "SELECT resets_at_utc FROM segments WHERE segment_id = ?", (seg.segment_id,)
    )


def dump(st: Store) -> list[tuple[Any, ...]]:
    """Each row that a class could change."""
    found: list[tuple[Any, ...]] = []
    for table in ("runs", "segments", "notices", "transitions", "effects"):
        found += [(table, *row) for row in st.rows(f"SELECT * FROM {table}")]
    return found


def classify_args(run_id: str, stop_class: str, resets: int | str) -> tuple[str, ...]:
    """The arguments of one class with a reset time."""
    target = "done" if stop_class == "done" else "stopped"
    args = ("--run-id", run_id, "--to", target, "--class", stop_class)
    return (*args, "--resets-at", str(resets))


def test_ac_927_3_the_monitor_stores_the_reset_time_of_the_fixture(
    st: Store, bench: Bench
) -> None:
    seg = finalizing(st)
    shutil.copyfile(STREAMS / "rejected-derived.jsonl", bench.folder / "stream.jsonl")
    bench.put(output=ERROR_RESULT, exit_code=1)
    answer = bench.call(stored_run(st, bench), mode="set", db=st.db)
    assert answer == {"set": True}
    assert run_state(st, "r1") == "stopped"
    assert st.one("SELECT stop_class FROM runs WHERE run_id = 'r1'") == "usage_limit"
    assert reset_column(st, seg) == RESETS_UTC


def test_ac_927_3_a_limit_with_no_reset_time_stores_none(
    st: Store, bench: Bench
) -> None:
    seg = finalizing(st)
    bench.put(
        output=result_line(is_error=True, result="weekly limit reached"), exit_code=1
    )
    assert bench.call(stored_run(st, bench), mode="set", db=st.db) == {"set": True}
    assert st.one("SELECT stop_class FROM runs WHERE run_id = 'r1'") == "usage_limit"
    assert reset_column(st, seg) is None


def test_ac_927_3_a_reset_time_that_the_store_refuses_does_not_keep_the_run_open(
    st: Store, bench: Bench
) -> None:
    seg = finalizing(st)
    bench.put(
        stream=[rejected_event(resetsAt=RESETS_AT * 1000), ERROR_RESULT],
        output=ERROR_RESULT,
        exit_code=1,
    )
    assert bench.call(stored_run(st, bench), mode="set", db=st.db) == {"set": True}
    assert st.one("SELECT stop_class FROM runs WHERE run_id = 'r1'") == "usage_limit"
    assert reset_column(st, seg) is None
    warned = [r for r in bench.log_records() if r["event"] == "resets_at_refused"]
    assert len(warned) == 1, bench.log_records()
    assert warned[0]["level"] == "WARN"
    assert warned[0]["limit_name"] == "resets_at"


@pytest.mark.parametrize("resets", [RESETS_MIN, RESETS_AT, RESETS_MAX])
def test_ac_927_3_a_reset_time_in_the_range_is_stored(st: Store, resets: int) -> None:
    seg = finalizing(st)
    st.ok("classify", *classify_args("r1", "usage_limit", resets), now=200)
    expected = {
        RESETS_MIN: "2020-01-01T00:00:00Z",
        RESETS_AT: RESETS_UTC,
        RESETS_MAX: at(200 + 8 * 86400),
    }
    assert reset_column(st, seg) == expected[resets]


@pytest.mark.parametrize("resets", [RESETS_MIN - 1, RESETS_MAX + 1, RESETS_AT * 1000])
def test_ac_927_3_a_reset_time_out_of_the_range_is_refused(
    st: Store, resets: int
) -> None:
    finalizing(st)
    before = dump(st)
    out = st.cli("classify", *classify_args("r1", "usage_limit", resets), now=200)
    assert out.code == 3, out.show()
    assert out.error == "resets_at_out_of_range", out.show()
    assert out.payload is not None
    assert out.payload["limit_name"] == "resets_at"
    assert out.payload["configured_value"] == [RESETS_MIN, RESETS_MAX]
    assert out.payload["observed_value"] == resets
    assert out.payload["window"] == "one classify"
    assert dump(st) == before


@pytest.mark.parametrize("stop_class", ["done", "billing"])
def test_ac_927_3_a_reset_time_needs_the_usage_limit_class(
    st: Store, stop_class: str
) -> None:
    finalizing(st)
    before = dump(st)
    out = st.cli("classify", *classify_args("r1", stop_class, RESETS_AT), now=200)
    assert out.code == 3, out.show()
    assert out.error == "resets_at_class_mismatch", out.show()
    assert dump(st) == before


def test_ac_927_3_a_reset_time_that_is_no_integer_is_a_usage_error(st: Store) -> None:
    finalizing(st)
    before = dump(st)
    out = st.cli("classify", *classify_args("r1", "usage_limit", "soon"), now=200)
    assert out.code == 2, out.show()
    assert out.payload is not None
    assert "not an integer" in out.payload["message"], out.show()
    assert dump(st) == before


def test_ac_927_3_the_class_and_the_reset_time_land_in_one_transaction(
    st: Store,
) -> None:
    seg = finalizing(st)
    args = classify_args("r1", "usage_limit", RESETS_AT)
    for point in cs.CRASH_POINTS["classify"]:
        if point == "after_effect":
            continue
        env = {"CREDITS_TEST_CRASH_AT": f"classify:{point}"}
        out = st.cli("classify", *args, now=200, env=env)
        done = point == "after_commit"
        assert out.code == 9, out.show()
        assert run_state(st, "r1") == ("stopped" if done else "finalizing")
        assert reset_column(st, seg) == (RESETS_UTC if done else None)
    st.ok("classify", *args, now=200, expect=("changed", "no_change"))
    assert run_state(st, "r1") == "stopped"
    assert reset_column(st, seg) == RESETS_UTC


def test_ac_927_3_only_the_latest_segment_gets_the_reset_time(st: Store) -> None:
    seg = finalizing(st)
    st.write(
        "INSERT INTO segments (segment_id, run_id, supervision, job, state, created_utc,"
        " updated_utc, finalized_utc) VALUES ('old', 'r1', 'job', 1, 'finalized', ?, ?, ?)",
        (at(-500), at(-400), at(-400)),
    )
    st.ok("classify", *classify_args("r1", "usage_limit", RESETS_AT), now=200)
    assert reset_column(st, seg) == RESETS_UTC
    assert st.one("SELECT resets_at_utc FROM segments WHERE segment_id = 'old'") is None


def store_facts(db: Path) -> tuple[int, set[str]]:
    """The schema version of a store and the columns of its segments table."""
    con = sqlite3.connect(db)
    try:
        version = int(con.execute("PRAGMA user_version").fetchone()[0])
        return version, {row[1] for row in con.execute("PRAGMA table_info(segments)")}
    finally:
        con.close()


def test_ac_927_3_a_v9_store_gets_the_column_at_each_crash_point(
    tmp_path: Path,
) -> None:
    assert cs.SCHEMA_VERSION >= 10
    source = tmp_path / "source.db"
    con = sqlite3.connect(source)
    try:
        for step in range(1, 10):
            for statement in cs.SCHEMA_STEPS[step]:
                con.execute(statement)
        con.execute("PRAGMA user_version = 9")
        con.execute(
            "INSERT INTO runs (run_id, state, kind, supervision, created_utc, updated_utc) "
            "VALUES ('old', 'stopped', 'exec', 'job', ?, ?)",
            (at(0), at(0)),
        )
        con.execute(
            "INSERT INTO segments (segment_id, run_id, supervision, job, state, created_utc, "
            "updated_utc, cli_version) VALUES ('old-seg', 'old', 'job', 1, 'finalized', ?, ?, '2.1.0')",
            (at(0), at(0)),
        )
        con.commit()
    finally:
        con.close()
    assert "resets_at_utc" not in store_facts(source)[1]
    for point in cs.CRASH_POINTS["init"]:
        db = tmp_path / point / "state.db"
        db.parent.mkdir()
        shutil.copy2(source, db)
        crashed = run_cli(db, "init", env={"CREDITS_TEST_CRASH_AT": f"init:{point}"})
        assert crashed.code == 9, crashed.show()
        version, columns = store_facts(db)
        done = point == "after_commit"
        assert version == (cs.SCHEMA_VERSION if done else 9)
        assert ("resets_at_utc" in columns) is done
        again = run_cli(db, "init")
        assert again.code == 0, again.show()
        version, columns = store_facts(db)
        assert version == cs.SCHEMA_VERSION and "resets_at_utc" in columns
        con = sqlite3.connect(db)
        try:
            rows = con.execute(
                "SELECT segment_id, state, cli_version, resets_at_utc FROM segments"
            ).fetchall()
        finally:
            con.close()
        assert rows == [("old-seg", "finalized", "2.1.0", None)]


# --- AC-927.4 the fixtures


def manifests(root: Path) -> list[Path]:
    """Each fixture manifest under a folder."""
    return sorted(root.rglob("expected.json"))


def entries(manifest: Path) -> list[dict[str, Any]]:
    """The entries of one manifest; an empty or unreadable one is ``no_fixture``."""
    found = json.loads(manifest.read_text(encoding="utf-8")).get("fixtures")
    if not isinstance(found, list) or not found:
        raise AssertionError(f"no_fixture {manifest}")
    return found


def check_manifests(root: Path) -> None:
    """Each manifest names its files, and each stream file has one complete entry."""
    named: set[Path] = set()
    for manifest in manifests(root):
        listed = entries(manifest)
        for entry in listed:
            path = manifest.parent / entry["file"]
            assert path.is_file(), f"entry_without_file {path}"
            assert path not in named, f"entry_twice {path}"
            assert entry["source"] and entry["class"], f"entry_incomplete {entry}"
            assert set(entry) == {"file", "source", "class", "resets_at", "derived"}
            named.add(path)
        real = [e for e in listed if e["class"] == "usage_limit" and not e["derived"]]
        assert manifest.parent.name != "live" or real, f"no_live_limit {manifest}"
    assert named, "no_fixture"
    assert set(root.rglob("*.jsonl")) == named, "file_without_entry"


def scan(root: Path) -> list[str]:
    """The lines of the fixture files that hold a secret or a name of the person."""
    patterns = [
        r"sk-ant-",
        r"(?i)C:[\\/]+Users[\\/]+(?!USER\b)",
        r"@[A-Za-z0-9-]+\.[A-Za-z]{2,}",
        r'"(email|orgId|orgName|account_uuid|organization_uuid|apiKeySource)"\s*:',
    ]
    account = os.environ.get("USERNAME") or os.environ.get("USER")
    if account:
        patterns.append(rf"\b{re.escape(account)}\b")
    hits: list[str] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            hits += [
                f"{path.name}:{number} {p}" for p in patterns if re.search(p, line)
            ]
    return hits


def cases() -> list[Any]:
    """One case of each entry of each manifest; a manifest with no entry stays one case."""
    found: list[Any] = []
    for manifest in manifests(STREAMS):
        listed = json.loads(manifest.read_text(encoding="utf-8")).get("fixtures")
        for entry in listed or [None]:
            label = "no_fixture" if entry is None else entry["file"]
            folder = manifest.parent.relative_to(STREAMS).as_posix()
            found.append(pytest.param(manifest, entry, id=f"{folder}/{label}"))
    return found or [pytest.param(STREAMS / "expected.json", None, id="no_manifest")]


@pytest.mark.parametrize(("manifest", "entry"), cases())
def test_ac_927_4_each_fixture_gets_its_class(
    bench: Bench, manifest: Path, entry: dict[str, Any] | None
) -> None:
    assert entry is not None, f"no_fixture {manifest}"
    source = manifest.parent / entry["file"]
    out = subprocess.run(
        [
            sys.executable,
            "-I",
            str(STREAM_TOOL),
            "split",
            "--out",
            str(bench.folder / "output.json"),
            "--stream",
            str(bench.folder / "stream.jsonl"),
        ],
        input=source.read_bytes(),
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert out.returncode in (0, 1, 3), out.stderr
    assert (bench.folder / "stream.jsonl").read_bytes() == source.read_bytes()
    bench.put(exit_code=out.returncode)
    found = bench.classify()
    assert (found["class"] == "usage_limit") == (entry["class"] == "usage_limit"), found
    assert found["resets_at"] == entry["resets_at"], found


def test_ac_927_4_each_fixture_has_an_entry_with_its_source() -> None:
    check_manifests(STREAMS)
    names = {e["file"]: e for m in manifests(STREAMS) for e in entries(m)}
    assert names["allowed-success.jsonl"]["class"] == "not_usage_limit"
    assert names["harness-allowed.jsonl"]["class"] == "not_usage_limit"
    derived = names["rejected-derived.jsonl"]
    assert derived["derived"] is True
    assert derived["class"] == "usage_limit"
    assert derived["resets_at"] == RESETS_AT


def test_ac_927_4_the_fixtures_hold_no_secret() -> None:
    assert scan(STREAMS) == []


@pytest.mark.parametrize(
    "planted",
    [
        "sk-" + "ant-oat01-" + "A" * 20,
        "C:\\\\" + "Users\\\\someone\\\\x",
        "person@example.com",
        '"email": "x"',
        '"orgName": "x"',
    ],
)
def test_ac_927_4_the_scan_finds_a_planted_value(tmp_path: Path, planted: str) -> None:
    copy = tmp_path / "streams"
    shutil.copytree(STREAMS, copy)
    target = copy / "harness-allowed.jsonl"
    with target.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps({"type": "user"})[:-1] + f", {planted}}}\n")
    found = scan(copy)
    assert found and all(hit.startswith("harness-allowed.jsonl:") for hit in found)


def test_ac_927_4_a_wrong_manifest_fails(tmp_path: Path) -> None:
    copy = tmp_path / "streams"
    shutil.copytree(STREAMS, copy)
    (copy / "allowed-success.jsonl").unlink()
    with pytest.raises(AssertionError, match="entry_without_file"):
        check_manifests(copy)
    shutil.copyfile(STREAMS / "allowed-success.jsonl", copy / "allowed-success.jsonl")
    (copy / "extra.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="file_without_entry"):
        check_manifests(copy)
    (copy / "extra.jsonl").unlink()
    live = copy / "live"
    live.mkdir()
    (live / "expected.json").write_text('{"fixtures": []}', encoding="utf-8")
    with pytest.raises(AssertionError, match="no_fixture"):
        check_manifests(copy)


def test_ac_927_4_a_live_manifest_needs_a_real_limit(tmp_path: Path) -> None:
    copy = tmp_path / "streams"
    shutil.copytree(STREAMS, copy)
    live = copy / "live"
    live.mkdir()
    shutil.copyfile(STREAMS / "rejected-derived.jsonl", live / "forced-limit.jsonl")
    entry: dict[str, Any] = {
        "file": "forced-limit.jsonl",
        "source": "fixture",
        "class": "usage_limit",
        "resets_at": RESETS_AT,
        "derived": True,
    }
    manifest = live / "expected.json"
    manifest.write_text(json.dumps({"fixtures": [entry]}), encoding="utf-8")
    with pytest.raises(AssertionError, match="no_live_limit"):
        check_manifests(copy)
    entry["derived"] = False
    manifest.write_text(json.dumps({"fixtures": [entry]}), encoding="utf-8")
    check_manifests(copy)


# --- a rejected event after the last result


def split_stream(bench: Bench) -> subprocess.CompletedProcess[str]:
    """Run the splitter on the stream of the bench, as the launch does."""
    return stream_tool(
        "split",
        "--from-stream",
        "--out",
        str(bench.folder / "output.json"),
        "--stream",
        str(bench.folder / "stream.jsonl"),
    )


@pytest.mark.parametrize("later", ["event_only", "new_turn"])
def test_a_rejection_after_an_earlier_success_is_a_usage_limit(
    bench: Bench, later: str
) -> None:
    turn: list[dict[str, Any]] = [{"type": "user", "message": {"content": "next"}}]
    end: list[dict[str, Any]] = [{"type": "assistant", "message": {"content": []}}]
    stream = [result_line(result="first turn done")]
    stream += (
        [rejected_event()] if later == "event_only" else [*turn, rejected_event(), *end]
    )
    bench.put(stream=stream)
    done = split_stream(bench)
    assert done.returncode == 3, done.stderr
    assert not (bench.folder / "output.json").exists()
    bench.put(exit_code=1)
    found = bench.classify()
    assert found["class"] == "usage_limit", found
    assert found["resets_at"] == RESETS_AT, found
    assert found["signals"]["stream"]["result"] is None, found


def test_a_success_after_a_rejection_is_no_usage_limit(bench: Bench) -> None:
    final = result_line(result="second turn done")
    bench.put(stream=[result_line(), rejected_event(), final], exit_code=0)
    done = split_stream(bench)
    assert done.returncode == 0, done.stderr
    assert json.loads((bench.folder / "output.json").read_bytes()) == final
    found = bench.classify()
    assert found["class"] == "unknown", found
    assert found["resets_at"] is None, found


def test_an_allowed_event_after_a_success_keeps_the_result(bench: Bench) -> None:
    bench.put(stream=[result_line(), rejected_event(status="allowed")], exit_code=0)
    done = split_stream(bench)
    assert done.returncode == 0, done.stderr
    assert bench.classify()["class"] == "unknown"


@pytest.mark.parametrize(
    ("cli_exit", "is_error", "code"),
    [("7", False, 7), ("7", True, 7), ("0", False, 0), ("0", True, 1), ("x", False, 1)],
)
def test_the_split_keeps_a_cli_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cli_exit: str,
    is_error: bool,
    code: int,
) -> None:
    line = {"type": "result", "is_error": is_error, "result": "last"}
    stream = tmp_path / "stream.jsonl"
    stream.write_text(json.dumps(line) + "\n", encoding="utf-8")
    out = tmp_path / "output.json"
    monkeypatch.setenv("{{PROJECT_NAME_UPPER}}_CREDITS_CLI_EXIT", cli_exit)
    done = stream_tool(
        "split", "--from-stream", "--out", str(out), "--stream", str(stream)
    )
    assert done.returncode == code, done.stderr
    assert json.loads(out.read_bytes()) == line
