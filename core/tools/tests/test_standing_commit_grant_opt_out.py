"""MEU-939 execution-review round 1 fix R1-F7: both carriers can opt out of the standing grant.

Plan: docs/execution/plans/2026-11-07-standing-commit-grant (AC-939.1, AC-939.3; D-1 A,
SG-D3). Review:
``.agent/context/handoffs/2026-11-07-standing-commit-grant-implementation-critical-review.md``
Round 1, finding R1-F7.

The contract these tests fix (``tools.run_parameters._standing_opt_out`` and its caller
``standing_authority``):

* The ``task.md`` block and the ``implementation-plan.md`` block are read independently. A
  missing ``task.md`` or a legacy one (no ``run_parameters`` block) never hides a manual or a
  false enabling boolean in ``implementation-plan.md``: the plan refuses
  ``standing_opt_out:manual`` or ``standing_opt_out:<key>``.
* Each present block passes V-0 (``_check_block``); a malformed one refuses ``schema``.
* With no block in either carrier the plan never opts out (the AC-939.1 / AC-939.3 legacy and
  missing-carrier rule), and a valid task block behaves as before.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from tools.tests.run_parameters_fixtures import build_fixture as bf
from tools.tests.run_parameters_fixtures import phase_b3 as b3
from tools.tests import test_standing_commit_grant as sg

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
MISSING = "2026-11-03-missing-task"
LEGACY = "2026-11-04-legacy-task"
BARE = "2026-11-05-no-blocks"


def _rp() -> ModuleType:
    return importlib.import_module("tools.run_parameters")


def _plan_md(rig: b3.Rig, plan: str, block: dict[str, Any] | None) -> None:
    """``implementation-plan.md`` of ``plan``: frontmatter with ``block``, or a bare heading."""
    head = (
        bf.frontmatter(
            {"plan": plan, "template_version": "2.3", "run_parameters": block}
        )
        if block is not None
        else ""
    )
    rig.fx.write_text(
        f"docs/execution/plans/{plan}/implementation-plan.md",
        f"{head}\n# Implementation plan: {plan}\n",
    )


def _legacy_task(rig: b3.Rig, plan: str) -> None:
    """A ``task.md`` with no frontmatter and so no ``run_parameters`` block."""
    rig.fx.write_text(
        f"docs/execution/plans/{plan}/task.md",
        f"# Task: {plan}\n\n| # | Task | Status |\n| :- | :- | :- |\n| 0 | row | [ ] |\n",
    )


def _manual(rig: b3.Rig) -> dict[str, Any]:
    return {**rig.fx.block, "authorization": {"schema": "manual"}}


def _false(rig: b3.Rig, key: str) -> dict[str, Any]:
    return {**rig.fx.block, key: False, "tightened_from": "grouping"}


def _opt_out(rig: b3.Rig, plan: str, act: str) -> tuple[str, str] | None:
    """``(reason, detail)`` of ``_standing_opt_out`` for ``plan`` and ``act``; None when it passes."""
    rp = _rp()
    with bf.patched_environ(rig.fx.env()):
        repo = rp._open_repo(rig.fx.repo)
        try:
            rp._standing_opt_out(repo, plan, act)
        except rp.Refusal as exc:
            return str(exc.reason), str(exc.detail)
    return None


def test_r1_f7_missing_task_and_a_manual_plan_block_opt_out(tmp_path: Path) -> None:
    """R1-F7: no ``task.md``; a manual ``implementation-plan.md`` opts out of every standing act."""
    rig = sg._rig(tmp_path)
    _plan_md(rig, MISSING, _manual(rig))
    rig.fx.commit("fixture: a plan with no task carrier")
    for act in sg.STANDING_GRANTS:
        assert _opt_out(rig, MISSING, act) == ("standing_opt_out", "manual"), act
    assert sg._opt_out(rig.fx, MISSING, "exec_commit") == "manual"


def test_r1_f7_legacy_task_and_a_manual_plan_block_opt_out_on_the_grant_route(
    tmp_path: Path,
) -> None:
    """R1-F7: a legacy ``task.md`` beside a manual plan block refuses ``standing_opt_out:manual``.

    The grant route under a live standing grant refuses too, and no ref moves.
    """
    rig = sg._rig(tmp_path)
    _legacy_task(rig, LEGACY)
    _plan_md(rig, LEGACY, _manual(rig))
    rig.fx.commit("fixture: a legacy task with a manual plan block")
    uid = sg._grant(rig.fx)
    for act in sg.STANDING_GRANTS:
        assert _opt_out(rig, LEGACY, act) == ("standing_opt_out", "manual"), act
    before = rig.ref()
    res = rig.commit("op-1", rig.packet(plan=LEGACY))
    assert sg._commit_refusal(res) == ("standing_opt_out", "manual")
    assert rig.ref() == before
    assert sg._envelope(rig.fx, uid)["consumed"] == {}


def test_r1_f7_legacy_task_and_a_false_commit_exec_opt_out(tmp_path: Path) -> None:
    """R1-F7: a legacy ``task.md`` beside ``commit_exec: false`` opts out of exec_commit and finalize only."""
    rig = sg._rig(tmp_path)
    _legacy_task(rig, LEGACY)
    _plan_md(rig, LEGACY, _false(rig, "commit_exec"))
    rig.fx.commit("fixture: a legacy task with commit_exec false")
    assert _opt_out(rig, LEGACY, "exec_commit") == ("standing_opt_out", "commit_exec")
    assert _opt_out(rig, LEGACY, "finalize") == ("standing_opt_out", "commit_exec")
    assert _opt_out(rig, LEGACY, "plan_commit") is None


def test_r1_f7_missing_task_and_a_false_commit_plan_opt_out(tmp_path: Path) -> None:
    """R1-F7: no ``task.md``; ``commit_plan: false`` opts out of plan_commit only."""
    rig = sg._rig(tmp_path)
    _plan_md(rig, MISSING, _false(rig, "commit_plan"))
    rig.fx.commit("fixture: a plan block with commit_plan false")
    assert _opt_out(rig, MISSING, "plan_commit") == ("standing_opt_out", "commit_plan")
    assert _opt_out(rig, MISSING, "exec_commit") is None


def test_r1_f7_no_block_in_either_carrier_never_opts_out(tmp_path: Path) -> None:
    """R1-F7: with no block in either carrier, or no carrier at all, the plan never opts out."""
    rig = sg._rig(tmp_path)
    _legacy_task(rig, LEGACY)
    _plan_md(rig, LEGACY, None)
    _plan_md(rig, BARE, None)
    rig.fx.commit("fixture: plans with no run_parameters block")
    for plan in (LEGACY, BARE, MISSING, "none"):
        for act in sg.STANDING_GRANTS:
            assert _opt_out(rig, plan, act) is None, (plan, act)
    uid = sg._grant(rig.fx)
    live = sg._authority(rig.fx, LEGACY, "exec_commit")
    assert live is not None and live["message_uuid"] == uid


def test_r1_f7_a_malformed_plan_block_refuses_schema(tmp_path: Path) -> None:
    """R1-F7: a present ``implementation-plan.md`` block is checked even with a legacy task."""
    rig = sg._rig(tmp_path)
    _legacy_task(rig, LEGACY)
    _plan_md(rig, LEGACY, {**rig.fx.block, "unknown": True})
    rig.fx.commit("fixture: a malformed plan block")
    assert _opt_out(rig, LEGACY, "exec_commit") == ("schema", "block_keys")


def test_r1_f7_a_valid_task_block_keeps_its_behavior(tmp_path: Path) -> None:
    """R1-F7: the fixture plan's own valid blocks do not opt out; a task-only false still does."""
    rig = sg._rig(tmp_path)
    for act in sg.STANDING_GRANTS:
        assert _opt_out(rig, rig.plan, act) is None, act
    tight = _false(rig, "commit_exec")
    rig.fx.write_carrier(rig.fx.block, task_block=tight, grouping_values=rig.fx.block)
    rig.fx.commit("fixture: commit_exec false in the task block only")
    assert _opt_out(rig, rig.plan, "exec_commit") == ("standing_opt_out", "commit_exec")
    assert _opt_out(rig, rig.plan, "plan_commit") is None
