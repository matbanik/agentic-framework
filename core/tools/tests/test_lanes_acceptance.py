"""MEU-785 AC-785.25: two lanes land in turn behind the real ref guard — red first (G19).

FIC: ``docs/execution/plans/2026-10-22-lane-branches-governed-land/implementation-plan.md``
AC-785.25 (design D:240-252, D:384; the ``main_moved`` edge is AC-785.19, D:250).

One disposable files-backend repository (``phase_b3``, ``git init -b main``, SSH signing,
a marked run-parameters store) in ``tmp_path``, with the real ref guard installed by
``python tools/ref_guard.py install`` (the ``test_ref_guard.py`` ``_guarded_rig`` order: drop
the fixture's outside ``core.hooksPath``, then install) after the fixture's seed commits. Lanes A (the fixture plan) and B
(the second fixture plan) both start at P0, and each handoff carries one ``metrics-row`` integration request. A lands
(prepare, verdict, publish through the fixture human route). B's publish with its old P
refuses ``main_moved`` and returns the card to ``active``; B then lands on the new P.
Each land adds exactly one commit to ``main`` with tree(C) == tree(T), and the main tree
equals C after it. A direct ``update-ref`` of ``refs/heads/main`` is refused by the guard.

The guard installs on Git for Windows only (D§9.2); the platform marker is the
``test_ref_guard.py`` one. The guard is never installed in a real repository. Do not skip,
only, or early-return (G36).
"""

from __future__ import annotations

import dataclasses
import subprocess
import sys
from pathlib import Path

import pytest

from tools.tests.run_parameters_fixtures import build_fixture as bf
from tools.tests.run_parameters_fixtures import phase_b3 as b3
from tools.tests import test_lanes_recovery as rec
from tools.tests import test_ref_guard as rg
from tools.tests import lane_worktree_config as lwc

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "tools" / "ref_guard.py"
MAIN = "refs/heads/main"
OP_A = "op-accept-a"
OP_B_STALE = "op-accept-b-1"
OP_B = "op-accept-b-2"
LANE_A_SESSION = "s-lane-a"
LANE_B_SESSION = "s-lane-b"
DATE = "2026-10-23"


def _metrics_row(plan: str) -> str:
    return f"| {DATE} | {plan} | landed |"


def _guarded(rig: b3.Rig) -> None:
    """Install the real ref guard in the fixture repository (``_guarded_rig`` order)."""
    rig.git("config", "--unset", "core.hooksPath")
    proc = subprocess.run(
        [sys.executable, str(GUARD), "install"],
        cwd=str(rig.repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=rig.fx.env(**{rg.SWITCH: None}),
        timeout=rec.CLI_TIMEOUT_S,
        check=False,
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)


def _parents(lr: rec.LaneRig, commit: str) -> list[str]:
    return rec.git(lr.repo, "rev-list", "--parents", "-n", "1", commit).split()[1:]


def _tree(lr: rec.LaneRig, commit: str) -> str:
    return rec.git(lr.repo, "rev-parse", f"{commit}^{{tree}}")


def _metrics_at(lr: rec.LaneRig, commit: str) -> list[str]:
    return rec.git(lr.repo, "show", f"{commit}:{rec.METRICS}").splitlines()


def _landed(lr: rec.LaneRig, parent: str, tree: str, op: str) -> str:
    """One new ``main`` commit on ``parent`` with tree ``tree``; the land closed; return C."""
    c = rec.main_ref(lr)
    assert _parents(lr, c) == [parent]
    assert rec.git(lr.repo, "rev-list", "--count", f"{parent}..{c}") == "1"
    assert _tree(lr, c) == tree
    assert rec.phases(lr, op)[-1] == ("land:closed", "done"), rec.phases(lr, op)
    rec.assert_main_tree_at(lr, c)
    return c


def _legacy_plan_b(rig: b3.Rig) -> None:
    """Plan B's ``task.md`` carries no ``run_parameters`` block (a legacy plan).

    The fixture gives plan B plan A's granted block. A granted plan that is not bound
    to the session is not one a human direction resolves to, and the session already
    binds plan A; a legacy plan resolves when the direction names it (EA-50, EA-66).
    """
    task = rig.fx.task_path(bf.PLAN_B)
    task.write_text(
        f"---\nstatus: in_progress\n---\n\n# Task: {bf.PLAN_B}\n\n"
        "| # | Task | Status |\n| :- | :- | :- |\n| 0 | fixture row | [ ] |\n",
        encoding="utf-8",
        newline="\n",
    )


# Two full lands run some 30 git and lanes.py subprocesses (46 s alone); under a loaded
# xdist gate the 120 s default ends the worker. Each subprocess keeps its own
# CLI_TIMEOUT_S, so this outer bound only catches a hang (EA-67).
@pytest.mark.timeout(600)
@rg.WINDOWS
def test_two_lanes_land_in_turn_behind_the_ref_guard(tmp_path: Path) -> None:
    rig = b3.rig(tmp_path / "fx", ROOT, seed=lwc.SEED)
    rig.bind()
    _legacy_plan_b(rig)
    rec.seed_plan(rig, rig.plan, {rec.METRICS: rec.METRICS_HEAD.encode()})
    rec.seed_plan(rig, bf.PLAN_B)
    p0 = rig.ref()
    lane_a = rec.open_lane(
        rig,
        tmp_path,
        rig.plan,
        LANE_A_SESSION,
        requests=[f"metrics-row {_metrics_row(rig.plan)}"],
    )
    lane_b = rec.open_lane(
        rig,
        tmp_path,
        bf.PLAN_B,
        LANE_B_SESSION,
        requests=[f"metrics-row {_metrics_row(bf.PLAN_B)}"],
    )
    assert lane_a.p == lane_b.p == p0
    # The guard goes in after the fixture's own direct commits on main (it refuses them).
    _guarded(rig)

    # Both lanes are prepared and reviewed at P0.
    tree_a = rec.ready(lane_a, OP_A)
    rec.ready(lane_b, OP_B_STALE)

    # A lands: one commit on P0, tree(C1) == tree(T_A), its integration request applied.
    rec.ok(rec.publish(lane_a, OP_A))
    c1 = _landed(lane_a, p0, tree_a, OP_A)
    assert _metrics_row(rig.plan) in _metrics_at(lane_a, c1)

    # B publishes with its old P: main moved, the card goes back to active (AC-785.19).
    rec.refused(rec.publish(lane_b, OP_B_STALE), "main_moved")
    assert rec.main_ref(lane_b) == c1
    assert rec.card(lane_b)["state"] == "active"
    assert rec.card(lane_b).get("op") is None

    # B restarts at step 1 on the new P and lands after A.
    lane_b_again = dataclasses.replace(
        lane_b, p=c1, l0=rec.git(lane_b.repo, "rev-parse", lane_b.branch_ref)
    )
    tree_b = rec.ready(lane_b_again, OP_B)
    rec.ok(rec.publish(lane_b_again, OP_B))
    c2 = _landed(lane_b_again, c1, tree_b, OP_B)
    metrics = _metrics_at(lane_b_again, c2)
    assert _metrics_row(rig.plan) in metrics
    assert _metrics_row(bf.PLAN_B) in metrics
    assert rig.reflog()[-2:] == [(p0, c1), (c1, c2)]

    # The guard refuses a direct move of main (no open commit_batch intent).
    direct = subprocess.run(
        ["git", "update-ref", MAIN, p0, c2],
        cwd=str(rig.repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=rig.fx.env(**{rg.SWITCH: None}),
        timeout=rec.CLI_TIMEOUT_S,
        check=False,
    )
    assert direct.returncode != 0, (direct.stdout, direct.stderr)
    assert rec.main_ref(lane_b_again) == c2
    rec.assert_main_tree_at(lane_b_again, c2)
