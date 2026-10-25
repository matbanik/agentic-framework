"""MEU-785 execution review round 3 corrections (R3-F1) — red first (G19).

FIC: ``docs/execution/plans/2026-10-22-lane-branches-governed-land/implementation-plan.md``
AC-785.21 / AC-785.23 (design §5.5 steps 8-9, D:258-266).

R3-F1: a lane may replace a tracked folder with a file, or a tracked file with a folder.
Step 8 classified every folder at a changed path as a blob of neither P nor C, so a
clean land published C and then refused ``sync_unexplained:<folder>`` at every recovery.
A folder whose every file is one of the classified paths is explained; a folder that
holds any other file is still unexplained, and the refusal names that file. The rigs are
the disposable lane rigs of ``test_lanes_recovery.py`` (a real ``phase_b3`` repository in
``tmp_path``). Do not skip, only, or early-return (G36).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tools.tests import lane_worktree_config as lwc
from tools.tests import test_lanes_recovery as lrx
from tools.tests.run_parameters_fixtures import phase_b3 as b3

# The tracked layout under ``src/<plan>/`` at P and at C, for each topology change.
AT_P = {
    "folder-to-file": {
        "shape/old.txt": b"tracked folder child at P\n",
        "shape/deep/inner.txt": b"nested tracked child at P\n",
    },
    "file-to-folder": {"shape": b"tracked file at P\n"},
}
AT_C = {
    "folder-to-file": {"shape": b"tracked file at C\n"},
    "file-to-folder": {
        "shape/new.txt": b"tracked folder child at C\n",
        "shape/deep/inner.txt": b"nested tracked child at C\n",
    },
}
KINDS = sorted(AT_P)


def _lay_out(root: Path, plan: str, layout: dict[str, bytes]) -> None:
    """Replace ``src/<plan>/shape`` under ``root`` with ``layout`` (exact bytes)."""
    shape = root / "src" / plan / "shape"
    if shape.is_dir():
        shutil.rmtree(shape)
    elif shape.exists():
        shape.unlink()
    for rel, data in layout.items():
        full = root / "src" / plan / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(data)


def _topology_rig(tmp_path: Path, kind: str) -> lrx.LaneRig:
    """The lane rig of ``lrx.lane_rig`` with P's ``shape`` layout; the lane commits C's."""
    rig = b3.rig(tmp_path / "fx", lrx.ROOT, seed=lwc.SEED)
    rig.bind()
    extra = {lrx.METRICS: lrx.METRICS_HEAD.encode()}
    extra.update({f"src/{rig.plan}/{rel}": data for rel, data in AT_P[kind].items()})
    lrx.seed_plan(rig, rig.plan, extra)
    lr = lrx.open_lane(rig, tmp_path, rig.plan, lrx.CARD_SESSION)
    _lay_out(lr.wt, lr.plan, AT_C[kind])
    lrx.git(lr.wt, "add", "-A")
    lrx.git(lr.wt, "commit", "-q", "-m", f"lane: {kind}")
    lr.l0 = lrx.git(lr.wt, "rev-parse", "HEAD")
    assert lrx.git(lr.repo, "status", "--porcelain", "-uall") == "", "main not clean"
    return lr


def _assert_landed(lr: lrx.LaneRig, c: str, kind: str) -> None:
    """The land is closed and the main checkout holds C's ``shape`` layout exactly."""
    lrx.assert_closed(lr)
    lrx.assert_main_tree_at(lr, c)
    for rel, data in AT_C[kind].items():
        assert (lr.repo / "src" / lr.plan / rel).read_bytes() == data, rel
    for rel in AT_P[kind]:
        if rel not in AT_C[kind]:
            assert not (lr.repo / "src" / lr.plan / rel).is_file(), rel
    assert ("land:sync", "refused:sync_unexplained") not in lrx.phases(lr)


@pytest.mark.parametrize("kind", KINDS)
def test_r3_f1_a_clean_land_across_a_file_folder_change_closes(
    tmp_path: Path, kind: str
) -> None:
    """R3-F1, AC-785.21: publish of a clean lane that swaps a file and a folder syncs the
    main checkout to C and closes the land."""
    lr = _topology_rig(tmp_path, kind)
    lrx.ready(lr)
    lrx.ok(lrx.publish(lr))
    c = lrx.main_ref(lr)
    assert c != lr.p
    _assert_landed(lr, c, kind)


@pytest.mark.parametrize("state", ["index-and-work-at-p", "work-at-c"])
@pytest.mark.parametrize("kind", KINDS)
def test_r3_f1_an_interrupted_sync_across_a_file_folder_change_recovers(
    tmp_path: Path, kind: str, state: str
) -> None:
    """R3-F1, AC-785.23 row "Step 8 partly done": a crash at ``land:sync:started``, with
    the working layout still at P or already at C (index at P), recovers and closes."""
    lr = _topology_rig(tmp_path, kind)
    lrx.ready(lr)
    lrx.crashed(lrx.publish(lr, env={lrx.CRASH: "land:sync:started"}))
    c = lrx.main_ref(lr)
    assert c != lr.p
    if state == "work-at-c":
        _lay_out(lr.repo, lr.plan, AT_C[kind])
    lrx.ok(lrx.recover(lr))
    assert lrx.main_ref(lr) == c
    _assert_landed(lr, c, kind)


@pytest.mark.parametrize("kind", KINDS)
def test_r3_f1_an_untracked_file_in_a_changed_folder_still_stops_the_sync(
    tmp_path: Path, kind: str
) -> None:
    """R3-F1, AC-785.21 (R1-F1 kept): an untracked file inside a folder that the sync
    would replace or create is nobody's tracked content; recovery refuses and names it,
    and every byte stays in place."""
    lr = _topology_rig(tmp_path, kind)
    lrx.ready(lr)
    lrx.crashed(lrx.publish(lr, env={lrx.CRASH: "land:sync:started"}))
    if kind == "file-to-folder":
        _lay_out(lr.repo, lr.plan, AT_C[kind])
    note = lr.repo / "src" / lr.plan / "shape" / "deep" / "note.txt"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_bytes(b"untracked note\n")
    before = {
        path.relative_to(lr.repo).as_posix(): path.read_bytes()
        for path in (lr.repo / "src" / lr.plan / "shape").rglob("*")
        if path.is_file()
    }
    for _ in range(2):
        lrx.refused(
            lrx.recover(lr), f"sync_unexplained:src/{lr.plan}/shape/deep/note.txt"
        )
    after = {
        path.relative_to(lr.repo).as_posix(): path.read_bytes()
        for path in (lr.repo / "src" / lr.plan / "shape").rglob("*")
        if path.is_file()
    }
    assert after == before
    assert ("land:closed", "done") not in lrx.phases(lr)
