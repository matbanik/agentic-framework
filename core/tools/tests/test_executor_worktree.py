"""GT-6 MEU-642 executor worktree: create, check, land, sync, remove — red first (G19).

FIC: ``docs/execution/plans/2026-10-01-gt6-shared-tree-session-concurrency/implementation-plan.md``
§MEU-642 (AC-642.1, AC-642.2; predicates ``EXECUTOR_WORKTREE`` and ``WORKTREE_LAND``).

Every test builds a real temp git repository (``core.autocrlf=true``) holding the
planning-to-execution state the tool exists for: tracked files, one of them CRLF on
disk, a tracked file an ignore rule also matches, a modified tracked status file, an
untracked plan folder, an ignored ``.env``, ``node_modules/`` and ``mcp-server/dist/``.
The tool's ``main()`` runs in-process. Git, the worktree, the junction and the gate
lease are real; only the venv step is replaced (it writes ``.venv/pyvenv.cfg``).
The rig is local to this file (rigs are copied between test files, never imported).
Multi-case tests run their cases in sequence inside one function (no parametrize).
Do not skip, only, or early-return (G36); the filesystem-dependent tests probe
the temp directory and assert their branch in full.
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

CREATE = "EXECUTOR_WORKTREE"
LAND = "WORKTREE_LAND"

REF_PREFIX = "refs/executor-worktrees/"
MANIFEST_NAME = "executor-worktree.json"
TEMP_INDEX_NAME = "executor-index.tmp"
MANIFEST_FIELDS = {
    "source_root",
    "slug",
    "branch",
    "links",
    "copies",
    "carry",
    "created",
}

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
TASK_OPEN = b"| 1 | row | `[ ]` |\n"
TASK_DONE = b"| 1 | row | `[x]` |\n"

# Committed. ``pkg/mod.py`` is CRLF on disk and LF in the repository (autocrlf).
# The ``node_modules`` rule has no trailing slash so that it matches the link the
# tool makes whether that link is a junction (a directory to git) or a symlink (a
# file to git); ``test_capture_never_records_links`` covers a link no rule matches.
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
# Written after the commit: ignored members and the untracked plan folder.
SEED_LOCAL: dict[str, bytes] = {
    ".env": ENV_BYTES,
    NODE_FILE: b"module.exports = 1;\n",
    DIST_FILE: b"console.log(1);\n",
    PLAN: b"# Plan\r\n\r\nApproved.\r\n",
    TASK: TASK_OPEN,
}
CARRIED = (PLAN, TASK, STATUS)

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
    if data is None:
        return subprocess.run(
            argv,
            cwd=repo,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            env=merged,
            check=False,
        )
    return subprocess.run(
        argv, cwd=repo, input=data, capture_output=True, env=merged, check=False
    )


def _git(
    repo: Path,
    *args: str,
    data: bytes | None = None,
    env: dict[str, str] | None = None,
) -> str:
    proc = _git_proc(repo, *args, data=data, env=env)
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
    """The AC-642.1 source repository at the planning-to-execution transition."""
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


def _is_link(path: Path) -> bool:
    return os.path.islink(path) or os.path.isjunction(path)


def _files(root: Path) -> list[tuple[str, Path]]:
    """Every file under ``root`` outside its top-level ``.git``; links not descended."""
    found: list[tuple[str, Path]] = []
    stack = [root]
    while stack:
        current = stack.pop()
        for entry in os.scandir(current):
            path = Path(entry.path)
            if current == root and entry.name == ".git":
                continue
            if _is_link(path):
                continue
            if entry.is_dir(follow_symlinks=False):
                stack.append(path)
            else:
                found.append((path.relative_to(root).as_posix(), path))
    return found


def _snapshot(root: Path) -> dict[str, bytes]:
    return {rel: path.read_bytes() for rel, path in _files(root)}


def _stamps(root: Path) -> dict[str, tuple[int, int]]:
    stamps: dict[str, tuple[int, int]] = {}
    for rel, path in _files(root):
        stat = path.stat()
        stamps[rel] = (stat.st_mtime_ns, stat.st_size)
    return stamps


def _lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def _tree_map(repo: Path, treeish: str) -> dict[str, str]:
    """``{path: blob}`` of every file in a tree."""
    result: dict[str, str] = {}
    for record in _git(repo, "ls-tree", "-r", "-z", treeish).split("\0"):
        if record:
            meta, _, name = record.partition("\t")
            result[name] = meta.split()[2]
    return result


def _blob(repo: Path, rel: str, data: bytes) -> str:
    return _git(repo, "hash-object", "--path", rel, "--stdin", data=data).strip()


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


def _capture(wt: Path, scratch: Path) -> str:
    """An independent capture of the worktree: HEAD-seeded index, ``add -A``, tree."""
    index = scratch / "oracle-index"
    if index.exists():
        index.unlink()
    env = {"GIT_INDEX_FILE": str(index)}
    _git(wt, "read-tree", "HEAD", env=env)
    _git(wt, "add", "-A", "--", ".", env=env)
    tree = _git(wt, "write-tree", env=env).strip()
    index.unlink()
    return tree


def _git_dir(wt: Path) -> Path:
    return Path(_git(wt, "rev-parse", "--absolute-git-dir").strip())


def _status(repo: Path) -> set[str]:
    return set(_git(repo, "status", "--porcelain").splitlines())


@dataclass
class Rig:
    """One source repository, the tool under test and its captured stdout."""

    tool: Any
    vc: Any
    src: Path
    scratch: Path
    capsys: pytest.CaptureFixture[str]
    venvs: list[Path] = field(default_factory=list)

    def call(self, *argv: object) -> tuple[int, list[str]]:
        self.capsys.readouterr()
        code = self.tool.main(["--root", str(self.src), *[str(a) for a in argv]])
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

    def create_carried(self, marker: str, slug: str) -> Path:
        return self.create(marker, slug, "--carry", PLAN_DIR, "--carry", STATUS)


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
    vc = tool
    rig = Rig(
        tool=tool, vc=vc, src=_build_source(tmp_path), scratch=tmp_path, capsys=capsys
    )

    def fake_venv(path: Path) -> int:
        rig.venvs.append(Path(path))
        _write(Path(path), {".venv/pyvenv.cfg": b"home = stub\n"})
        return 0

    monkeypatch.setattr(tool, "_build_venv", fake_venv)
    return rig


def test_create_carries_planning_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-642.1 — create carries the plan and status file into an LF worktree."""
    rig = _rig(tmp_path, monkeypatch, capsys, CREATE)
    src = rig.src
    head = _git(src, "rev-parse", "HEAD").strip()
    head_map = _tree_map(src, "HEAD")

    wt = rig.create_carried(CREATE, "gt6-a")

    assert wt == rig.parent / "gt6-a" and wt.is_dir(), f"{CREATE}: {wt}"
    assert _listed(src, wt), f"{CREATE}: git does not list {wt}"
    assert _git(wt, "rev-parse", "HEAD").strip() == head, f"{CREATE}: not at HEAD"
    assert _git_proc(wt, "symbolic-ref", "-q", "HEAD").returncode == 1, (
        f"{CREATE}: the worktree is on a branch, want a detached HEAD"
    )

    assert (wt / OVERLAY).read_bytes() == SEED_TRACKED[OVERLAY], (
        f"{CREATE}: the overlay file is not the committed LF bytes"
    )
    assert (wt / MODULE).read_bytes() == _lf(SEED_TRACKED[MODULE]), (
        f"{CREATE}: {MODULE} was not checked out with LF"
    )
    for rel in CARRIED:
        assert (wt / rel).read_bytes() == (src / rel).read_bytes(), (
            f"{CREATE}: carried {rel} differs from the source"
        )

    git_dir = _git_dir(wt)
    manifest_path = git_dir / MANIFEST_NAME
    assert manifest_path.is_file(), f"{CREATE}: no manifest at {manifest_path}"
    assert not (wt / MANIFEST_NAME).exists(), f"{CREATE}: manifest in the worktree"
    assert not (git_dir / TEMP_INDEX_NAME).exists(), (
        f"{CREATE}: the temporary index was left behind"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert set(manifest) == MANIFEST_FIELDS, f"{CREATE}: fields {sorted(manifest)}"
    assert manifest["slug"] == "gt6-a", f"{CREATE}: slug {manifest['slug']!r}"
    assert manifest["branch"] is None, f"{CREATE}: branch {manifest['branch']!r}"
    assert sorted(manifest["carry"]) == sorted(CARRIED), (
        f"{CREATE}: carry {manifest['carry']}"
    )
    assert manifest["links"] == ["node_modules"], f"{CREATE}: {manifest['links']}"
    assert sorted(manifest["copies"]) == [".env", "mcp-server/dist"], (
        f"{CREATE}: copies {manifest['copies']}"
    )
    assert os.path.samefile(manifest["source_root"], src), (
        f"{CREATE}: source_root {manifest['source_root']!r}"
    )
    assert isinstance(manifest["created"], str), f"{CREATE}: created is not text"
    assert datetime.fromisoformat(manifest["created"]).tzinfo is not None, (
        f"{CREATE}: created {manifest['created']!r} carries no timezone"
    )
    assert _status(wt) == {f" M {STATUS}", "?? docs/execution/"}, (
        f"{CREATE}: worktree status {_status(wt)}"
    )

    ref = f"{REF_PREFIX}gt6-a"
    assert _git(src, "cat-file", "-t", ref).strip() == "tree", (
        f"{CREATE}: {ref} is not a tree"
    )
    expected = dict(head_map)
    for rel in CARRIED:
        expected[rel] = _blob(src, rel, (src / rel).read_bytes())
    assert SETTINGS in expected, f"{CREATE}: rig lost {SETTINGS} from HEAD"
    base_map = _tree_map(src, ref)
    assert base_map == expected, (
        f"{CREATE}: baseline tree differs from HEAD plus the carried files: "
        f"{sorted(set(base_map.items()) ^ set(expected.items()))}"
    )
    leaked = [
        rel
        for rel in base_map
        if rel == ".env"
        or rel.startswith(("node_modules/", "mcp-server/dist/", ".venv/"))
    ]
    assert not leaked, f"{CREATE}: baseline holds ignored paths {leaked}"

    assert (wt / ".env").read_bytes() == ENV_BYTES, f"{CREATE}: .env not copied"
    link = wt / "node_modules"
    assert _is_link(link), f"{CREATE}: node_modules is not a link"
    assert os.path.isjunction(link) == (sys.platform == "win32"), (
        f"{CREATE}: node_modules is the wrong kind of link for {sys.platform}"
    )
    assert os.path.samefile(link, src / "node_modules"), (
        f"{CREATE}: node_modules does not resolve to the source directory"
    )
    assert (wt / NODE_FILE).read_bytes() == SEED_LOCAL[NODE_FILE], (
        f"{CREATE}: node_modules does not read through"
    )
    assert not _is_link(wt / "mcp-server") and not _is_link(wt / "mcp-server/dist"), (
        f"{CREATE}: mcp-server/dist is a link, want a real copy"
    )
    assert (wt / DIST_FILE).read_bytes() == SEED_LOCAL[DIST_FILE], (
        f"{CREATE}: mcp-server/dist not copied"
    )
    assert rig.venvs == [wt], f"{CREATE}: venv step ran for {rig.venvs}"
    assert (wt / ".venv/pyvenv.cfg").is_file(), f"{CREATE}: no venv in the worktree"

    assert rig.call("check", wt) == (0, ["worktree_ok"]), f"{CREATE}: fresh check"

    (wt / MODULE).write_bytes(b"A = 1\nB = 2\nC = 3\n")
    _write(wt, {"tests/new_test.py": b"def test_new():\n    assert True\n"})
    (wt / TASK).write_bytes(TASK_DONE)
    assert rig.call("check", wt) == (0, ["worktree_ok"]), (
        f"{CREATE}: check refused a worktree for holding executor edits"
    )

    branched = rig.create(CREATE, "gt6-c", "--branch", "gt6/a")
    assert _git(branched, "symbolic-ref", "--short", "HEAD").strip() == "gt6/a", (
        f"{CREATE}: --branch did not put the worktree on gt6/a"
    )
    branched_manifest = json.loads(
        (_git_dir(branched) / MANIFEST_NAME).read_text(encoding="utf-8")
    )
    assert branched_manifest["branch"] == "gt6/a", f"{CREATE}: {branched_manifest}"
    assert branched_manifest["carry"] == [], f"{CREATE}: {branched_manifest}"
    assert _tree_map(src, f"{REF_PREFIX}gt6-c") == head_map, (
        f"{CREATE}: a worktree with no carry has a baseline other than HEAD"
    )


def test_check_reports_reasons(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-642.1 negative — every check reason, each masking the ones after it."""
    rig = _rig(tmp_path, monkeypatch, capsys, CREATE)
    src = rig.src
    wt = rig.create_carried(CREATE, "gt6-a")
    ref = f"{REF_PREFIX}gt6-a"
    tree = _ref(src, "gt6-a")
    assert tree is not None, f"{CREATE}: create wrote no baseline ref"
    manifest_path = _git_dir(wt) / MANIFEST_NAME
    manifest_bytes = manifest_path.read_bytes()
    link = wt / "node_modules"

    def expect(reason: str, why: str) -> None:
        got = rig.call("check", wt)
        assert got == (1, [f"worktree_bad:{reason}"]), f"{CREATE}: {why}: {got}"

    plain = tmp_path / "plain"
    plain.mkdir()
    for unlisted in (plain, tmp_path / "absent"):
        got = rig.call("check", unlisted)
        assert got == (1, ["worktree_bad:unlisted"]), f"{CREATE}: {unlisted}: {got}"

    # Every defect at once; the repairs below then walk the order top down.
    (wt / ".env").unlink()
    (wt / ".venv/pyvenv.cfg").unlink()
    rig.vc._drop_dir_link(link)
    (wt / OVERLAY).write_bytes(SEED_TRACKED[OVERLAY].replace(b"\n", b"\r\n"))
    _git(src, "update-ref", "-d", ref)
    manifest_path.unlink()

    expect("manifest", "manifest deleted")
    manifest_path.write_bytes(b"{")
    expect("manifest", "manifest unparsable")
    manifest_path.write_bytes(manifest_bytes)

    expect("baseline", "baseline ref deleted")
    _git(src, "update-ref", ref, _git(src, "rev-parse", "HEAD").strip())
    expect("baseline", "baseline ref names a commit, not a tree")
    _git(src, "update-ref", ref, tree)

    expect("overlay_crlf", "overlay rewritten with CRLF")
    (wt / OVERLAY).write_bytes(SEED_TRACKED[OVERLAY])

    expect("link:node_modules", "node_modules link missing")
    _write(wt, {"node_modules/real.txt": b"a real directory\n"})
    expect("link:node_modules", "node_modules replaced by a real directory")
    shutil.rmtree(link)
    rig.vc._make_dir_link(link, src / "node_modules")

    expect("venv", "pyvenv.cfg missing")
    _write(wt, {".venv/pyvenv.cfg": b"home = stub\n"})

    expect("env", "the source has .env and the worktree does not")
    (wt / ".env").write_bytes(ENV_BYTES)
    assert rig.call("check", wt) == (0, ["worktree_ok"]), (
        f"{CREATE}: check still refuses after every repair"
    )

    (src / ".env").unlink()
    expect("env", "the worktree has .env and the source does not")
    assert (src / NODE_FILE).read_bytes() == SEED_LOCAL[NODE_FILE], (
        f"{CREATE}: the source's node_modules lost its contents"
    )


def test_land_then_remove_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-642.2 — land writes the diff onto the source, uncommitted; remove follows."""
    rig = _rig(tmp_path, monkeypatch, capsys, LAND)
    src = rig.src
    wt = rig.create_carried(LAND, "gt6-a")
    log_before = _git(src, "log", "--all", "--format=%H")
    status_before = _status(src)

    (wt / MODULE).write_bytes(b"A = 1\nB = 2\nC = 3\n")
    (wt / GONE).unlink()
    _write(wt, {"docs/new.md": b"new\n"})
    (wt / TASK).write_bytes(TASK_DONE)
    worktree_before = _snapshot(wt)

    assert rig.call("land", wt) == (0, ["land_ok:1:2:1"]), f"{LAND}: first land"

    assert (src / MODULE).read_bytes() == b"A = 1\r\nB = 2\r\nC = 3\r\n", (
        f"{LAND}: {MODULE} lost the source's CRLF: {(src / MODULE).read_bytes()!r}"
    )
    assert not (src / GONE).exists(), f"{LAND}: {GONE} still on the source"
    assert _lf((src / "docs/new.md").read_bytes()) == b"new\n", f"{LAND}: new.md"
    assert _lf((src / TASK).read_bytes()) == TASK_DONE, f"{LAND}: task row not landed"
    assert _snapshot(wt) == worktree_before, f"{LAND}: land changed the worktree"
    assert _git(src, "log", "--all", "--format=%H") == log_before, (
        f"{LAND}: land committed"
    )
    assert _git(src, "diff", "--cached", "--name-only") == "", (
        f"{LAND}: land staged something in the real index"
    )
    assert _status(src) == status_before | {
        f" M {MODULE}",
        f" D {GONE}",
        "?? docs/new.md",
    }, f"{LAND}: source status {_status(src)}"
    landed = _ref(src, "gt6-a")
    assert landed == _capture(wt, tmp_path), (
        f"{LAND}: the baseline ref is not the worktree's tree after land"
    )

    source_before = _stamps(src)
    assert rig.call("land", wt) == (0, ["land_ok:0:0:0"]), f"{LAND}: second land"
    assert _stamps(src) == source_before, f"{LAND}: an empty land rewrote files"
    assert _ref(src, "gt6-a") == landed, f"{LAND}: an empty land moved the baseline"

    (wt / "docs/new.md").write_bytes(b"new\nmore\n")
    assert rig.call("land", wt) == (0, ["land_ok:0:1:0"]), f"{LAND}: incremental"
    assert _lf((src / "docs/new.md").read_bytes()) == b"new\nmore\n", (
        f"{LAND}: the incremental edit did not land"
    )

    code, lines = rig.call("remove", wt)
    assert code == 0 and lines[-1:] == [f"worktree_removed:{wt.as_posix()}"], (
        f"{LAND}: remove exited {code} with {lines}"
    )
    assert (src / NODE_FILE).read_bytes() == SEED_LOCAL[NODE_FILE], (
        f"{LAND}: remove deleted the source's node_modules contents"
    )
    assert not os.path.lexists(wt), f"{LAND}: {wt} still exists"
    assert not _listed(src, wt), f"{LAND}: git still lists {wt}"
    assert _ref(src, "gt6-a") is None, f"{LAND}: the baseline ref survived remove"
    assert _git(src, "log", "--all", "--format=%H") == log_before, (
        f"{LAND}: remove changed the history"
    )


def test_land_refuses_then_sync_recovers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-642.2 — a sibling's edit refuses the landing; sync plus re-edit recovers."""
    rig = _rig(tmp_path, monkeypatch, capsys, LAND)
    src = rig.src
    wt = rig.create_carried(LAND, "gt6-a")
    baseline = _ref(src, "gt6-a")

    sibling = b"MEU-1: approved\r\nMEU-2: pending\r\nMEU-3: sibling\r\n"
    (src / STATUS).write_bytes(sibling)
    (wt / STATUS).write_bytes(STATUS_MODIFIED + b"MEU-4: executor\n")
    source_before = _snapshot(src)

    assert rig.call("land", wt) == (1, [f"land_fail:changed:{STATUS}"]), (
        f"{LAND}: a sibling's edit to the same file was not refused"
    )
    assert _snapshot(src) == source_before, f"{LAND}: a refused land wrote"
    assert _ref(src, "gt6-a") == baseline, f"{LAND}: a refused land moved the ref"

    assert rig.call("sync", wt, STATUS) == (0, [f"sync_ok:{STATUS}"]), (
        f"{LAND}: sync of the refused file"
    )
    assert (wt / STATUS).read_bytes() == _lf(sibling), (
        f"{LAND}: sync did not give the worktree the sibling's bytes with LF: "
        f"{(wt / STATUS).read_bytes()!r}"
    )
    assert _snapshot(src) == source_before, f"{LAND}: sync wrote to the source"
    assert _tree_map(src, f"{REF_PREFIX}gt6-a")[STATUS] == _blob(
        src, STATUS, sibling
    ), f"{LAND}: sync did not refresh the baseline entry"

    both = _lf(sibling) + b"MEU-4: executor\n"
    (wt / STATUS).write_bytes(both)
    assert rig.call("land", wt) == (0, ["land_ok:0:1:0"]), f"{LAND}: land after sync"
    assert _lf((src / STATUS).read_bytes()) == both, (
        f"{LAND}: the source does not hold both edits: {(src / STATUS).read_bytes()!r}"
    )


def test_land_keeps_a_file_named_like_its_scratch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-642.2 — landing never replaces or deletes a sibling file beside its target."""
    rig = _rig(tmp_path, monkeypatch, capsys, LAND)
    src = rig.src
    wt = rig.create_carried(LAND, "gt6-a")

    scratch = src / (KEEP + ".executor-write.tmp")
    sibling = b"a sibling session's file that only shares the name\n"
    scratch.write_bytes(sibling)
    edited = b"the executor edits this file\n"
    (wt / KEEP).write_bytes(edited)

    assert rig.call("land", wt) == (0, ["land_ok:0:1:0"]), f"{LAND}: land of {KEEP}"
    assert _lf((src / KEEP).read_bytes()) == edited, f"{LAND}: {KEEP} not landed"
    assert scratch.exists(), f"{LAND}: land deleted the sibling's {scratch.name}"
    assert scratch.read_bytes() == sibling, (
        f"{LAND}: land changed the sibling's {scratch.name}: {scratch.read_bytes()!r}"
    )
    leftovers = sorted(
        entry.name
        for entry in scratch.parent.iterdir()
        if entry.name.endswith(".executor-write.tmp") and entry != scratch
    )
    assert leftovers == [], f"{LAND}: land left scratch files behind: {leftovers}"


def test_sync_keeps_a_file_named_like_its_scratch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-642.2 — sync never replaces or deletes an executor file beside its target."""
    rig = _rig(tmp_path, monkeypatch, capsys, LAND)
    src = rig.src
    wt = rig.create_carried(LAND, "gt6-a")

    scratch = wt / (KEEP + ".executor-write.tmp")
    work = b"the executor's own file that only shares the name\n"
    scratch.write_bytes(work)
    (src / KEEP).write_bytes(b"a sibling edit\n")

    assert rig.call("sync", wt, KEEP) == (0, [f"sync_ok:{KEEP}"]), f"{LAND}: sync"
    assert (wt / KEEP).read_bytes() == b"a sibling edit\n", f"{LAND}: {KEEP} not synced"
    assert scratch.exists(), f"{LAND}: sync deleted the executor's {scratch.name}"
    assert scratch.read_bytes() == work, (
        f"{LAND}: sync changed the executor's {scratch.name}: {scratch.read_bytes()!r}"
    )
    leftovers = sorted(
        entry.name
        for entry in scratch.parent.iterdir()
        if entry.name.endswith(".executor-write.tmp") and entry != scratch
    )
    assert leftovers == [], f"{LAND}: sync left scratch files behind: {leftovers}"


def test_capture_keeps_tracked_ignored_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-642.2 — ignore rules never drop a tracked file from the capture."""
    rig = _rig(tmp_path, monkeypatch, capsys, LAND)
    src = rig.src
    wt = rig.create_carried(LAND, "gt6-a")
    ref = f"{REF_PREFIX}gt6-a"

    edited = b'{\n  "editor.tabSize": 2\n}\n'
    (wt / SETTINGS).write_bytes(edited)
    assert rig.call("land", wt) == (0, ["land_ok:0:1:0"]), (
        f"{LAND}: an edit to a tracked file that an ignore rule matches"
    )
    assert _lf((src / SETTINGS).read_bytes()) == edited, (
        f"{LAND}: the source does not hold the {SETTINGS} edit"
    )
    assert _tree_map(src, ref)[SETTINGS] == _blob(src, SETTINGS, edited), (
        f"{LAND}: the baseline does not hold the {SETTINGS} edit"
    )

    rules = SEED_TRACKED[".gitignore"] + b"data/\n"
    (wt / ".gitignore").write_bytes(rules)
    assert rig.call("land", wt) == (0, ["land_ok:0:1:0"]), (
        f"{LAND}: a new ignore rule landed as more than the .gitignore entry"
    )
    assert _lf((src / ".gitignore").read_bytes()) == rules, f"{LAND}: .gitignore"
    assert (src / IGNORED_LATER).read_bytes() == SEED_TRACKED[IGNORED_LATER], (
        f"{LAND}: the new ignore rule deleted {IGNORED_LATER} on the source"
    )
    assert IGNORED_LATER in _tree_map(src, ref), (
        f"{LAND}: the new ignore rule dropped {IGNORED_LATER} from the baseline"
    )


def test_land_holds_main_tree_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-642.2 — land runs under the source tree's gate lease and is resumable."""
    rig = _rig(tmp_path, monkeypatch, capsys, LAND)
    src, vc, tool = rig.src, rig.vc, rig.tool
    wt = rig.create_carried(LAND, "gt6-a")
    baseline = _ref(src, "gt6-a")
    (wt / MODULE).write_bytes(b"A = 1\nB = 2\nC = 3\n")
    _write(wt, {"docs/new.md": b"new\n"})
    source_before = _snapshot(src)

    lease = vc._acquire_lease(
        vc._lease_path(src), argv=["test-holder"], source_root=str(src)
    )
    try:
        busy = rig.call("land", wt)
        assert busy == (1, [f"land_fail:busy:{os.getpid()}"]), f"{LAND}: {busy}"
        assert _snapshot(src) == source_before, f"{LAND}: a busy land wrote"
        assert _ref(src, "gt6-a") == baseline, f"{LAND}: a busy land moved the ref"
    finally:
        vc._release_lease(lease)

    real_git = tool._run_git
    seen: list[list[str]] = []

    def failing_first_update_ref(args: Any, **kwargs: Any) -> Any:
        argv = [str(a) for a in args]
        if "update-ref" in argv:
            seen.append(argv)
            if len(seen) == 1:
                return subprocess.CompletedProcess(
                    ["git", *argv], 1, b"", b"simulated update-ref failure\n"
                )
        return real_git(args, **kwargs)

    monkeypatch.setattr(tool, "_run_git", failing_first_update_ref)

    interrupted = rig.call("land", wt)
    assert interrupted == (1, ["git_error:update-ref"]), f"{LAND}: {interrupted}"
    assert len(seen) == 1, f"{LAND}: update-ref ran {len(seen)} time(s)"
    assert (src / MODULE).read_bytes() == b"A = 1\r\nB = 2\r\nC = 3\r\n", (
        f"{LAND}: the write before the failed update-ref is missing"
    )
    assert _lf((src / "docs/new.md").read_bytes()) == b"new\n", (
        f"{LAND}: the added file before the failed update-ref is missing"
    )
    assert _ref(src, "gt6-a") == baseline, f"{LAND}: the ref moved without update-ref"

    stamps = _stamps(src)
    assert rig.call("land", wt) == (0, ["land_ok:1:1:0"]), f"{LAND}: the rerun"
    assert _stamps(src) == stamps, f"{LAND}: the rerun rewrote landed files"
    assert _ref(src, "gt6-a") == _capture(wt, tmp_path), (
        f"{LAND}: the rerun did not advance the baseline"
    )
    assert len(seen) == 2, f"{LAND}: update-ref ran {len(seen)} time(s) in all"

    free = vc._acquire_lease(
        vc._lease_path(src), argv=["test-after"], source_root=str(src)
    )
    vc._release_lease(free)


def test_land_refuses_case_only_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-642.2 negative — a case-only rename is refused, never silently lost."""
    rig = _rig(tmp_path, monkeypatch, capsys, LAND)
    src = rig.src
    (tmp_path / "probe").write_bytes(b"")
    insensitive = (tmp_path / "PROBE").exists()
    wt = rig.create_carried(LAND, "gt6-a")
    baseline = _ref(src, "gt6-a")

    _git(wt, "mv", GUIDE, "docs/guide.md")
    assert "guide.md" in os.listdir(wt / "docs"), f"{LAND}: rig rename did not happen"
    assert "Guide.md" not in os.listdir(wt / "docs"), f"{LAND}: rig rename incomplete"
    source_before = _snapshot(src)

    landed = rig.call("land", wt)
    if insensitive:
        assert landed == (1, [f"land_fail:case:{GUIDE}"]), f"{LAND}: {landed}"
        assert _snapshot(src) == source_before, f"{LAND}: a refused land wrote"
        assert "Guide.md" in os.listdir(src / "docs"), (
            f"{LAND}: the source no longer spells Guide.md: {os.listdir(src / 'docs')}"
        )
        assert _ref(src, "gt6-a") == baseline, f"{LAND}: a refused land moved the ref"

        removed = rig.call("remove", wt)
        assert removed == (1, [f"worktree_bad:case:{GUIDE}"]), f"{LAND}: {removed}"
        assert _listed(src, wt) and wt.is_dir(), f"{LAND}: remove dropped the worktree"
        assert _is_link(wt / "node_modules"), f"{LAND}: remove dropped the link"

        _git(wt, "mv", "docs/guide.md", GUIDE)
        assert rig.call("land", wt) == (0, ["land_ok:0:0:0"]), (
            f"{LAND}: land after the spelling was restored"
        )
    else:
        assert landed == (0, ["land_ok:1:0:1"]), f"{LAND}: {landed}"
        names = os.listdir(src / "docs")
        assert "guide.md" in names and "Guide.md" not in names, (
            f"{LAND}: the source does not spell guide.md: {names}"
        )

    code, lines = rig.call("remove", wt)
    assert code == 0 and lines[-1:] == [f"worktree_removed:{wt.as_posix()}"], (
        f"{LAND}: remove exited {code} with {lines}"
    )
    assert not os.path.lexists(wt), f"{LAND}: {wt} still exists"


def test_remove_preflights_before_dropping_links(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-642.2 negative — remove refuses unlanded work and a replaced link first."""
    rig = _rig(tmp_path, monkeypatch, capsys, CREATE)
    src = rig.src
    wt = rig.create_carried(CREATE, "gt6-a")
    _write(wt, {"docs/unlanded.md": b"not landed\n"})

    refused = rig.call("remove", wt)
    assert refused == (1, ["worktree_bad:unlanded"]), f"{CREATE}: {refused}"
    assert _listed(src, wt) and wt.is_dir(), f"{CREATE}: refusal removed the worktree"
    assert _is_link(wt / "node_modules"), f"{CREATE}: refusal dropped the link"
    assert _ref(src, "gt6-a") is not None, f"{CREATE}: refusal deleted the ref"
    assert (wt / "docs/unlanded.md").is_file(), f"{CREATE}: refusal lost the edit"

    code, lines = rig.call("remove", wt, "--discard")
    assert code == 0 and lines[-1:] == [f"worktree_removed:{wt.as_posix()}"], (
        f"{CREATE}: remove --discard exited {code} with {lines}"
    )
    assert not os.path.lexists(wt), f"{CREATE}: {wt} still exists"
    assert not _listed(src, wt), f"{CREATE}: git still lists {wt}"
    assert _ref(src, "gt6-a") is None, f"{CREATE}: the ref survived --discard"
    assert not (src / "docs/unlanded.md").exists(), (
        f"{CREATE}: --discard landed the abandoned edit"
    )
    assert (src / NODE_FILE).read_bytes() == SEED_LOCAL[NODE_FILE], (
        f"{CREATE}: --discard deleted the source's node_modules contents"
    )

    second = rig.create(CREATE, "gt6-b")
    link = second / "node_modules"
    rig.vc._drop_dir_link(link)
    _write(second, {"node_modules/only-copy.txt": b"the only copy\n"})
    for flags in ((), ("--discard",)):
        got = rig.call("remove", second, *flags)
        assert got == (1, ["worktree_bad:link:node_modules"]), (
            f"{CREATE}: remove {flags} over a real directory: {got}"
        )
        assert (link / "only-copy.txt").read_bytes() == b"the only copy\n", (
            f"{CREATE}: remove {flags} deleted a real directory's contents"
        )
        assert _listed(src, second), f"{CREATE}: remove {flags} ran git worktree remove"
        assert _ref(src, "gt6-b") is not None, (
            f"{CREATE}: remove {flags} dropped the ref"
        )


# --- M42-2: the AC-642.1 and AC-642.2 positives and negatives not named in M42-1 ---


def _torn_down(rig: Rig, marker: str, slug: str, why: str) -> None:
    """A refused ``create`` left no worktree, no ref and the source's links intact."""
    wt = rig.path(slug)
    assert not os.path.lexists(wt), f"{marker}: {why}: {wt} was left behind"
    assert not _listed(rig.src, wt), f"{marker}: {why}: git still lists {wt}"
    assert _ref(rig.src, slug) is None, f"{marker}: {why}: a baseline ref was left"
    assert (rig.src / NODE_FILE).read_bytes() == SEED_LOCAL[NODE_FILE], (
        f"{marker}: {why}: the teardown deleted the source's node_modules contents"
    )


def test_create_refuses_and_leaves_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-642.1 negative — every create refusal, each leaving no worktree behind."""
    rig = _rig(tmp_path, monkeypatch, capsys, CREATE)
    src, tool = rig.src, rig.tool
    wt = rig.create(CREATE, "gt6-a")
    listing = _git(src, "worktree", "list", "--porcelain")

    again = rig.call("create", "gt6-a")
    assert again == (1, ["worktree_bad:exists"]), f"{CREATE}: second create: {again}"
    assert rig.call("check", wt) == (0, ["worktree_ok"]), (
        f"{CREATE}: the refused second create damaged the first worktree"
    )
    occupied = rig.path("gt6-taken")
    _write(occupied, {"note.txt": b"a plain directory already at the path\n"})
    taken = rig.call("create", "gt6-taken")
    assert taken == (1, ["worktree_bad:exists"]), f"{CREATE}: occupied path: {taken}"
    assert (occupied / "note.txt").is_file() and not _listed(src, occupied), (
        f"{CREATE}: create touched a directory it did not make"
    )

    for slug in ("GT6_A", "a", "ab_c", "ab.c", "ab/c", "a" * 42):
        got = rig.call("create", slug)
        assert got == (1, ["worktree_bad:slug"]), f"{CREATE}: slug {slug!r}: {got}"
        assert not os.path.lexists(rig.parent / slug), (
            f"{CREATE}: slug {slug!r} created a directory"
        )

    for carry, slug in (
        ("docs/missing.md", "gt6-m"),
        (".env", "gt6-e"),
        ("node_modules", "gt6-n"),
    ):
        got = rig.call("create", slug, "--carry", carry)
        assert got == (1, [f"worktree_bad:carry_missing:{carry}"]), (
            f"{CREATE}: --carry {carry}: {got}"
        )
        _torn_down(rig, CREATE, slug, f"--carry {carry}")

    several = rig.call(
        "create",
        "gt6-m",
        "--branch",
        "gt6/m",
        "--carry",
        STATUS,
        "--carry",
        "zz/absent",
        "--carry",
        "docs/missing.md",
    )
    assert several == (
        1,
        [
            "worktree_bad:carry_missing:zz/absent",
            "worktree_bad:carry_missing:docs/missing.md",
        ],
    ), f"{CREATE}: two missing carries, argument order: {several}"
    _torn_down(rig, CREATE, "gt6-m", "two missing carries")
    assert (
        _git_proc(src, "rev-parse", "--verify", "-q", "refs/heads/gt6/m").returncode
        == 1
    ), f"{CREATE}: the refused create left its branch behind"

    real_git = tool._run_git
    built = list(rig.venvs)

    def dirty_status(args: Any, **kwargs: Any) -> Any:
        argv = [str(a) for a in args]
        if "status" in argv:
            return subprocess.CompletedProcess(["git", *argv], 0, b" M x\n", b"")
        return real_git(args, **kwargs)

    monkeypatch.setattr(tool, "_run_git", dirty_status)
    dirty = rig.call("create", "gt6-d")
    monkeypatch.setattr(tool, "_run_git", real_git)
    assert dirty == (1, ["worktree_bad:bootstrap_dirty"]), f"{CREATE}: {dirty}"
    _torn_down(rig, CREATE, "gt6-d", "bootstrap_dirty")
    assert rig.venvs == built, f"{CREATE}: a dirty bootstrap still built a venv"

    stub_venv = tool._build_venv
    monkeypatch.setattr(tool, "_build_venv", lambda path: 1)
    no_venv = rig.call("create", "gt6-v")
    monkeypatch.setattr(tool, "_build_venv", stub_venv)
    assert no_venv == (1, ["worktree_bad:venv"]), f"{CREATE}: failed venv: {no_venv}"
    _torn_down(rig, CREATE, "gt6-v", "failed venv build")

    assert _git(src, "worktree", "list", "--porcelain") == listing, (
        f"{CREATE}: the refusals changed git's worktree list"
    )
    refs = _git(src, "for-each-ref", "--format=%(refname)", REF_PREFIX).split()
    assert refs == [f"{REF_PREFIX}gt6-a"], f"{CREATE}: refs after refusals: {refs}"

    retried = rig.create(
        CREATE, "gt6-m", "--branch", "gt6/m", "--carry", PLAN_DIR, "--carry", PLAN
    )
    manifest = json.loads(
        (_git_dir(retried) / MANIFEST_NAME).read_text(encoding="utf-8")
    )
    assert sorted(manifest["carry"]) == sorted((PLAN, TASK)), (
        f"{CREATE}: overlapping carries listed {manifest['carry']}"
    )


def test_create_refuses_head_with_two_spellings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-642.1 negative — a HEAD this filesystem cannot hold is refused at create."""
    rig = _rig(tmp_path, monkeypatch, capsys, CREATE)
    src = rig.src
    (tmp_path / "probe").write_bytes(b"")
    insensitive = (tmp_path / "PROBE").exists()
    for rel, data in (("Notes/a.md", b"a\n"), ("notes/b.md", b"b\n")):
        blob = _git(src, "hash-object", "-w", "--stdin", data=data).strip()
        _git(src, "update-index", "--add", "--cacheinfo", f"100644,{blob},{rel}")
    _git(src, "commit", "-q", "--no-verify", "-m", "two spellings of one directory")
    head_map = _tree_map(src, "HEAD")
    assert {"Notes/a.md", "notes/b.md"} <= set(head_map), (
        f"{CREATE}: rig did not commit both spellings: {sorted(head_map)}"
    )

    got = rig.call("create", "gt6-a")
    wt = rig.path("gt6-a")
    if insensitive:
        assert got == (1, ["worktree_bad:case:notes/b.md"]), f"{CREATE}: {got}"
        _torn_down(rig, CREATE, "gt6-a", "two spellings")
    else:
        assert got == (0, [f"worktree_ready:{wt.as_posix()}"]), f"{CREATE}: {got}"
        assert _tree_map(src, f"{REF_PREFIX}gt6-a") == head_map, (
            f"{CREATE}: the baseline is not HEAD on a case-sensitive filesystem"
        )


def test_commands_refuse_unusable_worktree_before_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-642.2 negative — unlisted, manifest, baseline: every command, no write."""
    rig = _rig(tmp_path, monkeypatch, capsys, LAND)
    src = rig.src
    wt = rig.create_carried(LAND, "gt6-a")
    ref = f"{REF_PREFIX}gt6-a"
    tree = _ref(src, "gt6-a")
    assert tree is not None, f"{LAND}: create wrote no baseline ref"
    manifest_path = _git_dir(wt) / MANIFEST_NAME
    manifest_bytes = manifest_path.read_bytes()

    # Work that land and sync would move if they got past the refusal.
    (wt / MODULE).write_bytes(b"A = 1\nB = 2\nC = 3\n")
    (src / KEEP).write_bytes(b"a sibling edit that sync would copy\n")
    plain = tmp_path / "plain"
    plain.mkdir()
    source_before, worktree_before = _snapshot(src), _snapshot(wt)

    def expect(path: Path, reason: str, why: str) -> None:
        for argv in (
            ("check", path),
            ("land", path),
            ("sync", path, KEEP),
            ("remove", path),
            ("remove", path, "--discard"),
        ):
            got = rig.call(*argv)
            assert got == (1, [f"worktree_bad:{reason}"]), (
                f"{LAND}: {why}: {argv[0]} {argv[2:]}: {got}"
            )
        assert _snapshot(src) == source_before, f"{LAND}: {why}: the source changed"
        assert _snapshot(wt) == worktree_before, f"{LAND}: {why}: the worktree changed"
        assert _listed(src, wt) and _is_link(wt / "node_modules"), (
            f"{LAND}: {why}: the worktree or its link was dropped"
        )

    expect(plain, "unlisted", "a plain directory")
    _git(src, "update-ref", "-d", ref)
    expect(wt, "baseline", "baseline ref deleted")
    manifest_path.unlink()
    expect(wt, "manifest", "manifest and ref both gone; the manifest is read first")
    manifest_path.write_bytes(manifest_bytes)
    expect(wt, "baseline", "manifest restored, ref still gone")
    _git(src, "update-ref", ref, tree)

    assert rig.call("sync", wt, KEEP) == (0, [f"sync_ok:{KEEP}"]), (
        f"{LAND}: sync after the ref was restored"
    )
    assert rig.call("land", wt) == (0, ["land_ok:0:1:0"]), (
        f"{LAND}: land after the ref was restored"
    )


def test_land_collisions_with_a_sibling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-642.2 negatives — exists, shape, missing, changed, and what is not one."""
    rig = _rig(tmp_path, monkeypatch, capsys, LAND)
    src = rig.src
    wt = rig.create(LAND, "gt6-b")
    ref = f"{REF_PREFIX}gt6-b"
    status_before = _status(src)

    # A worktree that only adds an untracked file.
    _write(wt, {"docs/only.md": b"only\n"})
    assert rig.call("land", wt) == (0, ["land_ok:1:0:0"]), f"{LAND}: untracked only"
    assert _lf((src / "docs/only.md").read_bytes()) == b"only\n", f"{LAND}: only.md"
    assert _status(src) == status_before | {"?? docs/only.md"}, (
        f"{LAND}: source status {_status(src)}"
    )

    # A sibling's edit to a file the worktree never touched is left alone.
    sibling_keep = b"a sibling rewrote this file\r\n"
    (src / KEEP).write_bytes(sibling_keep)
    keep_stamp = _stamps(src)[KEEP]
    (wt / MODULE).write_bytes(b"A = 1\nB = 2\nC = 3\n")
    assert rig.call("land", wt) == (0, ["land_ok:0:1:0"]), f"{LAND}: untouched file"
    assert (src / KEEP).read_bytes() == sibling_keep, f"{LAND}: {KEEP} was overwritten"
    assert _stamps(src)[KEEP] == keep_stamp, f"{LAND}: {KEEP} was rewritten"
    assert (wt / KEEP).read_bytes() == SEED_TRACKED[KEEP], (
        f"{LAND}: land changed the worktree's {KEEP}"
    )

    # exists: the sibling created the same new path; the tracked edit is held back.
    edited_guide = b"# Guide\n\nEdited.\n"
    _write(src, {"docs/new.md": b"the sibling wrote this\n"})
    _write(wt, {"docs/new.md": b"the executor wrote this\n"})
    (wt / GUIDE).write_bytes(edited_guide)
    source_before, baseline = _snapshot(src), _ref(src, "gt6-b")
    refused = rig.call("land", wt)
    assert refused == (1, ["land_fail:exists:docs/new.md"]), f"{LAND}: {refused}"
    assert _snapshot(src) == source_before, (
        f"{LAND}: a refused land applied part of the diff"
    )
    assert _ref(src, "gt6-b") == baseline, f"{LAND}: a refused land moved the ref"
    assert rig.call("sync", wt, "docs/new.md") == (0, ["sync_ok:docs/new.md"]), (
        f"{LAND}: sync of the colliding path"
    )
    assert (wt / "docs/new.md").read_bytes() == b"the sibling wrote this\n", (
        f"{LAND}: sync did not hand the worktree the sibling's file"
    )
    assert rig.call("land", wt) == (0, ["land_ok:0:1:0"]), f"{LAND}: land after sync"
    assert _lf((src / GUIDE).read_bytes()) == edited_guide, (
        f"{LAND}: {GUIDE} not landed"
    )
    assert (src / "docs/new.md").read_bytes() == b"the sibling wrote this\n", (
        f"{LAND}: the sibling's file was overwritten"
    )

    # exists again; this time the source file is removed instead of synced.
    _write(src, {"docs/other.md": b"the sibling wrote this too\n"})
    _write(wt, {"docs/other.md": b"the executor wants this\n"})
    refused = rig.call("land", wt)
    assert refused == (1, ["land_fail:exists:docs/other.md"]), f"{LAND}: {refused}"
    (src / "docs/other.md").unlink()
    assert rig.call("land", wt) == (0, ["land_ok:1:0:0"]), (
        f"{LAND}: land after the colliding source file was removed"
    )
    assert _lf((src / "docs/other.md").read_bytes()) == b"the executor wants this\n", (
        f"{LAND}: other.md not landed"
    )

    # Identical content is not a collision, whatever the line endings on disk.
    _write(src, {"docs/same.md": b"same\r\n"})
    _write(wt, {"docs/same.md": b"same\n"})
    same_stamp = _stamps(src)["docs/same.md"]
    assert rig.call("land", wt) == (0, ["land_ok:1:0:0"]), f"{LAND}: identical bytes"
    assert (src / "docs/same.md").read_bytes() == b"same\r\n", (
        f"{LAND}: an identical file was rewritten"
    )
    assert _stamps(src)["docs/same.md"] == same_stamp, (
        f"{LAND}: an identical file was touched"
    )

    # shape: a directory where a file would land, a file where a directory would.
    _write(
        src,
        {
            "deep": b"a file where the worktree has a directory\n",
            "docs/shape.md/inner.txt": b"a directory where the worktree has a file\n",
        },
    )
    _write(wt, {"deep/x.md": b"x\n", "docs/shape.md": b"shape\n"})
    source_before, baseline = _snapshot(src), _ref(src, "gt6-b")
    refused = rig.call("land", wt)
    assert refused == (
        1,
        ["land_fail:shape:deep/x.md", "land_fail:shape:docs/shape.md"],
    ), f"{LAND}: shape refusals in path order: {refused}"
    assert _snapshot(src) == source_before, f"{LAND}: a shape refusal wrote"
    assert _ref(src, "gt6-b") == baseline, f"{LAND}: a shape refusal moved the ref"
    shutil.rmtree(wt / "deep")
    (wt / "docs/shape.md").unlink()
    assert rig.call("land", wt) == (0, ["land_ok:0:0:0"]), (
        f"{LAND}: land after the shape collisions were withdrawn"
    )

    # missing: the sibling deleted a file the worktree edited.
    (wt / GUIDE).write_bytes(b"# Guide\n\nEdited twice.\n")
    (src / GUIDE).unlink()
    refused = rig.call("land", wt)
    assert refused == (1, [f"land_fail:missing:{GUIDE}"]), f"{LAND}: {refused}"
    assert not (src / GUIDE).exists(), f"{LAND}: a refused land recreated {GUIDE}"
    assert rig.call("sync", wt, GUIDE) == (0, [f"sync_ok:{GUIDE}"]), (
        f"{LAND}: sync of a file the source deleted"
    )
    assert not (wt / GUIDE).exists(), f"{LAND}: sync kept a file the source deleted"
    assert GUIDE not in _tree_map(src, ref), (
        f"{LAND}: sync kept the deleted file in the baseline"
    )
    assert rig.call("land", wt) == (0, ["land_ok:0:0:0"]), (
        f"{LAND}: land after the deletion was synced"
    )

    # changed on a delete: the sibling edited a file the worktree deleted.
    sibling_gone = b"a sibling edited the file the executor deleted\n"
    (wt / GONE).unlink()
    (src / GONE).write_bytes(sibling_gone)
    refused = rig.call("land", wt)
    assert refused == (1, [f"land_fail:changed:{GONE}"]), f"{LAND}: {refused}"
    assert (src / GONE).read_bytes() == sibling_gone, (
        f"{LAND}: a refused land deleted the sibling's edit"
    )
    (src / GONE).unlink()
    assert rig.call("land", wt) == (0, ["land_ok:0:0:1"]), (
        f"{LAND}: a delete the source already made is not a refusal"
    )

    code, lines = rig.call("remove", wt)
    assert code == 0 and lines[-1:] == [f"worktree_removed:{wt.as_posix()}"], (
        f"{LAND}: remove exited {code} with {lines}"
    )


def test_sync_refuses_before_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-642.2 negatives — repeated sibling edits, and every sync refusal."""
    rig = _rig(tmp_path, monkeypatch, capsys, LAND)
    src = rig.src
    wt = rig.create_carried(LAND, "gt6-a")
    ref = f"{REF_PREFIX}gt6-a"
    executor = b"MEU-4: executor\n"

    # Each sibling edit after a sync is refused again until it is synced too.
    first = STATUS_MODIFIED + b"MEU-3: sibling\n"
    (src / STATUS).write_bytes(first)
    (wt / STATUS).write_bytes(STATUS_MODIFIED + executor)
    changed = (1, [f"land_fail:changed:{STATUS}"])
    assert rig.call("land", wt) == changed, f"{LAND}: first sibling edit"
    assert rig.call("sync", wt, STATUS) == (0, [f"sync_ok:{STATUS}"]), f"{LAND}: sync"
    (wt / STATUS).write_bytes(first + executor)
    second = first + b"MEU-5: sibling again\n"
    (src / STATUS).write_bytes(second)
    assert rig.call("land", wt) == changed, f"{LAND}: second sibling edit after sync"
    assert (src / STATUS).read_bytes() == second, f"{LAND}: a refused land wrote"
    assert rig.call("sync", wt, STATUS) == (0, [f"sync_ok:{STATUS}"]), f"{LAND}: sync"
    assert (wt / STATUS).read_bytes() == second, f"{LAND}: the second sync's bytes"
    (wt / STATUS).write_bytes(second + executor)
    assert rig.call("land", wt) == (0, ["land_ok:0:1:0"]), f"{LAND}: final land"
    assert _lf((src / STATUS).read_bytes()) == second + executor, (
        f"{LAND}: the source does not hold all three edits"
    )

    _write(
        src,
        {
            "docs/fresh.md": b"fresh\r\n",
            "brandnew/Foo.md": b"foo\n",
            "docs/dir.md/inner.txt": b"a directory named like a file\n",
        },
    )
    (src / KEEP).write_bytes(b"a sibling edit\n")
    source_before, worktree_before = _snapshot(src), _snapshot(wt)
    baseline = _ref(src, "gt6-a")
    cases: tuple[tuple[tuple[str, ...], list[str]], ...] = (
        ((".env",), ["sync_fail:ignored:.env"]),
        ((NODE_FILE,), [f"sync_fail:ignored:{NODE_FILE}"]),
        # A second spelling of a baseline file, then of a baseline directory.
        (("docs/guide.md",), ["sync_fail:case:docs/guide.md"]),
        (("Docs/fresh.md",), ["sync_fail:case:Docs/fresh.md"]),
        # Two spellings inside one batch, of a file and then of a directory,
        # where the baseline knows neither: the first spelling given wins.
        (("brandnew/Foo.md", "brandnew/foo.md"), ["sync_fail:case:brandnew/foo.md"]),
        (("BrandNew/a.md", "brandnew/Foo.md"), ["sync_fail:case:brandnew/Foo.md"]),
        (("docs/dir.md",), ["sync_fail:shape:docs/dir.md"]),
        # One refusal stops the whole batch, the syncable path included.
        (
            (KEEP, ".env", "docs/guide.md"),
            ["sync_fail:ignored:.env", "sync_fail:case:docs/guide.md"],
        ),
    )
    for rels, want in cases:
        got = rig.call("sync", wt, *rels)
        assert got == (1, want), f"{LAND}: sync {rels}: {got}"
        assert _snapshot(src) == source_before, f"{LAND}: sync {rels} wrote the source"
        assert _snapshot(wt) == worktree_before, (
            f"{LAND}: sync {rels} wrote the worktree"
        )
        assert _ref(src, "gt6-a") == baseline, f"{LAND}: sync {rels} moved the ref"

    for bad in ("../outside.md", str(src / KEEP)):
        with pytest.raises(SystemExit) as usage:
            rig.call("sync", wt, bad)
        assert usage.value.code == 2, f"{LAND}: sync {bad!r} exited {usage.value.code}"
    assert _snapshot(wt) == worktree_before, f"{LAND}: a usage error wrote"
    assert _ref(src, "gt6-a") == baseline, f"{LAND}: a usage error moved the ref"

    got = rig.call("sync", wt, "docs/fresh.md", KEEP, "docs/fresh.md")
    assert got == (0, ["sync_ok:docs/fresh.md", f"sync_ok:{KEEP}"]), f"{LAND}: {got}"
    assert (wt / "docs/fresh.md").read_bytes() == b"fresh\n", (
        f"{LAND}: sync did not write the new file with LF"
    )
    assert (wt / KEEP).read_bytes() == b"a sibling edit\n", f"{LAND}: {KEEP} not synced"
    assert _snapshot(src) == source_before, f"{LAND}: sync wrote the source"
    synced = _tree_map(src, ref)
    assert synced["docs/fresh.md"] == _blob(src, "docs/fresh.md", b"fresh\r\n"), (
        f"{LAND}: the baseline does not hold the synced new file"
    )
    assert synced[KEEP] == _blob(src, KEEP, b"a sibling edit\n"), (
        f"{LAND}: the baseline does not hold the synced edit"
    )
    assert not (_git_dir(wt) / TEMP_INDEX_NAME).exists(), (
        f"{LAND}: sync left its temporary index behind"
    )
    assert rig.call("land", wt) == (0, ["land_ok:0:0:0"]), (
        f"{LAND}: synced files are not changes to land"
    )


def test_capture_never_records_links(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-642.2 — a link no ignore rule matches still never enters a tree."""
    rig = _rig(tmp_path, monkeypatch, capsys, LAND)
    src = rig.src
    wt = rig.create(LAND, "gt6-a")
    ref = f"{REF_PREFIX}gt6-a"

    rules = SEED_TRACKED[".gitignore"].replace(b"node_modules\n", b"")
    assert rules != SEED_TRACKED[".gitignore"], f"{LAND}: rig has no node_modules rule"
    (wt / ".gitignore").write_bytes(rules)
    assert _git(wt, "status", "--porcelain", "--", "node_modules") != "", (
        f"{LAND}: rig: git still ignores the link"
    )

    assert rig.call("land", wt) == (0, ["land_ok:0:1:0"]), (
        f"{LAND}: an unignored link landed as more than the .gitignore edit"
    )
    recorded = [
        rel
        for rel in _tree_map(src, ref)
        if rel == "node_modules" or rel.startswith("node_modules/")
    ]
    assert not recorded, f"{LAND}: the baseline recorded the link: {recorded}"
    assert _lf((src / ".gitignore").read_bytes()) == rules, f"{LAND}: .gitignore"

    code, lines = rig.call("remove", wt)
    assert code == 0 and lines[-1:] == [f"worktree_removed:{wt.as_posix()}"], (
        f"{LAND}: remove exited {code} with {lines}"
    )
    assert (src / NODE_FILE).read_bytes() == SEED_LOCAL[NODE_FILE], (
        f"{LAND}: remove deleted the source's node_modules contents"
    )


# IT8-8 MEU-659 (EOL_PIN, ATOMIC_WRITE_CLEANUP): red first (G19). The source
# keeps local core.autocrlf=false and its own .gitattributes, so the result
# does not depend on the repository's own rules.
_IT8_8_ATTRS = b"*.raw -text\n"
_IT8_8_EDITED = "docs/edited.md"
_IT8_8_CARRIED = "docs/carried.md"
_IT8_8_RAW = "bin/blob.raw"
_IT8_8_TRACKED: dict[str, bytes] = {
    **SEED_TRACKED,
    ".gitattributes": _IT8_8_ATTRS,
    _IT8_8_EDITED: b"one\ntwo\n",
    _IT8_8_CARRIED: b"carry one\ncarry two\n",
    _IT8_8_RAW: b"raw one\nraw two\n",
}


def _it8_8_rig(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    marker: str,
) -> Rig:
    """The ``_rig`` source, built with local ``core.autocrlf=false``."""
    tool = _tool(marker)
    vc = tool
    src = tmp_path / "repo"
    src.mkdir()
    _git(src, "init", "-q", "-b", "main")
    _git(src, "config", "core.autocrlf", "false")
    _write(src, _IT8_8_TRACKED)
    _git(src, "add", "-A")
    _git(src, "add", "-f", SETTINGS)
    _git(src, "commit", "-q", "--no-verify", "-m", "seed")
    _write(src, SEED_LOCAL)
    (src / STATUS).write_bytes(STATUS_MODIFIED)
    rig = Rig(tool=tool, vc=vc, src=src, scratch=tmp_path, capsys=capsys)

    def fake_venv(path: Path) -> int:
        rig.venvs.append(Path(path))
        _write(Path(path), {".venv/pyvenv.cfg": b"home = stub\n"})
        return 0

    monkeypatch.setattr(tool, "_build_venv", fake_venv)
    return rig


def _it8_8_rev(repo: Path, spec: str) -> str:
    return _git(repo, "rev-parse", spec).strip()


def test_it8_8_ac_659_4_a_land_ignores_a_crlf_rewrite_on_the_main_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rig = _it8_8_rig(tmp_path, monkeypatch, capsys, "AC-659.4")
    src = rig.src
    wt = rig.create_carried("AC-659.4", "it8-8-a")
    (wt / _IT8_8_EDITED).write_bytes(b"one\ntwo\nthree\n")
    (src / _IT8_8_EDITED).write_bytes(b"one\r\ntwo\r\n")
    assert rig.call("land", wt) == (0, ["land_ok:0:1:0"]), (
        "AC-659.4(a): a CRLF-only rewrite on the main tree refused the land"
    )
    assert (src / _IT8_8_EDITED).read_bytes() == b"one\ntwo\nthree\n", (
        "AC-659.4(a): the main path does not hold the worktree's edited bytes"
    )


def test_it8_8_ac_659_4_b_a_carried_crlf_copy_keeps_the_lf_blob(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rig = _it8_8_rig(tmp_path, monkeypatch, capsys, "AC-659.4")
    src = rig.src
    crlf = b"carry one\r\ncarry two\r\n"
    (src / _IT8_8_CARRIED).write_bytes(crlf)
    wt = rig.create(
        "AC-659.4",
        "it8-8-b",
        "--carry",
        PLAN_DIR,
        "--carry",
        STATUS,
        "--carry",
        _IT8_8_CARRIED,
    )
    head = _it8_8_rev(src, f"HEAD:{_IT8_8_CARRIED}")
    baseline = _it8_8_rev(src, f"{REF_PREFIX}it8-8-b:{_IT8_8_CARRIED}")
    assert baseline == head, (
        f"AC-659.4(b): the carried CRLF copy entered the baseline as {baseline}, "
        f"not the LF blob {head}"
    )
    assert rig.call("land", wt) == (0, ["land_ok:0:0:0"]), (
        "AC-659.4(b): the carried CRLF copy landed as a change"
    )
    assert (src / _IT8_8_CARRIED).read_bytes() == crlf, (
        "AC-659.4(b): land rewrote the carried file"
    )


def test_it8_8_ac_659_4_c_crlf_blobs_and_minus_text_paths_are_preserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rig = _it8_8_rig(tmp_path, monkeypatch, capsys, "AC-659.4")
    src = rig.src
    wt = rig.create_carried("AC-659.4", "it8-8-c")
    head_module = _it8_8_rev(src, f"HEAD:{MODULE}")
    assert b"\r" in _git_proc(src, "cat-file", "blob", head_module).stdout, (
        "AC-659.4(c) rig: the committed module blob holds no CR"
    )
    assert _it8_8_rev(src, f"{REF_PREFIX}it8-8-c:{MODULE}") == head_module, (
        "AC-659.4(c): _tree_of changed the committed CRLF blob id"
    )
    assert rig.tool._main_blob(src, MODULE) == head_module, (
        "AC-659.4(c): _main_blob changed the committed CRLF blob id"
    )
    raw = b"raw one\r\nraw two\r\n"
    (wt / _IT8_8_RAW).write_bytes(raw)
    want = _git(wt, "hash-object", "--no-filters", _IT8_8_RAW).strip()
    assert rig.call("land", wt) == (0, ["land_ok:0:1:0"]), (
        "AC-659.4(c): the -text edit did not land"
    )
    assert _it8_8_rev(src, f"{REF_PREFIX}it8-8-c:{_IT8_8_RAW}") == want, (
        "AC-659.4(c): the -text path was not stored byte for byte"
    )
    assert (src / _IT8_8_RAW).read_bytes() == raw, (
        "AC-659.4(c): the main -text path does not hold the CRLF bytes"
    )
    assert rig.tool._main_blob(src, _IT8_8_RAW) == want, (
        "AC-659.4(c): _main_blob converted the -text path"
    )


def _it8_8_verb(elements: list[Any]) -> tuple[str | None, bool]:
    """The git verb of a literal argument list, and whether ``*EOL_PIN`` precedes it."""
    import ast

    pinned = False
    index = 0
    while index < len(elements):
        element = elements[index]
        if isinstance(element, ast.Starred):
            value = element.value
            pinned = pinned or (isinstance(value, ast.Name) and value.id == "EOL_PIN")
            index += 1
            continue
        if not (isinstance(element, ast.Constant) and isinstance(element.value, str)):
            return None, pinned
        word = element.value
        if word == "git" and index == 0:
            index += 1
        elif word == "-c":
            index += 2
        elif word.startswith("-"):
            index += 1
        else:
            return word, pinned
    return None, pinned


def test_it8_8_ac_659_5_every_hashing_git_call_carries_eol_pin() -> None:
    import ast

    tool = _tool("AC-659.5")
    tree = ast.parse(Path(tool.__file__).read_text(encoding="utf-8"))
    sites: list[tuple[int, str, bool]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple)):
            verb, pinned = _it8_8_verb(list(node.elts))
            if verb in ("hash-object", "add"):
                sites.append((node.lineno, verb, pinned))
    assert len(sites) >= 3, f"AC-659.5: found {len(sites)} hashing git calls: {sites}"
    bare = [f"{verb}@{line}" for line, verb, pinned in sites if not pinned]
    assert not bare, f"AC-659.5: hashing git calls without *EOL_PIN: {bare}"


@pytest.mark.skipif(
    sys.platform != "win32", reason="AC-659.6: a read-only scratch file blocks unlink"
)
def test_it8_8_ac_659_6_atomic_write_cleanup_keeps_the_replace_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import stat

    tool = _tool("AC-659.6")
    target = tmp_path / "ro" / "target.txt"
    target.parent.mkdir()
    target.write_bytes(b"old\n")
    os.chmod(target, stat.S_IREAD)

    def scratch_files() -> list[Path]:
        return sorted(target.parent.glob("*.executor-write.tmp"))

    first = PermissionError(13, "AC-659.6 replace refused")
    second = PermissionError(13, "AC-659.6 replace refused again")
    unlink_error = OSError(5, "AC-659.6 unlink refused")

    def refuse(error: BaseException) -> Any:
        def raiser(*_args: object, **_kwargs: object) -> None:
            raise error

        return raiser

    try:
        with monkeypatch.context() as patch:
            patch.setattr(tool.os, "replace", refuse(first))
            with pytest.raises(PermissionError) as raised:
                tool._atomic_write(target, b"new\n")
        assert raised.value is first, (
            f"AC-659.6: _atomic_write raised {raised.value!r}, not the replace error"
        )
        assert not scratch_files(), (
            f"AC-659.6: the scratch file stayed: {[p.name for p in scratch_files()]}"
        )

        with monkeypatch.context() as patch:
            patch.setattr(tool.os, "replace", refuse(second))
            patch.setattr(tool.os, "unlink", refuse(unlink_error))
            with pytest.raises(PermissionError) as raised:
                tool._atomic_write(target, b"new\n")
        assert raised.value is second, (
            f"AC-659.6: the unlink error replaced the replace error: {raised.value!r}"
        )
        left = scratch_files()
        notes = getattr(raised.value, "__notes__", [])
        assert left and any(str(left[-1]) in note for note in notes), (
            f"AC-659.6: no note names the scratch path {left}: {notes}"
        )
    finally:
        for path in scratch_files():
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            path.unlink()
        os.chmod(target, stat.S_IWRITE | stat.S_IREAD)


# 659-PR (advisory peer read F1-F3): ``_added_blob`` must store what a pinned
# ``git add -f`` stores. The oracle runs that ``add`` in a copy of the index.
def _it8_8_git_add_blob(repo: Path, rel: str, scratch: Path) -> str:
    """The blob a pinned ``git add -f`` stores for ``rel`` in a copy of the index."""
    index = scratch / f"oracle-{rel.replace('/', '-')}.index"
    shutil.copyfile(repo / ".git" / "index", index)
    env = {"GIT_INDEX_FILE": str(index)}
    pin = ("-c", "core.autocrlf=true", "-c", "core.safecrlf=false")
    _git(repo, *pin, "add", "-f", "--", rel, env=env)
    records = _git(repo, "ls-files", "--stage", "-z", "--", rel, env=env).split("\0")
    blobs = [r.split()[1] for r in records if r.split("\t", 1)[-1] == rel and r]
    assert len(blobs) == 1, f"659-PR oracle: {rel} has {len(blobs)} index entries"
    return blobs[0]


def _it8_8_symlink(link: Path, target: str) -> None:
    try:
        os.symlink(target, link)
    except OSError as error:
        pytest.skip(f"659-PR F3: this host cannot create a symlink: {error}")


def test_it8_8_ac_659_4_d_added_blob_reads_only_the_exact_index_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rig = _it8_8_rig(tmp_path, monkeypatch, capsys, "AC-659.4")
    src = rig.src
    _write(src, {"it8nest/inner.txt": b"in one\r\nin two\r\n"})
    _git(src, "add", "--", "it8nest/inner.txt")
    shutil.rmtree(src / "it8nest")
    (src / "it8nest").write_bytes(b"top one\r\ntop two\r\n")
    want = _it8_8_git_add_blob(src, "it8nest", tmp_path)
    got = rig.tool._added_blob(src, "it8nest", write=False)
    assert got == want, (
        f"659-PR F1: _added_blob read a directory entry's CRLF for a file: "
        f"{got}, want {want}"
    )


def test_it8_8_ac_659_4_e_added_blob_reads_ours_in_a_conflicted_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rig = _it8_8_rig(tmp_path, monkeypatch, capsys, "AC-659.4")
    src = rig.src
    rel = "docs/conflict.md"
    stages = (
        (1, b"base one\nbase two\n"),
        (2, b"ours one\r\nours two\r\n"),
        (3, b"theirs one\ntheirs two\n"),
    )
    info = ""
    for stage, body in stages:
        blob = _git(src, "hash-object", "-w", "--stdin", data=body).strip()
        info += f"100644 {blob} {stage}\t{rel}\n"
    _git(src, "update-index", "--index-info", data=info.encode("utf-8"))
    (src / rel).write_bytes(b"merged one\r\nmerged two\r\n")
    want = _it8_8_git_add_blob(src, rel, tmp_path)
    got = rig.tool._added_blob(src, rel, write=False)
    assert got == want, (
        f"659-PR F2: _added_blob did not read stage 2 (ours): {got}, want {want}"
    )


def test_it8_8_ac_659_4_f_added_blob_hashes_a_link_as_git_add_does(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rig = _it8_8_rig(tmp_path, monkeypatch, capsys, "AC-659.4")
    src = rig.src
    tracked = "docs/tracked-link.md"
    loose = "docs/loose-link.md"
    dangling = "docs/dangling-link.md"
    _it8_8_symlink(src / tracked, "edited.md")
    _git(src, "add", "--", tracked)
    _it8_8_symlink(src / loose, "edited.md")
    _it8_8_symlink(src / dangling, "missing.md")
    wrong = []
    for rel in (tracked, loose, dangling):
        want = _it8_8_git_add_blob(src, rel, tmp_path)
        try:
            got = rig.tool._added_blob(src, rel, write=False)
        except OSError as error:
            got = f"raised {error!r}"
        if got != want:
            wrong.append(f"{rel}: {got}, want {want}")
    assert not wrong, f"659-PR F3: _added_blob followed a link: {wrong}"


def test_it8_8_ac_659_4_g_sync_refuses_a_link_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rig = _it8_8_rig(tmp_path, monkeypatch, capsys, "AC-659.4")
    src = rig.src
    wt = rig.create_carried("AC-659.4", "it8-8-g")
    rel = "docs/sync-link.md"
    _it8_8_symlink(src / rel, "edited.md")
    worktree_before = _snapshot(wt)
    baseline = _ref(src, "it8-8-g")
    got = rig.call("sync", wt, rel)
    assert got == (1, [f"sync_fail:shape:{rel}"]), (
        f"659-PR F3: sync of a link source was not refused as a shape: {got}"
    )
    assert _snapshot(wt) == worktree_before, "659-PR F3: the refused sync wrote"
    assert _ref(src, "it8-8-g") == baseline, "659-PR F3: the refused sync moved the ref"


# IT8-14 MEU-699 (PY_PIN_WORKTREE, KI PY-INTERPRETER-UNPINNED-WORKTREE-SPLIT):
# red first (G19). A worktree's venv runs the main tree's interpreter version.
_IT8_14_PIN = "PY_PIN_WORKTREE"
_IT8_14_PIN_REFUSAL = ["worktree_bad:python_pin"]


def _it8_14_need(tool: Any, name: str) -> Any:
    """``tool.<name>``, asserted present before any call (RED_SHAPE)."""
    found = getattr(tool, name, None)
    assert found is not None, f"{_IT8_14_PIN}: executor_worktree defines no {name}"
    return found


def _it8_14_main_with_cfg(root: Path, cfg: bytes | None) -> Path:
    """A main-tree stand-in whose ``.venv/pyvenv.cfg`` holds ``cfg`` (None: absent)."""
    root.mkdir(parents=True)
    if cfg is not None:
        _write(root, {".venv/pyvenv.cfg": cfg})
    return root


def _it8_14_same_path(left: Path | str, right: Path | str) -> bool:
    return os.path.normcase(str(Path(left).resolve())) == os.path.normcase(
        str(Path(right).resolve())
    )


def test_it8_14_ac_699_1_pinned_python_reads_the_main_venv_version(
    tmp_path: Path,
) -> None:
    """AC-699.1 — X.Y.Z from ``version_info``; a missing or bad value refuses."""
    tool = _tool(_IT8_14_PIN)
    pinned_python = _it8_14_need(tool, "_pinned_python")
    for name, cfg in (
        ("full", b"home = C:/py\nversion_info = 3.12.12.final.0\n"),
        ("short", b"home = C:/py\nimplementation = CPython\nversion_info = 3.12.12\n"),
    ):
        root = _it8_14_main_with_cfg(tmp_path / name, cfg)
        got = pinned_python(root)
        assert got == "3.12.12", f"{_IT8_14_PIN}: {name} cfg gave {got!r}"
    for name, cfg in (
        ("missing", None),
        ("no-key", b"home = C:/py\nversion = 3.12.12\n"),
        ("malformed", b"home = C:/py\nversion_info = 3.x\n"),
    ):
        root = _it8_14_main_with_cfg(tmp_path / name, cfg)
        with pytest.raises(tool._Refusal) as caught:
            pinned_python(root)
        assert caught.value.lines == _IT8_14_PIN_REFUSAL, (
            f"{_IT8_14_PIN}: {name} cfg refused with {caught.value.lines}"
        )


def test_it8_14_ac_699_2_build_venv_passes_the_main_tree_python(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-699.2 — uv sync gets ``--python <main X.Y.Z>`` and no venv override."""
    tool = _tool(_IT8_14_PIN)
    main_root_of = _it8_14_need(tool, "_main_root_of")
    _it8_14_need(tool, "_pinned_python")

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _write(repo, {"seed.txt": b"seed\n"})
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--no-verify", "-m", "seed")
    linked = tmp_path / "repo-linked"
    _git(repo, "worktree", "add", "-q", "--detach", str(linked), "HEAD")
    got_root = main_root_of(linked)
    assert _it8_14_same_path(got_root, repo), (
        f"{_IT8_14_PIN}: _main_root_of({linked}) gave {got_root}, want {repo}"
    )
    assert _it8_14_same_path(main_root_of(repo), repo), (
        f"{_IT8_14_PIN}: _main_root_of of the main tree is not the main tree"
    )

    main = _it8_14_main_with_cfg(
        tmp_path / "main", b"home = C:/py\nversion_info = 3.12.12\n"
    )
    # The uv command is adopter config in the framework (AC-J.2).
    _write(main, {CONFIG: CONFIG_BYTES})
    uv_sync = json.loads(CONFIG_BYTES)["venv_build"]
    worktree = tmp_path / "main-wt"
    worktree.mkdir()
    monkeypatch.setattr(tool, "_main_root_of", lambda path: main)
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "foreign-venv"))
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(tmp_path / "foreign-env"))
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def fake_run(argv: Any, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(([str(a) for a in argv], kwargs))
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(tool.subprocess, "run", fake_run)
    code = tool._build_venv(worktree)
    monkeypatch.undo()
    assert code == 0, f"{_IT8_14_PIN}: _build_venv returned {code}"
    assert len(calls) == 1, f"{_IT8_14_PIN}: _build_venv ran {len(calls)} processes"
    argv, kwargs = calls[0]
    want = [*uv_sync, "--python", "3.12.12"]
    assert argv == want, f"{_IT8_14_PIN}: uv argv {argv}, want {want}"
    env = kwargs.get("env") or {}
    leaked = sorted(
        name for name in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT") if name in env
    )
    assert not leaked, f"{_IT8_14_PIN}: uv sync inherited {leaked}"
    assert _it8_14_same_path(kwargs.get("cwd", ""), worktree), (
        f"{_IT8_14_PIN}: uv sync ran in {kwargs.get('cwd')!r}, not the worktree"
    )


def test_it8_14_ac_699_3_a_pin_refusal_tears_the_create_down(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-699.3 — a ``python_pin`` refusal prints the reason and leaves nothing."""
    rig = _rig(tmp_path, monkeypatch, capsys, _IT8_14_PIN)
    tool = rig.tool
    listing = _git(rig.src, "worktree", "list", "--porcelain")

    def refuse(path: Path) -> int:
        raise tool._Refusal(list(_IT8_14_PIN_REFUSAL))

    monkeypatch.setattr(tool, "_build_venv", refuse)
    got = rig.call("create", "it8-14-pin")
    assert got == (1, _IT8_14_PIN_REFUSAL), f"{_IT8_14_PIN}: create gave {got}"
    _torn_down(rig, _IT8_14_PIN, "it8-14-pin", "python_pin refusal")
    assert _git(rig.src, "worktree", "list", "--porcelain") == listing, (
        f"{_IT8_14_PIN}: the refused create changed git's worktree list"
    )
