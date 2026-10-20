"""B-8 worktree layout and guarded cleanup — red first (G19).

FIC: ``the run-parameters design plan/implementation-plan.md`` Component G
(AC-G.1 to AC-G.4; R§6 D-18, R§7 ``executor_worktree.py`` row, R§8 B-8; EA-28).

The contract these tests fix:

* ``create <slug>`` builds ``WORKTREE_PARENT/<slug>`` (``{{PROJECT_ROOT}}-wt``, a module constant
  with no CLI flag and no environment override); the commit-candidate root is
  ``WORKTREE_PARENT/.candidates`` (``candidate_root()``), the default ``commit_batch`` names.
  ``create`` takes ``--run-id``, ``--op`` and ``--plan`` together (``worktree_bad:identity``
  otherwise) and writes them to the manifest as ``run_id``, ``op_id`` and ``plan``.
  ``legacy_worktree_path`` is the old ``<root>-<slug>`` sibling; ``slug_taken`` is true when
  either folder exists (the τ3 ``path_free`` fact reads it).
* ``contained(path)``: a registered path (the module set ``GRANDFATHERED``, matched by the
  given path, never by resolving it) or a path whose physical location (links resolved) is
  strictly inside the parent. ``remove`` refuses any other worktree with
  ``worktree_bad:containment``.
* ``remove <path>`` on an executor worktree refuses the current directory or an ancestor of
  it (``worktree_bad:cwd``) and a path a process holds (``worktree_bad:held:<pid>``, one line
  per process; no process is ever terminated, because no record proves ownership). A
  manifest with ``run_id`` and ``plan`` gets the H2-3c records through
  ``run_parameters.record_removal`` (``worktree_removal_started`` before the removal,
  ``worktree_removed`` after it); a store refusal is ``worktree_bad:record:<reason>`` with
  nothing removed.
* ``remove <path> --ad-hoc`` is the guarded plain-git route for a listed worktree with no
  manifest of either kind: the main worktree → ``worktree_bad:main``, a managed one →
  ``worktree_bad:managed``, then cwd, containment, a tracked change
  (``worktree_bad:dirty:<rel>``), an untracked or ignored file (``worktree_bad:unknown:<rel>``)
  and a holding process, in that order; ``--ad-hoc`` with ``--discard`` is a usage error.
  Without ``--ad-hoc`` such a worktree stays ``worktree_bad:manifest``.

The tool's ``main()`` runs in-process against a real temp git repository, with only the
venv step replaced. The rig is local to this file. Do not skip, only, or early-return (G36).
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_NAME = "executor-worktree.json"
REAL_PARENT = "{{PROJECT_ROOT}}-wt"
# The framework ships no grandfathered lane; an adopter lists its pre-layout lanes in
# ``executor_worktree.GRANDFATHERED``. These are the lanes the AC-G.2 test registers.
REGISTERED = (
    "{{PROJECT_ROOT}}-lane-a",
    "{{PROJECT_ROOT}}-lane-b",
)
# The adopter config the tool reads from the main tree (a missing one refuses
# ``worktree_bad:config``). ``venv_build`` runs the rig's stub, never ``uv``.
SEED: dict[str, bytes] = {
    ".gitignore": b".venv/\n*.log\n",
    "README.md": b"# fixture\n",
    "pkg/mod.py": b"A = 1\n",
    ".agent/credits/worktree.json": (
        b'{"env_files": [], "frozen_dirs": [], '
        b'"venv_build": ["uv", "sync"], "linked_trees": []}\n'
    ),
}
_GIT_ENV_DROPPED = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")
SLEEPER = "import time; time.sleep(120)"


def _tool() -> Any:
    return importlib.import_module("tools.executor_worktree")


def _git_proc(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    merged = {k: v for k, v in os.environ.items() if k not in _GIT_ENV_DROPPED}
    argv = [
        "git",
        "-c",
        "user.name=b8",
        "-c",
        "user.email=b8@example.invalid",
        "-c",
        "commit.gpgsign=false",
        *args,
    ]
    return subprocess.run(
        argv,
        cwd=repo,
        stdin=subprocess.DEVNULL,
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
    src = tmp_path / "repo"
    src.mkdir()
    _git(src, "init", "-q", "-b", "main")
    _git(src, "config", "core.autocrlf", "false")
    _write(src, SEED)
    _git(src, "add", "-A")
    _git(src, "commit", "-q", "--no-verify", "-m", "seed")
    return src


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


def _link(link: Path, target: Path) -> None:
    importlib.import_module("tools.tests.run_parameters_fixtures.phase_b8")._make_dir_link(link, target)


def _unlink(link: Path) -> None:
    importlib.import_module("tools.tests.run_parameters_fixtures.phase_b8")._drop_dir_link(link)


def _sleeper(cwd: Path) -> subprocess.Popen[bytes]:
    """A process whose working directory is ``cwd`` (the base interpreter: no launcher)."""
    exe = getattr(sys, "_base_executable", sys.executable)
    return subprocess.Popen([exe, "-c", SLEEPER], cwd=cwd)


def _stop(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is None:
        proc.kill()
    proc.wait(timeout=30)


@dataclass
class Rig:
    """One source repository, the tool, its parent and its captured stdout."""

    tool: Any
    src: Path
    parent: Path
    capsys: pytest.CaptureFixture[str]
    venvs: list[Path] = field(default_factory=list)

    def call(self, *argv: object) -> tuple[int, list[str]]:
        self.capsys.readouterr()
        try:
            code = self.tool.main(["--root", str(self.src), *[str(a) for a in argv]])
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 2
        return code, self.capsys.readouterr().out.splitlines()

    def create(self, marker: str, slug: str, *extra: str) -> Path:
        code, lines = self.call("create", slug, *extra)
        wt = self.parent / slug
        assert code == 0 and lines[-1:] == [f"worktree_ready:{wt.as_posix()}"], (
            f"{marker}: create {slug} exited {code} with {lines}"
        )
        return wt

    def ad_hoc(self, path: Path) -> Path:
        """A listed worktree made by plain git: no manifest of either kind."""
        _git(self.src, "worktree", "add", "--detach", str(path), "HEAD")
        assert _listed(self.src, path), f"rig: git does not list {path}"
        return path


def _rig(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    registered: tuple[Path, ...] = (),
) -> Rig:
    tool = _tool()
    monkeypatch.delenv("CREDITS_BASE_COMMIT", raising=False)
    parent = tmp_path / "wt"
    monkeypatch.setattr(tool, "WORKTREE_PARENT", parent, raising=False)
    monkeypatch.setattr(
        tool,
        "GRANDFATHERED",
        frozenset(path.as_posix() for path in registered),
        raising=False,
    )
    rig = Rig(tool=tool, src=_build_source(tmp_path), parent=parent, capsys=capsys)

    def fake_venv(path: Path) -> int:
        rig.venvs.append(Path(path))
        _write(Path(path), {".venv/pyvenv.cfg": b"home = stub\n"})
        return 0

    monkeypatch.setattr(tool, "_build_venv", fake_venv)
    monkeypatch.chdir(tmp_path)
    return rig


def test_vec_v8_001_g1_the_parent_is_a_fixed_module_constant() -> None:
    """AC-G.1 — ``WORKTREE_PARENT`` is ``{{PROJECT_ROOT}}-wt``; no flag; candidates beneath it."""
    tool = _tool()
    assert Path(tool.WORKTREE_PARENT).as_posix() == REAL_PARENT, tool.WORKTREE_PARENT
    assert tool.candidate_root() == Path(REAL_PARENT) / ".candidates"
    batch = importlib.import_module("tools.commit_batch")
    assert batch.DEFAULT_CANDIDATE_ROOT == tool.candidate_root().as_posix()
    with pytest.raises(SystemExit) as info:
        tool._parser().parse_args(["create", "rp-x", "--parent", "C:/elsewhere"])
    assert info.value.code == 2, "create takes no parent flag"
    src = Path("{{PROJECT_ROOT}}")
    assert tool.worktree_path(src, "rp-x") == Path(REAL_PARENT) / "rp-x"
    assert tool.legacy_worktree_path(src, "rp-x") == Path("{{PROJECT_ROOT}}-rp-x")


def test_vec_v8_001_g1_create_places_the_worktree_under_the_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-G.1 — ``create <slug>`` → ``<parent>/<slug>``; outside slugs refused; identity."""
    rig = _rig(tmp_path, monkeypatch, capsys)
    src, tool = rig.src, rig.tool
    assert not rig.parent.exists(), "rig: the parent exists before the first create"
    assert tool.candidate_root() == rig.parent / ".candidates"
    assert not tool.slug_taken(src, "rp-a")

    wt = rig.create("AC-G.1", "rp-a")
    assert wt.is_dir() and _listed(src, wt), f"AC-G.1: {wt} is not a listed worktree"
    assert not os.path.lexists(src.parent / "repo-rp-a"), "AC-G.1: sibling folder made"
    assert tool.slug_taken(src, "rp-a"), "AC-G.1: slug_taken misses the new folder"
    manifest = json.loads((_git_dir(wt) / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert not {"run_id", "op_id", "plan"} & set(manifest), sorted(manifest)

    legacy = tool.legacy_worktree_path(src, "rp-old")
    assert legacy == src.parent / "repo-rp-old"
    legacy.mkdir()
    assert tool.slug_taken(src, "rp-old"), (
        "AC-G.1: slug_taken misses the legacy sibling"
    )

    before = sorted(p.name for p in tmp_path.iterdir())
    for slug in ("..", "../rp-x", "..\\rp-x", "c:rp-x", "C:/rp-x", "/rp-x"):
        got = rig.call("create", slug)
        assert got == (1, ["worktree_bad:slug"]), f"AC-G.1: slug {slug!r}: {got}"
    assert sorted(p.name for p in tmp_path.iterdir()) == before, (
        "AC-G.1: a refusal made a folder"
    )
    assert sorted(p.name for p in rig.parent.iterdir()) == ["rp-a"]

    ident = rig.create(
        "AC-G.1", "rp-id", "--run-id", "run-1", "--op", "op-1", "--plan", "plan-x"
    )
    manifest = json.loads((_git_dir(ident) / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert (manifest["run_id"], manifest["op_id"], manifest["plan"]) == (
        "run-1",
        "op-1",
        "plan-x",
    ), manifest
    for extra in (
        ("--run-id", "run-2"),
        ("--run-id", "run-2", "--op", "op-2"),
        ("--run-id", "../run", "--op", "op-2", "--plan", "plan-x"),
        ("--run-id", "run-2", "--op", "op 2", "--plan", "plan-x"),
    ):
        got = rig.call("create", "rp-bad", *extra)
        assert got == (1, ["worktree_bad:identity"]), f"AC-G.1: {extra}: {got}"
        assert not os.path.lexists(rig.parent / "rp-bad"), (
            f"AC-G.1: {extra} made a folder"
        )


def test_vec_v8_003_g2_registered_paths_pass_by_registration_never_by_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-G.2 — the shipped set is empty; each registered lane is contained; renames and others are not."""
    tool = _tool()
    assert tool.GRANDFATHERED == frozenset(), sorted(tool.GRANDFATHERED)
    monkeypatch.setattr(tool, "GRANDFATHERED", frozenset(REGISTERED))
    for path in REGISTERED:
        assert tool.contained(Path(path)), f"AC-G.2: registered {path} refused"
    for path in (
        "{{PROJECT_ROOT}}-unregistered",
        "{{PROJECT_ROOT}}-lane-a-renamed",
        "X:/qf1-commit-wt2",
        REAL_PARENT,
        "{{PROJECT_ROOT}}",
    ):
        assert not tool.contained(Path(path)), f"AC-G.2: {path} passed containment"
    assert tool.contained(Path(REAL_PARENT) / "rp-x")
    assert tool.contained(Path(REAL_PARENT) / ".candidates" / "op-1")


def test_vec_v8_005_g2_grandfathered_worktree_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-G.2 — outside the parent: refused unless registered; an alias or a rename is not."""
    lanes = tmp_path / "lanes"
    lanes.mkdir()
    lane_a, lane_b = lanes / "lane-a", lanes / "lane-b"
    rig = _rig(tmp_path, monkeypatch, capsys)
    src, tool = rig.src, rig.tool

    first = rig.create("AC-G.2", "rp-ga")
    _git(src, "worktree", "move", str(first), str(lane_a))
    got = rig.call("remove", lane_a)
    assert got == (1, ["worktree_bad:containment"]), f"AC-G.2: unregistered: {got}"
    assert _listed(src, lane_a) and lane_a.is_dir(), "AC-G.2: the refusal removed it"

    monkeypatch.setattr(tool, "GRANDFATHERED", frozenset({lane_a.as_posix()}))
    alias = tmp_path / "alias-a"
    _link(alias, lane_a)
    try:
        got = rig.call("remove", alias)
        assert got == (1, ["worktree_bad:containment"]), f"AC-G.2: alias: {got}"
        assert _listed(src, lane_a), "AC-G.2: the alias removed the registered lane"
    finally:
        _unlink(alias)
    got = rig.call("remove", lane_a)
    assert got == (0, [f"worktree_removed:{lane_a.as_posix()}"]), f"AC-G.2: {got}"
    assert not _listed(src, lane_a) and not os.path.lexists(lane_a)

    second = rig.create("AC-G.2", "rp-gb")
    _git(src, "worktree", "move", str(second), str(lane_b))
    monkeypatch.setattr(tool, "GRANDFATHERED", frozenset({lane_b.as_posix()}))
    renamed = lanes / "lane-b2"
    _git(src, "worktree", "move", str(lane_b), str(renamed))
    got = rig.call("remove", renamed)
    assert got == (1, ["worktree_bad:containment"]), f"AC-G.2: renamed: {got}"
    assert _listed(src, renamed) and renamed.is_dir(), "AC-G.2: the rename was removed"


def test_vec_v8_004_g3_ad_hoc_route_guards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-G.3 — the plain-git route: cwd, containment, unknown files, holders; then removal."""
    rig = _rig(tmp_path, monkeypatch, capsys)
    src = rig.src
    adhoc = rig.ad_hoc(rig.parent / "adhoc")

    assert rig.call("remove", adhoc) == (1, ["worktree_bad:manifest"]), (
        "AC-G.3: without --ad-hoc a worktree with no manifest stays refused"
    )
    assert rig.call("remove", adhoc, "--ad-hoc", "--discard")[0] == 2
    assert rig.call("remove", src, "--ad-hoc") == (1, ["worktree_bad:main"])
    managed = rig.create("AC-G.3", "rp-m")
    assert rig.call("remove", managed, "--ad-hoc") == (1, ["worktree_bad:managed"])

    (adhoc / "sub").mkdir()
    for cwd in (adhoc, adhoc / "sub"):
        monkeypatch.chdir(cwd)
        got = rig.call("remove", adhoc, "--ad-hoc")
        assert got == (1, ["worktree_bad:cwd"]), f"AC-G.3: cwd {cwd}: {got}"
        assert _listed(src, adhoc), f"AC-G.3: cwd {cwd}: removed"
    monkeypatch.chdir(tmp_path)
    (adhoc / "sub").rmdir()

    for rel, data, reason in (
        ("README.md", b"# changed\n", "dirty"),
        ("stray.txt", b"untracked\n", "unknown"),
        ("run.log", b"ignored\n", "unknown"),
    ):
        target = adhoc / rel
        before = target.read_bytes() if target.exists() else None
        target.write_bytes(data)
        got = rig.call("remove", adhoc, "--ad-hoc")
        assert got == (1, [f"worktree_bad:{reason}:{rel}"]), f"AC-G.3: {rel}: {got}"
        assert target.read_bytes() == data and _listed(src, adhoc), f"AC-G.3: {rel}"
        if before is None:
            target.unlink()
        else:
            target.write_bytes(before)

    holder = _sleeper(adhoc)
    try:
        code, lines = rig.call("remove", adhoc, "--ad-hoc")
        assert code == 1 and f"worktree_bad:held:{holder.pid}" in lines, lines
        assert all(line.startswith("worktree_bad:held:") for line in lines), lines
        assert holder.poll() is None, "AC-G.3: a foreign process was terminated"
        assert _listed(src, adhoc), "AC-G.3: a held worktree was removed"
    finally:
        _stop(holder)

    outside = tmp_path / "outside"
    outside.mkdir()
    real = rig.ad_hoc(outside / "adhoc-x")
    hop = rig.parent / "hop"
    _link(hop, outside)
    try:
        got = rig.call("remove", hop / "adhoc-x", "--ad-hoc")
        assert got == (1, ["worktree_bad:containment"]), f"AC-G.3: via a link: {got}"
        got = rig.call("remove", real, "--ad-hoc")
        assert got == (1, ["worktree_bad:containment"]), f"AC-G.3: outside: {got}"
        assert _listed(src, real) and real.is_dir(), "AC-G.3: an outside path removed"
    finally:
        _unlink(hop)

    got = rig.call("remove", adhoc, "--ad-hoc")
    assert got == (0, [f"worktree_removed:{adhoc.as_posix()}"]), f"AC-G.3: {got}"
    assert not _listed(src, adhoc) and not os.path.lexists(adhoc)


def test_vec_v8_004_g3_managed_route_guards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-G.3 — ``remove <path>``: the cwd or an ancestor of it, and a holder, are refused."""
    rig = _rig(tmp_path, monkeypatch, capsys)
    src = rig.src
    wt = rig.create("AC-G.3", "rp-c")

    for cwd in (wt, wt / "pkg"):
        monkeypatch.chdir(cwd)
        for flags in ((), ("--discard",)):
            got = rig.call("remove", wt, *flags)
            assert got == (1, ["worktree_bad:cwd"]), f"AC-G.3: cwd {cwd} {flags}: {got}"
    monkeypatch.chdir(tmp_path)
    assert _listed(src, wt) and wt.is_dir(), "AC-G.3: a cwd refusal removed it"

    holder = _sleeper(wt / "pkg")
    try:
        code, lines = rig.call("remove", wt)
        assert code == 1 and f"worktree_bad:held:{holder.pid}" in lines, lines
        assert holder.poll() is None, "AC-G.3: a foreign process was terminated"
        assert _listed(src, wt), "AC-G.3: a held worktree was removed"
    finally:
        _stop(holder)
    got = rig.call("remove", wt)
    assert got == (0, [f"worktree_removed:{wt.as_posix()}"]), f"AC-G.3: {got}"


def test_vec_v8_005_g4_removal_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-G.4 — H2-3c: ``worktree_removal_started`` before, ``worktree_removed`` after."""
    rig = _rig(tmp_path, monkeypatch, capsys)
    src, tool = rig.src, rig.tool
    rp = tool._run_parameters()
    calls: list[dict[str, Any]] = []
    refuse: list[Exception] = []

    def spy(repo: Path, **kw: Any) -> dict[str, Any]:
        if refuse:
            raise refuse[0]
        wt = Path(kw["path"])
        calls.append({"repo": Path(repo), "exists": wt.is_dir(), **kw})
        return {"seq": len(calls), **kw}

    monkeypatch.setattr(rp, "record_removal", spy)
    ident = ("--run-id", "run-h", "--op", "op-h", "--plan", "plan-h")
    wt = rig.create("AC-G.4", "rp-h", *ident)
    digest = hashlib.sha256((_git_dir(wt) / MANIFEST_NAME).read_bytes()).hexdigest()
    got = rig.call("remove", wt)
    assert got == (0, [f"worktree_removed:{wt.as_posix()}"]), f"AC-G.4: {got}"
    assert [(c["event"], c["exists"]) for c in calls] == [
        ("worktree_removal_started", True),
        ("worktree_removed", False),
    ], calls
    for call in calls:
        assert os.path.samefile(call["repo"], src), call
        assert (call["plan"], call["run_id"], call["path"]) == (
            "plan-h",
            "run-h",
            wt.as_posix(),
        ), call
        assert (call["manifest_digest"], call["by"], call["row"]) == (
            digest,
            "executor_worktree.py remove",
            "H2-3c",
        ), call

    calls.clear()
    held = rig.create("AC-G.4", "rp-j", *ident)
    refuse.append(rp.Refusal("phase_state", "plan:active"))
    got = rig.call("remove", held)
    assert got == (1, ["worktree_bad:record:phase_state"]), f"AC-G.4: {got}"
    assert _listed(src, held) and held.is_dir(), "AC-G.4: a refused record removed it"
    refuse.clear()

    plain = rig.create("AC-G.4", "rp-k")
    assert rig.call("remove", plain) == (0, [f"worktree_removed:{plain.as_posix()}"])
    assert calls == [], f"AC-G.4: a worktree with no identity wrote records: {calls}"


def test_vec_v8_002_g4_templates_name_remove_path() -> None:
    """AC-G.4 — the closeout, the brief template and the preflight line name ``remove <path>``."""
    brief = (ROOT / ".agent/skills/claude-credits/templates/resume-brief.md").read_text(
        encoding="utf-8"
    )
    template = (ROOT / "templates/TASK-TEMPLATE.md").read_text(
        encoding="utf-8"
    )
    preflight = (ROOT / ".agent/skills/terminal-preflight/SKILL.md").read_text(
        encoding="utf-8"
    )
    h2_3c = [line for line in template.splitlines() if line.startswith("| H2-3c |")]
    assert len(h2_3c) == 1, "AC-G.4: TASK-TEMPLATE has no single H2-3c row"
    for name, text in (("resume-brief", brief), ("H2-3c", h2_3c[0])):
        assert "executor_worktree.py remove <path>" in text, f"AC-G.4: {name}"
        assert "remove <slug>" not in text, f"AC-G.4: {name} names remove <slug>"
    for record in ("worktree_removal_started", "worktree_removed"):
        assert record in brief, f"AC-G.4: the brief does not name {record}"
    assert "never `rm`/`rmdir` a worktree" in brief, "AC-G.4: the brief has no rm rule"
    assert (
        "`rm -rf` takes a literal path; never `rm`/`rmdir` a worktree — use "
        "`tools/executor_worktree.py remove <path>`" in preflight
    ), "AC-G.4: the terminal-preflight line is missing"


def _msg() -> Any:
    """``credits_msg`` imports its sibling as ``credits_state``, as when it runs as a script."""
    tools = str(ROOT / "tools")
    if tools not in sys.path:
        sys.path.append(tools)
    return importlib.import_module("credits_msg")


@dataclass
class _Phase:
    """The ``PhaseRun`` members τ3 (``admit_step``) and τ4 (``worktree_proven``) read."""

    tree: Path
    run_id: str
    plan: str
    rp: Any
    prepared: dict[str, Any]

    def records(self) -> list[dict[str, Any]]:
        return [self.prepared]

    def head(self, repo: Path | None = None) -> str:
        return _git(repo or self.tree, "rev-parse", "HEAD").strip()

    def record(
        self, kind: str, payload: dict[str, Any], facts: dict[str, Any], op_id: str
    ) -> dict[str, Any]:
        return {"kind": kind, "payload": payload, "facts": facts, "op_id": op_id}


def test_vec_v8_001_g1_tau_facts_read_the_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-G.1 — τ3 ``path_free`` and τ4 read ``<parent>/<run_id>``; τ3 sees the old sibling."""
    rig = _rig(tmp_path, monkeypatch, capsys)
    msg = _msg()
    helper = msg.worktree_module()
    monkeypatch.setattr(helper, "WORKTREE_PARENT", rig.parent, raising=False)
    monkeypatch.setattr(helper, "GRANDFATHERED", frozenset(), raising=False)
    src = rig.src.resolve()
    run, op = "rp-run", "rp-run-exec"
    prepared: dict[str, Any] = {
        "to": "transition:prepared",
        "guard_result": "passed",
        "op_id": op,
        "payload": {"base": _git(src, "rev-parse", "HEAD").strip()},
    }
    rp = SimpleNamespace(
        resume_facts=lambda *a, **k: {"binding_active": True},
        authority_ok=lambda *a, **k: True,
    )
    phase = _Phase(tree=src, run_id=run, plan="plan-t", rp=rp, prepared=prepared)

    def path_free() -> object:
        return msg.admit_step(phase, prepared)["facts"]["path_free"]

    assert path_free() is True, "AC-G.1: τ3 sees a worktree that is not there"
    assert msg.worktree_proven(phase) is False
    legacy = src.parent / f"{src.name}-{run}"
    legacy.mkdir()
    assert path_free() is False, "AC-G.1: τ3 misses the legacy sibling"
    legacy.rmdir()

    wt = rig.create("AC-G.1", run, "--run-id", run, "--op", op, "--plan", "plan-t")
    assert wt == rig.parent / run
    assert path_free() is False, "AC-G.1: τ3 misses <parent>/<run_id>"
    assert msg.worktree_proven(phase) is True, "AC-G.1: τ4 does not find the worktree"
    phase.prepared = {**prepared, "op_id": "other-op"}
    assert msg.worktree_proven(phase) is False, "AC-G.1: τ4 ignores the op_id"
