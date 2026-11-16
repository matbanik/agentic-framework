"""MEU-943 AC-943.3, AC-943.7 (writer part) and AC-943.9: the coordination-event writer (PK1).

``tools/coordination_events.py`` (CE) appends one JSON line per wait, land or refusal
record (design §5.2, §5.3) and reads the records back into the metrics of design §5.5.
Each test loads CE by file path and first asserts that the file exists, so a missing
module is an assertion, not a collection error.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import subprocess
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[2]
CE_PATH = REPO / "tools" / "coordination_events.py"
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
ID_RE = re.compile(r"^[0-9a-f]{32}$")
RECORD_KEYS = {
    "schema",
    "id",
    "ts",
    "writer",
    "kind",
    "session",
    "plan",
    "row",
    "reason",
    "scope",
    "blocker",
    "outcome",
}
SESSION = "0b7c2a7e-4d4f-4a59-9a43-3f2b9c1d8e10"
U2 = "6f1e9d3c-2b4a-4c8e-9f7d-1a2b3c4d5e6f"
PLAN = "2026-11-10-pk1-stage3-instrumentation"
SESSION_KINDS = [
    ("wait_started", None),
    ("continued_elsewhere", None),
    ("parked", None),
    ("resumed", None),
    ("ended", "resumed_work"),
    ("ended", "gave_up"),
    ("ended", "handed_back"),
]


def _load_ce() -> ModuleType:
    assert CE_PATH.is_file(), f"missing {CE_PATH}"
    spec = importlib.util.spec_from_file_location("pk1_coordination_events", CE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def _lines(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]


def _fields(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "writer": "session",
        "session": SESSION,
        "plan": PLAN,
        "row": "943-G2",
        "reason": "gate_busy",
        "scope": "tools/lanes.py",
    }
    base.update(over)
    return base


def _argv(kind: str, log: Path, **over: str) -> list[str]:
    args = {
        "--kind": kind,
        "--session": SESSION,
        "--plan": PLAN,
        "--row": "943-G2",
        "--reason": "gate_busy",
        "--scope": "tools/lanes.py",
        "--log": str(log),
    }
    args.update({f"--{k.replace('_', '-')}": v for k, v in over.items()})
    out: list[str] = ["record"]
    for k, v in args.items():
        out += [k, v]
    return out


def _exit(ce: ModuleType, argv: list[str]) -> object:
    """Return the exit code of ``CE.main``, whether it returns or raises it."""
    try:
        return ce.main(argv)
    except SystemExit as exc:
        return exc.code


@pytest.fixture
def no_env_log(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("{{PROJECT_NAME_UPPER}}_HOOK_LOG", raising=False)


# --- AC-943.3: the six session kinds through the API and the CLI ---------------------


def test_f2p_ac943_3_constants_hold_the_kinds_and_outcomes() -> None:
    ce = _load_ce()
    assert ce.EVENT_SCHEMA == "coordination-event/1"
    assert set(ce.KINDS) == {
        "busy_observed",
        "wait_started",
        "continued_elsewhere",
        "parked",
        "resumed",
        "ended",
        "land_started",
        "land_ended",
        "refused",
        "committed",
        "step_refused",
    }
    assert {k: set(v) for k, v in ce.OUTCOMES.items()} == {
        "ended": {"resumed_work", "gave_up", "handed_back"},
        "land_ended": {"closed", "superseded", "abandoned", "refused"},
    }
    assert ce.EVENTS_FILE == "coordination-events.jsonl"


@pytest.mark.parametrize(("kind", "outcome"), SESSION_KINDS)
def test_f2p_ac943_3_api_writes_one_line_per_session_kind(
    tmp_path: Path, no_env_log: None, kind: str, outcome: str | None
) -> None:
    ce = _load_ce()
    log = tmp_path / "events.jsonl"
    ok = ce.record(kind, **_fields(blocker="lane-b"), outcome=outcome, log=log)
    assert ok is True
    lines = _lines(log)
    assert len(lines) == 1
    rec = lines[0]
    assert set(rec) == RECORD_KEYS
    assert rec["schema"] == "coordination-event/1"
    assert ID_RE.fullmatch(str(rec["id"]))
    assert TS_RE.fullmatch(str(rec["ts"]))
    assert rec["kind"] == kind
    assert {k: rec[k] for k in ("writer", "session", "plan", "row", "reason")} == {
        "writer": "session",
        "session": SESSION,
        "plan": PLAN,
        "row": "943-G2",
        "reason": "gate_busy",
    }
    assert rec["scope"] == "tools/lanes.py"
    assert rec["blocker"] == "lane-b"
    assert rec["outcome"] == outcome


def test_f2p_ac943_3_api_appends_and_ids_differ(
    tmp_path: Path, no_env_log: None
) -> None:
    ce = _load_ce()
    log = tmp_path / "events.jsonl"
    assert ce.record("wait_started", **_fields(), log=log) is True
    assert ce.record("ended", **_fields(), outcome="gave_up", log=log) is True
    first, second = _lines(log)
    assert first["id"] != second["id"]
    assert (first["kind"], second["kind"]) == ("wait_started", "ended")
    assert first["blocker"] is None and first["outcome"] is None


@pytest.mark.parametrize(("kind", "outcome"), SESSION_KINDS)
def test_f2p_ac943_3_cli_writes_one_line_per_session_kind(
    tmp_path: Path,
    no_env_log: None,
    capsys: pytest.CaptureFixture[str],
    kind: str,
    outcome: str | None,
) -> None:
    ce = _load_ce()
    log = tmp_path / "events.jsonl"
    extra = {"outcome": outcome} if outcome else {}
    assert ce.main(_argv(kind, log, blocker="op-7", **extra)) == 0
    capsys.readouterr()
    lines = _lines(log)
    assert len(lines) == 1
    rec = lines[0]
    assert set(rec) == RECORD_KEYS
    assert rec["kind"] == kind
    assert rec["writer"] == "session"
    assert rec["session"] == SESSION and rec["plan"] == PLAN
    assert rec["blocker"] == "op-7"
    assert rec["outcome"] == outcome


def test_f2p_ac943_3_cli_is_one_command(tmp_path: Path) -> None:
    assert CE_PATH.is_file(), f"missing {CE_PATH}"
    log = tmp_path / "events.jsonl"
    proc = subprocess.run(
        [sys.executable, str(CE_PATH), *_argv("wait_started", log)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=REPO,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert [x["kind"] for x in _lines(log)] == ["wait_started"]


@pytest.mark.parametrize(
    ("field", "over"),
    [
        ("kind", {"kind": "slept"}),
        ("reason", {"reason": "has space"}),
        ("reason", {"reason": "Upper"}),
        ("scope", {"scope": "a;b"}),
        ("scope", {"scope": "$HOME"}),
        ("scope", {"scope": "git commit -m x"}),
        ("blocker", {"blocker": "a|b"}),
        ("session", {"session": "two words"}),
        ("outcome", {"kind": "ended", "outcome": "closed"}),
        ("outcome", {"kind": "wait_started", "outcome": "gave_up"}),
        ("outcome", {"kind": "land_ended", "outcome": "resumed_work"}),
    ],
)
def test_f2p_ac943_3_invalid_field_is_refused_with_no_line(
    tmp_path: Path,
    no_env_log: None,
    capsys: pytest.CaptureFixture[str],
    field: str,
    over: dict[str, str],
) -> None:
    ce = _load_ce()
    log = tmp_path / "events.jsonl"
    kind = over.get("kind", "wait_started")
    rest = {k: v for k, v in over.items() if k != "kind"}
    assert ce.main(_argv(kind, log, **rest)) == 2
    err = capsys.readouterr().err
    assert f"record_invalid {field}" in err
    assert not log.exists()
    api = {k: v for k, v in rest.items() if k != "outcome"}
    assert (
        ce.record(kind, **_fields(**api), outcome=rest.get("outcome"), log=log) is False
    )
    assert not log.exists()


def test_f2p_ac943_3_cli_refuses_an_unknown_flag(
    tmp_path: Path, no_env_log: None, capsys: pytest.CaptureFixture[str]
) -> None:
    ce = _load_ce()
    log = tmp_path / "events.jsonl"
    assert _exit(ce, [*_argv("parked", log), "--command", "git"]) == 2
    assert _exit(ce, [*_argv("parked", log)[:-2], "--lo", str(log)]) == 2
    capsys.readouterr()
    assert not log.exists()


def test_f2p_ac943_3_destination_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ce = _load_ce()
    given = tmp_path / "given.jsonl"
    hook = tmp_path / "hooks" / "hook-log.jsonl"
    monkeypatch.setenv("{{PROJECT_NAME_UPPER}}_HOOK_LOG", str(hook))
    assert ce.destination(given) == given
    assert ce.destination(None) == hook.parent / "coordination-events.jsonl"
    assert ce.record("parked", **_fields()) is True
    assert [x["kind"] for x in _lines(hook.parent / "coordination-events.jsonl")] == [
        "parked"
    ]
    assert not hook.exists()
    monkeypatch.delenv("{{PROJECT_NAME_UPPER}}_HOOK_LOG")
    assert ce.destination(None) is None
    assert ce.record("parked", **_fields()) is False
    argv = [x for x in _argv("parked", given) if x not in ("--log", str(given))]
    assert ce.main(argv) == 0
    assert "record_skipped no_destination" in capsys.readouterr().err
    assert not given.exists()


# --- AC-943.7: a failed write is harmless; records hold no command or environment ---


def test_f2p_ac943_7_writer_folder_destination_returns_false(
    tmp_path: Path, no_env_log: None, capsys: pytest.CaptureFixture[str]
) -> None:
    ce = _load_ce()
    folder = tmp_path / "events-dir"
    folder.mkdir()
    assert ce.record("wait_started", **_fields(), log=folder) is False
    assert list(folder.iterdir()) == []
    assert ce.main(_argv("wait_started", folder)) == 0
    assert "record_skipped write_failed" in capsys.readouterr().err
    assert list(folder.iterdir()) == []


def test_f2p_ac943_7_writer_records_hold_no_environment_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ce = _load_ce()
    hook = tmp_path / "hooks" / "hook-log.jsonl"
    monkeypatch.setenv("{{PROJECT_NAME_UPPER}}_HOOK_LOG", str(hook))
    monkeypatch.setenv("{{PROJECT_NAME_UPPER}}_PK1_PROBE", "pk1-env-value-7f3a")
    assert ce.record("busy_observed", **_fields(writer="lanes")) is True
    text = (hook.parent / "coordination-events.jsonl").read_text(encoding="utf-8")
    for value in ("pk1-env-value-7f3a", str(hook), hook.as_posix()):
        assert value not in text
    rec = json.loads(text)
    assert set(rec) == RECORD_KEYS


def test_f2p_ac943_7_writer_imports_only_the_standard_library() -> None:
    assert CE_PATH.is_file(), f"missing {CE_PATH}"
    tree = ast.parse(CE_PATH.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module.split(".")[0])
    names.discard("__future__")
    assert names, "CE imports nothing"
    assert names <= set(sys.stdlib_module_names), names - set(sys.stdlib_module_names)


# --- AC-943.9: the report ------------------------------------------------------------


def _ev(ts: str, kind: str, writer: str, **f: object) -> dict[str, object]:
    rec: dict[str, object] = {
        "schema": "coordination-event/1",
        "id": uuid.uuid4().hex,
        "ts": f"2026-11-14T{ts}.000Z",
        "writer": writer,
        "kind": kind,
        "session": SESSION,
        "plan": PLAN,
        "row": "943-G2",
        "reason": "gate_busy",
        "scope": "tools/lanes.py",
        "blocker": None,
        "outcome": None,
    }
    rec.update(f)
    return rec


def _hook(session: str, decision: str) -> dict[str, object]:
    return {
        "hook": "commit_gate",
        "session_id": session,
        "permission_mode": "default",
        "command": "x",
        "decision": decision,
        "ts": "2026-11-14T10:00:00.000Z",
        "reason": decision,
    }


def _write_jsonl(path: Path, rows: Sequence[object]) -> Path:
    out = []
    for row in rows:
        out.append(row if isinstance(row, str) else json.dumps(row))
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    missing = _ev("10:19:00", "committed", "commit_batch", scope="op-x", reason="r")
    del missing["scope"]
    events = [
        # Episode 1 (closed, 120 s): one continued_elsewhere, no parked.
        _ev("10:00:00", "wait_started", "session"),
        _ev("10:00:30", "continued_elsewhere", "session"),
        _ev("10:02:00", "ended", "session", outcome="resumed_work"),
        # Episode 2 (open, censored): two parked, one of them a human decision.
        _ev("10:05:00", "wait_started", "session", scope="gate"),
        _ev("10:06:00", "parked", "session", scope="gate", reason="lane_busy"),
        _ev("10:07:00", "parked", "session", scope="gate", reason="human_decision"),
        # Episodes 3 and 4: busy_observed with no open episode, both censored.
        _ev(
            "10:08:00",
            "busy_observed",
            "commit_batch",
            plan="-",
            row="-",
            scope="refs/heads/main",
            reason="parent_moved",
        ),
        _ev(
            "10:08:30",
            "busy_observed",
            "lanes",
            plan="-",
            row="-",
            reason="claim_overlap",
            blocker="lane-b",
        ),
        _ev("10:09:00", "refused", "commit_batch", plan="-", reason="parent_moved"),
        _ev(
            "10:09:30", "refused", "validate_codebase", plan="-", reason="foreign_edit"
        ),
        # Land ops: op-a closed after 150 s, op-b open with a step refusal, op-c abandoned.
        _ev("10:10:00", "land_started", "commit_batch", scope="op-a", reason="land"),
        _ev(
            "10:12:30",
            "land_ended",
            "lanes",
            scope="op-a",
            reason="land",
            outcome="closed",
        ),
        _ev("10:13:00", "land_started", "commit_batch", scope="op-b", reason="land"),
        _ev(
            "10:14:00",
            "step_refused",
            "commit_batch",
            scope="op-b",
            reason="sync_unexplained",
        ),
        _ev("10:15:00", "land_started", "commit_batch", scope="op-c", reason="land"),
        _ev(
            "10:16:00",
            "land_ended",
            "lanes",
            scope="op-c",
            reason="land",
            outcome="abandoned",
        ),
        # Main-tree commits: a two-packet batch.
        _ev(
            "10:17:00",
            "committed",
            "commit_batch",
            scope="op-m/1",
            reason="packet_reconciled",
        ),
        _ev(
            "10:18:00",
            "committed",
            "commit_batch",
            scope="op-m/2",
            reason="packet_reconciled",
        ),
        missing,
        # A test record: a session id that is not a UUID.
        _ev("10:20:00", "resumed", "session", session="sess-1"),
        "{not json",
        _ev("10:21:00", "parked", "session") | {"schema": "coordination-event/0"},
    ]
    hooks = [
        _hook(SESSION, "ask"),
        _hook(SESSION, "ask"),
        _hook(U2, "ask"),
        _hook(U2, "allow"),
        _hook("sess-1", "ask"),
    ]
    return (
        _write_jsonl(tmp_path / "events.jsonl", events),
        _write_jsonl(tmp_path / "hook-log.jsonl", hooks),
    )


def _report(ce: ModuleType, argv: list[str], capsys: pytest.CaptureFixture[str]):
    code = ce.main(["report", *argv])
    out = capsys.readouterr().out
    return code, out


def test_f2p_ac943_9_report_json_metrics(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ce = _load_ce()
    events, hooks = _fixture(tmp_path)
    code, out = _report(
        ce, ["--log", str(events), "--hook-log", str(hooks), "--json"], capsys
    )
    assert code == 0
    data = json.loads(out)
    assert data["as_of"] == "2026-11-14T10:20:00.000Z"
    assert data["asks"] == 4
    assert data["commits"] == 3
    assert data["prompts_per_commit"] == pytest.approx(4 / 3, abs=1e-3)
    assert data["handbacks_no_decision"] == 1
    episodes = data["episodes"]
    assert [
        (e["scope"], e["continued_elsewhere"], e["parked"], e["censored"])
        for e in episodes
    ] == [
        ("tools/lanes.py", 1, 0, False),
        ("gate", 0, 2, True),
        ("refs/heads/main", 0, 0, True),
        ("tools/lanes.py", 0, 0, True),
    ]
    assert [e["wait_s"] for e in episodes] == pytest.approx(
        [120.0, 900.0, 720.0, 690.0]
    )
    assert [e["plan"] for e in episodes] == [PLAN, PLAN, "-", "-"]
    assert data["collisions_caught"] == 3
    assert data["foreign_edit_failures"] == 1
    assert data["land_times"] == {"op-a": pytest.approx(150.0)}
    assert data["outcome_mix"] == {
        "closed": 1,
        "superseded": 0,
        "abandoned": 1,
        "refused": 0,
        "open": 1,
    }
    assert data["step_refusals"] == {"sync_unexplained": 1}
    assert data["records_per_writer"] == {
        "session": 7,
        "commit_batch": 9,
        "lanes": 3,
        "validate_codebase": 1,
    }
    assert data["missing_fields"] == 1
    assert data["malformed_lines"] == 2
    assert data["test_records"] == 2


def test_f2p_ac943_9_report_as_of_moves_the_censoring(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ce = _load_ce()
    events, hooks = _fixture(tmp_path)
    argv = ["--log", str(events), "--as-of", "2026-11-14T11:05:00.000Z", "--json"]
    code, out = _report(ce, argv, capsys)
    assert code == 0
    data = json.loads(out)
    assert data["as_of"] == "2026-11-14T11:05:00.000Z"
    assert [e["wait_s"] for e in data["episodes"]] == pytest.approx(
        [120.0, 3600.0, 3420.0, 3390.0]
    )
    assert data["asks"] == 0
    assert data["prompts_per_commit"] == pytest.approx(0.0)


def test_f2p_ac943_9_report_main_tree_commits_give_a_number(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ce = _load_ce()
    events = _write_jsonl(
        tmp_path / "events.jsonl",
        [_ev("10:00:00", "committed", "commit_batch", scope="op-1", reason="r")],
    )
    hooks = _write_jsonl(
        tmp_path / "hook-log.jsonl", [_hook(SESSION, "ask"), _hook(SESSION, "ask")]
    )
    code, out = _report(
        ce, ["--log", str(events), "--hook-log", str(hooks), "--json"], capsys
    )
    assert code == 0
    data = json.loads(out)
    assert data["commits"] == 1
    assert data["prompts_per_commit"] == pytest.approx(2.0)
    assert data["test_records"] == 0
    empty = _write_jsonl(
        tmp_path / "none.jsonl", [_ev("10:00:00", "parked", "session")]
    )
    code, out = _report(
        ce, ["--log", str(empty), "--hook-log", str(hooks), "--json"], capsys
    )
    assert code == 0
    assert json.loads(out)["prompts_per_commit"] == "n/a"


def test_f2p_ac943_9_report_counts_test_records_in_the_live_log(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ce = _load_ce()
    events = _write_jsonl(
        tmp_path / "events.jsonl", [_ev("10:00:00", "parked", "session")]
    )
    hooks = _write_jsonl(
        tmp_path / "hook-log.jsonl", [_hook("sess-1", "allow"), _hook(U2, "ask")]
    )
    code, out = _report(
        ce, ["--log", str(events), "--hook-log", str(hooks), "--json"], capsys
    )
    assert code == 0
    assert json.loads(out)["test_records"] == 1


def test_f2p_ac943_9_report_text_has_one_line_per_metric(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ce = _load_ce()
    events, hooks = _fixture(tmp_path)
    code, out = _report(ce, ["--log", str(events), "--hook-log", str(hooks)], capsys)
    assert code == 0
    heads = [line.split(":", 1)[0] for line in out.splitlines() if line]
    for key in (
        "prompts_per_commit",
        "handbacks_no_decision",
        "episodes",
        "collisions_caught",
        "foreign_edit_failures",
        "land_times",
        "outcome_mix",
        "step_refusals",
        "records_per_writer",
        "missing_fields",
        "malformed_lines",
        "test_records",
    ):
        assert heads.count(key) == 1, (key, heads)


def test_f2p_ac943_9_report_bad_input_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ce = _load_ce()
    events, _ = _fixture(tmp_path)
    assert ce.main(["report", "--log", str(tmp_path / "absent.jsonl")]) == 2
    assert ce.main(["report", "--log", str(events), "--as-of", "yesterday"]) == 2
    capsys.readouterr()


# --- Execution review round 1: the writer-level corrections ------------------------------

R1_WRITERS = 6
R1_CALLS = 300

# One writer process: wait for the start file, then write R1_CALLS records.
R1_WRITER_SCRIPT = """import importlib.util, pathlib, sys, time
spec = importlib.util.spec_from_file_location("ce_writer", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
start = pathlib.Path(sys.argv[3])
while not start.exists():
    time.sleep(0.002)
for _ in range(int(sys.argv[5])):
    if not module.record(
        "busy_observed", writer="writer", reason="busy", scope=sys.argv[4], log=sys.argv[2]
    ):
        sys.exit(9)
"""


def _r1_record(ce: ModuleType, **fields: object) -> dict[str, object]:
    base: dict[str, object] = {
        "schema": ce.EVENT_SCHEMA,
        "ts": "2026-11-15T10:00:00.000Z",
        "writer": "session",
        "session": "s-one",
        "plan": PLAN,
        "row": "M",
        "reason": "busy",
        "scope": "gate",
        "blocker": None,
        "outcome": None,
    }
    base.update(fields)
    return base


def test_f2p_r1_f1_concurrent_writers_keep_every_record(tmp_path: Path) -> None:
    log = tmp_path / "many.jsonl"
    start = tmp_path / "start"
    procs = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                R1_WRITER_SCRIPT,
                str(CE_PATH),
                str(log),
                str(start),
                f"writer-{n}",
                str(R1_CALLS),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for n in range(R1_WRITERS)
    ]
    start.touch()
    for proc in procs:
        out, err = proc.communicate(timeout=120)
        assert proc.returncode == 0, (proc.returncode, out, err)
    records = [json.loads(line) for line in log.read_bytes().splitlines()]
    assert len(records) == R1_WRITERS * R1_CALLS, len(records)
    assert len({rec["id"] for rec in records}) == R1_WRITERS * R1_CALLS
    for n in range(R1_WRITERS):
        mine = sum(1 for rec in records if rec["scope"] == f"writer-{n}")
        assert mine == R1_CALLS, (n, mine)


def test_f2p_r1_f4_scope_token_is_deterministic_and_bounded() -> None:
    ce = _load_ce()
    assert ce.scope_token("src/a.py") == "src/a.py"
    assert ce.scope_token("a=b") == "a=3Db"
    assert ce.scope_token("\u00e9") == "=C3=A9"
    long_value = "x " * 150
    first = ce.scope_token(long_value)
    assert first == ce.scope_token(long_value)
    assert first is not None and ce.TOKEN_RE.fullmatch(first), first
    assert first.startswith("sha256:") and len(first) == len("sha256:") + 64, first
    assert ce.scope_token("") is None and ce.scope_token(None) is None


def test_f2p_r1_f4_split_code_keeps_a_path_with_a_space() -> None:
    ce = _load_ce()
    assert ce.split_code("owns_overlap:lane-a:src/with space.py\ndetail") == (
        "owns_overlap",
        "lane-a:src/with=20space.py",
    )
    assert ce.split_code("no_task") == ("no_task", None)


def test_f2p_r1_f6_one_land_ended_per_op(tmp_path: Path) -> None:
    ce = _load_ce()
    log = tmp_path / "land.jsonl"
    for _ in range(2):
        assert ce.record(
            "land_ended",
            writer="lanes",
            reason="land_superseded",
            scope="op-1",
            outcome="superseded",
            log=str(log),
        )
    assert ce.record(
        "land_ended",
        writer="lanes",
        reason="land_abandoned",
        scope="op-2",
        outcome="abandoned",
        log=str(log),
    )
    ended = [rec for rec in _lines(log) if rec["kind"] == "land_ended"]
    assert [(rec["scope"], rec["outcome"]) for rec in ended] == [
        ("op-1", "superseded"),
        ("op-2", "abandoned"),
    ], ended


def test_f2p_r1_f7_equal_times_keep_the_append_order() -> None:
    ce = _load_ce()
    records = [
        _r1_record(ce, id="f" * 32, kind="wait_started"),
        _r1_record(ce, id="0" * 32, kind="ended", outcome="resumed_work"),
    ]
    report = ce.build_report(records, 0, [], 0, None)
    episodes = report["episodes"]
    assert len(episodes) == 1, episodes
    assert (episodes[0]["censored"], episodes[0]["outcome"]) == (
        False,
        "resumed_work",
    ), episodes[0]


def test_f2p_r1_f7_report_reads_a_record_with_a_null_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ce = _load_ce()
    good = _r1_record(ce, id="1" * 32, kind="busy_observed", writer="review")
    bad = dict(good, id=None)
    log = tmp_path / "bad.jsonl"
    log.write_text(json.dumps(good) + "\n" + json.dumps(bad) + "\n", encoding="utf-8")
    code = ce.main(["report", "--log", str(log), "--json"])
    out = capsys.readouterr().out
    assert code == 0, (code, out)
    assert json.loads(out)["records_per_writer"] == {"review": 2}, out
