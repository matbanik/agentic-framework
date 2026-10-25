"""MEU-785 execution review round 4 corrections (R4-F1) — red first (G19).

FIC: ``docs/execution/plans/2026-10-22-lane-branches-governed-land/implementation-plan.md``
AC-785.21 / AC-785.23 (design §5.5 steps 8-9, D:258-266; §5.3 case-folded path identity,
D:226).

R4-F1: a lane may rename a tracked file by case only (``Widget.py`` to ``widget.py``) and
edit it. With ``core.ignorecase`` true both Git names are one working file, and step 8
compared that file with each name's own P and C blobs only, so a clean land published C
and then refused ``sync_unexplained:<new name>`` at every recovery. The working file of
names that fold to one key is at P when it holds P's blob of the name P has, and at C when
it holds C's blob of the name C has; any other bytes are still unexplained. Where the
filesystem is case-sensitive the two names are two files and the cases check the ordinary
rename. The rigs are the disposable lane rigs of ``test_lanes_recovery.py`` (a real
``phase_b3`` repository in ``tmp_path``). Do not skip, only, or early-return (G36).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tools.tests import lane_worktree_config as lwc
from tools.tests import test_lanes_recovery as lrx
from tools.tests.run_parameters_fixtures import phase_b3 as b3

AT_P = b"VALUE = 0\n"
EDITED = b"VALUE = 1\n"
FOREIGN = b"VALUE = 2  # an edit of nobody's lane\n"
EDITS = {"edited": EDITED, "unchanged": AT_P}


def _rename_rig(tmp_path: Path, at_c: bytes) -> lrx.LaneRig:
    """The lane rig with a tracked ``Widget.py`` at P; the lane renames it to ``widget.py``
    by case only, with ``at_c`` as its bytes at C."""
    rig = b3.rig(tmp_path / "fx", lrx.ROOT, seed=lwc.SEED)
    rig.bind()
    lrx.seed_plan(
        rig,
        rig.plan,
        {lrx.METRICS: lrx.METRICS_HEAD.encode(), f"src/{rig.plan}/Widget.py": AT_P},
    )
    lr = lrx.open_lane(rig, tmp_path, rig.plan, lrx.CARD_SESSION)
    lrx.git(
        lr.wt, "mv", "--force", f"src/{lr.plan}/Widget.py", f"src/{lr.plan}/widget.py"
    )
    (lr.wt / "src" / lr.plan / "widget.py").write_bytes(at_c)
    lrx.git(lr.wt, "add", "-A")
    lrx.git(lr.wt, "commit", "-q", "-m", "lane: case-only rename")
    lr.l0 = lrx.git(lr.wt, "rev-parse", "HEAD")
    assert lrx.git(lr.repo, "status", "--porcelain", "-uall") == "", "main not clean"
    return lr


def _names(lr: lrx.LaneRig) -> list[str]:
    """The exact names on disk in the plan's ``src`` folder."""
    return sorted(os.listdir(lr.repo / "src" / lr.plan))


def _assert_landed(lr: lrx.LaneRig, c: str, at_c: bytes) -> None:
    """The land is closed and the main checkout holds ``widget.py`` exactly as at C."""
    lrx.assert_closed(lr)
    lrx.assert_main_tree_at(lr, c)
    assert _names(lr) == ["lane.py", "widget.py"]
    assert (lr.repo / "src" / lr.plan / "widget.py").read_bytes() == at_c
    assert ("land:sync", "refused:sync_unexplained") not in lrx.phases(lr)


@pytest.mark.parametrize("edit", sorted(EDITS))
def test_r4_f1_a_clean_land_with_a_case_only_rename_closes(
    tmp_path: Path, edit: str
) -> None:
    """R4-F1, AC-785.21: publish of a clean lane that renames a file by case only, with or
    without an edit, syncs the main checkout to C and closes the land."""
    lr = _rename_rig(tmp_path, EDITS[edit])
    lrx.ready(lr)
    lrx.ok(lrx.publish(lr))
    c = lrx.main_ref(lr)
    assert c != lr.p
    _assert_landed(lr, c, EDITS[edit])


@pytest.mark.parametrize("state", ["index-and-work-at-p", "work-at-c"])
def test_r4_f1_an_interrupted_sync_with_a_case_only_rename_recovers(
    tmp_path: Path, state: str
) -> None:
    """R4-F1, AC-785.23 row "Step 8 partly done": a crash at ``land:sync:started``, with
    the renamed and edited file still at P or already at C (index at P), recovers and
    closes; a second recovery changes nothing."""
    lr = _rename_rig(tmp_path, EDITED)
    lrx.ready(lr)
    lrx.crashed(lrx.publish(lr, env={lrx.CRASH: "land:sync:started"}))
    c = lrx.main_ref(lr)
    assert c != lr.p
    if state == "work-at-c":
        (lr.repo / "src" / lr.plan / "Widget.py").unlink()
        (lr.repo / "src" / lr.plan / "widget.py").write_bytes(EDITED)
    lrx.ok(lrx.recover(lr))
    assert lrx.main_ref(lr) == c
    _assert_landed(lr, c, EDITED)
    lrx.ok(lrx.recover(lr))
    _assert_landed(lr, c, EDITED)


def test_r4_f1_a_foreign_edit_of_the_renamed_file_still_stops_the_sync(
    tmp_path: Path,
) -> None:
    """R4-F1, AC-785.21 (R1-F1 kept): bytes at neither P nor C in the file that both names
    share are nobody's tracked content; recovery refuses and names it, and the file keeps
    its name and bytes."""
    lr = _rename_rig(tmp_path, EDITED)
    lrx.ready(lr)
    lrx.crashed(lrx.publish(lr, env={lrx.CRASH: "land:sync:started"}))
    (lr.repo / "src" / lr.plan / "Widget.py").write_bytes(FOREIGN)
    for _ in range(2):
        lrx.refused(lrx.recover(lr), f"sync_unexplained:src/{lr.plan}/Widget.py")
    assert _names(lr) == ["Widget.py"]
    assert (lr.repo / "src" / lr.plan / "Widget.py").read_bytes() == FOREIGN
    assert ("land:closed", "done") not in lrx.phases(lr)
