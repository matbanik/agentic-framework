"""MEU-785 execution review round 5 corrections (R5-F1, R5-F2, R5-F3) — red first (G19).

FIC: ``docs/execution/plans/2026-10-22-lane-branches-governed-land/implementation-plan.md``
AC-785.19 / AC-785.21 / AC-785.23 / AC-785.33 (design §5.3 Git ``-z`` paths, D:226; §5.5
steps 8-9, D:251 and D:258-266).

R5-F1: step 8 took a working file to be a classified path when its name folded to the
same key. ``strasse.py`` and ``straße.py``, or a composed and a decomposed ``Café.py``, are
two files on Windows; under a folder that C replaces with a file, the untracked one was
accepted unread and ``read-tree --reset`` deleted it. A working file is a classified path
only when it is that path's file (its exact name, or the same physical file); any other
file is unexplained, named in the refusal, and kept.

R5-F2: a rename that changes Unicode normalization (``Café.py`` to a decomposed
``café.py``) gave both names one P/C blob pair although they are two files, so the absent
new name matched no blob and every sync refused. Each name is its own file and is checked
against its own P and C blobs.

R5-F3: ``_pre_hook_check`` compared Git-quoted ``--name-only`` lines with the raw packet
paths, so a land that adds a non-ASCII file refused ``unlisted_staged`` under Git's
default ``core.quotepath``. The index reconciliation of ``run_parameters.py`` read quoted
``ls-files`` / ``ls-tree`` lines the same way. Both read NUL-separated raw names.

The rigs are the disposable lane rigs of ``test_lanes_recovery.py`` (a real ``phase_b3``
repository in ``tmp_path``). Do not skip, only, or early-return (G36).
"""

from __future__ import annotations

import os
import unicodedata
from pathlib import Path

import pytest

from tools import run_parameters as rp
from tools.tests import lane_worktree_config as lwc
from tools.tests import test_lanes_recovery as lrx
from tools.tests.run_parameters_fixtures import phase_b3 as b3

AT_P = b"VALUE = 0\n"
EDITED = b"VALUE = 1\n"
FOREIGN = b"VALUE = 2  # an edit of nobody's lane\n"
HUMAN = b"UNTRACKED HUMAN WORK MUST SURVIVE\n"
SHAPE_AT_C = b"C tracked file\n"
EDITS = {"edited": EDITED, "unchanged": AT_P}
NFC_CAFE = unicodedata.normalize("NFC", "Café.py")
NFD_CAFE = unicodedata.normalize("NFD", "café.py")
#: (tracked name at P, distinct untracked name that folds to the same key).
FOLDED = {
    "sharp-s": ("strasse.py", "straße.py"),
    "nfc-nfd": (NFC_CAFE, unicodedata.normalize("NFD", NFC_CAFE)),
}


def _lane_rig(tmp_path: Path, seed: dict[str, bytes], quotepath: bool) -> lrx.LaneRig:
    """The lane rig with ``seed`` (paths below ``src/<plan>/``) tracked at P.

    ``core.quotepath`` is set explicitly: true is Git's default (R5-F3); false keeps the
    R5-F1 / R5-F2 cases independent of the R5-F3 listing.
    """
    rig = b3.rig(tmp_path / "fx", lrx.ROOT, seed=lwc.SEED)
    rig.bind()
    lrx.git(rig.repo, "config", "core.quotepath", "true" if quotepath else "false")
    lrx.seed_plan(
        rig,
        rig.plan,
        {
            lrx.METRICS: lrx.METRICS_HEAD.encode(),
            **{f"src/{rig.plan}/{rel}": data for rel, data in seed.items()},
        },
    )
    return lrx.open_lane(rig, tmp_path, rig.plan, lrx.CARD_SESSION)


def _commit_lane(lr: lrx.LaneRig, message: str) -> None:
    """Commit every lane change as L0; the main checkout stays clean at P."""
    lrx.git(lr.wt, "add", "-A")
    lrx.git(lr.wt, "commit", "-q", "-m", message)
    lr.l0 = lrx.git(lr.wt, "rev-parse", "HEAD")
    assert lrx.git(lr.repo, "status", "--porcelain", "-uall") == "", "main not clean"


def _src(lr: lrx.LaneRig) -> Path:
    return lr.repo / "src" / lr.plan


def _names(folder: Path) -> list[str]:
    """The exact names on disk in ``folder``."""
    return sorted(os.listdir(folder))


# ---------------------------------------------------------------------------
# R5-F1: a distinct file whose name folds to a classified path's key
# ---------------------------------------------------------------------------


def _folder_to_file_rig(tmp_path: Path, tracked: str) -> lrx.LaneRig:
    """``shape/<tracked>`` at P; the lane replaces the folder ``shape`` with a file."""
    lr = _lane_rig(tmp_path, {f"shape/{tracked}": AT_P}, quotepath=False)
    lrx.git(lr.wt, "rm", "-q", "-r", "--", f"src/{lr.plan}/shape")
    (lr.wt / "src" / lr.plan / "shape").write_bytes(SHAPE_AT_C)
    _commit_lane(lr, "lane: folder to file")
    return lr


@pytest.mark.parametrize("index", ["index-at-p", "index-at-c"])
@pytest.mark.parametrize("pair", sorted(FOLDED))
def test_r5_f1_a_distinct_folded_name_under_a_replaced_folder_is_kept(
    tmp_path: Path, pair: str, index: str
) -> None:
    """R5-F1, AC-785.21 / AC-785.23: after a crash at ``land:sync:started``, an untracked
    file whose name folds to the tracked file's key is nobody's tracked content. Recovery
    refuses and names it, with the index still at P or already at C; the file keeps its
    name and bytes. Once the human moves it away, recovery closes the land."""
    tracked, foreign = FOLDED[pair]
    lr = _folder_to_file_rig(tmp_path, tracked)
    lrx.ready(lr)
    lrx.crashed(lrx.publish(lr, env={lrx.CRASH: "land:sync:started"}))
    c = lrx.main_ref(lr)
    assert c != lr.p
    shape = _src(lr) / "shape"
    (shape / foreign).write_bytes(HUMAN)
    assert not os.path.samefile(shape / tracked, shape / foreign)
    if index == "index-at-c":
        lrx.git(lr.repo, "read-tree", c)
    for _ in range(2):
        lrx.refused(lrx.recover(lr), f"sync_unexplained:src/{lr.plan}/shape/{foreign}")
    assert _names(shape) == sorted([tracked, foreign])
    assert (shape / foreign).read_bytes() == HUMAN
    assert (shape / tracked).read_bytes() == AT_P
    assert ("land:closed", "done") not in lrx.phases(lr)
    (shape / foreign).replace(tmp_path / "moved-aside.py")
    lrx.ok(lrx.recover(lr))
    lrx.assert_closed(lr)
    lrx.assert_main_tree_at(lr, c)
    assert (_src(lr) / "shape").read_bytes() == SHAPE_AT_C
    assert (tmp_path / "moved-aside.py").read_bytes() == HUMAN


@pytest.mark.parametrize("index", ["index-at-p", "index-at-c"])
def test_r5_f1_a_case_only_spelling_of_the_replaced_folder_still_closes(
    tmp_path: Path, index: str
) -> None:
    """R5-F1 control (R4-F1 kept), AC-785.23: P has ``Shape/a.py``; C replaces it with a
    file ``shape``. Where the filesystem folds case, ``shape/a.py`` is the same physical
    file as the tracked ``Shape/a.py``, so the folder counts as absent and recovery
    closes; where it does not, the names are the ordinary folder-to-file change."""
    lr = _lane_rig(tmp_path, {"Shape/a.py": AT_P}, quotepath=False)
    lrx.git(lr.wt, "rm", "-q", "-r", "--", f"src/{lr.plan}/Shape")
    (lr.wt / "src" / lr.plan / "shape").write_bytes(SHAPE_AT_C)
    _commit_lane(lr, "lane: case-changing folder to file")
    lrx.ready(lr)
    lrx.crashed(lrx.publish(lr, env={lrx.CRASH: "land:sync:started"}))
    c = lrx.main_ref(lr)
    if index == "index-at-c":
        lrx.git(lr.repo, "read-tree", c)
    lrx.ok(lrx.recover(lr))
    lrx.assert_closed(lr)
    lrx.assert_main_tree_at(lr, c)
    assert _names(_src(lr)) == ["lane.py", "shape"]
    assert (_src(lr) / "shape").read_bytes() == SHAPE_AT_C


# ---------------------------------------------------------------------------
# R5-F2: a rename that changes Unicode normalization
# ---------------------------------------------------------------------------


def _normalization_rig(tmp_path: Path, at_c: bytes, quotepath: bool) -> lrx.LaneRig:
    """A composed ``Café.py`` at P; the lane renames it to a decomposed lowercase
    ``café.py`` with ``at_c`` as its bytes at C."""
    lr = _lane_rig(tmp_path, {NFC_CAFE: AT_P}, quotepath=quotepath)
    lrx.git(
        lr.wt, "mv", "--force", f"src/{lr.plan}/{NFC_CAFE}", f"src/{lr.plan}/{NFD_CAFE}"
    )
    (lr.wt / "src" / lr.plan / NFD_CAFE).write_bytes(at_c)
    _commit_lane(lr, "lane: rename that changes normalization")
    return lr


def _assert_renamed(lr: lrx.LaneRig, c: str, at_c: bytes) -> None:
    """The land is closed and the main checkout holds the decomposed name exactly as at C."""
    lrx.assert_closed(lr)
    lrx.assert_main_tree_at(lr, c)
    assert _names(_src(lr)) == sorted(["lane.py", NFD_CAFE])
    assert (_src(lr) / NFD_CAFE).read_bytes() == at_c
    assert ("land:sync", "refused:sync_unexplained") not in lrx.phases(lr)


@pytest.mark.parametrize("edit", sorted(EDITS))
def test_r5_f2_a_clean_land_with_a_normalization_rename_closes(
    tmp_path: Path, edit: str
) -> None:
    """R5-F2, AC-785.21: publish of a clean lane that renames ``Café.py`` to a decomposed
    ``café.py``, with or without an edit, syncs the main checkout to C and closes."""
    lr = _normalization_rig(tmp_path, EDITS[edit], quotepath=False)
    lrx.ready(lr)
    lrx.ok(lrx.publish(lr))
    c = lrx.main_ref(lr)
    assert c != lr.p
    _assert_renamed(lr, c, EDITS[edit])


@pytest.mark.parametrize("state", ["index-and-work-at-p", "work-at-c"])
def test_r5_f2_an_interrupted_sync_with_a_normalization_rename_recovers(
    tmp_path: Path, state: str
) -> None:
    """R5-F2, AC-785.23 row "Step 8 partly done": a crash at ``land:sync:started``, with
    the renamed and edited file still at P or already at C (index at P), recovers and
    closes; a second recovery changes nothing."""
    lr = _normalization_rig(tmp_path, EDITED, quotepath=False)
    lrx.ready(lr)
    lrx.crashed(lrx.publish(lr, env={lrx.CRASH: "land:sync:started"}))
    c = lrx.main_ref(lr)
    assert c != lr.p
    if state == "work-at-c":
        (_src(lr) / NFC_CAFE).unlink()
        (_src(lr) / NFD_CAFE).write_bytes(EDITED)
    lrx.ok(lrx.recover(lr))
    assert lrx.main_ref(lr) == c
    _assert_renamed(lr, c, EDITED)
    lrx.ok(lrx.recover(lr))
    _assert_renamed(lr, c, EDITED)


def test_r5_f2_a_foreign_edit_of_the_old_name_still_stops_the_sync(
    tmp_path: Path,
) -> None:
    """R5-F2, AC-785.21 (R1-F1 kept): bytes at neither P nor C in the old name are
    nobody's tracked content; recovery refuses and names it, and the file keeps its name
    and bytes."""
    lr = _normalization_rig(tmp_path, EDITED, quotepath=False)
    lrx.ready(lr)
    lrx.crashed(lrx.publish(lr, env={lrx.CRASH: "land:sync:started"}))
    (_src(lr) / NFC_CAFE).write_bytes(FOREIGN)
    for _ in range(2):
        lrx.refused(lrx.recover(lr), f"sync_unexplained:src/{lr.plan}/{NFC_CAFE}")
    assert _names(_src(lr)) == [NFC_CAFE]
    assert (_src(lr) / NFC_CAFE).read_bytes() == FOREIGN
    assert ("land:closed", "done") not in lrx.phases(lr)


# ---------------------------------------------------------------------------
# R5-F3: non-ASCII paths under Git's default core.quotepath
# ---------------------------------------------------------------------------


def test_r5_f3_a_land_that_adds_a_non_ascii_file_closes_under_default_quoting(
    tmp_path: Path,
) -> None:
    """R5-F3, AC-785.19 / AC-785.33: with ``core.quotepath`` true, a lane that adds
    ``café.py`` publishes T and closes; the main checkout holds the file's bytes."""
    lr = _lane_rig(tmp_path, {}, quotepath=True)
    name = unicodedata.normalize("NFC", "café.py")
    (lr.wt / "src" / lr.plan / name).write_bytes(EDITED)
    _commit_lane(lr, "lane: a non-ASCII file")
    tree = lrx.ready(lr)
    lrx.ok(lrx.publish(lr))
    c = lrx.main_ref(lr)
    assert c != lr.p
    assert lrx.git(lr.repo, "rev-parse", f"{c}^{{tree}}") == tree
    lrx.assert_closed(lr)
    lrx.assert_main_tree_at(lr, c)
    assert (_src(lr) / name).read_bytes() == EDITED


def test_r5_f3_a_normalization_rename_closes_under_default_quoting(
    tmp_path: Path,
) -> None:
    """R5-F3 with R5-F2, AC-785.19 / AC-785.21: the normalization rename of the R5-F2
    cases also lands and closes with ``core.quotepath`` true."""
    lr = _normalization_rig(tmp_path, EDITED, quotepath=True)
    lrx.ready(lr)
    lrx.ok(lrx.publish(lr))
    _assert_renamed(lr, lrx.main_ref(lr), EDITED)


def test_r5_f3_index_reconciliation_reads_non_ascii_entries_under_default_quoting(
    tmp_path: Path,
) -> None:
    """R5-F3 sibling, AC-785.33 (D:226): ``run_parameters._index_entry`` and
    ``_tree_entry`` find ``café.py``'s stage-0 entry and its blob in a commit with
    ``core.quotepath`` true, as they do for an ASCII name."""
    repo = tmp_path / "repo"
    repo.mkdir()
    lrx.git(repo, "init", "-q")
    lrx.git(repo, "config", "core.quotepath", "true")
    lrx.git(repo, "config", "user.name", "R5 Fixture")
    lrx.git(repo, "config", "user.email", "r5@fixture.invalid")
    name = unicodedata.normalize("NFC", "café.py")
    for rel in (name, "plain.py"):
        (repo / rel).write_bytes(EDITED)
    lrx.git(repo, "add", "-A")
    lrx.git(repo, "commit", "-q", "-m", "fixture")
    commit = lrx.git(repo, "rev-parse", "HEAD")
    blob = lrx.git(repo, "rev-parse", f"HEAD:{name}")
    for rel in (name, "plain.py"):
        assert rp._index_entry(repo, rel) == ("100644", blob), rel
        assert rp._tree_entry(repo, commit, rel) == ("100644", blob), rel
    assert rp._index_entry(repo, "absent.py") is None
    assert rp._tree_entry(repo, commit, "absent.py") is None
