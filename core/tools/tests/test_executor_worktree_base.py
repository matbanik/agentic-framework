"""S5 executor worktree at an admitted base — red first (G19).

Plan: ``docs/execution/plans/2026-10-15-scheduled-credits-runs`` (Component G,
AC-G.2, AC-G.3 and AC-G.6; report R§5.4; acceptance matrix MX-38 and MX-44).

A chained exec run starts at the base commit B that admission resolved and
recorded. These tests fix the helper side of that contract:

* ``create <slug> --base <rev>`` checks out B; without ``--base`` the helper
  reads ``CREDITS_BASE_COMMIT``; without either it checks out ``HEAD`` as
  before (AC-G.6). ``--base`` wins over the environment.
* A base that does not resolve to a commit prints ``worktree_bad:base_unknown``,
  exits 1 and creates nothing: no directory, no worktree record, no ref.
* ``sync`` prints ``worktree_bad:base_bound`` and writes nothing while
  ``CREDITS_BASE_COMMIT`` is set: a run bound to B never pulls main-tree
  content into its tree.
* The worktree manifest keeps its fields (``test_executor_worktree.py``
  MANIFEST_FIELDS does not change).

Every test builds a real temp git repository; the helper's ``main()`` runs
in-process and only the venv step is replaced (it writes ``.venv/pyvenv.cfg``).
The rig is copied from ``test_executor_worktree.py`` (rigs are copied, never
imported); its ``call`` also turns an argparse ``SystemExit`` into an exit code.
Do not skip, only, or early-return (G36).
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

MARK = "CREDITS_WORKTREE_BASE"
ENV_BASE = "CREDITS_BASE_COMMIT"

REF_PREFIX = "refs/executor-worktrees/"
MANIFEST_NAME = "executor-worktree.json"
MANIFEST_FIELDS = {
    "source_root",
    "slug",
    "branch",
    "links",
    "copies",
    "carry",
    "created",
}

STATUS = ".agent/context/meu-status.yaml"
PLAN_DIR = "docs/execution/plans/2026-10-16-x"
PLAN = f"{PLAN_DIR}/implementation-plan.md"
GUIDE = "docs/guide.md"
KEEP = "docs/keep.md"

GUIDE_V1 = b"# Guide v1\n"
GUIDE_V2 = b"# Guide v2\n"
KEEP_V1 = b"keep v1\n"
KEEP_MAIN = b"keep edited in the main tree\n"
STATUS_V1 = b"MEU-1: approved\n"
STATUS_DIRTY = b"MEU-1: approved\nMEU-2: pending\n"
STATUS_SUCCESSOR = b"MEU-1: approved\nMEU-2: done\n"

# The adopter config the tool reads from the main tree; the rig stubs
# ``_build_venv``.
CONFIG = ".agent/credits/worktree.json"
SEED_TRACKED: dict[str, bytes] = {
    ".gitignore": b".venv/\n.env\n",
    CONFIG: (
        b'{"env_files": [".env"], "frozen_dirs": [], '
        b'"venv_build": ["uv", "sync"], "linked_trees": [], "junction_files": []}\n'
    ),
    STATUS: STATUS_V1,
    GUIDE: GUIDE_V1,
    KEEP: KEEP_V1,
}

_GIT_ENV_DROPPED = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")


def _find_tool() -> Any:
    try:
        return importlib.import_module("tools.executor_worktree")
    except ImportError:
        return None


def _tool(marker: str) -> Any:
    module = _find_tool()
    if module is None:
        pytest.fail(
            f"{marker}: tools/executor_worktree.py does not exist", pytrace=False
        )
    return module


def _git_proc(
    repo: Path, *args: str, data: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    merged = {k: v for k, v in os.environ.items() if k not in _GIT_ENV_DROPPED}
    argv = [
        "git",
        "-c",
        "user.name=s5",
        "-c",
        "user.email=s5@example.invalid",
        "-c",
        "commit.gpgsign=false",
        *args,
    ]
    return subprocess.run(
        argv,
        cwd=repo,
        input=data,
        stdin=None if data is not None else subprocess.DEVNULL,
        capture_output=True,
        env=merged,
        check=False,
    )


def _git(repo: Path, *args: str, data: bytes | None = None) -> str:
    proc = _git_proc(repo, *args, data=data)
    assert proc.returncode == 0, (
        f"rig: git {' '.join(args)} exited {proc.returncode}: "
        f"{proc.stderr.decode('utf-8', 'replace')}"
    )
    return proc.stdout.decode("utf-8", "replace")


def _write(root: Path, files: dict[str, bytes]) -> None:
    for rel, data in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def _build_source(tmp_path: Path) -> Path:
    """A small LF source repository with one untracked plan folder."""
    src = tmp_path / "repo"
    src.mkdir()
    _git(src, "init", "-q", "-b", "main")
    _git(src, "config", "core.autocrlf", "false")
    _write(src, SEED_TRACKED)
    _git(src, "add", "-A")
    _git(src, "commit", "-q", "--no-verify", "-m", "seed")
    _write(src, {PLAN: b"# Plan\n\nApproved.\n"})
    return src


def _head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").strip()


def _commit_guide(src: Path) -> str:
    """Move ``HEAD`` past the admitted base; return the new commit."""
    _write(src, {GUIDE: GUIDE_V2})
    _git(src, "add", "--", GUIDE)
    _git(src, "commit", "-q", "--no-verify", "-m", "after admission")
    return _head(src)


def _ref(src: Path, slug: str) -> str | None:
    proc = _git_proc(src, "rev-parse", "--verify", "-q", f"{REF_PREFIX}{slug}")
    assert proc.returncode in (0, 1), f"rig: rev-parse exited {proc.returncode}"
    return proc.stdout.decode("utf-8").strip() or None


def _listed(src: Path, path: Path) -> bool:
    listing = _git(src, "worktree", "list", "--porcelain")
    paths = {
        os.path.normcase(os.path.abspath(line[len("worktree ") :]))
        for line in listing.splitlines()
        if line.startswith("worktree ")
    }
    return os.path.normcase(os.path.abspath(path)) in paths


def _git_dir(wt: Path) -> Path:
    return Path(_git(wt, "rev-parse", "--absolute-git-dir").strip())


@dataclass
class Rig:
    """One source repository, the tool under test and its captured stdout."""

    tool: Any
    src: Path
    capsys: pytest.CaptureFixture[str]
    venvs: list[Path] = field(default_factory=list)

    def call(self, *argv: object) -> tuple[int, list[str]]:
        self.capsys.readouterr()
        try:
            code = self.tool.main(["--root", str(self.src), *[str(a) for a in argv]])
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 2
        return code, self.capsys.readouterr().out.splitlines()

    @property
    def parent(self) -> Path:
        """The configured worktree parent (B-8, AC-G.1)."""
        return Path(self.tool.WORKTREE_PARENT)

    def path(self, slug: str) -> Path:
        return self.parent / slug

    def create(self, marker: str, slug: str, *extra: str) -> Path:
        code, lines = self.call("create", slug, *extra)
        wt = self.path(slug)
        assert code == 0 and lines[-1:] == [f"worktree_ready:{wt.as_posix()}"], (
            f"{marker}: create {slug} exited {code} with {lines}"
        )
        return wt

    def assert_nothing_created(self, marker: str, slug: str) -> None:
        wt = self.path(slug)
        assert not os.path.lexists(wt), f"{marker}: {wt} exists"
        assert not _listed(self.src, wt), f"{marker}: {wt} is a worktree"
        assert _ref(self.src, slug) is None, f"{marker}: the {slug} ref exists"


@pytest.fixture(autouse=True)
def _worktree_parent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """B-8 (AC-G.1): every worktree this file makes goes under a temp ``WORKTREE_PARENT``."""
    tool = importlib.import_module("tools.executor_worktree")
    monkeypatch.setattr(tool, "WORKTREE_PARENT", tmp_path / "wt", raising=False)


def _rig(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    marker: str,
) -> Rig:
    tool = _tool(marker)
    monkeypatch.delenv(ENV_BASE, raising=False)
    rig = Rig(tool=tool, src=_build_source(tmp_path), capsys=capsys)

    def fake_venv(path: Path) -> int:
        rig.venvs.append(Path(path))
        _write(Path(path), {".venv/pyvenv.cfg": b"home = stub\n"})
        return 0

    monkeypatch.setattr(tool, "_build_venv", fake_venv)
    return rig


def test_mx_38_create_base_checks_out_b_after_head_moved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-G.2, AC-G.3 (MX-38) — HEAD moving after admission leaves the worktree at B."""
    rig = _rig(tmp_path, monkeypatch, capsys, MARK)
    src = rig.src
    base = _head(src)
    moved = _commit_guide(src)
    assert moved != base

    wt = rig.create(MARK, "at-base", "--base", base)
    assert _head(wt) == base
    assert (wt / GUIDE).read_bytes() == GUIDE_V1
    assert (src / GUIDE).read_bytes() == GUIDE_V2
    assert _ref(src, "at-base") == _git(src, "rev-parse", f"{base}^{{tree}}").strip()
    assert _git(wt, "status", "--porcelain").strip() == ""

    branched = rig.create(
        MARK, "at-branch", "--branch", "lane/at-branch", "--base", base
    )
    assert _head(branched) == base
    assert _git(src, "rev-parse", "lane/at-branch").strip() == base


def test_mx_38_create_reads_the_base_from_the_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-G.3 (MX-38) — CREDITS_BASE_COMMIT is the base when --base is absent."""
    rig = _rig(tmp_path, monkeypatch, capsys, MARK)
    src = rig.src
    base = _head(src)
    moved = _commit_guide(src)

    monkeypatch.setenv(ENV_BASE, base)
    wt = rig.create(MARK, "from-env")
    assert _head(wt) == base
    assert (wt / GUIDE).read_bytes() == GUIDE_V1

    flagged = rig.create(MARK, "flag-wins", "--base", moved)
    assert _head(flagged) == moved
    assert (flagged / GUIDE).read_bytes() == GUIDE_V2


def test_mx_38_an_unknown_base_creates_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-G.3 (MX-38, boundary) — an unresolvable base is worktree_bad:base_unknown."""
    rig = _rig(tmp_path, monkeypatch, capsys, MARK)
    src = rig.src
    blob = _git(src, "rev-parse", f"HEAD:{GUIDE}").strip()

    code, lines = rig.call("create", "no-such-commit", "--base", "0" * 40)
    assert (code, lines) == (1, ["worktree_bad:base_unknown"])
    rig.assert_nothing_created(MARK, "no-such-commit")

    code, lines = rig.call("create", "no-such-name", "--base", "no-such-branch")
    assert (code, lines) == (1, ["worktree_bad:base_unknown"])
    rig.assert_nothing_created(MARK, "no-such-name")

    code, lines = rig.call("create", "a-blob", "--base", blob)
    assert (code, lines) == (1, ["worktree_bad:base_unknown"])
    rig.assert_nothing_created(MARK, "a-blob")

    monkeypatch.setenv(ENV_BASE, "f" * 40)
    code, lines = rig.call("create", "bad-env")
    assert (code, lines) == (1, ["worktree_bad:base_unknown"])
    rig.assert_nothing_created(MARK, "bad-env")


def test_mx_38_sync_is_refused_while_the_run_is_bound_to_b(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-G.3 (MX-38) — sync prints worktree_bad:base_bound and writes nothing."""
    rig = _rig(tmp_path, monkeypatch, capsys, MARK)
    src = rig.src
    base = _head(src)
    wt = rig.create(MARK, "bound", "--base", base)
    baseline = _ref(src, "bound")
    _write(src, {KEEP: KEEP_MAIN})

    monkeypatch.setenv(ENV_BASE, base)
    code, lines = rig.call("sync", wt, KEEP)
    assert (code, lines) == (1, ["worktree_bad:base_bound"])
    assert (wt / KEEP).read_bytes() == KEEP_V1
    assert _ref(src, "bound") == baseline

    monkeypatch.delenv(ENV_BASE)
    code, lines = rig.call("sync", wt, KEEP)
    assert (code, lines) == (0, [f"sync_ok:{KEEP}"])
    assert (wt / KEEP).read_bytes() == KEEP_MAIN


def test_mx_44_a_dirty_permitted_input_edited_by_the_successor_lands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-G.3 (MX-44) — a carried dirty input lands with the successor's blob only."""
    rig = _rig(tmp_path, monkeypatch, capsys, MARK)
    src = rig.src
    base = _head(src)
    _commit_guide(src)
    _write(src, {STATUS: STATUS_DIRTY})

    wt = rig.create(
        MARK, "carry", "--base", base, "--carry", STATUS, "--carry", PLAN_DIR
    )
    assert _head(wt) == base
    assert (wt / STATUS).read_bytes() == STATUS_DIRTY
    assert (wt / GUIDE).read_bytes() == GUIDE_V1

    _write(wt, {STATUS: STATUS_SUCCESSOR})
    code, lines = rig.call("land", wt)
    assert (code, lines) == (0, ["land_ok:0:1:0"])
    assert (src / STATUS).read_bytes() == STATUS_SUCCESSOR
    assert (src / GUIDE).read_bytes() == GUIDE_V2


def test_ac_g_6_create_without_a_base_checks_out_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-G.6 — no --base and no CREDITS_BASE_COMMIT: HEAD, as before."""
    rig = _rig(tmp_path, monkeypatch, capsys, MARK)
    src = rig.src
    moved = _commit_guide(src)

    wt = rig.create(MARK, "at-head", "--carry", PLAN_DIR)
    assert _head(wt) == moved
    assert (wt / GUIDE).read_bytes() == GUIDE_V2
    manifest = json.loads((_git_dir(wt) / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert set(manifest) == MANIFEST_FIELDS
    assert manifest["carry"] == [PLAN]
