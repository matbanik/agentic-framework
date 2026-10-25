"""MEU-785 corrections of EA-120 before execution review round 6 (EA-121) — red first (G19).

FIC: ``docs/execution/plans/2026-10-22-lane-branches-governed-land/implementation-plan.md``
AC-785.21 / AC-785.23 (design §5.5 step 8, D:251 and D:258-266); the findings are those
of an advisory peer read of EA-120, recorded in the plan as EA-121.

PF-1: Python 3.12 ``is_symlink`` is False for an NTFS junction, so the step-8 walk went
through a junction under a folder that C replaces. A file reached through it has the
physical identity of its target; when the target is a classified path, the file counted as
explained, and ``read-tree --reset`` deleted the target through the junction. A directory
link (a symlink or a junction) is never walked: it is unexplained itself, named in the
refusal, and kept with its target.

PF-2: ``os.walk`` skips a folder that it cannot list, so an unreadable subtree counted as
empty and the sync could delete it. A folder that the walk cannot list is unexplained.

PF-3: ``hash-object --stdin-paths`` hashed the target of a symlink (and failed on a
dangling one), and it C-unquotes a line that starts with a double quote. A symlink is
hashed from its link text, as Git stores it; a name that the stdin form would change is
hashed from the command line.

The controls cover the EA-120 identity rules that no earlier test reached: an ancestor that
is the same physical file as a classified path, a file with two links, a filesystem without
a file index, and a nested non-ASCII path in the ``run_parameters`` readers.

The rigs are the disposable lane rigs of ``test_lanes_recovery.py`` (a real ``phase_b3``
repository in ``tmp_path``) and plain temporary repositories. Do not skip, only, or
early-return (G36).
"""

from __future__ import annotations

import os
import stat
import sys
import unicodedata
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from tools import commit_batch as cb
from tools import run_parameters as rp
from tools.tests import lane_worktree_config as lwc
from tools.tests import test_lanes_recovery as lrx
from tools.tests.run_parameters_fixtures import phase_b3 as b3

AT_P = b"VALUE = 0\n"
EDITED = b"VALUE = 1\n"
HUMAN = b"UNTRACKED HUMAN WORK MUST SURVIVE\n"
SHAPE_AT_C = b"C tracked file\n"
#: Names that ``hash-object --stdin-paths`` would read as another name (PF-3).
CHANGED_BY_STDIN = ['"quoted".py', "carriage\r.py", "new\nline.py"]


def _make_dir_link(link: Path, target: Path) -> None:
    """A directory link without privileges: a junction on Windows, a symlink elsewhere."""
    target.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


def _is_dir_link(path: Path) -> bool:
    return os.path.islink(path) or os.path.isjunction(path)


def _remove_dir_link(link: Path) -> None:
    """Remove the link only; its target and the target's files stay."""
    if os.path.isjunction(link):
        os.rmdir(link)
    else:
        os.unlink(link)


def _repo(top: Path) -> rp.Repo:
    """A plain temporary repository (``core.autocrlf`` false) as a ``run_parameters`` Repo."""
    top.mkdir(parents=True)
    lrx.git(top, "init", "-q")
    for key, value in (
        ("core.autocrlf", "false"),
        ("user.name", "R5b Fixture"),
        ("user.email", "r5b@fixture.invalid"),
    ):
        lrx.git(top, "config", key, value)
    return rp.Repo(
        top=top, display=str(top), common=top / ".git", main=top, main_display=str(top)
    )


def _commit(top: Path, message: str) -> str:
    lrx.git(top, "add", "-A")
    lrx.git(top, "commit", "-q", "-m", message)
    return lrx.git(top, "rev-parse", "HEAD")


def _ids(top: Path, explained: frozenset[str]) -> dict[cb.FileId, list[str]]:
    return cb._work_ids(top, sorted(explained))


# ---------------------------------------------------------------------------
# PF-1: a directory link under a folder that C replaces
# ---------------------------------------------------------------------------


def _linked_folder_rig(tmp_path: Path) -> lrx.LaneRig:
    """``shape/a.py`` and ``lib/x.py`` at P; the lane replaces the folder ``shape`` with a
    file and edits ``lib/x.py``."""
    rig = b3.rig(tmp_path / "fx", lrx.ROOT, seed=lwc.SEED)
    rig.bind()
    lrx.git(rig.repo, "config", "core.quotepath", "false")
    src = f"src/{rig.plan}"
    lrx.seed_plan(
        rig,
        rig.plan,
        {
            lrx.METRICS: lrx.METRICS_HEAD.encode(),
            f"{src}/shape/a.py": AT_P,
            f"{src}/lib/x.py": AT_P,
        },
    )
    lr = lrx.open_lane(rig, tmp_path, rig.plan, lrx.CARD_SESSION)
    lrx.git(lr.wt, "rm", "-q", "-r", "--", f"{src}/shape")
    (lr.wt / src / "shape").write_bytes(SHAPE_AT_C)
    (lr.wt / src / "lib" / "x.py").write_bytes(EDITED)
    lrx.git(lr.wt, "add", "-A")
    lrx.git(lr.wt, "commit", "-q", "-m", "lane: folder to file and an edit")
    lr.l0 = lrx.git(lr.wt, "rev-parse", "HEAD")
    assert lrx.git(lr.repo, "status", "--porcelain", "-uall") == "", "main not clean"
    return lr


@pytest.mark.parametrize("index", ["index-at-p", "index-at-c"])
def test_pf1_a_directory_link_under_a_replaced_folder_is_kept(
    tmp_path: Path, index: str
) -> None:
    """PF-1, AC-785.21 / AC-785.23: after a crash at ``land:sync:started``, a directory
    link ``shape/junc`` to the tracked folder ``lib`` is nobody's tracked content.
    Recovery refuses and names the link, with the index still at P or already at C; the
    link and the tracked file behind it are kept. Once the human removes the link,
    recovery closes the land."""
    lr = _linked_folder_rig(tmp_path)
    lrx.ready(lr)
    lrx.crashed(lrx.publish(lr, env={lrx.CRASH: "land:sync:started"}))
    c = lrx.main_ref(lr)
    assert c != lr.p
    src = lr.repo / "src" / lr.plan
    link = src / "shape" / "junc"
    _make_dir_link(link, src / "lib")
    assert _is_dir_link(link)
    if index == "index-at-c":
        lrx.git(lr.repo, "read-tree", c)
    for _ in range(2):
        lrx.refused(lrx.recover(lr), f"sync_unexplained:src/{lr.plan}/shape/junc")
    assert _is_dir_link(link)
    assert (src / "lib" / "x.py").read_bytes() == AT_P
    assert (src / "shape" / "a.py").read_bytes() == AT_P
    assert ("land:closed", "done") not in lrx.phases(lr)
    _remove_dir_link(link)
    assert (src / "lib" / "x.py").read_bytes() == AT_P
    lrx.ok(lrx.recover(lr))
    lrx.assert_closed(lr)
    lrx.assert_main_tree_at(lr, c)
    assert (src / "shape").read_bytes() == SHAPE_AT_C
    assert (src / "lib" / "x.py").read_bytes() == EDITED


def test_pf1_a_directory_link_at_a_replaced_folder_is_unexplained(
    tmp_path: Path,
) -> None:
    """PF-1, AC-785.21: a link that stands where the folder ``shape`` was, to a folder of
    classified files, is the stray itself; the walk never reads the files behind it."""
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "a.py").write_bytes(AT_P)
    _make_dir_link(tmp_path / "shape", tmp_path / "lib")
    explained = frozenset({"shape", "shape/a.py", "lib/a.py"})
    ids = _ids(tmp_path, explained)
    assert cb._stray_below(tmp_path, "shape", explained, ids) == "shape"
    assert _is_dir_link(tmp_path / "shape")
    assert (tmp_path / "lib" / "a.py").read_bytes() == AT_P


# ---------------------------------------------------------------------------
# PF-2: a folder that the walk cannot list
# ---------------------------------------------------------------------------


def _deny_listing(
    monkeypatch: pytest.MonkeyPatch, folder: Path
) -> Callable[[], list[str]]:
    """Make ``os.scandir`` fail for ``folder`` only; return the denied calls seen."""
    real = os.scandir
    denied: list[str] = []
    key = os.path.normcase(os.path.abspath(folder))

    def scandir(path: str) -> Iterator[os.DirEntry[str]]:
        if os.path.normcase(os.path.abspath(path)) == key:
            denied.append(path)
            raise PermissionError(13, "listing denied by the test", path)
        return real(path)

    monkeypatch.setattr(os, "scandir", scandir)
    return lambda: denied


def _deep_folder(top: Path) -> frozenset[str]:
    """``shape/a.py`` and ``shape/deep/b.py`` (classified) and an untracked human file."""
    (top / "shape" / "deep").mkdir(parents=True)
    (top / "shape" / "a.py").write_bytes(AT_P)
    (top / "shape" / "deep" / "b.py").write_bytes(AT_P)
    (top / "shape" / "deep" / "human.py").write_bytes(HUMAN)
    return frozenset({"shape", "shape/a.py", "shape/deep/b.py"})


@pytest.mark.parametrize(
    ("denied", "stray"), [("shape", "shape"), ("shape/deep", "shape/deep")]
)
def test_pf2_a_folder_the_walk_cannot_list_is_unexplained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, denied: str, stray: str
) -> None:
    """PF-2, AC-785.21: a folder the walk cannot list may hold anything, so it is the
    stray (the replaced folder itself, or a folder below it); it never counts as empty."""
    explained = _deep_folder(tmp_path)
    ids = _ids(tmp_path, explained)
    seen = _deny_listing(monkeypatch, tmp_path / denied)
    assert cb._stray_below(tmp_path, "shape", explained, ids) == stray
    assert seen(), "the denied folder was never listed"


def test_pf2_an_unlistable_folder_stops_the_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PF-2, AC-785.21: P has ``shape/a.py`` and ``shape/deep/b.py``; C replaces ``shape``
    with a file. With ``shape/deep`` unreadable to the walk, the step-8 check names it."""
    top = tmp_path / "repo"
    repo = _repo(top)
    (top / "shape" / "deep").mkdir(parents=True)
    (top / "shape" / "a.py").write_bytes(AT_P)
    (top / "shape" / "deep" / "b.py").write_bytes(AT_P)
    parent = _commit(top, "P")
    lrx.git(top, "rm", "-q", "-r", "--", "shape")
    (top / "shape").write_bytes(SHAPE_AT_C)
    commit = _commit(top, "C")
    lrx.git(top, "checkout", "-q", "--detach", parent)
    (top / "shape" / "deep" / "human.py").write_bytes(HUMAN)
    paths = sorted(
        lrx.git(
            top, "diff-tree", "-r", "--name-only", "--no-renames", parent, commit
        ).splitlines()
    )
    assert paths == ["shape", "shape/a.py", "shape/deep/b.py"]
    seen = _deny_listing(monkeypatch, top / "shape" / "deep")
    assert cb._sync_unexplained(repo, parent, commit, paths) == "shape/deep"
    assert seen(), "the denied folder was never listed"
    assert (top / "shape" / "deep" / "human.py").read_bytes() == HUMAN


# ---------------------------------------------------------------------------
# PF-3: the blob id of a symlink and of a name the stdin form would change
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("target", ["t.txt", "missing.txt"])
def test_pf3_a_tracked_symlink_hashes_as_its_link_text(
    tmp_path: Path, target: str
) -> None:
    """PF-3, AC-785.21: a tracked symlink, live or dangling, gets the blob id of its link
    text, which is the blob Git stores, so an unchanged link matches its P blob."""
    top = tmp_path / "repo"
    _repo(top)
    lrx.git(top, "config", "core.symlinks", "true")
    (top / "t.txt").write_bytes(AT_P)
    os.symlink(target, top / "L")
    _commit(top, "P")
    assert lrx.git(top, "ls-files", "-s", "--", "L").startswith("120000 ")
    paths = ["L", "t.txt"]
    work = cb._work_oids(top, paths, cb._work_ids(top, paths))
    assert work["L"] == lrx.git(top, "rev-parse", "HEAD:L")
    assert work["t.txt"] == lrx.git(top, "rev-parse", "HEAD:t.txt")


@pytest.mark.parametrize("name", CHANGED_BY_STDIN)
def test_pf3_names_the_stdin_form_would_change_are_hashed_from_argv(name: str) -> None:
    """PF-3, AC-785.21: ``hash-object --stdin-paths`` C-unquotes a line that starts with a
    double quote and splits at line ends, so such a name is never sent on stdin."""
    assert cb._stdin_path_ok(name) is False
    assert cb._stdin_path_ok("plain.py") is True
    assert cb._stdin_path_ok(unicodedata.normalize("NFC", "café.py")) is True


def test_pf3_every_file_hashes_as_git_hashes_it_by_name(tmp_path: Path) -> None:
    """PF-3, AC-785.21: each working file gets the blob id that ``git hash-object -- <name>``
    gives it. The names of ``CHANGED_BY_STDIN`` exist only where the filesystem allows
    them (not on Windows)."""
    top = tmp_path / "repo"
    _repo(top)
    names = ["plain.py", unicodedata.normalize("NFC", "café.py")]
    if os.name != "nt":
        names += CHANGED_BY_STDIN
    for index, name in enumerate(names):
        (top / name).write_bytes(b"file %d\n" % index)
    work = cb._work_oids(top, names, cb._work_ids(top, names))
    for name in names:
        assert work[name] == lrx.git(top, "hash-object", "--", name), name


# ---------------------------------------------------------------------------
# Controls: the EA-120 identity rules
# ---------------------------------------------------------------------------


def test_control_an_ancestor_that_is_a_classified_file_is_no_obstruction(
    tmp_path: Path,
) -> None:
    """EA-120 control, AC-785.21: P has a file ``Widget``; C has ``widget/new.py``. Where
    the filesystem folds case, ``widget`` opens the classified file ``Widget`` (one
    physical file), which the sync replaces; it is no obstruction. Any other file at an
    ancestor is one."""
    (tmp_path / "Widget").write_bytes(AT_P)
    (tmp_path / "other").write_bytes(HUMAN)
    explained = frozenset({"Widget", "widget/new.py", "other/new.py"})
    ids = _ids(tmp_path, explained)
    assert cb._obstruction(tmp_path, "widget/new.py", explained, ids) is None
    assert cb._obstruction(tmp_path, "other/new.py", explained, ids) == "other"


def test_control_a_file_with_two_links_has_no_identity(tmp_path: Path) -> None:
    """EA-120 control, AC-785.21: a hard-linked file is two names of one inode; neither
    name stands for the other, so the file has no identity and each name is its own."""
    (tmp_path / "a.py").write_bytes(AT_P)
    os.link(tmp_path / "a.py", tmp_path / "b.py")
    assert cb._file_id(tmp_path / "a.py") is None
    assert cb._file_id(tmp_path / "b.py") is None
    assert cb._work_ids(tmp_path, ["a.py", "b.py"]) == {}
    (tmp_path / "c.py").write_bytes(AT_P)
    assert cb._file_id(tmp_path / "c.py") is not None


@pytest.mark.parametrize(("ino", "expected"), [(0, None), (5, (7, 5))])
def test_control_a_filesystem_without_a_file_index_gives_no_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ino: int,
    expected: tuple[int, int] | None,
) -> None:
    """EA-120 control, AC-785.21: ``st_ino`` 0 means the filesystem gives no file index,
    so the name keeps only its exact spelling; a real index gives ``(st_dev, st_ino)``."""
    (tmp_path / "a.py").write_bytes(AT_P)
    fake = os.stat_result((stat.S_IFREG | 0o644, ino, 7, 1, 0, 0, 10, 0, 0, 0))
    monkeypatch.setattr(os, "stat", lambda *_args, **_kwargs: fake)
    assert cb._file_id(tmp_path / "a.py") == expected


def test_control_index_readers_find_a_nested_non_ascii_path(tmp_path: Path) -> None:
    """EA-120 control, AC-785.33 (D:226): with ``core.quotepath`` true,
    ``run_parameters._index_entry`` and ``_tree_entry`` find ``dir/café.py`` below a
    non-ASCII folder as they find an ASCII name."""
    top = tmp_path / "repo"
    _repo(top)
    lrx.git(top, "config", "core.quotepath", "true")
    name = unicodedata.normalize("NFC", "dossier-é/café.py")
    (top / "dossier-é").mkdir()
    (top / name).write_bytes(EDITED)
    commit = _commit(top, "fixture")
    blob = lrx.git(top, "rev-parse", f"HEAD:{name}")
    assert rp._index_entry(top, name) == ("100644", blob)
    assert rp._tree_entry(top, commit, name) == ("100644", blob)
