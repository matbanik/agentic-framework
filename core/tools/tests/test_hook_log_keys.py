"""MEU-943 AC-943.1 and AC-943.2: the hook-log keys and the test log split (PK1).

AC-943.1: both hook-log writers (``.claude/hooks/_hook_common.py`` ``append_log`` and
``tools/stop_gate.py`` ``_append_log`` / ``_append_log_line``) add ``ts`` (UTC, ISO 8601,
``Z``) and ``reason`` after the existing keys, which keep their names, order and values.
A reason code that fails ``REASON_RE`` becomes ``invalid_reason``; no code gives the
decision. AC-943.2 (part): the same hook run outside pytest still appends to the log.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from tools import stop_gate
from tools.tests import test_stop_gate as sg_tests

REPO = Path(__file__).resolve().parents[2]
HC_PATH = REPO / ".claude" / "hooks" / "_hook_common.py"
COMMIT_GATE = REPO / ".claude" / "hooks" / "commit_gate.py"
HOOK_LOG_ENV = "{{PROJECT_NAME_UPPER}}_HOOK_LOG"
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
REASON_RE = re.compile(r"^[a-z][a-z0-9_:-]{0,63}$")
HC_KEYS = ["hook", "session_id", "permission_mode", "command", "decision"]
SG_KEYS = ["hook", "session_id", "decision", "blocks"]
BAD_REASONS = ["has space", "Upper", "1abc", "a;b", "x" * 65]

SEED = b'{"hook": "seed", "session_id": "live-0", "decision": "allow"}\n'
DENIED = "git commit -m x"


def _load_hc() -> ModuleType:
    """Load ``_hook_common`` from its file under a private name."""
    spec = importlib.util.spec_from_file_location("pk1_hook_common", HC_PATH)
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


def _input(hc: ModuleType) -> object:
    return hc.HookInput(
        session_id="sess-pk1",
        permission_mode="default",
        command="git status",
        tool_name="Bash",
        agent_id=None,
    )


@pytest.fixture
def log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "hooks.jsonl"
    monkeypatch.setenv(HOOK_LOG_ENV, str(path))
    return path


# --- AC-943.1: the hook writer (HC) ----------------------------------------------------


def test_f2p_ac943_1_append_log_adds_ts_and_reason(log: Path) -> None:
    hc = _load_hc()
    hc.append_log("commit_gate", _input(hc), "ask")
    lines = _lines(log)
    assert len(lines) == 1
    rec = lines[0]
    assert list(rec) == [*HC_KEYS, "ts", "reason"]
    assert {k: rec[k] for k in HC_KEYS} == {
        "hook": "commit_gate",
        "session_id": "sess-pk1",
        "permission_mode": "default",
        "command": "git status",
        "decision": "ask",
    }
    assert TS_RE.fullmatch(str(rec["ts"]))
    assert rec["reason"] == "ask"


def test_f2p_ac943_1_append_log_takes_a_reason_code(log: Path) -> None:
    hc = _load_hc()
    params = inspect.signature(hc.append_log).parameters
    assert "reason" in params and params["reason"].default is None
    hc.append_log("commit_gate", _input(hc), "deny", reason="deny:headless_commit")
    rec = _lines(log)[0]
    assert rec["decision"] == "deny"
    assert rec["reason"] == "deny:headless_commit"


@pytest.mark.parametrize("bad", BAD_REASONS)
def test_f2p_ac943_1_append_log_invalid_reason_never_raises(
    log: Path, bad: str
) -> None:
    hc = _load_hc()
    assert "reason" in inspect.signature(hc.append_log).parameters
    hc.append_log("commit_gate", _input(hc), "allow", reason=bad)
    rec = _lines(log)[0]
    assert rec["reason"] == "invalid_reason"
    assert rec["decision"] == "allow"


def test_p2p_ac943_1_append_log_unwritable_target_never_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hc = _load_hc()
    monkeypatch.setenv(HOOK_LOG_ENV, str(tmp_path))  # a folder, not a file
    hc.append_log("commit_gate", _input(hc), "allow")
    assert list(tmp_path.iterdir()) == []


# --- AC-943.1: the stop-gate writers (SG) ----------------------------------------------


def test_f2p_ac943_1_stop_gate_line_adds_ts_and_reason(log: Path) -> None:
    stop_gate._append_log("sess-1", "allow", 0)
    stop_gate._append_log("sess-1", "emergency_release", 4, "2026-11-10-plan")
    first, second = _lines(log)
    assert list(first) == [*SG_KEYS, "ts", "reason"]
    assert {k: first[k] for k in SG_KEYS} == {
        "hook": "stop_gate",
        "session_id": "sess-1",
        "decision": "allow",
        "blocks": 0,
    }
    assert TS_RE.fullmatch(str(first["ts"]))
    assert first["reason"] == "allow"
    assert list(second) == [*SG_KEYS, "plan", "ts", "reason"]
    assert second["plan"] == "2026-11-10-plan"
    assert second["reason"] == "emergency_release"


def test_f2p_ac943_1_stop_gate_reason_keyword(log: Path) -> None:
    params = inspect.signature(stop_gate._append_log).parameters
    assert "reason" in params and params["reason"].default is None
    stop_gate._append_log("sess-1", "block", 1, reason="block:open_rows")
    for bad in BAD_REASONS:
        stop_gate._append_log("sess-1", "block", 2, reason=bad)
    lines = _lines(log)
    assert lines[0]["reason"] == "block:open_rows"
    assert [x["reason"] for x in lines[1:]] == ["invalid_reason"] * len(BAD_REASONS)
    assert [x["blocks"] for x in lines] == [1] + [2] * len(BAD_REASONS)


def test_f2p_ac943_1_stop_gate_other_writer_adds_ts_and_reason(log: Path) -> None:
    fields: dict[str, object] = {
        "hook": "stop_gate",
        "session_id": "sess-1",
        "decision": "notify_error",
        "error": "OSError",
    }
    stop_gate._append_log_line(dict(fields))
    rec = _lines(log)[0]
    assert list(rec) == [*fields, "ts", "reason"]
    assert {k: rec[k] for k in fields} == fields
    assert TS_RE.fullmatch(str(rec["ts"]))
    assert rec["reason"] == "notify_error"


def test_f2p_ac943_1_main_records_carry_a_reason_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    log: Path,
) -> None:
    sg_tests._make_plan(tmp_path, "2026-06-22-open", sg_tests._TASK_OPEN)
    for _ in range(stop_gate.MAX_CONSECUTIVE_BLOCKS + 1):
        assert sg_tests._run_main(monkeypatch, tmp_path, sg_tests._STOP_PAYLOAD) == 0
    sg_tests._make_plan(tmp_path, "2026-06-22-open", sg_tests._TASK_DONE)
    assert sg_tests._run_main(monkeypatch, tmp_path, sg_tests._STOP_PAYLOAD) == 0
    capsys.readouterr()
    lines = _lines(log)
    decisions = [x["decision"] for x in lines]
    assert decisions == (
        ["block"] * stop_gate.MAX_CONSECUTIVE_BLOCKS + ["release", "allow"]
    )
    reasons = [str(x.get("reason")) for x in lines]
    assert all(REASON_RE.fullmatch(x) for x in reasons), reasons
    assert all(re.fullmatch(r"block(:[a-z0-9_:-]+)?", x) for x in reasons[:-2])
    assert re.fullmatch(r"release(:[a-z0-9_:-]+)?", reasons[-2])
    assert reasons[-1] == "allow"
    assert all(TS_RE.fullmatch(str(x.get("ts"))) for x in lines)


# --- AC-943.2: the same hook outside pytest still appends ------------------------------


def _child_env(live: Path) -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("PYTEST_ADDOPTS", "PYTEST_CURRENT_TEST")
    }
    env[HOOK_LOG_ENV] = str(live)
    return env


def test_p2p_ac943_2_the_same_hook_outside_pytest_appends(tmp_path: Path) -> None:
    live = tmp_path / "live-hook-log.jsonl"
    live.write_bytes(SEED)
    payload = {
        "session_id": "sess-pk1",
        "transcript_path": "C:/tmp/transcript.jsonl",
        "cwd": str(REPO),
        "permission_mode": "bypassPermissions",
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": DENIED},
        "tool_use_id": "toolu_pk1",
    }
    proc = subprocess.run(
        [sys.executable, str(COMMIT_GATE)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_child_env(live),
        cwd=REPO,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    data = live.read_bytes()
    assert data.startswith(SEED)
    added = [json.loads(x) for x in data[len(SEED) :].decode("utf-8").splitlines()]
    assert len(added) == 1
    assert added[0]["hook"] == "commit_gate"
    assert added[0]["decision"] == "deny"
    assert added[0]["command"] == DENIED
