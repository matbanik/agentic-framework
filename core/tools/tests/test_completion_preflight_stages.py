"""B-4: ``completion_preflight.py --stage structural|readiness|final`` (AC-D.3, AC-D.6).

Plan: the run-parameters design plan (B-4; report R§4.6 "Check-by-stage
matrix": "``completion_preflight.py`` gains the same three stages with the same pending
sets"). Vectors V4-001, V4-005 and V4-006.

The stage mode is a new CLI mode, mutually exclusive with the legacy ``--json`` contract that
``tools/tests/test_completion_preflight.py`` fixes (and that file stays byte-unchanged):

* ``--stage <s> --plan <folder> --tree <path>`` prints one JSON object
  ``{"ok", "stage", "missing", "details"}``; exit 0 ok, 1 a check missing, 2 usage (an unknown
  stage, or ``--stage`` with ``--json``).
* The stage checks are the six legacy ids plus ``plan_task_status``: ``task_rows`` honours the
  stage's pending set, ``stop_gate`` expects ``armed`` before ``final`` and ``released:done``
  at ``final``, and ``plan_task_status`` expects the plan's and the task's ``status`` equal to
  the stage's value (``in_progress``, ``in_progress``, ``complete``).
* ``PENDING_SETS`` is one constant, equal in both validators.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from tools.tests.test_completion_preflight import (
    PLAN,
    PLAN_REL,
    ROWS_DONE,
    TASK_HEADER,
    check,
    make_tree,
    run_tool,
    write,
)

STAGES = ("structural", "readiness", "final")
STAGE_STATUS = {
    "structural": "in_progress",
    "readiness": "in_progress",
    "final": "complete",
}
STAGE_GATE = {"structural": "armed", "readiness": "armed", "final": "released:done"}
CLOSE_ROWS = ("H2-4", "H2-5", "COMMIT", "H2-6")
PENDING = {
    "structural": frozenset({"H2-4", "H2-5", "COMMIT", "H2-6"}),
    "readiness": frozenset({"H2-5", "COMMIT", "H2-6"}),
    "final": frozenset(),
}


def stage_tree(
    tmp_path: Path,
    stage: str,
    *,
    plan_status: str | None = None,
    task_status: str | None = None,
    gate: str | None = None,
    open_rows: frozenset[str] | None = None,
) -> Path:
    """A legacy-checks-passing tree rewritten for ``stage``: statuses, gate and closeout rows."""
    tree = make_tree(tmp_path)
    pending = PENDING[stage] if open_rows is None else open_rows
    rows = ROWS_DONE + "".join(
        f"| {row} | Closeout {row} | coordinator | evidence | {'[ ]' if row in pending else '[x]'} |\n"
        for row in CLOSE_ROWS
    )
    write(
        tree / PLAN_REL / "task.md",
        "---\n"
        f'project: "{PLAN}"\n'
        f'status: "{task_status or STAGE_STATUS[stage]}"\n'
        f'stop_gate: "{gate or STAGE_GATE[stage]}"\n'
        "meus: []\n"
        "---\n\n"
        "# Task\n\n" + TASK_HEADER + rows,
    )
    write(
        tree / PLAN_REL / "implementation-plan.md",
        "---\n"
        f'status: "{plan_status or STAGE_STATUS[stage]}"\n'
        "---\n\n# Plan\n\nThe fixture plan.\n",
    )
    return tree


def run_stage(tree: Path, stage: str, *extra: str) -> tuple[int, dict[str, Any]]:
    """Run ``--stage`` on ``tree``; return the exit code and the JSON object."""
    proc = run_tool("--stage", stage, "--plan", PLAN_REL, "--tree", str(tree), *extra)
    try:
        doc = json.loads(proc.stdout)
    except ValueError:
        doc = {"_stdout": proc.stdout, "_stderr": proc.stderr}
    return proc.returncode, doc


@pytest.mark.parametrize("stage", STAGES)
def test_vec_v4_001_each_stage_passes_its_own_tree(tmp_path: Path, stage: str) -> None:
    """AC-D.3: a tree in the stage's own state passes that stage (its pending rows open)."""
    code, doc = run_stage(stage_tree(tmp_path, stage), stage)
    assert code == 0, doc
    assert doc.get("ok") is True, doc
    assert doc.get("stage") == stage, doc
    assert doc.get("missing") == [], doc


@pytest.mark.parametrize("stage", STAGES)
def test_vec_v4_005_plan_task_status_mismatch_fails(tmp_path: Path, stage: str) -> None:
    """AC-D.3: ``PLAN_TASK_STATUS`` differs between task.md and the plan → that stage fails
    with ``plan_task_status``."""
    other = "complete" if STAGE_STATUS[stage] == "in_progress" else "in_progress"
    code, doc = run_stage(stage_tree(tmp_path, stage, plan_status=other), stage)
    assert code == 1, doc
    assert "plan_task_status" in doc.get("missing", []), doc


def test_vec_v4_006_readiness_allows_only_its_pending_set(tmp_path: Path) -> None:
    """AC-D.3: H2-5's own row may be pending during readiness; H2-4 may not."""
    code, doc = run_stage(stage_tree(tmp_path, "readiness"), "readiness")
    assert (code, doc.get("missing")) == (0, []), doc
    tree = stage_tree(
        tmp_path / "h2-4", "readiness", open_rows=PENDING["readiness"] | {"H2-4"}
    )
    code, doc = run_stage(tree, "readiness")
    assert code == 1, doc
    assert "task_rows" in doc.get("missing", []), doc
    assert "H2-4" in json.dumps(doc.get("details", {})), doc


def test_vec_v4_006_final_allows_no_open_row(tmp_path: Path) -> None:
    """AC-D.3: at ``final`` no row is open, H2-6 included."""
    tree = stage_tree(tmp_path, "final", open_rows=frozenset({"H2-6"}))
    code, doc = run_stage(tree, "final")
    assert code == 1, doc
    assert "task_rows" in doc.get("missing", []), doc


@pytest.mark.parametrize(
    ("stage", "gate"),
    [
        ("structural", "released:done"),
        ("readiness", "released:done"),
        ("final", "armed"),
    ],
)
def test_vec_v4_001_stop_gate_value_per_stage(
    tmp_path: Path, stage: str, gate: str
) -> None:
    """AC-D.3: ``stop_gate`` is ``armed`` before ``final`` and ``released:done`` at it."""
    code, doc = run_stage(stage_tree(tmp_path, stage, gate=gate), stage)
    assert code == 1, doc
    assert "stop_gate" in doc.get("missing", []), doc


def test_ac_d6_stage_and_json_are_mutually_exclusive(tmp_path: Path) -> None:
    """AC-D.6: ``--stage final`` with ``--plan --tree --json`` is a usage error (exit 2)."""
    code, doc = run_stage(stage_tree(tmp_path, "final"), "final", "--json")
    assert code == 2, doc


def test_ac_d6_unknown_stage_is_a_usage_error(tmp_path: Path) -> None:
    """AC-D.6: a stage outside ``structural|readiness|final`` exits 2."""
    code, doc = run_stage(stage_tree(tmp_path, "final"), "sealed")
    assert code == 2, doc


def test_ac_d6_legacy_json_mode_is_unchanged(tmp_path: Path) -> None:
    """AC-D.6: the legacy ``--plan --tree --json`` keeps its six checks and its JSON."""
    code, doc = check(make_tree(tmp_path))
    assert (code, doc) == (0, {"ok": True, "missing": [], "details": {}})
    module = importlib.import_module("tools.completion_preflight")
    assert tuple(module.CHECK_IDS) == (
        "task_rows",
        "stop_gate",
        "approved_verdict",
        "handoff",
        "reflection",
        "metrics",
    )
    assert module.STAGES == STAGES


def test_ac_d3_pending_sets_are_one_constant() -> None:
    """AC-D.3: both validators carry the same pending sets, the matrix's row column."""
    preflight = importlib.import_module("tools.completion_preflight")
    closeout = importlib.import_module("tools.validate_closeout_artifacts")
    assert preflight.PENDING_SETS == PENDING
    assert closeout.PENDING_SETS == PENDING
