"""MEU-785 AC-785.1, .2, .9, .10: executor worktrees on lane branches — red first (G19).

FIC: ``docs/execution/plans/2026-10-22-lane-branches-governed-land/implementation-plan.md``
AC-785.1 (D:170), AC-785.2 (D:274), AC-785.9 (D:217; ``.agent/docs/commands.md:36``)
and AC-785.10 (brief B:215-219, self-hosting).

``create <slug>`` makes ``refs/heads/lane/<slug>`` at the base and checks it out;
the manifest records the branch and the baseline ref stays. ``--branch`` takes only
``lane/<slug>``. ``check`` reports a linked worktree on ``main``. ``remove`` deletes
a landed lane branch and refuses an unlanded one unless ``--discard``. A legacy
worktree (detached HEAD, manifest ``branch`` null or absent) keeps working.

Every test builds a real temp git repository (``core.autocrlf=true``) with the
source rig of ``test_executor_worktree.py`` (copied, not imported). The tool's
``main()`` runs in-process; only the venv step is replaced. Multi-case tests run
their cases in sequence inside one function. Do not skip, only, or early-return
(G36).
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

REF_PREFIX = "refs/executor-worktrees/"
MANIFEST_NAME = "executor-worktree.json"
LANE_PREFIX = "refs/heads/lane/"

OVERLAY = ".agent/model-registry.local.json"
STATUS = ".agent/context/meu-status.yaml"
SETTINGS = ".vscode/settings.json"
PLAN_DIR = "docs/execution/plans/2026-10-01-x"
PLAN = f"{PLAN_DIR}/implementation-plan.md"
TASK = f"{PLAN_DIR}/task.md"
MODULE = "pkg/mod.py"
GUIDE = "docs/Guide.md"
GONE = "docs/gone.md"
KEEP = "docs/keep.md"
IGNORED_LATER = "data/tracked.txt"
NODE_FILE = "node_modules/pkg/index.js"
DIST_FILE = "mcp-server/dist/index.js"
LANE_FILE = "pkg/lane_work.py"
# The adopter config the tool reads from the main tree. ``venv_build`` is never
# run here: the rig stubs ``_build_venv``.
CONFIG = ".agent/credits/worktree.json"
CONFIG_BYTES = (
    b'{"env_files": [".env"], "frozen_dirs": ["mcp-server/dist"], '
    b'"venv_build": ["uv", "sync"], "linked_trees": ["node_modules"], '
    b'"junction_files": []}\n'
)

ENV_BYTES = b"GT6_ENV=placeholder\n"
STATUS_MODIFIED = b"MEU-1: approved\nMEU-2: pending\n"

SEED_TRACKED: dict[str, bytes] = {
    ".gitignore": b"node_modules\n.venv/\n.env\nmcp-server/dist/\n.vscode/\n",
    OVERLAY: b'{\n  "overlay": "pinned"\n}\n',
    STATUS: b"MEU-1: approved\n",
    SETTINGS: b'{\n  "editor.tabSize": 4\n}\n',
    GUIDE: b"# Guide\n",
    GONE: b"the executor deletes this file\n",
    KEEP: b"nobody in the worktree edits this file\n",
    IGNORED_LATER: b"tracked; a later ignore rule matches it\n",
    MODULE: b"A = 1\r\nB = 2\r\n",
    CONFIG: CONFIG_BYTES,
}
SEED_LOCAL: dict[str, bytes] = {
    ".env": ENV_BYTES,
    NODE_FILE: b"module.exports = 1;\n",
    DIST_FILE: b"console.log(1);\n",
    PLAN: b"# Plan\r\n\r\nApproved.\r\n",
    TASK: b"| 1 | row | `[ ]` |\n",
}

_GIT_ENV_DROPPED = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")


def _git_proc(
    repo: Path,
    *args: str,
    data: bytes | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    merged = {k: v for k, v in os.environ.items() if k not in _GIT_ENV_DROPPED}
    merged.update(env or {})
    argv = [
        "git",
        "-c",
        "user.name=gt6",
        "-c",
        "user.email=gt6@example.invalid",
        "-c",
        "commit.gpgsign=false",
        *args,
    ]
    return subprocess.run(
        argv,
        cwd=repo,
        input=data,
        stdin=subprocess.DEVNULL if data is None else None,
        capture_output=True,
        env=merged,
        check=False,
    )


def _git(repo: Path, *args: str) -> str:
    proc = _git_proc(repo, *args)
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
    """The source repository at the planning-to-execution transition."""
    src = tmp_path / "repo"
    src.mkdir()
    _git(src, "init", "-q", "-b", "main")
    _git(src, "config", "core.autocrlf", "true")
    _write(src, SEED_TRACKED)
    _git(src, "add", "-A")
    _git(src, "add", "-f", SETTINGS)
    _git(src, "commit", "-q", "--no-verify", "-m", "seed")
    _write(src, SEED_LOCAL)
    (src / STATUS).write_bytes(STATUS_MODIFIED)
    return src


def _ref(src: Path, ref: str) -> str | None:
    proc = _git_proc(src, "rev-parse", "--verify", "-q", ref)
    assert proc.returncode in (0, 1), f"rig: rev-parse exited {proc.returncode}"
    return proc.stdout.decode("utf-8").strip() or None


def _heads(src: Path) -> dict[str, str]:
    """``{refname: sha}`` of every branch."""
    out = _git(src, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads")
    pairs = (line.split(" ", 1) for line in out.splitlines() if line)
    return {name: sha for name, sha in pairs}


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


def _manifest(wt: Path) -> dict[str, Any]:
    return json.loads((_git_dir(wt) / MANIFEST_NAME).read_text(encoding="utf-8"))


def _shows(lines: list[str], token: str, path: Path) -> bool:
    for line in lines:
        if line.startswith(f"{token}:"):
            shown = Path(line[len(token) + 1 :])
            if shown.exists() and os.path.samefile(shown, path):
                return True
    return False


@dataclass
class Rig:
    """One source repository, the tool under test and its captured stdout."""

    tool: Any
    src: Path
    scratch: Path
    capsys: pytest.CaptureFixture[str]
    venvs: list[Path] = field(default_factory=list)

    def call(self, *argv: object) -> tuple[int, list[str]]:
        self.capsys.readouterr()
        code = self.tool.main(["--root", str(self.src), *[str(a) for a in argv]])
        return code, self.capsys.readouterr().out.splitlines()

    def path(self, slug: str) -> Path:
        return Path(self.tool.WORKTREE_PARENT) / slug

    def base(self) -> str:
        return _git(self.src, "rev-parse", "refs/heads/main").strip()

    def create_lane(self, slug: str, *extra: str) -> Path:
        """``create <slug>`` and the AC-785.1 shape of the result."""
        code, lines = self.call("create", slug, *extra)
        wt = self.path(slug)
        assert code == 0 and lines[-1:] == [f"worktree_ready:{wt.as_posix()}"], (
            slug,
            code,
            lines,
        )
        branch = f"lane/{slug}"
        head = _git_proc(wt, "symbolic-ref", "-q", "HEAD")
        assert head.returncode == 0, f"{slug}: create left a detached HEAD"
        assert head.stdout.decode("utf-8").strip() == f"refs/heads/{branch}"
        assert _ref(self.src, f"refs/heads/{branch}") == self.base()
        assert _manifest(wt)["branch"] == branch
        assert _ref(self.src, f"{REF_PREFIX}{slug}") is not None, "baseline ref gone"
        return wt


@pytest.fixture(autouse=True)
def _worktree_parent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every worktree this file makes goes under a temp ``WORKTREE_PARENT``."""
    tool = importlib.import_module("tools.executor_worktree")
    monkeypatch.setattr(tool, "WORKTREE_PARENT", tmp_path / "wt", raising=False)


@pytest.fixture
def rig(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> Rig:
    tool = importlib.import_module("tools.executor_worktree")
    made = Rig(tool=tool, src=_build_source(tmp_path), scratch=tmp_path, capsys=capsys)

    def fake_venv(path: Path) -> int:
        made.venvs.append(Path(path))
        _write(Path(path), {".venv/pyvenv.cfg": b"home = stub\n"})
        return 0

    monkeypatch.setattr(tool, "_build_venv", fake_venv)
    return made


def _assert_nothing_left(rig: Rig, slug: str, heads: dict[str, str]) -> None:
    wt = rig.path(slug)
    assert not wt.exists(), f"{slug}: the refused create left {wt}"
    assert not _listed(rig.src, wt), f"{slug}: the refused create left a worktree"
    assert _ref(rig.src, f"{REF_PREFIX}{slug}") is None, f"{slug}: baseline ref left"
    assert _heads(rig.src) == heads, f"{slug}: the refused create changed a branch"


def _lane_commit(wt: Path) -> str:
    _write(wt, {LANE_FILE: b"LANE = 1\n"})
    _git(wt, "add", "--", LANE_FILE)
    _git(wt, "commit", "-q", "--no-verify", "-m", "lane work")
    return _git(wt, "rev-parse", "HEAD").strip()


# ---------------------------------------------------------------------------
# AC-785.1 — create checks out lane/<slug>; --branch takes only lane/<slug>
# ---------------------------------------------------------------------------


def test_create_checks_out_the_lane_branch_and_keeps_the_baseline(rig: Rig) -> None:
    rig.create_lane("lane-x")
    rig.create_lane("lane-y", "--branch", "lane/lane-y")


def test_create_refuses_a_branch_other_than_the_lane_branch(rig: Rig) -> None:
    for slug, branch in (("lane-m", "main"), ("lane-o", "lane/other")):
        heads = _heads(rig.src)
        code, lines = rig.call("create", slug, "--branch", branch)
        assert (code, lines) == (1, ["worktree_bad:branch"]), (branch, code, lines)
        _assert_nothing_left(rig, slug, heads)


def test_create_refuses_an_existing_lane_branch(rig: Rig) -> None:
    _git(rig.src, "branch", "lane/lane-e", "main")
    heads = _heads(rig.src)
    code, lines = rig.call("create", "lane-e")
    assert (code, lines) == (1, ["worktree_bad:branch_exists"]), (code, lines)
    _assert_nothing_left(rig, "lane-e", heads)


# ---------------------------------------------------------------------------
# AC-785.2 — check reports a linked worktree on main
# ---------------------------------------------------------------------------


def test_check_reports_a_linked_worktree_on_main(rig: Rig) -> None:
    wt = rig.create_lane("lane-c")
    _git(wt, "checkout", "-q", "--ignore-other-worktrees", "main")
    code, lines = rig.call("check", wt)
    assert code == 1, (code, lines)
    assert _shows(lines, "main_reserved", wt), lines


# ---------------------------------------------------------------------------
# AC-785.9 — remove deletes a landed lane branch, refuses an unlanded one
# ---------------------------------------------------------------------------


def test_remove_deletes_a_landed_lane_branch(rig: Rig) -> None:
    wt = rig.create_lane("lane-r")
    code, lines = rig.call("remove", wt)
    assert (code, lines) == (0, [f"worktree_removed:{wt.as_posix()}"]), lines
    assert not _listed(rig.src, wt)
    assert _ref(rig.src, f"{LANE_PREFIX}lane-r") is None, "the landed branch stayed"


def test_remove_refuses_an_unlanded_lane_tip_and_keeps_both(rig: Rig) -> None:
    wt = rig.create_lane("lane-u")
    tip = _lane_commit(wt)
    code, lines = rig.call("remove", wt)
    assert (code, lines) == (1, ["worktree_bad:unlanded"]), lines
    assert _listed(rig.src, wt) and wt.is_dir()
    assert _ref(rig.src, f"{LANE_PREFIX}lane-u") == tip


def test_remove_discard_deletes_an_unlanded_lane_branch(rig: Rig) -> None:
    wt = rig.create_lane("lane-d")
    _lane_commit(wt)
    code, lines = rig.call("remove", wt, "--discard")
    assert (code, lines) == (0, [f"worktree_removed:{wt.as_posix()}"]), lines
    assert not _listed(rig.src, wt)
    assert _ref(rig.src, f"{LANE_PREFIX}lane-d") is None, "--discard kept the branch"


# ---------------------------------------------------------------------------
# AC-785.10 — a legacy detached worktree keeps working
# ---------------------------------------------------------------------------


def _make_legacy(wt: Path, *, drop_key: bool) -> None:
    """Rewrite a new worktree into the stage-1 shape: detached, branch null or absent."""
    path = _git_dir(wt) / MANIFEST_NAME
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if drop_key:
        del manifest["branch"]
    else:
        manifest["branch"] = None
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    _git(wt, "checkout", "-q", "--detach")


@pytest.mark.parametrize("drop_key", [False, True], ids=["branch_null", "no_branch"])
def test_a_legacy_detached_worktree_checks_syncs_lands_and_removes(
    rig: Rig, drop_key: bool
) -> None:
    slug = "lane-l" if drop_key else "lane-n"
    wt = rig.create_lane(slug)
    _make_legacy(wt, drop_key=drop_key)
    assert rig.call("check", wt) == (0, ["worktree_ok"])
    assert rig.call("sync", wt, STATUS) == (0, [f"sync_ok:{STATUS}"])
    _write(wt, {LANE_FILE: b"LEGACY = 1\n"})
    code, lines = rig.call("land", wt)
    assert code == 0 and len(lines) == 1 and lines[0].startswith("land_ok:"), lines
    assert (rig.src / LANE_FILE).read_bytes().replace(b"\r\n", b"\n") == b"LEGACY = 1\n"
    heads = _heads(rig.src)
    code, lines = rig.call("remove", wt)
    assert (code, lines) == (0, [f"worktree_removed:{wt.as_posix()}"]), lines
    assert _heads(rig.src) == heads, "a legacy remove deleted a branch"
